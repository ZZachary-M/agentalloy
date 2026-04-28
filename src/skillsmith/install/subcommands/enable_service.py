"""``enable-service`` subcommand.

Registers Skillsmith as a persistent background service so it starts
automatically without requiring ``skillsmith serve`` each session.

Three modes
-----------
native
    Linux: writes a systemd user unit (~/.config/systemd/user/skillsmith.service)
    and enables + starts it. No root required.

    macOS: writes a launchd LaunchAgent plist
    (~/Library/LaunchAgents/ai.skillsmith.plist) and loads it.

    Windows: not implemented (v1.1).

container
    Runs ``podman compose`` or ``docker compose up -d`` with the appropriate
    compose file. Radeon preset uses compose.radeon.yaml (skillsmith-only;
    LM Studio lives on the host at host.containers.internal:1234). All other
    presets use compose.yaml (skillsmith + Ollama bundled).

manual
    No-op: prints the ``skillsmith serve`` command and exits. Records the
    choice in state so subsequent steps know the mode.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import xml.sax.saxutils
from pathlib import Path
from typing import Any

from skillsmith.install import state as install_state

SCHEMA_VERSION = 1

# How long to poll /health after starting the container stack.
_HEALTH_TIMEOUT_S = 30
_HEALTH_POLL_S = 2


# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------


def _detect_os() -> str:
    """Return 'linux', 'macos', or 'windows'."""
    s = platform.system().lower()
    if s == "darwin":
        return "macos"
    if s == "windows":
        return "windows"
    return "linux"


def _native_available() -> bool:
    """True if a supported native service manager is present."""
    os_name = _detect_os()
    if os_name == "linux":
        return shutil.which("systemctl") is not None
    if os_name == "macos":
        return shutil.which("launchctl") is not None
    return False


def _detect_container_runtimes() -> list[str]:
    """Return available container runtimes, podman first."""
    runtimes: list[str] = []
    for rt in ("podman", "docker"):
        if shutil.which(rt):
            runtimes.append(rt)
    return runtimes


def _resolve_compose_file(repo_root: Path, preset: str | None) -> Path:
    """Return the correct compose file path for the preset."""
    if preset == "radeon":
        candidate = repo_root / "compose.radeon.yaml"
        if candidate.exists():
            return candidate
    return repo_root / "compose.yaml"


def _poll_health(port: int) -> bool:
    """Poll /health until ok/degraded or timeout. Returns True on success."""
    url = f"http://127.0.0.1:{port}/health"
    deadline = time.monotonic() + _HEALTH_TIMEOUT_S
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:
                data = json.loads(resp.read())
                status = data.get("status")
                if status == "ok":
                    return True
                if status == "degraded":
                    print(
                        "NOTE: Service is degraded (model still warming up). "
                        "It will become fully available shortly.",
                        file=sys.stderr,
                    )
                    return True
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            pass
        time.sleep(_HEALTH_POLL_S)
    return False


# ---------------------------------------------------------------------------
# Native: Linux systemd user unit
# ---------------------------------------------------------------------------


def _systemd_unit_path() -> Path:
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    unit_dir = config_home / "systemd" / "user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    return unit_dir / "skillsmith.service"


def _sanitize_env_for_systemd(env_path: Path) -> Path:
    """Write a systemd-compatible env file (no export, no quotes, no shell expansion).

    systemd's EnvironmentFile parser is strict: bare KEY=VALUE only.
    Returns path to the sanitized file (written next to the original).
    """
    sanitized_path = env_path.parent / "skillsmith.env"
    lines: list[str] = []
    for raw in (env_path.read_text() if env_path.exists() else "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
            val = val[1:-1]
        if key:
            lines.append(f"{key}={val}")
    install_state._atomic_write(sanitized_path, "\n".join(lines) + "\n")  # pyright: ignore[reportPrivateUsage]
    return sanitized_path


def _render_systemd_unit(uv_bin: str, repo_root: Path, port: int, env_path: Path) -> str:
    uvicorn_bin = repo_root / ".venv" / "bin" / "uvicorn"
    if uvicorn_bin.exists():
        exec_start = f"{uvicorn_bin} skillsmith.app:app --host 127.0.0.1 --port {port}"
        extra_env = f"Environment=VIRTUAL_ENV={repo_root / '.venv'}\n"
    else:
        exec_start = f"{uv_bin} run uvicorn skillsmith.app:app --host 127.0.0.1 --port {port}"
        extra_env = f"Environment=HOME={Path.home()}\n"
    return (
        "[Unit]\n"
        "Description=Skillsmith skill composition service\n"
        "After=network.target\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        f"EnvironmentFile={env_path}\n"
        f"{extra_env}"
        f"ExecStart={exec_start}\n"
        f"WorkingDirectory={repo_root}\n"
        "Restart=on-failure\n"
        "RestartSec=5\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def _ollama_unit_exists() -> bool:
    for scope in (["--user"], ["--system", "--global"]):
        try:
            result = subprocess.run(
                ["systemctl", *scope, "cat", "ollama.service"],
                capture_output=True,
                timeout=5,
            )
            if result.returncode == 0:
                return True
        except (OSError, subprocess.TimeoutExpired):
            pass
    return False


def _write_ollama_unit(uv_bin: str) -> Path | None:  # noqa: ARG001
    """Write a minimal ollama user unit. Returns path or None on failure."""
    ollama_bin = shutil.which("ollama")
    if not ollama_bin:
        return None
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    unit_dir = config_home / "systemd" / "user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    unit_path = unit_dir / "ollama.service"
    content = (
        "[Unit]\n"
        "Description=Ollama embedding service\n"
        "After=network.target\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        f"ExecStart={ollama_bin} serve\n"
        "Restart=on-failure\n"
        "RestartSec=5\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )
    install_state._atomic_write(unit_path, content)  # pyright: ignore[reportPrivateUsage]
    return unit_path


def _enable_native_linux(
    uv_bin: str, repo_root: Path, port: int, preset: str | None
) -> dict[str, Any]:
    env_path = _sanitize_env_for_systemd(install_state.env_path())
    unit_path = _systemd_unit_path()
    content = _render_systemd_unit(uv_bin, repo_root, port, env_path)
    install_state._atomic_write(unit_path, content)  # pyright: ignore[reportPrivateUsage]

    ollama_unit_written = False
    if preset != "radeon" and not _ollama_unit_exists():
        written = _write_ollama_unit(uv_bin)
        ollama_unit_written = written is not None
        if ollama_unit_written:
            subprocess.run(
                ["systemctl", "--user", "enable", "--now", "ollama.service"], check=False
            )

    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", "skillsmith.service"], check=True)

    if preset == "radeon":
        print(
            "NOTE: LM Studio cannot be managed by systemd. Enable 'Start on Login' "
            "in LM Studio → Settings so the embedding server starts automatically.",
            file=sys.stderr,
        )

    return {
        "unit_path": str(unit_path),
        "ollama_unit_written": ollama_unit_written,
    }


# ---------------------------------------------------------------------------
# Native: macOS launchd plist
# ---------------------------------------------------------------------------


def _launchd_plist_path() -> Path:
    agents_dir = Path.home() / "Library" / "LaunchAgents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    return agents_dir / "ai.skillsmith.plist"


def _xml_str(value: str) -> str:
    return f"<string>{xml.sax.saxutils.escape(value)}</string>"


def _render_launchd_plist(uv_bin: str, repo_root: Path, port: int, env_vars: dict[str, str]) -> str:
    env_entries = "\n".join(
        f"    <key>{xml.sax.saxutils.escape(k)}</key>\n    {_xml_str(v)}"
        for k, v in env_vars.items()
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"'
        ' "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n'
        "<dict>\n"
        "  <key>Label</key>\n"
        "  <string>ai.skillsmith</string>\n"
        "  <key>ProgramArguments</key>\n"
        "  <array>\n"
        f"    {_xml_str(uv_bin)}\n"
        "    <string>run</string>\n"
        "    <string>uvicorn</string>\n"
        "    <string>skillsmith.app:app</string>\n"
        "    <string>--host</string>\n"
        "    <string>127.0.0.1</string>\n"
        "    <string>--port</string>\n"
        f"    {_xml_str(str(port))}\n"
        "  </array>\n"
        "  <key>WorkingDirectory</key>\n"
        f"  {_xml_str(str(repo_root))}\n"
        "  <key>EnvironmentVariables</key>\n"
        "  <dict>\n"
        f"{env_entries}\n"
        "  </dict>\n"
        "  <key>RunAtLoad</key>\n"
        "  <true/>\n"
        "  <key>KeepAlive</key>\n"
        "  <true/>\n"
        "  <key>StandardOutPath</key>\n"
        "  <string>/tmp/skillsmith.log</string>\n"
        "  <key>StandardErrorPath</key>\n"
        "  <string>/tmp/skillsmith.log</string>\n"
        "</dict>\n"
        "</plist>\n"
    )


def _read_env_file(env_path: Path) -> dict[str, str]:
    """Parse .env into a dict for inlining into the launchd plist."""
    if not env_path.exists():
        return {}
    env_vars: dict[str, str] = {}
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
            val = val[1:-1]
        if key:
            env_vars[key] = val
    return env_vars


def _enable_native_macos(
    uv_bin: str, repo_root: Path, port: int, preset: str | None
) -> dict[str, Any]:
    env_vars = _read_env_file(install_state.env_path())
    plist_path = _launchd_plist_path()
    content = _render_launchd_plist(uv_bin, repo_root, port, env_vars)
    install_state._atomic_write(plist_path, content)  # pyright: ignore[reportPrivateUsage]
    os.chmod(plist_path, 0o600)

    # Unload first in case it's already loaded (idempotent re-run).
    subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True)
    subprocess.run(["launchctl", "load", "-w", str(plist_path)], check=True)

    if preset == "radeon":
        print(
            "NOTE: LM Studio cannot be managed by launchd. Enable 'Start on Login' "
            "in LM Studio → Settings so the embedding server starts automatically.",
            file=sys.stderr,
        )

    return {
        "unit_path": str(plist_path),
        "ollama_unit_written": False,
    }


# ---------------------------------------------------------------------------
# Container path
# ---------------------------------------------------------------------------


def _enable_container(
    runtime: str,
    compose_file: Path,
    port: int,
) -> dict[str, Any]:
    cmd = [runtime, "compose", "-f", str(compose_file), "up", "-d", "--build"]
    print(f"Running: {' '.join(cmd)}", file=sys.stderr)
    subprocess.run(cmd, check=True)

    print(f"Waiting up to {_HEALTH_TIMEOUT_S}s for service health...", file=sys.stderr)
    healthy = _poll_health(port)
    if not healthy:
        print(
            f"WARNING: /health did not return ok within {_HEALTH_TIMEOUT_S}s. "
            f"Check `{runtime} compose logs skillsmith` for details.",
            file=sys.stderr,
        )

    return {
        "compose_file": str(compose_file),
        "service_started": healthy,
    }


# ---------------------------------------------------------------------------
# Main enable_service function
# ---------------------------------------------------------------------------


def enable_service(
    mode: str,
    runtime: str | None = None,
    port: int = 47950,
    repo_root: Path | None = None,
    preset: str | None = None,
) -> dict[str, Any]:
    """Enable the Skillsmith service. Returns the contract-shaped result."""
    if repo_root is None:
        # Best-effort: find the package root from this file's location.
        repo_root = Path(__file__).resolve().parents[4]

    uv_bin = shutil.which("uv") or sys.executable

    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "mode": mode,
        "runtime": None,
        "unit_path": None,
        "compose_file": None,
        "ollama_unit_written": False,
        "service_started": False,
    }

    if mode == "native":
        os_name = _detect_os()
        if os_name == "windows":
            print("ERROR: Native service mode is not supported on Windows (v1.1).", file=sys.stderr)
            print("FIX:   Use --mode container or --mode manual.", file=sys.stderr)
            raise SystemExit(1)
        if os_name == "linux":
            details = _enable_native_linux(uv_bin, repo_root, port, preset)
        else:
            details = _enable_native_macos(uv_bin, repo_root, port, preset)
        result.update(details)
        result["service_started"] = True

    elif mode == "container":
        runtimes = _detect_container_runtimes()
        if not runtimes:
            print("ERROR: No container runtime found (podman or docker).", file=sys.stderr)
            print(
                "FIX:   Install podman (https://podman.io) or docker, then re-run.", file=sys.stderr
            )
            raise SystemExit(1)

        resolved_runtime = runtime if runtime in runtimes else runtimes[0]
        compose_file = _resolve_compose_file(repo_root, preset)
        if not compose_file.exists():
            print(f"ERROR: Compose file not found: {compose_file}", file=sys.stderr)
            raise SystemExit(1)

        details = _enable_container(resolved_runtime, compose_file, port)
        result["runtime"] = resolved_runtime
        result["compose_file"] = details["compose_file"]
        result["service_started"] = details["service_started"]

    elif mode == "manual":
        print(
            "To start skillsmith manually, run:\n\n    skillsmith serve\n\n"
            "Leave it running in a terminal while you work.",
            file=sys.stderr,
        )
        result["service_started"] = False

    else:
        print(f"ERROR: Unknown mode '{mode}'. Use native, container, or manual.", file=sys.stderr)
        raise SystemExit(1)

    return result


# ---------------------------------------------------------------------------
# Subcommand interface
# ---------------------------------------------------------------------------


def add_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
) -> None:
    p: argparse.ArgumentParser = subparsers.add_parser(
        "enable-service",
        help="Register Skillsmith as a persistent background service.",
    )
    p.add_argument(
        "--mode",
        choices=["native", "container", "manual"],
        default=None,
        help="Service mode. If omitted, available modes are detected and the user is prompted.",
    )
    p.add_argument(
        "--runtime",
        choices=["podman", "docker"],
        default=None,
        help="Container runtime (container mode only). Default: podman if available, else docker.",
    )
    p.add_argument(
        "--port",
        type=int,
        default=None,
        help="Service port override (default: read from user state, fallback 47950).",
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    st = install_state.load_state()
    port = install_state.validate_port(
        args.port if args.port is not None else st.get("port", 47950)
    )
    preset: str | None = st.get("preset")

    mode = args.mode
    if mode is None:
        mode = _prompt_mode()

    # For container mode with both runtimes available and no --runtime flag,
    # auto-select podman (project preference) without prompting.
    runtime = args.runtime
    if mode == "container" and runtime is None:
        runtimes = _detect_container_runtimes()
        if len(runtimes) > 1:
            runtime = _prompt_runtime(runtimes)
        elif runtimes:
            runtime = runtimes[0]

    result = enable_service(mode=mode, runtime=runtime, port=port, preset=preset)

    fp, digest = install_state.save_output_file(result, "enable-service.json")
    install_state.record_step(
        st,
        "enable-service",
        extra={
            "output_digest": digest,
            "output_path": str(fp),
            "mode": result["mode"],
            "runtime": result["runtime"],
            "unit_path": result["unit_path"],
        },
    )
    st["service_mode"] = result["mode"]
    st["service_runtime"] = result["runtime"]
    st["service_unit_path"] = result["unit_path"]
    install_state.save_state(st)

    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


# ---------------------------------------------------------------------------
# Interactive prompts (only used when args are not pre-supplied)
# ---------------------------------------------------------------------------


def _prompt_mode() -> str:
    os_name = _detect_os()
    runtimes = _detect_container_runtimes()
    native_ok = _native_available()

    options: list[tuple[str, str]] = []
    if native_ok:
        mgr = "systemd" if os_name == "linux" else "launchd"
        options.append(("native", f"Persistent — native service ({mgr}, starts at login)"))
    if runtimes:
        rt = runtimes[0]
        options.append(("container", f"Persistent — container ({rt} compose up -d)"))
    options.append(("manual", "Manual — I'll run `skillsmith serve` myself"))

    print("\nHow should Skillsmith run between coding sessions?", file=sys.stderr)
    for i, (_, label) in enumerate(options, 1):
        print(f"  {i}. {label}", file=sys.stderr)
    print(file=sys.stderr)

    while True:
        try:
            raw = input(f"Choice [1–{len(options)}] (default 1): ").strip()
        except (EOFError, KeyboardInterrupt):
            print(file=sys.stderr)
            raise SystemExit(1) from None
        if raw == "":
            return options[0][0]
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1][0]
        print(f"  Please enter a number between 1 and {len(options)}.", file=sys.stderr)


def _prompt_runtime(runtimes: list[str]) -> str:
    print(
        "\nBoth podman and docker are available. Which should run the container?", file=sys.stderr
    )
    for i, rt in enumerate(runtimes, 1):
        suffix = " (recommended)" if rt == "podman" else ""
        print(f"  {i}. {rt}{suffix}", file=sys.stderr)
    print(file=sys.stderr)

    while True:
        try:
            raw = input(f"Choice [1–{len(runtimes)}] (default 1): ").strip()
        except (EOFError, KeyboardInterrupt):
            print(file=sys.stderr)
            raise SystemExit(1) from None
        if raw == "":
            return runtimes[0]
        if raw.isdigit() and 1 <= int(raw) <= len(runtimes):
            return runtimes[int(raw) - 1]
        print(f"  Please enter a number between 1 and {len(runtimes)}.", file=sys.stderr)
