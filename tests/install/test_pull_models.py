# pyright: reportPrivateUsage=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownMemberType=false, reportUnknownLambdaType=false
"""Unit tests for the ``pull-models`` subcommand.

Maps to test-plan.md § Model pulling.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from skillsmith.install.subcommands.pull_models import (
    _PRESENCE_CHECKS,  # pyright: ignore[reportPrivateUsage]
    STEP_NAME,
    _auto_pull,  # pyright: ignore[reportPrivateUsage]
    _collect_model_runner_pairs,  # pyright: ignore[reportPrivateUsage]
    _is_model_present_ollama,  # pyright: ignore[reportPrivateUsage]
    pull_models,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def repo_root(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text("")
    return tmp_path


def _recommend_output(
    *,
    embed_model: str = "qwen3-embedding:0.6b",
    embed_runner: str = "ollama",
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "host_target": "CPU+RAM",
        "preset": "cpu",
        "options": [
            {
                "default": True,
                "embed_model": embed_model,
                "embed_runner": embed_runner,
            },
        ],
    }


# ---------------------------------------------------------------------------
# Pair extraction
# ---------------------------------------------------------------------------


class TestCollectPairs:
    def test_single_embed_pair(self) -> None:
        option = {
            "embed_model": "qwen3-embedding:0.6b",
            "embed_runner": "ollama",
        }
        pairs = _collect_model_runner_pairs(option)
        assert len(pairs) == 1
        assert ("qwen3-embedding:0.6b", "ollama") in pairs

    def test_ignores_ingest_fields_if_present(self) -> None:
        option = {
            "embed_model": "qwen3-embedding:0.6b",
            "embed_runner": "ollama",
            "ingest_model": "qwen3.5:0.8b",
            "ingest_runner": "ollama",
        }
        pairs = _collect_model_runner_pairs(option)
        assert len(pairs) == 1
        assert ("qwen3-embedding:0.6b", "ollama") in pairs

    def test_deduplicates_same_model_runner(self) -> None:
        option = {
            "embed_model": "qwen3-embedding:0.6b",
            "embed_runner": "ollama",
        }
        pairs = _collect_model_runner_pairs(option)
        assert len(pairs) == 1


# ---------------------------------------------------------------------------
# Ollama presence check
# ---------------------------------------------------------------------------


class TestOllamaPresence:
    def test_model_present(self) -> None:
        output = "NAME           ID          SIZE    MODIFIED\nembeddinggemma:latest   abc123   622 MB  2 days ago\n"
        with (
            patch("shutil.which", return_value="/usr/bin/ollama"),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout=output)
            assert _is_model_present_ollama("embeddinggemma") is True

    def test_model_absent(self) -> None:
        output = "NAME           ID          SIZE    MODIFIED\nother:latest   abc123   100 MB  1 day ago\n"
        with (
            patch("shutil.which", return_value="/usr/bin/ollama"),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout=output)
            assert _is_model_present_ollama("embeddinggemma") is False

    def test_ollama_not_installed(self) -> None:
        with patch("shutil.which", return_value=None):
            assert _is_model_present_ollama("embeddinggemma") is False

    def test_tagged_model_match(self) -> None:
        output = "NAME              ID       SIZE    MODIFIED\nqwen3.5:0.8b      xyz789   1.0 GB  1 day ago\n"
        with (
            patch("shutil.which", return_value="/usr/bin/ollama"),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout=output)
            assert _is_model_present_ollama("qwen3.5:0.8b") is True


# ---------------------------------------------------------------------------
# Auto-pull
# ---------------------------------------------------------------------------


class TestAutoPull:
    def test_successful_pull(self) -> None:
        # Daemon-running probe must return True so _auto_pull skips
        # the spawn path and goes straight to the pull subprocess.
        with (
            patch(
                "skillsmith.install.subcommands.pull_models._ollama_daemon_running",
                return_value=True,
            ),
            patch("shutil.which", return_value="/usr/bin/ollama"),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0, stderr="")
            result = _auto_pull("ollama", "embeddinggemma")
            assert result["success"] is True
            assert "duration_ms" in result
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert args == ["/usr/bin/ollama", "pull", "--", "embeddinggemma"]

    def test_pull_failure(self) -> None:
        with (
            patch(
                "skillsmith.install.subcommands.pull_models._ollama_daemon_running",
                return_value=True,
            ),
            patch("shutil.which", return_value="/usr/bin/ollama"),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=1, stderr="connection refused")
            result = _auto_pull("ollama", "embeddinggemma")
            assert result["success"] is False
            assert "connection refused" in result["error"]

    def test_binary_not_found(self) -> None:
        with patch("shutil.which", return_value=None):
            result = _auto_pull("ollama", "embeddinggemma")
            assert result["success"] is False
            assert "not found" in result["error"]

    def test_fastflowlm_pull(self) -> None:
        with (
            patch("shutil.which", return_value="/usr/bin/flm"),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0, stderr="")
            result = _auto_pull("fastflowlm", "embed-gemma:300m")
            assert result["success"] is True
            args = mock_run.call_args[0][0]
            assert args == ["/usr/bin/flm", "pull", "--", "embed-gemma:300m"]


# ---------------------------------------------------------------------------
# Full pull_models
# ---------------------------------------------------------------------------


class TestPullModels:
    def test_auto_pull_embed_model(self, repo_root: Path) -> None:
        models = _recommend_output()

        def always_false(m: str) -> bool:
            return False

        with (
            patch.dict(_PRESENCE_CHECKS, {"ollama": always_false}),
            patch("skillsmith.install.subcommands.pull_models._auto_pull") as mock_pull,
        ):
            mock_pull.return_value = {"success": True, "duration_ms": 100}
            result = pull_models(models, root=repo_root)
        assert result["schema_version"] == 1
        assert len(result["auto_pulled"]) == 1
        assert result["auto_pulled"][0]["model"] == "qwen3-embedding:0.6b"
        assert result["manual_steps_required"] == []
        assert result["skipped_already_present"] == []

    def test_skips_already_present(self, repo_root: Path) -> None:
        models = _recommend_output()

        def always_true(m: str) -> bool:
            return True

        with patch.dict(_PRESENCE_CHECKS, {"ollama": always_true}):
            result = pull_models(models, root=repo_root)
        assert len(result["skipped_already_present"]) == 1
        assert result["auto_pulled"] == []

    def test_manual_steps_for_fastflowlm(self, repo_root: Path) -> None:
        models = _recommend_output(
            embed_model="qwen3-embedding:0.6b",
            embed_runner="fastflowlm",
        )

        def always_false(m: str) -> bool:
            return False

        with (
            patch.dict(_PRESENCE_CHECKS, {"fastflowlm": always_false}),
            patch("skillsmith.install.subcommands.pull_models._auto_pull") as mock_pull,
        ):
            mock_pull.return_value = {"success": True, "duration_ms": 50}
            result = pull_models(models, root=repo_root)
        assert len(result["auto_pulled"]) == 1
        assert result["auto_pulled"][0]["model"] == "qwen3-embedding:0.6b"

    def test_idempotent_skip(self, repo_root: Path) -> None:
        """Second run exits 4 (noop) when step already completed."""
        models = _recommend_output()

        def always_true(m: str) -> bool:
            return True

        with patch.dict(_PRESENCE_CHECKS, {"ollama": always_true}):
            pull_models(models, root=repo_root)
        # Second call should raise SystemExit(4)
        with pytest.raises(SystemExit, match="4"):
            pull_models(models, root=repo_root)

    def test_records_state(self, repo_root: Path) -> None:
        models = _recommend_output()

        def always_true(m: str) -> bool:
            return True

        with patch.dict(_PRESENCE_CHECKS, {"ollama": always_true}):
            pull_models(models, root=repo_root)
        from skillsmith.install.state import is_step_completed, load_state

        st = load_state(repo_root)
        assert is_step_completed(st, STEP_NAME)

    def test_no_options_exits(self, repo_root: Path) -> None:
        with pytest.raises(SystemExit):
            pull_models({"options": []}, root=repo_root)

    def test_pull_error_recorded(self, repo_root: Path) -> None:
        models = _recommend_output()

        def always_false(m: str) -> bool:
            return False

        with (
            patch.dict(_PRESENCE_CHECKS, {"ollama": always_false}),
            patch("skillsmith.install.subcommands.pull_models._auto_pull") as mock_pull,
        ):
            mock_pull.return_value = {
                "success": False,
                "error": "connection refused",
                "duration_ms": 10,
            }
            result = pull_models(models, root=repo_root)
        assert "errors" in result
        assert len(result["errors"]) == 1

    def test_partial_failure_does_not_record_completion(self, repo_root: Path) -> None:
        """If any pull fails, pull-models must NOT mark itself completed —
        otherwise idempotency permanently skips it on rerun."""
        from skillsmith.install.state import is_step_completed, load_state

        models = _recommend_output()

        def always_false(m: str) -> bool:
            return False

        with (
            patch.dict(_PRESENCE_CHECKS, {"ollama": always_false}),
            patch("skillsmith.install.subcommands.pull_models._auto_pull") as mock_pull,
        ):
            mock_pull.return_value = {
                "success": False,
                "error": "connection refused",
                "duration_ms": 10,
            }
            pull_models(models, root=repo_root)
        st = load_state(repo_root)
        assert not is_step_completed(st, "pull-models")
        # And no models_pulled tracking either, since nothing succeeded.
        assert not st.get("models_pulled")

    def test_models_pulled_in_state(self, repo_root: Path) -> None:
        models = _recommend_output()

        def always_false(m: str) -> bool:
            return False

        with (
            patch.dict(_PRESENCE_CHECKS, {"ollama": always_false}),
            patch("skillsmith.install.subcommands.pull_models._auto_pull") as mock_pull,
        ):
            mock_pull.return_value = {"success": True, "duration_ms": 100}
            pull_models(models, root=repo_root)
        from skillsmith.install.state import load_state

        st = load_state(repo_root)
        assert "ollama:qwen3-embedding:0.6b" in st["models_pulled"]


class TestOllamaDaemonAutoStart:
    """``_auto_pull`` must start the ollama daemon if it's down before pulling."""

    def test_no_binary_surfaces_clear_error(self, repo_root: Path) -> None:
        """When the ``ollama`` binary isn't on PATH, _auto_pull short-circuits
        with an actionable error — no daemon-start is attempted."""
        with patch(
            "skillsmith.install.subcommands.pull_models.shutil.which",
            return_value=None,
        ):
            result = _auto_pull("ollama", "qwen3-embedding:0.6b")
        assert result["success"] is False
        assert "not found" in (result["error"] or "").lower()

    def test_daemon_already_up_no_spawn(self, repo_root: Path) -> None:
        from skillsmith.install.subcommands import pull_models as pm

        with (
            patch.object(pm, "_ollama_daemon_running", return_value=True),
            patch(
                "skillsmith.install.subcommands.pull_models.shutil.which",
                return_value="/usr/bin/ollama",
            ),
            patch("skillsmith.install.subcommands.pull_models.subprocess.Popen") as mock_popen,
            patch("skillsmith.install.subcommands.pull_models.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0, stderr="")
            result = _auto_pull("ollama", "qwen3-embedding:0.6b")
        assert result["success"] is True
        mock_popen.assert_not_called()

    def test_daemon_down_triggers_spawn(self, repo_root: Path) -> None:
        from skillsmith.install.subcommands import pull_models as pm

        # First probe → False (down). After spawn, probes during the wait
        # loop return True (came up).
        check_results = iter([False, True])

        with (
            patch.object(
                pm,
                "_ollama_daemon_running",
                side_effect=lambda *_a, **_k: next(check_results),
            ),
            patch(
                "skillsmith.install.subcommands.pull_models.shutil.which",
                return_value="/usr/bin/ollama",
            ),
            patch("skillsmith.install.subcommands.pull_models.subprocess.Popen") as mock_popen,
            patch("skillsmith.install.subcommands.pull_models.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0, stderr="")
            result = _auto_pull("ollama", "qwen3-embedding:0.6b")
        mock_popen.assert_called_once()
        cmd = mock_popen.call_args[0][0]
        assert cmd[0] == "/usr/bin/ollama"
        assert cmd[1] == "serve"
        assert result["success"] is True

    def test_daemon_never_comes_up_fails_loudly(self, repo_root: Path) -> None:
        """Spawn succeeded but daemon never bound the port → clear error."""
        from skillsmith.install.subcommands import pull_models as pm

        # All probes return False. The deadline loop bails after the
        # time.monotonic() sequence indicates timeout.
        with (
            patch.object(pm, "_ollama_daemon_running", return_value=False),
            patch(
                "skillsmith.install.subcommands.pull_models.shutil.which",
                return_value="/usr/bin/ollama",
            ),
            patch("skillsmith.install.subcommands.pull_models.subprocess.Popen"),
            # Sequence: initial t0, then time.monotonic() > deadline on first
            # check inside the while loop.
            patch(
                "skillsmith.install.subcommands.pull_models.time.monotonic",
                side_effect=[0.0, 100.0, 100.0, 100.0],
            ),
            patch("skillsmith.install.subcommands.pull_models.time.sleep"),
        ):
            result = _auto_pull("ollama", "qwen3-embedding:0.6b")
        assert result["success"] is False
        assert "ollama" in (result["error"] or "").lower()


class TestRunExitCodes:
    """``_run`` exit codes: 0 = work done, 4 = no-op, 1 = error."""

    def _models_file(self, repo_root: Path, runner: str = "ollama") -> Path:
        import json as _json

        p = repo_root / "models.json"
        p.write_text(_json.dumps(_recommend_output(embed_runner=runner)))
        return p

    def test_exit_4_when_all_models_already_present(self, repo_root: Path) -> None:
        """Re-running pull-models after install: every model is present.
        No pulls happen, no manual steps required → EXIT_NOOP (4)."""
        from argparse import Namespace

        from skillsmith.install.subcommands.pull_models import _run

        models_path = self._models_file(repo_root)

        def always_present(m: str) -> bool:
            return True

        with patch.dict(_PRESENCE_CHECKS, {"ollama": always_present}):
            rc = _run(Namespace(models=str(models_path), runner=None, quiet=True))
        assert rc == 4

    def test_exit_0_when_models_pulled(self, repo_root: Path) -> None:
        from argparse import Namespace

        from skillsmith.install.subcommands.pull_models import _run

        models_path = self._models_file(repo_root)

        def always_absent(m: str) -> bool:
            return False

        with (
            patch.dict(_PRESENCE_CHECKS, {"ollama": always_absent}),
            patch("skillsmith.install.subcommands.pull_models._auto_pull") as mock_pull,
        ):
            mock_pull.return_value = {"success": True, "duration_ms": 50}
            rc = _run(Namespace(models=str(models_path), runner=None, quiet=True))
        assert rc == 0

    def test_exit_1_when_pull_fails(self, repo_root: Path) -> None:
        from argparse import Namespace

        from skillsmith.install.subcommands.pull_models import _run

        models_path = self._models_file(repo_root)

        def always_absent(m: str) -> bool:
            return False

        with (
            patch.dict(_PRESENCE_CHECKS, {"ollama": always_absent}),
            patch("skillsmith.install.subcommands.pull_models._auto_pull") as mock_pull,
        ):
            mock_pull.return_value = {
                "runner": "ollama",
                "model": "qwen3-embedding:0.6b",
                "success": False,
                "error": "ollama daemon unavailable",
            }
            rc = _run(Namespace(models=str(models_path), runner=None, quiet=True))
        assert rc == 1
