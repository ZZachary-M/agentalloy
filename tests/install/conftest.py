"""Shared pytest fixtures for install subcommand tests."""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from agentalloy.install import state as install_state


@pytest.fixture(autouse=True)
def _clean_install_state():
    """Remove all global install artifacts before and after each test.

    Tests that don't use tmp_state_dir write to global XDG dirs:
    - ~/.config/agentalloy/ (install-state.json, .env, corpus)
    - ~/.local/share/agentalloy/ (outputs, corpus)

    Clean both to prevent cross-test pollution.
    """
    config_dir = install_state.user_config_dir()
    data_dir = install_state.user_data_dir()

    existed_config = config_dir.exists()
    existed_data = data_dir.exists()

    if existed_config:
        shutil.rmtree(config_dir, ignore_errors=True)
    if existed_data:
        shutil.rmtree(data_dir, ignore_errors=True)

    yield

    if config_dir.exists():
        shutil.rmtree(config_dir, ignore_errors=True)
    if data_dir.exists():
        shutil.rmtree(data_dir, ignore_errors=True)


@pytest.fixture
def tmp_state_dir(tmp_path: Path) -> Iterator[tuple[Path, Path]]:
    """Set up a temporary XDG state directory for install tests.

    XDG_DATA_HOME -> tmp/.local/share (outputs_dir() appends 'agentalloy/outputs')
    XDG_CONFIG_HOME -> tmp/.config (user_config_dir() appends 'agentalloy')
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
