# ruff: noqa: I001, PLC0415 -- testing private module members intentionally
"""Tests for the uninstall subcommand (container branch)."""

from __future__ import annotations

import subprocess
from pathlib import Path, Path as _RealPath  # noqa: F811 -- _RealPath used when patching uninstall.Path
from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock, patch

from agentalloy.install.subcommands.uninstall import (
    _remove_sentinel_block,  # type: ignore[attr-defined]
    _extract_sentinel_content,  # type: ignore[attr-defined]
    _stop_container_stack,  # type: ignore[attr-defined]
)

# Typed helper for mock_which.side_effect to avoid pyright reportUnknownLambdaType
WhichSideEffect = Callable[[str], str | None]


def _which_map(**mapping: str) -> WhichSideEffect:
    """Create a typed which side_effect from a mapping."""

    def _which(name: str) -> str | None:
        return mapping.get(name)

    return _which


def _which_single(target: str, path: str) -> WhichSideEffect:
    """Create a typed which side_effect that returns path only for target."""

    def _which(name: str) -> str | None:
        return path if name == target else None

    return _which


def _which_none() -> WhichSideEffect:
    """Create a typed which side_effect that always returns None."""

    def _which(name: str) -> str | None:
        return None

    return _which


class TestContainerUninstall:
    """Test container-specific uninstall logic."""

    def test_compose_down_on_container_deployment(self, tmp_path: Path):
        """State with deployment='container' runs compose down -v."""
        compose_file = tmp_path / "compose.yaml"
        compose_file.touch()

        state: dict[str, Any] = {
            "deployment": "container",
            "compose_binary": "podman compose",
            "compose_file": str(compose_file),
        }
        warnings: list[str] = []

        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            actions = _stop_container_stack(state, warnings)

        # Should call subprocess with podman compose down
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "podman"
        assert call_args[1] == "compose"
        assert call_args[2] == "-f"
        assert call_args[3] == str(compose_file)
        assert call_args[4] == "down"
        assert call_args[5] == "-v"

        assert len(actions) == 1
        assert actions[0]["action"] == "compose_down"
        assert not warnings

    def test_compose_down_docker(self, tmp_path: Path):
        """Docker compose variant works identically."""
        compose_file = tmp_path / "compose.yaml"
        compose_file.touch()

        state: dict[str, Any] = {
            "deployment": "container",
            "compose_binary": "docker compose",
            "compose_file": str(compose_file),
        }
        warnings: list[str] = []

        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            actions = _stop_container_stack(state, warnings)

        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "docker"
        assert actions[0]["action"] == "compose_down"

    def test_compose_down_skipped_native(self):
        """Native deployment does NOT run compose down."""
        state: dict[str, Any] = {
            "deployment": "native",
        }
        warnings: list[str] = []

        with patch("subprocess.run") as mock_run:
            actions = _stop_container_stack(state, warnings)

        mock_run.assert_not_called()
        assert actions == []

    def test_compose_down_skipped_no_deployment(self):
        """State with no deployment field skips compose down."""
        state: dict[str, Any] = {}
        warnings: list[str] = []
        actions = _stop_container_stack(state, warnings)
        assert actions == []

    def test_compose_down_missing_binary_warns(self, tmp_path: Path):
        """Binary not found adds warning but continues."""
        compose_file = tmp_path / "compose.yaml"
        compose_file.touch()

        state: dict[str, Any] = {
            "deployment": "container",
            "compose_binary": "podman compose",
            "compose_file": str(compose_file),
        }
        warnings: list[str] = []

        with patch("subprocess.run", side_effect=OSError("No such file: podman")):
            actions = _stop_container_stack(state, warnings)

        assert len(warnings) == 1
        assert "binary not found" in warnings[0].lower()
        assert actions[0]["action"] == "compose_down_skipped"

    def test_compose_down_missing_file_warns(self, tmp_path: Path):
        """Compose file in state points to non-existent file."""
        state: dict[str, Any] = {
            "deployment": "container",
            "compose_binary": "podman compose",
            "compose_file": str(tmp_path / "nonexistent.yaml"),
        }
        warnings: list[str] = []
        actions = _stop_container_stack(state, warnings)

        assert len(warnings) == 1
        assert "missing" in warnings[0].lower() or "not found" in warnings[0].lower()
        assert actions == []

    def test_compose_down_none_in_state_warns(self):
        """compose_file is None (old/corrupt state)."""
        state: dict[str, Any] = {
            "deployment": "container",
            "compose_binary": "podman compose",
            "compose_file": None,
        }
        warnings: list[str] = []
        actions = _stop_container_stack(state, warnings)

        assert len(warnings) == 1
        assert "None" in warnings[0] or "compose_file" in warnings[0].lower()
        assert actions == []

    def test_compose_down_missing_binary_label_warns(self):
        """compose_binary is missing in state."""
        state: dict[str, Any] = {
            "deployment": "container",
            "compose_file": "/some/path/compose.yaml",
        }
        warnings: list[str] = []
        actions = _stop_container_stack(state, warnings)

        assert len(warnings) == 1
        assert "compose_binary" in warnings[0].lower()
        assert actions == []

    def test_compose_down_invalid_label_warns(self, tmp_path: Path):
        """Invalid compose_binary label (no space) is rejected."""
        compose_file = tmp_path / "compose.yaml"
        compose_file.touch()

        state: dict[str, Any] = {
            "deployment": "container",
            "compose_binary": "podman",  # missing "compose" part
            "compose_file": str(compose_file),
        }
        warnings: list[str] = []
        _actions = _stop_container_stack(state, warnings)

        assert len(warnings) == 1
        assert "Invalid" in warnings[0] or "invalid" in warnings[0].lower()

    def test_compose_down_failure_warns(self, tmp_path: Path):
        """subprocess returns non-zero, warning added, action recorded."""
        compose_file = tmp_path / "compose.yaml"
        compose_file.touch()

        state: dict[str, Any] = {
            "deployment": "container",
            "compose_binary": "podman compose",
            "compose_file": str(compose_file),
        }
        warnings: list[str] = []

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "Error: network not found"

        with patch("subprocess.run", return_value=mock_result):
            actions = _stop_container_stack(state, warnings)

        assert len(warnings) == 1
        assert "failed" in warnings[0].lower()
        assert actions[0]["action"] == "compose_down_failed"

    def test_compose_down_timeout(self, tmp_path: Path):
        """subprocess timeout adds warning and records timeout action."""
        compose_file = tmp_path / "compose.yaml"
        compose_file.touch()

        state: dict[str, Any] = {
            "deployment": "container",
            "compose_binary": "podman compose",
            "compose_file": str(compose_file),
        }
        warnings: list[str] = []

        with patch(
            "subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="timeout", timeout=60)
        ):
            actions = _stop_container_stack(state, warnings)

        assert len(warnings) == 1
        assert "timed out" in warnings[0].lower()
        assert actions[0]["action"] == "compose_down_timeout"


class TestSentinelHelpers:
    """Test sentinel block extraction and removal."""

    def test_extract_sentinel_content_found(self):
        text = "before\n<!-- BEGIN AGENTALLOY -->\nsome content\n<!-- END AGENTALLOY -->\nafter"
        result = _extract_sentinel_content(
            text, "<!-- BEGIN AGENTALLOY -->", "<!-- END AGENTALLOY -->"
        )
        assert result == "some content"

    def test_extract_sentinel_content_not_found(self):
        text = "no sentinels here"
        result = _extract_sentinel_content(text, "BEGIN", "END")
        assert result is None

    def test_extract_sentinel_only_begin_missing(self):
        """When markers are reversed (END before BEGIN), returns empty string."""
        text = "has END but no BEGIN"
        result = _extract_sentinel_content(text, "BEGIN", "END")
        # Both "BEGIN" and "END" are substrings, but END comes before BEGIN,
        # so the extraction range is reversed and returns empty string.
        assert result == ""

    def test_remove_sentinel_block(self):
        text = "before\n\n<!-- BEGIN AGENTALLOY -->\nsome content\n<!-- END AGENTALLOY -->\nafter"
        result = _remove_sentinel_block(
            text, "<!-- BEGIN AGENTALLOY -->", "<!-- END AGENTALLOY -->"
        )
        assert "some content" not in result
        assert "before" in result
        assert "after" in result

    def test_remove_sentinel_block_not_found(self):
        text = "no sentinels here"
        result = _remove_sentinel_block(text, "BEGIN", "END")
        assert result == text

    def test_remove_sentinel_clean_double_blanks(self):
        text = "before\n\n<!-- BEGIN -->\ncontent\n<!-- END -->\n\n\n\nafter"
        result = _remove_sentinel_block(text, "<!-- BEGIN -->", "<!-- END -->")
        # Should clean up triple+ newlines
        assert "\n\n\n" not in result


class TestRemovePulledModels:
    """Test _remove_pulled_models helper."""

    def test_no_models_pulled(self):
        from agentalloy.install.subcommands.uninstall import _remove_pulled_models  # type: ignore[attr-defined]

        actions = _remove_pulled_models({})
        assert actions == []

    def test_malformed_entry_skipped(self):
        from agentalloy.install.subcommands.uninstall import _remove_pulled_models  # type: ignore[attr-defined]

        actions = _remove_pulled_models({"models_pulled": [123, None, ""]})
        for action in actions:
            assert action["action"] in ("skipped_malformed_entry", "skipped_empty_fields")

    def test_unmanaged_runner_skipped(self):
        from agentalloy.install.subcommands.uninstall import _remove_pulled_models  # type: ignore[attr-defined]

        actions = _remove_pulled_models({"models_pulled": ["lm-studio:some-model"]})
        assert len(actions) == 1
        assert actions[0]["action"] == "skipped_unmanaged_runner"


class TestDetectInstallMode:
    """Test _detect_install_mode detection logic."""

    @patch("agentalloy.install.subcommands.uninstall.shutil.which")
    @patch("agentalloy.install.subcommands.uninstall.subprocess.run")
    def test_uv_tool_mode_detected(self, mock_run: MagicMock, mock_which: MagicMock):
        """uv tool list contains agentalloy -> mode is uv_tool."""
        mock_which.side_effect = _which_map(
            uv="/usr/bin/uv", agentalloy="/usr/local/bin/agentalloy"
        )
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "agentalloy 1.0.0 /path/to/venv\n"
        mock_run.return_value = mock_result

        from agentalloy.install.subcommands.uninstall import _detect_install_mode  # type: ignore[attr-defined]

        result = _detect_install_mode()
        assert result["mode"] == "uv_tool"
        assert result["binary_path"] == "/usr/local/bin/agentalloy"
        assert result["venv_path"] is None
        assert "uv tool" in result["details"]
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "/usr/bin/uv"
        assert "tool" in call_args
        assert "list" in call_args

    @patch("agentalloy.install.subcommands.uninstall.shutil.which")
    @patch("agentalloy.install.subcommands.uninstall.subprocess.run")
    def test_pipx_mode_detected(self, mock_run: MagicMock, mock_which: MagicMock):
        """uv tool list does NOT contain agentalloy, pipx does -> mode is pipx."""
        mock_which.side_effect = _which_map(
            uv="/usr/bin/uv", pipx="/usr/bin/pipx", agentalloy="/usr/bin/agentalloy"
        )

        # First call: uv tool list — no agentalloy
        uv_result = MagicMock()
        uv_result.returncode = 0
        uv_result.stdout = "some-other-tool 1.0.0 /path\n"

        # Second call: pipx list --short — agentalloy found
        pipx_result = MagicMock()
        pipx_result.returncode = 0
        pipx_result.stdout = "agentalloy 1.0.0\n"

        mock_run.side_effect = [uv_result, pipx_result]

        from agentalloy.install.subcommands.uninstall import _detect_install_mode  # type: ignore[attr-defined]

        result = _detect_install_mode()
        assert result["mode"] == "pipx"
        assert "pipx" in result["details"].lower()

    @patch("agentalloy.install.subcommands.uninstall.shutil.which")
    @patch("agentalloy.install.subcommands.uninstall.subprocess.run")
    def test_editable_mode_detected(
        self, mock_run: MagicMock, mock_which: MagicMock, tmp_path: Path
    ):
        """Binary under .venv + pyproject.toml with name=agentalloy -> mode is editable."""
        # Set up .venv and pyproject.toml
        venv_dir = tmp_path / ".venv"
        venv_dir.mkdir()
        bin_dir = venv_dir / "bin"
        bin_dir.mkdir()
        binary_path = str(bin_dir / "agentalloy")

        repo_root = tmp_path
        pyproject = repo_root / "pyproject.toml"
        pyproject.write_text('[project]\nname = "agentalloy"\n')

        mock_which.side_effect = _which_single("agentalloy", binary_path)

        # uv tool list returns no agentalloy (but uv is not even found)
        # pipx is not found either

        from agentalloy.install.subcommands.uninstall import _detect_install_mode  # type: ignore[attr-defined]

        result = _detect_install_mode()
        assert result["mode"] == "editable"
        assert result["venv_path"] == str(venv_dir)
        assert ".venv" in result["details"]

    @patch("agentalloy.install.subcommands.uninstall.shutil.which")
    def test_unknown_mode_detected(self, mock_which: MagicMock):
        """No detection method matches -> mode is unknown."""
        mock_which.side_effect = _which_none()

        from agentalloy.install.subcommands.uninstall import _detect_install_mode  # type: ignore[attr-defined]

        result = _detect_install_mode()
        assert result["mode"] == "unknown"
        assert result["binary_path"] is None
        assert result["venv_path"] is None
        assert "could not be determined" in result["details"].lower()

    @patch("agentalloy.install.subcommands.uninstall.shutil.which")
    @patch("agentalloy.install.subcommands.uninstall.subprocess.run")
    def test_uv_tool_list_timeout_falls_through(self, mock_run: MagicMock, mock_which: MagicMock):
        """subprocess.TimeoutExpired during uv tool list causes pipx check to run."""
        mock_which.side_effect = _which_map(
            uv="/usr/bin/uv", pipx="/usr/bin/pipx", agentalloy="/usr/bin/agentalloy"
        )

        # First call: uv tool list — timeout
        # Second call: pipx list --short — agentalloy found
        pipx_result = MagicMock()
        pipx_result.returncode = 0
        pipx_result.stdout = "agentalloy 1.0.0\n"

        mock_run.side_effect = [
            subprocess.TimeoutExpired(cmd=["uv", "tool", "list"], timeout=10),
            pipx_result,
        ]

        from agentalloy.install.subcommands.uninstall import _detect_install_mode  # type: ignore[attr-defined]

        result = _detect_install_mode()
        assert result["mode"] == "pipx"
        # uv tool list was called, pipx list was called as fallback
        assert mock_run.call_count == 2


class TestRemoveCliInstall:
    """Test _remove_cli_install dispatch and individual removal strategies."""

    @patch("agentalloy.install.subcommands.uninstall.shutil.which")
    @patch("agentalloy.install.subcommands.uninstall.subprocess.run")
    def test_uv_tool_mode_uninstalls(self, mock_run: MagicMock, mock_which: MagicMock):
        """uv_tool mode -> uv tool uninstall succeeds -> action uv_tool_uninstalled."""
        mock_which.side_effect = _which_single("uv", "/usr/bin/uv")
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        from agentalloy.install.subcommands.uninstall import _remove_cli_install  # type: ignore[attr-defined]

        mode_info = {"mode": "uv_tool", "binary_path": "/usr/bin/agentalloy"}
        result = _remove_cli_install(mode_info)
        assert result["action"] == "uv_tool_uninstalled"
        assert result["mode"] == "uv_tool"
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "/usr/bin/uv"
        assert "tool" in call_args
        assert "uninstall" in call_args
        assert "agentalloy" in call_args

    @patch("agentalloy.install.subcommands.uninstall.shutil.which")
    @patch("agentalloy.install.subcommands.uninstall.subprocess.run")
    def test_pipx_mode_uninstalls(self, mock_run: MagicMock, mock_which: MagicMock):
        """pipx mode -> pipx uninstall succeeds -> action pipx_uninstalled."""
        mock_which.side_effect = _which_single("pipx", "/usr/bin/pipx")
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        from agentalloy.install.subcommands.uninstall import _remove_cli_install  # type: ignore[attr-defined]

        mode_info = {"mode": "pipx", "binary_path": "/usr/bin/agentalloy"}
        result = _remove_cli_install(mode_info)
        assert result["action"] == "pipx_uninstalled"
        assert result["mode"] == "pipx"
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "/usr/bin/pipx"
        assert "uninstall" in call_args
        assert "agentalloy" in call_args

    def test_editable_mode_left_in_place(self):
        """editable mode -> action editable_install_left_in_place with venv_path."""
        from agentalloy.install.subcommands.uninstall import _remove_cli_install  # type: ignore[attr-defined]

        venv = "/home/user/project/.venv"
        mode_info = {
            "mode": "editable",
            "binary_path": "/home/user/project/.venv/bin/agentalloy",
            "venv_path": venv,
        }
        result = _remove_cli_install(mode_info)
        assert result["action"] == "editable_install_left_in_place"
        assert result["mode"] == "editable"
        assert result["venv_path"] == venv
        assert "Editable install" in result["details"]

    def test_unknown_mode_skipped(self):
        """unknown mode -> action cli_install_skipped."""
        from agentalloy.install.subcommands.uninstall import _remove_cli_install  # type: ignore[attr-defined]

        mode_info = {"mode": "unknown", "binary_path": None}
        result = _remove_cli_install(mode_info)
        assert result["action"] == "cli_install_skipped"
        assert result["mode"] == "unknown"
        assert "not found in PATH" in result["reason"]

    @patch("agentalloy.install.subcommands.uninstall.shutil.which")
    @patch("agentalloy.install.subcommands.uninstall.subprocess.run")
    def test_uv_tool_uninstall_fails(self, mock_run: MagicMock, mock_which: MagicMock):
        """uv tool uninstall returns non-zero -> action uv_tool_skipped with reason."""
        mock_which.side_effect = _which_single("uv", "/usr/bin/uv")
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "tool 'agentalloy' is not installed"
        mock_run.return_value = mock_result

        from agentalloy.install.subcommands.uninstall import _remove_cli_install  # type: ignore[attr-defined]

        mode_info = {"mode": "uv_tool", "binary_path": "/usr/bin/agentalloy"}
        result = _remove_cli_install(mode_info)
        assert result["action"] == "uv_tool_skipped"
        assert result["mode"] == "uv_tool"
        assert "not installed" in result["reason"]


class TestResultDictKeys:
    """Test that uninstall() returns the correct result dict keys."""

    @patch("agentalloy.install.server_proc.find_listening_pid", return_value=None)
    @patch("agentalloy.install.subcommands.uninstall._detect_install_mode")
    @patch("agentalloy.install.subcommands.uninstall.shutil.which")
    def test_cli_install_key_and_uv_tool_alias(
        self,
        mock_which: MagicMock,
        mock_detect: MagicMock,
        mock_find_pid: MagicMock,
        tmp_path: Path,
    ):
        """Result dict has 'cli_install' as primary key and 'uv_tool' as deprecated alias."""
        mock_which.side_effect = _which_none()
        mock_detect.return_value = {
            "mode": "unknown",
            "binary_path": None,
            "venv_path": None,
            "details": "Install mode could not be determined",
        }

        from agentalloy.install.subcommands.uninstall import uninstall

        minimal_state: dict[str, Any] = {
            "harness_files_written": [],
        }

        with (
            patch("agentalloy.install.state.load_state", return_value=minimal_state),
            patch("agentalloy.install.state.user_data_dir", return_value=tmp_path / "data"),
            patch("agentalloy.install.state.user_config_dir", return_value=tmp_path / "config"),
        ):
            result = uninstall(
                remove_data=False,
                force=True,
                stop_services=True,
            )

        # Primary key
        assert "cli_install" in result
        # Deprecated alias
        assert "uv_tool" in result
        # Both point to the same dict
        assert result["cli_install"] is result["uv_tool"]
        # install_mode is present
        assert "install_mode" in result

    @patch("agentalloy.install.server_proc.find_listening_pid", return_value=None)
    @patch("agentalloy.install.subcommands.uninstall._detect_install_mode")
    @patch("agentalloy.install.subcommands.uninstall.shutil.which")
    def test_cli_install_key_contains_action(
        self,
        mock_which: MagicMock,
        mock_detect: MagicMock,
        mock_find_pid: MagicMock,
        tmp_path: Path,
    ):
        """cli_install result contains an 'action' field."""
        mock_which.side_effect = _which_none()
        mock_detect.return_value = {
            "mode": "unknown",
            "binary_path": None,
            "venv_path": None,
            "details": "Install mode could not be determined",
        }

        from agentalloy.install.subcommands.uninstall import uninstall

        minimal_state: dict[str, Any] = {
            "harness_files_written": [],
        }

        with (
            patch("agentalloy.install.state.load_state", return_value=minimal_state),
            patch("agentalloy.install.state.user_data_dir", return_value=tmp_path / "data"),
            patch("agentalloy.install.state.user_config_dir", return_value=tmp_path / "config"),
        ):
            result = uninstall(
                remove_data=False,
                force=True,
                stop_services=True,
            )

        assert "action" in result["cli_install"]
        assert result["cli_install"]["action"] == "cli_install_skipped"


class TestPromptUninstallPreset:
    """Test _prompt_uninstall_preset interactive menu."""

    def test_default_is_full_bare_enter(self):
        """Bare Enter (empty string) returns 'full'."""
        from agentalloy.install.subcommands.uninstall import _prompt_uninstall_preset  # type: ignore[attr-defined]

        with patch("builtins.input", return_value=""):
            result = _prompt_uninstall_preset()
        assert result == "full"

    def test_default_is_full_eof(self):
        """EOFError (Ctrl-D / pipe) returns 'full'."""
        from agentalloy.install.subcommands.uninstall import _prompt_uninstall_preset  # type: ignore[attr-defined]

        with patch("builtins.input", side_effect=EOFError()):
            result = _prompt_uninstall_preset()
        assert result == "full"

    def test_choice_2_returns_keep_data(self):
        """Input '2' returns 'keep-data'."""
        from agentalloy.install.subcommands.uninstall import _prompt_uninstall_preset  # type: ignore[attr-defined]

        with patch("builtins.input", return_value="2"):
            result = _prompt_uninstall_preset()
        assert result == "keep-data"

    def test_choice_3_returns_custom(self):
        """Input '3' returns 'custom'."""
        from agentalloy.install.subcommands.uninstall import _prompt_uninstall_preset  # type: ignore[attr-defined]

        with patch("builtins.input", return_value="3"):
            result = _prompt_uninstall_preset()
        assert result == "custom"


class TestPortConflictDiagnostics:
    """Test port conflict detection in the uninstall function (step 5b)."""

    @patch("agentalloy.install.server_proc.find_listening_pid")
    @patch("agentalloy.install.server_proc.stop")
    @patch("agentalloy.install.subcommands.uninstall.Path")
    def test_foreign_process_warns_no_kill(
        self,
        mock_path_cls: MagicMock,
        mock_stop: MagicMock,
        mock_find_pid: MagicMock,
        tmp_path: Path,
    ):
        """Foreign process on the port: warning added, no kill attempted."""
        mock_find_pid.return_value = 12345
        cmdline_path_str = "/proc/12345/cmdline"
        cmdline_content = "nginx: master process /usr/sbin/nginx"

        # Create a mock Path instance for the cmdline
        cmdline_mock = MagicMock(spec=_RealPath)
        cmdline_mock.exists.return_value = True
        cmdline_mock.read_bytes.return_value = cmdline_content.encode()

        # Make Path.home() return a real Path (needed for claude_mcp path construction)
        mock_path_cls.home = _RealPath.home

        # Patch Path to return our mock for cmdline path, real Path otherwise
        def path_side_effect(*args: Any, **kwargs: Any) -> Any:
            if not args:
                # Called as a classmethod (e.g., Path.home) — fall back to real
                return _RealPath.home()
            if str(args[0]) == cmdline_path_str:
                return cmdline_mock
            return _RealPath(*args, **kwargs)

        mock_path_cls.side_effect = path_side_effect

        from agentalloy.install.subcommands.uninstall import uninstall

        minimal_state: dict[str, Any] = {
            "harness_files_written": [],
            "port": 47950,
        }

        with (
            patch("agentalloy.install.state.load_state", return_value=minimal_state),
            patch("agentalloy.install.state.user_data_dir", return_value=tmp_path / "data"),
            patch("agentalloy.install.state.user_config_dir", return_value=tmp_path / "config"),
        ):
            result = uninstall(
                remove_data=False,
                force=True,
                stop_services=True,
            )

        # Verify no attempt to stop the process
        mock_stop.assert_not_called()

        # Verify a warning about the foreign process was added
        warnings = result.get("warnings", [])
        found_warning = any("not an agentalloy server" in w.lower() for w in warnings)
        assert found_warning, f"No foreign-process warning found in: {warnings}"

    @patch("agentalloy.install.server_proc.find_listening_pid")
    @patch("agentalloy.install.server_proc.stop")
    @patch("agentalloy.install.subcommands.uninstall.Path")
    def test_agentalloy_process_stopped(
        self,
        mock_path_cls: MagicMock,
        mock_stop: MagicMock,
        mock_find_pid: MagicMock,
        tmp_path: Path,
    ):
        """Agentalloy process on the port: it is stopped."""
        mock_find_pid.return_value = 12345
        cmdline_path_str = "/proc/12345/cmdline"
        cmdline_content = "python -m uvicorn agentalloy.app:app --host 0.0.0.0 --port 47950"

        # Create a mock Path instance for the cmdline
        cmdline_mock = MagicMock(spec=_RealPath)
        cmdline_mock.exists.return_value = True
        cmdline_mock.read_bytes.return_value = cmdline_content.encode()

        # Make Path.home() return a real Path (needed for claude_mcp path construction)
        mock_path_cls.home = _RealPath.home

        # Patch Path to return our mock for cmdline path, real Path otherwise
        def path_side_effect(*args: Any, **kwargs: Any) -> Any:
            if not args:
                return _RealPath.home()
            if str(args[0]) == cmdline_path_str:
                return cmdline_mock
            return _RealPath(*args, **kwargs)

        mock_path_cls.side_effect = path_side_effect

        from agentalloy.install.subcommands.uninstall import uninstall

        minimal_state: dict[str, Any] = {
            "harness_files_written": [],
            "port": 47950,
        }

        with (
            patch("agentalloy.install.state.load_state", return_value=minimal_state),
            patch("agentalloy.install.state.user_data_dir", return_value=tmp_path / "data"),
            patch("agentalloy.install.state.user_config_dir", return_value=tmp_path / "config"),
        ):
            mock_stop.return_value = "SIGTERM"
            result = uninstall(
                remove_data=False,
                force=True,
                stop_services=True,
            )

        # Verify stop was called with the pid
        mock_stop.assert_called_once_with(12345)

        # Verify the server was recorded as stopped
        files_removed = result.get("files_removed", [])
        stopped = any("stopped_manual_server" in f.get("action", "") for f in files_removed)
        assert stopped, f"No stopped server entry found in: {files_removed}"
