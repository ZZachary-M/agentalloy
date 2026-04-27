"""Unit tests for the ``enable-service`` subcommand."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from skillsmith.install.subcommands.enable_service import (
    _detect_container_runtimes,  # pyright: ignore[reportPrivateUsage]
    _detect_os,  # pyright: ignore[reportPrivateUsage]
    _native_available,  # pyright: ignore[reportPrivateUsage]
    _poll_health,  # pyright: ignore[reportPrivateUsage]
    _read_env_file,  # pyright: ignore[reportPrivateUsage]
    _render_launchd_plist,  # pyright: ignore[reportPrivateUsage]
    _render_systemd_unit,  # pyright: ignore[reportPrivateUsage]
    _resolve_compose_file,  # pyright: ignore[reportPrivateUsage]
    enable_service,
)

# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------


class TestDetectOS:
    def test_returns_linux_on_linux(self) -> None:
        with patch("platform.system", return_value="Linux"):
            assert _detect_os() == "linux"

    def test_returns_macos_on_darwin(self) -> None:
        with patch("platform.system", return_value="Darwin"):
            assert _detect_os() == "macos"

    def test_returns_windows(self) -> None:
        with patch("platform.system", return_value="Windows"):
            assert _detect_os() == "windows"


class TestNativeAvailable:
    def test_linux_with_systemctl(self) -> None:
        with (
            patch("platform.system", return_value="Linux"),
            patch("shutil.which", return_value="/usr/bin/systemctl"),
        ):
            assert _native_available() is True

    def test_linux_without_systemctl(self) -> None:
        with (
            patch("platform.system", return_value="Linux"),
            patch("shutil.which", return_value=None),
        ):
            assert _native_available() is False

    def test_macos_with_launchctl(self) -> None:
        with (
            patch("platform.system", return_value="Darwin"),
            patch("shutil.which", return_value="/bin/launchctl"),
        ):
            assert _native_available() is True

    def test_windows_always_false(self) -> None:
        with patch("platform.system", return_value="Windows"):
            assert _native_available() is False


class TestDetectContainerRuntimes:
    def test_podman_first(self) -> None:
        def which(cmd: str) -> str | None:
            return f"/usr/bin/{cmd}" if cmd in ("podman", "docker") else None

        with patch("shutil.which", side_effect=which):
            result = _detect_container_runtimes()
        assert result == ["podman", "docker"]

    def test_only_docker(self) -> None:
        def which(cmd: str) -> str | None:
            return "/usr/bin/docker" if cmd == "docker" else None

        with patch("shutil.which", side_effect=which):
            result = _detect_container_runtimes()
        assert result == ["docker"]

    def test_none_available(self) -> None:
        with patch("shutil.which", return_value=None):
            assert _detect_container_runtimes() == []


class TestResolveComposeFile:
    def test_radeon_returns_radeon_file(self, tmp_path: Path) -> None:
        (tmp_path / "compose.radeon.yaml").touch()
        (tmp_path / "compose.yaml").touch()
        result = _resolve_compose_file(tmp_path, "radeon")
        assert result.name == "compose.radeon.yaml"

    def test_radeon_fallback_when_file_missing(self, tmp_path: Path) -> None:
        (tmp_path / "compose.yaml").touch()
        result = _resolve_compose_file(tmp_path, "radeon")
        assert result.name == "compose.yaml"

    def test_cpu_returns_default_compose(self, tmp_path: Path) -> None:
        (tmp_path / "compose.yaml").touch()
        result = _resolve_compose_file(tmp_path, "cpu")
        assert result.name == "compose.yaml"

    def test_none_preset_returns_default_compose(self, tmp_path: Path) -> None:
        (tmp_path / "compose.yaml").touch()
        result = _resolve_compose_file(tmp_path, None)
        assert result.name == "compose.yaml"


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------


class TestRenderSystemdUnit:
    def test_contains_exec_start(self) -> None:
        content = _render_systemd_unit(
            "/usr/bin/uv", Path("/app"), 8000, Path("/home/u/.config/skillsmith/.env")
        )
        assert "ExecStart=/usr/bin/uv run uvicorn skillsmith.app:app" in content
        assert "--port 8000" in content

    def test_contains_working_directory(self) -> None:
        content = _render_systemd_unit(
            "/usr/bin/uv", Path("/app"), 8000, Path("/home/u/.config/skillsmith/.env")
        )
        assert "WorkingDirectory=/app" in content

    def test_contains_environment_file(self) -> None:
        content = _render_systemd_unit(
            "/usr/bin/uv", Path("/app"), 8000, Path("/home/u/.config/skillsmith/.env")
        )
        assert "EnvironmentFile=/home/u/.config/skillsmith/.env" in content

    def test_has_install_section(self) -> None:
        content = _render_systemd_unit("/usr/bin/uv", Path("/app"), 8000, Path("/env"))
        assert "[Install]" in content
        assert "WantedBy=default.target" in content


class TestRenderLaunchdPlist:
    def test_valid_xml_structure(self) -> None:
        content = _render_launchd_plist("/usr/bin/uv", Path("/app"), 8000, {"LOG_LEVEL": "INFO"})
        assert '<?xml version="1.0"' in content
        assert "<key>Label</key>" in content
        assert "<string>ai.skillsmith</string>" in content

    def test_port_injected(self) -> None:
        content = _render_launchd_plist("/usr/bin/uv", Path("/app"), 9000, {})
        assert "<string>9000</string>" in content

    def test_env_vars_inlined(self) -> None:
        content = _render_launchd_plist("/usr/bin/uv", Path("/app"), 8000, {"MY_KEY": "MY_VAL"})
        assert "<key>MY_KEY</key>" in content
        assert "<string>MY_VAL</string>" in content

    def test_run_at_load_true(self) -> None:
        content = _render_launchd_plist("/usr/bin/uv", Path("/app"), 8000, {})
        assert "<key>RunAtLoad</key>" in content
        assert "<true/>" in content


class TestReadEnvFile:
    def test_parses_key_value(self, tmp_path: Path) -> None:
        env = tmp_path / ".env"
        env.write_text("FOO=bar\nBAZ=qux\n")
        assert _read_env_file(env) == {"FOO": "bar", "BAZ": "qux"}

    def test_skips_comments(self, tmp_path: Path) -> None:
        env = tmp_path / ".env"
        env.write_text("# comment\nKEY=val\n")
        assert _read_env_file(env) == {"KEY": "val"}

    def test_strips_quotes(self, tmp_path: Path) -> None:
        env = tmp_path / ".env"
        env.write_text('KEY="quoted"\n')
        assert _read_env_file(env) == {"KEY": "quoted"}

    def test_handles_export_prefix(self, tmp_path: Path) -> None:
        env = tmp_path / ".env"
        env.write_text("export KEY=val\n")
        assert _read_env_file(env) == {"KEY": "val"}

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert _read_env_file(tmp_path / "nonexistent.env") == {}


# ---------------------------------------------------------------------------
# Poll health
# ---------------------------------------------------------------------------


class TestPollHealth:
    def test_returns_true_on_ok_status(self) -> None:
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = b'{"status": "ok"}'

        with patch("urllib.request.urlopen", return_value=mock_resp):
            assert _poll_health(8000) is True

    def test_returns_false_on_timeout(self) -> None:
        import urllib.error

        with (
            patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")),
            patch("skillsmith.install.subcommands.enable_service._HEALTH_TIMEOUT_S", 0),
        ):
            assert _poll_health(8000) is False

    def test_returns_false_on_degraded_status(self) -> None:
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = b'{"status": "degraded"}'

        with (
            patch("urllib.request.urlopen", return_value=mock_resp),
            patch(
                "skillsmith.install.subcommands.enable_service._HEALTH_TIMEOUT_S",
                0,
            ),
        ):
            assert _poll_health(8000) is False


# ---------------------------------------------------------------------------
# enable_service() integration-level unit tests (all I/O mocked)
# ---------------------------------------------------------------------------


class TestEnableServiceManual:
    def test_manual_mode_returns_correct_schema(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        result = enable_service(mode="manual", port=8000, repo_root=tmp_path)
        assert result["schema_version"] == 1
        assert result["mode"] == "manual"
        assert result["service_started"] is False
        assert result["runtime"] is None
        assert result["unit_path"] is None

    def test_manual_mode_prints_serve_hint(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        enable_service(mode="manual", port=8000, repo_root=tmp_path)
        captured = capsys.readouterr()
        assert "skillsmith serve" in captured.err


class TestEnableServiceInvalidMode:
    def test_unknown_mode_exits(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit):
            enable_service(mode="bogus", port=8000, repo_root=tmp_path)


class TestEnableServiceContainer:
    def test_container_mode_no_runtime_exits(self, tmp_path: Path) -> None:
        with patch("shutil.which", return_value=None), pytest.raises(SystemExit):
            enable_service(mode="container", port=8000, repo_root=tmp_path)

    def test_container_mode_missing_compose_file_exits(self, tmp_path: Path) -> None:
        with patch("shutil.which", return_value="/usr/bin/podman"), pytest.raises(SystemExit):
            enable_service(mode="container", runtime="podman", port=8000, repo_root=tmp_path)

    def test_container_mode_runs_compose_up(self, tmp_path: Path) -> None:
        compose_file = tmp_path / "compose.yaml"
        compose_file.touch()

        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = b'{"status": "ok"}'

        with (
            patch("shutil.which", return_value="/usr/bin/podman"),
            patch("subprocess.run") as mock_run,
            patch("urllib.request.urlopen", return_value=mock_resp),
        ):
            result = enable_service(
                mode="container",
                runtime="podman",
                port=8000,
                repo_root=tmp_path,
            )

        assert result["mode"] == "container"
        assert result["runtime"] == "podman"
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "podman"
        assert "up" in cmd

    def test_radeon_uses_radeon_compose_file(self, tmp_path: Path) -> None:
        (tmp_path / "compose.yaml").touch()
        (tmp_path / "compose.radeon.yaml").touch()

        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = b'{"status": "ok"}'

        with (
            patch("shutil.which", return_value="/usr/bin/podman"),
            patch("subprocess.run"),
            patch("urllib.request.urlopen", return_value=mock_resp),
        ):
            result = enable_service(
                mode="container",
                runtime="podman",
                port=8000,
                repo_root=tmp_path,
                preset="radeon",
            )

        assert "radeon" in result["compose_file"]


class TestEnableServiceNativeWindows:
    def test_windows_native_exits(self, tmp_path: Path) -> None:
        with patch("platform.system", return_value="Windows"), pytest.raises(SystemExit):
            enable_service(mode="native", port=8000, repo_root=tmp_path)


class TestOutputSchema:
    def test_all_required_keys_present(self, tmp_path: Path) -> None:
        result = enable_service(mode="manual", port=8000, repo_root=tmp_path)
        for key in (
            "schema_version",
            "mode",
            "runtime",
            "unit_path",
            "compose_file",
            "ollama_unit_written",
            "service_started",
        ):
            assert key in result, f"missing key: {key}"

    def test_schema_version_is_1(self, tmp_path: Path) -> None:
        result = enable_service(mode="manual", port=8000, repo_root=tmp_path)
        assert result["schema_version"] == 1
