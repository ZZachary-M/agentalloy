"""Smoke test for the eval/ corpus-regression harness.

Cheap, network-free guards that catch port/adaptation breakage in the four
ported harness modules before the (live, slow) audit + gold-hit runs:

* all four modules import cleanly (no missing deps / broken module paths),
* every domain task's gold skill ids are well-formed non-empty strings,
* the committed corpus_baselines.json parses and carries the keys the
  comparator (check_corpus_regression.compare) actually reads.

No service, no model calls — pure import + JSON parse, so it runs in CI
without a live AgentAlloy on :47950.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINES = REPO_ROOT / "eval" / "corpus_baselines.json"


def test_all_four_harness_modules_import() -> None:
    """All four ported eval modules import without error."""
    import eval.check_corpus_regression  # noqa: F401
    import eval.domain_tasks  # noqa: F401
    import eval.gold_hit  # noqa: F401
    import eval.retrieval_audit  # noqa: F401


def test_domain_tasks_gold_ids_are_well_formed() -> None:
    """Every domain task carries a non-empty list of non-empty str gold ids."""
    from eval.domain_tasks import DOMAIN_TASKS

    assert DOMAIN_TASKS, "DOMAIN_TASKS must not be empty"
    seen_task_ids: set[str] = set()
    for task in DOMAIN_TASKS:
        assert isinstance(task.task_id, str) and task.task_id.strip(), (
            f"task_id must be a non-empty string, got {task.task_id!r}"
        )
        assert task.task_id not in seen_task_ids, f"duplicate task_id {task.task_id!r}"
        seen_task_ids.add(task.task_id)
        assert isinstance(task.gold_skills, (list, tuple)), (
            f"{task.task_id}: gold_skills must be a list/tuple"
        )
        assert len(task.gold_skills) >= 1, f"{task.task_id}: needs >=1 gold skill"
        for gid in task.gold_skills:
            assert isinstance(gid, str) and gid.strip(), (
                f"{task.task_id}: gold skill id must be a non-empty string, got {gid!r}"
            )
            # ids are kebab-case skill_ids: no whitespace, no path separators
            assert " " not in gid and "/" not in gid, (
                f"{task.task_id}: malformed gold skill id {gid!r}"
            )


def test_corpus_baselines_parses_with_required_keys() -> None:
    """corpus_baselines.json parses and has every key the comparator reads."""
    assert BASELINES.is_file(), f"missing baseline file: {BASELINES}"
    data = json.loads(BASELINES.read_text())
    assert isinstance(data, dict)

    # Keys consumed by check_corpus_regression.compare()
    for key in (
        "tolerance",
        "name_probe_hit_rate",
        "topic_probe_hit_rate",
        "stranded_count",
        "gold_hit",
        "gold_hit_total",
    ):
        assert key in data, f"corpus_baselines.json missing required key {key!r}"

    assert 0.0 <= float(data["name_probe_hit_rate"]) <= 1.0
    assert 0.0 <= float(data["topic_probe_hit_rate"]) <= 1.0
    assert float(data["tolerance"]) >= 0.0
    assert int(data["stranded_count"]) >= 0
    assert int(data["gold_hit"]) >= 0
    assert int(data["gold_hit_total"]) >= int(data["gold_hit"])

    # Optional per-phase floors must be a {phase: 0..1} map when present
    floors = data.get("phase_hit_rate_floors")
    if floors is not None:
        assert isinstance(floors, dict)
        for phase, floor in floors.items():
            assert isinstance(phase, str) and phase
            assert 0.0 <= float(floor) <= 1.0
