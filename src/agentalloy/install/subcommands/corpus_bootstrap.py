"""``corpus-bootstrap`` subcommand — cache-aware one-shot corpus build.

This is the single entry point a container bootstrap calls to make the skill
corpus ready. It replaces the multi-line ``migrate && install-packs && reembed``
shell with a cache-first flow:

1. **Hash** the pack sources + embedding model into a content key.
2. **Restore** the matching snapshot from S3 (``S3_CORPUS_BUCKET``) if present —
   on a hit, the slow embed is skipped entirely and we return immediately.
3. **Build** otherwise: clean the corpus, then run ``migrate`` → ``install-packs``
   → ``reembed`` as isolated subprocesses (preserving the proven prod sequence;
   the separate ``reembed`` process is what actually embeds, because
   ``install-packs``' in-process reembed self-locks DuckDB).
4. **Save** the freshly-built corpus back to S3 (best-effort) so the *next*
   start is a fast restore.

Everything S3 is fail-open: no bucket configured, ``boto3`` missing, or any
transfer error degrades cleanly to a normal local build. With no
``S3_CORPUS_BUCKET`` set this command is behaviourally identical to the old
inline build (local dev, the test suite, and non-S3 deploys are unaffected).

Exit codes (per the install dispatcher convention):

* 0 — corpus ready (restored from cache, or built + embedded).
* 1 — built but embedding incomplete / unverified (corpus may be degraded).
* 2 — hard build failure (migrate / install-packs failed).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

from agentalloy import corpus_snapshot
from agentalloy.config import get_settings

STEP_NAME = "corpus-bootstrap"

# install-packs returns 4 when every pack is already installed (idempotent
# no-op) — tolerated, mirrors the prod bootstrap shell.
_INSTALL_PACKS_NOOP = 4


def add_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
) -> None:
    p: argparse.ArgumentParser = subparsers.add_parser(
        "corpus-bootstrap",
        help="Cache-aware one-shot corpus build (restore-from-S3 or build + save).",
        description=(
            "Make the skill corpus ready: restore a content-hash-matched "
            "snapshot from S3 if available, otherwise build it and save the "
            "snapshot for next time. S3 is optional + fail-open."
        ),
    )
    p.add_argument(
        "--packs",
        default="all",
        help="Packs to install when building (default: all).",
    )
    p.add_argument(
        "--no-cache",
        action="store_true",
        help="Skip S3 restore + save; always build locally.",
    )
    p.set_defaults(func=_run)


def _packs_dir() -> Path:
    """Directory containing the in-image pack manifests (``_packs/``)."""
    import agentalloy

    return Path(agentalloy.__file__).resolve().parent / "_packs"


def verify_corpus(ladybug_path: Path, duckdb_path: Path) -> bool:
    """Lightweight check that a corpus is materially present.

    Confirms the DuckDB store is a non-empty file and the Kùzu ``ladybug``
    store is present with content. Snapshots are only ever *saved* after a
    verified build, so presence is a sufficient gate on restore.

    Kùzu >=0.4 (we run 0.11) persists the database as a single FILE; older
    versions used a directory. Accept EITHER — requiring a directory rejected
    every modern single-file build, so a healthy corpus failed verify, the
    snapshot was never saved, and every pod start re-ran the full ~3h embed.
    """
    duck = Path(duckdb_path)
    lady = Path(ladybug_path)
    if not (duck.is_file() and duck.stat().st_size > 0):
        return False
    if lady.is_file():
        return lady.stat().st_size > 0
    if lady.is_dir():
        try:
            return any(lady.iterdir())
        except OSError:
            return False
    return False


def _run_step(args: list[str], label: str) -> int:
    """Run ``python -m <args>`` as an isolated subprocess; return its rc."""
    cmd = [sys.executable, "-m", *args]
    print(f"[{STEP_NAME}] {label}: {' '.join(cmd)}", file=sys.stderr, flush=True)
    proc = subprocess.run(cmd, check=False)  # noqa: S603 - fixed argv, no shell
    return proc.returncode


def _build(packs: str, ladybug_path: Path, duckdb_path: Path) -> int:
    """Clean + build the corpus via isolated subprocesses. Returns an rc.

    0 = built + embedded, 1 = built but reembed incomplete, 2 = hard failure.
    """
    # Clean any torn/empty corpus left by a prior failed start.
    corpus_snapshot._clear_dir_contents(Path(ladybug_path).parent)  # noqa: SLF001
    for stale in (Path(ladybug_path), Path(duckdb_path), Path(f"{duckdb_path}.wal")):
        if stale.is_dir():
            import shutil

            shutil.rmtree(stale, ignore_errors=True)
        elif stale.exists():
            stale.unlink(missing_ok=True)

    if _run_step(["agentalloy.migrate"], "migrate") != 0:
        print(f"[{STEP_NAME}] migrate FAILED — corpus schema not created", file=sys.stderr)
        return 2

    install_rc = _run_step(
        ["agentalloy.install", "install-packs", "--packs", packs, "--non-interactive"],
        "install-packs",
    )
    if install_rc not in (0, _INSTALL_PACKS_NOOP):
        print(f"[{STEP_NAME}] install-packs FAILED rc={install_rc}", file=sys.stderr)
        return 2

    # Separate process: install-packs' in-process bulk reembed self-locks
    # DuckDB; running reembed standalone (lock released) is what embeds.
    reembed_rc = _run_step(["agentalloy.install", "reembed"], "reembed")
    if reembed_rc != 0:
        print(
            f"[{STEP_NAME}] reembed exited rc={reembed_rc} — fragments may lack "
            "embeddings; vector retrieval will skip them",
            file=sys.stderr,
        )
        return 1
    return 0


def _run(args: argparse.Namespace) -> int:
    t0 = time.monotonic()
    settings = get_settings()
    ladybug_path = Path(settings.ladybug_db_path)
    duckdb_path = Path(settings.duckdb_path)
    model = settings.runtime_embedding_model

    s3 = None if args.no_cache else corpus_snapshot.s3_config_from_env()
    root = corpus_snapshot.corpus_root(ladybug_path, duckdb_path)
    corpus_hash: str | None = None
    key: str | None = None

    if s3 is not None and root is not None:
        bucket, prefix = s3
        try:
            corpus_hash = corpus_snapshot.compute_corpus_hash(_packs_dir(), model)
            key = corpus_snapshot.snapshot_key(prefix, corpus_hash)
        except Exception as exc:  # noqa: BLE001
            print(f"[{STEP_NAME}] hash failed ({exc}) — building without cache", file=sys.stderr)
            corpus_hash = key = None

        if key is not None:
            print(
                f"[{STEP_NAME}] cache key s3://{bucket}/{key} (model={model})",
                file=sys.stderr,
            )
            if corpus_snapshot.restore_corpus(root, bucket, key) and verify_corpus(
                ladybug_path, duckdb_path
            ):
                dt = int((time.monotonic() - t0) * 1000)
                print(
                    f"[{STEP_NAME}] RESTORED from cache in {dt}ms — skipping build",
                    file=sys.stderr,
                )
                return 0
            print(f"[{STEP_NAME}] cache miss/invalid — building", file=sys.stderr)
    elif s3 is None:
        print(f"[{STEP_NAME}] S3 cache disabled — local build", file=sys.stderr)
    else:  # root is None
        print(
            f"[{STEP_NAME}] corpus paths share no root ({ladybug_path}, {duckdb_path}) "
            "— caching off, local build",
            file=sys.stderr,
        )

    rc = _build(args.packs, ladybug_path, duckdb_path)
    dt = int((time.monotonic() - t0) * 1000)

    if rc == 0 and not verify_corpus(ladybug_path, duckdb_path):
        print(f"[{STEP_NAME}] build reported OK but corpus failed verify", file=sys.stderr)
        rc = 1

    if rc == 0:
        print(f"[{STEP_NAME}] BUILD COMPLETE + verified in {dt}ms", file=sys.stderr)
        if s3 is not None and root is not None and key is not None:
            corpus_snapshot.save_corpus(root, s3[0], key)
    else:
        print(
            f"[{STEP_NAME}] build finished rc={rc} in {dt}ms — NOT saving snapshot",
            file=sys.stderr,
        )
    return rc


def run(args: argparse.Namespace) -> int:
    """Public entry point for non-argparse callers."""
    return _run(args)
