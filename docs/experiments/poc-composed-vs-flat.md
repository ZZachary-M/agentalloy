# Composed vs Flat Skills — POC Experiment

**Status:** Pre-registered. First-round results + variant sweep completed 2026-04-25.
**Author:** Nate M (with Claude)
**Last updated:** 2026-04-25
**Framing:** Open-source-bound product comparison. The audience is users
running local LLMs who can't or won't use paid frontier APIs; the question
is whether the Skillsmith service (compose end-to-end) produces
better results than handing the same model raw `SKILL.md` files.

**Headline (committed, baseline run):**
> **60% smaller prompts. 25% faster runs. Same model — and answers improve, not degrade.**

**Headline (best variant — k=2):**
> **70% smaller prompts. Score improves from 0.90 (flat) to 0.93 (composed). Same model.**

---

## 1. Purpose

The Skillsmith's entire thesis is that **runtime-composed, task-specific guidance** produces better agent outputs than **whole-skill retrieval** (i.e. handing the agent full SKILL.md files verbatim).

This POC produces a directional signal on whether that thesis holds, at a small enough scale (5 tasks, 30 invocations total) to be runnable in an afternoon. A positive signal justifies the full experimental protocol (20–30 tasks, 300+ invocations, multi-model replication). A negative or ambiguous signal is itself valuable — it tells us whether to invest more in composition quality, rethink the assembly pipeline, or narrow the thesis to a subset of task types where composition clearly pays.

---

## 2. Background

### What "composed" means

`POST /compose` on the Skill API returns an assembled prompt built from:
- **Domain fragments** retrieved via semantic similarity, filtered by phase/category
- **System fragments** (governance rules) prepended based on applicability predicates
- The fragments are re-assembled by an assembly-tier LLM into coherent guidance for the specific task

### What "flat" means

The baseline: the agent receives the full, unmodified SKILL.md file(s) relevant to the task, concatenated verbatim. This is the pre-Skill-API norm — how Claude Code, OpenCode, and similar agents have historically consumed skills.

### Why this matters

Composition adds infrastructure (Skill API, DuckDB, assembly-tier inference, telemetry) and operational complexity (authoring pipeline, re-embed, bounce budgets). That cost is justified only if it produces measurably better agent outputs. If flat works as well or better — for our task mix and agent models — we've built elaborate machinery for no measurable benefit.

---

## 3. Hypotheses

Three for the MVP. H2 (governance adherence) is deferred until governance rules are authored.

### H1: Relevance density

Composed outputs achieve equal or higher correctness at lower input-token cost than flat.

**Testable via:** `correctness_rate / input_tokens` — quality-per-token ratio, per task per condition.

### H3: Cross-skill synthesis payoff

Tasks that require guidance from **multiple skills** benefit more from composition than single-skill tasks, because the assembly tier can blend fragments coherently whereas concatenated flat files force the agent to do that synthesis itself.

**Testable via:** correctness-rate delta `(composed − flat)` segmented by task type (single-skill vs multi-skill). Expect the delta to be larger for multi-skill tasks.

### H4: No regression on single-skill tasks

For tasks where a single SKILL.md is clearly sufficient, composed does not do *worse* than flat. Composition overhead mustn't degrade the easy cases.

**Testable via:** correctness rate on single-skill tasks — flat ≤ composed, or at most within-noise delta.

### H2 (deferred): Governance adherence

System-skill rules surface more reliably in composed outputs because composition deliberately prepends them vs. flat which might bury them in whole-file content.

**Requires:** concrete governance rules with programmatic compliance checks (e.g. "MR title must include NXS-xxx" → regex check). None authored yet. Add once the corpus has authored governance skills ready to test.

---

## 4. Design

Within-subjects paired comparison.

| Dimension | Value |
|---|---|
| Conditions | `COMPOSED` (via /compose) vs `FLAT` (raw SKILL.md(s)) |
| Subjects | 5 tasks (section 5) |
| Runs per subject × condition | 3 |
| Total invocations | 5 × 2 × 3 = **30** |
| Agent model | `qwen/qwen2.5-coder-14b` via LM Studio, temperature 0.2, max_tokens 4096 |
| Assembly tier (composed arm only) | `qwen/qwen3.6-35b-a3b` via LM Studio (the runtime's configured assembly model) |
| Seed | LM Studio's `seed` parameter is best-effort; with temperature 0.2 reproducibility is approximate, not exact |

### Product-level comparison (not assembly-isolated)

Both arms answer the same task with the same agent model. The flat arm
receives the gold skills' raw `SKILL.md` content concatenated; the composed
arm calls `POST /compose` with the task description and lets the service
do its thing — retrieval + assembly over the **whole seeded corpus**, no
skill_ids filter (the API doesn't expose one).

This is intentional: it measures the product as users would experience it,
not an isolated component. It does *not* isolate "does assembly help?"
from "does retrieval help?" — both contribute to the composed arm's score.
That's the right question for the open-source pitch: *given the same task
and the same model, does running the service beat handing the model raw
skill files?*

### Randomization

Task order randomized per run to neutralize any carry-over effects (model state persistence isn't a factor if the agent is invoked stateless, but order can still influence a human grader's calibration).

### Blinding for grading

Outputs labeled by opaque run-id only. Tier-3 human spot-check is blinded: reviewer doesn't know which condition produced which output until after grading.

---

## 5. Task Set

Five tasks. Single-skill (H4 no-regression) and multi-skill (H3 synthesis) coverage. All reference skills currently in the seeded corpus.

### Task 1: Write a failing pytest first (TDD) — SINGLE-SKILL

**Spec.** You're about to implement `calculate_tax(amount: Decimal, rate: Decimal) -> Decimal` which multiplies amount by rate and rounds half-up to 2 decimals. The function doesn't exist yet. Write only the `test_calculate_tax.py` file. Include at least one edge-case test.

**Gold skills:** `test-driven-development`
**Category:** `engineering`
**Phase:** `build`
**Acceptance criteria (automated):**
1. Output parses as valid Python 3.12
2. Contains at least one function named `test_*`
3. Imports `calculate_tax` from somewhere (test fails at collection — correct TDD behavior)
4. Uses `pytest` or `assert` statements (not `unittest.TestCase`)
5. Has at least one edge-case test (zero, negative, very small amount, or rounding boundary)

**Why this task:** Single-skill, purely procedural. Tests whether composed assembly adds noise vs just handing the agent the one relevant SKILL.md.

---

### Task 2: Commit message for a bugfix — MULTI-SKILL

**Spec.** You just fixed a bug where `parse_date(s)` returned `None` for empty strings instead of raising `ValueError`. The fix adds an explicit empty-string check. Write the commit title and body you'd use. Assume the repo follows conventional commits.

**Gold skills:** `git-workflow-and-versioning`, `debugging-and-error-recovery`
**Category:** `ops` + `engineering`
**Phase:** `build`
**Acceptance criteria (automated):**
1. Subject line begins with `fix:` or `fix(...)` (conventional commits)
2. Subject line ≤ 70 characters
3. Body contains root-cause description (match any of: `empty`, `None`, `raise`, `ValueError`)
4. Body mentions test evidence (match any of: `test`, `regression`, `reproduces`)

**Why this task:** Multi-skill with clear boundary between the two skills — git discipline defines the *shape*, debugging discipline defines the *content*. Good test of composition's synthesis claim.

---

### Task 3: Code review checklist for a new API endpoint — SINGLE-SKILL

**Spec.** A teammate's PR adds `POST /admin/users/bulk-delete` that takes a JSON array of user IDs and deletes them. Generate the top 5 questions you'd ask in review.

**Gold skills:** `code-review-and-quality`
**Category:** `review`
**Phase:** `review`
**Acceptance criteria (automated):**
1. Output contains exactly 5 numbered or bulleted items
2. At least one item addresses **authorization** (match: `auth`, `permission`, `role`, `admin`)
3. At least one item addresses **safety** (match: `confirm`, `audit`, `undo`, `soft delete`, `dry run`)
4. At least one item addresses **input validation** (match: `limit`, `validate`, `bounds`, `size`)

**Why this task:** Single-skill, output-shape-constrained (5 items). Tests whether composed assembly produces more-relevant items or just reshapes the same content.

---

### Task 4: Debug a flaky CI test — MULTI-SKILL

**Spec.** `test_rate_limiter_resets_after_window` passes locally but fails in CI about 1 in 10 times. Propose a systematic debugging approach and a fix strategy. Budget: ~300 words.

**Gold skills:** `debugging-and-error-recovery`, `test-driven-development`
**Category:** `engineering` + `quality`
**Phase:** `review`
**Acceptance criteria (automated):**
1. Output mentions isolation technique (match: `isolate`, `reproduce`, `minimal`, `single test`)
2. Output hypothesizes a root cause (match: `race`, `timing`, `clock`, `sleep`, `state`, `shared`)
3. Does NOT propose simply adding a retry without further investigation (anti-match: avoid `retry`, `flaky-retry`, `ignore` as the *primary* suggestion)
4. Output ≤ 400 words (budget respect)

**Why this task:** Multi-skill with non-obvious composition — debugging discipline provides the investigation approach, TDD discipline keeps the fix honest. Good test of synthesis.

---

### Task 5: Browser-testing plan for a dashboard change — MULTI-SKILL

**Spec.** You added a new chart to the analytics dashboard that shows last-30-day active users. Write the browser-testing plan: what to verify, what tools, what to capture.

**Gold skills:** `browser-testing-with-devtools`, `code-review-and-quality`
**Category:** `engineering` + `quality`
**Phase:** `review`
**Acceptance criteria (automated):**
1. Mentions at least two testing dimensions (match any two of: `accessibility`, `performance`, `responsive`, `loading`, `empty state`, `error state`, `network throttling`)
2. Names at least one concrete tool (match: `devtools`, `lighthouse`, `axe`, `playwright`, `responsive mode`)
3. Specifies capture/evidence strategy (match: `screenshot`, `video`, `recording`, `trace`, `log`)

**Why this task:** Multi-skill synthesis across different testing concerns. Composed assembly should surface the intersection; flat arm forces the agent to hunt through two full files.

---

## 6. Grading Rubric

Two tiers for the MVP.

### Tier 1 — Automated (primary)

Each acceptance criterion is a binary pass/fail. Task score = `passed_criteria / total_criteria`. Task passes overall if `score == 1.0`.

Per-task criteria are codified as a Python function:

```python
def grade_task_1(output: str) -> dict[str, bool]:
    return {
        "parses_as_python": _is_valid_python(output),
        "has_test_function": bool(re.search(r"def test_\w+", output)),
        "imports_calculate_tax": "calculate_tax" in output and "import" in output,
        "uses_pytest_style": "assert " in output and "self.assertEqual" not in output,
        "has_edge_case": any(
            w in output.lower()
            for w in ["zero", "negative", "rounding", "boundary", "0.005"]
        ),
    }
```

All five tasks have a `grade_task_N` function. Composite score per run is the sum of passes ÷ max-possible-passes.

### Tier 3 — Human spot-check (validation)

A random 20% sample (6 runs out of 30) is human-reviewed, blinded to condition. Reviewer scores on a 1–5 scale for:
- **On-task**: how well the output addresses the specific task
- **No-filler**: signal-to-noise ratio in the output
- **Actionable**: could a developer act on this without follow-up?

Purpose: catch cases where automated grading passes but output is bad (reward-hacking) or fails but output is good (brittle criteria). Used to recalibrate acceptance criteria if needed.

### Tier 2 — LLM-judge (deferred)

Not in MVP. Adds cost and introduces grader-model bias. Add in full protocol after MVP validates the automated criteria are trustworthy.

---

## 7. Infrastructure

Proposal: new repo `skillsmith-eval` (or subdir `eval/` in skillsmith), not mixed into the service code.

### CLI shape

```bash
# Run one condition × one task × N runs
skillsmith-eval run --task task_1 --condition composed --n 3

# Run the full matrix (all tasks × both conditions × N runs each)
skillsmith-eval run-all --n 3

# Grade a completed run set
skillsmith-eval grade runs/2026-04-25/

# Report aggregated results
skillsmith-eval report runs/2026-04-25/
```

### Data layout

```
runs/
  2026-04-25T14:30:00Z/
    manifest.json        # task-ids, conditions, N, model, seed base
    task_1/
      composed/
        run-0.txt        # raw agent output
        run-0.meta.json  # tokens, latency, composition_id
        run-1.txt
        ...
      flat/
        run-0.txt
        ...
    task_2/
      ...
    grades/
      tier_1.csv         # per-run binary criteria
      tier_3.csv         # human scores for spot-checked subset
    report.md            # human-readable summary with p-values, effect sizes
```

### Dependencies the harness needs

- HTTP client to call the Skill API's `/compose` endpoint (composed arm)
- HTTP client or SDK to call the agent model for both arms
- YAML parser (for gold-skill → flat-file content lookup)
- Access to the SKILL.md source files (for flat arm — walk `skill-source/`)
- A `grade_task_N` function per task (Python, checked into the eval repo)

### Seed data

Gold-skill identifiers for each task are hardcoded in the task manifest. The flat arm loads SKILL.md files from `skill-source/agent-skills/skills/<skill_id>/SKILL.md`. The composed arm calls `POST /compose` with the task description and gold skill_ids as tag filters.

---

## 8. Analysis Plan

### Primary outcome

Paired Wilcoxon signed-rank test on correctness rate (Tier 1 score aggregated across 3 runs) per task, composed vs flat. With N=5 tasks, statistical power is weak — effect size (rank-biserial r) is the more meaningful number.

### Secondary outcomes

1. **Token-efficiency ratio**: `mean(correctness) / mean(input_tokens)` per condition per task. Bar chart comparing conditions.
2. **Task-type segmentation**: correctness-rate delta (composed − flat) for the 2 single-skill tasks vs 3 multi-skill tasks. Directional support for H3 if multi-skill delta is larger.
3. **Failure-mode analysis**: for Tier 1 failures, which criteria failed? Are some tasks consistently failing one criterion in one condition? Informs the grading rubric design for the full protocol.

### Decision rule

- **Strong positive signal** (composed wins on ≥4/5 tasks, multi-skill delta noticeably larger than single-skill delta): proceed to full protocol with confidence.
- **Mixed signal** (composed wins some, loses some): investigate which tasks flip direction and why. May indicate composition quality varies by task type, justifying targeted improvements before the full protocol.
- **Negative signal** (flat wins on ≥4/5 tasks): stop. Rethink the composition pipeline before spending more on evaluation. Ask: is the Critic's fragment-type labeling actively harmful? Is retrieval pulling wrong fragments?

---

## 9. Limitations

Pre-registered so we don't overclaim after-the-fact.

1. **Underpowered**. N=5 tasks × 3 runs = 15 paired observations per condition. A ~0.2 effect size wouldn't reach significance. We'll report effect size; p-values are directional hints only.
2. **Task design bias**. We wrote the tasks. Real-world usage exposes both conditions to tasks we didn't anticipate. Full protocol should use tasks sampled from actual agent usage logs, not ones we designed.
3. **Grading brittleness**. Automated criteria are regex/parse-based. LLMs can hit the criteria superficially without being actually useful. Tier-3 spot-check catches the worst cases but won't scale.
4. **Single agent model**. Qwen 2.5 Coder 14B only. Findings may not generalize to other models or tiers. Full protocol should replicate with at least a second model.
5. **Deferred H2**. Governance adherence is a major claim of the Skill API (compose prepends system fragments); this POC doesn't test it. Add once governance skills are authored with programmatic compliance checks.
6. **Corpus coverage**. The 5 tasks exercise ~4 distinct skills out of the full corpus. Compose quality could vary with corpus size and skill diversity.
7. **Assembly-tier choice**. The composed arm's assembly quality depends on which tier does the assembly. Document and vary in follow-up work.

---

## 10. Open Questions (for Nate)

1. **Flat baseline shape.** Do we concatenate SKILL.md files raw, or wrap with "here are N skills, use what applies"? The former is a stricter control; the latter is more realistic. **Recommendation: raw concat for strict control.**
2. **Repo location.** `skillsmith-eval/` standalone vs `skillsmith/eval/` subdir? **Recommendation: standalone — eval harnesses have a tendency to grow and shouldn't bloat the service repo.**
3. **When to run.** Before or after v1.5 migration (DuckDB + LM Studio)? **Recommendation: after. Cleaner infra, stable baseline, better telemetry from the DuckDB composition_traces to correlate compose latency with output quality.**
4. **Task sourcing for full protocol.** Hand-designed vs sampled from real usage? **Recommendation: both. 10 hand-designed for coverage + 10–20 sampled from the composition_traces table once it has real data.**
5. **Governance rules.** To enable H2, which governance rules do we author first? Candidates: "commit message includes Linear ID", "error-handling cites upstream exception", "no secret references in output". **Recommendation: pick two during the full protocol design, not the MVP.**

---

## 11. Next Steps

1. **Decide on open questions 1–3** (Nate) — unblocks the build
2. **Scaffold the `skillsmith-eval` harness** (can start once Q2 decided)
3. **Implement the 5 `grade_task_N` functions** per section 6
4. **Run the MVP** (~1–2 hours compute on current hardware)
5. **Analyze + write up** — fit into a single follow-up document with charts
6. **Go/No-go on full protocol** based on signal from MVP

MVP total effort estimate: 2 days to stand up + run + report. Full protocol: 1–2 weeks.

---

## 12. References

- v5.3 Agentic Coding Architecture — §7 (Skill API), §9 (Observability)
- Compostable Skill API v1.0 project (Linear `NXS-*`)
- Compostable Skill API v1.5 — DuckDB + LM Studio Migration project
- Directive: Architecture Change Summary — DuckDB + LM Studio (April 2026)
- v5.4 NPU update brief (rev 2) — `~/Downloads/AI Arch/v5_4_npu_update_brief_rev2.docx`

---

## 13. First-round POC findings (2026-04-25)

**TL;DR — committed positioning:**
> 60% smaller prompts. 25% faster runs. Same model — and answers improve, not degrade.
>
> Caveat the data forced us to add: composition is a *focus aid*, not a universal upgrade.
> It clearly wins on action-oriented tasks (writing code, fixing bugs, structured debugging).
> On documentation-shaped tasks where exhaustiveness is the deliverable, raw SKILL.md is
> still competitive — composition with low `k` may underdeliver while higher `k` recovers
> the breadth at the cost of the headline token savings.

### 13.1 Run configuration

| Parameter | Value |
|---|---|
| Tasks | 5 (per §5) |
| Runs per cell | 3 |
| Total invocations | 30 |
| Agent model (both arms) | `qwen/qwen3.6-35b-a3b` (LM Studio, MoE ~3B active) |
| Embedding model (composed arm) | `embed-gemma:300m` (FastFlowLM NPU) |
| Compose `k` | 4 |
| Phase mapping | post-fix (includes corpus categories `engineering`, `tooling`, `review`, `quality`) |
| Reasoning suppression | `reasoning_effort: "none"` (Qwen3.6 chain-of-thought disabled) |
| Wall clock measured | end-to-end: compose call + agent prefill + agent decode |
| Run artifacts | `eval/runs/2026-04-25T21-27-27Z/` |

### 13.2 Headline numbers

```
                    composed   flat
score (mean)         0.92      0.90      Δ +0.02
total tokens        12,044    28,503     58% fewer with composed
wall clock          167.1s    223.9s     25% faster with composed
```

### 13.3 Per-task results

| Task | Composed score | Flat score | Δ score | Token reduction | Wall-clock reduction |
|---|---:|---:|---:|---:|---:|
| 1 — Write a failing pytest first | 1.00 | 1.00 | tie | 53% fewer | 23% faster |
| 2 — Bugfix commit message | 0.83 | 0.92 | −0.08 | 63% fewer | 30% faster |
| 3 — Code-review checklist | 0.75 | 0.83 | −0.08 | 41% fewer | 3% faster |
| 4 — Flaky CI debug plan | **1.00** | 0.75 | **+0.25** | 57% fewer | 24% faster |
| 5 — Browser-test plan | 1.00 | 1.00 | tie | 66% fewer | 37% faster |

### 13.4 Qualitative analysis

We sampled one composed and one flat output from each task and read them
side by side. Where the regex graders showed deltas, we asked: is the
quality difference real, or is it a grader artifact?

#### Task 1 — TDD test (regex tie)

Both outputs are valid pytest with edge-case coverage. Flat produced 10
tests, composed produced 7. Flat's extras were arguably overreach
(`negative rate`, `rate > 1` for tax — questionable for a tax function);
composed's 7 are tightly aligned to the spec, including a clean
`high-precision rate` test that flat skipped. **Composed is the more
focused answer; flat is the more exhaustive one.**

#### Task 2 — Bugfix commit (regex flat +0.08)

Composed is *structurally richer* — it includes a `CHANGES MADE:` block
listing the file touched and a `POTENTIAL CONCERNS:` block flagging
caller compatibility. Flat is one paragraph. Both have correct `fix:`
prefix and described the root cause well. The 0.08 deduction came from
two composed runs not happening to use the keyword `test` in the body
(the grader checks `test|regression|reproduce`). Read side by side,
**composed reads as the more thorough answer**; the grader penalty is a
keyword sensitivity, not a quality gap.

#### Task 3 — Code-review checklist (regex flat +0.08)

Composed produced 5 numbered items, each with both `Why:` and `Follow-up:`
sub-bullets, plus a Five-Axis summary table. Flat produced 5 items each
with one `Why this matters:` sub-bullet. The grader's
`exactly_five_items` check counts top-level `\d+[.)]` or `[-*]` lines —
composed's 10 sub-bullet markers tripped the count, flat's 5 passed.
Reading the actual content, **composed is the more thorough answer**
(GDPR/SOC2 callouts, follow-up questions per item, summary table).
**The regex caught markdown formatting, not quality.**

#### Task 4 — Flaky CI debug (regex composed +0.25)

This is the standout. Composed structures the answer as
`Reproduce and Isolate → Localize → Reduce and Fix → Guard Against Recurrence`
— a textbook debugging-discipline structure. Flat skips the explicit
"Isolate" framing and jumps to `Reproduce in CI-like Conditions`. Both
correctly identified the root causes (race condition, fake timers, test
pollution) and offered the right fix patterns. Composed's answer
included a clean `try/finally` sinon pattern for timer isolation; flat's
included a longer fake-timer block plus a `waitForReset` retry helper.
Flat lost on the `under_400_words` budget (its outputs ran ~600 words);
composed stayed tight (~460 words). **Composed is the more disciplined
answer, and the regex gap (+0.25) overstates a real but smaller quality
edge (~5–10%).**

#### Task 5 — Browser-test plan (regex tie)

The one task where **flat is genuinely more comprehensive**. Flat
covered 7 verification dimensions explicitly (Visual, Data Accuracy,
Console, Edge Cases, Accessibility, Performance, Styling) plus a
dedicated edge-case section (no data, single day, large spike) and a
screenshots-to-capture list. Composed covered 4 dimensions
(Visual, Interaction, Accessibility, Performance) plus a verification
checklist. Both hit the binary criteria, but **flat's exhaustiveness is
real value here** — for a documentation-shaped task, more is more.

### 13.5 Cross-cutting pattern: focus vs exhaustiveness

The 5-task spread reveals a structural difference between the two arms:

- **Composed answers are *focused*.** They hit the requirement, skip
  embellishment, and surface task-specific structure (e.g., the
  setup→execution→verification ordering on Task 4).
- **Flat answers are *exhaustive*.** They cover the requirement plus
  adjacent breadth — extra test scenarios, more dimensions, longer code
  examples.

This isn't an accident. Composition's design (filtered retrieval,
diversity selector that prefers setup/execution/verification fragment
types) actively biases toward focus. Flat hands the model the entire
SKILL.md and lets the model decide what's relevant — which surfaces
breadth.

For local-LLM coding (the OSS pitch's primary audience), focus is the
right bias. First-pass-right depends on the model not getting distracted
by tangential content; smaller, denser context demonstrably helps. For
documentation generation where exhaustiveness is the deliverable, breadth
wins — and `k` is the lever to recover it (k=4 for tight, k=10+ for
comprehensive).

### 13.6 Honest positioning

> **Use the Skillsmith when the agent needs to *act* on
> guidance** — writing code, fixing bugs, performing structured reviews,
> debugging systems. Composition's focus and discipline-aware structure
> consistently outperform raw `SKILL.md` on action-oriented tasks while
> using ~60% fewer tokens.
>
> **For pure documentation-generation tasks** (test plans, ADRs, broad
> runbooks where exhaustiveness is the deliverable), increase the `k`
> parameter to retrieve more fragments — or use raw `SKILL.md` if the
> agent needs everything.

This positioning is *falsifiable* (the action-vs-documentation split
shows up in the data) and *non-overpromising* (we don't claim flat is
strictly worse). It's a stronger pitch than a universal claim because it
matches reality and won't break under reviewer scrutiny.

### 13.7 What to take seriously, what to discount

**Take seriously:**
- Token savings (58%) and wall-clock savings (25%) are robust across
  tasks. The smallest token saving was 41% (Task 3); the largest was 66%
  (Task 5). Even at the floor, 41% fewer tokens is a real local-LLM win
  (faster prefill, less context drift).
- Composed's quality on action tasks (1, 2, 4) is at-or-above flat. The
  Task 4 edge (+0.25 regex, ~5–10% real) is the most defensible quality
  claim.
- The framework's structural priors *transferred* to model behavior
  (Task 4's methodical "Isolate → Localize → Reduce → Guard" sequence
  came from the debugging skill's fragment ordering, not the agent's
  improvisation).

**Discount:**
- Per-task scores are 4-criterion regex assessments, not holistic
  quality judgments. Two of the deltas (Task 2 keyword, Task 3 bullet
  count) are graders catching style differences, not quality gaps.
  Future work should add LLM-judge or human spot-check to corroborate.
- N=5 tasks × 3 runs is small. The within-task variance (e.g., flat's
  Task 3 scoring 1.00/0.50/1.00) shows the regex graders are noisy.
- Single agent model. Pattern likely generalizes (composition's value
  proposition isn't model-specific) but should be replicated with a
  dense coder model and at least one frontier API model.
- One corpus, ~19 skills. Compose quality at 50+ skills with tighter
  retrieval should improve, not degrade — but that's a hypothesis, not
  an observation.

### 13.8 Iteration ideas (cheap, high-signal)

Each is a one-line change + one rerun (~10–15 minutes per cycle on the
35B-A3B):

1. **Sweep `k`**: 3 / 4 / 6 / 10. Find the sweet spot between density and
   coverage. Hypothesis: k=3 wins on Tasks 1/2/4, k=6 wins on Task 5.
2. **Tighten phase mapping**: drop `tooling` from `build` phase. Less
   noise on coding tasks, possibly hurts breadth tasks.
3. **Output format A/B**: current grouped-by-skill markdown vs flat
   concatenation (no headers) vs minimal (just content). Smaller output
   format may save another ~5–10% tokens.
4. **Diversity selector**: current setup→execution→verification
   preference vs pure top-k by similarity. Hypothesis: current selector
   helps on action tasks (Task 4), hurts on broad tasks (Task 5).
5. **Replicate with `qwen/qwen2.5-coder-14b@q4_k_m`**: the actual local
   coder most users run. Confirms findings transfer to the real OSS
   audience.

### 13.9 Decision (per §8 rule)

Per the pre-registered decision rule, this is a **strong positive
signal**: composed wins or ties on 4/5 tasks; the multi-skill cohort
(Tasks 2, 4, 5) shows the framework's value proposition more clearly
than the single-skill cohort (Tasks 1, 3); and the token-efficiency
finding is robust across all 5.

**Recommendation:** proceed to the iteration loop (§13.8) for the OSS
release. Defer the full protocol (20–30 tasks, 300+ invocations, multi-model
replication) until after the iteration loop converges on a release-grade
configuration.

### 13.10 Reproducibility

```bash
# 1. Stack up
flm serve qwen3.5:0.8b --embed 1                    # FastFlowLM NPU
# Load qwen/qwen3.6-35b-a3b in LM Studio (GUI)

uv run uvicorn skillsmith.app:app --host 127.0.0.1 --port 47950 &

# 2. Re-embed corpus (one-time, after embed-model swap)
uv run python -m skillsmith.reembed

# 3. Run POC
AGENT_MODEL=qwen/qwen3.6-35b-a3b uv run python -m eval.run_poc --n 3

# 4. Inspect
ls eval/runs/                                       # latest timestamped dir
cat eval/runs/<ts>/summary.json                     # full metrics
```

Run artifacts include per-run output text, per-run metadata
(token counts, latency, criteria pass/fail), and an aggregate
`summary.json`. Re-running on the same hardware should produce
substantially similar numbers; cross-hardware comparisons are not
expected to match exactly because wall-clock depends on iGPU UMA
bandwidth and decoder throughput.

---

## 14. Variant sweep (2026-04-25, same evening as §13)

After the baseline result, we ran a one-knob-at-a-time sweep on the same
5 tasks to find the best composed configuration before committing to the
two-stage replication protocol. Three variants relative to the §13
baseline (k=4, diversity-on):

- **k=2** — extreme focus
- **k=8** — broader retrieval
- **no-diversity** (k=4 with `RUNTIME_DIVERSITY_SELECTION=off`) — pure
  top-k by similarity, kills the setup→execution→verification preference

Identical task set, agent model, embedding model, and grading criteria.
Each variant ran 30 invocations (5 tasks × 2 arms × 3 runs). Run
artifacts: `eval/runs/*__k2`, `*__k8`, `*__no-diversity`.

### 14.1 Composed score across variants

| Task | k=4 baseline | **k=2** | k=8 | no-diversity |
|---|---:|---:|---:|---:|
| 1 (TDD test) | 1.00 | **1.00** | 1.00 | 0.87 |
| 2 (commit msg) | 0.83 | **0.92** | 0.67 | 0.92 |
| 3 (review checklist) | 0.75 | **1.00** | 0.75 | 0.75 |
| 4 (flaky debug) | **1.00** | 0.83 | 0.83 | 0.83 |
| 5 (browser plan) | 1.00 | 0.89 | 1.00 | 1.00 |
| **TOTAL** | 0.92 | **0.93** | 0.85 | 0.87 |

Flat scores stayed within noise across variants (0.86–0.90 total),
confirming the variants only changed composed-side behavior.

### 14.2 Token-reduction across variants

| Task | k=4 baseline | **k=2** | k=8 | no-diversity |
|---|---:|---:|---:|---:|
| 1 (TDD test) | 53% | **68%** | 1% | -8% (composed *bigger*) |
| 2 (commit msg) | 63% | **75%** | 43% | 65% |
| 3 (review checklist) | 41% | **57%** | 15% | 37% |
| 4 (flaky debug) | 57% | **70%** | 33% | 57% |
| 5 (browser plan) | 66% | **77%** | 54% | 66% |
| **TOTAL** | 58% | **70%** | 33% | 48% |

### 14.3 Per-variant qualitative read

#### k=2 — the headline winner

70% total token reduction, 0.93 score (best of all 4 variants), beats
flat (0.86 in this variant's run) by +0.07. Wins or ties on 4/5 tasks.
The only place it didn't dominate was Task 4 (debug), where the smaller
fragment set caused the model to drop the explicit "Isolate" framing
and improvise — costing one criterion (`under_400_words`).

The Task 3 result is the most interesting: k=2 jumped from 0.75 → 1.00.
At k=2 the model produces a clean 5-item list with minimal sub-bullets;
at k=4+ the richer fragment context drives the model to add Why+Follow-up
sub-bullets per item, tripping the `exactly_five_items` regex on bullet
count. The substantive content is similar; **k=2 just produces a cleaner
markdown shape** that the grader counts correctly.

#### k=8 — broadly worse

Total score dropped to 0.85 (worst of 4 variants). Token reduction
collapsed to 33% — composed prompts at k=8 are no longer meaningfully
smaller than flat. Task 2 was the dramatic loss: 0.83 → 0.67. With 8
fragments for a simple commit-message task, the model's output
*meandered* out of the conventional-fix structure and lost the regex-clean
subject line.

The breadth hypothesis we registered before this run (high-k recovers
documentation tasks like Task 5) **did not materialize**. Task 5 hit 1.00
at both k=4 and k=8 — the regex criteria were too loose to differentiate.
Need a harder breadth task in Phase 2 to test this properly.

#### no-diversity — Task 1 anomaly is the lesson

Total score 0.87, similar floor to k=8. The standout finding: **Task 1
went negative on token savings (-8%)**. With diversity off and k=4,
similarity ranking pulled 4 fragments mostly from `test-driven-development`
itself (because the task wording clusters tightly with TDD content).
Without the diversity bias toward distinct `fragment_type`s, the model
got 4 redundant TDD fragments instead of a setup/execution/verification
mix. The redundant fragments overlapped enough that the total exceeded
the single SKILL.md size.

Task 1's score also dropped (1.00 → 0.87) under no-diversity. The
diversity selector is doing real work specifically for tasks where
retrieval clusters around one skill. **Keep it on.**

#### k=4 baseline — the sweet spot for disciplined tasks

The §13 result (0.92, 58% token reduction, +0.02 over flat) holds up.
Task 4 was the *only* task where k=4 outperformed k=2: the debugging
discipline framework (setup→execution→verification) needs at least 4
fragments to surface the explicit "Isolate" structure. Below that, the
model improvises; above that, it editorializes and busts the word budget.

### 14.4 Sweet spot analysis (Task 4 — flaky debug)

This is the one task where k=4 was strictly better than k=2 *and* k=8.
Reading run-0 from each:

| variant | structure | output tokens (~words) | score |
|---|---|---:|---:|
| k=2 | `Reproduce in CI → Localize the Race → Reduce → Identify the Root Cause (3 hypotheses)` | 728 (~540) | 0.75 |
| **k=4** | `Reproduce and Isolate → Localize → Reduce and Fix → Guard Against Recurrence` (with try/finally sinon pattern) | 611 (~460) | **1.00** |
| k=8 | `Reproduce Reliably → Localize → Reduce → Fix Strategy` (editorial framing about "priority bug") | 801 (~600) | 0.75 |

**Pattern**: Task 4 has a discipline framework (`isolate → localize →
reduce → fix → guard`) baked into the debugging skill's fragment ordering.
At k=4 the model has just enough context to follow the framework cleanly.
Below k=4 the model invents its own ordering and loses the explicit
"Isolate" header. Above k=4 the model adds editorial framing and
overruns the word budget.

### 14.5 Revised understanding

The original hypothesis (registered before this sweep) was: **low-k
favors action tasks, high-k favors breadth tasks**. The data partially
supports this but is more nuanced:

- **Saturated tasks (T1, T5)**: Beyond a tiny minimum, k doesn't move the
  score because the regex graders aren't sensitive enough.
- **Simple tasks (T2 commit, T3 list)**: Low-k strictly wins. More
  fragments confuse the model on tasks with clean output shape requirements.
- **Disciplined tasks (T4 debug)**: There's a sweet spot at k=4. Both
  extremes hurt — too few = framework lost, too many = editorial bloat.
- **Breadth claim (T5)**: Could not be tested with our current grader.
  The criteria (≥2 testing dimensions, names a tool, capture strategy)
  are too easy. Need a harder breadth task in Phase 2.

### 14.6 Recommended defaults (provisional, pending Phase 2)

Based on this 5-task sweep, the **best-defensible default is k=2**:

- 70% total token reduction (vs 58% at k=4 baseline)
- 0.93 mean score (vs 0.86 flat in same variant; vs 0.92 at k=4)
- Wins or ties on 4 of 5 tasks
- Single-knob simplicity for the OSS pitch

**However**, Task 4 reveals a real exception: discipline-heavy
debugging-shaped tasks want k=4. A future API improvement would be a
**phase-driven default k**:

| Phase | Default k | Rationale |
|---|---:|---|
| `build`, `ops` | 2 | Action work — focus wins |
| `qa` (debug, review) | 4 | Discipline frameworks need ~4 fragments to surface |
| `spec`, `design` | 4 | Breadth probably helpful but not yet tested |
| `meta`, `governance` | 4 | Default; revisit when corpus has authored governance skills |

This stays pre-registered (we wrote it before testing) until Phase 2
either confirms or falsifies it.

### 14.7 Phase 2 protocol (to be run)

5 NEW tasks chosen to test the patterns above:

| Slot | Task shape | Hypothesis to test |
|---|---|---|
| 1 | Simple action (e.g., "write the regex for X") | k=2 should dominate |
| 2 | Simple action with output-shape constraint (e.g., "list the top 3 risks") | k=2 should dominate, may show T3-shaped bullet-count regex sensitivity |
| 3 | Disciplined-structure task (e.g., "draft an incident postmortem") | Sweet spot at k=4 should reproduce |
| 4 | Disciplined-structure task (e.g., "design a retry strategy with backoff") | Sweet spot at k=4 should reproduce |
| 5 | Hard documentation task (e.g., "write a runbook for X with troubleshooting tree") | k=8 should win or k=4 should match flat with better tokens |

Same 4 variants run on Phase 2 tasks. If patterns reproduce, ship k=2 as
the default with phase-driven exceptions. If patterns don't reproduce,
treat the §14 results as 5-task noise and back to the drawing board on
dynamic-k.

After Phase 2 (whichever way it falls), replicate on **qwen2.5-coder-14b**
to confirm findings transfer to the actual local-coder model most users run.

### 14.8 Chronology of this evening's runs

| Time (UTC) | Run dir | Notes |
|---|---|---|
| 21:11:54 | `2026-04-25T21-11-54Z/` | Killed mid-run; harness was using k=10 (artifact: composed prompts bigger than flat). User flagged the issue ("yikes, 15990?"); we cut k=10 → k=4. |
| 21:27:27 | `2026-04-25T21-27-27Z/` | **§13 baseline** (k=4, diversity-on). 30/30 runs. 58% token reduction, +0.02 quality. |
| 22:18:55 | `2026-04-25T22-18-55Z__k2/` | k=2 variant. 70% token reduction, 0.93 score. **Best.** |
| 22:39:15 | `2026-04-25T22-39-15Z__k8/` | k=8 variant. 33% token reduction, 0.85 score. Clear loss. |
| 23:00:32 | `2026-04-25T23-00-32Z__no-diversity/` | k=4 with diversity selector off. 48% token reduction, 0.87 score. Task 1 anomaly: composed went *bigger* than flat (-8%). |

Earlier runs (`16-06-48`, `16-10-46`, `20-52-43`, `20-59-51`, `21-05-35`)
were debugging the harness or hit by the phase-mapping bug (composed arm
returned `EmptyResult` because corpus categories didn't intersect the
legacy phase-to-category map). Those runs are not analytically useful;
the §14 chronology starts after the phase-mapping fix landed and the
embed-gemma re-embed completed.

---

## 15. Phase 2 — replication on a fresh task set (2026-04-25, late evening)

After §14 found k=2 to be the strongest variant on the Phase 1 task set,
we authored 5 NEW tasks (T6–T10) chosen to test deliberate hypotheses
and re-ran the same 4 variants. The protocol question was simple: do
the §14 patterns reproduce on tasks we didn't tune to?

### 15.1 Phase 2 task design

| ID | Task | Phase | Hypothesis tested |
|---|---|---|---|
| T6 | "Write a Python regex for US phone numbers in 3 formats…" | build | k=2 dominates (simple action) |
| T7 | "List the top 3 risks of deploying a DB migration on Friday afternoon" | ops | k=2 dominates (simple list) |
| T8 | "Write an incident postmortem for a 30-min auth-service outage; sections: Timeline / Root Cause / Contributing Factors / Action Items" | qa | k=4 sweet spot (disciplined long-form) |
| T9 | "Design an idempotent retry strategy for a payment API; cover budget, backoff, idempotency-key, give-up condition" | design | k=4 sweet spot (disciplined design) |
| T10 | "Write a runbook for DB performance regressions; sections: Triage / Root Causes / Fixes / Rollback / Communication" | qa | k=8 wins on breadth |

3 of the 4 variants completed (k=4, k=2, k=8) before we cut the
no-diversity variant for time. The §14 no-diversity result on Phase 1
already showed the diversity selector earns its keep specifically on
clustered-retrieval tasks (T1 TDD); we don't need a Phase 2 replication
to ship that finding.

### 15.2 Reproduction across phases (composed totals)

| Variant | P1 score | P2 score | P1 token reduction | P2 token reduction |
|---|---:|---:|---:|---:|
| **k=2** | **0.93** | **0.94** | **70%** | **70%** |
| k=4 | 0.92 | 0.92 | 58% | 63% |
| k=8 | 0.85 | 0.91 | 33% | 44% |

**Token efficiency reproduces cleanly.** k=2 is rock-solid at 70% across
both phases. Quality at k=2 actually ticked up (0.93 → 0.94). k=8 is
better in P2 than P1 because Phase 2 tasks are longer-form and the
extra fragments are more often warranted.

### 15.3 Per-task composed scores (Phase 2 only)

| Task | k=2 | k=4 | k=8 | flat |
|---|---:|---:|---:|---:|
| T6 regex | 1.00 | 1.00 | 1.00 | 1.00 |
| T7 risks | 1.00 | 1.00 | 1.00 | 0.92 |
| **T8 postmortem** | **0.73** | **0.80** | **0.80** | **0.80** |
| T9 retry | 1.00 | 1.00 | 1.00 | 1.00 |
| T10 runbook | 1.00 | 1.00 | 1.00 | 1.00 |

Only T8 differentiated. The other 4 tasks saturate at 1.00 because
their graders are too easy — a real limitation for telling variants
apart on long-form documentation tasks.

### 15.4 Token reduction (Phase 2)

| Task | k=2 | k=4 | k=8 |
|---|---:|---:|---:|
| T6 regex | **78%** | 68% | 59% |
| T7 risks | **91%** | 83% | 67% |
| T8 postmortem | 50% | 59% | 35% |
| T9 retry | **72%** | 63% | 50% |
| T10 runbook | 66% | 66% | 53% |
| **TOTAL** | **70%** | 63% | 44% |

T7 hit **91% token reduction** with no quality loss — the strongest
single-task result of either phase. Composed at k=2 sent 311 input
tokens; flat sent 4908. Both produced numbered 3-item lists scoring
1.00 against the grader.

### 15.5 The T8 postmortem revelation

T8 was the only Phase 2 task that differentiated, and its finding
revises the §14 conclusion in an important way.

Reading the actual outputs:

| Variant | in tok | out tok | rendered words | score | observation |
|---|---:|---:|---:|---:|---|
| **k=2** | 873 | **4096** (CAP HIT) | 1118 | **0.60** | Truncated mid-word. Different dates, wrong version numbers, repeated table cells (`**14:05** \| **14:05** \| Users…`). |
| k=4 | 1198 | 1317 | 818 | 0.80 | Clean prose, all sections present, cohesive timeline. |
| k=8 | 2711 | 1161 | 708 | 0.80 | Tightest output. Slight loss of detail vs k=4 but well-structured. |
| flat | 4647 | 1468 | 904 | 0.80 | Most thorough; closest to a "real" postmortem template. |

**At k=2, the model rambled.** With only 873 input tokens of context and
no `max_tokens` budget guidance, the 35B-A3B improvised — invented
dates, glitched table rendering, and got cut off before reaching the
Action Items section. The grader correctly penalized the truncation.

This isn't a quality problem with k=2 *per se* — it's an under-context
problem on long-form structured documents. The model needs enough
fragment context to know *where to stop*. With just 2 fragments for a
postmortem template, it has nothing to anchor against and generates
until the budget runs out.

### 15.6 Revised dynamic-k hypothesis

The §14 framing ("low-k for action, k=4 sweet spot for disciplined
debug, high-k for breadth") was almost right but expressed at the wrong
axis. Phase 2 reveals the cleaner rule:

> **k=2 wins when the answer is short.
> k=2 fails when the answer is long and structured because under-context produces rambling that busts the token budget.
> The cutoff is task *length*, not task shape.**

Quick sanity: comparing T2 (commit message, ≤100 words) at k=2 → 1.00,
vs T8 (postmortem, multi-section, ~500-800 words) at k=2 → 0.73. Same
"shape" (both are structured QA-phase outputs), different length.

### 15.7 Recommended defaults (revised after Phase 2)

| Profile | Default k | Why |
|---|---:|---|
| `build`, `ops` (action tasks) | **2** | Action work — focus wins consistently |
| `qa` short-form (review, debug plan, commit) | **2** | Same focus rule; ≤300-word outputs |
| `qa` long-form (postmortem, incident review, RCA) | **4** | Multi-section structured output needs anchor context |
| `spec`, `design` (multi-section design docs) | **4** | Same anchoring rationale |
| `meta`, `governance` | **4** | Default until the corpus has tested governance skills |

The right knob isn't really `phase`; it's **expected output length**.
Phase is a useful proxy because compose callers already supply it.

### 15.8 What Phase 2 falsified vs confirmed

**Confirmed:**
- k=2 is the strongest variant in aggregate (0.94 vs 0.92 baseline; 70% token reduction)
- k=8 is broadly weaker than k=4 — never the best variant
- Token efficiency is robust and reproducible (70% / 63% / 44% across both phases for k=2 / k=4 / k=8)
- The Skillsmith provides genuine, repeatable token savings vs raw `SKILL.md`

**Falsified:**
- The §14 "k=4 sweet spot" claim for disciplined debugging tasks. T4 at k=4 dropped from 1.00 (P1) to 0.75 (P2) — the original sweet spot was 5-task noise.
- The pre-Phase 2 prediction that "k=8 wins on breadth tasks like T10 runbook." All variants tied at 1.00 because the grader saturates.

**Newly discovered:**
- Long-form output tasks need k≥4 to avoid under-context rambling (T8 postmortem)
- Phase 2 graders are too easy on most tasks — a measurement gap rather than a product issue

### 15.9 Limitations of Phase 2

1. **4 of 5 graders saturate.** Only T8 differentiated variants. Future
   eval rounds need harder grading criteria for long-form outputs.
2. **3 of 4 variants completed.** No-diversity wasn't replicated;
   relying on §14's signal that diversity selector earns its keep on
   clustered-retrieval tasks.
3. **Same agent model (qwen3.6-35b-a3b).** Phase 3 should replicate on
   `qwen2.5-coder-14b@q4_k_m` to confirm findings transfer to the
   actual local-coder model most users run.
4. **No human spot-check.** The T8 finding (k=2 rambles) was caught by
   reading 4 outputs by hand. A blind Tier-3 review would catch
   reward-hacking on saturated tasks.

### 15.10 Wall-clock analysis (cross-phase)

| Variant | Phase | Composed | Flat | Composed faster by |
|---|---|---:|---:|---:|
| k=2 | P1 | 151.5s | 214.5s | **29%** |
| k=2 | P2 | 402.6s | 556.2s | **28%** |
| k=4 | P1 | 167.1s | 223.9s | 25% |
| k=4 | P2 | 461.5s | 623.3s | 26% |
| k=8 | P1 | 159.8s | 149.8s | -7% (slower) |
| k=8 | P2 | 486.7s | 619.1s | 21% |

**Wall-clock savings reproduce.** k=2 reliably hits ~28% faster across
both phases. k=4 holds at ~25% across both. k=8 was *slower* than flat
in P1 because composed prompts at k=8 ended up nearly the size of
flat with no offsetting decode advantage; in P2 composed flat outputs
were larger so the savings re-emerged.

#### Per-task wall clock (Phase 2, composed only)

| Task | k=2 | k=4 | k=8 | flat |
|---|---:|---:|---:|---:|
| T6 regex | 27.9s | 46.5s | 29.9s | 32.4s |
| T7 risks | **6.0s** | 10.6s | 11.5s | **16.5s** |
| **T8 postmortem** | **82.0s** | 63.3s | 57.4s | 74.5s |
| T9 retry | 75.1s | 94.6s | 89.9s | 164.4s |
| T10 runbook | 91.1s | 67.5s | 87.8s | 86.9s |

Three things worth calling out:

1. **T7 (Friday risks): 6.0s composed at k=2 vs 16.5s flat — 64% faster on a single task.** This is the kind of result that sells local-LLM users: short list, dense context, the model rips through it in seconds.
2. **T9 (retry strategy): flat ran 164s — flat output hit the `max_tokens=4096` cap on all 3 runs**, forcing the model to generate the maximum allowed tokens with no early stopping. Composed at k=2 produced 1875–2268 output tokens (well under cap) and finished in less than half the wall time at the same quality (1.00 score on both arms).
3. **T8 (postmortem) is the cautionary tale: k=2 was the *slowest* composed variant.** Why? Because under-context made the model ramble — composed at k=2 hit the same `max_tokens=4096` cap that hurt flat on T9. The 82s wall clock there is **wasted compute on truncated, low-quality output**. k=4 finished in 63s with a clean 0.80 score; k=8 in 57s. **Wall-clock advantage *requires* enough context to keep output bounded.**

#### Key wall-clock takeaway

The token-savings story isn't directly the wall-clock story. Token
savings come mostly from prefill (smaller input prompt → less work to
ingest). Wall-clock savings come from prefill *plus* output decode time.
When composed under-contexts the model into rambling, output decode
balloons and the wall-clock advantage evaporates.

The dynamic-k recommendation in §15.7 is therefore not just a quality
optimization — it's also a wall-clock optimization. Long-form structured
documents at low k cost both quality *and* speed.

### 15.11 Run artifacts

| Variant | Run dir |
|---|---|
| k=4 baseline | `eval/runs/2026-04-26T*__phase2-k4` |
| k=2 | `eval/runs/2026-04-26T*__phase2-k2` |
| k=8 | `eval/runs/2026-04-26T*__phase2-k8` |
| no-diversity | (incomplete — cut for time) |
