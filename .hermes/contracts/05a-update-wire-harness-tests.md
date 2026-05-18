# Contract 5a: Update test_wire_harness.py with Intake Activation Markers

## Objective

Add a `TestIntakeActivationMarkers` class to the end of `tests/install/test_wire_harness.py` that verifies wired templates contain intake activation markers.

## Existing Test File

Full content of `tests/install/test_wire_harness.py` is available on disk — read it for the existing patterns. Key imports to use:

```python
from skillsmith.install.subcommands.wire_harness import (
    SENTINEL_BEGIN, SENTINEL_END, STEP_NAME, VALID_HARNESSES, wire_harness,
)
```

## Tests to Add

Append the following class at the end of the file (after `TestScopeFlag`):

```python
# ---------------------------------------------------------------------------
# Intake activation markers
# ---------------------------------------------------------------------------


class TestIntakeActivationMarkers:
    """Verify wired templates contain intake activation markers.

    Maps to plan: intake activation workflow — harness templates must include
    health-gate, phase lock file reference, and skip-if-non-SDD guidance.
    """

    _INTAKE_MARKERS = [
        ".skillsmith/phase",
        "Health-gate",
        "non-SDD",
    ]

    def test_hermes_agent_has_intake_markers(self, tmp_path: Path) -> None:
        result = wire_harness("hermes-agent", port=8000, root=tmp_path, scope="user")
        content = (tmp_path / ".hermes" / "SOUL.md").read_text()
        for marker in self._INTAKE_MARKERS:
            assert marker in content, f"Missing marker: {marker}"

    def test_claude_code_has_intake_markers(self, repo_root: Path) -> None:
        wire_harness("claude-code", port=8000, root=repo_root)
        content = (repo_root / "CLAUDE.md").read_text()
        for marker in self._INTAKE_MARKERS:
            assert marker in content, f"Missing marker: {marker}"

    def test_all_harnesses_have_phase_reference(self, repo_root: Path) -> None:
        """Smoke test: every harness template references .skillsmith/phase."""
        for harness in VALID_HARNESSES:
            state_file = repo_root / ".skillsmith" / "install-state.json"
            if state_file.exists():
                state_file.unlink()
            if harness == "mcp-only":
                continue
            result = wire_harness(harness, port=8000, root=repo_root)
            for entry in result["files_written"]:
                path = Path(entry["path"])
                if path.exists():
                    content = path.read_text()
                    assert ".skillsmith/phase" in content, (
                        f"Harness {harness} at {path} missing phase reference"
                    )
```

## Acceptance Criteria

- `TestIntakeActivationMarkers` class added with 3 test methods
- All existing tests continue to pass
- New tests verify `.skillsmith/phase`, `Health-gate`, and `non-SDD` markers appear in wired templates
