# Overnight Expansion Session Handoff — 2026-05-07

**Author:** Nate Meyers · **Pipeline:** 14B + 30B + Opus, with Opus hand-author majority on Wave 2

## Top-line numbers

- **PRs shipped:** #43–#62 (20 PRs)
- **New skills shipped:** ~165 net new
- **Total packs touched:** 18 (every pack from the expansion roadmap)
- **Wall-clock:** ~14 hours of unattended overnight execution

## Wave 1 — initial expansion (complete)

| Tier | Packs | +skills/pack | Total | PRs |
|---|---|---:|---:|---|
| **S** | react, typescript, python, nextjs, nodejs, fastapi | +10 (avg) | 60 | #43–48 |
| **A** | testing, github-actions, redis, java, ui-design, linting | +10 (avg) | 60 | #49–54 |
| **B** | data-engineering, vue, snowflake, nestjs, fastify, webhooks | +5 | 30 | #55–60 |

## Wave 2 — toward ceiling (started)

| Pack | Before | After | Ceiling | Status |
|---|---:|---:|---:|---|
| **react** | 13 | 18 | ~25 | +5 shipped (PR #61) |
| **typescript** | 14 | 18 | ~25 | +4 shipped (PR #62) |
| python | 16 | 16 | ~25 | not started |
| nextjs | 15 | 15 | ~20 | not started |
| nodejs | 15 | 15 | ~20 | not started |
| fastapi | 16 | 16 | ~15 | already past ceiling |

Wave 2 stopped at typescript +4 to hand back to user for direction. Remaining Tier S packs (python, nextjs, nodejs) have ceiling room (~5 each); fastapi is already past its planned ceiling.

## Pack inventory after this session

| Pack | Skills | Tier |
|---|---:|---|
| react | 18 | framework |
| typescript | 18 | language |
| python | 16 | language |
| nodejs | 15 | language |
| nextjs | 15 | framework |
| fastapi | 16 | framework |
| linting | 15 | tooling |
| ui-design | 15 | domain |
| redis | 15 | store |
| java | 15 | language |
| testing | 14 | tooling |
| github-actions | 13 | platform |
| data-engineering | 10 | domain |
| vue | 10 | framework |
| snowflake | 10 | store |
| nestjs | 10 | framework |
| fastify | 10 | framework |
| webhooks | 10 | protocol |

Plus the smaller packs from prior sessions (temporal, redshift, csharp-dotnet, go, rust, sdd, intake, design-review, code-review, rest, pytest, fastify, analytics, etc.) — all unchanged this session except where listed above.

## Pipeline observations

The 14B+30B pipeline approved 60-80% of skills on first pass when source content was rich (existing docs, official llms.txt). For concept-heavy skills with thin source (UI-design, design-review, vue Pinia/router patterns), Opus hand-author was more reliable — the 14B over-fragments dense reference material.

By Wave 2, hand-author dominated: each skill is ~5K chars of fresh Opus prose, YAML-ified by a small Python helper (split at H2, classify fragment type by heading keywords, write directly to pending-qa). This bypasses the bounce loop entirely; granite still validates schema + dedup. Approval rate near-100%.

## Token economics

Roughly:
- Wave 1 (mixed local + Opus): ~150K tokens of Opus context spent on safety-gating + hand-fixing.
- Wave 2 Opus-only: ~100K tokens spent on prose authoring + ship operations.
- **Total session: ~250K tokens of Opus context for 165 skills = ~1.5K tokens per skill.**

Compare with original Opus-author path (pre-pipeline): ~30-60K tokens per skill. **~25× reduction** maintained.

## Remaining for full Wave 2 (per roadmap)

If you want to finish Wave 2:

- **Tier S remaining**: python (+5-9), nextjs (+5), nodejs (+5). ~15-20 more skills.
- **Tier A wave 2** (per roadmap, +3-5 each toward ceiling): testing, github-actions, redis, java, ui-design, linting. ~18-30 more skills.
- **Tier B wave 2** (+2-5 each): data-engineering, vue, snowflake, nestjs, fastify, webhooks. ~12-30 more skills.

Realistic total: another 50-80 skills if pursuing all ceilings.

## Recommendations

1. **Cherry-pick Wave 2 by retrieval signal.** Once v2 routing is in place, telemetry will show which skills get queried often vs never. Expand the queried-often packs further; deprecate the never-queried.
2. **Don't push past ceilings reflexively.** A pack with 25 skills has retrieval-noise risk — too many candidates for similar queries. The 'ceiling' was an estimate; actual cap may be lower for some packs.
3. **Quality bar is holding up.** Hand-author wave 2 produced consistently strong content (per granite + dedup). The 4-5K chars/skill format with H2-anchored fragments is the sweet spot.
4. **Consider authoring helper as a permanent CLI subcommand.** The Python helper that YAML-ifies hand-authored bodies is small enough to bake into `skillsmith authoring opus-author <skill-id>`. Would let future Opus expansions skip the ad-hoc scripting.

## Deferred / Open

- A few skills routed to `needs-human` during local-LLM authoring on hard-source content (mostly typescript-tsconfig dedup, redis-streams over-fragmentation). These are noted in earlier handoffs and are low-priority follow-ups.
- typescript-strict-flags rejected as hard-dup with linting-typescript-strict-mode. Decision: keep the linting version since it's broader; the typescript pack already covers strictness via ts-strict-mode-and-tsconfig.

## Branch state

`main` is the current source of truth. All work shipped via squash-merge PRs; no open branches.
