"""``skillsmith contract`` — contract management subcommand.

Commands:
    skillsmith contract validate <path>
    skillsmith contract show <path>
    skillsmith contract init --phase <name> --slug <slug>
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _validate(args: argparse.Namespace) -> int:
    from skillsmith.contracts import ContractMalformed, parse_contract, validate_contract
    from skillsmith.install.state import _repo_root  # pyright: ignore[reportPrivateUsage]

    path = Path(args.path).resolve()
    try:
        contract = parse_contract(path)
    except ContractMalformed as exc:
        print(json.dumps({"valid": False, "error": str(exc), "issues": [str(exc)]}))
        return 1

    project_root = _repo_root()
    issues = validate_contract(contract, project_root)

    result: dict[str, Any] = {
        "valid": not issues,
        "path": str(path),
        "phase": contract.phase,
        "task_slug": contract.task_slug,
        "domain_tags": contract.domain_tags,
        "issues": issues,
    }
    print(json.dumps(result, indent=2))
    return 0 if not issues else 1


def _show(args: argparse.Namespace) -> int:
    from skillsmith.contracts import ContractMalformed, parse_contract

    path = Path(args.path).resolve()
    try:
        contract = parse_contract(path)
    except ContractMalformed as exc:
        print(f"  [error] {exc}", file=sys.stderr)
        return 1

    result: dict[str, Any] = {
        "path": str(contract.path),
        "phase": contract.phase,
        "task_slug": contract.task_slug,
        "domain_tags": contract.domain_tags,
        "scope": {
            "touches": contract.scope.touches,
            "avoids": contract.scope.avoids,
        },
        "success_criteria": contract.success_criteria,
        "related_contracts": [str(p) for p in contract.related_contracts],
        "created_at": contract.created_at.isoformat() if contract.created_at else None,
        "body": contract.body,
    }

    if getattr(args, "human", False):
        print(f"  Phase:    {contract.phase}")
        print(f"  Slug:     {contract.task_slug}")
        print(f"  Tags:     {', '.join(contract.domain_tags)}")
        print(f"\n  Body:\n{contract.body}")
    else:
        print(json.dumps(result, indent=2))
    return 0


def _init(args: argparse.Namespace) -> int:
    from skillsmith.install.state import _repo_root  # pyright: ignore[reportPrivateUsage]

    phase: str = args.phase
    slug: str = args.slug
    force: bool = getattr(args, "force", False)

    project_root = _repo_root()
    contracts_dir = project_root / ".skillsmith" / "contracts" / phase
    contracts_dir.mkdir(parents=True, exist_ok=True)
    target = contracts_dir / f"{slug}.md"

    if target.exists() and not force:
        print(
            f"  [error] Contract already exists: {target}. Use --force to overwrite.",
            file=sys.stderr,
        )
        return 1

    # Try to load contract_template from active workflow skill
    template = _load_contract_template(phase)
    if template is None:
        # Fallback minimal template
        template = (
            "---\n"
            "phase: {phase}\n"
            "task_slug: {task_slug}\n"
            "domain_tags: []\n"
            "scope:\n"
            "  touches: []\n"
            "  avoids: []\n"
            "success_criteria: []\n"
            "related_contracts: []\n"
            "created_at: {created_at}\n"
            "---\n\n"
            "# {task_slug_title}\n\n"
            "## Task description\n\n"
            "<fill in what you intend to do and why>\n"
        )

    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    content = (
        template.replace("{{phase}}", phase)
        .replace("{{task_slug}}", slug)
        .replace("{{created_at}}", now)
        .replace("{phase}", phase)
        .replace("{task_slug}", slug)
        .replace("{created_at}", now)
        .replace("{task_slug_title}", slug.replace("-", " ").title())
    )

    target.write_text(content, encoding="utf-8")
    result = {"path": str(target), "phase": phase, "task_slug": slug}
    print(json.dumps(result, indent=2))
    return 0


def _load_contract_template(phase: str) -> str | None:
    """Load the contract_template field from the workflow skill for this phase."""
    try:
        import duckdb

        from skillsmith.profiles import detect_profile, profile_datastore_path

        profile = detect_profile()
        ds_path = profile_datastore_path(profile.name)
        if not ds_path.exists():
            return _load_template_from_packs(phase)

        conn = duckdb.connect(str(ds_path), read_only=True)
        try:
            # Check if profile_skills table has a workflow skill for this phase
            rows = conn.execute(
                "SELECT applies_to_phases, raw_prose FROM profile_skills WHERE skill_class = 'workflow'"
            ).fetchall()
        except Exception:
            rows = []
        finally:
            conn.close()

        for row in rows:
            phases_raw, _raw_prose = row
            phases: list[Any] = phases_raw or []
            if phase in phases:
                # The Phase 1 profile_skills table doesn't persist
                # contract_template yet, so even when the profile datastore
                # has a workflow skill for this phase we still need the
                # shipped pack's template. Fall through to packs lookup.
                break

    except Exception:
        pass
    return _load_template_from_packs(phase)


def _load_template_from_packs(phase: str) -> str | None:
    """Load contract_template from _packs sdd-*.yaml for the given phase."""
    try:
        import yaml

        import skillsmith

        packs_root = Path(skillsmith.__file__).resolve().parent / "_packs"
        for yaml_file in packs_root.rglob("*.yaml"):
            if yaml_file.name == "pack.yaml":
                continue
            try:
                data: dict[str, Any] = yaml.safe_load(yaml_file.read_text(encoding="utf-8")) or {}
            except Exception:
                continue
            if data.get("skill_class") != "workflow":
                continue
            applies: list[Any] = data.get("applies_to_phases") or []
            if phase not in applies:
                continue
            template: Any = data.get("contract_template")
            if template:
                return str(template)
    except Exception:
        pass
    return None


_HANDLERS = {
    "validate": _validate,
    "show": _show,
    "init": _init,
}


def add_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
) -> None:
    p = subparsers.add_parser("contract", help="Manage task contracts.")
    p.add_argument("--human", action="store_true", help="Human-readable output.")
    sub = p.add_subparsers(dest="contract_cmd")

    # validate
    val_p = sub.add_parser("validate", help="Validate a contract file.")
    val_p.add_argument("path", help="Path to the contract markdown file.")

    # show
    show_p = sub.add_parser("show", help="Display a parsed contract.")
    show_p.add_argument("path", help="Path to the contract markdown file.")

    # init
    init_p = sub.add_parser(
        "init", help="Scaffold a contract from the active workflow skill's template."
    )
    init_p.add_argument("--phase", required=True, help="Phase (e.g. build, spec, design).")
    init_p.add_argument("--slug", required=True, help="Task slug (kebab-case identifier).")
    init_p.add_argument("--force", action="store_true", help="Overwrite existing contract.")

    p.set_defaults(func=_run)


def _run(args: argparse.Namespace) -> int:
    cmd = getattr(args, "contract_cmd", None)
    if not cmd:
        print("  Usage: skillsmith contract {validate,show,init}", file=sys.stderr)
        return 1
    handler = _HANDLERS.get(cmd)
    if not handler:
        print(f"  Unknown contract command: {cmd}", file=sys.stderr)
        return 1
    return handler(args)
