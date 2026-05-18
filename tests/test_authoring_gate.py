"""Unit tests for the QA gate's deterministic layer and router.

LLM and Ladybug are not exercised here — those are integration surfaces
best tested via fixtures against a live store. These tests pin the pure
logic: vocab validation, routing precedence, bounce accounting.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from skillsmith.authoring.paths import PipelinePaths
from skillsmith.authoring.qa_gate import (
    CriticVerdict,
    DedupHit,
    load_bounces,
    route,
    save_bounces,
)


@pytest.fixture
def paths(tmp_path: Path) -> PipelinePaths:
    p = PipelinePaths(root=tmp_path / "skill-source")
    p.ensure_all()
    return p


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def _approve() -> CriticVerdict:
    return CriticVerdict(verdict="approve", summary="ok")


def _revise() -> CriticVerdict:
    return CriticVerdict(verdict="revise", summary="fix fragment types", blocking_issues=["x"])


def _reject() -> CriticVerdict:
    return CriticVerdict(verdict="reject", summary="dup coverage", blocking_issues=["y"])


def _record_stub() -> Any:
    class R:
        skill_id = "x"

    return R()


def test_route_approve_goes_to_pending_review(paths: PipelinePaths) -> None:
    dest, verdict = route(
        draft_path=Path("x.yaml"),
        record=_record_stub(),
        schema_errors=[],
        hard_dup=None,
        soft_dups=[],
        critic=_approve(),
        bounces=0,
        budget=3,
        paths=paths,
    )
    assert dest == paths.pending_review
    assert verdict == "approve"


def test_route_schema_error_bounces_under_budget(paths: PipelinePaths) -> None:
    dest, verdict = route(
        draft_path=Path("x.yaml"),
        record=_record_stub(),
        schema_errors=["bad category"],
        hard_dup=None,
        soft_dups=[],
        critic=None,
        bounces=1,
        budget=3,
        paths=paths,
    )
    assert dest == paths.pending_revision
    assert verdict == "revise"


def test_route_schema_error_escalates_at_budget(paths: PipelinePaths) -> None:
    dest, verdict = route(
        draft_path=Path("x.yaml"),
        record=_record_stub(),
        schema_errors=["bad category"],
        hard_dup=None,
        soft_dups=[],
        critic=None,
        bounces=3,
        budget=3,
        paths=paths,
    )
    assert dest == paths.needs_human
    assert verdict == "needs-human"


def test_route_hard_dup_rejects(paths: PipelinePaths) -> None:
    hit = DedupHit("other", "other-v1-f1", 0.97, "excerpt")
    dest, verdict = route(
        draft_path=Path("x.yaml"),
        record=_record_stub(),
        schema_errors=[],
        hard_dup=hit,
        soft_dups=[],
        critic=None,
        bounces=0,
        budget=3,
        paths=paths,
    )
    assert dest == paths.rejected
    assert verdict == "reject"


def test_route_critic_revise_bounces(paths: PipelinePaths) -> None:
    dest, verdict = route(
        draft_path=Path("x.yaml"),
        record=_record_stub(),
        schema_errors=[],
        hard_dup=None,
        soft_dups=[],
        critic=_revise(),
        bounces=2,
        budget=3,
        paths=paths,
    )
    assert dest == paths.pending_revision
    assert verdict == "revise"


def test_route_critic_revise_escalates_past_budget(paths: PipelinePaths) -> None:
    dest, _verdict = route(
        draft_path=Path("x.yaml"),
        record=_record_stub(),
        schema_errors=[],
        hard_dup=None,
        soft_dups=[],
        critic=_revise(),
        bounces=3,
        budget=3,
        paths=paths,
    )
    assert dest == paths.needs_human


def test_route_critic_reject_rejects(paths: PipelinePaths) -> None:
    dest, verdict = route(
        draft_path=Path("x.yaml"),
        record=_record_stub(),
        schema_errors=[],
        hard_dup=None,
        soft_dups=[],
        critic=_reject(),
        bounces=0,
        budget=3,
        paths=paths,
    )
    assert dest == paths.rejected
    assert verdict == "reject"


def test_route_parse_failure_escalates(paths: PipelinePaths) -> None:
    dest, _verdict = route(
        draft_path=Path("x.yaml"),
        record=None,
        schema_errors=["parse: bad yaml"],
        hard_dup=None,
        soft_dups=[],
        critic=None,
        bounces=0,
        budget=3,
        paths=paths,
    )
    assert dest == paths.needs_human


def test_route_unparseable_critic_escalates(paths: PipelinePaths) -> None:
    critic = CriticVerdict.unparseable("junk", "json: bad")
    # unparseable marks verdict="needs-human", so the final branch → needs-human
    dest, _verdict = route(
        draft_path=Path("x.yaml"),
        record=_record_stub(),
        schema_errors=[],
        hard_dup=None,
        soft_dups=[],
        critic=critic,
        bounces=0,
        budget=3,
        paths=paths,
    )
    assert dest == paths.needs_human


# ---------------------------------------------------------------------------
# Bounce state persistence
# ---------------------------------------------------------------------------


def test_bounce_roundtrip(paths: PipelinePaths) -> None:
    save_bounces(paths, {"a": 1, "b": 2})
    assert load_bounces(paths) == {"a": 1, "b": 2}


def test_bounce_missing_file_returns_empty(paths: PipelinePaths) -> None:
    assert load_bounces(paths) == {}


def test_bounce_corrupt_file_returns_empty(paths: PipelinePaths) -> None:
    paths.qa_state.parent.mkdir(parents=True, exist_ok=True)
    paths.qa_state.write_text("not-json", encoding="utf-8")
    assert load_bounces(paths) == {}


# ---------------------------------------------------------------------------
# Critic verdict parsing
# ---------------------------------------------------------------------------


def test_unparseable_critic_marked_as_needs_human() -> None:
    v = CriticVerdict.unparseable("garbage", "json decode error")
    assert v.verdict == "needs-human"
    assert "garbage" in v.blocking_issues[0]


# ---------------------------------------------------------------------------
# PipelinePaths
# ---------------------------------------------------------------------------


def test_pipeline_paths_ensure_all(tmp_path: Path) -> None:
    paths = PipelinePaths(root=tmp_path / "x")
    paths.ensure_all()
    for d in (
        paths.pending_qa,
        paths.pending_review,
        paths.pending_revision,
        paths.rejected,
        paths.needs_human,
    ):
        assert d.is_dir()


# ---------------------------------------------------------------------------
# Author output strip fence
# ---------------------------------------------------------------------------


def test_author_strip_yaml_fence() -> None:
    from skillsmith.authoring.driver import _strip_code_fence  # pyright: ignore[reportPrivateUsage]

    fenced = "```yaml\nskill_id: foo\n```"
    assert _strip_code_fence(fenced) == "skill_id: foo"
    assert _strip_code_fence("skill_id: bar") == "skill_id: bar"
