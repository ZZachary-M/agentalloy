"""Content-hash S3 snapshot/restore for the built skill corpus.

The corpus (Kùzu ``ladybug`` graph + DuckDB ``skills.duck`` vector store) is a
deterministic function of the packs that ship in-image (``_packs/``) and the
embedding model. Embedding ~3k fragments through a CPU embedder is the slow
part of bootstrap, and it is wasted work to redo it on every pod start when the
inputs have not changed.

This module computes a content hash over the pack sources + model + cache
format version, and tars / uploads the *built* corpus to S3 keyed by that hash.
On a subsequent start with the same inputs, the snapshot is downloaded and
extracted instead of rebuilding — turning a minutes-long embed into a
seconds-long download.

S3 is **optional and fail-open**:

* ``boto3`` is imported lazily, only inside the transfer helpers.
* If ``S3_CORPUS_BUCKET`` is unset, ``boto3`` is missing, or any transfer
  errors, the helpers return ``False`` (or ``None``) and the caller falls back
  to a normal local build. A deploy without S3 — and local dev / the test
  suite — behave exactly as before.

The orchestration that ties restore → build → save together lives in
``agentalloy.install.subcommands.corpus_bootstrap``; this module is pure I/O so
it can be unit-tested without a live AWS account.
"""

from __future__ import annotations

import hashlib
import logging
import os
import tarfile
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = [
    "CACHE_FORMAT_VERSION",
    "compute_corpus_hash",
    "corpus_root",
    "restore_corpus",
    "s3_config_from_env",
    "save_corpus",
    "snapshot_key",
]

# Bump to invalidate every existing snapshot (e.g. if the on-disk corpus
# layout or the tar format changes in a way the hash would not otherwise
# capture). Part of the hash input, so a bump simply produces new keys.
CACHE_FORMAT_VERSION = "1"

# Cap the number of pack files folded into the hash defensively — the pack
# tree is ~370 small files, so this is a sanity bound, not a real limit.
_MAX_HASH_FILES = 50_000


def compute_corpus_hash(packs_dir: Path, model: str) -> str:
    """Return a stable hex digest identifying a corpus build.

    The digest folds in, in deterministic order:

    * every file under ``packs_dir`` (posix relpath + sha256 of its bytes),
    * the embedding ``model`` name (dim is a function of the model),
    * ``CACHE_FORMAT_VERSION``.

    Any pack content change, an added/removed pack file, or a model swap
    yields a different digest — and therefore a cache miss + rebuild.
    """
    packs_dir = Path(packs_dir)
    files: list[Path] = sorted(
        (p for p in packs_dir.rglob("*") if p.is_file()),
        key=lambda p: p.relative_to(packs_dir).as_posix(),
    )
    if len(files) > _MAX_HASH_FILES:  # pragma: no cover - defensive
        raise ValueError(f"refusing to hash {len(files)} files under {packs_dir}")

    outer = hashlib.sha256()
    for f in files:
        rel = f.relative_to(packs_dir).as_posix()
        inner = hashlib.sha256()
        with f.open("rb") as fh:
            for chunk in iter(lambda fh=fh: fh.read(65536), b""):
                inner.update(chunk)
        outer.update(rel.encode("utf-8"))
        outer.update(b"\0")
        outer.update(inner.hexdigest().encode("ascii"))
        outer.update(b"\n")
    outer.update(f"model={model}\n".encode())
    outer.update(f"format={CACHE_FORMAT_VERSION}\n".encode("ascii"))
    # 32 hex chars (128 bits) is ample to avoid collisions for a handful of
    # builds while keeping the S3 key short and readable.
    return outer.hexdigest()[:32]


def corpus_root(ladybug_path: Path, duckdb_path: Path) -> Path | None:
    """Return the shared parent directory of the two corpus stores.

    Both stores live under one corpus root in every real configuration
    (prod: ``/corpus/{ladybug,skills.duck}``; default XDG:
    ``…/agentalloy/corpus/{ladybug,skills.duck}``). The snapshot tars and
    restores this whole root. Returns ``None`` when the two paths do not
    share a sensible common root (caller then skips caching and builds).
    """
    try:
        common = Path(os.path.commonpath([str(Path(ladybug_path)), str(Path(duckdb_path))]))
    except ValueError:
        # Different drives / no common path (e.g. relative vs absolute).
        return None
    # A common path equal to the filesystem root ("/") would mean tarring the
    # whole disk — refuse and fall back to build.
    if common == common.parent:
        return None
    return common


def s3_config_from_env() -> tuple[str, str] | None:
    """Return ``(bucket, prefix)`` from env, or ``None`` when caching is off.

    Reads ``S3_CORPUS_BUCKET`` (required to enable caching) and
    ``S3_CORPUS_PREFIX`` (default ``skillsmith``). The prefix is normalised
    to have no leading/trailing slashes.
    """
    bucket = (os.environ.get("S3_CORPUS_BUCKET") or "").strip()
    if not bucket:
        return None
    prefix = (os.environ.get("S3_CORPUS_PREFIX") or "skillsmith").strip().strip("/")
    return bucket, prefix


def snapshot_key(prefix: str, corpus_hash: str) -> str:
    """S3 object key for a corpus snapshot tarball."""
    prefix = prefix.strip("/")
    return f"{prefix}/corpus-{corpus_hash}.tar.gz" if prefix else f"corpus-{corpus_hash}.tar.gz"


def _s3_client():  # noqa: ANN202 - boto3 client, lazily typed
    """Build a boto3 S3 client. Raises ImportError if boto3 is absent."""
    import boto3  # lazy: keeps boto3 out of the base import path

    region = os.environ.get("AWS_REGION") or "us-east-1"
    return boto3.client("s3", region_name=region)


def _clear_dir_contents(root: Path) -> None:
    """Remove everything *inside* ``root`` without removing ``root`` itself.

    ``root`` is often a volume mount point (prod ``/corpus`` emptyDir), so
    ``rmtree(root)`` would fail with EBUSY on the final ``rmdir``. Clearing
    the contents avoids that while still wiping any torn prior state.
    """
    import contextlib
    import shutil

    if not root.is_dir():
        return
    for child in root.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child, ignore_errors=True)
        else:
            with contextlib.suppress(OSError):
                child.unlink()


def _safe_extract(tar: tarfile.TarFile, dest: Path) -> None:
    """Extract ``tar`` into ``dest``, rejecting members that escape ``dest``.

    Guards against path-traversal in tar members even though we author the
    tarballs ourselves (defence in depth).
    """
    dest = dest.resolve()
    for member in tar.getmembers():
        target = (dest / member.name).resolve()
        if dest != target and dest not in target.parents:
            raise ValueError(f"unsafe tar member outside dest: {member.name!r}")
    # filter="data" (py3.12+) adds stdlib hardening — rejects absolute paths,
    # traversal, and special files — on top of the explicit check above, and
    # makes the call forward-compatible with the py3.14 default.
    tar.extractall(dest, filter="data")  # noqa: S202 - members validated + data filter


def save_corpus(root: Path, bucket: str, key: str) -> bool:
    """Tar ``root`` and upload it to ``s3://bucket/key``.

    Best-effort: returns ``True`` on success, ``False`` (logged) on any
    failure. Never raises — a failed save must not fail the boot.
    """
    root = Path(root)
    if not root.exists():
        logger.warning("corpus_snapshot: save skipped — root %s does not exist", root)
        return False
    try:
        client = _s3_client()
    except Exception as exc:  # noqa: BLE001
        logger.warning("corpus_snapshot: save skipped — S3 client unavailable: %s", exc)
        return False
    try:
        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            with tarfile.open(tmp_path, "w:gz") as tar:
                # arcname = root.name so the archive contains "<root>/…" and a
                # restore into root.parent recreates the exact layout.
                tar.add(str(root), arcname=root.name)
            client.upload_file(str(tmp_path), bucket, key)
        finally:
            tmp_path.unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("corpus_snapshot: upload to s3://%s/%s failed: %s", bucket, key, exc)
        return False
    logger.info("corpus_snapshot: saved corpus snapshot to s3://%s/%s", bucket, key)
    return True


def restore_corpus(root: Path, bucket: str, key: str) -> bool:
    """Download ``s3://bucket/key`` and extract it so ``root`` is recreated.

    Returns ``True`` only when the object existed and extracted cleanly.
    A missing object (cache miss) or any error returns ``False`` (logged at
    debug for the common miss case) so the caller builds from scratch.
    The existing ``root`` is removed first so a torn prior state cannot mix
    with the restored corpus.
    """
    root = Path(root)
    try:
        client = _s3_client()
    except Exception as exc:  # noqa: BLE001
        logger.warning("corpus_snapshot: restore skipped — S3 client unavailable: %s", exc)
        return False
    try:
        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            try:
                client.download_file(bucket, key, str(tmp_path))
            except Exception as exc:  # noqa: BLE001 - typically a cache miss (404)
                logger.info("corpus_snapshot: no snapshot at s3://%s/%s (%s)", bucket, key, exc)
                return False
            # Clear any torn prior state inside root (not root itself — it
            # may be a mount point), then extract the snapshot. The archive
            # is namespaced under root.name, so extracting into root.parent
            # recreates "<root>/ladybug" + "<root>/skills.duck".
            _clear_dir_contents(root)
            root.parent.mkdir(parents=True, exist_ok=True)
            with tarfile.open(tmp_path, "r:gz") as tar:
                _safe_extract(tar, root.parent)
        finally:
            tmp_path.unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("corpus_snapshot: restore from s3://%s/%s failed: %s", bucket, key, exc)
        return False
    if not root.exists():
        logger.warning("corpus_snapshot: restore extracted but %s missing — building", root)
        return False
    logger.info("corpus_snapshot: restored corpus snapshot from s3://%s/%s", bucket, key)
    return True
