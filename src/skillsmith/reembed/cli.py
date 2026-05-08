"""Re-embed pass: populate DuckDB ``fragment_embeddings`` from LadybugDB
``Fragment`` nodes.

The migration model separates ingest (graph writes to LadybugDB) from embedding
(vector writes to DuckDB). This CLI is the embedding half — it runs after
ingest and can be re-run safely: fragments whose ids already have DuckDB rows
are skipped.

Usage::

    python -m skillsmith.reembed                    # embed everything missing
    python -m skillsmith.reembed --limit 10         # cap work (testing)
    python -m skillsmith.reembed --skill-id <id>    # one skill only
    python -m skillsmith.reembed --force            # re-embed everything (delete + insert)

Retries: 3 attempts with 1s/2s/4s exponential backoff on transient LM Studio
failures (timeouts, 5xx). A hard failure after retries halts the run and
leaves already-embedded fragments in place (idempotency means the next run
picks up where this one stopped).
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from skillsmith.config import Settings, get_settings
from skillsmith.lm_client import (
    LMBadResponse,
    LMClientError,
    LMTimeout,
    LMUnavailable,
    OpenAICompatClient,
)
from skillsmith.storage.ladybug import LadybugStore
from skillsmith.storage.vector_store import (
    FragmentEmbedding,
    VectorStore,
    open_or_create,
)

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_USAGE = 1
EXIT_LLM = 2
EXIT_DB = 3

_RETRY_DELAYS = (1.0, 2.0, 4.0)
_TRANSIENT_ERRORS = (LMTimeout, LMUnavailable)


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FragmentNeedingEmbedding:
    """A Fragment node pulled from LadybugDB with its parent Skill metadata.

    The denormalized columns (``skill_id``, ``category``, ``fragment_type``)
    carry through to the DuckDB row so compose-time filtered search doesn't
    need a cross-engine join.
    """

    fragment_id: str
    content: str
    fragment_type: str
    skill_id: str
    category: str


@dataclass
class ReembedStats:
    discovered: int = 0
    skipped_already_present: int = 0
    embedded: int = 0
    failed: int = 0
    failures: list[tuple[str, str]] = field(default_factory=lambda: [])

    def log_summary(self) -> None:
        logger.info(
            "re-embed complete: discovered=%d skipped=%d embedded=%d failed=%d",
            self.discovered,
            self.skipped_already_present,
            self.embedded,
            self.failed,
        )
        for fid, err in self.failures[:10]:
            logger.warning("  ✗ %s: %s", fid, err)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


_DISCOVERY_CYPHER_ALL = """
MATCH (s:Skill)-[:CURRENT_VERSION]->(v:SkillVersion)-[:DECOMPOSES_TO]->(f:Fragment)
WHERE v.status = 'active' AND s.deprecated = false
RETURN f.fragment_id, f.content, f.fragment_type, s.skill_id, s.category
ORDER BY s.skill_id, f.sequence
"""

_DISCOVERY_CYPHER_SKILL = """
MATCH (s:Skill {skill_id: $skill_id})-[:CURRENT_VERSION]->(v:SkillVersion)
    -[:DECOMPOSES_TO]->(f:Fragment)
WHERE v.status = 'active' AND s.deprecated = false
RETURN f.fragment_id, f.content, f.fragment_type, s.skill_id, s.category
ORDER BY f.sequence
"""


def discover_unembedded_fragments(
    store: LadybugStore,
    vector_store: VectorStore,
    *,
    skill_id: str | None = None,
    force: bool = False,
) -> list[FragmentNeedingEmbedding]:
    """Pull Fragment nodes from LadybugDB; filter out those already in DuckDB.

    ``force=True`` returns every fragment regardless of DuckDB state — useful
    for "wipe and re-embed" scenarios (caller is expected to have called
    ``vector_store.delete_skill`` first, otherwise the primary-key constraint
    on fragment_embeddings will raise).
    """
    if skill_id is not None:
        rows = store.execute(_DISCOVERY_CYPHER_SKILL, {"skill_id": skill_id})
    else:
        rows = store.execute(_DISCOVERY_CYPHER_ALL)

    all_fragments = [
        FragmentNeedingEmbedding(
            fragment_id=str(row[0]),
            content=str(row[1]),
            fragment_type=str(row[2]),
            skill_id=str(row[3]),
            category=str(row[4]),
        )
        for row in rows
    ]

    if force:
        return all_fragments

    present = vector_store.fragment_ids_present([f.fragment_id for f in all_fragments])
    return [f for f in all_fragments if f.fragment_id not in present]


# ---------------------------------------------------------------------------
# Embedding with retry
# ---------------------------------------------------------------------------


def _embed_with_retry(
    embed_fn: Callable[[str], list[float]],
    content: str,
    *,
    delays: tuple[float, ...] = _RETRY_DELAYS,
) -> list[float]:
    """Call ``embed_fn(content)``; retry transient failures with backoff.

    Non-transient errors (``LMBadResponse``, unknown errors) fail fast — they
    indicate a real problem that retrying won't fix.
    """
    last_exc: LMClientError | None = None
    for attempt, delay in enumerate([0.0, *delays]):
        if delay > 0.0:
            time.sleep(delay)
        try:
            return embed_fn(content)
        except _TRANSIENT_ERRORS as exc:
            last_exc = exc
            logger.warning("embed transient failure (attempt %d): %s", attempt + 1, exc)
        except LMBadResponse:
            # Malformed response is not retry-able.
            raise
    raise last_exc if last_exc else LMClientError("embed failed after retries")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def reembed_fragments(
    fragments: list[FragmentNeedingEmbedding],
    *,
    embed_fn: Callable[[str], list[float]],
    vector_store: VectorStore,
    embedding_model: str,
) -> ReembedStats:
    """Embed each fragment and insert to DuckDB. Returns run stats.

    ``embed_fn`` takes a content string and returns a raw (non-normalized)
    vector. The vector_store normalizes on insert. Injected rather than
    hard-wired to the LM client so tests can pass a fake.
    """
    stats = ReembedStats(discovered=len(fragments))
    now = int(time.time())

    for frag in fragments:
        try:
            vec = _embed_with_retry(embed_fn, frag.content)
        except LMClientError as exc:
            stats.failed += 1
            stats.failures.append((frag.fragment_id, str(exc)))
            logger.error("failed %s: %s", frag.fragment_id, exc)
            continue
        except Exception as exc:  # pyright: ignore[reportBroadExceptionCaught]
            stats.failed += 1
            stats.failures.append((frag.fragment_id, f"unexpected: {exc}"))
            logger.error("unexpected error on %s: %s", frag.fragment_id, exc)
            continue

        try:
            vector_store.insert_embeddings(
                [
                    FragmentEmbedding(
                        fragment_id=frag.fragment_id,
                        embedding=vec,
                        skill_id=frag.skill_id,
                        category=frag.category,
                        fragment_type=frag.fragment_type,
                        embedded_at=now,
                        embedding_model=embedding_model,
                        prose=frag.content,
                    )
                ]
            )
        except Exception as exc:  # pyright: ignore[reportBroadExceptionCaught]
            stats.failed += 1
            stats.failures.append((frag.fragment_id, f"insert: {exc}"))
            logger.error("insert failed for %s: %s", frag.fragment_id, exc)
            continue

        stats.embedded += 1
        if stats.embedded % 10 == 0:
            logger.info("  embedded %d/%d", stats.embedded, stats.discovered)

    return stats


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------


def _duckdb_path(settings: Settings) -> Path:
    """Locate the DuckDB file. Derived from LadybugDB path's parent dir."""
    ladybug_path = Path(settings.ladybug_db_path)
    return ladybug_path.parent / "skills.duck"


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(
        prog="python -m skillsmith.reembed",
        description=(
            "Compute embeddings for LadybugDB fragments and write them to "
            "the DuckDB vector store. Idempotent on re-run."
        ),
    )
    parser.add_argument(
        "--skill-id",
        help="Only embed fragments for this skill_id (default: all skills)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Cap the number of fragments processed (after skip-filtering)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Delete existing embeddings for the scope and re-embed from scratch",
    )
    parser.add_argument(
        "--model",
        help="Override the embedding model id (default: runtime_embedding_model from config)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be embedded without calling LM Studio or writing DuckDB",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    model_id = args.model or settings.runtime_embedding_model
    duck_path = _duckdb_path(settings)
    Path(settings.ladybug_db_path).parent.mkdir(parents=True, exist_ok=True)

    with LadybugStore(settings.ladybug_db_path) as store, open_or_create(duck_path) as vs:
        # --force: clear scope first so the primary-key constraint doesn't trip.
        if args.force:
            if args.skill_id:
                n = vs.delete_skill(args.skill_id)
                logger.info("--force: deleted %d existing embeddings for %s", n, args.skill_id)
            else:
                # Full wipe: required when changing embedding models (dimension change
                # makes existing vectors incompatible with the new index).
                n = vs.count_embeddings()
                vs._conn.execute("DELETE FROM fragment_embeddings")  # pyright: ignore[reportPrivateUsage]
                logger.info("--force: deleted all %d existing embeddings for full reindex", n)

        fragments = discover_unembedded_fragments(
            store, vs, skill_id=args.skill_id, force=args.force
        )
        if args.limit is not None:
            fragments = fragments[: args.limit]

        logger.info(
            "discovered %d fragment(s) to embed (model=%s, target=%s)",
            len(fragments),
            model_id,
            duck_path,
        )

        if args.dry_run:
            for f in fragments[:20]:
                logger.info(
                    "  would embed: %s (%s, %s)", f.fragment_id, f.skill_id, f.fragment_type
                )
            if len(fragments) > 20:
                logger.info("  ... and %d more", len(fragments) - 20)
            return EXIT_OK

        if not fragments:
            logger.info("nothing to do — all fragments already embedded")
            return EXIT_OK

        with OpenAICompatClient(settings.runtime_embed_base_url) as client:

            def _embed(text: str) -> list[float]:
                vectors = client.embed(model=model_id, texts=[text])
                return vectors[0]

            stats = reembed_fragments(
                fragments,
                embed_fn=_embed,
                vector_store=vs,
                embedding_model=model_id,
            )

        stats.log_summary()
        if stats.embedded > 0:
            logger.info("rebuilding BM25 FTS index after embedding %d fragment(s)", stats.embedded)
            try:
                vs.rebuild_fts_index()
            except Exception as exc:  # noqa: BLE001 — FTS rebuild is best-effort
                # DuckDB FTS extension occasionally hits a DDL dependency race
                # on alternating drop/create cycles ("subject 'stopwords' has
                # been deleted"). Vector search continues to work; BM25 leg
                # silently degrades to empty results until the next successful
                # rebuild. Log and continue rather than crashing the CLI.
                logger.warning("FTS index rebuild failed (BM25 leg degraded): %s", exc)
        return EXIT_OK if stats.failed == 0 else EXIT_LLM


if __name__ == "__main__":
    sys.exit(main())
