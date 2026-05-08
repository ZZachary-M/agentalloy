"""Unit tests for the ``doctor`` subcommand."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from skillsmith.install import state as install_state
from skillsmith.install.subcommands.doctor import (
    _check_runner_processes,  # pyright: ignore[reportPrivateUsage]
    _check_service_reachable,  # pyright: ignore[reportPrivateUsage]
    _check_state_consistent,  # pyright: ignore[reportPrivateUsage]
    run_doctor,
)


@pytest.fixture()
def repo_root(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text("")
    return tmp_path


def _minimal_state(root: Path) -> dict[str, Any]:
    """Set up a minimal install state with .env for doctor to read."""
    st = install_state.load_state(root)
    st["completed_steps"] = [{"step": "detect", "completed_at": "2026-01-01"}]
    st["port"] = 8000
    install_state.save_state(st, root)
    # Write a minimal .env
    (root / ".env").write_text(
        "RUNTIME_EMBED_BASE_URL=http://localhost:11434\n"
        "RUNTIME_EMBEDDING_MODEL=qwen3-embedding:0.6b\n"
        "DUCKDB_PATH=./data/skills.duck\n"
        "LADYBUG_DB_PATH=./data/ladybug\n"
    )
    return st


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


class TestServiceReachable:
    def test_service_up(self) -> None:
        body = json.dumps({"status": "ok"}).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = body
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("skillsmith.install.subcommands.doctor.urlopen", return_value=mock_resp):
            result = _check_service_reachable(8000)
        assert result["passed"] is True

    def test_service_down(self) -> None:
        from urllib.error import URLError

        with patch(
            "skillsmith.install.subcommands.doctor.urlopen", side_effect=URLError("refused")
        ):
            result = _check_service_reachable(8000)
        assert result["passed"] is False


class TestStateConsistent:
    def test_empty_state_fails(self) -> None:
        result = _check_state_consistent({"completed_steps": []})
        assert result["passed"] is False

    def test_populated_state_passes(self) -> None:
        result = _check_state_consistent(
            {
                "completed_steps": [{"step": "detect"}],
                "harness_files_written": [],
            }
        )
        assert result["passed"] is True


class TestRunnerProcesses:
    def test_no_runners(self) -> None:
        result = _check_runner_processes({"models_pulled": []})
        assert result["passed"] is True

    def test_missing_runner(self) -> None:
        with (
            patch("shutil.which", return_value="/usr/bin/ollama"),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=1)
            result = _check_runner_processes({"models_pulled": ["ollama:qwen3-embedding:0.6b"]})
        assert result["passed"] is False


# ---------------------------------------------------------------------------
# Full doctor
# ---------------------------------------------------------------------------


class TestRunDoctor:
    def test_returns_all_checks(self, repo_root: Path) -> None:
        _minimal_state(repo_root)
        # Mock network calls to avoid real connections
        from urllib.error import URLError

        with (
            patch(
                "skillsmith.install.subcommands.verify.urlopen", side_effect=URLError("no network")
            ),
            patch(
                "skillsmith.install.subcommands.doctor.urlopen", side_effect=URLError("no network")
            ),
        ):
            result = run_doctor(root=repo_root)
        assert result["schema_version"] == 1
        # 6 preflight-early + 8 verify + 4 doctor = 18 (count may grow as
        # checks are added; assert the named ones are all present rather
        # than a brittle total).
        names = [c["name"] for c in result["checks"]]
        assert "skillsmith_service_reachable" in names
        assert "compose_endpoint_works" in names
        assert "state_file_consistent" in names
        assert "runner_processes_present" in names
        # Preflight early checks now flow through doctor too.
        assert "uv_present" in names
        assert "cli_on_path" in names

    def test_output_shape(self, repo_root: Path) -> None:
        _minimal_state(repo_root)
        from urllib.error import URLError

        with (
            patch(
                "skillsmith.install.subcommands.verify.urlopen", side_effect=URLError("no network")
            ),
            patch(
                "skillsmith.install.subcommands.doctor.urlopen", side_effect=URLError("no network")
            ),
        ):
            result = run_doctor(root=repo_root)
        assert "all_checks_passed" in result
        for check in result["checks"]:
            assert "name" in check
            assert "passed" in check
