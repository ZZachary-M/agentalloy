# pyright: reportPrivateUsage=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownMemberType=false
"""Unit tests for the user-facing CLI verbs (setup / wire / unwire / serve / status).

These compose the existing 13-step subcommand surface — tests here
verify the composition behavior, not each underlying step (those have
their own test files).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from skillsmith.install import state as install_state


@pytest.fixture()
def repo_root(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text("")
    return tmp_path


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


class TestStatus:
    def test_empty_install_returns_safe_snapshot(
        self, repo_root: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from skillsmith.install.subcommands import status

        args = argparse.Namespace()
        rc = status._run(args)
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["schema_version"] == 1
        assert out["completed_steps"] == []
        assert out["wired_repos"] == []
        assert out["corpus"]["present"] is False  # bundled corpus blocked by conftest
        assert out["service"]["port"] == 47950

    def test_groups_entries_by_repo_root(
        self, repo_root: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from skillsmith.install.subcommands import status

        st = install_state.load_state(repo_root)
        st["harness_files_written"] = [
            {
                "path": "/repo-a/CLAUDE.md",
                "repo_root": "/repo-a",
                "harness": "claude-code",
                "action": "injected_block",
            },
            {
                "path": "/repo-a/.cursor/rules/skillsmith.mdc",
                "repo_root": "/repo-a",
                "harness": "cursor",
                "action": "wrote_new_file",
            },
            {
                "path": "/repo-b/GEMINI.md",
                "repo_root": "/repo-b",
                "harness": "gemini-cli",
                "action": "injected_block",
            },
        ]
        install_state.save_state(st, repo_root)
        rc = status._run(argparse.Namespace())
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        repos = {r["repo_root"]: r["entries"] for r in out["wired_repos"]}
        assert set(repos.keys()) == {"/repo-a", "/repo-b"}
        assert len(repos["/repo-a"]) == 2
        assert len(repos["/repo-b"]) == 1

    def test_invalid_port_handled_gracefully(
        self, repo_root: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A tampered port shouldn't crash status; surface it as null + unreachable."""
        from skillsmith.install.subcommands import status

        st = install_state.load_state(repo_root)
        st["port"] = "1@evil.com:80"  # type: ignore[assignment]
        install_state.save_state(st, repo_root)
        rc = status._run(argparse.Namespace())
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["service"]["port"] is None
        assert out["service"]["reachable_on_loopback"] is False


# ---------------------------------------------------------------------------
# wire
# ---------------------------------------------------------------------------


class TestWire:
    def test_auto_detects_claude_code(
        self, repo_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from skillsmith.install.subcommands import wire

        (repo_root / "CLAUDE.md").write_text("# Project\n")
        monkeypatch.chdir(repo_root)
        args = argparse.Namespace(harness=None, port=None, force=False)
        rc = wire._run(args)
        assert rc == 0
        # Sentinels written to CLAUDE.md
        content = (repo_root / "CLAUDE.md").read_text()
        assert "skillsmith" in content.lower()

    def test_auto_detects_cursor_when_dir_present(
        self, repo_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from skillsmith.install.subcommands import wire

        (repo_root / ".cursor").mkdir()
        monkeypatch.chdir(repo_root)
        args = argparse.Namespace(harness=None, port=None, force=False)
        rc = wire._run(args)
        assert rc == 0
        assert (repo_root / ".cursor" / "rules" / "skillsmith.mdc").exists()

    def test_no_marker_requires_explicit_harness(
        self, repo_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from skillsmith.install.subcommands import wire

        monkeypatch.chdir(repo_root)
        args = argparse.Namespace(harness=None, port=None, force=False)
        rc = wire._run(args)
        assert rc == 1

    def test_explicit_harness_wins_over_detection(
        self, repo_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from skillsmith.install.subcommands import wire

        # CLAUDE.md present (would auto-detect claude-code) but caller
        # forces gemini-cli — a separate file should be created.
        (repo_root / "CLAUDE.md").write_text("# Project\n")
        monkeypatch.chdir(repo_root)
        args = argparse.Namespace(harness="gemini-cli", port=None, force=False)
        rc = wire._run(args)
        assert rc == 0
        assert (repo_root / "GEMINI.md").exists()


# ---------------------------------------------------------------------------
# unwire
# ---------------------------------------------------------------------------


class TestUnwire:
    def test_removes_only_cwd_repo_entries(
        self, repo_root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from skillsmith.install.subcommands import unwire, wire

        # Wire the cwd-derived repo
        monkeypatch.chdir(repo_root)
        wire._run(argparse.Namespace(harness="claude-code", port=None, force=False))
        # Inject an entry from another repo into state — unwire must NOT touch it.
        st = install_state.load_state(repo_root)
        other_path = "/some/other-repo/CLAUDE.md"
        st["harness_files_written"].append(
            {
                "path": other_path,
                "repo_root": "/some/other-repo",
                "harness": "claude-code",
                "action": "injected_block",
            }
        )
        install_state.save_state(st, repo_root)
        capsys.readouterr()  # flush wire output
        rc = unwire._run(argparse.Namespace(force=False))
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        # cwd CLAUDE.md was either modified or removed
        cwd_touched = any(
            "CLAUDE.md" in f.get("path", "") for f in out["files_modified"] + out["files_removed"]
        )
        assert cwd_touched
        # The other-repo entry should have produced a "different repo" warning, not deletion
        assert any("different repo" in w.lower() for w in out["warnings"])

    def test_preserves_user_state_and_env(
        self, repo_root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """unwire must NOT delete the user-scope state directory or .env.
        Earlier behavior accidentally invoked uninstall's full teardown."""
        from skillsmith.install.subcommands import unwire, wire

        # Set up a wired repo + user-scope artifacts
        monkeypatch.chdir(repo_root)
        wire._run(argparse.Namespace(harness="claude-code", port=None, force=False))
        env_path = install_state.env_path()
        env_path.parent.mkdir(parents=True, exist_ok=True)
        env_path.write_text("# Generated by skillsmith install write-env\nKEY=val\n")
        state_file = install_state.state_path()
        assert state_file.exists()  # wire wrote to it

        capsys.readouterr()
        unwire._run(argparse.Namespace(force=False))

        # User-scope artifacts must survive unwire
        assert state_file.exists(), "unwire must NOT delete the user state file"
        assert env_path.exists(), "unwire must NOT delete the user .env"
        assert install_state.state_dir().exists(), "unwire must NOT remove the user-scope state dir"


# ---------------------------------------------------------------------------
# serve
# ---------------------------------------------------------------------------


class TestServe:
    def test_export_prefix_stripped(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """`.env` written shell-style with `export KEY=val` is common; the
        parser must strip the prefix or the actual key never gets set."""

        env_path = install_state.env_path()
        env_path.parent.mkdir(parents=True, exist_ok=True)
        env_path.write_text("export PORT=9999\nexport NAME=skillsmith\n")
        monkeypatch.delenv("PORT", raising=False)
        monkeypatch.delenv("NAME", raising=False)
        loaded = install_state.load_env_into_environ(env_path)
        assert "PORT" in loaded
        assert "NAME" in loaded
        import os

        assert os.environ["PORT"] == "9999"
        assert os.environ["NAME"] == "skillsmith"
        assert "export PORT" not in os.environ

    def test_loads_env_into_environ(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:

        env_path = install_state.env_path()
        env_path.parent.mkdir(parents=True, exist_ok=True)
        env_path.write_text("# header\nFOO=bar\nBAZ='quoted value'\nEMPTY=\nNO_EQUALS_LINE\n")
        # FOO must not be already set in environ for our load to take effect.
        monkeypatch.delenv("FOO", raising=False)
        monkeypatch.delenv("BAZ", raising=False)
        loaded = install_state.load_env_into_environ(env_path)
        assert "FOO" in loaded
        assert "BAZ" in loaded
        assert "EMPTY" in loaded
        import os

        assert os.environ["FOO"] == "bar"
        assert os.environ["BAZ"] == "quoted value"

    def test_existing_env_var_takes_precedence(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A key already in the process env must NOT be overridden by .env —
        process env is the higher-priority source."""

        env_path = install_state.env_path()
        env_path.parent.mkdir(parents=True, exist_ok=True)
        env_path.write_text("FOO=from_env_file\n")
        monkeypatch.setenv("FOO", "from_process")
        loaded = install_state.load_env_into_environ(env_path)
        import os

        assert os.environ["FOO"] == "from_process"
        assert "FOO" not in loaded


# ---------------------------------------------------------------------------
# setup
# ---------------------------------------------------------------------------


class TestSetup:
    def test_stops_at_first_failed_step_by_default(
        self, repo_root: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from skillsmith.install.subcommands import setup

        # Patch _invoke_step so the first step fails — composer must stop.
        calls: list[str] = []

        def fake_invoke(step: str, _module: str, _args: object) -> int:
            calls.append(step)
            return 1 if step == "detect" else 0

        with patch.object(setup, "_invoke_step", side_effect=fake_invoke):
            rc = setup._run(argparse.Namespace(continue_on_error=False))
        assert rc == 1
        # Only the first step ran; later steps never invoked.
        assert calls == ["detect"]
        out_lines = capsys.readouterr().out.strip().splitlines()
        # JSON output always emitted, even on early-stop
        result = json.loads("\n".join(out_lines))
        assert result["action"] == "setup_failed"
        assert "detect" in result["failed_steps"]

    def test_continue_on_error_keeps_running(self, repo_root: Path) -> None:
        """With --continue-on-error, every step is at least *attempted*. Since
        the underlying steps don't actually run (we patch _invoke_step), the
        prereq-skip path will short-circuit downstream steps that need
        upstream output files. The composer's behavior is: keep going past
        the failure, attempting whatever still has its prereqs satisfied."""
        from skillsmith.install.subcommands import setup

        calls: list[str] = []

        def fake_invoke(step: str, _module: str, _args: object) -> int:
            calls.append(step)
            return 1  # every step fails

        with patch.object(setup, "_invoke_step", side_effect=fake_invoke):
            rc = setup._run(argparse.Namespace(continue_on_error=True))
        assert rc == 1
        # detect was at least attempted; downstream steps either ran or
        # were skipped via the prereq check — both count as making progress.
        assert "detect" in calls

    def test_noop_exit_code_does_not_count_as_failure(self, repo_root: Path) -> None:
        from skillsmith.install.subcommands import setup

        # All steps return 4 (EXIT_NOOP) — composer must treat that as
        # success. The prereq check fires before _invoke_step, so we also
        # need to seed the upstream output files for downstream steps to
        # be reachable.
        outputs = install_state.outputs_dir()
        outputs.mkdir(parents=True, exist_ok=True)
        for fname in (
            "detect.json",
            "recommend-host-targets.json",
            "recommend-models.json",
        ):
            (outputs / fname).write_text("{}")
        with patch.object(setup, "_invoke_step", return_value=4):
            rc = setup._run(argparse.Namespace(continue_on_error=False))
        assert rc == 0

    def test_invoke_step_wraps_non_systemexit(self, repo_root: Path) -> None:
        """The real _invoke_step must convert non-SystemExit exceptions to
        exit code 2 so --continue-on-error keeps the loop alive."""
        from skillsmith.install.subcommands import setup

        def boom(_args: argparse.Namespace) -> int:
            raise RuntimeError("upstream failure")

        # Build a synthetic step module shape that _invoke_step can
        # parse-and-dispatch. We patch importlib.import_module to return
        # a stub module exposing the same `add_parser(subparsers)`
        # contract real subcommand modules expose.
        import types

        stub = types.ModuleType("stub")

        def add_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:  # noqa: ARG001
            sp = subparsers.add_parser("detect")
            sp.set_defaults(func=boom)

        stub.add_parser = add_parser  # type: ignore[attr-defined]
        with patch("importlib.import_module", return_value=stub):
            rc = setup._invoke_step("detect", "stub", argparse.Namespace())
        assert rc == 2

    def test_missing_prereq_skips_with_clear_error(self, repo_root: Path) -> None:
        """A step whose upstream output JSON is missing must be skipped
        with a clear stderr message, not an opaque argparse error."""
        from skillsmith.install.subcommands import setup

        # Patch out the actual step invocation and simulate detect succeeding
        # but writing no output — recommend-host-targets should skip.
        invoked: list[str] = []

        def fake_invoke(step: str, _module: str, _args: object) -> int:
            invoked.append(step)
            return 0  # claim success but write no output file

        with patch.object(setup, "_invoke_step", side_effect=fake_invoke):
            rc = setup._run(argparse.Namespace(continue_on_error=True))
        # detect was attempted; downstream steps recognized the missing
        # prereq and skipped without invoking the underlying command.
        assert "detect" in invoked
        assert "recommend-host-targets" not in invoked
        assert rc == 1


# ---------------------------------------------------------------------------
# Dispatcher integration
# ---------------------------------------------------------------------------


class TestDispatcherRegistration:
    def test_all_verbs_registered(self) -> None:
        """The new verbs must be dispatched by the top-level CLI parser."""
        from skillsmith.install.__main__ import build_parser

        parser = build_parser()
        # argparse stores subparser names in the choices of the
        # subparsers action — find it.
        sp_action = None
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                sp_action = action
                break
        assert sp_action is not None
        registered = set(sp_action.choices.keys())  # pyright: ignore[reportAttributeAccessIssue]
        for verb in ("setup", "wire", "unwire", "serve", "status"):
            assert verb in registered, f"{verb} not registered in dispatcher"
