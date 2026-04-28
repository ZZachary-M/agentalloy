"""Unit tests for the review-gated ingest CLI."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from skillsmith.ingest import EXIT_DUPLICATE, EXIT_OK, EXIT_USAGE, EXIT_VALIDATION, main
from skillsmith.storage.ladybug import LadybugStore

_DOMAIN_YAML = textwrap.dedent("""\
    skill_type: domain
    skill_id: test-domain-skill
    canonical_name: Test Domain Skill
    category: engineering
    skill_class: domain
    domain_tags: [testing]
    always_apply: false
    phase_scope: null
    category_scope: null
    author: test
    change_summary: unit test
    raw_prose: |
      This skill teaches you how to test things.
    fragments:
      - sequence: 1
        fragment_type: execution
        content: |
          Run pytest with the -x flag to stop on first failure.
      - sequence: 2
        fragment_type: verification
        content: |
          All tests pass with exit code 0.
""")

_SYSTEM_YAML = textwrap.dedent("""\
    skill_type: system
    skill_id: sys-test-governance
    canonical_name: Test Governance Rule
    category: governance
    skill_class: system
    domain_tags: []
    always_apply: true
    phase_scope: null
    category_scope: null
    author: test
    change_summary: unit test
    raw_prose: |
      Always cite your sources.
""")


def _make_settings(db_path: str) -> object:
    class FakeSettings:
        ladybug_db_path = db_path

    return FakeSettings()


@pytest.fixture
def seeded_db(tmp_path: Path) -> tuple[str, LadybugStore]:
    db_path = str(tmp_path / "ladybug")
    store = LadybugStore(db_path)
    store.open()
    store.migrate()
    store.close()
    return db_path, store


def test_insert_domain_skill(tmp_path: Path, seeded_db: tuple[str, LadybugStore]) -> None:
    db_path, store = seeded_db
    yaml_file = tmp_path / "domain.yaml"
    yaml_file.write_text(_DOMAIN_YAML)

    with patch("skillsmith.ingest.get_settings", return_value=_make_settings(db_path)):
        code = main([str(yaml_file), "--yes"])

    assert code == EXIT_OK

    store.open()
    name = store.scalar("MATCH (s:Skill {skill_id: 'test-domain-skill'}) RETURN s.canonical_name")
    assert name == "Test Domain Skill"
    fragment_count = store.scalar(
        """
        MATCH (:Skill {skill_id: 'test-domain-skill'})-[:HAS_VERSION]->(v)-[:DECOMPOSES_TO]->(f)
        RETURN count(f)
        """
    )
    assert fragment_count == 2
    current = store.scalar(
        "MATCH (:Skill {skill_id: 'test-domain-skill'})-[:CURRENT_VERSION]->(v) RETURN v.version_id"
    )
    assert current == "test-domain-skill-v1"
    store.close()


def test_insert_system_skill(tmp_path: Path, seeded_db: tuple[str, LadybugStore]) -> None:
    db_path, store = seeded_db
    yaml_file = tmp_path / "system.yaml"
    yaml_file.write_text(_SYSTEM_YAML)

    with patch("skillsmith.ingest.get_settings", return_value=_make_settings(db_path)):
        code = main([str(yaml_file), "--yes"])

    assert code == EXIT_OK

    store.open()
    fragment_count = store.scalar(
        """
        MATCH (:Skill {skill_id: 'sys-test-governance'})-[:HAS_VERSION]->(v)-[:DECOMPOSES_TO]->(f)
        RETURN count(f)
        """
    )
    assert fragment_count == 1
    store.close()


def test_duplicate_skill_id_without_force_fails(
    tmp_path: Path, seeded_db: tuple[str, LadybugStore]
) -> None:
    db_path, _ = seeded_db
    yaml_file = tmp_path / "domain.yaml"
    yaml_file.write_text(_DOMAIN_YAML)

    with patch("skillsmith.ingest.get_settings", return_value=_make_settings(db_path)):
        main([str(yaml_file), "--yes"])
        code = main([str(yaml_file), "--yes"])

    # Re-running ingest on an already-loaded skill returns EXIT_DUPLICATE
    # so re-running setup / install-pack on a populated DB is a clean no-op
    # rather than a "validation failure". Real validation errors still use
    # EXIT_VALIDATION.
    assert code == EXIT_DUPLICATE


def test_canonical_name_collision_without_force_fails(
    tmp_path: Path, seeded_db: tuple[str, LadybugStore]
) -> None:
    db_path, _ = seeded_db
    first = tmp_path / "first.yaml"
    first.write_text(_DOMAIN_YAML)

    second = tmp_path / "second.yaml"
    second.write_text(_DOMAIN_YAML.replace("test-domain-skill", "test-domain-skill-b"))

    with patch("skillsmith.ingest.get_settings", return_value=_make_settings(db_path)):
        assert main([str(first), "--yes"]) == EXIT_OK
        code = main([str(second), "--yes"])

    # Same exit-code semantics for canonical_name collisions.
    assert code == EXIT_DUPLICATE


def test_force_overwrites(tmp_path: Path, seeded_db: tuple[str, LadybugStore]) -> None:
    db_path, store = seeded_db
    yaml_file = tmp_path / "domain.yaml"
    yaml_file.write_text(_DOMAIN_YAML)

    with patch("skillsmith.ingest.get_settings", return_value=_make_settings(db_path)):
        main([str(yaml_file), "--yes"])
        code = main([str(yaml_file), "--force", "--yes"])

    assert code == EXIT_OK

    store.open()
    count = store.scalar("MATCH (s:Skill {skill_id: 'test-domain-skill'}) RETURN count(s)")
    assert count == 1
    store.close()


def test_file_not_found_returns_usage_error() -> None:
    code = main(["/nonexistent/review.yaml", "--yes"])
    assert code == EXIT_USAGE


def test_missing_execution_fragment_is_validation_error(tmp_path: Path) -> None:
    bad = tmp_path / "no_exec.yaml"
    bad.write_text(
        textwrap.dedent("""\
        skill_type: domain
        skill_id: test-no-exec
        canonical_name: No Exec
        category: engineering
        skill_class: domain
        domain_tags: []
        always_apply: false
        raw_prose: Content.
        fragments:
          - sequence: 1
            fragment_type: guardrail
            content: Do not do bad things.
    """)
    )
    code = main([str(bad), "--yes"])
    assert code == EXIT_VALIDATION


def test_system_skill_with_fragments_is_validation_error(tmp_path: Path) -> None:
    bad = tmp_path / "sys_with_frags.yaml"
    bad.write_text(
        textwrap.dedent("""\
        skill_type: system
        skill_id: sys-bad
        canonical_name: Bad System
        category: governance
        skill_class: system
        domain_tags: []
        always_apply: true
        raw_prose: Content.
        fragments:
          - sequence: 1
            fragment_type: guardrail
            content: Extra fragment.
    """)
    )
    code = main([str(bad), "--yes"])
    assert code == EXIT_VALIDATION


def test_system_skill_no_applicability_is_validation_error(tmp_path: Path) -> None:
    bad = tmp_path / "sys_no_apply.yaml"
    bad.write_text(
        textwrap.dedent("""\
        skill_type: system
        skill_id: sys-no-apply
        canonical_name: No Applicability
        category: governance
        skill_class: system
        domain_tags: []
        always_apply: false
        phase_scope: null
        category_scope: null
        raw_prose: Content.
    """)
    )
    code = main([str(bad), "--yes"])
    assert code == EXIT_VALIDATION


def test_invalid_fragment_type_is_validation_error(tmp_path: Path) -> None:
    bad = tmp_path / "bad_frag.yaml"
    bad.write_text(
        textwrap.dedent("""\
        skill_type: domain
        skill_id: test-bad-frag
        canonical_name: Bad Fragment
        category: engineering
        skill_class: domain
        domain_tags: []
        always_apply: false
        raw_prose: Content.
        fragments:
          - sequence: 1
            fragment_type: execution
            content: Core steps.
          - sequence: 2
            fragment_type: unknown_type
            content: What is this?
    """)
    )
    code = main([str(bad), "--yes"])
    assert code == EXIT_VALIDATION


def test_non_contiguous_sequences_is_validation_error(tmp_path: Path) -> None:
    bad = tmp_path / "gap.yaml"
    bad.write_text(
        textwrap.dedent("""\
        skill_type: domain
        skill_id: test-gap
        canonical_name: Gap Sequences
        category: engineering
        skill_class: domain
        domain_tags: []
        always_apply: false
        raw_prose: Content.
        fragments:
          - sequence: 1
            fragment_type: execution
            content: Step one.
          - sequence: 3
            fragment_type: verification
            content: Step three (gap!).
    """)
    )
    code = main([str(bad), "--yes"])
    assert code == EXIT_VALIDATION


# ---------------------------------------------------------------------------
# Batch mode tests
# ---------------------------------------------------------------------------


def _write_domain(path: Path, skill_id: str, canonical_name: str) -> None:
    path.write_text(
        textwrap.dedent(f"""\
        skill_type: domain
        skill_id: {skill_id}
        canonical_name: {canonical_name}
        category: engineering
        skill_class: domain
        domain_tags: []
        always_apply: false
        raw_prose: |
          Content for {skill_id}.
        fragments:
          - sequence: 1
            fragment_type: execution
            content: Core steps for {skill_id}.
    """)
    )


def test_batch_loads_all_valid_files(tmp_path: Path, seeded_db: tuple[str, LadybugStore]) -> None:
    db_path, store = seeded_db
    batch_dir = tmp_path / "batch"
    batch_dir.mkdir()

    _write_domain(batch_dir / "skill_a.yaml", "batch-skill-a", "Batch Skill A")
    _write_domain(batch_dir / "skill_b.yaml", "batch-skill-b", "Batch Skill B")

    with patch("skillsmith.ingest.get_settings", return_value=_make_settings(db_path)):
        code = main([str(batch_dir), "--yes"])

    assert code == EXIT_OK

    store.open()
    count = store.scalar("MATCH (s:Skill) RETURN count(s)")
    assert count == 2
    store.close()


def test_batch_empty_directory_returns_usage_error(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    code = main([str(empty), "--yes"])
    assert code == EXIT_USAGE


def test_batch_skips_invalid_and_loads_valid(
    tmp_path: Path, seeded_db: tuple[str, LadybugStore]
) -> None:
    db_path, store = seeded_db
    batch_dir = tmp_path / "batch"
    batch_dir.mkdir()

    _write_domain(batch_dir / "good.yaml", "batch-good", "Batch Good")

    bad = batch_dir / "bad.yaml"
    bad.write_text(
        textwrap.dedent("""\
        skill_type: domain
        skill_id: batch-bad
        canonical_name: Batch Bad
        category: engineering
        skill_class: domain
        always_apply: false
        raw_prose: Content.
        fragments:
          - sequence: 1
            fragment_type: guardrail
            content: Missing execution fragment.
    """)
    )

    with patch("skillsmith.ingest.get_settings", return_value=_make_settings(db_path)):
        code = main([str(batch_dir), "--yes"])

    assert code == EXIT_OK

    store.open()
    count = store.scalar("MATCH (s:Skill) RETURN count(s)")
    assert count == 1
    store.close()


def test_batch_blocks_duplicates_without_force(
    tmp_path: Path, seeded_db: tuple[str, LadybugStore]
) -> None:
    db_path, _ = seeded_db
    batch_dir = tmp_path / "batch"
    batch_dir.mkdir()

    _write_domain(batch_dir / "skill_a.yaml", "batch-dup-a", "Batch Dup A")

    with patch("skillsmith.ingest.get_settings", return_value=_make_settings(db_path)):
        main([str(batch_dir), "--yes"])
        code = main([str(batch_dir), "--yes"])

    assert code == EXIT_VALIDATION


def test_batch_force_overwrites_duplicates(
    tmp_path: Path, seeded_db: tuple[str, LadybugStore]
) -> None:
    db_path, store = seeded_db
    batch_dir = tmp_path / "batch"
    batch_dir.mkdir()

    _write_domain(batch_dir / "skill_a.yaml", "batch-force-a", "Batch Force A")

    with patch("skillsmith.ingest.get_settings", return_value=_make_settings(db_path)):
        main([str(batch_dir), "--yes"])
        code = main([str(batch_dir), "--force", "--yes"])

    assert code == EXIT_OK

    store.open()
    count = store.scalar("MATCH (s:Skill {skill_id: 'batch-force-a'}) RETURN count(s)")
    assert count == 1
    store.close()
