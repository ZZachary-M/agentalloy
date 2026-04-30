"""Startup-time active-skill cache (NXS-777).

Loaded once during lifespan from the runtime store. Compose and retrieve
handlers read exclusively from this snapshot — no per-request DB hits on
the hot path.  A restart is required to pick up re-seeded data.

If loading fails the cache remains ``None``; the health endpoint reflects
``unavailable`` and runtime handlers 503 rather than returning stale or
partial data.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from skillsmith.api.compose_models import Phase
from skillsmith.reads.active import (
    get_active_fragments,
    get_active_skills,
)
from skillsmith.reads.models import ActiveFragment, ActiveSkill, SkillClass
from skillsmith.retrieval.domain import phase_to_categories
from skillsmith.storage.ladybug import LadybugStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VersionDetail:
    """Raw prose + metadata for a single SkillVersion — cached at startup."""

    version_id: str
    version_number: int
    authored_at: Any  # datetime — kept as-is from Kuzu
    author: str
    change_summary: str
    raw_prose: str


class RuntimeCache:
    """Immutable snapshot of all active skill data, loaded at startup.

    Public surface intentionally mirrors the store-backed read functions so
    callers (orchestrators) require minimal changes.
    """

    def __init__(
        self,
        skills: dict[str, ActiveSkill],
        fragments: list[ActiveFragment],
        version_details: dict[str, VersionDetail],
    ) -> None:
        self._skills: dict[str, ActiveSkill] = skills
        self._fragments: list[ActiveFragment] = fragments
        self._version_details: dict[str, VersionDetail] = version_details
        self.skill_count: int = len(skills)
        self.fragment_count: int = len(fragments)

    # ---- skill reads ----

    def get_active_skill_by_id(self, skill_id: str) -> ActiveSkill | None:
        return self._skills.get(skill_id)

    def get_active_skills(
        self, *, skill_class: SkillClass | tuple[str, ...] | None = None
    ) -> list[ActiveSkill]:
        skills = list(self._skills.values())
        if skill_class is not None:
            if isinstance(skill_class, tuple):
                skills = [s for s in skills if s.skill_class in skill_class]
            else:
                skills = [s for s in skills if s.skill_class == skill_class]
        return sorted(skills, key=lambda s: s.skill_id)

    # ---- fragment reads ----

    def get_active_fragments(
        self,
        *,
        skill_class: SkillClass | tuple[str, ...] | None = None,
        categories: list[str] | None = None,
        domain_tags: list[str] | None = None,
    ) -> list[ActiveFragment]:
        result: list[ActiveFragment] = list(self._fragments)
        if skill_class is not None:
            if isinstance(skill_class, tuple):
                result = [f for f in result if f.skill_class in skill_class]
            else:
                result = [f for f in result if f.skill_class == skill_class]
        if categories is not None:
            cat_set = set(categories)
            result = [f for f in result if f.category in cat_set]
        if domain_tags is not None:
            tag_set = set(domain_tags)
            result = [f for f in result if any(t in tag_set for t in f.domain_tags)]
        return result

    def get_active_fragments_for_skill(self, skill_id: str) -> list[ActiveFragment]:
        return sorted(
            [f for f in self._fragments if f.skill_id == skill_id],
            key=lambda f: f.sequence,
        )

    def get_active_fragments_for_phase(
        self,
        phase: Phase,
        *,
        domain_tags: list[str] | None = None,
    ) -> list[ActiveFragment]:
        """Convenience: fragments eligible for a compose/retrieve phase."""
        return self.get_active_fragments(
            skill_class=("domain", "workflow"),
            categories=phase_to_categories(phase),
            domain_tags=domain_tags,
        )

    # ---- version detail reads ----

    def get_version_detail(self, version_id: str) -> VersionDetail | None:
        return self._version_details.get(version_id)


def load_runtime_cache(store: LadybugStore) -> RuntimeCache:
    """Query the store and build a ``RuntimeCache``.

    Raises on any store or consistency error — the caller (lifespan) should
    catch and record the failure rather than propagating through FastAPI's
    startup.
    """
    logger.info("Loading active skill data into runtime cache …")

    skills_list = get_active_skills(store)
    skills_by_id: dict[str, ActiveSkill] = {s.skill_id: s for s in skills_list}

    fragments = get_active_fragments(store)

    # Collect all unique version_ids we need details for.
    version_ids: set[str] = {s.active_version_id for s in skills_list}

    version_details: dict[str, VersionDetail] = {}
    for vid in version_ids:
        rows = store.execute(
            """
            MATCH (v:SkillVersion {version_id: $vid})
            RETURN v.version_id, v.version_number, v.authored_at, v.author,
                   v.change_summary, v.raw_prose
            """,
            {"vid": vid},
        )
        if not rows:
            raise RuntimeError(f"version {vid!r} not found during cache load")
        row = rows[0]
        version_details[vid] = VersionDetail(
            version_id=str(row[0]),
            version_number=int(row[1]),
            authored_at=row[2],
            author=str(row[3]),
            change_summary=str(row[4]),
            raw_prose=str(row[5]),
        )

    cache = RuntimeCache(
        skills=skills_by_id,
        fragments=fragments,
        version_details=version_details,
    )
    logger.info(
        "Runtime cache loaded: %d skills, %d fragments",
        cache.skill_count,
        cache.fragment_count,
    )
    return cache
