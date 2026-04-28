"""DuckDB-backed vector store for fragment embeddings + composition telemetry.

Single file per scope (``skills.duck``) holding both tables. Uses DuckDB's
built-in ``array_cosine_distance`` over ``FLOAT[1024]`` columns — not the
experimental VSS extension. Linear scan is <10ms at current corpus scale.

L2-normalization is enforced at write time so ``array_cosine_distance``
reduces to an inner product at query time. Callers pass raw embeddings;
the store normalizes before insert.

BM25 full-text search is available via ``search_bm25``, which uses DuckDB's
native FTS extension over the ``prose`` column. The FTS index is built once
on first open via ``open_or_create``.

Public API:
    - ``open_or_create(path) -> VectorStore``
    - ``VectorStore.insert_embeddings(items)``
    - ``VectorStore.search_similar(query_vec, *, category=None, fragment_type=None, k=10)``
    - ``VectorStore.search_bm25(query, *, categories=None, k=10)``
    - ``VectorStore.record_composition_trace(trace)``
    - ``l2_normalize(vec) -> list[float]`` — shared helper

Schema and semantics track v5.3 Agentic Coding Architecture §2.4 / §2.5.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

EMBEDDING_DIM = 1024
"""Vector dimensionality. Tied to ``qwen3-embedding:0.6b`` (1024-dim default).
Changing the model requires a schema migration and full corpus reindex —
DuckDB's ``FLOAT[1024]`` column type is dimension-fixed."""


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FragmentEmbedding:
    """A fragment's embedding vector plus the denormalized columns that make
    filtered vector search cheap (no cross-engine join on the hot path)."""

    fragment_id: str
    embedding: Sequence[float]  # raw; normalized on insert
    skill_id: str
    category: str
    fragment_type: str
    embedded_at: int  # unix epoch seconds
    embedding_model: str
    prose: str = ""  # raw fragment text; indexed for BM25


@dataclass(frozen=True)
class SimilarityHit:
    fragment_id: str
    skill_id: str
    distance: float  # cosine distance in [0, 2]; 0 = identical direction


@dataclass(frozen=True)
class BM25Hit:
    fragment_id: str
    score: float  # BM25 score; higher = more relevant


@dataclass(frozen=True)
class CompositionTrace:
    """One row in ``composition_traces``. Optional fields carry None into the
    DB column as SQL NULL. Schema per summary doc §2.4.2."""

    trace_id: str
    request_ts: int
    phase: str
    task_prompt: str
    status: str
    correlation_id: str | None = None
    category: str | None = None
    selected_fragment_ids: list[str] = field(default_factory=lambda: [])
    source_skill_ids: list[str] = field(default_factory=lambda: [])
    system_skill_ids: list[str] = field(default_factory=lambda: [])
    assembly_tier: str | None = None
    assembly_model: str | None = None
    retrieval_latency_ms: int | None = None
    assembly_latency_ms: int | None = None
    total_latency_ms: int | None = None
    error_code: str | None = None
    response_size_chars: int | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def l2_normalize(vec: Sequence[float]) -> list[float]:
    """Return the L2-normalized form of ``vec`` (unit Euclidean norm).

    Raises ``ValueError`` if ``vec`` is the zero vector (no defined direction).
    """
    norm_sq = sum(x * x for x in vec)
    if norm_sq == 0.0:
        raise ValueError("cannot L2-normalize the zero vector")
    norm = math.sqrt(norm_sq)
    return [x / norm for x in vec]


# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------


_SCHEMA_DDL = f"""
CREATE TABLE IF NOT EXISTS fragment_embeddings (
    fragment_id VARCHAR PRIMARY KEY,
    embedding FLOAT[{EMBEDDING_DIM}] NOT NULL,
    skill_id VARCHAR NOT NULL,
    category VARCHAR NOT NULL,
    fragment_type VARCHAR NOT NULL,
    embedded_at BIGINT NOT NULL,
    embedding_model VARCHAR NOT NULL,
    prose VARCHAR NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_frag_emb_skill ON fragment_embeddings(skill_id);
CREATE INDEX IF NOT EXISTS idx_frag_emb_category ON fragment_embeddings(category);
CREATE INDEX IF NOT EXISTS idx_frag_emb_type ON fragment_embeddings(fragment_type);

CREATE TABLE IF NOT EXISTS composition_traces (
    trace_id VARCHAR PRIMARY KEY,
    correlation_id VARCHAR,
    request_ts BIGINT NOT NULL,
    phase VARCHAR NOT NULL,
    category VARCHAR,
    task_prompt VARCHAR NOT NULL,
    selected_fragment_ids VARCHAR[],
    source_skill_ids VARCHAR[],
    system_skill_ids VARCHAR[],
    assembly_tier VARCHAR,
    assembly_model VARCHAR,
    retrieval_latency_ms INTEGER,
    assembly_latency_ms INTEGER,
    total_latency_ms INTEGER,
    status VARCHAR NOT NULL,
    error_code VARCHAR,
    response_size_chars INTEGER
);

CREATE INDEX IF NOT EXISTS idx_traces_ts ON composition_traces(request_ts);
CREATE INDEX IF NOT EXISTS idx_traces_phase ON composition_traces(phase);
CREATE INDEX IF NOT EXISTS idx_traces_status ON composition_traces(status);
"""

_FTS_SETUP_SQL = """
INSTALL fts;
LOAD fts;
"""

_FTS_INDEX_EXISTS_SQL = """
SELECT COUNT(*) FROM information_schema.tables
WHERE table_name = 'fts_main_fragment_embeddings_config'
"""

_FTS_CREATE_SQL = "PRAGMA create_fts_index('fragment_embeddings', 'fragment_id', 'prose');"


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class VectorStoreError(Exception):
    """Base for vector-store errors."""


class EmbeddingDimMismatch(VectorStoreError):
    """Raised when an embedding's length doesn't match ``EMBEDDING_DIM``."""


class VectorStore:
    """Thin wrapper over a DuckDB connection with the Skill API's schema.

    Not thread-safe — use one connection per process. DuckDB allows multiple
    reader processes against the same file but writer is exclusive.
    """

    def __init__(self, conn: duckdb.DuckDBPyConnection) -> None:
        self._conn = conn

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> VectorStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # -- embeddings ----------------------------------------------------------

    def insert_embeddings(self, items: Iterable[FragmentEmbedding]) -> int:
        """Batch insert. Normalizes at write time. Returns count inserted.

        Upsert semantics: ``fragment_id`` is the primary key, so re-inserting
        an existing id raises a DuckDB constraint error. Use ``delete_skill``
        before re-inserting if replacing a skill's fragments.
        """
        batch = list(items)
        if not batch:
            return 0
        for f in batch:
            if len(f.embedding) != EMBEDDING_DIM:
                raise EmbeddingDimMismatch(
                    f"fragment_id={f.fragment_id}: embedding has {len(f.embedding)} "
                    f"dimensions, expected {EMBEDDING_DIM}"
                )
        rows = [
            (
                f.fragment_id,
                l2_normalize(f.embedding),
                f.skill_id,
                f.category,
                f.fragment_type,
                f.embedded_at,
                f.embedding_model,
                f.prose,
            )
            for f in batch
        ]
        self._conn.executemany(
            """
            INSERT INTO fragment_embeddings
                (fragment_id, embedding, skill_id, category, fragment_type,
                 embedded_at, embedding_model, prose)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        return len(rows)

    def search_similar(
        self,
        query_vec: Sequence[float],
        *,
        categories: list[str] | None = None,
        fragment_types: list[str] | None = None,
        k: int = 10,
    ) -> list[SimilarityHit]:
        """Top-k cosine distance, with optional denormalized-column filters.

        ``query_vec`` is L2-normalized internally before comparison so cosine
        distance reduces to inner product regardless of what the caller passes.
        """
        if len(query_vec) != EMBEDDING_DIM:
            raise EmbeddingDimMismatch(
                f"query vector has {len(query_vec)} dimensions, expected {EMBEDDING_DIM}"
            )
        q = l2_normalize(query_vec)

        where_clauses: list[str] = []
        params: list[object] = [q]
        if categories:
            where_clauses.append("category = ANY(?)")
            params.append(categories)
        if fragment_types:
            where_clauses.append("fragment_type = ANY(?)")
            params.append(fragment_types)
        where = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        params.append(k)

        sql = f"""
            SELECT
                fragment_id,
                skill_id,
                array_cosine_distance(
                    embedding,
                    CAST(? AS FLOAT[{EMBEDDING_DIM}])
                ) AS distance
            FROM fragment_embeddings
            {where}
            ORDER BY distance
            LIMIT ?
        """
        rows = self._conn.execute(sql, params).fetchall()
        return [
            SimilarityHit(
                fragment_id=str(row[0]),
                skill_id=str(row[1]),
                distance=float(row[2]),
            )
            for row in rows
        ]

    def search_bm25(
        self,
        query: str,
        *,
        categories: list[str] | None = None,
        k: int = 10,
    ) -> list[BM25Hit]:
        """BM25 full-text search over the prose column.

        Returns up to ``k`` results ordered by descending BM25 score.
        Only fragments with a non-null score (i.e. at least one query token
        matched) are returned. Returns empty list if the FTS index is not
        available or query is empty.
        """
        if not query.strip():
            return []

        try:
            where_clauses: list[str] = ["score IS NOT NULL"]
            params: list[object] = [query]
            if categories:
                where_clauses.append("category = ANY(?)")
                params.append(categories)
            params.append(k)

            where = " AND ".join(where_clauses)
            sql = f"""
                SELECT score, fragment_id FROM (
                    SELECT *,
                        fts_main_fragment_embeddings.match_bm25(
                            fragment_id, ?, fields := 'prose'
                        ) AS score
                    FROM fragment_embeddings
                )
                WHERE {where}
                ORDER BY score DESC
                LIMIT ?
            """
            rows = self._conn.execute(sql, params).fetchall()
        except Exception:  # noqa: BLE001 — FTS unavailable or index not built
            return []

        return [BM25Hit(fragment_id=str(row[1]), score=float(row[0])) for row in rows]

    def rebuild_fts_index(self) -> None:
        """Drop (if present) and recreate the FTS index on the prose column.

        Note: DuckDB's FTS extension hits a DDL dependency race on alternating
        drop+create cycles across separate processes ("subject 'stopwords' has
        been deleted"). The CHECKPOINT helps within a single session but does
        not fully eliminate the cross-process race. Callers should treat
        rebuild failures as non-fatal — vector search continues to work and
        the BM25 leg silently returns empty until the next successful rebuild.
        """
        import contextlib

        with contextlib.suppress(Exception):
            self._conn.execute("PRAGMA drop_fts_index('fragment_embeddings');")
        self._conn.execute("CHECKPOINT;")
        self._conn.execute(_FTS_CREATE_SQL)

    def count_embeddings(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM fragment_embeddings").fetchone()
        return int(row[0]) if row else 0

    def embedding_dim(self) -> int | None:
        """Return the dimension of stored embeddings, or None if the corpus is empty.

        Used by install-pack to hard-block dim-mismatched packs before they
        corrupt the vector store. Reads one non-null embedding and measures
        its length — DuckDB doesn't enforce a fixed length on FLOAT[] columns,
        so the corpus's "dim" is whatever was first written.
        """
        row = self._conn.execute(
            "SELECT len(embedding) FROM fragment_embeddings "
            "WHERE embedding IS NOT NULL LIMIT 1"
        ).fetchone()
        return int(row[0]) if row else None

    def fragment_ids_present(self, fragment_ids: Sequence[str]) -> set[str]:
        """Return the subset of ``fragment_ids`` that already have embeddings.
        Useful for idempotent re-embed runs (skip what's already done)."""
        if not fragment_ids:
            return set()
        rows = self._conn.execute(
            "SELECT fragment_id FROM fragment_embeddings WHERE fragment_id = ANY(?)",
            [list(fragment_ids)],
        ).fetchall()
        return {str(row[0]) for row in rows}

    def delete_skill(self, skill_id: str) -> int:
        """Remove all fragment embeddings for a skill. Returns rows deleted."""
        before = self.count_embeddings()
        self._conn.execute("DELETE FROM fragment_embeddings WHERE skill_id = ?", [skill_id])
        return before - self.count_embeddings()

    # -- telemetry -----------------------------------------------------------

    def record_composition_trace(self, trace: CompositionTrace) -> None:
        """Insert a composition trace row. Callers should wrap in try/except
        so telemetry failures never propagate to the caller of /compose."""
        self._conn.execute(
            """
            INSERT INTO composition_traces (
                trace_id, correlation_id, request_ts, phase, category,
                task_prompt, selected_fragment_ids, source_skill_ids,
                system_skill_ids, assembly_tier, assembly_model,
                retrieval_latency_ms, assembly_latency_ms, total_latency_ms,
                status, error_code, response_size_chars
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                trace.trace_id,
                trace.correlation_id,
                trace.request_ts,
                trace.phase,
                trace.category,
                trace.task_prompt,
                trace.selected_fragment_ids,
                trace.source_skill_ids,
                trace.system_skill_ids,
                trace.assembly_tier,
                trace.assembly_model,
                trace.retrieval_latency_ms,
                trace.assembly_latency_ms,
                trace.total_latency_ms,
                trace.status,
                trace.error_code,
                trace.response_size_chars,
            ],
        )

    def count_traces(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM composition_traces").fetchone()
        return int(row[0]) if row else 0


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def _fts_index_exists(conn: duckdb.DuckDBPyConnection) -> bool:
    row = conn.execute(_FTS_INDEX_EXISTS_SQL).fetchone()
    return bool(row and row[0] > 0)


def open_or_create(path: str | Path) -> VectorStore:
    """Open (or create) the DuckDB vector store at ``path``.

    Creates parent directories if missing. Idempotent: applies schema DDL on
    every open. Builds the BM25 FTS index on first open (or when missing).
    Use as a context manager to guarantee connection close.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(p))
    conn.execute(_SCHEMA_DDL)

    try:
        conn.execute(_FTS_SETUP_SQL)
        if not _fts_index_exists(conn):
            conn.execute(_FTS_CREATE_SQL)
    except Exception:  # noqa: BLE001 — FTS extension unavailable; BM25 leg silently degrades
        pass

    return VectorStore(conn)
