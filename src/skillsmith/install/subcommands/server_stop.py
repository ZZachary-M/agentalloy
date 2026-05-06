"""``server-stop`` verb — terminate the skillsmith server holding the corpus lock.

Detection is port-based; a manually-launched uvicorn on the configured
port is still discoverable. SIGTERM first; SIGKILL after ``--timeout``.
"""

from __future__ import annotations

import argparse
import json
import sys

from skillsmith.install import server_proc

EXIT_OK = 0
EXIT_USER = 1


def add_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
) -> None:
    p: argparse.ArgumentParser = subparsers.add_parser(
        "server-stop",
        help=(
            "Stop whatever process is listening on the configured port "
            "(releases the corpus lock). Does not verify the process is "
            "skillsmith — on a shared port that's the operator's concern."
        ),
    )
    p.add_argument("--port", type=int, default=None, help="Override configured port.")
    p.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Seconds to wait after SIGTERM before escalating to SIGKILL.",
    )
    p.set_defaults(func=_run)


def _run(args: argparse.Namespace) -> int:
    port = args.port if args.port is not None else server_proc.configured_port()
    pid = server_proc.find_listening_pid(port)
    if pid is None:
        # Nothing listening is the desired post-condition of stop —
        # report success so scripts and the setup composer don't treat
        # idempotent re-runs as failure. The "already_stopped" action
        # lets callers distinguish if they care.
        json.dump({"action": "already_stopped", "port": port}, sys.stdout, indent=2)
        sys.stdout.write("\n")
        print(f"server-stop: nothing listening on :{port}", file=sys.stderr)
        return EXIT_OK

    try:
        outcome = server_proc.stop(pid, timeout_s=args.timeout)
    except server_proc.ServerLifecycleError as e:
        print(f"server-stop: {e}", file=sys.stderr)
        return EXIT_USER

    json.dump(
        {"action": "stopped", "port": port, "pid": pid, "signal": outcome.upper()},
        sys.stdout,
        indent=2,
    )
    sys.stdout.write("\n")
    print(
        f"server-stop: pid {pid} on :{port} stopped via SIG{outcome.upper()}",
        file=sys.stderr,
    )
    return EXIT_OK
