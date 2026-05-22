# Phase 3: Signal Layer

**Prerequisites:** Phase 2 complete. Read `docs/signal-detection-and-domain-trigger-spec.md` (especially the predicate vocabulary and hook events sections).

**Goal:** Hooks fire on UserPromptSubmit, PostToolUse, and PreToolUse.
Phase transitions evaluate declared gates (deterministic + semantic via
Qwen classifier) and update `.skillsmith/phase`. Contract writes trigger
automatic domain retrieval. System skills fire on tool-use applicability.
After this phase, Skillsmith routes context automatically without
paid-LLM decisions to call it.

**Done means:** all acceptance criteria below pass AND the integration
test passes on Claude Code (the reference Tier 1 binding).

## Files to create

| Path | Purpose |
|---|---|
| `src/skillsmith/signals/__init__.py` | Package init |
| `src/skillsmith/signals/predicates.py` | Deterministic predicate evaluators |
| `src/skillsmith/signals/classifier.py` | Qwen-based semantic predicate evaluator |
| `src/skillsmith/signals/gates.py` | Gate aggregation (all_of, any_of, not) and phase-transition decision |
| `src/skillsmith/signals/prefilter.py` | Cheap signal detection (keyword match, file events, tool events) |
| `src/skillsmith/install/subcommands/signal.py` | `skillsmith signal {evaluate-phase, evaluate-system, watch-contract}` |
| `tools/skillsmith-signal.sh` | Bash hook wrapper invoked by harness |
| `tests/test_predicates.py` | Per-predicate unit tests |
| `tests/test_gates.py` | Aggregation + decision tests |
| `tests/test_signal_cli.py` | CLI smoke tests |
| `tests/test_signal_e2e_claude_code.py` | End-to-end test with simulated Claude Code hook events |

## Files to modify

| Path | What changes |
|---|---|
| `src/skillsmith/_packs/sdd/sdd-*.yaml` | Add semantic gates (Phase 3 makes them callable) |
| `src/skillsmith/install/subcommands/wire_harness.py` | When wiring Claude Code, register UserPromptSubmit/PostToolUse/PreToolUse hooks |
| `src/skillsmith/storage/vector_store.py` | Extend `CompositionTrace` with signal-layer fields |
| `src/skillsmith/install/__main__.py` | Register `signal` subcommand |

## Step-by-step

### Step 3.1 — Deterministic predicate evaluators

**Create** `src/skillsmith/signals/predicates.py`.

Implement the 14 deterministic predicates from
`signal-detection-and-domain-trigger-spec.md` "Predicate vocabulary":

```python
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

class PredicateResult(Enum):
    MET = "met"
    NOT_MET = "not_met"
    UNKNOWN = "unknown"

@dataclass(frozen=True)
class PredicateContext:
    project_root: Path
    current_phase: str | None
    recent_prompt_text: str | None
    recent_tool_use: dict[str, Any] | None    # {tool: str, path: str | None, args: dict}
    file_events_since: list[Path]              # paths modified since last check
    contracts_root: Path                       # .skillsmith/contracts/

# Each predicate evaluator returns PredicateResult.
# Signature: (args: dict, ctx: PredicateContext) -> PredicateResult

def eval_artifact_exists(args, ctx) -> PredicateResult: ...
def eval_artifact_absent(args, ctx) -> PredicateResult: ...
def eval_artifact_contains(args, ctx) -> PredicateResult: ...
def eval_artifact_size_min(args, ctx) -> PredicateResult: ...
def eval_artifact_newer_than(args, ctx) -> PredicateResult: ...
def eval_phase_in(args, ctx) -> PredicateResult: ...
def eval_phase_not_in(args, ctx) -> PredicateResult: ...
def eval_tool_use_about_to_fire(args, ctx) -> PredicateResult: ...
def eval_tool_use_just_completed(args, ctx) -> PredicateResult: ...
def eval_git_state(args, ctx) -> PredicateResult: ...
def eval_contract_exists(args, ctx) -> PredicateResult: ...
def eval_contract_has_tags(args, ctx) -> PredicateResult: ...
def eval_file_type_active(args, ctx) -> PredicateResult: ...

PREDICATES: dict[str, Callable] = { ... }  # name → evaluator
```

Implementation notes:

- `artifact_contains` with `sections: [...]`: parse markdown headings (lines starting with `## `) and check named sections exist.
- `artifact_contains` with `pattern: <regex>`: compile and search. Use `re.MULTILINE`.
- `git_state` shells out to `git status --porcelain` once (cache in ctx if called multiple times in same gate eval).
- All file ops respect `project_root` (no absolute-path escapes).
- Predicates that reference paths outside the project root return `UNKNOWN`, not raise.

**Acceptance criteria:**

- [ ] All 14 predicates implemented with type hints.
- [ ] Unknown predicate name in args raises `ValueError` with available names listed.
- [ ] Predicates never raise on missing context fields; they return `UNKNOWN`.
- [ ] Predicates that read files use `try/except OSError` and degrade to `UNKNOWN` on read failure.

### Step 3.2 — Semantic predicate evaluator

> **Superseded by Phase 6 (06-classifier-elimination.md).** The classifier
> model approach described here was replaced after Phase 3 completed. The
> implementation uses cosine similarity via the embed server instead of a
> separate chat model. `artifact_completeness` is a soft advisory, not a hard
> gate. Do not re-introduce `runtime_classifier_model` or port 11436.

**Create** `src/skillsmith/signals/classifier.py`.

Four semantic predicates from the spec:

```python
def eval_user_intent_matches(args, ctx, lm_client) -> PredicateResult: ...
def eval_agent_intent_matches(args, ctx, lm_client) -> PredicateResult: ...
def eval_artifact_completeness(args, ctx, lm_client) -> PredicateResult: ...
def eval_prompt_topic_matches(args, ctx, lm_client) -> PredicateResult: ...
```

Each builds a constrained prompt for Qwen and parses a yes/no/unknown response. Use a small instruction template:

```
You are a classifier. Answer with one word: YES, NO, or UNKNOWN.

Criterion: {criterion}

Input:
{input_text}

Answer:
```

Use `OpenAICompatClient` (already in `lm_client.py`). Model: same Qwen3 embedding model is NOT a chat model. We need a small chat model. Two options:

1. **Reuse the existing maintainer authoring model** (`AuthoringConfig.authoring_model = "qwen3-14b-instruct"`) — too heavy for per-turn use; probably not on by default for users who only installed runtime.
2. **Add a runtime classifier model** as a new config field. Recommend: `qwen3-1.7b-instruct` or similar small chat model. Add to `Settings`:
   ```python
   runtime_classifier_base_url: str = "http://localhost:11436"  # may share embed server
   runtime_classifier_model: str = "qwen3-1.7b-instruct"
   ```

The classifier should:

- Timeout at 2 seconds per call (user said latency is fine, but bound it).
- On timeout or connection error: return `UNKNOWN`.
- Log every call to telemetry (`qwen_calls` counter).
- Trim input text to ~2000 chars to keep prompts small.

**Acceptance criteria:**

- [ ] All four semantic predicates implemented.
- [ ] Classifier failure (model unavailable, timeout, malformed response) → `UNKNOWN`, never raises.
- [ ] Telemetry counts every classifier invocation.
- [ ] A unit test with a mocked `lm_client` covers each predicate.

### Step 3.3 — Gate aggregation + transition decision

**Create** `src/skillsmith/signals/gates.py`.

```python
@dataclass(frozen=True)
class GateEvaluation:
    gate_name: str
    result: PredicateResult
    detail: str  # for telemetry / debugging

@dataclass(frozen=True)
class PhaseTransitionDecision:
    should_transition: bool
    from_phase: str
    to_phase: str | None     # None if can't determine target
    gates_met: list[GateEvaluation]
    gates_unmet: list[GateEvaluation]
    qwen_calls: int

def evaluate_gates(
    gate_spec: dict,       # the exit_gates field from a workflow skill
    ctx: PredicateContext,
    lm_client,
) -> list[GateEvaluation]: ...

def aggregate(
    operator: str,         # "all_of" | "any_of" | "not"
    children: list[PredicateResult | "AggregateResult"],
) -> PredicateResult: ...

def decide_transition(
    current_phase: str,
    workflow_skill: WorkflowSkill,    # loaded from datastore
    ctx: PredicateContext,
    lm_client,
    next_phase_hint: str | None = None,  # if known; else inferred from phase graph
) -> PhaseTransitionDecision: ...
```

Aggregation semantics:

- `all_of`: every child must be `MET`. Any `NOT_MET` → `NOT_MET`. Any `UNKNOWN` (no `NOT_MET`) → `UNKNOWN`.
- `any_of`: at least one `MET` → `MET`. All `NOT_MET` → `NOT_MET`. Otherwise → `UNKNOWN`.
- `not`: invert (`MET` ↔ `NOT_MET`; `UNKNOWN` stays `UNKNOWN`).

**For `decide_transition`**: only transition when aggregate is `MET`. `UNKNOWN` and `NOT_MET` both leave phase as-is. The `next_phase` is determined by a hardcoded SDD phase graph for now (spec → design → build → qa → ship); make it configurable later.

**Acceptance criteria:**

- [ ] Aggregation correctly handles `UNKNOWN` in all-of/any_of/not.
- [ ] `decide_transition` returns telemetry-friendly detail per gate.
- [ ] Phase graph is a simple ordered list in code; document at top of file.

### Step 3.4 — Pre-filter logic

**Create** `src/skillsmith/signals/prefilter.py`.

```python
@dataclass(frozen=True)
class PreFilterMatch:
    name: str    # "prompt_keyword" | "artifact_event" | "tool_use_event" | "manual"
    detail: str  # which keyword, which path, which tool

def check_prefilter(
    workflow_skill: WorkflowSkill,
    ctx: PredicateContext,
) -> PreFilterMatch | None:
    """Return the first matching pre-filter or None."""
```

Implementation:

- Check `workflow_skill.signal_keywords` against `ctx.recent_prompt_text` (case-insensitive substring match).
- Check whether any `artifact_exists` / `artifact_contains` path glob in the gates intersects `ctx.file_events_since`.
- Check whether `ctx.recent_tool_use` matches any `tool_use_*` predicate's tools.
- Check for the manual check sentinel (user typed `/skillsmith phase check` — surface this via env var `SKILLSMITH_FORCE_CHECK=1`).

If none match → return None → skip gate evaluation entirely (most common case).

**Acceptance criteria:**

- [ ] Empty `recent_prompt_text` + no file events + no tool use → `None`.
- [ ] Each pre-filter type tested with both matching and non-matching inputs.
- [ ] Pre-filter check completes in <5ms in the common case.

### Step 3.5 — `skillsmith signal` subcommand

**Create** `src/skillsmith/install/subcommands/signal.py`.

| Command | Purpose |
|---|---|
| `skillsmith signal evaluate-phase [--prompt-file PATH] [--tool TOOL --tool-path PATH]` | Run pre-filter + gate evaluation for the active phase. Writes new phase to `.skillsmith/phase` on transition. Emits JSON to stdout. |
| `skillsmith signal evaluate-system --tool TOOL` | Find system skills whose `applies_when` matches; for each match, emit its prose body. Used by PreToolUse hook. |
| `skillsmith signal watch-contract --path PATH` | Validate the contract; on success, invoke `skillsmith compose --contract <path>` and emit its output. Used by PostToolUse hook. |
| `skillsmith signal check --json` | Diagnostics: dump current phase, active workflow skill, last pre-filter, last gate evaluation result. For debugging. |

`evaluate-phase` flow:

1. Load `.skillsmith/phase` and the corresponding workflow skill from the profile's datastore.
2. Build `PredicateContext` from inputs (prompt text from stdin or `--prompt-file`).
3. Call `check_prefilter`. If `None`, exit 0 with `{matched: false}`.
4. Call `decide_transition`.
5. If `should_transition`: write new phase atomically; emit `{transition: true, from: ..., to: ...}`; write the new workflow skill's prose to stdout (prefixed `[skillsmith-workflow]`) so the harness can inject it.
6. If not: emit `{transition: false, gates_unmet: [...]}` (no stdout to harness).

**Atomic write**: write to `.skillsmith/phase.tmp` and rename.

**Acceptance criteria:**

- [ ] All four subcommands implemented.
- [ ] `evaluate-phase` is idempotent: running twice with same inputs doesn't double-transition.
- [ ] Phase file writes are atomic (no partial files visible).
- [ ] Soft-fail: every error path exits 0 with structured stderr; never blocks the hook.

### Step 3.6 — Bash hook wrapper

**Create** `tools/skillsmith-signal.sh`.

```bash
#!/usr/bin/env bash
# Skillsmith signal-layer hook. Routed by SKILLSMITH_HOOK_EVENT env var.
# Soft-fails — always exits 0.
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$SCRIPT_DIR"
while [[ "$ROOT" != "/" && ! -d "$ROOT/.git" ]]; do
    ROOT="$(dirname "$ROOT")"
done
cd "$ROOT" 2>/dev/null || exit 0

EVENT="${SKILLSMITH_HOOK_EVENT:-UserPromptSubmit}"

case "$EVENT" in
    UserPromptSubmit)
        skillsmith signal evaluate-phase \
            --prompt-file "${CLAUDE_PROMPT_FILE:-/dev/null}" 2>/dev/null || true
        ;;
    PostToolUse)
        TOOL="${SKILLSMITH_TOOL_NAME:-}"
        PATH_ARG="${SKILLSMITH_TOOL_PATH:-}"
        # Only fire on writes inside .skillsmith/contracts/
        if [[ "$TOOL" =~ ^(Edit|Write|MultiEdit)$ ]] \
           && [[ "$PATH_ARG" == *".skillsmith/contracts/"* ]]; then
            skillsmith signal watch-contract --path "$PATH_ARG" 2>/dev/null || true
        fi
        ;;
    PreToolUse)
        TOOL="${SKILLSMITH_TOOL_NAME:-}"
        skillsmith signal evaluate-system --tool "$TOOL" 2>/dev/null || true
        ;;
esac

exit 0
```

**Acceptance criteria:**

- [ ] Script is executable (`chmod +x tools/skillsmith-signal.sh`).
- [ ] Each event branch tested via integration test (Step 3.8).
- [ ] Self-locates project root from any working directory.
- [ ] Stderr suppression preserves the soft-fail contract.

### Step 3.7 — Wire Claude Code hooks during `wire-harness`

**Modify** `src/skillsmith/install/subcommands/wire_harness.py`.

When wiring Claude Code (one of `VALID_HARNESSES`), additionally write three hook registrations to `.claude/settings.json`:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "matcher": "",
        "hooks": [
          { "type": "command", "command": "SKILLSMITH_HOOK_EVENT=UserPromptSubmit bash <SKILLSMITH_HOOK_PATH>" }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Edit|Write|MultiEdit",
        "hooks": [
          { "type": "command", "command": "SKILLSMITH_HOOK_EVENT=PostToolUse SKILLSMITH_TOOL_NAME=$CLAUDE_TOOL_NAME SKILLSMITH_TOOL_PATH=$CLAUDE_TOOL_PATH bash <SKILLSMITH_HOOK_PATH>" }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": ".*",
        "hooks": [
          { "type": "command", "command": "SKILLSMITH_HOOK_EVENT=PreToolUse SKILLSMITH_TOOL_NAME=$CLAUDE_TOOL_NAME bash <SKILLSMITH_HOOK_PATH>" }
        ]
      }
    ]
  }
}
```

`<SKILLSMITH_HOOK_PATH>` resolves to the installed location of `tools/skillsmith-signal.sh`. Use `pkg_resources` or `importlib.resources` to locate it; copy to `~/.skillsmith/hooks/skillsmith-signal.sh` during wire.

**Variable substitution**: verify the actual Claude Code env vars before shipping. Today's hooks expose `$CLAUDE_TOOL_NAME` and possibly `$CLAUDE_TOOL_PATH` — confirm against current Claude Code docs before locking in.

If `.claude/settings.json` already has hooks, merge rather than overwrite. Use marker-comment blocks or a structured merge.

**Acceptance criteria:**

- [ ] `skillsmith wire claude-code` writes all three hook entries.
- [ ] Existing user hooks in `settings.json` preserved.
- [ ] `skillsmith unwire claude-code` removes Skillsmith hooks specifically.
- [ ] Hook command lines correctly export `SKILLSMITH_HOOK_EVENT` so the wrapper routes properly.

### Step 3.8 — Extend telemetry for signal events

**Modify** `src/skillsmith/storage/vector_store.py` `CompositionTrace`:

```python
event_type: str = "compose"  # "compose" | "phase_eval" | "phase_transition" | "system_skill_applied" | "contract_retrieval"
pre_filter_matched: str | None = None
gates_met: list[str] = field(default_factory=list)
gates_unmet: list[str] = field(default_factory=list)
qwen_calls: int = 0
```

`skillsmith signal` writes telemetry on every invocation, even no-op pre-filter misses (so we can analyze pre-filter selectivity post-hoc).

**Acceptance criteria:**

- [ ] All five event types emit telemetry.
- [ ] Pre-filter misses are recorded (`event_type=phase_eval, pre_filter_matched=null`).
- [ ] `qwen_calls` is an accurate count per evaluation.

## Tests to add

`tests/test_predicates.py`:

- Per-predicate tests with crafted contexts.
- `test_artifact_contains_named_sections` — markdown parsing correctness.
- `test_git_state_caching` — multiple calls in same eval don't re-shell-out.
- `test_predicate_returns_unknown_on_io_error` — soft-fail.

`tests/test_gates.py`:

- `test_all_of_short_circuit_on_not_met` — early exit
- `test_any_of_short_circuit_on_met` — early exit
- `test_unknown_propagates_correctly` — all_of with UNKNOWN+MET → UNKNOWN; any_of with UNKNOWN+NOT_MET → UNKNOWN
- `test_nested_aggregates` — `all_of: [any_of: [...], not: [...]]`
- `test_decide_transition_writes_phase_atomically` — temp file approach

`tests/test_signal_cli.py`:

- `test_evaluate_phase_no_prefilter_match_exit_0` — common path
- `test_evaluate_phase_transition_writes_workflow_skill_to_stdout` — happy path
- `test_evaluate_system_emits_matching_skill_bodies` — predicate match
- `test_watch_contract_invokes_compose` — happy path (mocked service)

`tests/test_signal_e2e_claude_code.py`:

- Simulate the three hook events with crafted env vars and assert correct CLI was invoked + correct output emitted.

## Phase 3 integration test

**Goal:** verify the full pull-side architecture in Claude Code.

Manual or scripted scenario:

1. With Phases 1+2 complete, run `skillsmith wire claude-code` in a test repo.
2. Confirm `.claude/settings.json` has all three hooks.
3. Start a Claude Code session in the repo.
4. Set `.skillsmith/phase` to `spec`.
5. Prompt Claude: "Let's spec a new auth feature." Expected: workflow skill prose for spec phase already in context (from previous turn's evaluate-phase output). No transition.
6. Have Claude write `docs/spec/auth.md` with the required sections per the spec workflow skill's gates.
7. Prompt: "Done with spec, ready to design." Expected: hook fires evaluate-phase → pre-filter matches `signal_keywords` → gates evaluate (deterministic artifact_exists + artifact_contains MET; semantic user_intent_matches MET) → transition writes `.skillsmith/phase` to `design` → workflow skill for design phase is emitted to stdout.
8. Next prompt: confirm design workflow skill appears in Claude's context.
9. Have Claude write a contract `.skillsmith/contracts/design/auth-architecture.md`.
10. PostToolUse hook fires → `skillsmith signal watch-contract` → `compose --contract` → fragments injected.
11. Inspect telemetry. Assert: 1 `phase_transition`, ≥1 `contract_retrieval`, several `phase_eval` (no-transition).
12. Have Claude attempt `git commit`. PreToolUse fires → `skillsmith signal evaluate-system --tool "git commit"` → commit-safety system skill (if installed) emits its prose.

If all 12 steps pass, Phase 3 is complete.

## Known gotchas

- **Classifier model** isn't on most users' machines today. Decide: do we install it during `setup`, or is it opt-in? Recommend: opt-in (`skillsmith setup --enable-classifier`). Without it, semantic predicates return `UNKNOWN` and gates fall back to deterministic-only behavior — which is degraded but workable.
- **Claude Code hook env-var names** may differ from `$CLAUDE_TOOL_NAME`. Verify current docs before shipping. The hook contract has been evolving; pin to a specific Claude Code version in the README.
- **`PreToolUse` for system skills can fire frequently** (every tool use). Cache results per-session to avoid evaluating the same applies_when twice when the same tool fires repeatedly.
- **Atomic phase write** matters because hooks can fire concurrently in edge cases (rare; mostly when the user pastes a multi-prompt). Use rename, not in-place truncate-and-write.
- **Workflow skill prose emission**: when phase transitions, the new workflow skill needs to actually reach the LLM's next turn. Mechanism is "hook stdout becomes injected context" in Claude Code's `UserPromptSubmit`. Verify by reading the new workflow skill's first sentence appears in the model's context on the very next prompt.
