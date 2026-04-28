"""``server-status`` verb — report background server lifecycle state.

Lifecycle-focused: port, pid (if listening), reachability. The broader
``status`` verb covers install state and wired repos.
"""

from __future__ import annotations

import argparse
import json
import sys

from skillsmith.install import server_proc


def add_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
) -> None:
    p: argparse.ArgumentParser = subparsers.add_parser(
        "server-status",
        help="Report skillsmith server lifecycle state (port, pid, reachable).",
    )
    p.add_argument("--port", type=int, default=None, help="Override configured port.")
    p.set_defaults(func=_run)


def _run(args: argparse.Namespace) -> int:
    info = server_proc.server_info(port=args.port)
    payload = {
        "port": info.port,
        "pid": info.pid,
        "reachable": info.reachable,
        "log_path": str(server_proc.server_log_path()),
    }
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0
