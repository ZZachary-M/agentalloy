"""Tests for the corpus-bootstrap subcommand (restore/build/save orchestration).

Subprocess steps (migrate / install-packs / reembed) and S3 transfers are
patched so the orchestration logic is tested in isolation — no real corpus
build, no AWS.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agentalloy import corpus_snapshot as cs
from agentalloy.install.subcommands import corpus_bootstrap as cb


def _args(**kw: object) -> argparse.Namespace:
    ns = argparse.Namespace(packs="all", no_cache=False)
    for k, v in kw.items():
        setattr(ns, k, v)
    return ns


def _settings(root: Path):
    class _S:
        ladybug_db_path = str(root / "ladybug")
        duckdb_path = str(root / "skills.duck")
        runtime_embedding_model = "qwen3-embedding:0.6b"

    return _S()


def _materialize(root: Path) -> None:
    """Create a plausible on-disk corpus (what a real build would leave)."""
    (root / "ladybug").mkdir(parents=True, exist_ok=True)
    (root / "ladybug" / "graph.kz").write_bytes(b"g")
    (root / "skills.duck").write_bytes(b"d")


# --------------------------------------------------------------------------- #
# verify_corpus
# --------------------------------------------------------------------------- #
def test_verify_corpus_true_when_present(tmp_path: Path) -> None:
    _materialize(tmp_path)
    assert cb.verify_corpus(tmp_path / "ladybug", tmp_path / "skills.duck") is True


def test_verify_corpus_false_when_duck_missing(tmp_path: Path) -> None:
    (tmp_path / "ladybug").mkdir()
    (tmp_path / "ladybug" / "g").write_bytes(b"g")
    assert cb.verify_corpus(tmp_path / "ladybug", tmp_path / "skills.duck") is False


def test_verify_corpus_false_when_duck_empty(tmp_path: Path) -> None:
    (tmp_path / "ladybug").mkdir()
    (tmp_path / "ladybug" / "g").write_bytes(b"g")
    (tmp_path / "skills.duck").write_bytes(b"")  # zero bytes
    assert cb.verify_corpus(tmp_path / "ladybug", tmp_path / "skills.duck") is False


def test_verify_corpus_false_when_ladybug_empty(tmp_path: Path) -> None:
    (tmp_path / "ladybug").mkdir()
    (tmp_path / "skills.duck").write_bytes(b"d")
    assert cb.verify_corpus(tmp_path / "ladybug", tmp_path / "skills.duck") is False


# --------------------------------------------------------------------------- #
# _run — restore hit short-circuits the build
# --------------------------------------------------------------------------- #
def test_restore_hit_skips_build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "corpus"
    monkeypatch.setattr(cb, "get_settings", lambda: _settings(root))
    monkeypatch.setenv("S3_CORPUS_BUCKET", "bucket")
    monkeypatch.setattr(cb, "_packs_dir", lambda: tmp_path)  # any dir → hashable

    def _fake_restore(r: Path, bucket: str, key: str) -> bool:
        _materialize(Path(r))  # simulate a successful extract
        return True

    monkeypatch.setattr(cs, "restore_corpus", _fake_restore)

    build_called = {"n": 0}
    monkeypatch.setattr(cb, "_build", lambda *a, **k: build_called.__setitem__("n", build_called["n"] + 1) or 0)
    save_called = {"n": 0}
    monkeypatch.setattr(cs, "save_corpus", lambda *a, **k: save_called.__setitem__("n", save_called["n"] + 1) or True)

    rc = cb._run(_args())
    assert rc == 0
    assert build_called["n"] == 0  # build skipped
    assert save_called["n"] == 0  # nothing to re-save on a hit


def test_cache_miss_builds_then_saves(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "corpus"
    monkeypatch.setattr(cb, "get_settings", lambda: _settings(root))
    monkeypatch.setenv("S3_CORPUS_BUCKET", "bucket")
    monkeypatch.setattr(cb, "_packs_dir", lambda: tmp_path)
    monkeypatch.setattr(cs, "restore_corpus", lambda *a, **k: False)  # miss

    def _fake_build(packs: str, lady: Path, duck: Path) -> int:
        _materialize(root)
        return 0

    monkeypatch.setattr(cb, "_build", _fake_build)
    saved = {"key": None}
    monkeypatch.setattr(cs, "save_corpus", lambda r, b, key: saved.__setitem__("key", key) or True)

    rc = cb._run(_args())
    assert rc == 0
    assert saved["key"] is not None and saved["key"].startswith("skillsmith/corpus-")


def test_no_bucket_builds_without_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "corpus"
    monkeypatch.setattr(cb, "get_settings", lambda: _settings(root))
    monkeypatch.delenv("S3_CORPUS_BUCKET", raising=False)

    restore_called = {"n": 0}
    monkeypatch.setattr(cs, "restore_corpus", lambda *a, **k: restore_called.__setitem__("n", 1) or False)
    save_called = {"n": 0}
    monkeypatch.setattr(cs, "save_corpus", lambda *a, **k: save_called.__setitem__("n", 1) or True)
    monkeypatch.setattr(cb, "_build", lambda *a, **k: _materialize(root) or 0)

    rc = cb._run(_args())
    assert rc == 0
    assert restore_called["n"] == 0  # never tried S3
    assert save_called["n"] == 0  # never saved


def test_reembed_failure_returns_1_and_skips_save(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "corpus"
    monkeypatch.setattr(cb, "get_settings", lambda: _settings(root))
    monkeypatch.setenv("S3_CORPUS_BUCKET", "bucket")
    monkeypatch.setattr(cb, "_packs_dir", lambda: tmp_path)
    monkeypatch.setattr(cs, "restore_corpus", lambda *a, **k: False)
    # build returns 1 (reembed incomplete) but still leaves files on disk
    monkeypatch.setattr(cb, "_build", lambda *a, **k: _materialize(root) or 1)
    save_called = {"n": 0}
    monkeypatch.setattr(cs, "save_corpus", lambda *a, **k: save_called.__setitem__("n", 1) or True)

    rc = cb._run(_args())
    assert rc == 1
    assert save_called["n"] == 0  # never save a degraded corpus


def test_build_ok_but_verify_fails_downgrades_to_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "corpus"
    monkeypatch.setattr(cb, "get_settings", lambda: _settings(root))
    monkeypatch.delenv("S3_CORPUS_BUCKET", raising=False)
    # build claims success (rc 0) but writes nothing → verify fails
    monkeypatch.setattr(cb, "_build", lambda *a, **k: 0)
    rc = cb._run(_args())
    assert rc == 1


# --------------------------------------------------------------------------- #
# _build — subprocess sequencing (steps patched)
# --------------------------------------------------------------------------- #
def test_build_tolerates_install_packs_noop_exit4(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def _fake_step(args: list[str], label: str) -> int:
        calls.append(label)
        return 4 if label == "install-packs" else 0

    monkeypatch.setattr(cb, "_run_step", _fake_step)
    rc = cb._build("all", tmp_path / "ladybug", tmp_path / "skills.duck")
    assert rc == 0
    assert calls == ["migrate", "install-packs", "reembed"]


def test_build_migrate_failure_returns_2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cb, "_run_step", lambda args, label: 1 if label == "migrate" else 0)
    rc = cb._build("all", tmp_path / "ladybug", tmp_path / "skills.duck")
    assert rc == 2


def test_build_install_packs_hard_failure_returns_2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cb, "_run_step", lambda args, label: 1 if label == "install-packs" else 0)
    rc = cb._build("all", tmp_path / "ladybug", tmp_path / "skills.duck")
    assert rc == 2


def test_build_reembed_failure_returns_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cb, "_run_step", lambda args, label: 5 if label == "reembed" else 0)
    rc = cb._build("all", tmp_path / "ladybug", tmp_path / "skills.duck")
    assert rc == 1
