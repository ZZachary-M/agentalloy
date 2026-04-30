"""Mechanical (deterministic) tag linting for skill corpus quality checks.

Implements Rules R2, R3-stem, W1, tier-ceiling, and system-empty checks.
No LLM calls — all logic is rule-based and testable in isolation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from skillsmith.ingest import TAG_POLICY_BY_TIER, WORKFLOW_POSITION_MARKERS, WORKFLOW_TAG_POLICY


@dataclass(frozen=True)
class TagVerdict:
    tag: str  # the tag being judged
    rule: str  # e.g. "R2", "R3-stem", "W1", "tier-ceiling", "system-empty"
    verdict: str  # "redundant_with_title" | "synonym_of:<other>" | "missing_position_marker"
    # | "over_ceiling" | "system_has_tags"
    detail: str  # human-readable explanation


def _stems(text: str) -> set[str]:
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    suffixes = re.compile(r"(ing|tion|tions|ation|ations|ed|ment|ments|ness|ity|ies|es|s)$")
    return {suffixes.sub("", t) for t in tokens if len(t) > 2}


def lint_tags_mechanical(
    tags: list[str],
    skill_class: str,
    canonical_name: str,
    tier: str | None,
) -> list[TagVerdict]:
    """Run mechanical tag lint rules; return a (possibly empty) list of TagVerdicts."""
    verdicts: list[TagVerdict] = []

    if skill_class == "system":
        for tag in tags:
            verdicts.append(
                TagVerdict(
                    tag=tag,
                    rule="system-empty",
                    verdict="system_has_tags",
                    detail="system skills must have domain_tags: [] — tags are ignored during retrieval",
                )
            )
        return verdicts

    # --- Shared checks for domain and workflow ---

    # Rule 2: tag stems overlap title stems → redundant
    title_stems = _stems(canonical_name)
    for tag in tags:
        tag_stems = _stems(tag)
        if tag_stems and tag_stems <= title_stems:
            verdicts.append(
                TagVerdict(
                    tag=tag,
                    rule="R2",
                    verdict="redundant_with_title",
                    detail=f"tag '{tag}' stem-overlaps title — already retrievable from title",
                )
            )

    # Rule 3-stem: pairwise stem overlap between tags
    for i, t1 in enumerate(tags):
        for t2 in tags[i + 1 :]:
            if t1 == t2:
                continue
            shared = _stems(t1) & _stems(t2)
            if shared:
                verdicts.append(
                    TagVerdict(
                        tag=t2,
                        rule="R3-stem",
                        verdict=f"synonym_of:{t1}",
                        detail=f"'{t2}' shares stems with '{t1}' — deduplicate",
                    )
                )

    if skill_class == "domain":
        # Tier ceiling
        policy = TAG_POLICY_BY_TIER.get(tier) if tier else None
        if policy is not None and len(tags) > policy["soft_ceiling"]:
            verdicts.append(
                TagVerdict(
                    tag="(count)",
                    rule="tier-ceiling",
                    verdict="over_ceiling",
                    detail=(
                        f"{len(tags)} tags exceeds {tier} ceiling of "
                        f"{policy['soft_ceiling']} — trim or add tags_rationale"
                    ),
                )
            )

    elif skill_class == "workflow":
        # Tier ceiling (uses WORKFLOW_TAG_POLICY, not tier-keyed)
        policy = WORKFLOW_TAG_POLICY
        if len(tags) > policy["soft_ceiling"]:
            verdicts.append(
                TagVerdict(
                    tag="(count)",
                    rule="tier-ceiling",
                    verdict="over_ceiling",
                    detail=(
                        f"{len(tags)} tags exceeds workflow ceiling of "
                        f"{policy['soft_ceiling']} — trim or add tags_rationale"
                    ),
                )
            )

        # Rule W1: position marker required
        if not any(tag in WORKFLOW_POSITION_MARKERS for tag in tags):
            verdicts.append(
                TagVerdict(
                    tag="(none)",
                    rule="W1",
                    verdict="missing_position_marker",
                    detail=(
                        "workflow skill needs at least one position marker from "
                        "WORKFLOW_POSITION_MARKERS (e.g. phase:spec, phase:build, sdd, code-review)"
                    ),
                )
            )

    return verdicts
