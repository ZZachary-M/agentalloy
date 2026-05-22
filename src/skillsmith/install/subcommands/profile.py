"""``skillsmith profile`` — profile management subcommand.

Commands:
    skillsmith profile list                       — list all configured profiles
    skillsmith profile current                    — show active profile for cwd
    skillsmith profile init <name>                — create a new profile
    skillsmith profile set-default <name>         — change the fallback default
    skillsmith profile delete <name>              — remove a profile
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _list(args: argparse.Namespace) -> int:
    from skillsmith.profiles import list_profiles

    profiles = list_profiles(cwd=Path.cwd())
    if getattr(args, "human", False):
        for p in profiles:
            active = " *" if p["active_for_cwd"] else ""
            print(f"  {p['name']}{active}")
            if p["match_remote"]:
                print(f"    match_remote: {p['match_remote']}")
            if p["match_path"]:
                print(f"    match_path: {p['match_path']}")
            print(f"    has_overrides: {p['has_overrides']}")
    else:
        print(json.dumps(profiles, indent=2))
    return 0


def _current(args: argparse.Namespace) -> int:
    from skillsmith.profiles import detect_profile

    profile = detect_profile(cwd=Path.cwd())
    result: dict[str, Any] = {
        "name": profile.name,
        "datastore_path": str(profile.datastore_path),
        "skills_dir": str(profile.skills_dir),
        "is_default": profile.is_default,
    }
    if getattr(args, "human", False):
        print(f"  Profile:   {result['name']}")
        print(f"  Datastore: {result['datastore_path']}")
    else:
        print(json.dumps(result, indent=2))
    return 0


def _init(args: argparse.Namespace) -> int:
    from skillsmith.profiles import init_profile

    name: str = args.name
    match_remote: list[str] | None = getattr(args, "match_remote", None) or None
    match_path: list[str] | None = getattr(args, "match_path", None) or None

    # Interactive prompts when running in a TTY and no patterns were given.
    if sys.stdin.isatty() and not args.non_interactive:
        if not match_remote:
            raw = input("  Match git remote pattern (leave blank to skip): ").strip()
            if raw:
                match_remote = [raw]
        if not match_path:
            raw = input("  Match path pattern (leave blank to skip): ").strip()
            if raw:
                match_path = [raw]

    try:
        profile = init_profile(name, match_remote=match_remote, match_path=match_path)
    except (ValueError, KeyError) as exc:
        print(f"  [error] {exc}", file=sys.stderr)
        return 1

    result: dict[str, Any] = {
        "name": profile.name,
        "datastore_path": str(profile.datastore_path),
        "skills_dir": str(profile.skills_dir),
        "match_remote": match_remote or [],
        "match_path": match_path or [],
    }
    if getattr(args, "human", False):
        print(f"  Created profile '{profile.name}' at {profile.skills_dir}")
    else:
        print(json.dumps(result, indent=2))
    return 0


def _set_default(args: argparse.Namespace) -> int:
    from skillsmith.profiles import set_default_profile

    try:
        set_default_profile(args.name)
    except (ValueError, KeyError) as exc:
        print(f"  [error] {exc}", file=sys.stderr)
        return 1

    result = {"default_profile": args.name}
    if getattr(args, "human", False):
        print(f"  Default profile set to '{args.name}'")
    else:
        print(json.dumps(result, indent=2))
    return 0


def _delete(args: argparse.Namespace) -> int:
    from skillsmith.profiles import delete_profile

    name: str = args.name

    # Confirmation prompt unless --yes passed.
    if not getattr(args, "yes", False) and sys.stdin.isatty():
        confirm = input(f"  Delete profile '{name}' and all its overrides? (yes/n): ").strip()
        if confirm.lower() != "yes":
            print("  Cancelled.")
            return 0

    try:
        delete_profile(name)
    except (ValueError, KeyError) as exc:
        print(f"  [error] {exc}", file=sys.stderr)
        return 1

    result = {"deleted": name}
    if getattr(args, "human", False):
        print(f"  Profile '{name}' deleted.")
    else:
        print(json.dumps(result, indent=2))
    return 0


_PROFILE_SUBCOMMANDS = {
    "list": _list,
    "current": _current,
    "init": _init,
    "set-default": _set_default,
    "delete": _delete,
}


def add_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
) -> None:
    p = subparsers.add_parser("profile", help="Manage skillsmith profiles.")
    p.add_argument("--human", action="store_true", help="Human-readable output instead of JSON.")
    p.add_argument("--non-interactive", action="store_true", dest="non_interactive", default=False)
    sub = p.add_subparsers(dest="profile_cmd")

    # list
    sub.add_parser("list", help="List all configured profiles.")

    # current
    sub.add_parser("current", help="Show the active profile for the current directory.")

    # init
    init_p = sub.add_parser("init", help="Create a new profile.")
    init_p.add_argument("name", help="Profile name.")
    init_p.add_argument(
        "--match-remote",
        dest="match_remote",
        nargs="*",
        help="Git remote URL glob patterns that activate this profile.",
    )
    init_p.add_argument(
        "--match-path",
        dest="match_path",
        nargs="*",
        help="Path glob patterns that activate this profile.",
    )

    # set-default
    sd_p = sub.add_parser("set-default", help="Change the fallback default profile.")
    sd_p.add_argument("name", help="Profile name.")

    # delete
    del_p = sub.add_parser("delete", help="Remove a profile.")
    del_p.add_argument("name", help="Profile name.")
    del_p.add_argument("--yes", action="store_true", help="Skip confirmation prompt.")

    p.set_defaults(func=_run)


def _run(args: argparse.Namespace) -> int:
    cmd = getattr(args, "profile_cmd", None)
    if not cmd:
        print("  Usage: skillsmith profile {list,current,init,set-default,delete}", file=sys.stderr)
        return 1
    handler = _PROFILE_SUBCOMMANDS.get(cmd)
    if not handler:
        print(f"  Unknown profile command: {cmd}", file=sys.stderr)
        return 1
    return handler(args)
