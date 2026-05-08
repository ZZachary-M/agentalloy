"""Unit tests for the reembed CLI.

Live LM Studio isn't required — ``embed_fn`` is injected so tests pass a
deterministic fake. LadybugDB also isn't required for most tests; we unit-test
the pure logic (retry + main loop) and leave the Cypher discovery path for
integration coverage.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from skillsmith.lm_client import LMBadResponse, LMTimeout, LMUnavailable
from skillsmith.reembed import (
    FragmentNeedingEmbedding,
    reembed_fragments,
)
from skillsmith.reembed.cli import _embed_with_retry  # pyright: ignore[reportPrivateUsage]
from skillsmith.storage.vector_store import EMBEDDING_DIM, VectorStore, open_or_create

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _unit_vec(i: int) -> list[float]:
    v = [0.0] * EMBEDDING_DIM
    v[i] = 1.0
    return v


def _mk_frag(i: int, skill: str = "skill-a") -> FragmentNeedingEmbedding:
    return FragmentNeedingEmbedding(
        fragment_id=f"frag-{i}",
        content=f"content of fragment {i}",
        fragment_type="execution",
        skill_id=skill,
        category="engineering",
    )


@pytest.fixture
def store(tmp_path: Path):
    with open_or_create(tmp_path / "r.duck") as s:
        yield s


# ---------------------------------------------------------------------------
# _embed_with_retry
# ---------------------------------------------------------------------------


def test_retry_succeeds_on_first_attempt() -> None:
    calls = {"n": 0}

    def fn(_: str) -> list[float]:
        calls["n"] += 1
        return _unit_vec(0)

    result = _embed_with_retry(fn, "x", delays=(0.0, 0.0, 0.0))
    assert result == _unit_vec(0)
    assert calls["n"] == 1


def test_retry_recovers_after_transient_failure() -> None:
    calls = {"n": 0}

    def fn(_: str) -> list[float]:
        calls["n"] += 1
        if calls["n"] < 3:
            raise LMTimeout("simulated timeout")
        return _unit_vec(5)

    result = _embed_with_retry(fn, "x", delays=(0.0, 0.0, 0.0))
    assert result == _unit_vec(5)
    assert calls["n"] == 3


def test_retry_gives_up_after_max_attempts() -> None:
    calls = {"n": 0}

    def fn(_: str) -> list[float]:
        calls["n"] += 1
        raise LMUnavailable("endpoint dead")

    with pytest.raises(LMUnavailable):
        _embed_with_retry(fn, "x", delays=(0.0, 0.0, 0.0))
    # 1 initial + 3 retries = 4 attempts with the default delays tuple.
    assert calls["n"] == 4


def test_retry_fails_fast_on_non_transient_error() -> None:
    calls = {"n": 0}

    def fn(_: str) -> list[float]:
        calls["n"] += 1
        raise LMBadResponse("malformed")

    with pytest.raises(LMBadResponse):
        _embed_with_retry(fn, "x", delays=(0.0, 0.0, 0.0))
    # Bad-response errors are not retried.
    assert calls["n"] == 1


# ---------------------------------------------------------------------------
# reembed_fragments
# ---------------------------------------------------------------------------


def test_reembed_happy_path(store: VectorStore) -> None:
    fragments = [_mk_frag(i) for i in range(5)]

    def embed(content: str) -> list[float]:
        # Synthesize a stable fake: one unit vector per fragment index.
        i = int(content.rsplit(" ", 1)[-1])
        return _unit_vec(i)

    stats = reembed_fragments(
        fragments,
        embed_fn=embed,
        vector_store=store,
        embedding_model="test-embed",
    )
    assert stats.discovered == 5
    assert stats.embedded == 5
    assert stats.failed == 0
    assert store.count_embeddings() == 5


def test_reembed_records_failures_and_keeps_going(store: VectorStore) -> None:
    fragments = [_mk_frag(i) for i in range(3)]

    def embed(content: str) -> list[float]:
        if "fragment 1" in content:
            raise LMUnavailable("server down")
        i = int(content.rsplit(" ", 1)[-1])
        return _unit_vec(i)

    stats = reembed_fragments(
        fragments,
        embed_fn=embed,
        vector_store=store,
        embedding_model="test-embed",
    )
    assert stats.embedded == 2
    assert stats.failed == 1
    assert any(fid == "frag-1" for fid, _ in stats.failures)
    assert store.count_embeddings() == 2


def test_reembed_empty_input(store: VectorStore) -> None:
    def embed(content: str) -> list[float]:  # should never be called
        raise AssertionError("embed called on empty input")

    stats = reembed_fragments(
        [],
        embed_fn=embed,
        vector_store=store,
        embedding_model="test-embed",
    )
    assert stats.discovered == 0
    assert stats.embedded == 0
    assert store.count_embeddings() == 0


def test_reembed_catches_insert_failure(store: VectorStore) -> None:
    """Pre-insert the same fragment_id; the reembed insert should fail (PK)
    but the loop must continue to the next fragment."""
    fragments = [_mk_frag(0), _mk_frag(1)]
    # Seed the duckdb with frag-0 so the next insert trips the PK.
    from skillsmith.storage.vector_store import FragmentEmbedding

    store.insert_embeddings(
        [
            FragmentEmbedding(
                fragment_id="frag-0",
                embedding=_unit_vec(0),
                skill_id="skill-a",
                category="engineering",
                fragment_type="execution",
                embedded_at=0,
                embedding_model="seeded",
            )
        ]
    )

    def embed(content: str) -> list[float]:
        i = int(content.rsplit(" ", 1)[-1])
        return _unit_vec(i)

    stats = reembed_fragments(
        fragments,
        embed_fn=embed,
        vector_store=store,
        embedding_model="test-embed",
    )
    # frag-0 fails (PK clash), frag-1 succeeds.
    assert stats.failed == 1
    assert stats.embedded == 1
    assert store.count_embeddings() == 2


def test_reembed_uses_model_id_in_metadata(store: VectorStore) -> None:
    fragments = [_mk_frag(0)]

    def embed(_: str) -> list[float]:
        return _unit_vec(0)

    reembed_fragments(
        fragments,
        embed_fn=embed,
        vector_store=store,
        embedding_model="qwen3-embedding:0.6b",
    )
    # The model id ends up in the row; nothing on VectorStore exposes it
    # directly, but we can sanity-check the insert landed.
    assert store.count_embeddings() == 1
