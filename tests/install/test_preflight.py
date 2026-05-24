# ruff: noqa: I001, PLC0415 -- testing private module members intentionally
"""Tests for the preflight container phase."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agentalloy.install.subcommands.preflight import (
    _check_compose_binary,  # pyright: ignore[reportPrivateUsage]
    _check_compose_file_present,  # pyright: ignore[reportPrivateUsage]
    _check_image_build_deps,  # pyright: ignore[reportPrivateUsage]
    _detect_compose_binary,  # pyright: ignore[reportPrivateUsage]
    run_preflight,
)


class TestDetectComposeBinary:
    """Test _detect_compose_binary helper."""

    def test_podman_detected(self):
        """Podman is found and compose version succeeds."""
        mock_result = MagicMock()
        mock_result.returncode = 0

        with (
            patch("shutil.which", return_value="/usr/bin/podman"),
            patch("subprocess.run", return_value=mock_result),
        ):
            label, binary_path = _detect_compose_binary()
        assert label == "podman compose"
        assert binary_path == "/usr/bin/podman"

    def test_docker_fallback(self):
        """Podman missing, docker found."""
        mock_result = MagicMock()
        mock_result.returncode = 0

        def which_side_effect(cmd: str) -> str | None:
            if cmd == "podman":
                return None
            return "/usr/bin/docker"

        with (
            patch("shutil.which", side_effect=which_side_effect),
            patch("subprocess.run", return_value=mock_result),
        ):
            label, binary_path = _detect_compose_binary()
        assert label == "docker compose"
        assert binary_path == "/usr/bin/docker"

    def test_none_found(self):
        """Neither podman nor docker found."""
        with patch("shutil.which", return_value=None):
            label, binary_path = _detect_compose_binary()
        assert label is None
        assert binary_path is None

    def test_podman_fails_docker_fallback(self):
        """Podman found but compose version fails, docker works."""

        def run_side_effect(cmd: Any, **kwargs: Any) -> Any:
            mock = MagicMock()
            # cmd is a list like ["/usr/bin/podman", "compose", "version"]
            cmd_str = " ".join(str(c) for c in cmd)
            if "podman" in cmd_str:
                mock.returncode = 1
            else:
                mock.returncode = 0
            return mock

        def which_side_effect(cmd: str) -> str | None:
            if cmd == "podman":
                return "/usr/bin/podman"
            return "/usr/bin/docker"

        with (
            patch("shutil.which", side_effect=which_side_effect),
            patch("subprocess.run", side_effect=run_side_effect),
        ):
            label, binary_path = _detect_compose_binary()
        assert label == "docker compose"
        assert binary_path == "/usr/bin/docker"


class TestComposeBinaryCheck:
    """Test _check_compose_binary check function."""

    def test_check_passes_when_podman_present(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        with (
            patch("shutil.which", return_value="/usr/bin/podman"),
            patch("subprocess.run", return_value=mock_result),
        ):
            result = _check_compose_binary()
        assert result["passed"] is True
        assert "podman compose" in result["detail"]

    def test_check_fails_when_none_found(self):
        with patch("shutil.which", return_value=None):
            result = _check_compose_binary()
        assert result["passed"] is False
        assert result["severity"] == "fatal"
        assert "remediation" in result

    def test_check_returns_docker_when_fallback(self):
        mock_result = MagicMock()
        mock_result.returncode = 0

        def which_side_effect(cmd: str) -> str | None:
            return None if cmd == "podman" else "/usr/bin/docker"

        with (
            patch("shutil.which", side_effect=which_side_effect),
            patch("subprocess.run", return_value=mock_result),
        ):
            result = _check_compose_binary()
        assert result["passed"] is True
        assert "docker compose" in result["detail"]


class TestComposeFilePresentCheck:
    """Test _check_compose_file_present check function."""

    def test_compose_file_present(self, tmp_path: Path):
        compose_file = tmp_path / "compose.yaml"
        compose_file.touch()
        result = _check_compose_file_present(str(compose_file))
        assert result["passed"] is True
        assert str(compose_file) in result["detail"]

    def test_compose_file_missing(self):
        result = _check_compose_file_present("/nonexistent/compose.yaml")
        assert result["passed"] is False
        assert "not found" in result["error"]

    def test_compose_file_none(self):
        result = _check_compose_file_present(None)
        assert result["passed"] is False
        assert "No compose file" in result["error"]


class TestImageBuildDepsCheck:
    """Test _check_image_build_deps check function."""

    def test_containerfile_present(self, tmp_path: Path):
        compose_file = tmp_path / "compose.yaml"
        compose_file.touch()
        containerfile = tmp_path / "Containerfile"
        containerfile.touch()
        result = _check_image_build_deps(str(compose_file))
        assert result["passed"] is True
        assert "Containerfile" in result["detail"]

    def test_dockerfile_fallback(self, tmp_path: Path):
        compose_file = tmp_path / "compose.yaml"
        compose_file.touch()
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.touch()
        result = _check_image_build_deps(str(compose_file))
        assert result["passed"] is True
        assert "Dockerfile" in result["detail"]

    def test_no_build_file(self, tmp_path: Path):
        compose_file = tmp_path / "compose.yaml"
        compose_file.touch()
        result = _check_image_build_deps(str(compose_file))
        assert result["passed"] is False
        assert "No Containerfile" in result["error"]

    def test_none_compose_file_skips(self):
        result = _check_image_build_deps(None)
        assert result["passed"] is True
        assert result["severity"] == "warn"


class TestContainerPhaseEnvelope:
    """Test the full container phase run_preflight."""

    def test_container_phase_runs_all_checks(self, tmp_path: Path):
        compose_file = tmp_path / "compose.yaml"
        compose_file.touch()
        containerfile = tmp_path / "Containerfile"
        containerfile.touch()

        mock_result = MagicMock()
        mock_result.returncode = 0

        def which_side_effect(cmd: str) -> str | None:
            return str(tmp_path / cmd) if cmd in ("podman",) else None

        with (
            patch("shutil.which", side_effect=which_side_effect),
            patch("subprocess.run", return_value=mock_result),
        ):
            result = run_preflight(phase="container", compose_file=str(compose_file))

        check_names = [c["name"] for c in result["checks"]]
        assert "compose_binary" in check_names
        assert "compose_file_present" in check_names
        assert "port_free" in check_names
        assert "image_build_deps" in check_names

    def test_invalid_phase_raises(self):
        with pytest.raises(ValueError, match="invalid phase"):
            run_preflight(phase="invalid")
