"""Unit tests for the ``verify`` subcommand.

Tests the individual check functions in isolation (mocked external deps).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch
from urllib.error import URLError

from skillsmith.install.subcommands.verify import (
    MIN_SKILL_COUNT,
    SCHEMA_VERSION,
    _check_duckdb_present,  # pyright: ignore[reportPrivateUsage]
    _check_embedding_1024_dim,  # pyright: ignore[reportPrivateUsage]
    _check_embedding_endpoint_reachable,  # pyright: ignore[reportPrivateUsage]
    _check_harness_config_present,  # pyright: ignore[reportPrivateUsage]
    _check_harness_config_url,  # pyright: ignore[reportPrivateUsage]
    _check_ladybug_present,  # pyright: ignore[reportPrivateUsage]
    _check_port_available,  # pyright: ignore[reportPrivateUsage]
    _check_skill_count,  # pyright: ignore[reportPrivateUsage]
    run_checks,
)

# ---------------------------------------------------------------------------
# Check 1: embedding endpoint reachable
# ---------------------------------------------------------------------------


class TestEmbeddingEndpointReachable:
    @patch("skillsmith.install.subcommands.verify.urlopen")
    def test_pass_on_200(self, mock_urlopen: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s  # pyright: ignore[reportUnknownLambdaType]
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp
        result = _check_embedding_endpoint_reachable("http://localhost:11434")
        assert result["passed"] is True

    @patch("skillsmith.install.subcommands.verify.urlopen", side_effect=URLError("refused"))
    def test_fail_on_connection_error(self, mock: MagicMock) -> None:
        result = _check_embedding_endpoint_reachable("http://localhost:11434")
        assert result["passed"] is False
        assert "remediation" in result


# ---------------------------------------------------------------------------
# Check 2: embedding 1024-dim
# ---------------------------------------------------------------------------


class TestEmbedding1024Dim:
    @patch("skillsmith.install.subcommands.verify.urlopen")
    def test_pass_on_1024_dim(self, mock_urlopen: MagicMock) -> None:
        body = json.dumps({"data": [{"embedding": [0.1] * 1024}]}).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = body
        mock_resp.__enter__ = lambda s: s  # pyright: ignore[reportUnknownLambdaType]
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp
        result = _check_embedding_1024_dim("http://localhost:11434", "qwen3-embedding:0.6b")
        assert result["passed"] is True

    @patch("skillsmith.install.subcommands.verify.urlopen")
    def test_fail_on_wrong_dim(self, mock_urlopen: MagicMock) -> None:
        body = json.dumps({"data": [{"embedding": [0.1] * 768}]}).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = body
        mock_resp.__enter__ = lambda s: s  # pyright: ignore[reportUnknownLambdaType]
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp
        result = _check_embedding_1024_dim("http://localhost:11434", "wrong-model")
        assert result["passed"] is False
        assert "768" in result.get("error", "")


# ---------------------------------------------------------------------------
# Check 3: DuckDB present
# ---------------------------------------------------------------------------


class TestDuckDBPresent:
    def test_fail_on_missing_file(self) -> None:
        result = _check_duckdb_present("/nonexistent/path/skills.duck")
        assert result["passed"] is False


# ---------------------------------------------------------------------------
# Check 4: Ladybug present
# ---------------------------------------------------------------------------


class TestLadybugPresent:
    def test_fail_on_missing_dir(self) -> None:
        result = _check_ladybug_present("/nonexistent/path/ladybug")
        assert result["passed"] is False


# ---------------------------------------------------------------------------
# Check 6: harness config present
# ---------------------------------------------------------------------------


class TestHarnessConfigPresent:
    def test_fail_when_no_harness_files(self) -> None:
        st: dict[str, Any] = {"harness_files_written": []}
        result = _check_harness_config_present(st)
        assert result["passed"] is False

    def test_pass_with_sentinel(self, tmp_path: Path) -> None:
        harness_file = tmp_path / "CLAUDE.md"
        harness_file.write_text(
            "# Claude\n<!-- BEGIN skillsmith install -->\nstuff\n<!-- END skillsmith install -->\n"
        )
        st: dict[str, Any] = {
            "harness": "claude-code",
            "harness_files_written": [
                {"path": str(harness_file), "sentinel_begin": "<!-- BEGIN skillsmith install -->"}
            ],
        }
        result = _check_harness_config_present(st)
        assert result["passed"] is True

    def test_fail_when_sentinel_missing(self, tmp_path: Path) -> None:
        harness_file = tmp_path / "CLAUDE.md"
        harness_file.write_text("# Claude\nno sentinel here\n")
        st: dict[str, Any] = {
            "harness_files_written": [
                {"path": str(harness_file), "sentinel_begin": "<!-- BEGIN skillsmith install -->"}
            ],
        }
        result = _check_harness_config_present(st)
        assert result["passed"] is False


# ---------------------------------------------------------------------------
# Check 7: harness URL matches
# ---------------------------------------------------------------------------


class TestHarnessConfigURL:
    def test_pass_when_url_present(self, tmp_path: Path) -> None:
        f = tmp_path / "CLAUDE.md"
        f.write_text("http://localhost:8000/compose\n")
        st: dict[str, Any] = {
            "port": 8000,
            "harness_files_written": [{"path": str(f)}],
        }
        result = _check_harness_config_url(st)
        assert result["passed"] is True

    def test_fail_when_url_missing(self, tmp_path: Path) -> None:
        f = tmp_path / "CLAUDE.md"
        f.write_text("http://localhost:9999/compose\n")
        st: dict[str, Any] = {
            "port": 8000,
            "harness_files_written": [{"path": str(f)}],
        }
        result = _check_harness_config_url(st)
        assert result["passed"] is False


# ---------------------------------------------------------------------------
# Check 8: port available
# ---------------------------------------------------------------------------


class TestPortAvailable:
    def test_unused_port_passes(self) -> None:
        # Port 0 should be available (OS assigns ephemeral)
        result = _check_port_available(19999)
        # Might pass or fail depending on what's running, but should not error
        assert "name" in result
        assert result["name"] == "runtime_port_available"


class TestPortAvailableHealthStatus:
    """`_check_port_available` consults `/health` when the port is bound.

    Regression: previously compared `status == "ok"`, but the service
    returns `"healthy"` / `"degraded"` / `"unavailable"`.
    """

    @patch("skillsmith.install.subcommands.verify.urlopen")
    @patch("skillsmith.install.subcommands.verify.socket.socket")
    def test_healthy_status_passes(self, mock_sock: MagicMock, mock_urlopen: MagicMock) -> None:
        # Mock the TCP connect_ex to return 0 (port in use).
        sock_inst = MagicMock()
        sock_inst.connect_ex.return_value = 0
        sock_inst.__enter__ = lambda s: s  # pyright: ignore[reportUnknownLambdaType]
        sock_inst.__exit__ = MagicMock(return_value=False)
        mock_sock.return_value = sock_inst

        body = json.dumps({"status": "healthy"}).encode()
        resp = MagicMock()
        resp.read.return_value = body
        resp.__enter__ = lambda s: s  # pyright: ignore[reportUnknownLambdaType]
        resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = resp

        result = _check_port_available(47950)
        assert result["passed"] is True

    @patch("skillsmith.install.subcommands.verify.urlopen")
    @patch("skillsmith.install.subcommands.verify.socket.socket")
    def test_degraded_status_passes(self, mock_sock: MagicMock, mock_urlopen: MagicMock) -> None:
        sock_inst = MagicMock()
        sock_inst.connect_ex.return_value = 0
        sock_inst.__enter__ = lambda s: s  # pyright: ignore[reportUnknownLambdaType]
        sock_inst.__exit__ = MagicMock(return_value=False)
        mock_sock.return_value = sock_inst

        body = json.dumps({"status": "degraded"}).encode()
        resp = MagicMock()
        resp.read.return_value = body
        resp.__enter__ = lambda s: s  # pyright: ignore[reportUnknownLambdaType]
        resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = resp

        result = _check_port_available(47950)
        assert result["passed"] is True

    @patch("skillsmith.install.subcommands.verify.urlopen")
    @patch("skillsmith.install.subcommands.verify.socket.socket")
    def test_unavailable_status_fails(self, mock_sock: MagicMock, mock_urlopen: MagicMock) -> None:
        sock_inst = MagicMock()
        sock_inst.connect_ex.return_value = 0
        sock_inst.__enter__ = lambda s: s  # pyright: ignore[reportUnknownLambdaType]
        sock_inst.__exit__ = MagicMock(return_value=False)
        mock_sock.return_value = sock_inst

        body = json.dumps({"status": "unavailable"}).encode()
        resp = MagicMock()
        resp.read.return_value = body
        resp.__enter__ = lambda s: s  # pyright: ignore[reportUnknownLambdaType]
        resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = resp

        result = _check_port_available(47950)
        assert result["passed"] is False
        assert "'unavailable'" in result.get("error", "")


class TestDBChecksWithServiceUp:
    """When `diag` is provided, the three DB checks must NOT touch the
    DB files — the service holds the locks. They derive pass/fail from
    the diagnostics response instead.
    """

    def _diag(self, *, runtime: str, telemetry: str, skills: int) -> dict[str, Any]:
        return {
            "dependency_readiness": {
                "runtime_store": runtime,
                "telemetry_store": telemetry,
                "embedding_runtime": "ok",
                "runtime_cache": "ok",
            },
            "store_state": [{"skill_id": f"s{i}"} for i in range(skills)],
        }

    def test_duckdb_passes_when_telemetry_ok(self) -> None:
        diag = self._diag(runtime="ok", telemetry="ok", skills=29)
        result = _check_duckdb_present("/path/that/does/not/exist.duck", diag=diag)
        assert result["passed"] is True
        assert "/diagnostics/runtime" in result["detail"]

    def test_duckdb_fails_when_telemetry_unavailable(self) -> None:
        diag = self._diag(runtime="ok", telemetry="unavailable", skills=29)
        result = _check_duckdb_present("/path/that/does/not/exist.duck", diag=diag)
        assert result["passed"] is False
        assert "telemetry_store" in result["error"]

    def test_ladybug_passes_when_runtime_ok(self) -> None:
        diag = self._diag(runtime="ok", telemetry="ok", skills=29)
        result = _check_ladybug_present("/path/that/does/not/exist", diag=diag)
        assert result["passed"] is True
        assert "29 active skills" in result["detail"]

    def test_ladybug_fails_when_runtime_unavailable(self) -> None:
        diag = self._diag(runtime="unavailable", telemetry="ok", skills=29)
        result = _check_ladybug_present("/path/that/does/not/exist", diag=diag)
        assert result["passed"] is False
        assert "runtime_store" in result["error"]

    def test_skill_count_passes_when_at_minimum(self) -> None:
        diag = self._diag(runtime="ok", telemetry="ok", skills=MIN_SKILL_COUNT)
        result = _check_skill_count("/unused", diag=diag)
        assert result["passed"] is True

    def test_skill_count_fails_when_below_minimum(self) -> None:
        diag = self._diag(runtime="ok", telemetry="ok", skills=MIN_SKILL_COUNT - 1)
        result = _check_skill_count("/unused", diag=diag)
        assert result["passed"] is False


# ---------------------------------------------------------------------------
# Full run_checks
# ---------------------------------------------------------------------------


class TestRunChecks:
    @patch("skillsmith.install.subcommands.verify.urlopen", side_effect=URLError("refused"))
    def test_output_schema(self, mock_urlopen: MagicMock, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("")
        st: dict[str, Any] = {
            "port": 8000,
            "harness_files_written": [],
        }
        result = run_checks(st, root=tmp_path)
        assert result["schema_version"] == SCHEMA_VERSION
        assert "all_checks_passed" in result
        assert "checks" in result
        assert len(result["checks"]) == 8

    @patch("skillsmith.install.subcommands.verify.urlopen", side_effect=URLError("refused"))
    def test_all_checks_have_name_and_passed(self, mock_urlopen: MagicMock, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("")
        st: dict[str, Any] = {"port": 8000, "harness_files_written": []}
        result = run_checks(st, root=tmp_path)
        for check in result["checks"]:
            assert "name" in check
            assert "passed" in check
