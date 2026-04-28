"""``serve`` verb — run the Skillsmith service in the foreground.

Sources the user-scope ``.env`` into the process environment, then
execs uvicorn against ``skillsmith.app:app``. Foreground / blocking, in
the local-LLM-tooling idiom (``ollama serve``, ``lm studio``). Daemon
supervision is intentionally out of scope — users start it in a terminal
and leave it running, or wrap it in their own systemd / launchd unit.
"""

from __future__ import annotations

import argparse
import os
import shlex
import sys
from pathlib import Path

from skillsmith.install import state as install_state


def add_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
) -> None:
    p: argparse.ArgumentParser = subparsers.add_parser(
        "serve",
        help="Run the Skillsmith service (foreground uvicorn).",
    )
    p.add_argument(
        "--port",
        type=int,
        default=None,
        help="Override the service port (default: read from user state, fallback 47950).",
    )
    p.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind address (default: 127.0.0.1 — loopback only).",
    )
    p.add_argument(
        "--reload",
        action="store_true",
        help="Enable uvicorn auto-reload (development only).",
    )
    p.set_defaults(func=_run)


def _run(args: argparse.Namespace) -> int:
    # 1. Load the user-scope .env into os.environ. We don't use python-dotenv
    # to avoid pulling in another dependency; the parser is intentionally
    # minimal — KEY=value lines, # comments, no shell expansion.
    loaded_keys = _load_env_into_environ(install_state.env_path())
    if loaded_keys:
        print(
            f"skillsmith serve: loaded {len(loaded_keys)} keys from {install_state.env_path()}",
            file=sys.stderr,
        )
    else:
        print(
            f"skillsmith serve: no .env found at {install_state.env_path()} — "
            "running with process environment only. Run "
            "`python -m skillsmith.install setup` if you haven't yet.",
            file=sys.stderr,
        )

    # 2. Resolve port: CLI flag > state > default 47950.
    if args.port is not None:
        port = install_state.validate_port(args.port)
    else:
        st = install_state.load_state()
        port = install_state.validate_port(st.get("port", 47950))

    # 3. Exec uvicorn so signals (SIGINT) propagate cleanly.
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "skillsmith.app:app",
        "--host",
        args.host,
        "--port",
        str(port),
    ]
    if args.reload:
        cmd.append("--reload")

    print(
        f"skillsmith serve: exec {shlex.join(cmd)}",
        file=sys.stderr,
        flush=True,
    )
    # os.execvp replaces this process with uvicorn — no return on success.
    try:
        os.execvp(cmd[0], cmd)
    except FileNotFoundError:
        print(
            f"ERROR: {cmd[0]} not found. Is the skillsmith venv active?",
            file=sys.stderr,
        )
        return 2
    # Unreachable after execvp; kept for type-checker.
    return 0


def _load_env_into_environ(env_path: Path) -> list[str]:
    """Parse a .env file and inject its keys into os.environ. Returns
    the list of keys that were loaded (for logging). Process-env
    values that are already set take precedence over .env (matching
    pydantic-settings' priority model).
    """
    if not env_path.exists():
        return []
    loaded: list[str] = []
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        # Allow shell-style `export KEY=value` (common when users paste
        # from `set -a; source ...; set +a` workflows).
        if key.startswith("export "):
            key = key[len("export ") :].strip()
        val = val.strip()
        # Strip matching outer quotes for typical .env values.
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
            val = val[1:-1]
        if key and key not in os.environ:
            os.environ[key] = val
            loaded.append(key)
    return loaded
