# Skill Authoring Guidelines

**Purpose:** Quality contract for the human or agent writing a NEW skill source
(SKILL.md / pack YAML draft) from scratch. Applies BEFORE the
`skill-authoring-agent.md` ingest/transform pass.

These are not formatting rules. They are content-correctness rules derived from
adversarial review of shipped batches. Each rule cites the failure mode that
created it. Treat them as a checklist; if you can't satisfy the rule, drop the
example or the claim — don't paper over it.

Source: `docs/skill-review-history/2026-04-28-batch-2-stack-foundations.md`
(6 cross-skill patterns observed across 8 stack-foundation skills).

---

## R1 — Fetch authoritative docs before authoring against fast-moving APIs

If the technology has API churn — frameworks <2 years old, ML/agent SDKs,
vendor SDKs (Anthropic, OpenAI, Prisma, OTel, mongo Node driver, mocha+tsx
loaders) — fetch the current docs via `ctx_fetch_and_index` BEFORE writing any
example.

Quote the docs when an example uses a non-trivial signature. Knowledge in your
training data is allowed to be ~6 months stale and routinely is on these APIs.

**Failure mode this prevents:** Prisma generator name (`prisma-client` vs
`prisma-client-js`), Mongo `Decimal128` shell-vs-driver syntax, mocha tsx
`loader:` field, OTel `resourceFromAttributes` vs `Resource` class — all
shipped wrong because of stale recollection.

## R2 — Every non-stdlib name in a code block must show its `import` once

If a code block references `Prisma.Decimal`, `Decimal128`, `Anthropic.Tool`,
`PrismaClientKnownRequestError`, etc., at least one block in the same skill
must show the `import` line that introduces it.

Readers wire the example into a real file. An example without imports compiles
in nobody's editor.

**Failure mode this prevents:** examples that read fluently but cannot be
copy-pasted because the type name has no resolvable origin.

## R3 — Verification checklists are contracts; every item must be mechanically checkable

A verification fragment is a list of post-conditions a downstream agent will
check. Vague items like "good practices followed" or "config is sensible" are
not checkable and should not appear.

Each item should be expressible as a one-line shell command, a single
assertion, or a binary observation. If you can't write the check, drop the
item.

**Failure mode this prevents:** wrong claims surviving review (e.g.,
"env-var change requires server restart" when Vite watches `.env*` files and
restarts automatically).

## R4 — State machines and coverage examples must enumerate every case

When a code example claims to cover a state machine, an enum, or a method set
(soft-delete extension over Prisma client methods, retry handler over error
classes, switch statement over discriminated union variants), enumerate every
method/state. Comment why each one is or isn't handled.

A soft-delete extension that overrides `findMany` and `findFirst` but leaves
`findUnique`, `findUniqueOrThrow`, `count`, `update.where`, and `deleteMany`
untouched leaks deleted rows. That is a correctness bug, not a style nit.

**Failure mode this prevents:** examples that work for the happy path and
silently fail for half the API surface.

## R5 — Trace one edge case mentally before including any example

Before committing an example, walk through one realistic edge case in your
head. Most failure modes shipped in batch 2 were happy-path examples that
skipped a rare-but-real edge.

Examples to specifically pressure-test:

- Tool-execution loops without a max-iteration cap.
- Pagination over OFFSET with growing tables.
- Caching with prefixes shorter than the model's minimum (1024 / 2048 / 4096).
- Async test harnesses where the assertion runs before the promise resolves.
- Connection pools without `directUrl` for migrations through PgBouncer.

**Failure mode this prevents:** runaway agent loops, silent data loss,
"works locally" examples that fail under prod load.

## R6 — Date-stamp version-specific or minimum-value claims

When citing a minimum, threshold, or version-specific behavior — "cache prefix
must be ≥ 4096 tokens for Opus", "INCLUDE syntax requires Postgres 11+",
"`resourceFromAttributes` is `@opentelemetry/resources` v1.27+", "Stable API
requires driver v6+" — include the date you verified it (today's date if
freshly fetched).

A reader six months from now needs to know whether to trust the number or
re-check it.

**Format:** `(verified YYYY-MM-DD)` inline, or a footer `## Verified` block
listing each numeric/version claim with its date.

**Failure mode this prevents:** quietly outdated facts. "I don't know — go
check" beats a confident wrong number.

---

## Process for a new batch

1. **Pre-author:** for each skill, fetch authoritative docs (R1). Note the
   verification date for any version-specific claim (R6).
2. **Author:** write skill prose with examples. Apply R2 (imports), R4
   (enumerate cases), R5 (edge cases) as you write.
3. **Self-review (R3):** read your own verification fragments. Strike any
   item you cannot check mechanically.
4. **Adversarial review:** dispatch an independent critic (Claude or human)
   with this guidelines doc and the review-history templates. Issues found
   here are cheaper than issues found post-ingest.
5. **Single revision pass:** apply review fixes. Resist scope creep —
   line-level corrections, not redesigns.
6. **Ingest:** hand off to `skill-authoring-agent.md` for source-to-YAML
   transformation.

---

## Anti-patterns observed (do not repeat)

- **Mocha tsx loader via `.mocharc.cjs` `loader:` field.** Use `--import tsx`
  on the script line, or document c8 for coverage. (Batch 2, mocha-chai-sinon)
- **Soft-delete extension overriding only read-list methods.** Cover the full
  client method surface or document the gaps explicitly.
  (Batch 2, prisma-orm-patterns)
- **Tool-loop examples without a `MAX_TURNS` constant.** Always cap.
  (Batch 2, claude-api-patterns)
- **Mongo shell syntax in Node driver examples.** `NumberDecimal('19.99')`
  is shell; driver wants `new Decimal128('19.99')`. (Batch 2, mongodb-patterns)
- **Recommending sysctl-level fixes for app-level problems.** Prefer
  `setcap` or a reverse proxy over `net.ipv4.ip_unprivileged_port_start`.
  (Batch 2, podman-rootless)

Add new entries here as future batches surface new patterns.
