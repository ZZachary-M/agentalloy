"""``uninstall`` subcommand.

Removes harness wiring (sentinel-bounded), ``.env``, ``install-state.json``,
the native service unit / plist (if any), and the uv tool installation.
Preserves ``data/`` by default.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from skillsmith.install import state as install_state
from skillsmith.install.subcommands.wire_harness import SENTINEL_BEGIN, SENTINEL_END

SCHEMA_VERSION = 1


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def _extract_sentinel_content(text: str, begin: str, end: str) -> str | None:
    """Extract the content between sentinel markers, or None if not found."""
    if begin not in text or end not in text:
        return None
    b = text.index(begin) + len(begin)
    e = text.index(end)
    return text[b:e].strip()


def _remove_sentinel_block(text: str, begin: str, end: str) -> str:
    """Remove the sentinel block (inclusive) from text."""
    if begin not in text or end not in text:
        return text
    b = text.index(begin)
    e = text.index(end) + len(end)
    # Consume trailing newline
    if e < len(text) and text[e] == "\n":
        e += 1
    elif e + 1 < len(text) and text[e : e + 2] == "\r\n":
        e += 2
    # Consume blank line before block if present
    if b > 0 and text[b - 1] == "\n":
        b -= 1
        if b > 0 and text[b - 1] == "\n":
            b -= 1
    result = text[:b] + text[e:]
    # Clean up double blank lines
    while "\n\n\n" in result:
        result = result.replace("\n\n\n", "\n\n")
    return result


def _stop_native_service(st: dict[str, Any]) -> list[dict[str, Any]]:
    """Stop and disable the native systemd/launchd service if one was registered."""
    actions: list[dict[str, Any]] = []
    mode = st.get("service_mode")
    unit_path_str = st.get("service_unit_path")
    if mode != "native" or not unit_path_str:
        return actions

    unit_path = Path(unit_path_str)
    os_name = sys.platform

    if os_name == "linux" and unit_path.suffix == ".service":
        unit_name = unit_path.name
        for cmd in (
            ["systemctl", "--user", "disable", "--now", unit_name],
            ["systemctl", "--user", "daemon-reload"],
        ):
            with contextlib.suppress(OSError, subprocess.TimeoutExpired):
                subprocess.run(cmd, capture_output=True, timeout=10)
        if unit_path.exists():
            unit_path.unlink()
            actions.append({"path": str(unit_path), "action": "deleted_systemd_unit"})
        # Also remove the sanitized env file written alongside the unit
        sanitized = unit_path.parent / "skillsmith.env"
        if sanitized.exists():
            sanitized.unlink()
            actions.append({"path": str(sanitized), "action": "deleted_systemd_env"})

    elif os_name == "darwin" and unit_path.suffix == ".plist":
        with contextlib.suppress(OSError, subprocess.TimeoutExpired):
            subprocess.run(
                ["launchctl", "unload", "-w", str(unit_path)],
                capture_output=True,
                timeout=10,
            )
        if unit_path.exists():
            unit_path.unlink()
            actions.append({"path": str(unit_path), "action": "deleted_launchd_plist"})

    return actions


def _remove_uv_tool() -> dict[str, Any]:
    """Remove the uv tool installation. Returns an action dict."""
    uv = shutil.which("uv")
    if not uv:
        return {"action": "uv_tool_skipped", "reason": "uv not found in PATH"}
    try:
        result = subprocess.run(
            [uv, "tool", "uninstall", "skillsmith"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return {"action": "uv_tool_uninstalled"}
        # uv exits non-zero if the tool wasn't installed — treat as already gone
        return {"action": "uv_tool_skipped", "reason": result.stderr.strip() or "not installed"}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"action": "uv_tool_skipped", "reason": str(exc)}


def uninstall(
    remove_data: bool = False,
    force: bool = False,
    root: Path | None = None,
    *,
    remove_user_state: bool = True,
    remove_env: bool = True,
) -> dict[str, Any]:
    """Remove harness wiring, .env, and state. Returns contract-shaped result.

    ``remove_user_state`` and ``remove_env`` are False for the per-repo
    ``unwire`` verb, which must touch only sentinels in the cwd repo and
    leave the user-scope `${XDG_CONFIG_HOME}/skillsmith/` directory alone.
    Default True preserves the original full-teardown behavior of
    `uninstall` so existing callers don't change semantics.
    """
    from skillsmith.install.state import _repo_root  # pyright: ignore[reportPrivateUsage]

    root = root or _repo_root()
    st = install_state.load_state(root)

    files_modified: list[dict[str, Any]] = []
    files_removed: list[dict[str, Any]] = []
    warnings: list[str] = []

    # 1. Remove harness wiring. State is user-scoped and may carry entries
    # from multiple repos, but the containment check MUST use a trusted
    # bound — both `path` and `repo_root` come from the state file and a
    # tampered entry like `{"path": "/etc/shadow", "repo_root": "/etc"}`
    # would otherwise pass a per-entry check trivially. The trusted bound
    # is the cwd-derived `root` (or the known per-tool user config dirs).
    # An entry whose recorded `repo_root` doesn't match cwd is skipped at
    # this invocation; the user can `cd` into that repo to clean it up.
    home = Path.home()
    allowed_user_prefixes = (
        home / ".claude",
        home / ".cursor",
        home / ".continue",
    )
    # Set of harness target basenames / suffix-paths we ever write. Any
    # `path` in state that doesn't end in one of these is rejected even
    # if the containment check would otherwise allow it.
    allowed_path_suffixes = (
        "CLAUDE.md",
        "GEMINI.md",
        ".clinerules",
        ".cursorrules",
        ".cursor/rules/skillsmith.mdc",
        ".continuerc.json",
        ".cursor/mcp.json",
        ".aider.conf.yml",
        ".skillsmith-aider-instructions.md",
        ".opencode/system-prompt.md",
        "mcp_servers.json",  # ~/.claude/mcp_servers.json
    )
    root_resolved = root.resolve()
    for entry in st.get("harness_files_written", []):
        raw_path = entry.get("path")
        if not isinstance(raw_path, str) or not raw_path:
            warnings.append(f"Skipping harness entry with non-string path: {entry!r}")
            continue
        path = Path(raw_path)
        # Reject paths that don't end in a known harness target — defends
        # against tampered entries like `/etc/shadow`.
        if not any(str(path).endswith(suffix) for suffix in allowed_path_suffixes):
            warnings.append(
                f"Skipping harness entry with non-harness path (state may be tampered): {raw_path}"
            )
            continue
        # Containment is checked against the trusted cwd-derived root, NOT
        # the entry's recorded repo_root (which is itself in the state file).
        path_inside_cwd_repo = install_state.is_inside_root(path, root)
        path_inside_user = any(
            install_state.is_inside_root(path, p) for p in allowed_user_prefixes if p.exists()
        )
        if not (path_inside_cwd_repo or path_inside_user):
            # Entry belongs to a different repo. Skip silently — running
            # uninstall in this cwd shouldn't touch other repos. Track
            # the skip so the user can see why state still has entries.
            entry_repo_root = entry.get("repo_root")
            warnings.append(
                f"Skipping harness entry from a different repo "
                f"(repo_root={entry_repo_root!r}, run uninstall there to clean it up): "
                f"{raw_path}"
            )
            continue
        # Defense in depth: even when path passes containment, refuse to
        # follow into the trusted root via a path that escapes via `..`.
        try:
            resolved = path.resolve()
            if path_inside_cwd_repo and not str(resolved).startswith(str(root_resolved)):
                warnings.append(
                    f"Skipping harness entry that escapes repo root via symlink: {raw_path}"
                )
                continue
        except OSError:
            warnings.append(f"Cannot resolve harness path: {raw_path}")
            continue
        if not path.exists():
            warnings.append(f"Harness file not found (already removed?): {path}")
            continue

        content = path.read_text()
        sentinel_begin = entry.get("sentinel_begin", SENTINEL_BEGIN)
        sentinel_end = entry.get("sentinel_end", SENTINEL_END)

        if sentinel_begin and sentinel_begin in content and sentinel_end in content:
            # Check if content was modified inside sentinels
            current_inner = _extract_sentinel_content(content, sentinel_begin, sentinel_end)
            stored_sha = entry.get("content_sha256", "")

            # For dedicated files (no sentinels in content), just delete
            if entry.get("action") == "wrote_new_file":
                path.unlink()
                files_removed.append({"path": str(path), "action": "deleted_dedicated_file"})
                continue

            if current_inner is not None and stored_sha:
                # Verify the inner content hasn't drifted since wire-harness wrote it.
                # If it has, the user (or another tool) edited inside the sentinels;
                # without --force, refuse to clobber their changes.
                current_sha = _sha256(current_inner)
                expected = (
                    stored_sha[len("sha256:") :] if stored_sha.startswith("sha256:") else stored_sha
                )
                if current_sha != expected and not force:
                    warnings.append(
                        f"Tampered sentinel block in {path} (sha256 mismatch). "
                        f"Skipped to preserve your edits — use --force to remove anyway."
                    )
                    continue

            cleaned = _remove_sentinel_block(content, sentinel_begin, sentinel_end)
            if cleaned.strip():
                path.write_text(cleaned)
                files_modified.append({"path": str(path), "action": "removed_sentinel_block"})
            else:
                # File is now empty after removing our block — delete it
                path.unlink()
                files_removed.append({"path": str(path), "action": "deleted_empty_file"})
        elif entry.get("action") == "wrote_new_file":
            # Dedicated file (no sentinels) — delete it
            path.unlink()
            files_removed.append({"path": str(path), "action": "deleted_dedicated_file"})
        else:
            if force:
                path.unlink()
                files_removed.append({"path": str(path), "action": "force_deleted"})
            else:
                warnings.append(
                    f"Sentinel block not found in {path} — skipped. Use --force to delete anyway."
                )

    # 2. Handle Continue.dev marker cleanup (markdown injection variant)
    continuerc = root / ".continuerc.json"
    if continuerc.exists():
        try:
            config = json.loads(continuerc.read_text())
            modified = False

            # 2a. Remove the skillsmith MCP server entry, if present
            servers = config.get("mcpServers")
            if isinstance(servers, dict) and "skillsmith" in servers:
                del servers["skillsmith"]
                if not servers:
                    del config["mcpServers"]
                modified = True

            if "_skillsmith_install_marker" in config:
                # Remove our custom command
                commands = config.get("customCommands", [])
                config["customCommands"] = [c for c in commands if c.get("name") != "skill"]
                if not config["customCommands"]:
                    del config["customCommands"]

                # Remove system message sentinel block
                sys_msg = config.get("systemMessage", "")
                if "<!-- skillsmith:begin -->" in sys_msg:
                    b = sys_msg.index("<!-- skillsmith:begin -->")
                    e = sys_msg.index("<!-- skillsmith:end -->") + len("<!-- skillsmith:end -->")
                    sys_msg = sys_msg[:b].rstrip() + sys_msg[e:].lstrip()
                    if sys_msg.strip():
                        config["systemMessage"] = sys_msg.strip()
                    else:
                        del config["systemMessage"]

                del config["_skillsmith_install_marker"]
                modified = True

            if modified:
                if any(k for k in config if not k.startswith("_")):
                    install_state._atomic_write(  # pyright: ignore[reportPrivateUsage]
                        continuerc, json.dumps(config, indent=2) + "\n"
                    )
                    files_modified.append({"path": str(continuerc), "action": "cleaned_continuerc"})
                else:
                    continuerc.unlink()
                    files_removed.append(
                        {"path": str(continuerc), "action": "deleted_empty_continuerc"}
                    )
        except json.JSONDecodeError:
            warnings.append(f"Could not parse {continuerc} as JSON — skipped")

    # 2b. Handle Cursor MCP config cleanup (.cursor/mcp.json)
    cursor_mcp = root / ".cursor" / "mcp.json"
    if cursor_mcp.exists():
        try:
            cfg = json.loads(cursor_mcp.read_text())
            servers = cfg.get("mcpServers")
            if isinstance(servers, dict) and "skillsmith" in servers:
                del servers["skillsmith"]
                if not servers:
                    cfg.pop("mcpServers", None)
                if cfg:
                    install_state._atomic_write(  # pyright: ignore[reportPrivateUsage]
                        cursor_mcp, json.dumps(cfg, indent=2) + "\n"
                    )
                    files_modified.append({"path": str(cursor_mcp), "action": "removed_mcp_entry"})
                else:
                    cursor_mcp.unlink()
                    files_removed.append({"path": str(cursor_mcp), "action": "deleted_empty_file"})
        except json.JSONDecodeError:
            warnings.append(f"Could not parse {cursor_mcp} as JSON — skipped")

    # 2c. Handle user-scoped Claude Code MCP config (~/.claude/mcp_servers.json)
    claude_mcp = Path.home() / ".claude" / "mcp_servers.json"
    if claude_mcp.exists():
        try:
            cfg = json.loads(claude_mcp.read_text())
            servers = cfg.get("mcpServers")
            if isinstance(servers, dict) and "skillsmith" in servers:
                del servers["skillsmith"]
                if not servers:
                    cfg.pop("mcpServers", None)
                if cfg:
                    install_state._atomic_write(  # pyright: ignore[reportPrivateUsage]
                        claude_mcp, json.dumps(cfg, indent=2) + "\n"
                    )
                    files_modified.append({"path": str(claude_mcp), "action": "removed_mcp_entry"})
                else:
                    claude_mcp.unlink()
                    files_removed.append({"path": str(claude_mcp), "action": "deleted_empty_file"})
        except json.JSONDecodeError:
            warnings.append(f"Could not parse {claude_mcp} as JSON — skipped")

    # 3. Handle aider config cleanup
    aider_conf = root / ".aider.conf.yml"
    if aider_conf.exists():
        content = aider_conf.read_text()
        aider_begin = "# <!-- BEGIN skillsmith install -->"
        aider_end = "# <!-- END skillsmith install -->"
        if aider_begin in content:
            cleaned = _remove_sentinel_block(content, aider_begin, aider_end)
            if cleaned.strip():
                aider_conf.write_text(cleaned)
                files_modified.append({"path": str(aider_conf), "action": "removed_sentinel_block"})
            else:
                aider_conf.unlink()
                files_removed.append({"path": str(aider_conf), "action": "deleted_empty_file"})

    # 4. Remove user-scope .env (skipped by `unwire`)
    if remove_env:
        env_path = install_state.env_path()
        if env_path.exists():
            env_path.unlink()
            files_removed.append({"path": str(env_path), "action": "deleted"})

    # 5. Handle the user corpus dir
    data_kept: list[str] = []
    data_dir = install_state.corpus_dir()
    if remove_data and data_dir.exists():
        shutil.rmtree(data_dir)
        files_removed.append({"path": str(data_dir), "action": "deleted_data_directory"})
    elif data_dir.exists():
        data_kept.append(str(data_dir))

    # 6. Stop and remove native service unit / plist (skipped by `unwire`)
    service_actions: list[dict[str, Any]] = []
    if remove_user_state:
        service_actions = _stop_native_service(st)
        files_removed.extend(service_actions)

    # 7. Remove user-scope state directory (skipped by `unwire`)
    if remove_user_state:
        state_d = install_state.state_dir()
        if state_d.exists():
            shutil.rmtree(state_d)
            files_removed.append({"path": str(state_d), "action": "deleted_state_directory"})

    # 8. Remove uv tool installation (skipped by `unwire`)
    uv_tool_result: dict[str, Any] = {}
    if remove_user_state:
        uv_tool_result = _remove_uv_tool()

    return {
        "schema_version": SCHEMA_VERSION,
        "files_modified": files_modified,
        "files_removed": files_removed,
        "data_kept": data_kept,
        "warnings": warnings,
        "uv_tool": uv_tool_result,
    }


# ---------------------------------------------------------------------------
# Subcommand interface
# ---------------------------------------------------------------------------


def add_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
) -> None:
    p: argparse.ArgumentParser = subparsers.add_parser(
        "uninstall",
        help="Remove harness wiring, .env, and state files.",
    )
    p.add_argument(
        "--remove-data",
        action="store_true",
        default=False,
        help="Also remove data/ directory (default: preserve).",
    )
    p.add_argument(
        "--keep-data",
        action="store_true",
        default=False,
        help="Explicit opt-in for the default behavior (no-op).",
    )
    p.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Force removal even when sentinel blocks are missing or modified.",
    )
    p.set_defaults(func=_run)


def _run(args: argparse.Namespace) -> int:
    result = uninstall(remove_data=args.remove_data, force=args.force)
    print(json.dumps(result, indent=2))
    return 0
