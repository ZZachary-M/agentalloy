# Phase 6: Classifier Elimination

**Prerequisites:** Phase 3 complete (introduces `classifier.py` and the config fields being removed). Phases 4 and 5 are independent.

**Context:** Phase 3 introduced `src/skillsmith/signals/classifier.py` and a
`runtime_classifier_model` config field (`qwen3-1.7b-instruct`) backed by a
second llama-server instance on port 11436. This was never an explicit
architectural decision — the agent building Phase 3 picked it from a list of
options in the spec. After review, the approach conflicts with the token-economics
constraint: it adds a second model pull and a second server process for a job
that can be done with what is already running.

**Goal:** Remove the classifier model entirely. Replace the three
similarity-based semantic predicates with cosine similarity against built-in
reference phrase sets (reusing the existing embed server). Demote
`artifact_completeness` from a hard gate to a soft advisory injected into
Claude's next turn.

**Done means:** all acceptance criteria below pass, the Phase 3 integration
test still passes, and no configuration references `runtime_classifier_model`
or port 11436.

---

## Architectural decision

### Similarity-based predicates

`user_intent_matches`, `agent_intent_matches`, and `prompt_topic_matches` are
replaced with cosine similarity scoring against a small built-in reference
phrase set per named intent. The existing embed server (same base URL and model
as `runtime_embedding_model`) handles all calls — no new server, no new model.

Similarity threshold defaults to `0.75`. If no reference set exists for the
requested intent name, the predicate returns `UNKNOWN` (existing soft-fail
semantics preserved).

### `artifact_completeness` as soft advisory

`artifact_completeness` is removed as a hard gate. When encountered in a gate
spec during `evaluate-phase`, the evaluator:

1. Reads the artifact.
2. Emits a structured eval request to hook stdout alongside any other injected
   context, prefixed `[skillsmith-eval]`.
3. Returns `UNKNOWN` for the gate (does not block transition).

The eval request lands in Claude's next turn context. Claude's response is
advisory — it does not feed back into gate state. The structural predicates
(`artifact_exists`, `artifact_contains`, `artifact_size_min`) carry the hard
gate responsibility.

Gate authors should not use `artifact_completeness` as the sole exit criterion.
The spec should document this.

---

## Files to modify

| Path | What changes |
|---|---|
| `src/skillsmith/signals/classifier.py` | Replace chat-based classifier with similarity scorer; remove `lm_client.chat` calls |
| `src/skillsmith/config.py` | Remove `runtime_classifier_base_url` and `runtime_classifier_model` fields |
| `src/skillsmith/signals/gates.py` | Handle `artifact_completeness` as soft advisory (emit + return UNKNOWN) |
| `docs/build-sequence/03-signal-layer.md` | Note superseded by this doc for classifier model decision |
| `docs/signal-detection-and-domain-trigger-spec.md` | Update `artifact_completeness` predicate description; add note on advisory-only semantics |

## Files to delete

| Path | Reason |
|---|---|
| *(none)* | `classifier.py` is kept but gutted; deleting it would break imports in `gates.py` |

---

## Step-by-step

### Step 6.1 — Similarity scorer

**Modify** `src/skillsmith/signals/classifier.py`.

Replace the `_CLASSIFIER_PROMPT` and `_call_classifier` machinery with:

```python
import math

# Reference phrases per named intent. Extend as needed.
_INTENT_REFERENCES: dict[str, list[str]] = {
    "completion": [
        "done with spec", "ready to move on", "spec is complete",
        "finished", "that looks good", "good to go",
    ],
    "approval": [
        "looks good", "approve", "ship it", "lgtm", "approved",
    ],
    "redirection": [
        "let's change direction", "scratch that", "new approach",
        "start over", "different direction",
    ],
}

_SIMILARITY_THRESHOLD = 0.75
_MAX_INPUT_CHARS = 2000


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _intent_similarity(
    text: str,
    intent: str,
    lm_client: "OpenAICompatClient",
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
```

Update the four public predicate functions to call `_intent_similarity` (for
`user_intent_matches`, `agent_intent_matches`, `prompt_topic_matches`) and
return `UNKNOWN` unconditionally for `artifact_completeness` (gate handling
moves to `gates.py`).

The `lm_client` and `model` passed in should use `Settings().runtime_embedding_model`
and the embed base URL — same server already running.

**Acceptance criteria:**

- [ ] No `chat()` calls anywhere in `classifier.py`.
- [ ] `_intent_similarity` returns `UNKNOWN` (not raises) on embed failure.
- [ ] `artifact_completeness` predicate returns `UNKNOWN`.
- [ ] Unit tests updated: mock `lm_client.embed`, not `lm_client.chat`.

### Step 6.2 — Soft advisory emission in gates

**Modify** `src/skillsmith/signals/gates.py`.

When `evaluate_gates` encounters an `artifact_completeness` predicate:

1. Read the artifact at `args["path"]` (glob-resolve against `ctx.project_root`; take first match).
2. Format the advisory:
   ```
   [skillsmith-eval] Soft completeness check — does this artifact meet the bar?
   Criteria: {args["criteria"]}

   {artifact_content[:3000]}
   ```
3. Store the formatted string in a new field on `GateEvaluation`: `advisory: str | None`.
4. Return `UNKNOWN` for the gate result.

In `decide_transition`, collect all advisories from `GateEvaluation` objects and
return them in `PhaseTransitionDecision` as `advisories: list[str]`.

**Modify** `src/skillsmith/install/subcommands/signal.py` `evaluate-phase` handler:

After emitting the transition JSON, emit each advisory to stdout prefixed
`[skillsmith-eval]`. The harness injects this into Claude's next turn
alongside the workflow skill prose.

**Acceptance criteria:**

- [ ] `artifact_completeness` gate never blocks a transition.
- [ ] Advisory text appears in `evaluate-phase` stdout when the predicate is present.
- [ ] Advisory is omitted from stdout when no `artifact_completeness` gate exists.
- [ ] `test_gates.py`: assert advisory collected and UNKNOWN returned.

### Step 6.3 — Remove classifier config fields

**Modify** `src/skillsmith/config.py`.

Remove:
```python
runtime_classifier_base_url: str = "http://localhost:11436"
runtime_classifier_model: str = "qwen3-1.7b-instruct"
```

Callers of the classifier now pass the embed base URL and model. Update call
sites in `gates.py` accordingly.

**Acceptance criteria:**

- [ ] `grep -r runtime_classifier` finds no references in `src/`.
- [ ] `grep -r "11436"` finds no references in `src/` or `docs/build-sequence/`.
- [ ] `Settings()` instantiation in tests does not require classifier fields.

### Step 6.4 — Update spec docs

**Modify** `docs/signal-detection-and-domain-trigger-spec.md`:

- In the predicate vocabulary table, update `artifact_completeness` description
  to: "Advisory only. Emits a completeness eval request into the agent's next
  turn context. Does not block gate evaluation (returns UNKNOWN)."
- Add a note under the example gate: "Do not use `artifact_completeness` as the
  sole exit criterion — it never returns MET."

**Modify** `docs/build-sequence/03-signal-layer.md`:

Add a note at the top of Step 3.2:

> **Superseded by Phase 6 (06-classifier-elimination.md).** The classifier
> model approach described here was replaced after Phase 3 completed. The
> implementation uses cosine similarity via the embed server instead of a
> separate chat model. `artifact_completeness` is a soft advisory, not a hard
> gate. Do not re-introduce `runtime_classifier_model` or port 11436.

---

## Cross-cutting constraints (unchanged from index)

- Token economics: no paid-LLM cost introduced. The embed server was already
  running; adding similarity calls adds negligible latency.
- Soft-fail: embed failures return `UNKNOWN`, same as classifier timeout did.
- Telemetry: `qwen_calls` counter in `CompositionTrace` now counts embed calls
  made by the similarity scorer. Semantics unchanged.

---

## What is NOT changed

- The prefilter (`prefilter.py`) is untouched.
- Gate aggregation semantics (`all_of`, `any_of`, `not`) are unchanged.
- The `UNKNOWN` propagation rules are unchanged — `artifact_completeness`
  returning `UNKNOWN` already has well-defined behavior in `all_of`/`any_of`.
- The hook scripts and Claude Code wiring are unchanged.
