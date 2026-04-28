# Matt Pocock Skills — Import Analysis

Source: https://github.com/mattpocock/skills (MIT). Local clone: `/tmp/mattpocock-skills/`.
Target: `/home/nmeyers/dev/skillsmith/src/skillsmith/_packs/`.
Reference: `/home/nmeyers/dev/skillsmith/docs/CORPUS-AUDIT-2026-04-28.md`.

## 1. Summary table

| # | Skill | Category | Overlap | Novel pattern (one sentence) | Recommendation | Target pack |
|---|---|---|---|---|---|---|
| 1 | tdd | engineering | heavy | Tracer-bullet vertical slices framed explicitly as anti-pattern to "horizontal RED/GREEN" + per-cycle checklist. | IMPORT-MERGE | core/test-driven-development.yaml |
| 2 | diagnose | engineering | heavy | "Phase 1 = build a feedback loop, everything else is mechanical" elevates loop construction above hypothesis chasing. | IMPORT-MERGE | core/debugging-strategies.yaml |
| 3 | grill-with-docs | engineering | none | Interrogation session that side-effects into `CONTEXT.md` (lazy ubiquitous-language doc) + sparing ADR offers. | IMPORT | engineering/ (new) |
| 4 | improve-codebase-architecture | engineering | partial | Deep-module exploration + grilling loop + lazy CONTEXT.md/ADR side effects. | IMPORT | engineering/ (new) |
| 5 | setup-matt-pocock-skills | engineering | n/a | Pure bootstrap for AGENTS.md + docs/agents/ wiring; repo-shape specific. | SKIP | — |
| 6 | to-issues | engineering | partial | Vertical-slice issue decomposition with HITL/AFK flag; tracer-bullet framing on issue-level. | IMPORT-MERGE | core/planning-and-task-breakdown.yaml + new fragment in core/spec-driven-development.yaml |
| 7 | to-prd | engineering | partial | Compact PRD template (Problem/Solution/User Stories/Implementation/Testing/OOS) tied to backlog `needs-triage` label. | IMPORT-MERGE | core/spec-driven-development.yaml |
| 8 | triage | engineering | none | Two-role (PM/eng) backlog triage flow with state-override commands and needs-info templates. | IMPORT | core/ or new ops pack |
| 9 | zoom-out | engineering | none | One-shot "raise abstraction level using the project glossary" instruction. | IMPORT (small) | core/ (or fragment of context-engineering) |
| 10 | caveman | productivity | none | Token-compression communication mode with auto-clarity exception list. | IMPORT | core/ (or new ux/ pack) |
| 11 | grill-me | productivity | none | Relentless one-question-at-a-time interrogation walking the decision tree, with recommended-answer prompt. | IMPORT | core/ |
| 12 | write-a-skill | productivity | heavy | Skill-authoring meta with description-discoverability checklist. | DEFER (compare to core/writing-skills.yaml) | — |
| 13 | git-guardrails-claude-code | misc | partial | Harness-level git destructive-op block via Claude Code hook. | SKIP (harness-specific; covered by update-config ecosystem) | — |
| 14 | migrate-to-shoehorn | misc | none | Library-specific (`shoehorn` test fixtures) — no general value. | SKIP | — |
| 15 | scaffold-exercises | misc | none | Total TypeScript exercise repo conventions — domain-specific. | SKIP | — |
| 16 | setup-pre-commit | misc | partial | Husky + lint-staged + prettier bootstrap. Stack-narrow, low ROI. | SKIP | — |
| 17 | edit-article | personal | none | Section-DAG editing of prose; off-domain for skillsmith. | SKIP | — |
| 18 | obsidian-vault | personal | none | Personal note-taking conventions. | SKIP | — |
| 19 | design-an-interface | deprecated | none | Parallel sub-agents producing radically different interface designs with assigned constraints. | IMPORT | engineering/api-and-interface-design.yaml (merge) |
| 20 | qa | deprecated | partial | QA session → file issues (superseded upstream by to-issues). | SKIP (covered by to-issues import-merge) | — |
| 21 | request-refactor-plan | deprecated | partial | Refactor-plan template (Problem/Solution/Commits/Decision/Testing/OOS). | IMPORT-MERGE | core/code-simplification.yaml or new core/refactor-planning fragment |
| 22 | ubiquitous-language | deprecated | none | DDD glossary extraction from conversation → `UBIQUITOUS_LANGUAGE.md`, flags ambiguity/synonyms. | IMPORT | engineering/documentation-and-adrs.yaml (or new) |

## 2. Per-skill findings

### IMPORT (whole new skill)

**grill-with-docs** (`/tmp/mattpocock-skills/skills/engineering/grill-with-docs/SKILL.md`)
No corpus analog. Combines five inline moves — challenge against glossary, sharpen fuzzy language, discuss concrete scenarios, cross-reference code, update `CONTEXT.md` inline — into a single grilling session. The sparing-ADR-offer rule (only when a future explorer would re-suggest the rejected option) is genuinely sharp. Mirror references `CONTEXT-FORMAT.md` and `ADR-FORMAT.md` from the source repo as fragments. Partition: one fragment per "during-the-session" move + one for ADR offer rule.

**improve-codebase-architecture** (`/tmp/mattpocock-skills/skills/engineering/improve-codebase-architecture/SKILL.md`)
Partial overlap with `engineering/architecture-patterns.yaml` (3.9KB, generic). Novel: explicit Ousterhout-style "deep modules" glossary, candidate-presentation step with explicit trade-offs, then grilling loop with side-effects into CONTEXT.md/ADRs/INTERFACE-DESIGN.md. Mirrors INTERFACE-DESIGN.md asset. Partition: glossary, explore, present-candidates, grilling-loop, side-effect rules.

**triage** (`/tmp/mattpocock-skills/skills/engineering/triage/SKILL.md`)
No analog — closest is `core/on-call-handoff-patterns.yaml` (different concern). Two-role model (PM-mode / eng-mode), state-override commands, needs-info templates, session-resumption pattern. Partition: roles, invocation, per-issue flow, needs-info template, resume.

**grill-me** (`/tmp/mattpocock-skills/skills/productivity/grill-me/SKILL.md`)
No analog. Distinct from our `core/brainstorming.yaml` (open exploration) and `core/idea-refine.yaml` (refinement) — this is interrogation under load, one question at a time, with recommended-answer-included rule. Cheap import.

**caveman** (`/tmp/mattpocock-skills/skills/productivity/caveman/SKILL.md`)
No analog. Compression mode plus persistence rule plus auto-clarity exception list (security/destructive/multi-step). Useful as a corpus-wide UX skill.

**zoom-out** (`/tmp/mattpocock-skills/skills/engineering/zoom-out/SKILL.md`)
Tiny (3 lines of body) but no analog. Either standalone micro-skill or one fragment inside `agents/context-engineering.yaml`.

**ubiquitous-language** (`/tmp/mattpocock-skills/skills/deprecated/ubiquitous-language/SKILL.md`)
"Deprecated" upstream because subsumed by grill-with-docs's CONTEXT.md flow, but as a standalone glossary-extraction skill it's still atomic and useful. Output format and rules sections are well-specified. Could fold into `engineering/documentation-and-adrs.yaml` or live standalone.

**design-an-interface** (`/tmp/mattpocock-skills/skills/deprecated/design-an-interface/SKILL.md`)
Deprecated upstream but pattern is strong: spawn 3+ sub-agents with deliberately-different constraints (minimize methods / maximize flex / common-case / paradigm-inspired), then compare/synthesize. Merge into `engineering/api-and-interface-design.yaml` as a "designing it twice" fragment, or import standalone alongside our `core/dispatching-parallel-agents.yaml`.

### IMPORT-MERGE (extract novel insight as fragment)

**tdd** → `core/test-driven-development.yaml` (currently 7 fragments). Add: (a) "Anti-Pattern: Horizontal Slices" fragment with the WRONG/RIGHT diagram; (b) tracer-bullet step naming; (c) per-cycle checklist; (d) explicit "never refactor while RED" rule. Our existing skill is generic; Matt's framing is sharper.

**diagnose** → `core/debugging-strategies.yaml` (15 fragments) and `core/debugging-and-error-recovery.yaml`. Add: (a) "Phase 1 = build a feedback loop is THE skill" reframe; (b) ordered list of loop-construction techniques; (c) instrumentation/regression-test/post-mortem split; (d) non-deterministic-bug fork. Our skill is checklist-heavy and lacks the "loop first, hypotheses second" hierarchy.

**to-prd** → `core/spec-driven-development.yaml`. Our SDD is gated and document-heavy (six core areas, approval checkpoint). Matt's PRD template is lighter and explicitly tied to a backlog item with `needs-triage`. Add as alternate "lightweight PRD" fragment + cross-reference.

**to-issues** → `core/planning-and-task-breakdown.yaml`. Already has vertical-slice section and Bad/Good example. Matt adds: (a) HITL vs AFK slice flag (decision-quality signal for agentic execution); (b) "tracer-bullet" naming convention; (c) issue-template (Parent / What to build / Acceptance / Blocked by). Merge as a fragment.

**request-refactor-plan** → `core/code-simplification.yaml`. The Problem/Solution/Commits/Decision/Testing/OOS template is a clean refactor-PRD. Add as a refactor-planning fragment.

### SKIP

`setup-matt-pocock-skills`, `git-guardrails-claude-code`, `migrate-to-shoehorn`, `scaffold-exercises`, `setup-pre-commit`, `edit-article`, `obsidian-vault`, `qa` (deprecated, covered by to-issues), `setup-pre-commit` — see table for reasons.

### DEFER

`write-a-skill` — compare line-by-line against `core/writing-skills.yaml` (currently TDD-for-skills framing, 11 fragments). If Matt's "Description Requirements" section adds discoverability rules we lack, merge that one fragment; otherwise SKIP.

## 3. Cross-cutting patterns worth extracting (even from SKIP/MERGE)

1. **CONTEXT.md as a lazy ubiquitous-language doc.** Created on demand during grilling; updated inline when fuzzy terms are sharpened. Distinct from formal DDD bounded contexts. Fragment candidate for `engineering/documentation-and-adrs.yaml`.
2. **HITL vs AFK slice tagging.** Per-issue flag indicating whether the slice can ship without human-in-the-loop. Useful signal for agentic execution prioritization. Fragment for `core/planning-and-task-breakdown.yaml` and `core/subagent-driven-development.yaml`.
3. **Sparing-ADR rule.** Offer ADR only when a future explorer would re-suggest the rejected option; skip ephemeral and self-evident reasons. Fragment for `engineering/architecture-decision-records.yaml`.
4. **Tracer-bullet vertical slice as the unit of TDD AND of issue decomposition.** Same primitive at two zoom levels — link in both `test-driven-development` and `planning-and-task-breakdown`.
5. **Auto-clarity exception list (caveman).** Reusable pattern for any "compressed mode" skill — drop compression for security warnings, destructive ops, multi-step sequences, repeated questions.
6. **Parallel-sub-agent constraint assignment.** Each agent gets a *different* constraint (not just "design it three times"). Fragment for `core/dispatching-parallel-agents.yaml`.
7. **Two-role triage (PM-mode / eng-mode) with state-override commands.** Reusable for any backlog-management skill.
8. **Section-DAG prose structuring (edit-article).** Even though the skill is off-domain, the underlying claim — "information is a DAG, order sections to respect dependencies" — is a fragment-worthy authoring rule. Could land in `core/writing-skills.yaml` or `core/documentation-overview.yaml`.

## 4. SDD overlap assessment

Our `core/spec-driven-development.yaml` (`raw_prose` ~7.9KB, gated with approval checkpoint covering six areas: requirements, success criteria, boundaries, etc.) is the **HITL/document-heavy** flavor of SDD. The spec is a single artifact that must be approved before code starts; the skill is explicitly named `phase_scope: null, always_apply: false, gated-workflow`.

Matt's loop — `grill-with-docs → to-prd → to-issues → tdd → diagnose → improve-codebase-architecture → zoom-out` — is the **AFK/atomic-artifact** flavor:

- Each step produces a small, named artifact (CONTEXT.md, PRD, issues, code+tests, ADR).
- The "spec" is distributed across CONTEXT.md (glossary), PRD (problem/user stories), and per-issue acceptance criteria — never one monolith.
- The unit of work is a tracer-bullet vertical slice, not a phase.
- HITL/AFK is tagged at the slice level, not the project level.
- No big approval checkpoint; quality gates are inline (grilling, ADR offers, regression tests).

**Where Matt's approach offers value our SDD doesn't:**
- Granularity matched to agentic execution (slice-sized work, not phase-sized).
- The "grilling loop" produces a sharper spec than a template-fill exercise — interrogation > form completion.
- HITL/AFK tagging gives a routing signal for parallel agent dispatch.
- CONTEXT.md as a *living* glossary built lazily during grilling, vs our SDD's "define boundaries up front."
- Lighter PRD template (~1KB vs ~8KB skill) reduces overhead for small features.

**Where ours wins:**
- Explicit success-criteria + boundaries (Always/Ask First/Never) — Matt has no equivalent gating on what an agent may touch.
- Approval checkpoint forces synchronization with humans on larger initiatives.
- The six-area structure handles cross-functional concerns (security, performance, rollout) that Matt's PRD template glosses.

**Recommendation:** keep both; cross-reference. Add a fragment to `core/spec-driven-development.yaml` saying "for atomic agentic flows, see `to-prd` + `to-issues` + `tdd` skills." Add a fragment to the imported `to-prd` saying "for HITL/cross-functional work, use `spec-driven-development` instead." Frame Matt's loop in pack metadata as the **agentic-AFK SDD variant**.

## 5. License / attribution plan

Matt's repo is MIT (`/tmp/mattpocock-skills/LICENSE`). Per-skill YAML metadata (already supported — `author` field, `change_summary` field):

```
author: mattpocock (adapted by navistone)
license: MIT
upstream: https://github.com/mattpocock/skills/blob/main/skills/engineering/<name>/SKILL.md
change_summary: imported from mattpocock/skills SKILL.md @ <commit-sha>; partitioned into N fragments
```

Add `THIRD_PARTY_LICENSES.md` (or extend an existing one) at repo root with the MIT header + attribution block listing all imported skill paths and upstream URLs. For IMPORT-MERGE skills, credit Matt in the fragment-level `change_summary` rather than the whole-skill author field.

## 6. Recommended next steps (effort-ordered)

1. **Quick wins (≤2h each):** Import `caveman`, `zoom-out`, `grill-me` as small standalone skills. No partitioning headaches; cheap retrieval value.
2. **Cross-cutting fragment merges (≤4h):** Add tracer-bullet/horizontal-slice fragment to `core/test-driven-development.yaml`; add "feedback-loop-first" fragment to `core/debugging-strategies.yaml`; add HITL/AFK fragment to `core/planning-and-task-breakdown.yaml`.
3. **CONTEXT.md / ubiquitous-language stack (≤1 day):** Import `grill-with-docs` and `ubiquitous-language` together (they share CONTEXT.md format). Decide whether CONTEXT.md format becomes its own skill or a fragment of `engineering/documentation-and-adrs.yaml`.
4. **Triage + improve-codebase-architecture (≤1 day):** Import as standalone skills. These are larger and reference assets (INTERFACE-DESIGN.md, ADR-FORMAT.md) — mirror those into the skill's reference material.
5. **SDD reconciliation (≤4h):** Author cross-reference fragments in both `core/spec-driven-development.yaml` and the imported `to-prd`/`to-issues` skills. Add the agentic-AFK-variant framing to pack metadata.
6. **Defer:** `write-a-skill` — only proceed if a careful diff against `core/writing-skills.yaml` reveals novel discoverability rules.
7. **Skip-but-mine:** Extract the section-DAG prose rule from `edit-article` and the parallel-sub-agent constraint-assignment pattern from `design-an-interface` as standalone fragments before discarding.

End of analysis.
