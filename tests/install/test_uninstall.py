"""Tests for the uninstall subcommand (container branch).

ruff: noqa: I001, PLC0415 -- testing private module members intentionally
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from agentalloy.install.subcommands.uninstall import (
    _remove_sentinel_block,
    _extract_sentinel_content,
    _stop_container_stack,
)


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

        with patch(
            "subprocess.run", side_effect=OSError("No such file: podman")
        ):
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
        actions = _stop_container_stack(state, warnings)

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

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="timeout", timeout=60)):
            actions = _stop_container_stack(state, warnings)

        assert len(warnings) == 1
        assert "timed out" in warnings[0].lower()
        assert actions[0]["action"] == "compose_down_timeout"


class TestSentinelHelpers:
    """Test sentinel block extraction and removal."""

    def test_extract_sentinel_content_found(self):
        text = "before\n<!-- BEGIN AGENTALLOY -->\nsome content\n<!-- END AGENTALLOY -->\nafter"
        result = _extract_sentinel_content(text, "<!-- BEGIN AGENTALLOY -->", "<!-- END AGENTALLOY -->")
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
        result = _remove_sentinel_block(text, "<!-- BEGIN AGENTALLOY -->", "<!-- END AGENTALLOY -->")
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
        from agentalloy.install.subcommands.uninstall import _remove_pulled_models

        actions = _remove_pulled_models({})
        assert actions == []

    def test_malformed_entry_skipped(self):
        from agentalloy.install.subcommands.uninstall import _remove_pulled_models

        actions = _remove_pulled_models({"models_pulled": [123, None, ""]})
        for action in actions:
            assert action["action"] in ("skipped_malformed_entry", "skipped_empty_fields")

    def test_unmanaged_runner_skipped(self):
        from agentalloy.install.subcommands.uninstall import _remove_pulled_models

        actions = _remove_pulled_models({"models_pulled": ["lm-studio:some-model"]})
        assert len(actions) == 1
        assert actions[0]["action"] == "skipped_unmanaged_runner"
