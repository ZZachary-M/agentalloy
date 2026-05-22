"""``skillsmith watch`` — Tier 3 file-watching sidecar.

Commands:
    skillsmith watch start [--harness X] [--profile X]   Start the watcher (foreground)
    skillsmith watch stop                                  Send SIGTERM to running watcher
    skillsmith watch status                                Report watcher state
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
from pathlib import Path


def _watch_dir() -> Path:
    return Path.home() / ".skillsmith" / "watch"


def _pid_file(profile: str) -> Path:
    return _watch_dir() / f"{profile}.pid"


def _config_file(profile: str) -> Path:
    return _watch_dir() / f"{profile}.yaml"


def _read_pid(profile: str) -> int | None:
    pf = _pid_file(profile)
    if not pf.exists():
        return None
    try:
        return int(pf.read_text().strip())
    except (ValueError, OSError):
        return None


def _is_running(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # process exists but we can't signal it


def _detect_harness() -> str | None:
    """Try to detect the active harness from state.json."""
    try:
        from skillsmith.install import state as install_state

        st = install_state.load_state()
        files = st.get("harness_files_written", [])
        for entry in files:
            h = entry.get("harness", "")
            if h in ("cursor", "windsurf", "github-copilot", "cline", "gemini-cli", "aider"):
                return h
    except Exception:
        pass
    return None


def _start(args: argparse.Namespace) -> int:
    import yaml

    profile = getattr(args, "profile", None) or "default"
    harness = getattr(args, "harness", None) or _detect_harness()

    if harness is None:
        print(
            "ERROR: --harness required (could not detect from state.json).\n"
            "Use: skillsmith watch start --harness <cursor|windsurf|github-copilot|cline|gemini-cli|aider>",
            file=sys.stderr,
        )
        return 1

    existing_pid = _read_pid(profile)
    if _is_running(existing_pid):
        print(f"Watcher already running for profile={profile} (pid={existing_pid})")
        return 0

    project_root = Path.cwd()
    _watch_dir().mkdir(parents=True, exist_ok=True)

    config_path = _config_file(profile)
    config_data = {
        "project_root": str(project_root),
        "profile_name": profile,
        "harness": harness,
        "poll_interval_s": 1.0,
        "debounce_ms": 500,
    }
    config_path.write_text(yaml.dump(config_data))

    print(f"Starting watcher: profile={profile}, harness={harness}, root={project_root}")
    print("Press Ctrl+C to stop. (Recommend running under tmux or systemd for persistence.)")

    from skillsmith.watch.watcher import WatchConfig, run_watcher

    config = WatchConfig(
        project_root=project_root,
        profile_name=profile,
        harness=harness,
    )
    run_watcher(config)  # blocks until signal
    return 0


def _stop(args: argparse.Namespace) -> int:
    profile = getattr(args, "profile", None) or "default"
    pid = _read_pid(profile)
    if not _is_running(pid):
        print(f"No running watcher for profile={profile}")
        return 0
    assert pid is not None  # _is_running returned True only when pid is not None
    try:
        os.kill(pid, signal.SIGTERM)
        print(f"Sent SIGTERM to watcher pid={pid}")
    except ProcessLookupError:
        print("Watcher already stopped")
    return 0


def _status(args: argparse.Namespace) -> int:
    profile = getattr(args, "profile", None) or "default"
    pid = _read_pid(profile)
    running = _is_running(pid)

    log_file = _watch_dir() / f"{profile}.log"
    last_line = ""
    if log_file.exists():
        try:
            lines = log_file.read_text().splitlines()
            last_line = lines[-1] if lines else ""
        except OSError:
            pass

    report = {
        "profile": profile,
        "running": running,
        "pid": pid if running else None,
        "last_log": last_line,
    }
    print(json.dumps(report, indent=2))
    return 0


def add_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
) -> None:
    p: argparse.ArgumentParser = subparsers.add_parser(
        "watch",
        help="Tier 3 file-watching sidecar — regenerates harness rules files on phase/contract changes",
    )
    sub: argparse._SubParsersAction[argparse.ArgumentParser] = p.add_subparsers(dest="watch_cmd")  # pyright: ignore[reportPrivateUsage]

    start: argparse.ArgumentParser = sub.add_parser("start", help="Start the watcher (foreground)")
    start.add_argument("--harness", default=None, help="Tier 3 harness name")
    start.add_argument("--profile", default=None, help="Profile name (default: default)")

    stop: argparse.ArgumentParser = sub.add_parser("stop", help="Stop the running watcher")
    stop.add_argument("--profile", default=None)

    status: argparse.ArgumentParser = sub.add_parser("status", help="Report watcher state")
    status.add_argument("--profile", default=None)

    p.set_defaults(func=_dispatch)


def _dispatch(args: argparse.Namespace) -> int:
    cmd = getattr(args, "watch_cmd", None)
    if cmd == "start":
        return _start(args)
    if cmd == "stop":
        return _stop(args)
    if cmd == "status":
        return _status(args)
    print("Usage: skillsmith watch {start,stop,status}", file=sys.stderr)
    return 1
