"""Tests for Phase E: workflow skill_class inclusion in get_active_fragments."""

from __future__ import annotations

from pathlib import Path

import pytest

from skillsmith.ingest import (
    FragmentRecord,
    ReviewRecord,
    _insert,  # type: ignore[reportPrivateUsage]
)
from skillsmith.reads import active as reads_active
from skillsmith.storage.ladybug import LadybugStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> LadybugStore:
    s = LadybugStore(str(tmp_path / "ladybug"))
    s.open()
    s.migrate()
    return s


def _workflow_record() -> ReviewRecord:
    return ReviewRecord(
        skill_type="domain",
        skill_id="test-workflow-skill",
        canonical_name="Test Workflow Skill",
        category="engineering",
        skill_class="workflow",
        domain_tags=["testing", "workflow"],
        always_apply=False,
        phase_scope=[],
        category_scope=[],
        author="test-author",
        change_summary="initial",
        raw_prose="Follow the workflow steps carefully.",
        fragments=[
            FragmentRecord(
                sequence=1,
                fragment_type="execution",
                content="Step 1: plan. Step 2: execute.",
            )
        ],
        tier=None,
    )


def _domain_record() -> ReviewRecord:
    return ReviewRecord(
        skill_type="domain",
        skill_id="test-domain-skill",
        canonical_name="Test Domain Skill",
        category="engineering",
        skill_class="domain",
        domain_tags=["testing", "domain"],
        always_apply=False,
        phase_scope=[],
        category_scope=[],
        author="test-author",
        change_summary="initial",
        raw_prose="Apply domain knowledge.",
        fragments=[
            FragmentRecord(
                sequence=1,
                fragment_type="execution",
                content="Apply the domain pattern here.",
            )
        ],
        tier=None,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_workflow_fragment_included_in_tuple_query(store: LadybugStore) -> None:
    """get_active_fragments(skill_class=("domain","workflow")) returns workflow fragments."""
    _insert(store, _workflow_record(), force=False)

    fragments = reads_active.get_active_fragments(store, skill_class=("domain", "workflow"))
    fragment_skill_ids = [f.skill_id for f in fragments]
    assert "test-workflow-skill" in fragment_skill_ids


def test_workflow_fragment_included_in_string_query(store: LadybugStore) -> None:
    """get_active_fragments(skill_class="workflow") returns workflow fragments."""
    _insert(store, _workflow_record(), force=False)

    fragments = reads_active.get_active_fragments(store, skill_class="workflow")
    fragment_skill_ids = [f.skill_id for f in fragments]
    assert "test-workflow-skill" in fragment_skill_ids


def test_domain_filter_excludes_workflow_fragments(store: LadybugStore) -> None:
    """get_active_fragments(skill_class="domain") does NOT return workflow fragments."""
    _insert(store, _workflow_record(), force=False)

    fragments = reads_active.get_active_fragments(store, skill_class="domain")
    fragment_skill_ids = [f.skill_id for f in fragments]
    assert "test-workflow-skill" not in fragment_skill_ids


def test_tuple_query_includes_both_classes(store: LadybugStore) -> None:
    """get_active_fragments(skill_class=("domain","workflow")) returns both domain and workflow."""
    _insert(store, _workflow_record(), force=False)
    _insert(store, _domain_record(), force=False)

    fragments = reads_active.get_active_fragments(store, skill_class=("domain", "workflow"))
    fragment_skill_ids = {f.skill_id for f in fragments}
    assert "test-workflow-skill" in fragment_skill_ids
    assert "test-domain-skill" in fragment_skill_ids


def test_domain_string_query_excludes_workflow(store: LadybugStore) -> None:
    """get_active_fragments(skill_class="domain") only returns domain, not workflow."""
    _insert(store, _workflow_record(), force=False)
    _insert(store, _domain_record(), force=False)

    fragments = reads_active.get_active_fragments(store, skill_class="domain")
    fragment_skill_ids = {f.skill_id for f in fragments}
    assert "test-domain-skill" in fragment_skill_ids
    assert "test-workflow-skill" not in fragment_skill_ids
