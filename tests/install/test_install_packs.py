# pyright: reportPrivateUsage=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownMemberType=false
"""Unit tests for the ``install-packs`` subcommand.

Focus: the state-file handoff that prevents the setup wizard and
install-packs from prompting the user twice for the same pack selection.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from skillsmith.install import state as install_state
from skillsmith.install.subcommands.install_packs import (
    _clear_pending_pack_selection,
    _installed_pack_names,
    _load_pending_pack_selection,
    _select_packs,
)


@pytest.fixture()
def repo_root(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text("")
    return tmp_path


@pytest.fixture()
def available() -> dict[str, dict[str, object]]:
    """A small pack catalog: one always-on, two tier'd."""
    return {
        "core/foundation": {
            "name": "core/foundation",
            "tier": "foundation",
            "always_install": True,
            "skills": [{"skill_id": "s1"}],
        },
        "lang/python": {
            "name": "lang/python",
            "tier": "language",
            "skills": [{"skill_id": "s2"}, {"skill_id": "s3"}],
        },
        "tool/git": {
            "name": "tool/git",
            "tier": "tooling",
            "skills": [{"skill_id": "s4"}],
        },
    }


class TestPendingSelectionLoader:
    def test_load_returns_none_when_absent(self, repo_root: Path) -> None:
        # Fresh state file has the field defaulted to None.
        st = install_state.load_state(repo_root)
        install_state.save_state(st, repo_root)
        assert _load_pending_pack_selection() is None

    def test_load_returns_persisted_list(self, repo_root: Path) -> None:
        st = install_state.load_state(repo_root)
        install_state.set_pending_pack_selection(st, ["lang/python"])
        install_state.save_state(st, repo_root)
        assert _load_pending_pack_selection() == ["lang/python"]

    def test_load_returns_empty_list_when_explicit_no_extras(self, repo_root: Path) -> None:
        st = install_state.load_state(repo_root)
        install_state.set_pending_pack_selection(st, [])
        install_state.save_state(st, repo_root)
        # Empty list (explicit "no extras") must be distinguishable from None
        # so the priority check in _select_packs honors the user's intent.
        result = _load_pending_pack_selection()
        assert result == []
        assert result is not None


class TestClearPendingSelection:
    def test_clear_after_set(self, repo_root: Path) -> None:
        st = install_state.load_state(repo_root)
        install_state.set_pending_pack_selection(st, ["lang/python"])
        install_state.save_state(st, repo_root)
        _clear_pending_pack_selection()
        st2 = install_state.load_state(repo_root)
        assert install_state.get_pending_pack_selection(st2) is None

    def test_clear_when_nothing_set_is_noop(self, repo_root: Path) -> None:
        # Should not raise even if pending_pack_selection was never set.
        st = install_state.load_state(repo_root)
        install_state.save_state(st, repo_root)
        _clear_pending_pack_selection()  # no exception
        st2 = install_state.load_state(repo_root)
        assert install_state.get_pending_pack_selection(st2) is None


class TestSelectPacksPriority:
    """Priority: --packs flag > pending-state > TTY prompt > defaults."""

    def test_packs_flag_wins_over_pending_state(
        self, repo_root: Path, available: dict[str, dict[str, object]]
    ) -> None:
        # Even though state has a pending selection, the explicit CLI
        # flag must override it (matches the documented contract).
        st = install_state.load_state(repo_root)
        install_state.set_pending_pack_selection(st, ["lang/python"])
        install_state.save_state(st, repo_root)

        selected, _unknown, consumed = _select_packs(
            available, packs_flag="tool/git", interactive=False
        )
        assert "tool/git" in selected
        assert "lang/python" not in selected  # state was ignored
        assert consumed is False  # didn't consume the pending selection

    def test_pending_state_wins_over_interactive(
        self, repo_root: Path, available: dict[str, dict[str, object]]
    ) -> None:
        # When state has a pending selection AND no --packs flag, use the
        # state — do NOT show the interactive prompt.
        st = install_state.load_state(repo_root)
        install_state.set_pending_pack_selection(st, ["lang/python"])
        install_state.save_state(st, repo_root)

        # `interactive=True` would normally trigger the prompt; pending
        # state must short-circuit that path.
        selected, _unknown, consumed = _select_packs(available, packs_flag=None, interactive=True)
        assert "lang/python" in selected
        # Always-on packs are always merged in regardless of source.
        assert "core/foundation" in selected
        assert consumed is True

    def test_pending_empty_list_means_explicit_no_extras(
        self, repo_root: Path, available: dict[str, dict[str, object]]
    ) -> None:
        st = install_state.load_state(repo_root)
        install_state.set_pending_pack_selection(st, [])
        install_state.save_state(st, repo_root)

        selected, _unknown, consumed = _select_packs(available, packs_flag=None, interactive=True)
        # Only the always-on pack — the user said "no extras".
        assert selected == ["core/foundation"]
        assert consumed is True

    def test_no_flag_no_pending_no_tty_returns_always_on_only(
        self, repo_root: Path, available: dict[str, dict[str, object]]
    ) -> None:
        # Non-TTY path with nothing in state: just always-on packs.
        selected, _unknown, consumed = _select_packs(available, packs_flag=None, interactive=False)
        assert selected == ["core/foundation"]
        assert consumed is False

    def test_pending_with_unknown_pack_reports_unknown(
        self, repo_root: Path, available: dict[str, dict[str, object]]
    ) -> None:
        # If the pending list references a pack that no longer exists
        # (e.g., it was removed between setup and ingest), the unknown
        # is reported but the rest still installs.
        st = install_state.load_state(repo_root)
        install_state.set_pending_pack_selection(st, ["lang/python", "gone/missing"])
        install_state.save_state(st, repo_root)
        selected, unknown, consumed = _select_packs(available, packs_flag=None, interactive=False)
        assert "lang/python" in selected
        assert "gone/missing" in unknown
        assert consumed is True


class TestInstalledPackAnnotation:
    """``_installed_pack_names`` powers the [installed] marker in the prompt."""

    def test_returns_empty_when_state_fresh(self, repo_root: Path) -> None:
        assert _installed_pack_names() == set()

    def test_returns_recorded_packs(self, repo_root: Path) -> None:
        st = install_state.load_state(repo_root)
        st["installed_packs"] = ["lang/python", "tool/git"]
        install_state.save_state(st, repo_root)
        assert _installed_pack_names() == {"lang/python", "tool/git"}

    def test_ignores_non_string_entries(self, repo_root: Path) -> None:
        # Defensive against tampered/corrupt state.
        st = install_state.load_state(repo_root)
        st["installed_packs"] = ["lang/python", 42, None, "tool/git"]
        install_state.save_state(st, repo_root)
        assert _installed_pack_names() == {"lang/python", "tool/git"}
