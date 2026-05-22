"""Tests for Phase 6 similarity-based semantic predicate evaluator."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from skillsmith.signals.classifier import (
    SEMANTIC_PREDICATES,
    _cosine,  # pyright: ignore[reportPrivateUsage]
    _intent_similarity,  # pyright: ignore[reportPrivateUsage]
    eval_artifact_completeness,
    eval_prompt_topic_matches,
    eval_user_intent_matches,
)
from skillsmith.signals.predicates import PredicateContext, PredicateResult


def _ctx(tmp_path: Path, prompt: str = "") -> PredicateContext:
    return PredicateContext(
        project_root=tmp_path,
        current_phase="build",
        recent_prompt_text=prompt,
    )


def _mock_client(vecs: list[list[float]]) -> MagicMock:
    client = MagicMock()
    client.embed.return_value = vecs
    return client


# ---------------------------------------------------------------------------
# _cosine
# ---------------------------------------------------------------------------


def test_cosine_identical_vectors():
    v = [1.0, 0.0, 0.0]
    assert _cosine(v, v) == pytest.approx(1.0)  # pyright: ignore[reportUnknownMemberType]


def test_cosine_orthogonal():
    assert _cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)  # pyright: ignore[reportUnknownMemberType]


def test_cosine_zero_vector():
    assert _cosine([0.0, 0.0], [1.0, 0.0]) == 0.0


# ---------------------------------------------------------------------------
# _intent_similarity
# ---------------------------------------------------------------------------


def test_intent_similarity_above_threshold_returns_met(tmp_path: Path):
    # query vec very similar to one of the refs
    query = [1.0, 0.0]
    refs = [[0.99, 0.14], [0.0, 1.0]]
    client = _mock_client([query] + refs)
    result = _intent_similarity("done", "completion", client, "embed-model", threshold=0.75)
    assert result == PredicateResult.MET


def test_intent_similarity_below_threshold_returns_not_met(tmp_path: Path):
    query = [1.0, 0.0]
    refs = [[0.0, 1.0], [0.0, 1.0]]  # all orthogonal
    client = _mock_client([query] + refs)
    result = _intent_similarity("done", "completion", client, "embed-model", threshold=0.75)
    assert result == PredicateResult.NOT_MET


def test_intent_similarity_unknown_intent_returns_unknown():
    client = MagicMock()
    result = _intent_similarity("text", "nonexistent_intent", client, "embed-model")
    assert result == PredicateResult.UNKNOWN
    client.embed.assert_not_called()


def test_intent_similarity_embed_failure_returns_unknown():
    client = MagicMock()
    client.embed.side_effect = RuntimeError("connection refused")
    result = _intent_similarity("text", "completion", client, "embed-model")
    assert result == PredicateResult.UNKNOWN


# ---------------------------------------------------------------------------
# eval_artifact_completeness — always UNKNOWN
# ---------------------------------------------------------------------------


def test_artifact_completeness_always_unknown(tmp_path: Path):
    ctx = _ctx(tmp_path)
    client = MagicMock()
    result = eval_artifact_completeness(
        {"path": "spec.md", "criteria": "all ACs are testable"},
        ctx,
        client,
        "embed-model",
    )
    assert result == PredicateResult.UNKNOWN
    client.embed.assert_not_called()


def test_artifact_completeness_no_args_unknown(tmp_path: Path):
    ctx = _ctx(tmp_path)
    result = eval_artifact_completeness({}, ctx, MagicMock(), "embed-model")
    assert result == PredicateResult.UNKNOWN


# ---------------------------------------------------------------------------
# eval_user_intent_matches
# ---------------------------------------------------------------------------


def test_user_intent_matches_met(tmp_path: Path):
    query = [1.0, 0.0]
    refs = [[0.99, 0.14], [0.0, 1.0]]
    client = _mock_client([query] + refs)
    ctx = _ctx(tmp_path, prompt="looks good, approve")
    result = eval_user_intent_matches({"intent": "completion"}, ctx, client, "embed-model")
    assert result == PredicateResult.MET


def test_user_intent_matches_empty_prompt_unknown(tmp_path: Path):
    ctx = _ctx(tmp_path, prompt="")
    result = eval_user_intent_matches({"intent": "completion"}, ctx, MagicMock(), "embed-model")
    assert result == PredicateResult.UNKNOWN


# ---------------------------------------------------------------------------
# eval_prompt_topic_matches
# ---------------------------------------------------------------------------


def test_prompt_topic_matches_met(tmp_path: Path):
    query = [1.0, 0.0]
    refs = [[0.99, 0.14]]
    client = _mock_client([query] + refs)
    ctx = _ctx(tmp_path, prompt="let's discuss authentication")
    result = eval_prompt_topic_matches({"topics": ["authentication"]}, ctx, client, "embed-model")
    assert result == PredicateResult.MET


def test_prompt_topic_matches_empty_topics_unknown(tmp_path: Path):
    ctx = _ctx(tmp_path, prompt="something")
    result = eval_prompt_topic_matches({"topics": []}, ctx, MagicMock(), "embed-model")
    assert result == PredicateResult.UNKNOWN


# ---------------------------------------------------------------------------
# SEMANTIC_PREDICATES registry
# ---------------------------------------------------------------------------


def test_semantic_predicates_no_chat_calls(tmp_path: Path):
    """Verify none of the semantic predicates use lm_client.chat."""
    ctx = _ctx(tmp_path, prompt="done")
    client = MagicMock()
    client.embed.return_value = [[1.0, 0.0]] * 10

    for name, fn in SEMANTIC_PREDICATES.items():
        if name == "artifact_completeness":
            fn({"path": "f.md", "criteria": "x"}, ctx, client, "m")
        elif name in ("user_intent_matches", "agent_intent_matches"):
            fn({"intent": "completion"}, ctx, client, "m")
        elif name == "prompt_topic_matches":
            fn({"topics": ["auth"]}, ctx, client, "m")

    client.chat.assert_not_called()
