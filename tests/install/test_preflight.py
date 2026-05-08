"""Unit tests for the ``preflight`` subcommand."""

from __future__ import annotations

import argparse
import json
import socket
from pathlib import Path
from typing import Any
from unittest.mock import patch
from urllib.error import URLError

import pytest

from skillsmith.install.subcommands import preflight
from skillsmith.install.subcommands.preflight import (
    _check_cli_on_path,  # pyright: ignore[reportPrivateUsage]
    _check_ollama_present,  # pyright: ignore[reportPrivateUsage]
    _check_ollama_reachable,  # pyright: ignore[reportPrivateUsage]
    _check_port_free,  # pyright: ignore[reportPrivateUsage]
    _check_python_version,  # pyright: ignore[reportPrivateUsage]
    _check_uv_present,  # pyright: ignore[reportPrivateUsage]
    _check_xdg_dirs_writable,  # pyright: ignore[reportPrivateUsage]
    run_preflight,
)

# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


class TestPythonVersion:
    def test_passes_on_current(self) -> None:
        result = _check_python_version()
        assert result["passed"] is True
        assert result["severity"] == "fatal"


class TestUvPresent:
    def test_pass(self) -> None:
        with patch.object(preflight.shutil, "which", return_value="/usr/bin/uv"):
            result = _check_uv_present()
        assert result["passed"] is True

    def test_fail(self) -> None:
        with patch.object(preflight.shutil, "which", return_value=None):
            result = _check_uv_present()
        assert result["passed"] is False
        assert "Install uv" in result["remediation"]


class TestCliOnPath:
    def test_pass(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        local_bin = tmp_path / ".local" / "bin"
        local_bin.mkdir(parents=True)
        monkeypatch.setenv("PATH", f"{local_bin}:/usr/bin")
        with patch.object(preflight.shutil, "which", return_value=str(local_bin / "skillsmith")):
            result = _check_cli_on_path()
        assert result["passed"] is True

    def test_fail_path_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("PATH", "/usr/bin")  # ~/.local/bin absent
        with patch.object(preflight.shutil, "which", return_value=None):
            result = _check_cli_on_path()
        assert result["passed"] is False
        assert "not in PATH" in result["error"]
        assert "export PATH=" in result["remediation"]


class TestXdgDirsWritable:
    def test_pass(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        result = _check_xdg_dirs_writable()
        assert result["passed"] is True


class TestPortFree:
    def test_pass(self) -> None:
        result = _check_port_free(0)  # port 0 → kernel picks a free one
        assert result["passed"] is True

    def test_fail_when_bound(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        try:
            result = _check_port_free(port)
        finally:
            sock.close()
        assert result["passed"] is False
        assert result["severity"] == "warn"


class TestOllamaPresent:
    def test_pass(self) -> None:
        with patch.object(preflight.shutil, "which", return_value="/usr/bin/ollama"):
            result = _check_ollama_present()
        assert result["passed"] is True

    def test_fail(self) -> None:
        with patch.object(preflight.shutil, "which", return_value=None):
            result = _check_ollama_present()
        assert result["passed"] is False


class TestOllamaReachable:
    def test_fail_when_unreachable(self) -> None:
        with patch(
            "skillsmith.install.subcommands.preflight.urlopen",
            side_effect=URLError("connection refused"),
        ):
            result = _check_ollama_reachable()
        assert result["passed"] is False
        assert "ollama serve" in result["remediation"]


# ---------------------------------------------------------------------------
# Phase orchestration
# ---------------------------------------------------------------------------


class TestRunPreflightEarly:
    def test_envelope_shape(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        # Force every fatal check to fail for a deterministic envelope.
        with (
            patch.object(preflight.shutil, "which", return_value=None),
            patch(
                "skillsmith.install.subcommands.preflight.urlopen",
                side_effect=URLError("offline"),
            ),
        ):
            result = run_preflight(phase="early", port=0)
        assert result["schema_version"] == 1
        assert result["phase"] == "early"
        assert result["action"] == "preflight_failed"
        assert "uv_present" in result["fatal_failures"]
        assert "cli_on_path" in result["fatal_failures"]
        # Every check returned has the expected keys.
        for c in result["checks"]:
            assert {"name", "passed", "severity", "duration_ms"} <= c.keys()


class TestRunPreflightRunner:
    def test_runner_argument_explicit_ollama_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with (
            patch.object(preflight.shutil, "which", return_value=None),
            patch(
                "skillsmith.install.subcommands.preflight.urlopen",
                side_effect=URLError("offline"),
            ),
        ):
            result = run_preflight(phase="runner", runner="ollama")
        names = [c["name"] for c in result["checks"]]
        assert "ollama_present" in names
        assert "ollama_reachable" in names
        assert result["action"] == "preflight_failed"

    def test_runner_unspecified_and_no_models_output(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Point outputs_dir at a fresh dir with no recommend-models.json.
        monkeypatch.setattr(
            "skillsmith.install.subcommands.preflight.install_state.outputs_dir",
            lambda: tmp_path,
        )
        result = run_preflight(phase="runner")
        assert any(c["name"] == "runner_selected" and not c["passed"] for c in result["checks"])

    def test_runner_inferred_from_models_output(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "recommend-models.json").write_text(json.dumps({"embed_runner": "ollama"}))
        monkeypatch.setattr(
            "skillsmith.install.subcommands.preflight.install_state.outputs_dir",
            lambda: tmp_path,
        )
        with (
            patch.object(preflight.shutil, "which", return_value="/usr/bin/ollama"),
            patch("skillsmith.install.subcommands.preflight.urlopen") as mock_open,
        ):
            mock_open.return_value.__enter__.return_value.read.return_value = b"{}"
            result = run_preflight(phase="runner")
        names = [c["name"] for c in result["checks"]]
        assert "ollama_present" in names

    def test_invalid_phase_raises(self) -> None:
        with pytest.raises(ValueError):
            run_preflight(phase="bogus")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# CLI _run integration
# ---------------------------------------------------------------------------


class TestCliRun:
    def test_exit_zero_on_pass(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        local_bin = tmp_path / ".local" / "bin"
        local_bin.mkdir(parents=True)
        monkeypatch.setenv("PATH", f"{local_bin}:/usr/bin")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        monkeypatch.setattr(
            "skillsmith.install.subcommands.preflight.install_state.outputs_dir",
            lambda: tmp_path / "outputs",
        )
        (tmp_path / "outputs").mkdir()

        def _which(name: str) -> str | None:
            return f"/usr/bin/{name}" if name in {"uv", "skillsmith"} else None

        with (
            patch.object(preflight.shutil, "which", side_effect=_which),
            patch("skillsmith.install.subcommands.preflight.urlopen") as mock_open,
        ):
            mock_resp: Any = mock_open.return_value.__enter__.return_value
            mock_resp.status = 200
            mock_resp.read.return_value = b""
            args = argparse.Namespace(phase="early", runner=None, port=0)
            rc = preflight._run(args)  # pyright: ignore[reportPrivateUsage]
        assert rc == 0
        # Output JSON written to outputs dir.
        out = json.loads((tmp_path / "outputs" / "preflight-early.json").read_text())
        assert out["action"] == "preflight"

    def test_exit_one_on_fatal(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("PATH", "/usr/bin")
        monkeypatch.setattr(
            "skillsmith.install.subcommands.preflight.install_state.outputs_dir",
            lambda: tmp_path / "outputs",
        )
        (tmp_path / "outputs").mkdir()
        with (
            patch.object(preflight.shutil, "which", return_value=None),
            patch(
                "skillsmith.install.subcommands.preflight.urlopen",
                side_effect=URLError("offline"),
            ),
        ):
            args = argparse.Namespace(phase="early", runner=None, port=0)
            rc = preflight._run(args)  # pyright: ignore[reportPrivateUsage]
        assert rc == 1
