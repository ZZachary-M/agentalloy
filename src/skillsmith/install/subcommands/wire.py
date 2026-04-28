"""``wire`` verb — per-repo harness wiring.

Convenience wrapper over ``wire-harness``. Auto-detects the harness from
markers in the cwd (`.cursor/` → cursor, `GEMINI.md` → gemini-cli,
`.continuerc.json` → continue-closed, etc.) and reads the service port
from user-scope state.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from skillsmith.install import state as install_state
from skillsmith.install.subcommands.wire_harness import VALID_HARNESSES, wire_harness


def add_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
) -> None:
    p: argparse.ArgumentParser = subparsers.add_parser(
        "wire",
        help="Inject Skillsmith sentinels into the current repo's agent config.",
    )
    p.add_argument(
        "--harness",
        choices=sorted(VALID_HARNESSES),
        default=None,
        help="Force a specific harness. Default: auto-detect from cwd.",
    )
    p.add_argument(
        "--port",
        type=int,
        default=None,
        help="Override the service port (default: read from user state, fallback 47950).",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an edited sentinel block (otherwise refuses).",
    )
    p.set_defaults(func=_run)


def _run(args: argparse.Namespace) -> int:
    cwd = Path.cwd().resolve()
    harness = args.harness or _detect_harness(cwd)
    if harness is None:
        print(
            "ERROR: Could not detect a harness in the current directory.",
            file=sys.stderr,
        )
        print(
            f"FIX:   Pass --harness explicitly. Choices: {', '.join(sorted(VALID_HARNESSES))}.",
            file=sys.stderr,
        )
        return 1

    if args.port is not None:
        port = install_state.validate_port(args.port)
    else:
        st = install_state.load_state()
        port = install_state.validate_port(st.get("port", 47950))

    result = wire_harness(harness, port=port, root=cwd, force=args.force)
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


# Detection priority (first match wins). Documented in INSTALL.md so
# users with multiple markers in the same repo know what they'll get.
# Order rationale: tool-specific dotfiles are stronger signals than
# `CLAUDE.md` (which Claude Code and many other agents now share), so
# they're checked first. A repo with both `.cursor/` and `CLAUDE.md`
# will wire as `cursor` — pass `--harness claude-code` to override.
_HARNESS_MARKERS: list[tuple[str, list[str]]] = [
    ("cursor", [".cursor", ".cursorrules"]),
    ("continue-local", [".continuerc.json"]),
    ("aider", [".aider.conf.yml"]),
    ("opencode", [".opencode"]),
    ("cline", [".clinerules"]),
    ("gemini-cli", ["GEMINI.md"]),
    ("claude-code", ["CLAUDE.md"]),
]


def _detect_harness(cwd: Path) -> str | None:
    """Best-effort harness detection from filesystem markers in cwd.

    Returns the first harness whose marker exists, scanning in priority
    order. Multi-marker repos pick the more-specific tool first; users
    can always pass `--harness` explicitly to override.
    """
    matches = [h for h, markers in _HARNESS_MARKERS if any((cwd / m).exists() for m in markers)]
    if len(matches) > 1:
        print(
            f"NOTE: Multiple harness markers detected ({', '.join(matches)}); "
            f"defaulting to {matches[0]}. Pass --harness <name> to choose explicitly.",
            file=sys.stderr,
        )
    return matches[0] if matches else None
