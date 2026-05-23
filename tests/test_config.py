"""AC-4: config defaults applied when env vars missing; env-var values override."""

from __future__ import annotations

from pathlib import Path

import pytest

from skillsmith.config import Settings

_ENV_KEYS = (
    "RUNTIME_EMBED_BASE_URL",
    "LADYBUG_DB_PATH",
    "DUCKDB_PATH",
    "RUNTIME_EMBEDDING_MODEL",
)


def test_defaults_when_env_unset(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    # XDG_DATA_HOME is read per-instantiation via default_factory, so no
    # module reload is needed.
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "_xdg_data"))
    monkeypatch.chdir(tmp_path)
    s = Settings()
    assert s.runtime_embed_base_url == "http://localhost:11434"
    expected_corpus = str(tmp_path / "_xdg_data" / "skillsmith" / "corpus")
    assert s.ladybug_db_path == f"{expected_corpus}/ladybug"
    assert s.duckdb_path == f"{expected_corpus}/skills.duck"
    assert s.runtime_embedding_model == "qwen3-embedding:0.6b"


def test_env_overrides(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RUNTIME_EMBED_BASE_URL", "http://embed.internal:52625")
    monkeypatch.setenv("LADYBUG_DB_PATH", "/var/lib/ladybug")
    s = Settings()
    assert s.runtime_embed_base_url == "http://embed.internal:52625"
    assert s.ladybug_db_path == "/var/lib/ladybug"
