"""Install CLI dispatcher.

Usage::

    python -m skillsmith.install <subcommand> [args]

Exit codes
----------
0  success
1  user-correctable failure (precondition not met)
2  system failure (unexpected exception)
3  schema-version mismatch
4  already-completed (idempotent skip / no-op)
"""

from __future__ import annotations

import argparse
import sys

from skillsmith.install.subcommands import (
    detect,
    doctor,
    enable_service,
    install_pack,
    pull_models,
    recommend_host_targets,
    recommend_models,
    reset_step,
    seed_corpus,
    serve,
    setup,
    status,
    uninstall,
    unwire,
    update,
    verify,
    wire,
    wire_harness,
    write_env,
)

EXIT_OK = 0
EXIT_USER = 1
EXIT_SYSTEM = 2
EXIT_SCHEMA = 3
EXIT_NOOP = 4

_SUBCOMMANDS = [
    # User-facing verbs first — these are what end users typically run.
    setup,
    wire,
    unwire,
    serve,
    enable_service,
    status,
    # Underlying step subcommands (still available for power-users + the
    # runbook LLM that drives them individually).
    detect,
    recommend_host_targets,
    recommend_models,
    seed_corpus,
    pull_models,
    write_env,
    wire_harness,
    verify,
    doctor,
    uninstall,
    reset_step,
    update,
    install_pack,
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m skillsmith.install",
        description="Skillsmith installer CLI.",
    )
    subparsers = parser.add_subparsers(dest="subcommand")
    for mod in _SUBCOMMANDS:
        mod.add_parser(subparsers)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.subcommand is None:
        parser.print_help(sys.stderr)
        return EXIT_USER

    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
