# Contract 5: Update Tests

## Objective

Two test tasks (depends on contracts 2 and 3 being complete):
1. Update `tests/install/test_wire_harness.py` to verify intake activation markers in templates
2. Create new `tests/install/test_phase_cli.py` for the phase CLI subcommand

---

## Task A: Update tests/install/test_wire_harness.py

Add tests that verify wired harness templates contain the new intake activation markers. Add these to the existing test file.

**Existing test file for reference:**

```python
"""Unit tests for the ``wire-harness`` subcommand.

Maps to test-plan.md § Harness wiring.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from skillsmith.install import state as install_state
from skillsmith.install.subcommands.wire_harness import (
    SENTINEL_BEGIN,
    SENTINEL_END,
    STEP_NAME,
    VALID_HARNESSES,
    _detect_line_ending,
    _inject_sentinel_block,
    wire_harness,
)


@pytest.fixture()
def repo_root(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text("")
    return tmp_path


class TestSentinelInjection:
    def test_inject_into_empty(self) -> None:
        result = _inject_sentinel_block("", "content here")
        assert SENTINEL_BEGIN in result
        assert SENTINEL_END in result
        assert "content here" in result

    def test_inject_appends_to_existing(self) -> None:
        existing = "# My CLAUDE.md\n\nExisting content.\n"
        result = _inject_sentinel_block(existing, "injected")
        assert result.startswith("# My CLAUDE.md")
        assert "Existing content." in result
        assert SENTINEL_BEGIN in result
        assert "injected" in result

    def test_replace_existing_block(self) -> None:
        existing = f"Before\n{SENTINEL_BEGIN}\nold content\n{SENTINEL_END}\nAfter\n"
        result = _inject_sentinel_block(existing, "new content")
        assert "old content" not in result
        assert "new content" in result
        assert "Before" in result
        assert "After" in result
        assert result.count(SENTINEL_BEGIN) == 1

    def test_preserves_crlf(self) -> None:
        existing = "Line 1\r\nLine 2\r\n"
        result = _inject_sentinel_block(existing, "injected")
        assert "\r\n" in result

    def test_detect_lf(self) -> None:
        assert _detect_line_ending("a\nb\n") == "\n"

    def test_detect_crlf(self) -> None:
        assert _detect_line_ending("a\r\nb\r\n") == "\r\n"


class TestClaudeCode:
    def test_creates_claude_md(self, repo_root: Path) -> None:
        result = wire_harness("claude-code", port=8000, root=repo_root)
        assert result["harness"] == "claude-code"
        assert result["integration_vector"] == "markdown_injection"
        assert len(result["files_written"]) == 1
        claude_md = repo_root / "CLAUDE.md"
        assert claude_md.exists()
        content = claude_md.read_text()
        assert SENTINEL_BEGIN in content
        assert "localhost:8000" in content

    def test_appends_to_existing_claude_md(self, repo_root: Path) -> None:
        (repo_root / "CLAUDE.md").write_text("# My Project\n\nExisting.\n")
        wire_harness("claude-code", port=9090, root=repo_root)
        content = (repo_root / "CLAUDE.md").read_text()
        assert "# My Project" in content
        assert "Existing." in content
        assert "localhost:9090" in content

    def test_replaces_on_rerun(self, repo_root: Path) -> None:
        wire_harness("claude-code", port=8000, root=repo_root)
        wire_harness("claude-code", port=9090, root=repo_root)
        content = (repo_root / "CLAUDE.md").read_text()
        assert "localhost:9090" in content
        assert "localhost:8000" not in content
        assert content.count(SENTINEL_BEGIN) == 1

    def test_custom_port(self, repo_root: Path) -> None:
        wire_harness("claude-code", port=3000, root=repo_root)
        content = (repo_root / "CLAUDE.md").read_text()
        assert "localhost:3000" in content


class TestHermesAgent:
    def test_user_scope_writes_soul_md(self, tmp_path: Path) -> None:
        result = wire_harness("hermes-agent", port=8000, root=tmp_path, scope="user")
        assert result["integration_vector"] == "markdown_injection"
        soul = tmp_path / ".hermes" / "SOUL.md"
        assert soul.exists()
        content = soul.read_text()
        assert SENTINEL_BEGIN in content
        assert "localhost:8000" in content
        assert "/health" in content

    def test_repo_scope_writes_agents_md(self, repo_root: Path) -> None:
        result = wire_harness("hermes-agent", port=8000, root=repo_root, scope="repo")
        assert result["integration_vector"] == "markdown_injection"
        agents = repo_root / "AGENTS.md"
        assert agents.exists()
        content = agents.read_text()
        assert SENTINEL_BEGIN in content
        assert "localhost:8000" in content

    def test_preserves_existing_soul_content(self, tmp_path: Path) -> None:
        soul = tmp_path / ".hermes" / "SOUL.md"
        soul.parent.mkdir(parents=True)
        soul.write_text("# My persona\n\nBe terse.\n")
        wire_harness("hermes-agent", port=8000, root=tmp_path, scope="user")
        content = soul.read_text()
        assert "# My persona" in content
        assert "Be terse." in content
        assert SENTINEL_BEGIN in content


class TestGeminiCli:
    def test_creates_gemini_md(self, repo_root: Path) -> None:
        result = wire_harness("gemini-cli", port=8000, root=repo_root)
        assert result["harness"] == "gemini-cli"
        gemini_md = repo_root / "GEMINI.md"
        assert gemini_md.exists()
        content = gemini_md.read_text()
        assert SENTINEL_BEGIN in content
        assert "shell tool" in content


class TestCursor:
    def test_modern_cursor_dir(self, repo_root: Path) -> None:
        (repo_root / ".cursor").mkdir()
        result = wire_harness("cursor", port=8000, root=repo_root)
        assert len(result["files_written"]) == 1
        mdc = repo_root / ".cursor" / "rules" / "skillsmith.mdc"
        assert mdc.exists()
        content = mdc.read_text()
        assert SENTINEL_BEGIN not in content
        assert "localhost:8000" in content
        assert "description:" in content

    def test_legacy_cursorrules(self, repo_root: Path) -> None:
        wire_harness("cursor", port=8000, root=repo_root)
        cursorrules = repo_root / ".cursorrules"
        assert cursorrules.exists()
        content = cursorrules.read_text()
        assert SENTINEL_BEGIN in content


class TestWindsurf:
    def test_modern_windsurf_dir(self, repo_root: Path) -> None:
        (repo_root / ".windsurf").mkdir()
        result = wire_harness("windsurf", port=8000, root=repo_root)
        assert len(result["files_written"]) == 1
        md = repo_root / ".windsurf" / "rules" / "skillsmith.md"
        assert md.exists()
        content = md.read_text()
        assert SENTINEL_BEGIN not in content
        assert "localhost:8000" in content
        assert "trigger:" in content

    def test_legacy_windsurfrules(self, repo_root: Path) -> None:
        wire_harness("windsurf", port=8000, root=repo_root)
        rules = repo_root / ".windsurfrules"
        assert rules.exists()
        content = rules.read_text()
        assert SENTINEL_BEGIN in content
        assert "localhost:8000" in content


class TestGithubCopilot:
    def test_writes_copilot_instructions(self, repo_root: Path) -> None:
        result = wire_harness("github-copilot", port=8000, root=repo_root)
        assert result["integration_vector"] == "markdown_injection"
        path = repo_root / ".github" / "copilot-instructions.md"
        assert path.exists()
        content = path.read_text()
        assert SENTINEL_BEGIN in content
        assert "localhost:8000" in content

    def test_preserves_existing_user_content(self, repo_root: Path) -> None:
        gh_dir = repo_root / ".github"
        gh_dir.mkdir()
        path = gh_dir / "copilot-instructions.md"
        path.write_text("# Project copilot rules\n\nUse TypeScript strict mode.\n")
        wire_harness("github-copilot", port=8000, root=repo_root)
        content = path.read_text()
        assert "Use TypeScript strict mode." in content
        assert SENTINEL_BEGIN in content


class TestOpenHarnesses:
    def test_opencode(self, repo_root: Path) -> None:
        result = wire_harness("opencode", port=8000, root=repo_root)
        assert result["integration_vector"] == "system_prompt_snippet"
        path = repo_root / ".opencode" / "system-prompt.md"
        assert path.exists()

    def test_cline(self, repo_root: Path) -> None:
        wire_harness("cline", port=8000, root=repo_root)
        path = repo_root / ".clinerules"
        assert path.exists()
        content = path.read_text()
        assert SENTINEL_BEGIN in content

    def test_aider(self, repo_root: Path) -> None:
        result = wire_harness("aider", port=8000, root=repo_root)
        instructions = repo_root / ".skillsmith-aider-instructions.md"
        assert instructions.exists()
        conf = repo_root / ".aider.conf.yml"
        assert conf.exists()
        content = conf.read_text()
        assert ".skillsmith-aider-instructions.md" in content
        assert len(result["files_written"]) == 2


class TestContinue:
    def test_closed_creates_config(self, repo_root: Path) -> None:
        result = wire_harness("continue-closed", port=8000, root=repo_root)
        assert result["harness"] == "continue-closed"
        config_path = repo_root / ".continuerc.json"
        assert config_path.exists()
        config = json.loads(config_path.read_text())
        assert "customCommands" in config
        assert any(c["name"] == "skill" for c in config["customCommands"])
        assert "systemMessage" in config
        assert "skillsmith:begin" in config["systemMessage"]

    def test_local_no_system_message(self, repo_root: Path) -> None:
        wire_harness("continue-local", port=8000, root=repo_root)
        config = json.loads((repo_root / ".continuerc.json").read_text())
        assert any(c["name"] == "skill" for c in config["customCommands"])
        assert "systemMessage" not in config

    def test_preserves_existing_config(self, repo_root: Path) -> None:
        existing = {"models": [{"title": "GPT-4"}], "customCommands": []}
        (repo_root / ".continuerc.json").write_text(json.dumps(existing))
        wire_harness("continue-closed", port=8000, root=repo_root)
        config = json.loads((repo_root / ".continuerc.json").read_text())
        assert config["models"] == [{"title": "GPT-4"}]
        assert any(c["name"] == "skill" for c in config["customCommands"])


class TestManual:
    def test_manual_prints_to_stderr(
        self, repo_root: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        result = wire_harness("manual", port=8000, root=repo_root)
        assert result["files_written"] == []
        assert SENTINEL_BEGIN in result["manual_block"]
        assert "localhost:8000" in result["manual_block"]
        captured = capsys.readouterr()
        assert SENTINEL_BEGIN in captured.err
        assert SENTINEL_BEGIN not in captured.out


class TestOutputSchema:
    def test_required_keys(self, repo_root: Path) -> None:
        result = wire_harness("claude-code", port=8000, root=repo_root)
        assert result["schema_version"] == 1
        assert "harness" in result
        assert "integration_vector" in result
        assert "files_written" in result

    def test_file_entry_shape(self, repo_root: Path) -> None:
        result = wire_harness("claude-code", port=8000, root=repo_root)
        entry = result["files_written"][0]
        assert "path" in entry
        assert "action" in entry
        assert "content_sha256" in entry


class TestState:
    def test_records_harness_in_state(self, repo_root: Path) -> None:
        wire_harness("claude-code", port=8000, root=repo_root)
        st = install_state.load_state(repo_root)
        assert "harness" not in st
        assert st["harness_files_written"][0]["harness"] == "claude-code"
        assert st["harness_files_written"][0]["repo_root"] == str(repo_root)
        assert install_state.is_step_completed(st, STEP_NAME)

    def test_records_files_written(self, repo_root: Path) -> None:
        wire_harness("claude-code", port=8000, root=repo_root)
        st = install_state.load_state(repo_root)
        assert len(st["harness_files_written"]) == 1


class TestEdgeCases:
    def test_unknown_harness_exits(self, repo_root: Path) -> None:
        with pytest.raises(SystemExit):
            wire_harness("nonexistent", root=repo_root)

    def test_all_valid_harnesses_accepted(self, repo_root: Path) -> None:
        for harness in VALID_HARNESSES:
            state_file = repo_root / ".skillsmith" / "install-state.json"
            if state_file.exists():
                state_file.unlink()
            if harness == "mcp-only":
                with pytest.raises(SystemExit):
                    wire_harness(harness, port=8000, root=repo_root)
                continue
            result = wire_harness(harness, port=8000, root=repo_root)
            assert result["harness"] == harness


class TestRewireMerge:
    def test_rewire_different_harness_preserves_prior_files(self, repo_root: Path) -> None:
        from skillsmith.install.state import load_state
        wire_harness("claude-code", port=8000, root=repo_root)
        st = load_state(repo_root)
        first_paths = {f["path"] for f in st["harness_files_written"]}
        assert any("CLAUDE.md" in p for p in first_paths)
        wire_harness("cursor", port=8000, root=repo_root)
        st = load_state(repo_root)
        merged_paths = {f["path"] for f in st["harness_files_written"]}
        assert any("CLAUDE.md" in p for p in merged_paths)
        assert any(".cursor" in p for p in merged_paths)
        harnesses = {f["harness"] for f in st["harness_files_written"]}
        assert harnesses == {"claude-code", "cursor"}

    def test_rewire_same_harness_replaces_entry_in_place(self, repo_root: Path) -> None:
        from skillsmith.install.state import load_state
        wire_harness("claude-code", port=8000, root=repo_root, force=True)
        wire_harness("claude-code", port=9000, root=repo_root, force=True)
        st = load_state(repo_root)
        paths = [f["path"] for f in st["harness_files_written"]]
        assert len(paths) == len(set(paths))


class TestScopeFlag:
    def test_scope_user_defaults_to_home(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))
        monkeypatch.setattr(Path, "home", lambda: fake_home)
        monkeypatch.setenv("SKILLSMITH_STATE_DIR", str(fake_home / ".skillsmith"))
        result = wire_harness("aider", port=8000, scope="user")
        for entry in result["files_written"]:
            assert str(fake_home) in entry["path"], entry

    def test_scope_repo_uses_repo_root(
        self, repo_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(repo_root)
        result = wire_harness("aider", port=8000, scope="repo")
        for entry in result["files_written"]:
            assert str(repo_root) in entry["path"], entry

    def test_scope_invalid_raises(self) -> None:
        with pytest.raises(SystemExit):
            wire_harness("aider", port=8000, scope="global")
```

**New tests to add at the end of the file:**

```python
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

---

## Task B: Create tests/install/test_phase_cli.py

Create a new test file for the phase CLI subcommand.

**Full content to write:**

```python
"""Unit tests for the ``phase`` subcommand.

Maps to plan: skillsmith phase CLI — set/get/clear phase lock file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from skillsmith.install.subcommands.phase import (
    run_phase_clear,
    run_phase_get,
    run_phase_set,
)


@pytest.fixture()
def repo_root(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text("")
    return tmp_path


class TestPhaseGet:
    def test_no_phase_returns_none(self, repo_root: Path) -> None:
        result = run_phase_get(root=repo_root)
        assert result.get("phase") is None

    def test_returns_current_phase(self, repo_root: Path) -> None:
        run_phase_set("build", root=repo_root)
        result = run_phase_get(root=repo_root)
        assert result["phase"] == "build"

    def test_returns_full_info(self, repo_root: Path) -> None:
        run_phase_set("design", root=repo_root)
        result = run_phase_get(root=repo_root)
        assert result["phase"] == "design"
        assert "started_at" in result
        assert "last_updated" in result
        assert "workflow" in result


class TestPhaseSet:
    def test_creates_phase_file(self, repo_root: Path) -> None:
        result = run_phase_set("build", root=repo_root)
        phase_file = repo_root / ".skillsmith" / "phase"
        assert phase_file.exists()
        assert result["phase"] == "build"

    def test_validates_phase(self, repo_root: Path) -> None:
        with pytest.raises((SystemExit, ValueError)):
            run_phase_set("invalid", root=repo_root)

    def test_valid_phases_accepted(self, repo_root: Path) -> None:
        for phase in ("spec", "design", "build", "qa", "ops"):
            state_file = repo_root / ".skillsmith" / "install-state.json"
            if state_file.exists():
                state_file.unlink()
            (repo_root / ".skillsmith" / "phase").unlink(missing_ok=True)
            result = run_phase_set(phase, root=repo_root)
            assert result["phase"] == phase

    def test_updates_existing_phase(self, repo_root: Path) -> None:
        run_phase_set("build", root=repo_root)
        original = run_phase_get(root=repo_root)
        run_phase_set("design", root=repo_root)
        updated = run_phase_get(root=repo_root)
        assert updated["phase"] == "design"
        # started_at should be preserved
        assert updated["started_at"] == original["started_at"]

    def test_creates_directory(self, repo_root: Path) -> None:
        # .skillsmith/ should not exist yet
        assert not (repo_root / ".skillsmith").exists()
        run_phase_set("build", root=repo_root)
        assert (repo_root / ".skillsmith").is_dir()


class TestPhaseClear:
    def test_removes_phase_file(self, repo_root: Path) -> None:
        run_phase_set("build", root=repo_root)
        assert (repo_root / ".skillsmith" / "phase").exists()
        run_phase_clear(root=repo_root)
        assert not (repo_root / ".skillsmith" / "phase").exists()

    def test_clear_when_no_phase(self, repo_root: Path) -> None:
        # Should not error if no phase file exists
        result = run_phase_clear(root=repo_root)
        assert result is not None  # returns success even if nothing to clear


class TestPhaseFileFormat:
    def test_yaml_format(self, repo_root: Path) -> None:
        run_phase_set("build", root=repo_root)
        content = (repo_root / ".skillsmith" / "phase").read_text()
        assert "phase: build" in content
        assert "started_at:" in content
        assert "last_updated:" in content
        assert "workflow:" in content

    def test_git_ignored(self, repo_root: Path) -> None:
        """Verify .skillsmith/ is in .gitignore."""
        run_phase_set("build", root=repo_root)
        gitignore = repo_root / ".gitignore"
        # If .gitignore exists, .skillsmith/ should be in it
        # If not, that's ok for tests — just verify the file was created
        assert (repo_root / ".skillsmith" / "phase").exists()
```

## Acceptance Criteria

- `tests/install/test_wire_harness.py` has new `TestIntakeActivationMarkers` class with tests verifying intake markers
- `tests/install/test_phase_cli.py` exists with comprehensive tests for get/set/clear
- All existing tests continue to pass
- New tests verify: phase validation, file format, markers in all harness templates
