# Skill YAML Quality Review — Corpus-Wide

**Date:** 2026-04-28
**Reviewer:** Claude Opus 4.7 (1M)
**Scope:** All `*.yaml` under `src/skillsmith/_packs/` (active corpus, 468 skills, 36 packs) and `skill-source/pending-review/` + `skill-source/needs-human/` (79 staged skills).
**Method:** schema sample, programmatic structural scan against the contract in `fixtures/skill-authoring-agent.md` and `fixtures/skill-authoring-guidelines.md` (R1–R8).
**Question asked:** Do the YAMLs deliver what skillsmith promises — composition-quality, retrieval-friendly fragments — or do they look ingest-valid but compose poorly?

---

## TL;DR

The contract in `fixtures/skill-authoring-agent.md` (fragment diversity, 80–800 word window, single-intent slices, 2–5 retrieval tags) is **not enforced by `ingest.py`** beyond contiguity, valid types, and at-least-one `execution`. The validator passes; the quality bar set by the authoring contract does not. The result is a bimodal corpus:

- **A small high-quality stratum** (~5 hand-authored batch-2/3 skills: `webhook-patterns`, `graphql-server-patterns`, `sentry-error-tracking`, `feature-flags-openfeature`, `websocket-scaling`). Type-diverse, properly sized, single-intent.
- **A large low-quality stratum** (~450+ machine-imported `node-*`, `nodejs-core-*`, `vue-*`, `typescript-magician-*`, `fastify-*`, `linting-*`). Single-type fragments, heading-only stubs, raw_prose pasted verbatim into one giant fragment, bag-of-tags taxonomies.

This degrades retrieval quality (RRF+BM25+dense) and composition density (the headline 60% prompt reduction). The README's empirical claim was measured against an unspecified slice of the corpus; if measured today against the full active corpus, expect worse — fragment retrieval can't beat skill-level retrieval if every skill is effectively one fragment.

---

## Findings — Active Corpus (`src/skillsmith/_packs/`, n=468)

| Issue | Count | % | Contract violated |
|---|---|---|---|
| Has at least one fragment under the 80-word floor | **433** | 93% | transform §"Hard fragmentation rules", R8 |
| `domain_tags` exceed 5-tag ceiling (bag-of-tags) | **393** | 84% | transform §"Tag rules" |
| Missing `verification` fragment | **368** | 79% | implied by 6-type taxonomy + R3 |
| Missing `example` fragment | **316** | 68% | transform §"Special cases" (code → `example`) |
| Missing `rationale` fragment | **309** | 66% | R8 |
| Missing `guardrail` fragment | **288** | 62% | R3-adjacent |
| Single-type (only `execution`) skill | **153** | 33% | transform §"Use only setup/execution/verification/example/guardrail/rationale" — six types exist for a reason |
| Heading-only stub fragment (e.g. `# Logging in Node.js`) | **60+** | — | transform §"single-intent" + 80-word floor |
| Under 3 fragments total | 9 | 2% | implied by 200–800 target × non-trivial sources |

**Worst tag-bloat offenders:**

```
prompt-engineering-patterns       12 tags
hybrid-search-implementation      10 tags
langchain-architecture            10 tags
llm-evaluation                    10 tags
rag-implementation                10 tags
embedding-strategies               8 tags
claude-api-patterns                8 tags
```

Even the deliberately-authored batch-3 skills exceed the 5-tag rule (webhook-patterns: 11, graphql-server-patterns: 14, sentry-error-tracking: 11, feature-flags-openfeature: 12, websocket-scaling: 13). The contract is being violated *consciously* — either rewrite the rule or the YAMLs.

---

## Findings — Staged YAMLs (`pending-review/` + `needs-human/`, n=79)

| Issue | Count | % |
|---|---|---|
| Single-type (only `execution`) | 46 | 58% |
| Missing `rationale` | **78** | 98% |
| Missing `verification` | 68 | 86% |
| Missing `example` | 67 | 84% |
| Missing `guardrail` | 63 | 79% |
| Fragments < 80 words | 145 instances | — |
| Fragments > 800 words | 36 instances | — |
| Heading-only stubs | 28 | — |
| `raw_prose` ≈ a single fragment (no real chunking) | 57 | 72% |
| `change_summary: "Imported from..."` with >4000-char `raw_prose` (R6 candidates) | 51 | 65% |
| Code-block-heavy fragments tagged `execution` (should be `example`) | 105 instances | — |

These are the imports from `mattpocock/skills`, `nodejs/`, `vue/`, `linting-neostandard-eslint9/`, etc. The transform agent split each source on H2/H3 headings, dumped the result into fragments, but did not:

1. classify code-heavy chunks as `example` (rule §"Special cases: Code blocks are usually `example`, not `execution`")
2. enforce 80-word floor (rule §"Hard fragmentation rules")
3. extract rationale prose into `rationale` fragments (R8)
4. produce mechanically checkable `verification` fragments (R3)
5. honor 2–5 retrieval-tag limit (rule §"Tag rules")

---

## Concrete examples

### 1. `node-logging.yaml` (typical machine import)

```
fragments:
  - sequence 1, type: execution, content: "# Logging in Node.js"        ← 5 words. Stub.
  - sequence 2, type: execution, content: <entire raw_prose minus stub>  ← ~1100 words. Single mega-chunk.
  - sequence 3, type: guardrail, content: "Avoid Logging Sensitive Data..."
domain_tags: [javascript, type-stripping, node, server, nodejs, typescript, backend]   ← 7 tags
```

This skill compresses to one retrievable unit. Querying for "pino transports" surfaces fragment 2 alongside everything else in the file. The promise of fragment-grain retrieval is unrealised.

### 2. `typescript-magician-infer-keyword.yaml`

3 fragments. Fragment 2 is ~1500 words containing 11 distinct examples (array element extraction, Promise unwrap, function return type, constructor params, route parsing, recursive types, etc.). Each is a separate query target. None will surface independently — all-or-nothing retrieval.

### 3. Most `node-*.yaml`

Fragment 1 = the H1 alone. Fragment 2 = everything else.

### 4. Batch-3 hand-authored skills

Correctly structured per R1–R8 fragmentation but ship 11–14 tags each. **Contract violation in the model batch.**

---

## Schema-versus-quality gap

`ingest.py` validates:

- `skill_type` is `domain` or `system`
- `skill_id`/`canonical_name`/`raw_prose` non-empty
- `category` is in the canonical set
- `fragments` has ≥1 `execution` for domain skills
- `fragment_type` ∈ {setup, execution, verification, example, guardrail, rationale}
- sequences contiguous
- system skills don't ship fragments
- system skill applicability is consistent

`ingest.py` does **not** validate:

- fragment word count (80–800 window)
- type diversity (e.g. ≥3 distinct types for non-trivial sources)
- single-intent (no mega-fragment containing the full body)
- code-block fragments classified as `example`
- tag count ≤ 5
- `change_summary` honesty (R6: "imported" vs "scaffold by skillsmith")
- `raw_prose ⊃ fragment.content` contiguity (called out in the contract; not enforced)
- presence of `rationale` (R8 retrieval requirement)

Every shipped YAML passed ingest. Most fail the authoring contract.

---

## Severity-ranked recommendations

### Critical

**C1. Promote the authoring contract to ingest-time lint.**
File: `src/skillsmith/ingest.py` `_validate()`. Add (warn, then enforce):

- per-fragment word count window (warn <80, hard-fail <20; warn >800, hard-fail >2000)
- count distinct fragment types; warn if 1, hard-fail if all-stub
- detect heading-only fragments (`^\#+\s*\S+$` and ≤8 words) → reject
- assert `fragment.content.strip()` is a substring of `raw_prose` (modulo whitespace) — already a documented contract, not enforced
- `len(domain_tags) <= 5` warn; `<= 8` hard-fail

These are mechanical and catch every issue listed above.

**C2. Bulk re-fragmentation of the imported strata.**
~450 active-corpus skills + 79 staged need re-running through the transform agent with a fragmentation pass that targets 200–800 words and labels code blocks as `example`. The current state defeats the system's value proposition. Suggested approach:

1. Run the structural lint above against `_packs/` and tag failing skills.
2. For each, re-feed the original source markdown (preserved in `skill-source/archive/`) through `fixtures/skill-authoring-agent.md` with a critic loop until the lint passes.
3. Bump pack `version` (MINOR — content materially changed).
4. Re-ingest.

The Vue stack (205 skills) is already flagged for retirement-watch; consider deferring its rewrite or dropping it.

**C3. Reconcile the 5-tag ceiling with reality.**
The hand-authored batch 3 was deliberately given more tags. Either:

(a) raise the ceiling in `fixtures/skill-authoring-agent.md` §"Tag rules" to e.g. 8 tags max with justification, OR
(b) trim the batch-3 packs to 5 tags each.

Pick one. Right now the contract is a noble lie.

### Important

**I1. R6 honesty pass on imports.**
51 staged YAMLs have `change_summary: Imported from <path>` despite ~5000+ char `raw_prose`. Skim each for added scaffolding. If the import is verbatim, leave it; if scaffolded, rewrite `change_summary: scaffold by skillsmith around upstream prose preserved in fragment <N>` per R6.

**I2. Detect & rewrite "execution that's an example".**
105 staged fragments and unknown count in active corpus have a code-fence-heavy fragment labeled `execution`. Rule §"Special cases" already says this should be `example`. Add a transform-time rule: if `content.count("```") >= 2` and code lines ≥ prose lines, retag to `example`. Run as a one-shot migration.

**I3. Add `rationale` fragments.**
98% of staged skills and 66% of active skills have no `rationale`. R8 explicitly says rationale is the embedding-anchor for "why" queries. Without it, "why use Pino instead of console.log?" hits the wrong fragment. For each rewritten skill, the transform agent should extract any "## Why", "## Tradeoffs", "## When to use", or 1–2 sentences of motivational prose into a dedicated `rationale` fragment. Hand-author the shortest as ≥80 words with the obvious-query keywords (R8).

**I4. Add `verification` fragments per R3.**
86% of staged, 79% of active skills lack one. For procedural skills, the transform agent should append a `verification` fragment with grep-shaped post-conditions ("`grep -q 'pino' package.json`", "logger output contains JSON"). If the source has no testable post-conditions, drop the rule for that skill rather than ship vague "config is sensible" items.

**I5. Stub fragments with H1-only content must merge.**
60+ active and 28 staged skills have a fragment whose only content is `# Title`. These embed terribly (<10 tokens) and pollute retrieval. The migration: drop fragment 1, renumber. Trivial.

### Useful

**U1. Pack-level audit against `pack.yaml`.**
Verify each pack's `pack.yaml` `fragment_count` matches actual fragment count after re-fragmentation. Bump `version` per `docs/PACK-AUTHORING.md` §Versioning. The migration script `scripts/migrate-seeds-to-packs.py` can regenerate manifests but doesn't currently lint contract conformance — add it.

**U2. Decide the Vue stack's fate.**
Per `CORPUS-AUDIT-2026-04-28.md`: 205 Vue skills, stack-mismatched. Re-fragmenting them is expensive. Recommendation: leave them out of the contract-conformance migration; instead either retire by 2026-05-28 if retrieval frequency is zero, or keep frozen as-is with an `archived: true` flag and exclude them from the active retrieval pool (the schema does not currently support this — it would be a small extension).

**U3. Add `change_summary` schema constraint.**
Allow only the documented values: `initial authoring | scaffold by skillsmith around upstream prose preserved in fragment <N> | imported verbatim from <upstream-path> | revision: <reason>`. Validate at ingest.

**U4. Document the gap.**
`docs/PACK-AUTHORING.md` §"Run the QA pipeline" mentions "Deterministic checks" without enumerating which contract rules are mechanical-vs-manual. Add a table mapping each rule (transform contract + R1–R8) to "ingest-enforced | lint-only | manual review", so authors know what they own.

---

## Hypothesis verdict on prior batches

`docs/CORPUS-AUDIT-2026-04-28.md` §"Out-of-scope" judged the Vue import as "leave them in". Quality review extends that judgment: **leaving in a 205-skill stratum that violates the authoring contract degrades retrieval globally**, not just on Vue queries. False-positive RRF hits on cross-stack queries are documented (see audit's probe queries: "Mocha Chai unit tests" surfacing `bats-...`; "decimal money currency" surfacing `vue-debug-v-model-number`). These are not coverage gaps — they are quality gaps in the existing entries crowding out better signal.

Recommend: **gate the next batch on C1 (lint) before authoring more skills**. Authoring more well-formed skills into a pool of malformed ones is rate-limited by the malformed retrieval, not by the new authoring effort.

---

## Out-of-scope for this review

- Factual correctness of skill content (R1, R5, R7) — the prior batch reviews already cover these adversarially per skill. This review only inspects structural and contractual conformance.
- Embedding quality / dense-retrieval evaluation — would require running `/compose` probes, not just YAML reading.
- The `fixtures/` and `skill-source/archive/` directories — fixtures are intentional test data with the older `versions:` format; archive is by definition frozen.

---

## Files inspected

- `src/skillsmith/ingest.py` (validation surface)
- `fixtures/skill-authoring-agent.md` (transform contract)
- `fixtures/skill-authoring-guidelines.md` (R1–R8)
- `docs/PACK-AUTHORING.md`
- `docs/CORPUS-AUDIT-2026-04-28.md`
- `docs/skill-review-history/2026-04-28-batch-3-protocol-and-flags.md`
- 468 active pack YAMLs, 79 staged YAMLs (programmatic scan)
- Spot reads: `node-logging.yaml`, `typescript-magician-infer-keyword.yaml`, `eslint-flat-config.yaml`, `git-commit-discipline.yaml`, `webhook-patterns.yaml` (et al. batch 3)
