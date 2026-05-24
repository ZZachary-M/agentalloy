# ruff: noqa: I001 -- testing private module members intentionally
"""Tests for install state management (schema v3)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from agentalloy.install import state as install_state

# Local aliases for private helpers used across multiple tests
_empty_state = install_state._empty_state  # pyright: ignore[reportPrivateUsage]


class TestSchemaVersion:
    """Test CURRENT_SCHEMA_VERSION is 3."""

    def test_schema_version_is_3(self):
        assert install_state.CURRENT_SCHEMA_VERSION == 3


class TestFreshState:
    """Test _empty_state() returns schema v3 with container fields."""

    def test_fresh_state_has_container_fields(self):
        st = _empty_state()
        assert st["schema_version"] == 3
        assert st["deployment"] is None
        assert st["compose_file"] is None
        assert st["compose_binary"] is None

    def test_fresh_state_has_legacy_fields(self):
        st = _empty_state()
        assert "install_started_at" in st
        assert st["completed_steps"] == []
        assert st["harness_files_written"] == []
        assert st["models_pulled"] == []
        assert st["port"] == 47950
        assert st["last_verify_passed_at"] is None
        assert st["pending_pack_selection"] is None


class TestV2ToV3Migration:
    """Test that v2 state files are migrated to v3 on load."""

    def test_v2_migrated_to_v3(self, tmp_path: Path):
        """A v2 state file loads with new fields defaulted to None."""
        # Set up XDG_CONFIG_HOME pointing to tmp_path
        config_dir = tmp_path / ".config"
        data_dir = tmp_path / ".local" / "share"
        config_dir.mkdir(parents=True)
        data_dir.mkdir(parents=True)
        old_config = os.environ.get("XDG_CONFIG_HOME")
        old_data = os.environ.get("XDG_DATA_HOME")
        os.environ["XDG_CONFIG_HOME"] = str(config_dir)
        os.environ["XDG_DATA_HOME"] = str(data_dir)

        try:
            # Create a v2 state file
            agentalloy_dir = config_dir / "agentalloy"
            agentalloy_dir.mkdir(parents=True)
            state_file = agentalloy_dir / "install-state.json"
            v2_state: dict[str, Any] = {
                "schema_version": 2,
                "install_started_at": "2025-01-01T00:00:00",
                "completed_steps": [],
                "harness_files_written": [],
                "models_pulled": [],
                "env_path": None,
                "port": 47950,
                "last_verify_passed_at": None,
                "pending_pack_selection": None,
            }
            state_file.write_text(json.dumps(v2_state))

            # Force re-import so state_path() picks up the new XDG dir
            import importlib

            importlib.reload(install_state)
            st = install_state.load_state()

            # Should have been migrated to v3
            assert st["schema_version"] == 3
            assert st["deployment"] is None
            assert st["compose_file"] is None
            assert st["compose_binary"] is None
        finally:
            if old_config is not None:
                os.environ["XDG_CONFIG_HOME"] = old_config
            elif "XDG_CONFIG_HOME" in os.environ:
                del os.environ["XDG_CONFIG_HOME"]
            if old_data is not None:
                os.environ["XDG_DATA_HOME"] = old_data
            elif "XDG_DATA_HOME" in os.environ:
                del os.environ["XDG_DATA_HOME"]

    def test_v2_preserves_existing_fields(self, tmp_path: Path):
        """Migration preserves existing v2 fields while adding v3 fields."""
        config_dir = tmp_path / ".config"
        data_dir = tmp_path / ".local" / "share"
        config_dir.mkdir(parents=True)
        data_dir.mkdir(parents=True)
        old_config = os.environ.get("XDG_CONFIG_HOME")
        old_data = os.environ.get("XDG_DATA_HOME")
        os.environ["XDG_CONFIG_HOME"] = str(config_dir)
        os.environ["XDG_DATA_HOME"] = str(data_dir)

        try:
            agentalloy_dir = config_dir / "agentalloy"
            agentalloy_dir.mkdir(parents=True)
            state_file = agentalloy_dir / "install-state.json"
            v2_state: dict[str, Any] = {
                "schema_version": 2,
                "install_started_at": "2025-01-01T00:00:00",
                "completed_steps": [
                    {"step": "wire-harness", "completed_at": "2025-01-01T00:01:00"}
                ],
                "harness_files_written": [],
                "models_pulled": ["ollama:nomic-embed-text"],
                "env_path": None,
                "port": 50000,
                "last_verify_passed_at": "2025-01-01T00:02:00",
                "pending_pack_selection": ["core"],
            }
            state_file.write_text(json.dumps(v2_state))

            import importlib

            importlib.reload(install_state)
            st = install_state.load_state()

            # Existing fields preserved
            assert st["port"] == 50000
            assert st["completed_steps"] == v2_state["completed_steps"]
            assert st["models_pulled"] == ["ollama:nomic-embed-text"]
            assert st["pending_pack_selection"] == ["core"]
            assert st["last_verify_passed_at"] == "2025-01-01T00:02:00"
            # New fields added
            assert st["deployment"] is None
            assert st["compose_file"] is None
            assert st["compose_binary"] is None
        finally:
            if old_config is not None:
                os.environ["XDG_CONFIG_HOME"] = old_config
            elif "XDG_CONFIG_HOME" in os.environ:
                del os.environ["XDG_CONFIG_HOME"]
            if old_data is not None:
                os.environ["XDG_DATA_HOME"] = old_data
            elif "XDG_DATA_HOME" in os.environ:
                del os.environ["XDG_DATA_HOME"]


class TestSaveAndLoadState:
    """Test save_state and load_state round-trip."""

    def test_save_and_load_container_state(self, tmp_path: Path):
        """Container deployment state is saved and loaded correctly."""
        config_dir = tmp_path / ".config"
        data_dir = tmp_path / ".local" / "share"
        config_dir.mkdir(parents=True)
        data_dir.mkdir(parents=True)
        old_config = os.environ.get("XDG_CONFIG_HOME")
        old_data = os.environ.get("XDG_DATA_HOME")
        os.environ["XDG_CONFIG_HOME"] = str(config_dir)
        os.environ["XDG_DATA_HOME"] = str(data_dir)

        try:
            import importlib

            importlib.reload(install_state)
            st = _empty_state()
            st["deployment"] = "container"
            st["compose_file"] = "/home/user/project/compose.yaml"
            st["compose_binary"] = "podman compose"

            fp = install_state.save_state(st)
            assert fp.exists()

            loaded = install_state.load_state()
            assert loaded["deployment"] == "container"
            assert loaded["compose_file"] == "/home/user/project/compose.yaml"
            assert loaded["compose_binary"] == "podman compose"
        finally:
            if old_config is not None:
                os.environ["XDG_CONFIG_HOME"] = old_config
            elif "XDG_CONFIG_HOME" in os.environ:
                del os.environ["XDG_CONFIG_HOME"]
            if old_data is not None:
                os.environ["XDG_DATA_HOME"] = old_data
            elif "XDG_DATA_HOME" in os.environ:
                del os.environ["XDG_DATA_HOME"]


class TestValidatePort:
    """Test validate_port input sanitization."""

    def test_valid_port(self):
        assert install_state.validate_port(47950) == 47950
        assert install_state.validate_port(1) == 1
        assert install_state.validate_port(65535) == 65535

    def test_string_port_exits(self):
        with pytest.raises(SystemExit, match="^2$"):
            install_state.validate_port("1@evil.com:80")

    def test_float_port_exits(self):
        with pytest.raises(SystemExit, match="^2$"):
            install_state.validate_port(3.14)

    def test_bool_port_exits(self):
        with pytest.raises(SystemExit, match="^2$"):
            install_state.validate_port(True)

    def test_negative_port_exits(self):
        with pytest.raises(SystemExit, match="^2$"):
            install_state.validate_port(-1)

    def test_zero_port_exits(self):
        with pytest.raises(SystemExit, match="^2$"):
            install_state.validate_port(0)

    def test_too_large_port_exits(self):
        with pytest.raises(SystemExit, match="^2$"):
            install_state.validate_port(65536)


class TestIsInsideRoot:
    """Test is_inside_root containment guard."""

    def test_path_inside_root(self, tmp_path: Path):
        root = tmp_path
        child = root / "sub" / "file.txt"
        assert install_state.is_inside_root(child, root) is True

    def test_path_outside_root(self, tmp_path: Path):
        root = tmp_path / "project"
        root.mkdir()
        outside = tmp_path / "other" / "file.txt"
        assert install_state.is_inside_root(outside, root) is False

    def test_symlink_escape(self, tmp_path: Path):
        """Symlink outside root is NOT considered inside."""
        root = tmp_path / "project"
        root.mkdir()
        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()
        outside_file = outside_dir / "secret.txt"
        outside_file.touch()
        symlink = root / "link.txt"
        symlink.symlink_to(outside_file)
        assert install_state.is_inside_root(symlink, root) is False


class TestPackSelectionHelpers:
    """Test pending pack selection helpers."""

    def test_get_pending_pack_selection_none(self):
        data = _empty_state()
        assert install_state.get_pending_pack_selection(data) is None

    def test_get_pending_pack_selection_list(self):
        data = _empty_state()
        install_state.set_pending_pack_selection(data, ["core", "framework"])
        result = install_state.get_pending_pack_selection(data)
        assert result == ["core", "framework"]

    def test_clear_pending_pack_selection(self):
        data = _empty_state()
        install_state.set_pending_pack_selection(data, ["core"])
        install_state.clear_pending_pack_selection(data)
        assert install_state.get_pending_pack_selection(data) is None

    def test_get_pending_pack_selection_filters_non_strings(self):
        data = _empty_state()
        data["pending_pack_selection"] = ["core", 123, None, "framework"]
        result = install_state.get_pending_pack_selection(data)
        assert result == ["core", "framework"]


class TestStepTracking:
    """Test record_step and is_step_completed."""

    def test_record_and_check_step(self):
        data = _empty_state()
        install_state.record_step(data, "wire-harness")
        assert install_state.is_step_completed(data, "wire-harness") is True
        assert install_state.is_step_completed(data, "pull-models") is False

    def test_get_step_output(self):
        data = _empty_state()
        install_state.record_step(data, "pull-models", extra={"models": ["ollama:text-embedding"]})
        output = install_state.get_step_output(data, "pull-models")
        assert output is not None
        assert output["step"] == "pull-models"
        assert output["models"] == ["ollama:text-embedding"]
        assert install_state.get_step_output(data, "missing") is None
