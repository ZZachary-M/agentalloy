"""Tests for contract-driven domain retrieval (Phase 2)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_contract(path: Path, phase: str = "build", domain_tags: list[str] | None = None) -> Path:
    fm: dict[str, Any] = {
        "phase": phase,
        "task_slug": "test-task",
        "domain_tags": domain_tags or ["NestJS", "JWT"],
        "scope": {"touches": [], "avoids": []},
        "success_criteria": [],
        "related_contracts": [],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{yaml.dump(fm)}---\n\nTest task.\n")
    return path


# ---------------------------------------------------------------------------
# ComposeRequest.resolved_contract_tags
# ---------------------------------------------------------------------------


def test_resolved_contract_tags_from_explicit(tmp_path: Path):
    from skillsmith.api.compose_models import ComposeRequest

    req = ComposeRequest(task="do thing", phase="build", contract_tags=["A", "B"])
    assert req.resolved_contract_tags == ["A", "B"]


def test_resolved_contract_tags_from_path(tmp_path: Path):
    from skillsmith.api.compose_models import ComposeRequest

    # Must live under a project's .skillsmith/contracts/<phase>/ directory
    # to pass the path-containment guard.
    contract_dir = tmp_path / ".skillsmith" / "contracts" / "build"
    f = _write_contract(contract_dir / "c.md", domain_tags=["NestJS", "JWT"])
    req = ComposeRequest(task="do thing", phase="build", contract_path=str(f))
    assert req.resolved_contract_tags == ["NestJS", "JWT"]


def test_resolved_contract_tags_rejects_unsafe_path(tmp_path: Path):
    """Paths outside any .skillsmith/contracts/ tree are silently rejected (returns None)."""
    from skillsmith.api.compose_models import ComposeRequest

    f = _write_contract(tmp_path / "loose-contract.md", domain_tags=["X"])
    req = ComposeRequest(task="do thing", phase="build", contract_path=str(f))
    assert req.resolved_contract_tags is None


def test_resolved_contract_tags_none_when_not_set():
    from skillsmith.api.compose_models import ComposeRequest

    req = ComposeRequest(task="do thing", phase="build")
    assert req.resolved_contract_tags is None


# ---------------------------------------------------------------------------
# retrieve_domain_candidates: BM25 source selection
# ---------------------------------------------------------------------------


def _make_mock_retrieval_env():
    """Return minimal mocks for retrieve_domain_candidates."""
    source = MagicMock()
    source.get_active_fragments.return_value = []
    lm = MagicMock()
    lm.embed.return_value = [[0.1] * 512]
    vector_store = MagicMock()
    vector_store.search_similar.return_value = []
    vector_store.search_bm25.return_value = []
    return source, lm, vector_store


def test_retrieval_uses_contract_tags_as_bm25(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from skillsmith.retrieval.domain import retrieve_domain_candidates

    source, lm, vector_store = _make_mock_retrieval_env()
    bm25_calls: list[str] = []

    def capture_bm25(query: str, **kwargs: Any) -> list[Any]:
        bm25_calls.append(query)
        return []

    vector_store.search_bm25.side_effect = capture_bm25

    result = retrieve_domain_candidates(
        source,
        lm,
        vector_store,
        task="add auth middleware",
        phase="build",
        domain_tags=None,
        k=4,
        embedding_model="test-model",
        contract_tags=["NestJS", "JWT validation"],
    )

    assert result.bm25_source == "contract"
    assert len(bm25_calls) == 1
    assert "NestJS" in bm25_calls[0]
    assert "JWT validation" in bm25_calls[0]


def test_retrieval_falls_back_to_rules_when_no_contract():
    from skillsmith.retrieval.domain import retrieve_domain_candidates

    source, lm, vector_store = _make_mock_retrieval_env()
    bm25_calls: list[str] = []

    def capture_bm25(query: str, **kwargs: Any) -> list[Any]:
        bm25_calls.append(query)
        return []

    vector_store.search_bm25.side_effect = capture_bm25

    result = retrieve_domain_candidates(
        source,
        lm,
        vector_store,
        task="add auth middleware to NestJS",
        phase="build",
        domain_tags=None,
        k=4,
        embedding_model="test-model",
    )

    assert result.bm25_source == "rule-extracted"
    assert len(bm25_calls) == 1


def test_retrieval_union_when_env_var_set(monkeypatch: pytest.MonkeyPatch):
    from skillsmith.retrieval.domain import retrieve_domain_candidates

    monkeypatch.setenv("SKILLSMITH_UNION_KEYWORDS", "1")
    source, lm, vector_store = _make_mock_retrieval_env()
    bm25_calls: list[str] = []

    def capture_bm25(query: str, **kwargs: Any) -> list[Any]:
        bm25_calls.append(query)
        return []

    vector_store.search_bm25.side_effect = capture_bm25

    result = retrieve_domain_candidates(
        source,
        lm,
        vector_store,
        task="add auth middleware",
        phase="build",
        domain_tags=None,
        k=4,
        embedding_model="test-model",
        contract_tags=["NestJS"],
    )

    assert result.bm25_source == "union"
    assert len(bm25_calls) == 1
    # Union: should contain both the contract tag and something rule-extracted
    assert "NestJS" in bm25_calls[0]


# ---------------------------------------------------------------------------
# Workflow skill schema (Phase 2 additions to customize validator)
# ---------------------------------------------------------------------------


def test_validate_workflow_requires_contract_template():
    from skillsmith.install.subcommands.customize import (
        _validate_skill_data,  # pyright: ignore[reportPrivateUsage]
    )

    data: dict[str, Any] = {
        "skill_id": "wf",
        "skill_class": "workflow",
        "raw_prose": "A" * 120,
        "applies_to_phases": ["build"],
        "exit_gates": {"all_of": []},
        # missing contract_template
    }
    errors = _validate_skill_data(data, "wf")
    assert any("contract_template" in e for e in errors)


def test_workflow_schema_accepts_phase2_minimal_gates():
    from skillsmith.install.subcommands.customize import (
        _validate_skill_data,  # pyright: ignore[reportPrivateUsage]
    )

    data: dict[str, Any] = {
        "skill_id": "wf",
        "skill_class": "workflow",
        "raw_prose": "A" * 120,
        "applies_to_phases": ["build"],
        "exit_gates": {"all_of": [{"artifact_exists": {"path": "src/**"}}]},
        "contract_template": "---\nphase: build\n---\n\nbody\n",
    }
    errors = _validate_skill_data(data, "wf")
    assert errors == []


def test_sdd_workflow_skills_pass_validation():
    """All shipped sdd-*.yaml files must pass the Phase 2 validator."""
    import yaml as _yaml

    import skillsmith
    from skillsmith.install.subcommands.customize import (
        _validate_skill_data,  # pyright: ignore[reportPrivateUsage]
    )

    packs_root = Path(skillsmith.__file__).resolve().parent / "_packs" / "sdd"
    failures: list[str] = []
    for f in sorted(packs_root.glob("sdd-*.yaml")):
        data: dict[str, Any] = _yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        if data.get("skill_class") == "workflow":
            errors = _validate_skill_data(data, f.stem)
            if errors:
                failures.append(f"{f.name}: {errors}")

    assert not failures, "SDD workflow skill validation failures:\n" + "\n".join(failures)
