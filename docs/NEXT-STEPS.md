# Next Steps — Skillsmith

**Updated:** 2026-04-28 (after batch 2 ship of 8 stack-foundation skills, commit `53a8f5e`)

Ranked by leverage. Pick one (or combine #1 + #2).

---

## 1. Improve the skill-authoring prompt (highest leverage) — DONE 2026-04-28

The adversarial review of batch 2 captured 6 cross-skill patterns at
`docs/skill-review-history/2026-04-28-batch-2-stack-foundations.md`. The 6 rules
are now codified at `fixtures/skill-authoring-guidelines.md` (R1–R6) and
referenced from `fixtures/skill-authoring-agent.md`.

**Validation:** run the next authoring batch (#2 below) using the guidelines doc
as a pre-author checklist, then compare review-feedback density vs. the batch-2
review history. If feedback density drops materially, the rules are paying.
If a pattern recurs that the rules don't cover, append to the "Anti-patterns
observed" section of the guidelines doc.

---

## 2. Author the next batch — remaining audit gaps

Still missing for an agentic team. Pick 6-8 from this list:

| Topic | Pack |
|---|---|
| **GraphQL** (Apollo/urql/Yoga, N+1 mitigation, federation basics) | new `graphql` pack |
| **Webhooks** (HMAC signing, replay protection, retries, dead-letter) | new `webhooks` pack OR `engineering` |
| **Sentry / error tracking** (SDK, source-map upload, performance monitoring) | `observability` |
| **Feature flags** (GrowthBook / LaunchDarkly / Unleash, kill switches, percentage rollouts) | new `feature-flags` pack |
| **WebSocket scaling** (Redis pub/sub fan-out, auth on upgrade, reconnection backoff) | `nodejs` or new `websockets` |
| **Linear workflow** (templates, sprint planning, MRD-to-issue) | new `pm-tools` pack |
| **Slack messaging** (mrkdwn, threading, Block Kit, attachment limits) | new `pm-tools` pack |
| **Email transactional** (Resend/SendGrid/SES, SPF/DKIM/DMARC, bounce handling) | new `email` pack |
| **GitHub PR workflow** (gh CLI patterns, PR templates, auto-merge, branch protection) | `engineering` or new `github` pack |
| **Time zones** (UTC storage, conversion at edges, date-fns-tz, DST traps) | `engineering` |
| **Decimal / money** (Decimal.js / bignumber.js, currency conversion, rounding rules) | `engineering` |
| **API versioning + cursor pagination** (URL/header/content-negotiation, opaque cursors) | `engineering` |

**Run through the same flow as batch 2:** fetch docs first → author → adversarial review →
single revision → ingest → verify retrieval → push.

---

## 3. Re-author the rejected stub packs

9 skills got rejected in earlier rounds for being TOC pointers (vue-jsx-patterns,
vue-options-api-patterns, fastify-stub, etc.). The actual content lives in
`skill-source/vue/skills/skills/<parent>/reference/*.md` files which we already
imported as ~205 atomic vue skills. The stubs are now redundant.

**Action:** verify the rejection records still match reality, leave them in
`/skill-source/.../rejected/`, and move on. No re-authoring needed; the granular
ref-derived skills replaced them.

---

## 4. Deploy skillsmith to a real navistone project

End-to-end validation. Pick a real repo, run `skillsmith setup` from a fresh state,
wire it into Claude Code (or whatever IDE), and watch the agent actually use the
corpus on real tickets.

**Why this matters:** runtime feedback (which skills hit, which miss, which compose
poorly) is the only true quality signal. Authoring quality is mechanical; retrieval
quality at runtime is empirical.

**What to capture:**
- Per-query: which skills retrieved, was the result useful, did the agent's output
  look better with the skill than without?
- Failure modes: queries where the corpus has the right info but RRF didn't surface it.

This becomes the input for the next round of skill authoring + retrieval tuning.

---

## 5. Productionize the install/distribution pipeline

Operational improvements that compound across teams:

- **Pack-bump automation** — `skillsmith pack-bump <pack>` increments version,
  regenerates manifest, optionally tags a release.
- **Pack registry** — host `manifest.json` + tarballs at a stable URL so
  `skillsmith install-pack <name>` works without a local checkout.
- **Telemetry** — privacy-preserving aggregate of "which packs get queried
  most often" so authoring effort can target high-utilization gaps.
- **CI guard against drift** — `pnpm prisma validate`-style check that pack
  manifests match their YAML inventories.

Lower priority than #1 and #2 unless multiple teams are publishing packs.

---

## 6. Smaller cleanups (drift / hygiene)

- **`fragment_count` enforcement on existing packs** — a few existing pack manifests
  weren't regenerated after content changes; the validator I added catches this on
  install but the existing packs haven't been re-validated.
- **The `seed-corpus` "verified_present" path** still has the legacy 50-skill minimum
  threshold. With pack-based installs, "verified_present" doesn't make sense anymore;
  the path should be retired or rethought as "verify the loaded corpus matches the
  declared installed_packs[]".
- **`docs/CORPUS-AUDIT-2026-04-28.md`** is dated; refresh after the next batch.

---

## Recommendation

**#1 → #2 in that order.** Applying the review history to the authoring prompt is
small (one skill edit + one ingest) but compounds for every future skill. Then run the
next batch through it and watch whether the review feedback density drops.

If you want raw forward progress and don't want to revisit the meta: skip to **#2**
(next batch). If you want to validate the whole loop in production:  **#4** (deploy)
delivers the highest signal-to-noise.
