# Skillsmith Build Sequence — Index

**Status:** Phases 1–5 complete. Phase 6 in progress.
**Audience:** LLM coding agent (or human) implementing the architecture defined in the spec set
**Date:** 2026-05-22

This is the master index for the build sequence that implements the
profile/contract/signal architecture across five phases. Each phase has
its own detailed doc with concrete file paths, function signatures, and
acceptance criteria.

## How to use this document set

1. Read this index in full.
2. Read the spec set referenced under "Source specs" to internalize the architecture.
3. Execute phases in order — each phase has dependencies on prior phases.
4. Within a phase, execute steps in order unless explicitly marked parallel-safe.
5. Mark each step's acceptance criteria as you go; don't advance until met.
6. Each phase doc ends with an integration test that verifies the phase is complete.

## Source specs (load before executing)

| Doc | What it defines |
|---|---|
| `docs/skill-authoring-and-overrides-spec.md` | Profiles, three-layer overrides, authoring CLI surface, datastore layout |
| `docs/signal-detection-and-domain-trigger-spec.md` | Contract artifact, predicate vocabulary, hook events, retrieval modification |
| `docs/qwen-runtime-role-findings.md` | Verified architectural facts about what Qwen does today (load-bearing constraints) |

The three reminder docs in `docs/` are **SUPERSEDED** (see headers).
The tier model, harness composition story, and binding patterns in them
still inform Phases 3–5; the reminder script itself is not built.

## Predecessor work (must land before Phase 1)

| Doc | What it defines | Status |
|---|---|---|
| `SETUP_WIZARD_UX_SPEC.md` (repo root) | UX overhaul + bug-fix cluster for `simple_setup.py` (numbered menus, hardware label map, runner-sentinel fix, flow reorder) | Must land before Phase 1 Step 1.5 — line references in that spec assume the pre-refactor wizard state |

Phase 1 layers profile-awareness on top of the cleaned-up wizard. Reverse
order is feasible but makes the SETUP_WIZARD diff much harder to review.

## Phase order and dependencies

```
Phase 1: Foundation              ←── prerequisite for all
   profiles, datastore-per-profile
   skillsmith setup/update/reset (refactored)
   skillsmith customize CLI
       │
       ▼
Phase 2: Contracts                ←── needs Phase 1 (workflow skills live in profile datastore)
   contract artifact + validator
   workflow-skill schema additions (exit_gates, applies_to_phases, contract template prose)
   retrieval BM25 modification (consume domain_tags)
       │
       ▼
Phase 3: Signal Layer             ←── needs Phase 2 (contracts trigger retrieval; gates evaluate against workflow skills)
   predicate evaluator (deterministic + semantic)
   skillsmith signal CLI
   hook scripts (UserPromptSubmit, PreToolUse, PostToolUse)
   Claude Code wiring as reference Tier 1 binding
       │
       ▼
Phase 4: Code-Indexer Integration ←── needs Phase 2 (contracts), Phase 3 (hooks)
   workflow skill prose update: instruct paid LLM to call code-indexer with scope
   code-indexer scope-filter verification
   end-to-end loop test
       │
       ▼
Phase 5: Tier 3 Hardening         ←── needs Phase 3 (hooks); independent of Phase 4
   skillsmith watch sidecar (file-system event source for non-hook harnesses)
   marker-block rules-file regeneration
   README + setup-time messaging about reduced Tier 3 experience
```

Phases 4 and 5 can be parallelized after Phase 3 completes.

```
Phase 6: Classifier Elimination      ←── needs Phase 3 only; independent of 4 and 5
   replace chat-model classifier with embed cosine similarity
   demote artifact_completeness to soft advisory
   remove runtime_classifier_model config + port 11436
```

## Cross-cutting concerns (apply to every phase)

### Token economics is the load-bearing constraint

Every implementation decision answers to one rule: **do not introduce
paid-LLM token cost where local compute or deterministic code suffices.**

- No MCP tool registration (the 20k-token tax inverts the math).
- No generative LLM in the compose path (v5.4 commitment, see findings doc).
- Qwen is used as embedder and similarity scorer, never as a synthesizer or chat classifier.
- Assembly is deterministic Python; do not regress to LLM-driven assembly.

### Soft-fail discipline

Anything in the hot path that touches the harness MUST exit 0 even on
failure. The harness has the user's prompt; a failing skillsmith
component cannot block them.

- Hook scripts always exit 0; errors go to stderr (suppressed by `2>/dev/null`).
- CLI commands called from hooks use `|| true` patterns in the wrapper.
- Qwen unavailability degrades semantic predicates to `unknown`; never raises.

### Telemetry is required, not optional

Every phase adds telemetry to `composition_traces` (existing table; see
`storage/vector_store.py` `CompositionTrace` dataclass). New event types:
`phase_eval`, `phase_transition`, `contract_retrieval`,
`system_skill_applied`.

If you implement a new behavior without telemetry, the build step is
incomplete — operators cannot tune what they cannot see.

### Idempotency

All CLI commands that mutate state must be idempotent. Re-running
`skillsmith setup` on an initialized install reports "already done"
and exits 0 (existing pattern — preserve it). Re-running
`skillsmith customize update <name>` with unchanged content is a no-op.

## Glossary

| Term | Meaning |
|---|---|
| **Profile** | A named bundle of system + workflow skill overrides (e.g. `work`, `personal`). Auto-detected from cwd via git remote or path. |
| **Phase** | A workflow stage (e.g. `spec`, `design`, `build`, `qa`). Sticky state in `.skillsmith/phase`. |
| **Workflow skill** | Whole-prose skill injected at phase entry. Defines persona + exit gates. |
| **System skill** | Whole-prose skill fired by applicability predicates (e.g. before commit). |
| **Domain skill** | Fragmented skill retrieved via hybrid search. Centrally curated; never user-edited. |
| **Contract** | Markdown+frontmatter file written by paid LLM stating task intent + domain tags. Drives domain retrieval. |
| **Pre-filter** | Cheap Python check that decides whether to invoke Qwen for gate evaluation. |
| **Gate** | Declarative exit criterion in a workflow skill. Evaluated by predicate evaluator. |
| **Tier 1 / 2 / 3** | Harness capability classes (per-turn hooks / per-session wrappers / static rules files). |
| **Push side** | Workflow-skill injection at phase entry (replaces sunsetted reminder pattern). |
| **Pull side** | Contract-write triggered domain retrieval. |

## Current state (verified via code-indexer at 2026-05-21)

These facts ground the build steps. Verify they're still true before
executing if significant time has passed.

| Item | Current state | Source |
|---|---|---|
| CLI entry point | `skillsmith` console script → `skillsmith.install.__main__:main` | `pyproject.toml` `[project.scripts]` |
| Subcommand dispatcher | argparse-based; modules under `src/skillsmith/install/subcommands/` | `install/__main__.py:96-103` |
| Service entry | `python -m skillsmith` → uvicorn on `:47950` | `src/skillsmith/__main__.py` |
| Config layer | `pydantic_settings`; user-scoped (no project-local .env) | `src/skillsmith/config.py:50-77` |
| Datastore default | `${XDG_DATA_HOME}/skillsmith/corpus/skills.duck` | `src/skillsmith/config.py:67` |
| Skill file format | YAML with `skill_class`, `domain_tags`, `raw_prose` (markdown in YAML string) | `src/skillsmith/_packs/sdd/sdd-spec-and-scoping.yaml` |
| SDD workflow skills | Exist as `_packs/sdd/sdd-*.yaml`, **currently tagged `skill_class: domain`** | `src/skillsmith/_packs/sdd/` |
| `authoring/` module | Maintainer-side LLM-driven skill generation. Distinct from the user-facing `customize` we add. | `src/skillsmith/authoring/` |
| Existing `setup` | Interactive wizard; refactor in Phase 1 to be profile-aware + refuse-if-existing | `install/subcommands/simple_setup.py` |
| Existing `update` | Schema migration + corpus integrity + model drift report. No default re-ingest yet. | `install/subcommands/update.py` |
| Compose orchestrator | Deterministic Python; no LLM in path | `orchestration/compose.py:213-242` |
| Domain retrieval | Qwen3 query embed + BM25 + RRF + diversity rerank | `retrieval/domain.py:166-200` |
| BM25 keyword source | Rule-extracted from task description (no contract input yet) | `retrieval/domain.py:227-230` |
| Telemetry | `CompositionTrace` dataclass; written to DuckDB | `storage/vector_store.py` `CompositionTrace` |

## Naming conventions for new code

- **New subcommands** go under `src/skillsmith/install/subcommands/` and are imported into `install/__main__.py:_SUBCOMMANDS`.
- **New CLI commands the user invokes:** `skillsmith profile`, `skillsmith customize`, `skillsmith contract`, `skillsmith signal`.
- **Avoid `skillsmith author`** — `authoring/` already exists for maintainer-side LLM-driven skill generation. Use `customize` for the user-facing markdown-editing surface in Phase 1.
- **New runtime modules** go under `src/skillsmith/` at the top level (e.g. `profiles.py`, `signals/`, `contracts.py`).
- **New tests** mirror the source path under `tests/`.

## What's deferred (not part of this build)

- Knowledge-Decision Indexer scoping and integration.
- Linear-issue contract import (mentioned by user as original intent for contracts; out of scope for first build).
- Multi-project shared state.
- Third-party predicate plug-ins.
- Branching/cyclic phase graphs (assume linear: spec → design → build → qa → ship).
- Per-profile domain pack selection (domain is universal).
- Author publish / share workflow.

## What to do next

Phases 1–5 are complete and committed on `build-sequence-phases`.
Open `docs/build-sequence/06-classifier-elimination.md` and execute it.
Phases 4 and 5 are done so Phase 6 has no remaining blockers.
