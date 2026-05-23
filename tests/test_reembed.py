"""Tests for reembed CLI and vector_store FTS rebuild retry."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from skillsmith.reembed.cli import (
    EXIT_OK,
)
from skillsmith.reembed.cli import (
    main as reembed_main,
)
from skillsmith.storage.vector_store import VectorStore

# ---------------------------------------------------------------------------
# --rebuild-fts flag
# ---------------------------------------------------------------------------


def test_rebuild_fts_flag_accepted() -> None:
    """--rebuild-fts is accepted as valid CLI (dry-run mode)."""
    with (
        patch("skillsmith.reembed.cli.get_settings") as mock_settings,
        patch("skillsmith.reembed.cli.LadybugStore") as mock_store_cls,
        patch("skillsmith.reembed.cli.open_or_create") as mock_vs_cls,
    ):
        mock_settings.return_value.ladybug_db_path = "/tmp/test/ladybug.db"
        mock_settings.return_value.runtime_embedding_model = "test-model"

        mock_store = MagicMock()
        mock_store_cls.return_value.__enter__ = MagicMock(return_value=mock_store)
        mock_store_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_store.execute.return_value = []

        mock_vs = MagicMock()
        mock_vs_cls.return_value.__enter__ = MagicMock(return_value=mock_vs)
        mock_vs_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_vs.count_embeddings.return_value = 0
        mock_vs.fragment_ids_present.return_value = set()

        # dry-run should exit OK with --rebuild-fts
        code = reembed_main(["--rebuild-fts", "--dry-run"])
        assert code == EXIT_OK


def test_rebuild_fts_runs_when_zero_fragments(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """--rebuild-fts triggers rebuild_fts_index when fragments is empty."""
    # Mock the LadybugStore and vector_store so we can control discovery
    with (
        patch("skillsmith.reembed.cli.LadybugStore") as mock_store_cls,
        patch("skillsmith.reembed.cli.open_or_create") as mock_vs_cls,
        patch("skillsmith.reembed.cli.get_settings") as mock_settings,
    ):
        mock_settings.return_value.ladybug_db_path = str(tmp_path / "ladybug.db")
        mock_settings.return_value.runtime_embedding_model = "test-model"

        # Mock LadybugStore context manager
        mock_store = MagicMock()
        mock_store_cls.return_value.__enter__ = MagicMock(return_value=mock_store)
        mock_store_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_store.execute.return_value = []  # no fragments

        # Mock VectorStore context manager
        mock_vs = MagicMock()
        mock_vs_cls.return_value.__enter__ = MagicMock(return_value=mock_vs)
        mock_vs_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_vs.count_embeddings.return_value = 100
        mock_vs.fragment_ids_present.return_value = set()

        with caplog.at_level(logging.INFO):
            code = reembed_main(["--rebuild-fts"])

        assert code == EXIT_OK
        mock_vs.rebuild_fts_index.assert_called_once()
        assert "running --rebuild-fts only" in caplog.text or "rebuild-fts requested" in caplog.text


def test_no_rebuild_without_flag_when_zero_fragments(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Without --rebuild-fts, rebuild_fts_index is NOT called when fragments is empty."""
    with (
        patch("skillsmith.reembed.cli.LadybugStore") as mock_store_cls,
        patch("skillsmith.reembed.cli.open_or_create") as mock_vs_cls,
        patch("skillsmith.reembed.cli.get_settings") as mock_settings,
    ):
        mock_settings.return_value.ladybug_db_path = str(tmp_path / "ladybug.db")
        mock_settings.return_value.runtime_embedding_model = "test-model"

        mock_store = MagicMock()
        mock_store_cls.return_value.__enter__ = MagicMock(return_value=mock_store)
        mock_store_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_store.execute.return_value = []  # no fragments

        mock_vs = MagicMock()
        mock_vs_cls.return_value.__enter__ = MagicMock(return_value=mock_vs)
        mock_vs_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_vs.count_embeddings.return_value = 100
        mock_vs.fragment_ids_present.return_value = set()

        with caplog.at_level(logging.INFO):
            code = reembed_main([])

        assert code == EXIT_OK
        mock_vs.rebuild_fts_index.assert_not_called()
        assert "nothing to do" in caplog.text


def test_rebuild_fts_exit_ok_on_failure(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """When rebuild_fts_index raises, exit code is still EXIT_OK."""
    with (
        patch("skillsmith.reembed.cli.LadybugStore") as mock_store_cls,
        patch("skillsmith.reembed.cli.open_or_create") as mock_vs_cls,
        patch("skillsmith.reembed.cli.get_settings") as mock_settings,
    ):
        mock_settings.return_value.ladybug_db_path = str(tmp_path / "ladybug.db")
        mock_settings.return_value.runtime_embedding_model = "test-model"

        mock_store = MagicMock()
        mock_store_cls.return_value.__enter__ = MagicMock(return_value=mock_store)
        mock_store_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_store.execute.return_value = []

        mock_vs = MagicMock()
        mock_vs_cls.return_value.__enter__ = MagicMock(return_value=mock_vs)
        mock_vs_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_vs.count_embeddings.return_value = 100
        mock_vs.fragment_ids_present.return_value = set()
        mock_vs.rebuild_fts_index.side_effect = Exception("stopwords has been deleted")

        with caplog.at_level(logging.WARNING):
            code = reembed_main(["--rebuild-fts"])

        assert code == EXIT_OK
        assert "BM25 leg degraded" in caplog.text
        assert "rebuild-fts" in caplog.text  # remediation hint


# ---------------------------------------------------------------------------
# VectorStore.rebuild_fts_index retry
# ---------------------------------------------------------------------------


def test_rebuild_fts_retry_on_stopwords_error(tmp_path: Path) -> None:
    """rebuild_fts_index retries once on the stopwords catalog race."""
    conn = MagicMock()
    create_count = 0

    def mock_execute(sql: str, *a: object, **kw: object) -> None:
        nonlocal create_count
        if "create_fts_index" in sql:
            create_count += 1
            if create_count == 1:
                raise Exception("subject 'stopwords' has been deleted")
        # drop_fts_index, CHECKPOINT, second create: all succeed
        return None

    conn.execute = mock_execute
    vs = VectorStore(conn)  # type: ignore[arg-type]

    # Patch time.sleep so the retry path doesn't actually sleep
    with patch("time.sleep"):
        # Should not raise - retry succeeds
        vs.rebuild_fts_index()

    # Verify create_fts_index was attempted twice
    assert create_count == 2


def test_rebuild_fts_no_retry_on_non_transient_error(tmp_path: Path) -> None:
    """rebuild_fts_index does NOT retry non-transient errors."""
    conn = MagicMock()
    create_count = 0

    def mock_execute(sql: str, *a: object, **kw: object) -> None:
        nonlocal create_count
        if "create_fts_index" in sql:
            create_count += 1
            raise Exception('Extension "fts" not loaded')
        return None

    conn.execute = mock_execute
    vs = VectorStore(conn)  # type: ignore[arg-type]

    with pytest.raises(Exception, match='Extension "fts" not loaded'):
        vs.rebuild_fts_index()

    # Only ONE create_fts_index call (no retry)
    assert create_count == 1
