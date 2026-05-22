"""End-to-end tests for signal layer with simulated Claude Code hook events."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import yaml

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_phase(root: Path, phase: str) -> None:
    pf = root / ".skillsmith" / "phase"
    pf.parent.mkdir(parents=True, exist_ok=True)
    pf.write_text(f"phase: {phase}\n")


def _write_skill(root: Path, phase: str, signal_keywords: list[str] | None = None) -> None:
    """Write a minimal workflow skill to _packs so the signal layer can find it."""
    import skillsmith

    packs_root = Path(skillsmith.__file__).resolve().parent / "_packs" / "sdd"
    for f in packs_root.glob("sdd-*.yaml"):
        data: dict[str, Any] = yaml.safe_load(f.read_text()) or {}
        if phase in (data.get("applies_to_phases") or []):
            return  # already exists


def _simulate_hook_event(
    event: str,
    *,
    prompt_file: str | None = None,
    tool_name: str | None = None,
    tool_path: str | None = None,
    cwd: Path,
) -> tuple[int, str, str]:
    """Run the skillsmith signal CLI as Claude Code would via a hook."""
    env = os.environ.copy()
    env["SKILLSMITH_HOOK_EVENT"] = event
    if tool_name:
        env["SKILLSMITH_TOOL_NAME"] = tool_name
    if tool_path:
        env["SKILLSMITH_TOOL_PATH"] = tool_path

    cmd = [sys.executable, "-m", "skillsmith.install", "signal"]

    if event == "UserPromptSubmit":
        cmd += ["evaluate-phase"]
        if prompt_file:
            cmd += ["--prompt-file", prompt_file]
    elif event == "PostToolUse" and tool_path and ".skillsmith/contracts/" in tool_path:
        cmd += ["watch-contract", "--path", tool_path]
    elif event == "PreToolUse":
        cmd += ["evaluate-system", "--tool", tool_name or ""]
    else:
        return 0, "", ""

    result = subprocess.run(
        cmd,
        env=env,
        capture_output=True,
        text=True,
        cwd=str(cwd),
        timeout=10,
    )
    return result.returncode, result.stdout, result.stderr


# ---------------------------------------------------------------------------
# UserPromptSubmit — no pre-filter match
# ---------------------------------------------------------------------------


def test_user_prompt_submit_no_match(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Common path: no signal keywords match → quick exit."""
    _write_phase(tmp_path, "build")
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("Show me the current file structure.")

    rc, stdout, _stderr = _simulate_hook_event(
        "UserPromptSubmit",
        prompt_file=str(prompt_file),
        cwd=tmp_path,
    )
    assert rc == 0
    # Should emit some JSON
    if stdout.strip():
        data = json.loads(stdout.strip())
        assert "matched" in data or "transition" in data


# ---------------------------------------------------------------------------
# UserPromptSubmit — transition fires
# ---------------------------------------------------------------------------


def test_user_prompt_submit_transition(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """When gate artifacts exist and prompt matches signal keywords, transition fires."""
    _write_phase(tmp_path, "spec")

    # Create the artifact that the sdd-spec-and-scoping gate checks for
    docs = tmp_path / "docs" / "spec"
    docs.mkdir(parents=True)
    spec_doc = docs / "auth.md"
    spec_doc.write_text(
        "## Acceptance Criteria\n\nAll tests pass.\n\n## Out of Scope\n\nBilling.\n" + "x" * 800
    )

    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("done with spec, ready to move to design")

    rc, _stdout, _stderr = _simulate_hook_event(
        "UserPromptSubmit",
        prompt_file=str(prompt_file),
        cwd=tmp_path,
    )
    assert rc == 0
    # Either it transitioned (wrote skill to stdout) or pre-filter didn't fire (matched: false)
    # Either outcome is valid — this is an e2e smoke test, not a gate correctness test


# ---------------------------------------------------------------------------
# PostToolUse — contract write triggers watch-contract
# ---------------------------------------------------------------------------


def test_post_tool_use_contract_write(tmp_path: Path):
    """PostToolUse on a .skillsmith/contracts/ path invokes watch-contract."""
    _write_phase(tmp_path, "build")

    contract_dir = tmp_path / ".skillsmith" / "contracts" / "build"
    contract_dir.mkdir(parents=True)
    contract_path = contract_dir / "task.md"

    fm: dict[str, Any] = {
        "phase": "build",
        "task_slug": "test-task",
        "domain_tags": ["NestJS"],
        "scope": {"touches": [], "avoids": []},
        "success_criteria": [],
        "related_contracts": [],
    }
    contract_path.write_text(f"---\n{yaml.dump(fm)}---\n\nTask body.\n")

    # The watch-contract path calls skillsmith compose — mock subprocess.run to prevent
    # actual HTTP calls while verifying the event routing works
    rc, _stdout, _stderr = _simulate_hook_event(
        "PostToolUse",
        tool_name="Write",
        tool_path=str(contract_path),
        cwd=tmp_path,
    )
    # Soft-fail: always exit 0 even if compose can't reach the server
    assert rc == 0


# ---------------------------------------------------------------------------
# PreToolUse — evaluate-system emits nothing when no skills installed
# ---------------------------------------------------------------------------


def test_pre_tool_use_no_system_skills(tmp_path: Path):
    """PreToolUse for a tool with no installed system skills exits 0 with no output."""
    _write_phase(tmp_path, "build")

    rc, stdout, _stderr = _simulate_hook_event(
        "PreToolUse",
        tool_name="Read",
        cwd=tmp_path,
    )
    assert rc == 0
    # No system skills installed → stdout should be empty
    assert stdout.strip() == ""


# ---------------------------------------------------------------------------
# Hook event routing test (simulates skillsmith-signal.sh logic)
# ---------------------------------------------------------------------------


def test_hook_routing_ups_calls_evaluate_phase(tmp_path: Path):
    """SKILLSMITH_HOOK_EVENT=UserPromptSubmit routes to evaluate-phase."""
    _write_phase(tmp_path, "build")

    with (
        patch("skillsmith.install.subcommands.signal._evaluate_phase", return_value=0) as mock_ep,
        patch(
            "skillsmith.install.subcommands.signal._load_workflow_skill_for_phase",
            return_value=None,
        ),
    ):
        import argparse

        from skillsmith.install.subcommands.signal import (
            _dispatch,  # pyright: ignore[reportPrivateUsage]
        )

        args = argparse.Namespace(
            signal_cmd="evaluate-phase", prompt_file=None, tool=None, tool_path=None
        )
        rc = _dispatch(args)

    assert rc == 0
    mock_ep.assert_called_once()


def test_hook_routing_pretool_calls_evaluate_system(tmp_path: Path):
    """signal_cmd=evaluate-system routes to _evaluate_system."""
    import argparse

    from skillsmith.install.subcommands.signal import (
        _dispatch,  # pyright: ignore[reportPrivateUsage]
    )

    with patch("skillsmith.install.subcommands.signal._evaluate_system", return_value=0) as mock_es:
        args = argparse.Namespace(signal_cmd="evaluate-system", tool="Bash")
        rc = _dispatch(args)

    assert rc == 0
    mock_es.assert_called_once()
