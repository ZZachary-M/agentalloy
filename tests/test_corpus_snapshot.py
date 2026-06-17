"""Unit tests for agentalloy.corpus_snapshot (content hash + S3 tar round-trip).

S3 is exercised with a filesystem-backed fake client so no AWS account or
boto3 network call is needed — the test patches ``_s3_client``.
"""

from __future__ import annotations

import tarfile
from pathlib import Path

import pytest

from agentalloy import corpus_snapshot as cs


# --------------------------------------------------------------------------- #
# compute_corpus_hash
# --------------------------------------------------------------------------- #
def _make_packs(tmp_path: Path) -> Path:
    packs = tmp_path / "_packs"
    (packs / "python").mkdir(parents=True)
    (packs / "python" / "pack.yaml").write_text("name: python\nskills: [a, b]\n")
    (packs / "python" / "a.yaml").write_text("skill_id: a\n")
    (packs / "aws").mkdir()
    (packs / "aws" / "pack.yaml").write_text("name: aws\n")
    return packs


def test_hash_is_deterministic(tmp_path: Path) -> None:
    packs = _make_packs(tmp_path)
    h1 = cs.compute_corpus_hash(packs, "qwen3-embedding:0.6b")
    h2 = cs.compute_corpus_hash(packs, "qwen3-embedding:0.6b")
    assert h1 == h2
    assert len(h1) == 32


def test_hash_changes_when_pack_content_changes(tmp_path: Path) -> None:
    packs = _make_packs(tmp_path)
    before = cs.compute_corpus_hash(packs, "m")
    (packs / "python" / "a.yaml").write_text("skill_id: a\nedited: true\n")
    after = cs.compute_corpus_hash(packs, "m")
    assert before != after


def test_hash_changes_when_pack_added_or_removed(tmp_path: Path) -> None:
    packs = _make_packs(tmp_path)
    before = cs.compute_corpus_hash(packs, "m")
    (packs / "go").mkdir()
    (packs / "go" / "pack.yaml").write_text("name: go\n")
    assert cs.compute_corpus_hash(packs, "m") != before


def test_hash_changes_when_model_changes(tmp_path: Path) -> None:
    packs = _make_packs(tmp_path)
    assert cs.compute_corpus_hash(packs, "model-a") != cs.compute_corpus_hash(packs, "model-b")


def test_hash_changes_with_cache_format_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    packs = _make_packs(tmp_path)
    before = cs.compute_corpus_hash(packs, "m")
    monkeypatch.setattr(cs, "CACHE_FORMAT_VERSION", "999")
    assert cs.compute_corpus_hash(packs, "m") != before


# --------------------------------------------------------------------------- #
# corpus_root / s3_config_from_env / snapshot_key
# --------------------------------------------------------------------------- #
def test_corpus_root_shared_parent() -> None:
    root = cs.corpus_root(Path("/corpus/ladybug"), Path("/corpus/skills.duck"))
    assert root == Path("/corpus")


def test_corpus_root_refuses_filesystem_root() -> None:
    # No shared parent below "/" → refuse (would tar the whole disk).
    assert cs.corpus_root(Path("/ladybug"), Path("/skills.duck")) is None


def test_s3_config_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("S3_CORPUS_BUCKET", raising=False)
    assert cs.s3_config_from_env() is None
    monkeypatch.setenv("S3_CORPUS_BUCKET", "my-bucket")
    monkeypatch.delenv("S3_CORPUS_PREFIX", raising=False)
    assert cs.s3_config_from_env() == ("my-bucket", "skillsmith")
    monkeypatch.setenv("S3_CORPUS_PREFIX", "/custom/prefix/")
    assert cs.s3_config_from_env() == ("my-bucket", "custom/prefix")


def test_snapshot_key() -> None:
    assert cs.snapshot_key("skillsmith", "abc123") == "skillsmith/corpus-abc123.tar.gz"
    assert cs.snapshot_key("", "abc123") == "corpus-abc123.tar.gz"


# --------------------------------------------------------------------------- #
# Fake S3 + save/restore round-trip
# --------------------------------------------------------------------------- #
class _FakeS3:
    """Filesystem-backed stand-in for a boto3 S3 client."""

    def __init__(self, store_dir: Path) -> None:
        self.store = store_dir
        self.store.mkdir(parents=True, exist_ok=True)

    def _obj(self, bucket: str, key: str) -> Path:
        p = self.store / bucket / key
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def upload_file(self, local: str, bucket: str, key: str) -> None:
        import shutil

        shutil.copyfile(local, self._obj(bucket, key))

    def download_file(self, bucket: str, key: str, local: str) -> None:
        import shutil

        src = self._obj(bucket, key)
        if not src.exists():
            raise FileNotFoundError(f"no such key: s3://{bucket}/{key}")
        shutil.copyfile(src, local)


def _make_corpus(root: Path) -> None:
    (root / "ladybug").mkdir(parents=True)
    (root / "ladybug" / "graph.kz").write_bytes(b"kuzu-graph-bytes")
    (root / "skills.duck").write_bytes(b"duckdb-vector-bytes")


def test_save_then_restore_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeS3(tmp_path / "s3")
    monkeypatch.setattr(cs, "_s3_client", lambda: fake)

    root = tmp_path / "corpus"
    _make_corpus(root)
    key = cs.snapshot_key("skillsmith", "deadbeef")

    assert cs.save_corpus(root, "bucket", key) is True

    # Wipe the corpus, then restore it from the fake S3.
    import shutil

    shutil.rmtree(root)
    assert not root.exists()

    assert cs.restore_corpus(root, "bucket", key) is True
    assert (root / "ladybug" / "graph.kz").read_bytes() == b"kuzu-graph-bytes"
    assert (root / "skills.duck").read_bytes() == b"duckdb-vector-bytes"


def test_restore_returns_false_on_cache_miss(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeS3(tmp_path / "s3")
    monkeypatch.setattr(cs, "_s3_client", lambda: fake)
    root = tmp_path / "corpus"
    assert cs.restore_corpus(root, "bucket", "skillsmith/corpus-missing.tar.gz") is False


def test_restore_clears_stale_state_before_extract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeS3(tmp_path / "s3")
    monkeypatch.setattr(cs, "_s3_client", lambda: fake)
    root = tmp_path / "corpus"
    _make_corpus(root)
    key = cs.snapshot_key("p", "h")
    cs.save_corpus(root, "b", key)

    # Add a stale file not present in the snapshot; restore must remove it.
    (root / "stale.tmp").write_text("torn")
    assert cs.restore_corpus(root, "b", key) is True
    assert not (root / "stale.tmp").exists()
    assert (root / "skills.duck").exists()


def test_save_fail_open_when_client_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom() -> object:
        raise ImportError("boto3 not installed")

    monkeypatch.setattr(cs, "_s3_client", _boom)
    root = tmp_path / "corpus"
    _make_corpus(root)
    assert cs.save_corpus(root, "b", "k") is False  # logged, never raises


def test_restore_fail_open_when_client_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom() -> object:
        raise ImportError("boto3 not installed")

    monkeypatch.setattr(cs, "_s3_client", _boom)
    assert cs.restore_corpus(tmp_path / "corpus", "b", "k") is False


# --------------------------------------------------------------------------- #
# _safe_extract path-traversal guard
# --------------------------------------------------------------------------- #
def test_safe_extract_rejects_traversal(tmp_path: Path) -> None:
    evil = tmp_path / "evil.tar.gz"
    payload = tmp_path / "payload"
    payload.write_text("x")
    with tarfile.open(evil, "w:gz") as tar:
        tar.add(str(payload), arcname="../escape.txt")

    dest = tmp_path / "dest"
    dest.mkdir()
    with tarfile.open(evil, "r:gz") as tar, pytest.raises(ValueError, match="unsafe tar member"):
        cs._safe_extract(tar, dest)


def test_clear_dir_contents_keeps_root(tmp_path: Path) -> None:
    root = tmp_path / "mount"
    _make_corpus(root)
    cs._clear_dir_contents(root)
    assert root.exists()  # root itself survives (mount-point safe)
    assert not any(root.iterdir())
