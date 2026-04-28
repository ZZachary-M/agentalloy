"""``status`` verb — show the current install snapshot.

Reads the user-scope state and reports:
  * Which user-scope steps have completed (detect, recommend-*,
    pull-models, seed-corpus, write-env).
  * Which repos have been wired, grouped by ``repo_root`` from
    ``harness_files_written`` entries.
  * Whether the corpus is present at the user data dir.
  * Whether the service is reachable on the configured port.

Read-only. Never mutates state. Safe to run anywhere.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
from collections import defaultdict
from typing import Any

from skillsmith.install import state as install_state

SCHEMA_VERSION = 1


def add_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
) -> None:
    p: argparse.ArgumentParser = subparsers.add_parser(
        "status",
        help="Show user-scope install state, wired repos, and service reachability.",
    )
    p.set_defaults(func=_run)


def _run(args: argparse.Namespace) -> int:  # noqa: ARG001
    st = install_state.load_state()
    completed_step_names = [s.get("step") for s in st.get("completed_steps", [])]

    # Group harness entries by repo_root so multi-repo users see a clean
    # per-project picture.
    repos: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in st.get("harness_files_written", []):
        repo_root = entry.get("repo_root") or "<unknown>"
        repos[repo_root].append(
            {
                "harness": entry.get("harness"),
                "path": entry.get("path"),
                "action": entry.get("action"),
            }
        )

    # Corpus presence
    corpus_path = install_state.corpus_dir()
    corpus_present = (corpus_path / "skills.duck").exists() and (corpus_path / "ladybug").exists()

    # Service reachability — TCP connect only; doctor/verify do the deeper /health probe.
    port_raw = st.get("port", 47950)
    try:
        port = install_state.validate_port(port_raw)
        service_reachable = _port_open("127.0.0.1", port)
    except SystemExit:
        port = None
        service_reachable = False

    snapshot: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "user_config_dir": str(install_state.user_config_dir()),
        "user_data_dir": str(install_state.user_data_dir()),
        "completed_steps": completed_step_names,
        "corpus": {
            "path": str(corpus_path),
            "present": corpus_present,
        },
        "service": {
            "port": port,
            "reachable_on_loopback": service_reachable,
        },
        "wired_repos": [
            {
                "repo_root": repo_root,
                "entries": entries,
            }
            for repo_root, entries in sorted(repos.items())
        ],
        "env_file": {
            "path": str(install_state.env_path()),
            "exists": install_state.env_path().exists(),
        },
    }
    json.dump(snapshot, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def _port_open(host: str, port: int) -> bool:
    """Return True if a TCP connect to host:port succeeds within 1 second."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            return s.connect_ex((host, port)) == 0
    except OSError:
        return False
