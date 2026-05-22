# Signal Detection and Domain Trigger

**Status:** Proposed
**Depends on:** `docs/skill-authoring-and-overrides-spec.md`, `docs/qwen-runtime-role-findings.md`
**Companion:** `docs/sdd-context-remind-hook-spec.md` (reminder = push;
this spec = pull)

## What this spec covers

The mechanisms that make Skillsmith fire **automatically**, at the right
moments, without burning paid-LLM tokens on routing decisions:

1. **Phase gate evaluation** — sticky phase state, transition-detected by
   cheap pre-filters + a small Qwen classifier against declared gates.
2. **Domain retrieval trigger** — purely deterministic, fired by the
   paid LLM writing a *task contract* under the active workflow skill's
   instructions.

Together these eliminate two paid-LLM cognitive burdens: "what phase am
I in?" and "should I call Skillsmith for skills now?" The paid LLM does
its actual work (write the spec, write the code) and the system around
it routes context.

## Architectural shape

```
                    ┌──────────────────────────────────────────────┐
                    │   paid LLM (Claude / harness)                │
                    └────────┬──────────────────────────┬──────────┘
                             │                          │
                  writes contract                executes workflow
                  per phase task                 skill instructions
                             │                          │
                             ▼                          ▼
                  ┌──────────────────────┐    ┌──────────────────────┐
                  │ .skillsmith/         │    │ .skillsmith/phase    │
                  │  contracts/          │    │ (sticky)             │
                  │   <phase>/<slug>.md  │    │                      │
                  └──────────┬───────────┘    └─────────┬────────────┘
                             │                          │
                file-write event              prompt/file pre-filter
                             │                          │
                             ▼                          ▼
                  ┌──────────────────────┐    ┌──────────────────────┐
                  │ DOMAIN TRIGGER       │    │ PHASE GATE EVAL      │
                  │ (deterministic)      │    │ Python predicates +  │
                  │ → /compose           │    │ Qwen classifier      │
                  └──────────┬───────────┘    └─────────┬────────────┘
                             │                          │
                  injected fragments         transition? → write phase
                             │                          │
                             ▼                          ▼
                       paid LLM context           workflow skill
                       (Tier 1/3 binding)         swapped on next turn
```

Two artifacts (`.skillsmith/phase`, `.skillsmith/contracts/...`) drive
everything. No sticky domain state — domain retrieval is stateless per
contract.

## The contract artifact

The contract is the paid LLM's structured statement of intent for a task.
It's written *by the paid LLM* under instructions injected via the active
workflow skill. Skillsmith consumes it deterministically.

### Location and naming

```
<project>/.skillsmith/contracts/<phase>/<task-slug>.md
```

- One file per task. Per-task lifecycle.
- `<phase>` matches the value of `.skillsmith/phase` at write time.
- `<task-slug>` is a kebab-case identifier the paid LLM chooses
  (workflow skill instructs format).

### Schema

```markdown
---
# REQUIRED
phase: build
task_slug: add-auth-middleware
domain_tags:
  - "NestJS"
  - "Express middleware"
  - "JWT validation"

# RECOMMENDED
scope:
  touches:
    - "src/auth/**"
    - "tests/auth/**"
  avoids:
    - "src/billing/**"
success_criteria:
  - "Existing auth tests still pass"
  - "Middleware tested with valid + invalid tokens"

# OPTIONAL
related_contracts:
  - ".skillsmith/contracts/design/auth-architecture.md"
created_at: 2026-05-21T14:32:11Z
---

# Add Auth Middleware

<task description prose; what the LLM intends to do and why>
```

| Field | Required | Used by |
|---|---|---|
| `phase` | yes | Sanity check (must match `.skillsmith/phase`) |
| `task_slug` | yes | Identifier; logs |
| `domain_tags` | yes | **BM25 input for retrieval** (the load-bearing field) |
| `scope.touches` | recommended | Phase gate predicates can reference |
| `scope.avoids` | recommended | Surfaced in reminder context if `code-indexer` is also wired |
| `success_criteria` | recommended | Gate predicates can semantically check artifacts against these |
| `related_contracts` | optional | Linkage for multi-task workflows |
| `created_at` | optional | Diagnostics; falls back to file mtime |

### Validation

A `skillsmith contract validate <path>` CLI lints the frontmatter. The
workflow skill instructs the paid LLM to write a contract and to call
this validator before proceeding. Validation failures result in the
workflow skill telling the LLM to fix the contract; no Skillsmith side
effects fire until the contract is valid.

### Why per-task and not per-phase

A phase is too coarse — a single SDD `build` phase usually spans many
tasks with different domain needs (one task touches the auth layer,
another touches billing). Per-task contracts let domain retrieval be
surgical *within* a phase without forcing artificial phase boundaries.

## Domain retrieval trigger

### Flow

1. Paid LLM writes (or updates) `<project>/.skillsmith/contracts/<phase>/<slug>.md`.
2. Hook event detects the file write (see "Hook events" below).
3. Hook validates the contract; on failure, emits a `[skillsmith] WARNING` and exits.
4. Hook invokes `skillsmith compose --contract <path>`.
5. Compose returns assembled fragments.
6. Hook injects the output into the paid LLM's next turn via the active
   binding (Tier 1: stdout to harness; Tier 3: marker-replaced block).

### Retrieval pipeline modification

`retrieval/domain.py:227` is modified to prefer contract tags as BM25 input:

```python
# Pseudocode for the change:
if contract_tags := req.contract_tags:
    bm25_query = " ".join(contract_tags)
    if SKILLSMITH_UNION_KEYWORDS:  # opt-in via env
        bm25_query += " " + _extract_bm25_keywords(task)
else:
    bm25_query = _extract_bm25_keywords(task)  # existing behavior
```

The dense (semantic) leg continues to embed the task description with
the Qwen3 instruct template. Phase-specific RRF weights still apply.
Diversity rerank still applies. Assembly stays deterministic Python.

Net: **no new Qwen jobs for domain retrieval**. The tags ride free into
the existing BM25 hybrid.

### Per-turn behavior within a task

Once a contract exists and fragments have been injected, *subsequent
turns within the same task do not re-fire retrieval* — the contract is
unchanged, the file event doesn't fire. The paid LLM keeps the original
fragments in its context until either:

- The contract is updated (scope shift mid-task) → re-retrieve.
- A new contract is written (new task) → retrieve for new task.
- Phase transitions → workflow skill swaps; existing contracts in the
  old phase become inert.

This matches the user-stated behavior: "Some turns won't change scope;
when they do, we return fragments pertinent to that turn." Old skills
lingering in paid context is acceptable — new fragments work on their
own merit.

## Phase gate evaluation

### Flow

```
UserPromptSubmit fires
  ↓
gather signals: user prompt text, recent file events, recent tool uses
  ↓
read .skillsmith/phase → current_phase
  ↓
pre-filter: any cheap signal matches a transition pattern?
  ├─ no  → no Qwen invocation; emit reminder if applicable; exit 0
  └─ yes ↓
  ↓
load active workflow skill from datastore → exit_gates declaration
  ↓
evaluate each gate:
  ├─ deterministic predicate → Python (artifact_exists, file_contains, etc.)
  └─ semantic predicate     → Qwen classifier (gate_met / not_met / unknown)
  ↓
aggregate: all gates met?
  ├─ no  → leave phase as-is; log unmet gates
  └─ yes → write new phase to .skillsmith/phase; log transition
  ↓
on transition: next prompt's hook injects the new phase's workflow skill
```

### Pre-filters (cheap, Python-only)

These don't decide transitions — they decide whether to *run* the
classifier. Pre-filter hits run gate evaluation; pre-filter misses skip
it entirely.

| Pre-filter | What triggers it |
|---|---|
| `prompt_keyword_match` | User prompt contains any phase's `signal_keywords` |
| `artifact_event` | File matching a phase's gate `artifact_exists` path was written/modified since last hook fire |
| `tool_use_event` | A tracked tool (git commit, deploy, etc.) just completed |
| `manual_check` | User typed `/skillsmith phase check` or equivalent |

If none fire, Qwen is not invoked. This is the normal case.

### Predicate vocabulary

Workflow skills declare `exit_gates` and system skills declare
`applies_when` using predicates from this list. Predicates are evaluated
in the order declared; short-circuit on first failure for `all_of` and
first success for `any_of`.

#### Deterministic predicates (Python-only)

| Predicate | Args | Meaning |
|---|---|---|
| `artifact_exists` | `path: <glob>` | File or directory at glob exists |
| `artifact_absent` | `path: <glob>` | Nothing matches the glob |
| `artifact_contains` | `path: <glob>`, `sections: [...]` | Markdown file has named `## sections` |
| `artifact_contains` | `path: <glob>`, `pattern: <regex>` | File contents match regex |
| `artifact_size_min` | `path: <glob>`, `bytes: <int>` | Non-trivial content (catches empty stubs) |
| `artifact_newer_than` | `path: <glob>`, `since: <path>` | Artifact mtime > marker file mtime |
| `phase_in` | `phases: [...]` | Current phase is in the list |
| `phase_not_in` | `phases: [...]` | Current phase is not in the list |
| `tool_use_about_to_fire` | `tools: [...]` | PreToolUse event for any listed tool |
| `tool_use_just_completed` | `tools: [...]` | PostToolUse event for any listed tool |
| `git_state` | `has_staged: <bool>`, `has_uncommitted: <bool>`, `branch_matches: <regex>` | Git status snapshot |
| `contract_exists` | `phase: <name>`, `count_min: <int>` | At least N contracts for the named phase |
| `contract_has_tags` | `phase: <name>`, `any_of: [...]` | A contract in the phase has any of these tags |
| `file_type_active` | `extensions: [...]` | Most recently edited file matches an extension |

#### Semantic predicates (Qwen classifier)

These invoke a single Qwen yes/no/unknown call per evaluation. The
classifier receives the predicate's prose criterion + the relevant
artifact or prompt text + returns one of three labels.

| Predicate | Args | Meaning |
|---|---|---|
| `user_intent_matches` | `intent: <name>` | User's recent prompt indicates a named intent (e.g. `"completion"`, `"approval"`, `"redirection"`) |
| `agent_intent_matches` | `intent: <name>` | Last agent response indicates a named intent |
| `artifact_completeness` | `path: <glob>`, `criteria: <prose>` | Advisory only. Emits a completeness eval request into the agent's next turn context. Does not block gate evaluation (returns UNKNOWN). Do not use as the sole exit criterion — it never returns MET. |
| `prompt_topic_matches` | `topics: [...]` | Recent prompt is on-topic for any listed topic (fallback if no contract is present) |

#### Composition operators

| Operator | Args | Meaning |
|---|---|---|
| `all_of` | list of predicates | All must pass |
| `any_of` | list of predicates | At least one must pass |
| `not` | single predicate | Negation |

### Example: workflow skill exit gates

```yaml
# inside sdd-spec.md frontmatter
exit_gates:
  all_of:
    - artifact_exists:
        path: "docs/spec/*.md"
    - artifact_contains:
        path: "docs/spec/*.md"
        sections: ["Acceptance Criteria", "Out of Scope"]
    - artifact_size_min:
        path: "docs/spec/*.md"
        bytes: 800
    - any_of:
        - user_intent_matches:
            intent: "completion"
        - artifact_completeness:  # advisory only — never returns MET; emits eval request into next turn
            path: "docs/spec/*.md"
            criteria: "Every acceptance criterion is independently testable and unambiguous."
```

Reads as: spec phase exits when a non-trivial spec doc exists with the
required sections, AND the user signaled completion. The `artifact_completeness`
arm never returns MET — it emits a soft eval advisory into Claude's next turn
context but does not contribute to gate satisfaction. Do not use it as the
sole exit criterion.

### Example: system skill applies_when

```yaml
# inside commit-safety.md frontmatter
applies_when:
  all_of:
    - tool_use_about_to_fire:
        tools: ["git commit", "git push"]
    - phase_in:
        phases: ["build", "qa"]
    - any_of:
        - git_state:
            has_uncommitted: true
        - file_type_active:
            extensions: [".env", ".secrets"]
```

Reads as: commit-safety system skill applies before commit/push in
build/qa phases when there's uncommitted state OR secret-shaped files
are active.

## Hook events used

Three hook events power the signal layer. Tier 1 harnesses (Claude
Code, Continue.dev, Hermes/SDK) support all three. Tier 3 harnesses
get reduced functionality (see fallbacks below).

| Hook event | Purpose | Tier 1 mechanism | Tier 3 fallback |
|---|---|---|---|
| `UserPromptSubmit` | Phase gate eval pre-filters; reminder injection | Native hook | Nothing — rules file is static |
| `PostToolUse` (on Edit/Write) | Contract-write detection; artifact event tracking | Filter on tool name + path | File-system watcher sidecar |
| `PreToolUse` | System skill applicability (commit-safety, etc.) | Native hook | Not available — system skills become advisory only |

### Bash hook script: `tools/skillsmith-signal.sh`

```bash
#!/usr/bin/env bash
# Skillsmith signal-layer hook. Soft-fails — never blocks. Bounded.
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
        if [[ "$TOOL" =~ ^(Edit|Write|MultiEdit)$ ]] && [[ "$PATH_ARG" == *".skillsmith/contracts/"* ]]; then
            skillsmith compose --contract "$PATH_ARG" --inject 2>/dev/null || true
        fi
        ;;
    PreToolUse)
        TOOL="${SKILLSMITH_TOOL_NAME:-}"
        skillsmith signal evaluate-system --tool "$TOOL" 2>/dev/null || true
        ;;
esac

exit 0
```

`skillsmith signal evaluate-phase`, `skillsmith signal evaluate-system`,
and `skillsmith compose --contract ... --inject` are the three CLI
entrypoints the signal layer adds. All write structured output to
stdout (which the harness binding routes to the model's context).

### Tier 3 fallback for contract-driven retrieval

Tier 3 harnesses (Cursor, Windsurf, Copilot, Cline, Gemini CLI, Aider)
can't use `PostToolUse`. Two options:

1. **File-system watcher sidecar** (`skillsmith watch`) — a long-running
   process that monitors `.skillsmith/contracts/**` for writes and updates
   the harness's rules file via the marker-block pattern. Adds a process
   to manage but recovers full functionality.
2. **Manual** — the paid LLM is instructed (by the workflow skill) to
   run `skillsmith compose --contract <path>` explicitly via the
   harness's shell-out facility (`/run`, terminal, etc.) after writing
   a contract. Lower fidelity but no sidecar.

For Tier 3, prefer the sidecar where the user is willing to run it;
fall back to manual otherwise.

## Telemetry

Every phase transition, gate evaluation (including not-transitioned),
and contract-driven retrieval writes a structured record to
`composition_traces` (existing telemetry table). New fields:

- `event_type`: `phase_eval`, `phase_transition`, `contract_retrieval`,
  `system_skill_applied`
- `pre_filter_matched`: which pre-filter fired (for phase_eval)
- `gates_met` / `gates_unmet`: lists for phase_eval
- `qwen_calls`: count of semantic predicate evaluations
- `contract_path`: for contract_retrieval

Purpose: post-hoc tuning of pre-filters and predicate thresholds, and
detecting when Qwen is being called more often than necessary.

## Failure modes

| Failure | Behavior |
|---|---|
| Qwen unavailable for a semantic predicate | Predicate returns `unknown`; treated as `not_met` for `all_of` (conservative) and skipped for `any_of` |
| Contract malformed | Hook emits `[skillsmith] WARNING: contract <path> failed validation: <reason>`; no retrieval fires |
| `.skillsmith/phase` missing | All phase predicates skipped; reminder still fires; no transitions possible |
| Workflow skill in datastore is missing `exit_gates` | Should have been caught at `author update` validation; runtime logs error, treats as `no transitions possible from this phase` |
| Pre-filter fires every turn (false-positive flood) | Telemetry surfaces it; author tunes `signal_keywords` to be more specific |
| Hook script itself errors | `2>/dev/null || true` ensures exit 0; user gets no signal-layer behavior but harness is unblocked |

## Out of scope (deferred)

- **Multi-project shared state** — e.g., a single contract referenced from multiple repos. Not currently needed.
- **Predicate plug-ins** — third-party-authored predicate types. Vocabulary above is closed for v1.
- **Phase-graph awareness** — the spec assumes linear phase progression (spec → design → build → qa). Cyclic or branching phase graphs are a future concern.
- **Cross-tool signals** — e.g., a Knowledge-Decision indexer reporting a decision that should trigger a phase transition. Future integration.

## Design decisions

**Why pre-filter + classifier instead of "always run classifier"?**
Qwen invocations are cheap but not free. Most turns are mid-task and
have no transition signal. Pre-filters cut classifier invocations from
"every turn" to "turns with plausible signal" — usually single digits
per session.

**Why not have Qwen do "what phase are we in" classification?**
Stateless classification of phase from a single prompt is brittle. State
lives in the lock file. Qwen's job is *transition* detection against
declared gates — a yes/no/unknown decision, well-suited to a small model.

**Why is the contract written by the paid LLM, not by a tool?**
The paid LLM is already reasoning about the task; capturing its
intent as a contract is near-free. The alternative (tool-extracted
contracts from prompt text) would require a separate model pass that
duplicates what the paid LLM already does in its head.

**Why does the contract use `domain_tags` as BM25 input rather than embedding the tags?**
The existing hybrid retrieval already does the matching work. Tags are
high-quality keyword candidates by construction (the paid LLM picks
them deliberately). Routing them to the BM25 leg matches their shape;
embedding them would add Qwen calls without adding signal that the
dense leg doesn't already get from the task description.

**Why semantic predicates at all? Can't everything be deterministic?**
"User indicated completion" and "spec is well-formed" are inherently
fuzzy. Forcing them to deterministic predicates either over-constrains
authors (every workflow needs a `## Done` marker) or under-captures
signal. A bounded Qwen call here costs ~200ms and is exactly the
asymmetric-compute trade we want.

**Why bound Tier 3 harnesses at "advisory" for system skills?**
Tier 3 has no `PreToolUse` equivalent. System skills like commit-safety
exist *to gate tool use*. Without the gate event, the best we can do is
include the system skill's text in the rules file ambiently, which the
paid LLM may or may not honor. Not great, but not a regression — Tier 3
users already accept reduced-fidelity behavior across the architecture.

**Why is per-turn state minimal?**
Two artifacts (`phase`, `contracts/`). No "active domain set," no
"last-fired gate," no "speculative retrieval cache." Statelessness keeps
the system debuggable: behavior at any moment is a function of two files
on disk plus the current prompt.
