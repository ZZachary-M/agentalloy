"""``server-status`` verb — report background server lifecycle state.

Lifecycle-focused: port, pid (if listening), reachability. The broader
``status`` verb covers install state and wired repos.
"""

from __future__ import annotations

import argparse
from typing import Any

from agentalloy.install import server_proc
from agentalloy.install.output import add_json_flag, write_result


def add_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
) -> None:
    p: argparse.ArgumentParser = subparsers.add_parser(
        "server-status",
        help="Report agentalloy server lifecycle state (port, pid, reachable).",
    )
    p.add_argument("--port", type=int, default=None, help="Override configured port.")
    add_json_flag(p)
    p.set_defaults(func=_run)


def _render_human(payload: dict[str, Any]) -> None:
    """Render server status in human-readable format."""
    from agentalloy.install.output import print_rich

    print_rich("\n  [bold]Server Status[/bold]\n")

    port = payload.get("port", "N/A")
    pid = payload.get("pid")
    reachable = payload.get("reachable", False)

    # Port
    print_rich(f"  Port: {port}")

    # PID
    if pid is not None:
        print_rich(f"  PID:  {pid}")
    else:
        print_rich("  PID:  [dim]no process[/dim]")

    # Reachability
    reach_status = "[green]reachable[/green]" if reachable else "[red]not reachable[/red]"
    print_rich(f"  Status: {reach_status}")

    # Log path
    log_path = payload.get("log_path", "N/A")
    print_rich(f"  Log:  {log_path}")

    print_rich()


def _run(args: argparse.Namespace) -> int:
    info = server_proc.server_info(port=args.port)
    payload = {
        "port": info.port,
        "pid": info.pid,
        "reachable": info.reachable,
        "log_path": str(server_proc.server_log_path()),
    }
    write_result(payload, args, human_fn=_render_human)
    return 0
