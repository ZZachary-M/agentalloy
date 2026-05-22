"""Semantic predicate evaluator using cosine similarity against reference phrase sets.

Replaces the chat-model classifier (Phase 3) with embed-based similarity scoring
using the same embed server already running for retrieval. No new server or model
required.

Four semantic predicates:
  user_intent_matches      — prompt similarity against named intent references
  agent_intent_matches     — same (proxy: recent_prompt_text)
  artifact_completeness    — soft advisory only; always returns UNKNOWN (gate handling in gates.py)
  prompt_topic_matches     — prompt similarity against topic phrases
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from skillsmith.signals.predicates import PredicateContext, PredicateResult

if TYPE_CHECKING:
    from skillsmith.lm_client import OpenAICompatClient

_log = logging.getLogger(__name__)

# Reference phrases per named intent. Extend as needed.
_INTENT_REFERENCES: dict[str, list[str]] = {
    "completion": [
        "done with spec",
        "ready to move on",
        "spec is complete",
        "finished",
        "that looks good",
        "good to go",
    ],
    "approval": [
        "looks good",
        "approve",
        "ship it",
        "lgtm",
        "approved",
    ],
    "redirection": [
        "let's change direction",
        "scratch that",
        "new approach",
        "start over",
        "different direction",
    ],
}

_SIMILARITY_THRESHOLD = 0.75
_MAX_INPUT_CHARS = 2000


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _intent_similarity(
    text: str,
    intent: str,
    lm_client: OpenAICompatClient,
    model: str,
    threshold: float = _SIMILARITY_THRESHOLD,
) -> PredicateResult:
    refs = _INTENT_REFERENCES.get(intent)
    if not refs:
        _log.debug("unknown intent %r — returning UNKNOWN", intent)
        return PredicateResult.UNKNOWN
    try:
        vecs = lm_client.embed(model=model, texts=[text[:_MAX_INPUT_CHARS]] + refs)
    except Exception as exc:
        _log.debug("embed call failed: %s", exc)
        return PredicateResult.UNKNOWN
    query_vec = vecs[0]
    best = max(_cosine(query_vec, r) for r in vecs[1:])
    _log.debug("intent=%r best_similarity=%.3f threshold=%.3f", intent, best, threshold)
    return PredicateResult.MET if best >= threshold else PredicateResult.NOT_MET


def _topic_similarity(
    text: str,
    topics: list[str],
    lm_client: OpenAICompatClient,
    model: str,
    threshold: float = _SIMILARITY_THRESHOLD,
) -> PredicateResult:
    if not topics:
        return PredicateResult.UNKNOWN
    try:
        vecs = lm_client.embed(model=model, texts=[text[:_MAX_INPUT_CHARS]] + topics)
    except Exception as exc:
        _log.debug("embed call failed: %s", exc)
        return PredicateResult.UNKNOWN
    query_vec = vecs[0]
    best = max(_cosine(query_vec, r) for r in vecs[1:])
    _log.debug("topics=%r best_similarity=%.3f threshold=%.3f", topics, best, threshold)
    return PredicateResult.MET if best >= threshold else PredicateResult.NOT_MET


def eval_user_intent_matches(
    args: dict[str, Any],
    ctx: PredicateContext,
    lm_client: OpenAICompatClient,
    model: str,
) -> PredicateResult:
    # recent_prompts arg is not supported; similarity runs against recent_prompt_text only.
    intent = args.get("intent", "")
    text = (ctx.recent_prompt_text or "").strip()
    if not text or not intent:
        return PredicateResult.UNKNOWN
    return _intent_similarity(text, intent, lm_client, model)


def eval_agent_intent_matches(
    args: dict[str, Any],
    ctx: PredicateContext,
    lm_client: OpenAICompatClient,
    model: str,
) -> PredicateResult:
    intent = args.get("intent", "")
    # agent_response not in PredicateContext; use recent_prompt_text as proxy
    text = (ctx.recent_prompt_text or "").strip()
    if not text or not intent:
        return PredicateResult.UNKNOWN
    return _intent_similarity(text, intent, lm_client, model)


def eval_artifact_completeness(
    args: dict[str, Any],
    ctx: PredicateContext,
    lm_client: OpenAICompatClient,
    model: str,
) -> PredicateResult:
    # Soft advisory only — gate handling (advisory emission) lives in gates.py.
    # This predicate always returns UNKNOWN so it never blocks a transition.
    return PredicateResult.UNKNOWN


def eval_prompt_topic_matches(
    args: dict[str, Any],
    ctx: PredicateContext,
    lm_client: OpenAICompatClient,
    model: str,
) -> PredicateResult:
    topics = args.get("topics", [])
    text = (ctx.recent_prompt_text or "").strip()
    if not text or not topics:
        return PredicateResult.UNKNOWN
    return _topic_similarity(text, topics, lm_client, model)


SEMANTIC_PREDICATES: dict[
    str,
    Callable[
        [dict[str, Any], PredicateContext, OpenAICompatClient, str],
        PredicateResult,
    ],
] = {
    "user_intent_matches": eval_user_intent_matches,
    "agent_intent_matches": eval_agent_intent_matches,
    "artifact_completeness": eval_artifact_completeness,
    "prompt_topic_matches": eval_prompt_topic_matches,
}
