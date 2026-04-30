# Skillsmith Architecture Spec — Routing, Workflow, Retrieval

**Status:** Design proposal for pressure-testing
**Author:** Nate (synthesized from working session)
**Last updated:** 2026-04-29

---

## 0. How to read this document

This spec covers three coupled changes to the skillsmith corpus and retrieval architecture:

1. **Tag policy reform** — replace the R3 5-tag cap with class-aware, tier-aware policy + universal quality rules. (v1, ready to build.)
2. **Skill class extension** — promote `skill_class` from `system | domain` to `system | domain | workflow`. Adds a first-class home for process/orchestration skills like the SDD pipeline. (v1, ready to build.)
3. **Routing layer** — add an intake workflow + Qwen-based router that determines which workflow loads, replacing the current "main agent boots with full context" pattern with a thin-bootloader-and-skillsmith model. (v2, design only.)

The first two ship together. The third is a separate, larger piece of work that benefits from the first two being in production first.

The spec is intentionally detailed because the architectural shifts are non-trivial and the cost of redesigning later is high. Readers who only need the v1 changes can stop after Section 5. Readers reviewing the routing architecture should read all of it because the routing design depends on the workflow class existing.

---

## 1. Executive summary

Skillsmith currently has a bimodal quality problem (5 hand-authored skills meet contract, ~450 imports fail systematically) and a precision drift problem (no scoping mechanism prevents lexically-adjacent-but-semantically-irrelevant skills from competing for top-k retrieval slots). The lint gate (C1) is now in place, which fixes structural quality at ingest. This spec addresses what comes next:

**The tag policy** prevents bag-of-tags spray from inflating retrieval surface, while allowing legitimate retrieval-surface coverage where it's warranted. Quality rules apply universally; count tolerance flexes by tier because dense embedding precision degrades non-uniformly across skill types.

**The class extension** acknowledges that not all retrievable skills are technical. SDD pipeline skills, code review checklists, and similar process artifacts are neither always-injected (so not `system`) nor technology-bound (so not `domain`). Promoting them to `workflow` keeps `PACK_TIERS` clean as a technical taxonomy and gives a stable home for future process skills.

**The routing layer** is the higher-leverage architectural shift. By inferring the active workflow from a structured intake interview before retrieval runs, the search space narrows from "all domain skills tagged for this phase" to "skills within the workflow's declared tier scope." That eliminates cross-domain lexical match competition in a way no amount of tag policy improvement can. Routing is gated by the lower layers being stable, but it's the change that delivers the precision improvement the corpus actually needs.

---

## 2. Background

### 2.1 Current state

Skillsmith ingests YAML skill descriptions and serves them via a retrieval pipeline (`retrieval/domain.py`) that combines embedding similarity (nomic-embed-code), BM25, and reciprocal rank fusion. Skills are filtered by phase (`spec`, `design`, `build`, `qa`, `ops`, `meta`, `governance`) and capped at k results per phase via `DEFAULT_K_BY_PHASE` (`compose_models.py:16-28`). The k values were determined empirically (`docs/experiments/poc-composed-vs-flat.md`):

- `build`, `ops`: k=2 (short-form action tasks; 70% token reduction, 0.93 mean quality)
- `qa`, `spec`, `design`, `meta`, `governance`: k=4 (long-form structured tasks)

The current `skill_class` field (`reads/models.py:21`) is binary: `system` (always-injected, bypass retrieval) or `domain` (retrieved). The retrieval filter (`retrieval/domain.py:190`) hard-filters to `skill_class = 'domain'`.

`PACK_TIERS` (`compose_models.py:251-287`) categorizes domain skills into a technical taxonomy: `foundation`, `language`, `framework`, `store`, `cross-cutting`, `platform`, `tooling`, `domain`, `protocol`.

### 2.2 Problems

**P1 — Bimodal corpus quality.** The 2026-04-28 corpus YAML quality review found ~5 hand-authored batch-2/3 skills meet the R1–R8 contract; the other ~450 active + 79 staged YAMLs fail systematically. C1 (promote contract rules to ingest-time lint) is now in place and will catch new failures. This spec addresses what to do about the existing failures — specifically the 84% that fail R3 (>5 tags).

**P2 — Misapplied R3 rule.** The 5-tag cap was borrowed from a presumed K=5 retrieval default. There is no K=5; the retrieval default is phase-driven (k=2 or k=4). Tags themselves are unbounded at compose time. The 5-tag cap was convention dressed up as measurement, and it punishes legitimate retrieval-surface coverage on hand-authored skills (batch-3 ships 11–14 tags deliberately) while doing nothing to prevent the actual harm: synonym spray on low-effort skills.

**P3 — SDD skills don't fit the taxonomy.** The seven SDD pipeline skills are clearly not `system` (they're not always-injected), but they don't fit `domain` cleanly either. They're process orchestration, not technology. Forcing them into `domain` muddies `PACK_TIERS`. There is no clean home for them today.

**P4 — Cross-domain lexical match pollution.** When retrieval runs, all `domain` skills compete in the same pool. A query about CSS layout can lexically match a Node.js skill that uses overlapping vocabulary. K-capping picks top results by score, but if the wrong skill ranks highly enough to enter top-k, it pollutes the result. There is currently no mechanism to scope retrieval to "skills relevant to what the user is actually doing" beyond phase filtering, which is too coarse.

**P5 — Front-loaded harness context.** The main agent currently needs to know about all workflows to determine which workflow applies to the user's intent. This forces front-loading of workflow descriptions/instructions even when most aren't relevant to the session. There's no clean way to defer workflow context loading until after intent is known.

### 2.3 Goals

- Eliminate the 5-tag cap. Replace with policy that targets actual harm (synonym spray, off-intent tags, embedding diffuseness) without penalizing legitimate retrieval-surface coverage.
- Give workflow skills a first-class taxonomy slot.
- Reduce cross-domain retrieval pollution by scoping retrieval to workflow-relevant tiers.
- Move workflow instruction loading out of the harness boot path. The harness should be a thin bootloader; skillsmith should be the policy store.
- Enable telemetry-driven improvement of routing decisions over time.

### 2.4 Non-goals

- Re-architecting the retrieval pipeline itself (embedding model, BM25, RRF). Those work; this spec layers on top.
- Changing `DEFAULT_K_BY_PHASE`. The empirical k values stand.
- Solving corpus coverage gaps (Prisma, MongoDB, Vite, podman). Separate workstream.
- Solving fact-accuracy issues (R1/R5/R7) in imported skills. Separate workstream.
- Replacing Qwen with the main agent for routing. Discussed and deferred.

---

## 3. Architecture overview

The proposed architecture has three layers:

```
┌─────────────────────────────────────────────────────────────────┐
│ Layer 1: Routing                                                │
│   - Intake workflow (loaded at harness boot via skillsmith)     │
│   - Qwen as classifier                                          │
│   - Structured signal interview                                 │
│   - User verification                                           │
│   - Hands off to selected workflow                              │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ Layer 2: Workflow                                               │
│   - Workflow class (system / domain / workflow)                 │
│   - Phase scaffolding within workflow                           │
│   - Exit gates and scope checks                                 │
│   - Declares tier scope for retrieval                           │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ Layer 3: Retrieval                                              │
│   - Embedding + BM25 + RRF (unchanged)                          │
│   - Filtered by phase (unchanged)                               │
│   - NEW: scoped by workflow's tier declaration                  │
│   - NEW: tag policy enforced at ingest                          │
└─────────────────────────────────────────────────────────────────┘
```

**Skillsmith** is the single source of truth for all three layers. Workflow definitions, intake interview design, tag policy config, retrieval scoping rules — all live in skillsmith and are versioned, lintable, and updatable through the standard skill update path.

**The harness** is a thin bootloader. It knows how to:
1. Load the intake workflow from skillsmith on session start.
2. Run the workflow execution loop (load instructions, execute, hand off to next workflow on gate satisfaction).
3. Talk to Qwen and the main agent.

It does not know what workflows exist, what their phases are, what skills they compose from, or how to interview users. All of that lives in skillsmith.

### 3.1 Why this shape

Each layer does one thing:

- **Routing decides what.** It picks the workflow. It doesn't know how to execute workflows; it knows how to interview users and classify intent.
- **Workflow decides how.** It defines the persona, the phases, the gates, the tier scope. It doesn't know what other workflows exist; it knows its own job.
- **Retrieval surfaces specifics.** It returns relevant skills given the workflow's tier scope and phase context. It doesn't know about workflows directly; it gets a tier filter and applies it.

This is the same router/controller/model pattern that web frameworks have been doing for 20 years. The skillsmith equivalent: routing/workflow/retrieval. Each layer can change without forcing changes in the others.

### 3.2 Build order

Build the layers bottom-up. The dependencies run upward (workflow depends on retrieval; routing depends on workflow), so building top-down means building against unstable foundations.

**v1 (this spec, ready to build):**
- Layer 3 changes: tag policy lint + retrieval filter accepts `workflow` class
- Layer 2 changes: `skill_class` extended to include `workflow`, SDD seven reclassified

**v2 (this spec, design only):**
- Layer 1: routing layer, intake workflow, Qwen integration, telemetry

The v1/v2 boundary is real. v1 ships the lint and the class extension, gets the corpus into a clean state, lets workflows-as-a-class settle in production for some weeks before v2 design hardens. Don't build v2 against the assumption v1 works exactly as designed; let it prove out first.

---

## 4. Skill class taxonomy (v1)

### 4.1 The three classes

`skill_class` is a required field on every skill. It accepts exactly one of three values:

#### `system`

**Retrieval contract:** always-injected. Bypasses the retrieval pipeline entirely. Loaded into context unconditionally for every session.

**Tag policy:** `domain_tags: []` (must be empty). Tags have no effect on system skills since they're not retrieved. Enforcing emptiness prevents authors from accidentally writing tags that won't do anything.

**Examples:**
- Governance/policy skills (CapEx PR rules, SSO setup checklists)
- Meta skills (skill-authoring guidance, contract docs)
- Always-relevant standards (writing conventions, output format rules)

**Lint behavior:** mechanical only. Verify `domain_tags: []`, verify `always_apply: true` (or whatever the system-skill flag is), verify any other system-skill schema requirements. No quality-rule lint; no tier policy.

#### `domain`

**Retrieval contract:** retrieved via embedding + BM25 + RRF. Filtered by phase. Scoped by `PACK_TIERS`. Capped at `DEFAULT_K_BY_PHASE[phase]`.

**Tag policy:** tier-keyed soft ceilings via `TAG_POLICY_BY_TIER` (Section 5.3). Universal quality rules 1–4 apply (Section 5.2).

**Examples:**
- Technology-bound skills: Prisma migration syntax, React component patterns, podman networking, GraphQL schema design
- Anything where the retrieval surface is "I'm working with X technology"

**Lint behavior:** full quality rules + tier ceiling lookup.

#### `workflow`

**Retrieval contract:** retrieved via the same embedding + BM25 + RRF pipeline as domain. Filtered by phase. Scoped by **pipeline-position markers** rather than `PACK_TIERS`. K-capped per `DEFAULT_K_BY_PHASE`.

**Tag policy:** single moderate ceiling (`WORKFLOW_TAG_POLICY` — Section 5.4). Universal quality rules 1–4 apply. Plus rule W1 (position marker required).

**Examples:**
- SDD pipeline skills (`sdd-spec`, `sdd-design`, `sdd-plan`, `sdd-testgen`, `sdd-build`, `sdd-verify`, `sdd-deliver`)
- Code review checklists
- Release runbooks
- Incident response playbooks
- RFC authoring guides
- Anything where the retrieval surface is "I'm in this part of an authoring/process pipeline"

**Lint behavior:** full quality rules + workflow ceiling + W1 position marker check.

### 4.2 Disambiguation rules

When unsure which class a skill belongs to, apply these in order:

1. **Is it always-injected regardless of session intent?** If yes, `system`. If no, continue.
2. **Is the retrieval surface a technology, framework, store, or protocol?** If yes, `domain`. If no, continue.
3. **Is the retrieval surface a position in an authoring or operational pipeline?** If yes, `workflow`. If no, the skill is probably miscategorized — it might be too broad (split it), or it might be a system skill the author didn't recognize as such.

The rule of thumb: if you'd say "this skill is *about* X" where X is a technology, it's domain. If you'd say "this skill is for *when* you're doing Y" where Y is a process step, it's workflow. If you'd say "this skill *always* applies," it's system.

### 4.3 Schema changes required

```python
# src/skillsmith/reads/models.py:21
# BEFORE:
skill_class: Literal["system", "domain"]

# AFTER:
skill_class: Literal["system", "domain", "workflow"]
```

```python
# src/skillsmith/retrieval/domain.py:190
# BEFORE:
WHERE skill_class = 'domain'

# AFTER:
WHERE skill_class IN ('domain', 'workflow')
```

The retrieval filter change is a behavior change to the live retrieval path. It must be feature-flagged and tested on a query subset before rolling out broadly. The lint changes are safe to land independently — workflow skills can exist as a class before the retriever knows about them.

### 4.4 Migration

Audit existing `domain` skills for misclassification. Any skill that describes "how to author X" rather than "how to use X" should reclassify to `workflow`. Specifically:

**Definite reclassifications:**
- `sdd-spec`, `sdd-design`, `sdd-plan`, `sdd-testgen`, `sdd-build`, `sdd-verify`, `sdd-deliver` → `workflow`

**Likely reclassifications (review each):**
- Any skill with "checklist" in the name
- Any skill with "playbook" in the name
- Any skill describing how to author specific document types (RFC templates, design doc templates)
- Any skill scoped to a specific operational procedure (release process, deployment runbook, incident response)

**Estimated total reclassifications:** 5–15 beyond the SDD seven, but this needs a corpus pass to confirm.

Reclassification must precede lint dry-run. Otherwise workflow skills will fail domain tier ceilings (because they don't have a tier) or fail W1 in confusing ways.

---

## 5. Tag policy (v1)

### 5.1 Replacing R3

The current R3 rule (`tags ≤ 5`) is removed. Replaced with class-aware policy:

- `system`: `domain_tags` must be empty. No further checks.
- `domain`: tier-keyed soft ceiling + quality rules 1–4.
- `workflow`: single ceiling + quality rules 1–4 + W1 position marker check.

### 5.2 Universal quality rules

Apply to `domain` and `workflow` skills. Each rule fails per-tag, not per-skill — the lint emits per-tag verdicts so authors know which tag to fix.

#### Rule 1: Plausibly queryable

Each tag must be a term a user would plausibly type when looking for this skill. Not a synonym chain, not a category-bucket label, not a restatement of the title.

**Implementation:** semantic check via model-in-the-loop. Same model tier as `sdd-verify`. Pinned, versioned prompt living in the repo alongside other SDD prompts.

**Failure verdicts:**
- `not_queryable`: tag is internal jargon, taxonomy label, or otherwise unlikely to appear in a real query

**Examples:**
- Pass: `prisma`, `migration`, `schema-evolution`
- Fail: `database-tooling-category`, `tier-2-skill`, `internal-use`

#### Rule 2: Distinct from title

Tag tokens (lowercased and stemmed) must not be a subset of title tokens.

**Implementation:** mechanical. Tokenize and stem with the same tokenizer the retriever uses. If `set(stem(tag_tokens)) ⊆ set(stem(title_tokens))`, fail.

**Failure verdict:**
- `redundant_with_title`: tag is already retrievable from the title

**Example:**
- Title: "Prisma migrations"
- Fail: `prisma`, `migrations`, `prisma migrations`
- Pass: `schema-evolution`, `database-versioning` (different stems)

#### Rule 3: Distinct from other tags on the same skill

No two tags may share a stem or be synonyms of each other.

**Implementation:** stem overlap is mechanical (compare stems pairwise). Synonym detection is semantic (model-in-the-loop, same prompt as Rule 1 with a synonym-check sub-task).

**Failure verdict:**
- `synonym_of:<other_tag>`: tag duplicates another tag on the same skill

**Examples:**
- Fail: `auth` and `authentication` (synonyms)
- Fail: `db` and `database` (synonyms)
- Fail: `migrate` and `migration` (stem overlap)
- Pass: `migration` and `schema-evolution` (related but distinct retrieval surfaces)

#### Rule 4: Single-intent aligned

Each tag must describe the skill's actual intent, not adjacent topics the skill happens to mention.

**Implementation:** semantic check via model-in-the-loop. Requires the lint prompt to have access to the skill's title, description, and content — not just the tag list.

**Failure verdict:**
- `off_intent`: tag describes an adjacent topic, not this skill's job

**Example:**
- Skill: "Writing Prisma schemas"
- Pass: `schema-design`, `prisma-models`, `field-types`
- Fail: `migrations` (related, but the skill is about authoring, not migrating)

### 5.3 Domain tier policy

```python
TAG_POLICY_BY_TIER = {
    # Recall-favored tiers (high cost of missing the skill)
    "foundation":    {"soft_ceiling": 15, "rationale_required_above": 12},
    "cross-cutting": {"soft_ceiling": 15, "rationale_required_above": 12},
    "domain":        {"soft_ceiling": 12, "rationale_required_above": 10},

    # Precision-favored tiers (false positives pollute adjacent retrievals)
    "language":      {"soft_ceiling": 8,  "rationale_required_above": 6},
    "framework":     {"soft_ceiling": 8,  "rationale_required_above": 6},
    "store":         {"soft_ceiling": 8,  "rationale_required_above": 6},
    "protocol":      {"soft_ceiling": 6,  "rationale_required_above": 5},
    "tooling":       {"soft_ceiling": 8,  "rationale_required_above": 6},

    # Mixed (precision-favored within stack, some cross-cutting flavor)
    "platform":      {"soft_ceiling": 10, "rationale_required_above": 8},
}
```

**Above `soft_ceiling`:** hard fail. Author must trim or split the skill.

**Above `rationale_required_above` and at-or-below `soft_ceiling`:** pass only if a `tags_rationale` field is present on the skill explaining why the count is justified. The rationale is human-reviewable text, not a checkbox.

**At or below `rationale_required_above`:** quality rules apply, count is fine.

**Tuning:** these numbers are first-pass guesses, not measured optima. Tune against batch-3 gold-standard skills during dry-run. If a batch-3 skill fails its tier's ceiling, either the ceiling is wrong or the skill is over-tagged. Both are useful signals; resolve case by case.

### 5.4 Workflow policy

```python
WORKFLOW_TAG_POLICY = {"soft_ceiling": 10, "rationale_required_above": 8}
```

Single policy across all workflow skills. Workflow scoping comes from W1, not from a tier breakdown.

**Rule W1: Position marker required**

At least one tag must be a recognized pipeline-position marker. Recognized markers live in `WORKFLOW_POSITION_MARKERS`:

```python
WORKFLOW_POSITION_MARKERS = frozenset({
    # SDD pipeline
    "sdd",
    "phase:spec", "phase:design", "phase:plan",
    "phase:testgen", "phase:build", "phase:verify", "phase:deliver",

    # General process
    "code-review", "release", "incident", "rfc",
})
```

**Failure verdict for W1:**
- `missing_position_marker`: workflow skill doesn't declare which pipeline position it serves

**Why:** workflow skills retrieve on process queries. Without position markers, an `sdd-spec` skill could match a code review query (since both involve "review" vocabulary). Position markers scope retrieval to the right pipeline.

The marker registry is authoritative. Adding a new position marker requires a deliberate update — it's not author-extensible inline. This prevents marker drift.

### 5.5 Lint architecture

The lint runs in two passes:

**Pass 1: Mechanical lint** (`lint_tags_mechanical`)
- Runs on every commit, every CI build, every YAML save
- Cheap, deterministic, no model calls
- Covers: Rule 2 (title overlap), Rule 3 stem overlap, count ceilings, W1 marker presence, system-skill emptiness

**Pass 2: Semantic lint** (`lint_tags_semantic`)
- Runs at ingest time, gated behind a flag
- Calls the model-in-the-loop prompt
- Covers: Rule 1 (queryable), Rule 3 synonym detection, Rule 4 (off-intent)
- Pinned, versioned prompt; same model tier as `sdd-verify`

The split is important. Mechanical lint stays fast enough to run continuously. Semantic lint is bounded to ingest because it's slower and costs model calls. Authors get fast feedback on the easy stuff and deeper feedback when committing to the corpus.

### 5.6 Per-tag verdict format

```yaml
# Example lint output for a skill
skill: prisma-migrations
class: domain
tier: store
tag_count: 7
ceiling: 8 (rationale required above 6)
rationale_required: true
rationale_present: false  # FAIL
tags:
  - tag: prisma
    verdict: redundant_with_title
  - tag: migration
    verdict: redundant_with_title
  - tag: schema-evolution
    verdict: pass
  - tag: db-versioning
    verdict: synonym_of:database-versioning
  - tag: database-versioning
    verdict: pass
  - tag: rollback
    verdict: pass
  - tag: deployment
    verdict: off_intent
overall: FAIL (3 tag failures, missing rationale)
```

Per-tag verdicts give authors specific, actionable feedback. Skill-level pass/fail does not.

---

## 6. Workflows (v1 + v2)

### 6.1 What a workflow is

A workflow is a skillsmith artifact that defines:

- **Persona:** how the agent should behave during this workflow ("you are an interviewer gathering signals," "you are a spec author asking clarifying questions")
- **Phase structure:** the sequence of phases this workflow goes through (e.g. `intake` workflow has phases `gather → propose → verify`; `sdd-spec` has phases corresponding to spec sections)
- **Exit gates:** conditions that must be met before this workflow completes
- **Scope checks:** conditions that determine whether the user's current intent still matches this workflow's job
- **Tier scope:** which `PACK_TIERS` (for domain skills) and position markers (for workflow skills) this workflow's retrieval should pull from
- **Retrieval policy:** any phase-specific overrides to default retrieval behavior
- **Hand-off rules:** what happens when this workflow exits — which workflow loads next, or whether the session ends

Workflows are versioned skills in skillsmith. Updating a workflow goes through the same path as updating any other skill (skill updater, lint, version bump).

### 6.2 The intake workflow (v2)

The intake workflow is the special workflow loaded at harness boot. It runs before any other workflow.

**Persona:** "You are an interviewer. Your job is to gather a structured set of signals about what the user wants to accomplish, then propose a workflow for them to confirm. You do not execute work; you route."

**Signal schema:** a fixed set of fields the interview gathers. These are the *input format to the router*, not just UX. Proposed v1 schema:

```yaml
session_signals:
  intent:               # primary action
    enum: [explore, scope, design, build, fix, review, deliver, learn]
  artifact_type:        # what gets produced
    enum: [doc, code, decision, plan, fix, none]
  scope:                # how big
    enum: [task, feature, project, initiative]
  technical_depth:      # how technical
    enum: [conceptual, architectural, implementation, debug]
  audience:             # who it's for
    enum: [self, team, leadership, external, none]
  current_state:        # where in the lifecycle
    enum: [greenfield, in_progress, troubleshooting, retrospective]
  time_horizon:         # urgency
    enum: [now, this_week, this_quarter, indefinite]
  # Free-form context
  free_text_summary: string  # user's own description, max 500 chars
```

The interview gathers these signals through natural conversation, not by literally asking each question. The agent should infer signals from user statements and only ask follow-up questions for missing or ambiguous signals.

**Phase structure:**

1. `gather`: run the interview until all signals are populated or the user signals they're done
2. `propose`: ship signals to Qwen, get back a routing decision (workflow + confidence + alternates)
3. `verify`: replay the routing decision in natural language and ask the user to confirm or correct
4. `hand_off`: load the confirmed workflow, unload intake

**Exit gates:**
- All required signals populated
- Routing decision returned with confidence above threshold
- User confirmation received

**Scope check:**
- Always passes during intake. The intake workflow's job is to determine scope; it can't be out of scope itself.

**Hand-off rules:**
- On confirmation, load the routed workflow.
- On rejection, return to `gather` with the previous routing attempt marked as ruled-out (Qwen sees this and won't repeat it).

### 6.3 Routing via Qwen

Qwen is the router. Inputs and outputs:

**Input:**
```yaml
signals: {populated session_signals}
ruled_out_workflows: [list of workflows the user already rejected this session]
available_workflows: [
  {workflow_id, description, scope_summary, signal_match_criteria}
  for each workflow in skillsmith
]
```

**Output:**
```yaml
primary_match:
  workflow_id: sdd-spec
  confidence: 0.87
  reasoning: "intent=scope + artifact_type=doc + scope=project matches sdd-spec criteria"
alternates:
  - workflow_id: sdd-design
    confidence: 0.42
    reasoning: "technical_depth=architectural is a partial match"
  - workflow_id: explore
    confidence: 0.31
    reasoning: "could be earlier-stage exploration"
```

**Confidence threshold:** if `primary_match.confidence` falls below a threshold (proposed v1: 0.6), the intake workflow surfaces the top 3 alternates as a menu rather than a single proposal. Below 0.4, it asks clarifying questions to narrow further before re-routing.

**Workflow descriptions** in skillsmith must be written in language that aligns with the signal schema, not in free prose. Each workflow has a `signal_match_criteria` block:

```yaml
# Example workflow metadata in skillsmith
workflow_id: sdd-spec
description_for_routing: "Authoring a project specification document. Used when the user needs to define scope, requirements, and success criteria for a project before design or implementation."
signal_match_criteria:
  intent: [scope, design]
  artifact_type: [doc]
  scope: [feature, project, initiative]
  technical_depth: [conceptual, architectural]
  current_state: [greenfield, in_progress]
strong_match_signals: [intent=scope, artifact_type=doc]
weak_match_signals: [audience=team, audience=leadership]
disqualifying_signals: [intent=fix, current_state=troubleshooting]
```

This is a controlled vocabulary that mirrors the interview signal schema. Workflow authors write to this format; Qwen matches against it. Free-prose descriptions are kept for human readers but don't drive routing.

### 6.4 Verification UX

When Qwen returns a routing decision, the intake workflow replays the signals back to the user in natural language and proposes the workflow:

> "It sounds like you want to scope a new project for your team — defining requirements and success criteria before getting into design details. I think you're looking for the **Project Spec** workflow. Want me to load that?"

Three response paths:

1. **Yes:** load the workflow, intake unloads, session continues.
2. **No, with correction:** user clarifies what's wrong. Common case: "actually I'm already past spec, I need to do the technical design now." The intake workflow updates the relevant signal (`current_state: in_progress`, or `intent: design`) and re-routes. Qwen sees the previous attempt as ruled-out.
3. **Show me options:** user wants to see the menu. Intake surfaces the top 3 alternates with brief descriptions.

The verification step is non-skippable in v1. Even when confidence is high, the user confirms before workflow loads. This costs one turn per session but prevents silent misroutes.

### 6.5 Workflow execution and gates

Once a workflow loads, the harness runs it. Each phase within the workflow has:

**Exit gate:** the conditions that must be met before this phase completes. These are codified in the workflow's instructions ("the spec is not complete until problem statement, success criteria, scope boundaries, and explicit non-goals are all populated").

**Scope check:** the conditions that determine whether the user's current activity still matches this phase's job. Scope checks run continuously during execution, not just at phase boundaries.

```yaml
# Example phase in sdd-spec
phase: define_problem
exit_gate:
  conditions:
    - problem_statement_populated
    - stakeholders_identified
    - constraints_documented
  validation: "All three fields must have at least one paragraph of substantive content. Empty or placeholder content does not satisfy."
scope_check:
  in_scope_signals:
    - user_describes_a_problem
    - user_identifies_constraints
    - user_lists_stakeholders
  out_of_scope_signals:
    - user_asks_about_implementation_details  # design phase
    - user_asks_about_specific_technologies   # build phase
    - user_describes_a_bug                    # different workflow entirely
  on_out_of_scope: |
    Surface to the user: "It sounds like you're moving into [detected scope].
    The current phase is about defining the problem. Want to continue here,
    or is it time to move on?"
```

**On scope check failure:** the workflow doesn't unilaterally switch contexts. It surfaces to the user that the current activity is drifting and offers a path. The user decides — continue in current scope, advance to next phase, or exit to re-route.

**On exit gate satisfaction:** the workflow advances. If all phases are complete, the workflow exits and the harness either ends the session or loads the next workflow per the workflow's hand-off rules.

### 6.6 v1 scope for workflow execution

The full gate-and-scope-check architecture is v2. v1 ships with simpler behavior:

- Workflows have exit gates only (no scope checks).
- If the user drifts out of scope, they have to explicitly request a workflow switch (which routes through intake again).
- Hard scope per session — no automatic re-routing.

This is a deliberate simplification. The full design with scope checks and inline re-routing is correct, but it's enough complexity that getting it right in v1 trades against shipping anything. v1 ships with hard scope; v2 adds scope checks and graceful re-routing once the rest of the architecture is stable.

This limitation must be documented prominently for v1 users. The most likely complaint: "I started in scope mode and now I want to do design, why do I have to start over?" The answer in v1 is "explicitly switch workflows from the menu." That's acceptable for early users but won't scale.

---

## 7. Telemetry-driven improvement (v2)

### 7.1 What we measure

The intake workflow generates telemetry at every stage. Recorded for every session:

- **Signals captured:** which fields, with what values, in what order
- **Interview turns:** how many turns it took to populate the signal schema
- **Routing decision:** primary match, confidence, alternates
- **User response:** confirmed / corrected / requested menu
- **Correction details:** which signal changed, what the new routing was
- **Final workflow loaded:** what actually got selected
- **Session outcome:** did the loaded workflow complete, was it abandoned, did the user switch out

### 7.2 What good looks like

**Routing accuracy:** percentage of routing decisions confirmed without correction on first proposal. Target: 80%+ once tuned.

**Signal coverage:** for sessions where users corrected, which signals were missing or wrong? Aggregating this surfaces interview gaps.

**Confidence calibration:** when Qwen reports confidence X, does it actually correspond to accuracy X in practice? If the model says 0.9 but only 70% of those decisions are confirmed, the model is overconfident and the threshold needs adjustment.

**Time to route:** how many turns from session start to workflow load? Target: 2–4 turns. Above 6 means the interview is over-asking; below 2 might mean it's under-asking.

**Workflow completion rate:** of sessions where a workflow loaded, what percentage hit the exit gate? Low completion suggests the workflow got loaded but wasn't actually what the user needed (a routing miss that wasn't caught at verification).

### 7.3 Improvement loop — human in the loop, not autonomous

Telemetry surfaces patterns to a human reviewer. The reviewer (Nate, or whoever owns the corpus) decides whether to change the intake workflow, individual workflow definitions, or routing criteria.

**Cadence:** weekly review for the first month, monthly thereafter once stable.

**Review artifacts:**
- Routing accuracy by workflow (which workflows are easy to route to, which are hard)
- Top correction patterns (e.g., "users keep correcting from sdd-spec to tech-design")
- Signal gap analysis (which signals correlate most with corrections)
- Confidence calibration plot

**Change paths:**
- **Interview tuning:** modify the intake workflow's instructions to gather better signal coverage. Skill update, version bump.
- **Workflow description tuning:** modify a specific workflow's `signal_match_criteria` to match user signals more accurately. Skill update, version bump.
- **Threshold tuning:** adjust the confidence thresholds for menu surfacing.
- **New workflow:** if telemetry shows users routing to "wrong" workflows because the right one doesn't exist, that's a corpus gap.

**No autonomous self-improvement.** The reviewer can ask Qwen or another model for suggestions on how to improve the interview, but every change is human-approved and version-controlled.

### 7.4 Versioning and rollback

Every change to the intake workflow or workflow definitions is a versioned skill update. This means:

- Sessions tag which version of each workflow they ran against. Reproducibility is possible weeks later.
- Rollback path exists: if a v17 of the intake workflow performs worse than v16, revert via standard skill update.
- A/B testing is possible: run v17 against 50% of sessions for a week, compare metrics, decide whether to promote or revert.

Without versioning, telemetry-driven improvement is one-way and undebuggable. The versioning requirement is non-negotiable.

---

## 8. Implementation plan

### 8.1 v1: Tag policy + class extension

**Phase 1.1: Schema and lint scaffolding** (estimate: small)
- Extend `skill_class` literal in `reads/models.py`
- Add `WORKFLOW_POSITION_MARKERS` registry
- Add `TAG_POLICY_BY_TIER` and `WORKFLOW_TAG_POLICY` config
- Stub `lint_tags_mechanical` and `lint_tags_semantic` modules

**Phase 1.2: Mechanical lint** (estimate: medium)
- Implement Rule 2 (title overlap), Rule 3 stem overlap, count ceilings, W1 marker check, system-skill emptiness
- Per-tag verdict output format
- Wire into `ingest.py` to run on every YAML
- CI integration

**Phase 1.3: Semantic lint** (estimate: medium)
- Author the lint prompt; pin and version it in repo
- Implement model-in-the-loop call for Rules 1, 3-synonyms, 4
- Wire into ingest with feature flag
- Test against batch-3 gold-standard skills for false positive rate

**Phase 1.4: Reclassify workflow skills** (estimate: small)
- Audit `domain` skills for misclassification
- Update `skill_class` on the SDD seven and any other process skills found
- Verify no `domain_tags` referencing technical tiers remain

**Phase 1.5: Retrieval filter update** (estimate: small, but high-risk)
- Change `retrieval/domain.py:190` filter to `IN ('domain', 'workflow')`
- Feature-flag the change
- Test on representative query set
- Verify no recall regression on existing domain queries
- Verify workflow skills now retrievable on workflow queries

**Phase 1.6: Dry-run lint over corpus** (estimate: medium)
- Run new lint over 450 active + 79 staged YAMLs
- Bucket failures by mode
- Tune ceilings against batch-3 gold-standard
- Generate triage report for corpus owner

**Phase 1.7: Migration assistance** (estimate: medium)
- Auto-suggest fixes for synonym failures (rule 3) where possible
- Generate `tags_rationale` template for skills that need it
- Surface off-intent and not-queryable failures for manual review

### 8.2 v2: Routing layer

Build only after v1 has been in production for at least 2-4 weeks. The routing layer benefits from seeing how workflows-as-a-class actually behave in practice.

**Phase 2.1: Intake workflow definition** (estimate: medium)
- Author the intake workflow: persona, phase structure, exit gates, signal schema
- Author workflow descriptions in `signal_match_criteria` format for all existing workflows

**Phase 2.2: Qwen integration** (estimate: medium-large)
- Define Qwen routing API
- Build the routing prompt
- Wire routing into the intake workflow's `propose` phase

**Phase 2.3: Harness changes** (estimate: large)
- Bootloader pattern: harness loads intake workflow at boot
- Workflow lifecycle: load, execute, hand-off, unload
- Failure handling: Qwen unavailable, routing low-confidence, user rejection

**Phase 2.4: Telemetry pipeline** (estimate: medium)
- Capture session telemetry per Section 7.1
- Build review artifacts per Section 7.3
- Versioning hooks for skill updates

**Phase 2.5: Scope checks and graceful re-routing** (estimate: large, optional for v2)
- Per-phase scope checks
- Drift detection
- Inline re-route offers
- This is the v2.1 piece if v2 ships without it

### 8.3 Critical path dependencies

```
1.1 → 1.2 → 1.6 (lint must work before dry-run)
1.1 → 1.4 → 1.5 (schema extension before reclassify before filter change)
1.4 → 1.6 (must reclassify before lint dry-run, or workflow skills fail incorrectly)
1.6 → 1.7 (triage drives migration)
v1 complete → 2.1 (routing depends on workflow class existing)
2.1 → 2.2 → 2.3 (intake definition before Qwen integration before harness changes)
2.3 → 2.4 (telemetry instruments the live system)
```

---

## 9. Risks and open questions

### 9.1 Risks

**R1: Retrieval filter change breaks existing queries.** The change at `domain.py:190` is the riskiest part of v1. Mitigation: feature flag, extensive query-set testing, gradual rollout, ability to revert.

**R2: Tag policy too strict, recall drops.** Specifically, Rule 1 (queryable) over-rejecting. Mitigation: dry-run measures recall before flipping the lint to enforcing mode; if recall drops, prompt-tune Rule 1 before enforcing.

**R3: Tag policy too loose, doesn't fix precision.** If Rules 3 and 4 don't catch enough spray, embedding diffuseness persists. Mitigation: precision telemetry per phase; tune ceilings down if needed.

**R4: Reclassification missing skills.** A process skill stays in `domain`, gets retrieved on technical queries, pollutes results. Mitigation: corpus pass before lint dry-run; audit skill descriptions for "how to author" language.

**R5: Qwen as critical-path dependency.** If Qwen is down, routing fails, no session can start. Mitigation (deferred): caching common routes, static menu fallback, power-user bypass flag. None blocks v2 ship; design for them.

**R6: Routing accuracy below threshold.** Users get bad initial routes, lose trust in the system. Mitigation: verification step is non-skippable; failure UX (signal replay + correction) is well-designed; telemetry catches systemic issues fast.

**R7: Self-improvement drift.** Even with human-in-the-loop, telemetry-driven changes can accumulate in directions that optimize for the metric but not for what we actually want. Mitigation: versioning + rollback + periodic full review (not just incremental tweaks); explicit "what does good look like" criteria written down.

**R8: Scope creep from this architecture.** This conversation moved from "fix R3" to "redesign the corpus contract" to "add a routing layer" in a single thread. Each step was defensible; cumulative scope is large. Mitigation: explicit v1/v2 boundary in this spec; v2 doesn't start until v1 has been in production several weeks.

### 9.2 Open questions

**Q1: Confidence threshold for routing.** v1 proposed 0.6 for primary match, below which the menu surfaces. Number is a guess; tune with telemetry. What's the right initial guess?

**Q2: Position marker registry governance.** Who can add new position markers? What's the bar? Probably a deliberate skill update per addition, but the policy needs writing.

**Q3: Workflow description authoring guidance.** `signal_match_criteria` is a controlled vocabulary; authors need clear guidance on how to write it. Probably a meta-workflow ("how to author a workflow") that authors run before adding new workflows.

**Q4: Cross-workflow skill sharing.** Some skills might legitimately serve multiple workflows. Currently a skill belongs to one tier scope. Do we need a way for, say, a `cross-cutting` skill to be retrievable from multiple workflow tier-scope declarations? Probably yes, but design this in v2 not v1.

**Q5: The `workflow` class retrieval scoping.** v1 says workflow skills retrieve via position markers, but the actual scoping mechanism in `retrieval/domain.py` isn't yet designed. Is it a tag filter? A separate index? An additional WHERE clause? Spec needs the implementation detail before v1.5 ships.

**Q6: Intake interview interface.** Is the interview a back-and-forth chat, a structured form rendered in the UI, or a hybrid? UX decision worth making before v2.1.

**Q7: Workflow chaining.** Can a workflow specify "after I exit, automatically load workflow X"? Useful for the SDD pipeline (spec → design → plan). Worth designing in v2 or deferring to v2.1.

**Q8: Substituting Qwen with the main agent.** Discussed and deferred. Worth a separate design doc if it ever becomes a real option, since it changes latency, cost, and privacy properties.

### 9.3 Pressure-test prompts for review

Suggested questions for the reviewer to push on:

1. Is the workflow-class addition actually needed, or could SDD skills be rehoused as a new tier within `domain`? Argue both sides.
2. Do the tier-keyed soft ceilings in `TAG_POLICY_BY_TIER` reflect the actual retrieval-precision tradeoff, or are they vibes-based? What measurement would falsify them?
3. The signal schema in Section 6.2 is a guess. Is it the right granularity, or does it over- or under-fit? What signals are missing? Which are redundant?
4. The verification step costs one turn per session. Is that worth it, or is high-confidence auto-routing acceptable?
5. v1 ships with hard scope (no graceful re-routing). How bad is the UX cliff in practice, and does v2 need to come faster than "after v1 settles"?
6. The architecture has Qwen on the critical path for every session. Is that acceptable, or does the design need to handle Qwen-unavailable as a first-class case?
7. Telemetry-driven improvement is human-in-the-loop. Is the loop tight enough to actually catch issues, or will telemetry pile up unread?
8. The scope of this change is large. What's the smallest version that ships and gets useful signal? Is even v1 too big?

---

## 10. Acceptance criteria

### 10.1 v1 acceptance

**Lint:**
- AC1.1: Batch-3 gold-standard skills pass the new lint without trimming. Failures, if any, are on quality rules (1–4) or W1, not on count.
- AC1.2: A representative spray-tag skill from the long tail (one of the `node-*` or `vue-*` imports with 8+ synonym-heavy tags) fails on Rule 3 with specific synonym pairs identified.
- AC1.3: All seven SDD skills pass under `workflow` class with appropriate position markers from `WORKFLOW_POSITION_MARKERS`.
- AC1.4: Mechanical lint runs in CI in under 5 seconds per skill.
- AC1.5: Semantic lint produces per-tag verdicts that a human reviewer agrees with on a 50-skill sample.

**Retrieval:**
- AC1.6: Recall measured per phase (k=2 for build/ops, k=4 elsewhere) holds or improves vs. the current corpus on a representative query set. If recall drops, Rule 1 needs prompt tuning.
- AC1.7: Precision per phase improves on a representative query set, especially for k=2 phases where embedding diffuseness matters most.
- AC1.8: Workflow skills are retrievable on workflow queries (e.g., querying for "spec authoring" surfaces `sdd-spec`).
- AC1.9: Workflow skills are *not* retrieved on technical queries that don't reference workflow position (e.g., querying for "Prisma migration syntax" does not surface `sdd-build` even though `sdd-build` mentions migrations).

**Migration:**
- AC1.10: Lint dry-run completes against full corpus (450 active + 79 staged) and produces a triage report bucketing failures by mode.
- AC1.11: Reclassification audit identifies all process skills currently misclassified as `domain`. Audit is documented and reviewed before lint enforcement.

### 10.2 v2 acceptance

**Routing:**
- AC2.1: Intake workflow loads at harness boot from skillsmith. Harness contains no workflow definitions.
- AC2.2: Routing accuracy (confirmed without correction on first proposal) is at least 70% on the first 100 sessions, 80% after telemetry-driven tuning.
- AC2.3: Verification UX successfully redirects when routing is wrong — corrections lead to the correct workflow on second attempt at least 90% of the time.
- AC2.4: Time to route (turns from session start to workflow load) averages 2–4 turns.

**Workflow execution:**
- AC2.5: Loaded workflows complete (hit exit gate) at least 60% of the time. Lower indicates routing misses not caught at verification.
- AC2.6: Hard scope behavior is documented and surfaced clearly to users when they drift out of scope.

**Telemetry:**
- AC2.7: All sessions produce telemetry per Section 7.1.
- AC2.8: Weekly review artifacts are generated and consumable.
- AC2.9: At least one telemetry-driven improvement to the intake workflow ships in the first month, demonstrating the loop works.

### 10.3 Prerequisites

These must exist before v1 can be acceptance-tested:

- **PR1: Representative query set, phase-tagged.** Required for AC1.6, AC1.7. Without it, "recall holds" and "precision improves" are unfalsifiable. If query logs from the design-reviewer agent or SDD pipeline don't exist, generate a synthetic set of 50–100 queries spanning all phases.

- **PR2: Semantic lint prompt.** Required for AC1.5. Pinned, versioned, lives in repo alongside other SDD prompts.

- **PR3: Workflow position marker registry.** Required for AC1.3. Initial registry per Section 5.4.

- **PR4: Reclassification audit.** Required for AC1.10, AC1.11. Pass over corpus identifying process skills before lint runs.

These must exist before v2:

- **PR5: Workflow descriptions in signal-match-criteria format.** Required for AC2.2. Existing workflows must be re-described in the controlled vocabulary.

- **PR6: Telemetry infrastructure.** Required for AC2.7-2.9. Where do session traces go, how are they queried, who has access.

---

## 11. Out of scope

Explicitly not addressed by this spec, and not blockers for it:

- **Corpus coverage gaps.** Prisma, MongoDB, Vite, podman, Claude API skills don't exist or are weak. Authoring those is a separate workstream (`CORPUS-AUDIT-2026-04-28.md`).
- **Fact accuracy in imported skills.** R1/R5/R7 substance failures aren't addressed by this lint. Separate verification pass needed.
- **Retirement of long-tail skills.** Whether to retire vs. fix the 84% failing skills is a triage decision that runs against the lint output. This spec produces the triage signal; doesn't decide retirement policy.
- **Re-architecting retrieval.** Embedding model, BM25 weights, RRF parameters all stay as-is.
- **K values per phase.** `DEFAULT_K_BY_PHASE` is settled. No changes.
- **Replacing Qwen.** Discussed; deferred to a separate design conversation if it ever becomes real.
- **Multi-modal skills (images, video).** Not on the radar for v1 or v2.
- **Cross-tenant skill isolation.** Skillsmith is single-tenant for now.

---

## 12. Document conventions

**Status markers** used throughout:
- "v1, ready to build" — included in v1 implementation plan
- "v2, design only" — captured here, build later
- "deferred" — not in v1 or v2; needs separate design conversation
- "out of scope" — explicitly not addressed by this spec

**File path references** are relative to the skillsmith repo root unless otherwise noted.

**Code blocks** are illustrative. Field names, types, and exact API shapes will be finalized during implementation.

**The reviewer's job** is to pressure-test the architecture, not to nitpick the code. Section 9.3 has explicit prompts for the kind of review feedback that's most useful.
