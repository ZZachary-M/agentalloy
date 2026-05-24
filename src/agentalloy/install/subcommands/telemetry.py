"""``telemetry`` subcommand group — telemetry table management.

Currently exposes one sub-verb:

    agentalloy telemetry clear [--confirm]

Clears ``composition_traces`` and ``prompt_loads`` from the user-scoped
DuckDB without touching ``fragment_embeddings`` (the corpus).
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from agentalloy.install.output import add_json_flag, print_rich, write_result

SCHEMA_VERSION = 1


def add_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
) -> None:
    p: argparse.ArgumentParser = subparsers.add_parser(
        "telemetry",
        help="Telemetry table management (clear, etc.).",
    )
    add_json_flag(p)
    sub = p.add_subparsers(dest="telemetry_verb", metavar="verb")
    sub.required = True

    clear_p = sub.add_parser(
        "clear",
        help="Delete all composition traces and prompt-load records.",
    )
    clear_p.add_argument(
        "--confirm",
        action="store_true",
        help="Skip the interactive confirmation prompt (required in non-TTY environments).",
    )
    clear_p.set_defaults(func=_run_clear)

    p.set_defaults(func=_dispatch)


def _dispatch(args: argparse.Namespace) -> int:
    return args.func(args)


def _run_clear(args: argparse.Namespace) -> int:
    if not args.confirm:
        if not sys.stdin.isatty():
            print(
                "ERROR: telemetry clear requires --confirm in non-interactive mode.",
                file=sys.stderr,
            )
            return 1
        try:
            answer = (
                input(
                    "This will permanently delete all composition traces and prompt-load "
                    "records from the local DuckDB.\nContinue? [y/N]: "
                )
                .strip()
                .lower()
            )
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.", file=sys.stderr)
            return 0
        if answer not in ("y", "yes"):
            print("Aborted.", file=sys.stderr)
            return 0

    from agentalloy.config import get_settings
    from agentalloy.storage.vector_store import open_or_create

    settings = get_settings()
    vs = open_or_create(settings.duckdb_path)
    try:
        result = vs.clear_telemetry()
    finally:
        vs.close()

    write_result(result, args, human_fn=_render_clear)
    return 0


def _render_clear(result: dict[str, Any]) -> None:
    """Render telemetry clear result in human-readable format."""
    print_rich("\n  [bold]Telemetry Clear[/bold]\n")
    print_rich(f"  Traces deleted: {result['traces_deleted']}")
    print_rich(f"  Prompt loads deleted: {result['prompt_loads_deleted']}")
    print_rich()
