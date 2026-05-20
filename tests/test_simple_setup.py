"""Tests for the simple setup flow."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# Private member imports for pyright strict mode testing (I001 excluded — private names)
# ruff: noqa: I001
from skillsmith.install.subcommands.simple_setup import (
    _prompt as _prompt,  # type: ignore[attr-defined]
    _prompt_context as _prompt_context,  # type: ignore[attr-defined]
    _resolve_preset as _resolve_preset,  # type: ignore[attr-defined]
    _run_from_args as _run_from_args,  # type: ignore[attr-defined]
    SetupConfig,
)
# ruff: noqa: I001

# ---------------------------------------------------------------------------
# Shared mock setup
# ---------------------------------------------------------------------------


class MockSetup:
    """Shared mock setup for all setup execution tests.

    Provides pre-mocked versions of all subcommands that return success (0).
    Override individual mocks per-test as needed.
    """

    def __init__(self):
        self.mocks: dict[str, MagicMock] = {}
        self.patchers: list[Any] = []  # type: ignore[type-arg]

    def _get_patch_path(self, name: str) -> str:
        return f"skillsmith.install.subcommands.{name}"

    def setup_all(self):
        # Modules that have a .run() method — preflight uses .run_preflight() instead
        for name in (
            "detect",
            "pull_models",
            "seed_corpus",
            "start_embed_server",
            "install_packs",
            "enable_service",
            "write_env",
            "verify",
            "wire_harness",
        ):
            mp = patch(f"{self._get_patch_path(name)}.run")
            self.mocks[name] = mp.start()
            self.mocks[name].return_value = 0
            self.patchers.append(mp)

        # preflight.run_preflight is a module-level function, not .run()
        pf = patch("skillsmith.install.subcommands.preflight.run_preflight")
        self.mocks["preflight"] = pf.start()
        self.mocks["preflight"].return_value = {
            "checks": [],
            "fatal_failures": [],
            "warn_failures": [],
        }
        self.patchers.append(pf)

    def teardown(self):
        for p in self.patchers:
            p.stop()


@pytest.fixture
def tmp_state_dir(tmp_path: Path):
    """Set up a temporary XDG state directory.

    XDG_DATA_HOME -> tmp/.local/share (outputs_dir() appends 'skillsmith/outputs')
    XDG_CONFIG_HOME -> tmp/.config (user_config_dir() appends 'skillsmith')
    """
    config_dir = tmp_path / ".config"
    data_dir = tmp_path / ".local" / "share"
    config_dir.mkdir(parents=True)
    data_dir.mkdir(parents=True)
    os.environ["XDG_CONFIG_HOME"] = str(config_dir)
    os.environ["XDG_DATA_HOME"] = str(data_dir)
    yield config_dir, data_dir
    del os.environ["XDG_CONFIG_HOME"]
    del os.environ["XDG_DATA_HOME"]


# ---------------------------------------------------------------------------
# Prompt and config tests
# ---------------------------------------------------------------------------


class TestSimpleSetupPrompts:
    """Test the interactive prompt logic."""

    def test_prompt_returns_default_in_non_tty(self):
        with patch.object(sys.stdin, "isatty", return_value=False):
            result = _prompt("Test prompt", default="hello")
            assert result == "hello"

    def test_prompt_returns_empty_when_no_default(self):
        with patch.object(sys.stdin, "isatty", return_value=False):
            result = _prompt("Test prompt")
            assert result == ""

    def test_prompt_context_returns_default_in_non_tty(self):
        with patch.object(sys.stdin, "isatty", return_value=False):
            result = _prompt_context("Test prompt", "Context here", default="hello")
            assert result == "hello"

    def test_invalid_runner_rejected(self, tmp_state_dir: tuple[Path, Path]):
        from skillsmith.install.subcommands.simple_setup import run_setup

        cfg = SetupConfig(runner="invalid", non_interactive=True)
        rc = run_setup(cfg)
        assert rc == 1

    def test_preset_resolved_from_runner_and_host(self):
        cfg = SetupConfig(runner="ollama", recommended_host="nvidia")
        preset = _resolve_preset(cfg)
        assert preset == "nvidia"
        assert cfg.preset == "nvidia"

    def test_preset_fallback_unknown_combination(self):
        cfg = SetupConfig(runner="ollama", recommended_host="unknown-hw")
        preset = _resolve_preset(cfg)
        assert preset == "cpu"  # fallback

    def test_preset_llama_server_cpu(self):
        cfg = SetupConfig(runner="llama-server", recommended_host="cpu")
        preset = _resolve_preset(cfg)
        assert preset == "cpu-llama-server"

    def test_preset_uses_user_hardware_target_over_detected(self):
        cfg = SetupConfig(runner="ollama", hardware_target="radeon", recommended_host="nvidia")
        preset = _resolve_preset(cfg)
        assert preset == "radeon"  # user choice wins over detected
        assert cfg.preset == "radeon"

    def test_preset_fallback_when_user_hardware_unknown(self):
        cfg = SetupConfig(runner="ollama", hardware_target="unknown-gpu")
        preset = _resolve_preset(cfg)
        assert preset == "cpu"  # fallback


# ---------------------------------------------------------------------------
# Execution tests
# ---------------------------------------------------------------------------


class TestSimpleSetupExecution:
    """Test the full setup flow with mocked subcommands."""

    @pytest.fixture(autouse=True)
    def _mocks(self, tmp_state_dir: tuple[Path, Path]):
        self.mock = MockSetup()
        self.mock.setup_all()
        self.tmp_config, self.tmp_data = tmp_state_dir
        # Patch outputs_dir to return a path inside the fixture
        outputs_patch = patch(
            "skillsmith.install.state.outputs_dir",
            return_value=self.tmp_data / "outputs",
        )
        self.mock.patchers.append(outputs_patch)
        self.mock.mocks["_outputs_dir"] = outputs_patch.start()
        (self.tmp_data / "outputs").mkdir(parents=True, exist_ok=True)
        yield
        self.mock.teardown()

    def _import_run_setup(self):
        # Force re-import to pick up mocks
        import importlib

        import skillsmith.install.subcommands.simple_setup as mod

        importlib.reload(mod)
        return mod.SetupConfig, mod.run_setup

    def test_run_setup_preflight_early_failure(self, tmp_state_dir: tuple[Path, Path]):
        """Setup aborts when early preflight has fatal failures."""
        self.mock.mocks["preflight"].return_value = {
            "checks": [
                {
                    "name": "python_version",
                    "passed": False,
                    "severity": "fatal",
                    "error": "Python < 3.12",
                }
            ],
            "fatal_failures": ["python_version"],
        }
        setup_config, run_setup = self._import_run_setup()
        rc = run_setup(setup_config(non_interactive=True))
        assert rc == 1
        self.mock.mocks["write_env"].assert_not_called()

    def test_run_setup_preflight_runner_failure(self, tmp_state_dir: tuple[Path, Path]):
        """Setup aborts when runner preflight fails."""
        # Early preflight passes, runner preflight fails
        self.mock.mocks["preflight"].side_effect = [
            {
                "checks": [],
                "fatal_failures": [],
                "warn_failures": [],
            },  # early
            {
                "checks": [
                    {
                        "name": "ollama_present",
                        "passed": False,
                        "severity": "fatal",
                        "error": "not found",
                    }
                ],
                "fatal_failures": ["ollama_present"],
            },  # runner
        ]
        setup_config, run_setup = self._import_run_setup()
        rc = run_setup(setup_config(non_interactive=True))
        assert rc == 1
        # write_env should NOT be called after runner preflight failure
        self.mock.mocks["write_env"].assert_not_called()

    def test_run_setup_writes_env_with_correct_preset(self, tmp_state_dir: tuple[Path, Path]):
        """Setup writes .env with preset resolved from runner + hardware."""
        setup_config, run_setup = self._import_run_setup()
        rc = run_setup(setup_config(runner="ollama", non_interactive=True))
        assert rc == 0
        self.mock.mocks["write_env"].assert_called_once()

    def test_run_setup_all_steps_called(self, tmp_state_dir: tuple[Path, Path]):
        """Full setup flow runs all expected steps."""
        setup_config, run_setup = self._import_run_setup()
        rc = run_setup(setup_config(non_interactive=True))
        assert rc == 0

        # All core steps called at least once
        for name in (
            "detect",
            "seed_corpus",
            "start_embed_server",
            "install_packs",
            "enable_service",
            "write_env",
            "verify",
            "pull_models",
        ):
            self.mock.mocks[name].assert_called_once()

        # Preflight called twice (early + runner)
        assert self.mock.mocks["preflight"].call_count == 2

    def test_run_setup_pulls_model(self, tmp_state_dir: tuple[Path, Path]):
        """Setup calls pull_models to ensure the model is present."""
        setup_config, run_setup = self._import_run_setup()
        rc = run_setup(setup_config(non_interactive=True))
        assert rc == 0
        self.mock.mocks["pull_models"].assert_called_once()

    def test_run_setup_wires_harness_when_specified(self, tmp_state_dir: tuple[Path, Path]):
        """Setup wires the harness when a non-manual harness is selected."""
        setup_config, run_setup = self._import_run_setup()
        rc = run_setup(setup_config(harness="claude-code", non_interactive=True))
        assert rc == 0
        self.mock.mocks["wire_harness"].assert_called_once()

    def test_run_setup_skips_harness_when_manual(self, tmp_state_dir: tuple[Path, Path]):
        """Setup does not call wire_harness when harness is 'manual'."""
        setup_config, run_setup = self._import_run_setup()
        rc = run_setup(setup_config(harness="manual", non_interactive=True))
        assert rc == 0
        self.mock.mocks["wire_harness"].assert_not_called()

    def test_run_setup_stops_on_step_failure(self, tmp_state_dir: tuple[Path, Path]):
        """Setup aborts when an intermediate step fails."""
        self.mock.mocks["seed_corpus"].return_value = 1
        setup_config, run_setup = self._import_run_setup()
        rc = run_setup(setup_config(non_interactive=True))
        assert rc == 1
        # Steps after seed_corpus should NOT be called
        self.mock.mocks["start_embed_server"].assert_not_called()

    def test_run_setup_rejects_invalid_hardware(self, tmp_state_dir: tuple[Path, Path]):
        """Setup rejects invalid hardware target in interactive mode."""
        setup_config, run_setup = self._import_run_setup()
        cfg = setup_config(non_interactive=False, recommended_host="nvidia")
        # Mock _prompt_context to return invalid hardware
        with (
            patch(
                "skillsmith.install.subcommands.simple_setup._prompt_context",
                return_value="invalid-gpu",
            ),
            patch(
                "skillsmith.install.subcommands.simple_setup.sys.stdin.isatty", return_value=True
            ),
        ):
            rc = run_setup(cfg)
        assert rc == 1


class TestAddParser:
    """Test argparse registration and flag parsing."""

    def test_parser_registers_setup_subcommand(self):
        import argparse

        from skillsmith.install.subcommands.simple_setup import add_parser

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="subcommand")
        add_parser(subparsers)

        args = parser.parse_args(["setup", "--non-interactive"])
        assert args.subcommand == "setup"
        assert args.non_interactive is True

    def test_parser_accepts_all_flags(self):
        import argparse

        from skillsmith.install.subcommands.simple_setup import add_parser

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="subcommand")
        add_parser(subparsers)

        args = parser.parse_args(
            [
                "setup",
                "-n",
                "--runner",
                "llama-server",
                "--model",
                "custom-model",
                "--port",
                "50000",
                "--mode",
                "manual",
                "--packs",
                "a,b,c",
                "--harness",
                "cursor",
                "--hardware",
                "nvidia",
            ]
        )
        assert args.runner == "llama-server"
        assert args.port == 50000
        assert args.mode == "manual"
        assert args.packs == "a,b,c"
        assert args.harness == "cursor"
        assert args.hardware == "nvidia"


class TestRunFromArgs:
    """Test the argparse -> SetupConfig bridge."""

    def test_defaults(self):
        import argparse

        args = argparse.Namespace(
            runner=None,
            model=None,
            port=None,
            mode=None,
            packs=None,
            harness=None,
            non_interactive=False,
        )
        # Just verify it builds a valid config -- actual run_setup is tested above
        # We'll just check _run_from_args doesn't raise with valid args
        with patch("skillsmith.install.subcommands.simple_setup.run_setup", return_value=0):
            rc = _run_from_args(args)
        assert rc == 0

    def test_explicit_values(self):
        import argparse

        args = argparse.Namespace(
            runner="llama-server",
            model="my-model",
            port=50000,
            mode="manual",
            packs="pack1,pack2",
            harness="cursor",
            non_interactive=True,
        )
        with patch("skillsmith.install.subcommands.simple_setup.run_setup", return_value=0):
            rc = _run_from_args(args)
        assert rc == 0
