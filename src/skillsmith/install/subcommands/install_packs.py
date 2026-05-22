# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false
"""``install-packs`` subcommand — interactive pack picker + bulk local install.

Runs after ``seed-corpus`` in the setup composer. Discovers in-tree packs
under ``seeds/packs/*/pack.yaml``, prompts the user (TTY) or applies a
sensible default (non-TTY), installs each selected pack locally, and
triggers one bulk reembed at the end.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import yaml

from skillsmith.install import state as install_state
from skillsmith.install.subcommands.install_pack import install_local_pack

SCHEMA_VERSION = 1
STEP_NAME = "install-packs"


def add_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
) -> None:
    p: argparse.ArgumentParser = subparsers.add_parser(
        "install-packs",
        help="Interactive pack picker + bulk install (called by `setup`).",
    )
    p.add_argument(
        "--packs",
        help="Comma-separated pack names. Skips the interactive picker. Use 'all' for every pack.",
    )
    p.add_argument(
        "--non-interactive",
        action="store_true",
        help="Force non-TTY mode (install only always-on packs unless --packs is given).",
    )
    p.add_argument(
        "--ignore-unknown",
        action="store_true",
        help=(
            "Continue with the known subset when --packs lists names that "
            "don't exist (default: fail with the available pack list)."
        ),
    )
    p.add_argument(
        "--list",
        action="store_true",
        help="Print available pack names (one per line) and exit.",
    )
    p.set_defaults(func=_run)


def _packs_dir() -> Path:
    """Return the directory containing pack manifests.

    Resolves to ``src/skillsmith/_packs/`` in both editable and wheel
    installs (the path is the same because editable installs point
    Python at the repo's `src/skillsmith/` directly).
    """
    import skillsmith

    return Path(skillsmith.__file__).resolve().parent / "_packs"


def _run(args: argparse.Namespace) -> int:
    from skillsmith.install.state import pack_source_dir

    root = pack_source_dir()
    root.mkdir(parents=True, exist_ok=True)
    packs_root = _packs_dir()

    available = _discover_packs(packs_root)

    if getattr(args, "list", False):
        for name in sorted(available):
            meta = available[name]
            always = " [always-on]" if meta.get("always_install") else ""
            print(f"{name}{always}")
        return 0

    if not available:
        print("install-packs: no packs found under seeds/packs/", file=sys.stderr)
        result = {
            "schema_version": SCHEMA_VERSION,
            "action": "no_packs_available",
            "packs_root": str(packs_root),
        }
        if not getattr(args, "quiet", False):
            json.dump(result, sys.stdout, indent=2)
            sys.stdout.write("\n")
        return 1

    interactive = sys.stdin.isatty() and not args.non_interactive
    selected, unknown, consumed_pending = _select_packs(
        available, args.packs, interactive=interactive
    )

    if unknown and not args.ignore_unknown:
        result = {
            "schema_version": SCHEMA_VERSION,
            "action": "unknown_packs",
            "unknown": sorted(unknown),
            "available": sorted(available),
        }
        if not getattr(args, "quiet", False):
            json.dump(result, sys.stdout, indent=2)
            sys.stdout.write("\n")
        print(
            f"install-packs: unknown pack(s): {sorted(unknown)}",
            file=sys.stderr,
        )
        print(
            "FIX:   re-run with valid pack names (see `available` above), "
            "or pass --ignore-unknown to skip them.",
            file=sys.stderr,
        )
        return 1
    if unknown and args.ignore_unknown:
        print(
            f"install-packs: ignoring unknown pack(s): {sorted(unknown)}",
            file=sys.stderr,
        )

    print(f"install-packs: installing {len(selected)} pack(s)", file=sys.stderr)
    t0 = time.monotonic()
    install_results: list[dict[str, Any]] = []
    failed: list[str] = []
    for pack_name in selected:
        pack_dir = packs_root / pack_name
        print(f"  → {pack_name}", file=sys.stderr, flush=True)
        r = install_local_pack(pack_dir, root=root)
        install_results.append(r)
        if r.get("ingest_failures", 0) > 0:
            # ingest_failures > 0 can be benign (skill_id already in corpus
            # from a prior run); that's recorded but not counted as a hard
            # failure here.
            pass
        # `already_installed` is a successful no-op (every skill in the
        # pack was already in the corpus). `ingested_with_errors` had
        # real failures but at least some progress; we still track which
        # packs that affects via per-pack ingest_failures, not here.
        if r.get("action") not in ("ingested", "ingested_with_errors", "already_installed"):
            failed.append(pack_name)

    # Bulk reembed once at the end (idempotent — only embeds new fragments).
    print("install-packs: bulk reembed", file=sys.stderr)
    reembed_rc = _bulk_reembed()

    duration_ms = int((time.monotonic() - t0) * 1000)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "action": "packs_installed" if not failed else "packs_partial",
        "selected": selected,
        "failed_packs": failed,
        "install_results": [
            {k: v for k, v in r.items() if k != "ingest_results"} for r in install_results
        ],
        "reembed_exit_code": reembed_rc,
        "duration_ms": duration_ms,
    }
    install_state.save_output_file(summary, "install-packs.json")
    if not getattr(args, "quiet", False):
        json.dump(summary, sys.stdout, indent=2)
        sys.stdout.write("\n")

    if reembed_rc != 0:
        print(
            "WARN: bulk reembed exited non-zero. Some fragments may lack embeddings; "
            "run `skillsmith reembed` again to retry. Vector retrieval will skip "
            "unembedded fragments until then.",
            file=sys.stderr,
        )

    # Clear the setup-wizard pack selection once we've acted on it, so a
    # later standalone `skillsmith install-packs` re-prompts the user with
    # the same UX (showing already-installed packs in the picker).
    if consumed_pending and not failed:
        _clear_pending_pack_selection()

    return 0 if not failed else 1


def _discover_packs(packs_root: Path) -> dict[str, dict[str, Any]]:
    """Return {pack_name: manifest} for every seeds/packs/*/pack.yaml."""
    out: dict[str, dict[str, Any]] = {}
    if not packs_root.is_dir():
        return out
    for pack_dir in sorted(packs_root.iterdir()):
        if not pack_dir.is_dir():
            continue
        manifest_path = pack_dir / "pack.yaml"
        if not manifest_path.is_file():
            continue
        try:
            manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        name = str(manifest.get("name") or pack_dir.name)
        out[name] = manifest
    return out


def _select_packs(
    available: dict[str, dict[str, Any]],
    packs_flag: str | None,
    *,
    interactive: bool,
) -> tuple[list[str], list[str], bool]:
    """Pick packs honoring priority: --packs > pending-state > TTY prompt > defaults.

    Returns ``(selected, unknown, consumed_pending)``. ``unknown`` is the
    list of names from ``--packs`` that don't match any available pack —
    caller decides whether to fail or continue. ``consumed_pending`` is
    True iff a ``pending_pack_selection`` from setup was applied; caller
    should clear it from state after a successful install.
    """
    always_on = [n for n, m in available.items() if m.get("always_install")]
    unknown: list[str] = []

    # Explicit --packs flag wins
    if packs_flag:
        if packs_flag.strip().lower() == "all":
            chosen = list(available)
        else:
            requested = [p.strip() for p in packs_flag.split(",") if p.strip()]
            unknown = [p for p in requested if p not in available]
            chosen = [p for p in requested if p in available]
        # Always include always-on packs even if user didn't list them.
        return _ordered_with_deps(set(chosen) | set(always_on), available), unknown, False

    # Pending selection from setup wizard (written by simple_setup before
    # ever calling install-packs). An empty list still counts as explicit
    # intent — "user picked nothing extra, install always-on only".
    pending = _load_pending_pack_selection()
    if pending is not None:
        chosen = [p for p in pending if p in available]
        unknown = [p for p in pending if p not in available]
        return _ordered_with_deps(set(chosen) | set(always_on), available), unknown, True

    if not interactive:
        # Non-TTY default: only install always-on packs.
        return _ordered_with_deps(set(always_on), available), unknown, False

    # Interactive multi-select.
    chosen = _prompt_for_packs(available, always_on)
    return _ordered_with_deps(set(chosen) | set(always_on), available), unknown, False


def _load_pending_pack_selection() -> list[str] | None:
    """Read ``pending_pack_selection`` from install-state, safely.

    Best-effort: a malformed/missing state file means "no pending
    selection", not a crash. This runs in the install pipeline where
    failing early on state-read errors would block users from
    re-installing.
    """
    try:
        data = install_state.load_state()
    except Exception:  # noqa: BLE001
        return None
    return install_state.get_pending_pack_selection(data)


def _clear_pending_pack_selection() -> None:
    """Wipe ``pending_pack_selection`` after install-packs consumed it.

    Best-effort: matches the load helper. A standalone re-run of
    install-packs (no pending state on disk) goes through the
    interactive prompt with already-installed annotations.
    """
    try:
        data = install_state.load_state()
        install_state.clear_pending_pack_selection(data)
        install_state.save_state(data)
    except Exception:  # noqa: BLE001
        # Non-fatal: leaving a stale pending selection just causes the
        # NEXT install-packs run to skip prompting, which is annoying
        # but not destructive.
        pass


def _installed_pack_names() -> set[str]:
    """Return the set of pack names previously recorded as installed.

    Used to annotate the interactive picker with [installed] markers.
    Returns an empty set on any read error.
    """
    try:
        data = install_state.load_state()
    except Exception:  # noqa: BLE001
        return set()
    packs = data.get("installed_packs") or []
    return {str(p) for p in packs if isinstance(p, str)}


_TIER_ORDER: tuple[str, ...] = (
    "foundation",
    "language",
    "framework",
    "tooling",
    "protocol",
    "store",
    "platform",
    "domain",
    "workflow",
    "other",
)
_TIER_LABELS: dict[str, str] = {
    "foundation": "Foundation",
    "language": "Languages",
    "framework": "Frameworks",
    "tooling": "Tooling",
    "protocol": "Protocols",
    "store": "Data Stores",
    "platform": "Platforms",
    "domain": "Domain",
    "workflow": "Workflows",
    "other": "Other",
}


def _prompt_for_packs(
    available: dict[str, dict[str, Any]],
    always_on: list[str],
) -> list[str]:
    """Show packs grouped by tier and accept a comma-separated selection.

    Mirrors the setup wizard's pack picker (``simple_setup._prompt_for_packs``)
    so re-running install-packs feels identical to first-time setup. Accepts
    pack names, tier names (case-insensitive display label or internal key),
    or ``all`` / ``defaults`` / blank for always-on only.

    Packs that were recorded in a prior install are annotated ``[installed]``.
    Selecting them again is a no-op: ``install_local_pack`` reports an
    ``already_installed`` action when every skill in the pack is already
    in the corpus. The marker just spares the user from guessing.
    """
    if not available:
        return []

    installed = _installed_pack_names()

    # Group by tier, retaining (name, skill_count, always_on, installed).
    tiers: dict[str, list[tuple[str, int, bool, bool]]] = {}
    for name, m in available.items():
        tier = str(m.get("tier") or "other")
        skill_count = len(m.get("skills") or [])
        is_always = bool(m.get("always_install"))
        is_installed = name in installed
        tiers.setdefault(tier, []).append((name, skill_count, is_always, is_installed))

    # Reverse lookup so users can type "Languages" or "language" interchangeably.
    label_to_tier = {v.lower(): k for k, v in _TIER_LABELS.items()}

    print("\n=== Available skill packs ===\n", file=sys.stderr)
    pack_index: list[str] = []  # flat list for numeric selection
    for tier in _TIER_ORDER:
        rows = tiers.get(tier)
        if not rows:
            continue
        label = _TIER_LABELS.get(tier, tier.title())
        print(f"  [{label}]", file=sys.stderr)
        for name, skill_count, is_always, is_installed in sorted(rows, key=lambda x: x[0]):
            markers: list[str] = []
            if is_always:
                markers.append("always-on")
            if is_installed:
                markers.append("installed")
            marker_str = f"  ({', '.join(markers)})" if markers else ""
            print(
                f"    - {name:22} {skill_count:>3} skills{marker_str}",
                file=sys.stderr,
            )
            pack_index.append(name)
        print("", file=sys.stderr)

    print(
        f"  Always-on (auto-installed): {', '.join(sorted(always_on)) or '(none)'}",
        file=sys.stderr,
    )
    visible_tiers = [_TIER_LABELS.get(t, t) for t in _TIER_ORDER if t in tiers]
    if visible_tiers:
        print(
            "\n  Tip: You can also use tiers (comma-separated):",
            file=sys.stderr,
        )
        print(f"    {', '.join(visible_tiers)}", file=sys.stderr)
    print(
        "\n  Enter pack or tier names (comma-separated), 'all', or blank for always-on only.",
        file=sys.stderr,
    )

    try:
        raw = input("Packs to install: ").strip()
    except (EOFError, KeyboardInterrupt):
        return []

    if not raw or raw.lower() == "defaults":
        return []
    if raw.lower() == "all":
        return list(pack_index)

    chosen: list[str] = []
    for token in raw.split(","):
        t = token.strip()
        if not t:
            continue
        # Tier-based selection: match internal key or display label (case-insensitive).
        tier_key: str | None = None
        if t in tiers:
            tier_key = t
        elif t.lower() in label_to_tier:
            tier_key = label_to_tier[t.lower()]
        if tier_key is not None and tier_key in tiers:
            chosen.extend(name for name, _, _, _ in tiers[tier_key])
        elif t in available:
            chosen.append(t)
        elif t.isdigit() and 1 <= int(t) <= len(pack_index):
            chosen.append(pack_index[int(t) - 1])
        else:
            print(f"  ignoring unknown pack: {t}", file=sys.stderr)

    # Deduplicate preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for name in chosen:
        if name not in seen:
            seen.add(name)
            deduped.append(name)
    return deduped


def _ordered_with_deps(
    chosen: set[str],
    available: dict[str, dict[str, Any]],
) -> list[str]:
    """Topological order: dependencies before dependents. Adds missing deps.

    Warns when a pack declares a dependency on a pack that isn't available.
    Without the warning, missing deps were silently ignored — masking
    misconfigurations until runtime.
    """
    closed: set[str] = set()
    missing_deps: list[tuple[str, str]] = []  # (declarant, missing_dep)
    work = list(chosen)
    while work:
        name = work.pop()
        if name in closed:
            continue
        closed.add(name)
        for dep in available.get(name, {}).get("depends_on") or []:
            if dep not in available:
                missing_deps.append((name, dep))
                continue
            if dep not in closed:
                work.append(dep)

    for declarant, dep in missing_deps:
        print(
            f"WARN: pack '{declarant}' declares depends_on '{dep}', "
            f"but that pack is not available — proceeding without it.",
            file=sys.stderr,
        )

    # Simple DFS-based topo sort
    ordered: list[str] = []
    visited: set[str] = set()

    def visit(n: str) -> None:
        if n in visited:
            return
        visited.add(n)
        for d in available.get(n, {}).get("depends_on") or []:
            if d in closed:
                visit(d)
        ordered.append(n)

    for n in sorted(closed):
        visit(n)
    return ordered


def _bulk_reembed() -> int:
    """Run the reembed CLI in-process. Returns its exit code."""
    try:
        from skillsmith.reembed.cli import main as reembed_main

        return reembed_main([])
    except Exception as exc:  # noqa: BLE001 — surface but don't crash setup
        print(f"install-packs: reembed raised: {exc}", file=sys.stderr)
        return 2


def run(args: argparse.Namespace) -> int:
    """Public entry point for non-argparse callers (e.g. simple_setup)."""
    return _run(args)
