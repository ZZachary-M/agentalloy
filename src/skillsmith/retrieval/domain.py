"""Domain fragment retrieval pipeline.

Given a task + phase + optional filters, embed the task via the inference
runtime, query DuckDB ``fragment_embeddings`` for top-k by cosine, fuse with
a BM25 lexical leg via Reciprocal Rank Fusion (RRF, k=60), hydrate
ActiveFragment metadata from LadybugDB, then reshuffle for structural
diversity (setup/execution/verification preferred).

Per v5.3, vector storage is DuckDB; cosine ranking happens in DuckDB via
``array_cosine_distance`` over L2-normalized vectors. The
``cosine_similarity`` Python helper is no longer used in the hot path.
"""

from __future__ import annotations

import os as _os
import time
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from skillsmith.api.compose_models import Phase
from skillsmith.authoring.lm_client import OpenAICompatClient
from skillsmith.reads import ActiveFragment
from skillsmith.reads.models import SkillClass
from skillsmith.storage.vector_store import SimilarityHit, VectorStore

_RRF_K = 60


@runtime_checkable
class FragmentSource(Protocol):
    """Structural protocol satisfied by ``RuntimeCache`` and ``StoreFragmentSource``."""

    def get_active_fragments(
        self,
        *,
        skill_class: SkillClass | tuple[str, ...] | None = None,
        categories: list[str] | None = None,
        domain_tags: list[str] | None = None,
    ) -> list[ActiveFragment]: ...


# Phase → eligible-category mapping. Aligned with the seeded corpus
# vocabulary (design, engineering, quality, review, tooling, ops). The
# legacy phase-as-category vocabulary (spec/qa/build/governance/meta) is
# kept where it overlaps so existing fragments authored to that schema
# remain reachable.
_PHASE_TO_CATEGORIES: dict[Phase, list[str]] = {
    "spec": ["spec", "design", "tooling", "governance", "meta"],
    "design": ["design", "engineering", "tooling", "governance", "meta"],
    "qa": ["qa", "quality", "review", "engineering", "tooling", "governance", "meta"],
    "build": ["build", "engineering", "tooling", "ops", "governance", "meta"],
    "ops": ["ops", "engineering", "tooling", "governance", "meta"],
    "meta": ["meta", "tooling", "governance"],
    "governance": ["governance", "review", "quality", "meta"],
}

# Order of preference for structural diversity during reshuffle.
_DIVERSITY_PRIORITY: tuple[str, ...] = ("setup", "execution", "verification")


def phase_to_categories(phase: Phase) -> list[str]:
    """Return the ordered list of Skill.category values eligible for a given phase."""
    return list(_PHASE_TO_CATEGORIES[phase])


@dataclass(frozen=True)
class RetrievalResult:
    candidates: list[ActiveFragment]
    eligible_count: int
    retrieval_ms: int
    # cosine similarity per fragment_id (in [0, 1]); 1 = identical direction.
    scores_by_id: dict[str, float] = field(default_factory=lambda: {})


class StoreFragmentSource:
    """Thin adapter so a raw ``LadybugStore`` satisfies ``FragmentSource``."""

    def __init__(self, store: object) -> None:
        self._store = store

    def get_active_fragments(
        self,
        *,
        skill_class: SkillClass | tuple[str, ...] | None = None,
        categories: list[str] | None = None,
        domain_tags: list[str] | None = None,
    ) -> list[ActiveFragment]:
        from skillsmith.reads import get_active_fragments  # local import avoids cycle

        return get_active_fragments(
            self._store,  # type: ignore[arg-type]
            skill_class=skill_class,
            categories=categories,
            domain_tags=domain_tags,
        )


def _rrf_fuse(
    dense_hits: list[SimilarityHit],
    bm25_fragment_ids: list[str],
    k: int = _RRF_K,
) -> list[str]:
    """Reciprocal Rank Fusion over dense and BM25 result lists.

    Returns fragment_ids ordered by descending RRF score. Documents appearing
    in only one leg get a rank of len(that_leg)+1 in the missing leg.
    """
    dense_ids = [h.fragment_id for h in dense_hits]
    all_ids = dict.fromkeys(dense_ids + bm25_fragment_ids)

    dense_rank = {fid: i + 1 for i, fid in enumerate(dense_ids)}
    bm25_rank = {fid: i + 1 for i, fid in enumerate(bm25_fragment_ids)}
    dense_miss = len(dense_ids) + 1
    bm25_miss = len(bm25_fragment_ids) + 1

    scores: dict[str, float] = {}
    for fid in all_ids:
        scores[fid] = 1.0 / (k + dense_rank.get(fid, dense_miss)) + 1.0 / (
            k + bm25_rank.get(fid, bm25_miss)
        )

    return sorted(all_ids, key=lambda fid: scores[fid], reverse=True)


def retrieve_domain_candidates(
    source: object,
    lm: OpenAICompatClient,
    vector_store: VectorStore,
    *,
    task: str,
    phase: Phase,
    domain_tags: list[str] | None,
    k: int,
    embedding_model: str,
    raw_scores: bool = False,
) -> RetrievalResult:
    """Execute the retrieval pipeline and return a bounded candidate set.

    ``source`` may be a ``RuntimeCache`` (startup-loaded snapshot) or a raw
    ``LadybugStore`` (wrapped automatically via ``StoreFragmentSource``).
    ``vector_store`` is a DuckDB ``VectorStore`` whose ``fragment_embeddings``
    table is populated via the reembed CLI.

    Stages:

    1. embed the task via ``lm.embed`` (propagates LMClientError on failure)
    2. DuckDB top-k vector search filtered by phase categories
    3. DuckDB BM25 search on prose column filtered by phase categories
    4. Reciprocal Rank Fusion of both legs
    5. hydrate ActiveFragment metadata from ``source`` and apply optional
       domain_tags filter
    6. greedy diversity reshuffle — prefer fragment_types from the
       setup/execution/verification priority set when not already in the
       selected set (skipped when ``raw_scores=True``)
    """
    start_ns = time.perf_counter_ns()

    frag_src: FragmentSource = (
        source if isinstance(source, FragmentSource) else StoreFragmentSource(source)
    )

    embed_prefix = (
        "Given a software engineering task description, retrieve relevant "
        "skill instruction fragments: "
    )
    query_vec = lm.embed(model=embedding_model, texts=[embed_prefix + task])[0]

    categories = phase_to_categories(phase)
    pool_size = max(k * 2, k)

    dense_hits = vector_store.search_similar(
        query_vec,
        categories=categories,
        k=pool_size,
    )

    bm25_hits = vector_store.search_bm25(task, categories=categories, k=pool_size)
    bm25_ids = [h.fragment_id for h in bm25_hits]

    if not dense_hits and not bm25_hits:
        elapsed_ms = (time.perf_counter_ns() - start_ns) // 1_000_000
        return RetrievalResult(candidates=[], eligible_count=0, retrieval_ms=int(elapsed_ms))

    fused_ids = _rrf_fuse(dense_hits, bm25_ids)

    # Hydrate ActiveFragment metadata from the source. Pull domain fragments
    # for the eligible categories; intersect with the fused ids.
    metadata = frag_src.get_active_fragments(
        skill_class=("domain", "workflow"),
        categories=categories,
        domain_tags=domain_tags,
    )
    by_id = {f.fragment_id: f for f in metadata}

    # Build dense score lookup for observability.
    dense_score_by_id = {h.fragment_id: 1.0 - h.distance for h in dense_hits}

    ranked: list[ActiveFragment] = []
    scores_by_id: dict[str, float] = {}
    for fid in fused_ids:
        frag = by_id.get(fid)
        if frag is None:
            continue
        ranked.append(frag)
        scores_by_id[fid] = dense_score_by_id.get(fid, 0.0)

    eligible_count = len(ranked)

    # raw_scores=True: return pre-diversity order (for /retrieve observability).
    # RUNTIME_DIVERSITY_SELECTION=off also short-circuits — used by eval harness.
    diversity_off = _os.environ.get("RUNTIME_DIVERSITY_SELECTION", "on").lower() == "off"
    selected = ranked[:k] if raw_scores or diversity_off else diversity_select(ranked, k)

    elapsed_ms = (time.perf_counter_ns() - start_ns) // 1_000_000
    return RetrievalResult(
        candidates=selected,
        eligible_count=eligible_count,
        retrieval_ms=int(elapsed_ms),
        scores_by_id=scores_by_id,
    )


def diversity_select(pool: list[ActiveFragment], k: int) -> list[ActiveFragment]:
    """Greedy selection that favors unseen fragment_types from the priority set.

    When a priority type (setup, execution, verification) is not yet represented
    in ``selected``, prefer the highest-scoring candidate of that type. Otherwise
    fall back to the next highest-scoring candidate regardless of type. Already-
    selected fragments are never re-picked.
    """
    selected: list[ActiveFragment] = []
    selected_types: set[str] = set()
    # `pool` is already ranked by similarity — index preserves score order.
    remaining = list(pool)

    while len(selected) < k and remaining:
        chosen_index: int | None = None
        # First pass: pick a priority type not yet selected.
        for ptype in _DIVERSITY_PRIORITY:
            if ptype in selected_types:
                continue
            for i, frag in enumerate(remaining):
                if frag.fragment_type == ptype:
                    chosen_index = i
                    break
            if chosen_index is not None:
                break
        # Fallback: take the top-ranked remaining fragment.
        if chosen_index is None:
            chosen_index = 0
        frag = remaining.pop(chosen_index)
        selected.append(frag)
        selected_types.add(frag.fragment_type)

    return selected
