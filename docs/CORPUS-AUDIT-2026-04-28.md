# Corpus Audit — Agentic SDLC Gaps

**Date:** 2026-04-28
**Corpus size:** 454 skills
**Auditor:** Claude Opus 4.7
**Method:** Full skill-id inventory + targeted `/compose` retrieval probes for each candidate gap area.

## Summary by group

| Group | Count | Notes |
|---|---|---|
| `vue-*` | 205 | Just imported. Frontend stack mismatch (team uses React) but high-quality reactivity/testing/router gotchas. |
| `node-*` + `nodejs-core-*` | 43 | Comprehensive Node.js coverage. |
| `typescript-magician-*` | 14 | Deep TypeScript types. |
| `fastify-*` | 19 | Imported as adjacent stack. Team uses NestJS. |
| `linting-*` | 6 | ESLint flat config + neostandard. |
| `nextjs-*` | 4 | Cache components + upgrade + best practices. |
| `sys-*` | 2 | Skill-authoring governance. |
| Core/other | 161 | Original ship-with-wheel + early imports. |

## Gaps by priority for this team's stack

### 🔴 Critical (stack-aligned, weak/missing coverage)

| Topic | Status | Best query result | Why it matters |
|---|---|---|---|
| **Prisma** (ORM) | ❌ | only generic `database-migration` | Team's stated ORM. No model/schema/migrate/relations guidance. |
| **PostgreSQL deep** | ⚠️ thin | `postgresql` (table design only) + `sql-optimization-patterns` | Missing: `EXPLAIN ANALYZE`, indexes (B-tree, GIN, GiST), advisory locks, `jsonb`, transactions, `pg_stat_statements`, partitioning. |
| **MongoDB** | ❌ | `fastapi-templates`, `spark-optimization` (off-target) | Team uses MongoDB for NoSQL needs. Zero coverage. |
| **Vite** | ❌ | misroutes to a Vue-debug skill | Team's frontend build tool. No config / plugin / HMR / SSR guidance. |
| **React 18** (vanilla, not Next.js/Vercel) | ⚠️ | `react-modernization`, `react-state-management`, vercel-flavored skills | Missing: hooks rules, concurrent features, Suspense boundaries, `useTransition`, `useDeferredValue`, error boundaries in 18. |
| **Mocha + Chai** | ⚠️ | generic `javascript-testing-patterns` | Team's stated test framework. No Mocha lifecycle (`before/after/beforeEach`), Chai assertion style guides, sinon mocking. |
| **podman** | ❌ | misroutes badly | User explicitly: "Containers: podman. Never docker." Zero podman skill. Need: rootless containers, podman-compose, systemd integration, image build patterns. |

### 🟡 Important (agentic SDLC essentials)

| Topic | Status | Notes |
|---|---|---|
| **Claude API / Anthropic SDK** | ❌ | Only `prompt-engineering-patterns` (vendor-neutral). For an agentic team this is foundational — prompt caching, tool use, batch API, message format, model selection. |
| **MCP servers** | ⚠️ | Only `protect-mcp-setup` (security-focused). No general "build an MCP server" guide. |
| **OpenTelemetry (Node.js)** | ⚠️ | `distributed-tracing` is generic; `node-profiling` is V8-specific. No OTel SDK integration patterns. |
| **Sentry / error tracking** | ❌ | misroutes. APM and runtime error capture is missing. |
| **GraphQL** | ❌ | Only generic `api-design-principles`. No Apollo/urql/Yoga, federation, subscriptions, N+1 mitigation. |
| **Webhooks** (in/out) | ❌ | misroutes to `protect-mcp-setup`. Need: HMAC signing, replay-window protection, retry semantics, dead-letter handling. |
| **WebSockets** (Node.js) | ⚠️ | only `fastify-websockets`. Missing: socket.io patterns, scaling with Redis pub/sub, auth on upgrade, reconnection. |
| **Feature flags** | ⚠️ | `shipping-and-launch` is too generic. Need: kill switches, percentage rollouts, GrowthBook/LaunchDarkly/Unleash patterns. |

### 🟢 Useful additions (broader best-practice coverage)

| Topic | Status | Notes |
|---|---|---|
| **GitHub PR workflow** | ⚠️ | `git-workflow-and-versioning`, `git-advanced-workflows` exist; missing `gh` CLI patterns, PR templates, draft/ready, auto-merge, branch protection, conventional review. |
| **Email (transactional)** | ❌ | misroutes. Need: Resend/SendGrid/SES integration, SPF/DKIM/DMARC, deliverability monitoring, bounce handling. |
| **SOC 2 / GDPR basics** | ❌ | misroutes. Audit logging, PII redaction, data residency, retention policies, right-to-delete. |
| **Decimal / money** | ❌ | misroutes hilariously. Need: `Decimal.js` / `bignumber.js` patterns, never floats for money, currency conversion, rounding rules. |
| **Time zones** | ❌ | misroutes. Need: store in UTC, convert at the edge, `date-fns-tz`, DST gotchas, ambiguous local times. |
| **API versioning** | ⚠️ | `api-design-principles` mentions it generically. No URL/header/content-negotiation versioning specifics. |
| **Cursor pagination** | ⚠️ | `api-design-principles` generic. Need: opaque cursors, stable sort, end-of-page semantics, REST vs GraphQL connection spec. |
| **Connection pooling** | ❌ | No Postgres pgbouncer / Prisma `pool_size` / Mongo `maxPoolSize` skill. |
| **Pulumi / CDK** | ❌ | Have `terraform-module-library`. No alternatives. |
| **Linear workflow** | ❌ | misroutes to task-coordination/on-call. No issue templates, sprint planning, MRD-to-issue patterns. |
| **Slack / team comms** | ❌ | No skill. Standup formats, incident comms, escalation patterns. |
| **Compliance / audit logging** | ⚠️ | `signed-audit-trails-recipe` exists but is Claude-Code-specific. No general application audit trail pattern. |
| **Property-based testing** | ❌ | No fast-check / hypothesis skill. |
| **Load testing** | ❌ | No k6 / artillery / locust skill. |
| **CDN / edge caching** | ❌ | No Cloudflare / Vercel Edge / CloudFront skill. |
| **Accessibility automation** | ⚠️ | `wcag-audit-patterns`, `screen-reader-testing` exist. No axe-core / Pa11y CI integration. |
| **i18n / l10n** | ❌ | No skill. |
| **Image / asset pipeline** | ❌ | No image optimization, responsive images, Next/Image alternatives. |
| **Background jobs (TS/Node)** | ⚠️ | `python-background-jobs` exists; Node side covered partially via `redis-nodejs` and Temporal. No BullMQ skill. |
| **Database backups / DR** | ❌ | No skill. |

## Recommended next batch

If we do another round, the **highest ROI for this specific team** is:

1. **Prisma + PostgreSQL pair** (model definition, migrations, relations, indexing, query optimization, Prisma Client patterns, transaction handling, soft deletes, audit columns). One large skill or a small parent + 5–8 ref skills.
2. **MongoDB** (schema design for documents, aggregation pipeline, indexes, change streams, transactions, Mongoose vs native driver).
3. **Mocha + Chai + sinon** (the team's explicit testing stack — no good answer in the corpus right now).
4. **Vite** (config, env, plugins, build modes, dev/prod parity, monorepo integration).
5. **Podman** (rootless, compose, systemd unit integration, image build).
6. **Claude API skill** (the existing `claude-api` skill from the user's CLI is a candidate to import; otherwise author from anthropic-sdk-typescript docs — covers prompt caching, tool use, batch, files, citations).
7. **OpenTelemetry for Node.js** (auto-instrumentation, manual spans, exporters to Tempo / Datadog / Honeycomb, sampling).
8. **GraphQL** (if the team plans to use it — otherwise skip).

Each can be authored as the prior batches were: SKILL.md as raw prose, ref files split into atomic skills if available, otherwise hand-author 7–8 fragments per skill.

## Out-of-scope for this team

- 205 Vue skills are stack-mismatched but already in the corpus. Net cost of leaving them = larger DB + occasional false-positive RRF hits when retrieval fires on Vue-flavored content for React queries. Net benefit = team education / framework comparison. Recommend: leave them in, monitor for cross-stack contamination in `/compose` results; remove the bottom 50% by retrieval frequency in 30 days if they're never returned for non-Vue queries.

## Probe queries used (full list)

```
Prisma migrate schema model              → database-migration (generic)
PostgreSQL EXPLAIN advisory lock jsonb   → sql-optimization-patterns
MongoDB aggregation pipeline             → fastapi-templates, spark-optimization (off)
Vite build dev server React              → vue-debug-..., vercel-react-best-practices
Mocha Chai unit tests                    → javascript-testing-patterns, bats-...
podman compose container                 → temporal-python-testing, vue-... (off)
Claude API Anthropic SDK prompt caching  → prompt-engineering-patterns
MCP server tools function calling        → browser-testing-..., protect-mcp-setup
GraphQL schema resolver                  → api-design-principles
OpenTelemetry tracing Node.js            → node-profiling, distributed-tracing
webhook signing replay protection        → protect-mcp-setup
Sentry error tracking                    → incident-runbook-..., vue-debug-suspense-...
Linear ticket workflow                   → task-coordination, on-call-handoff
feature flags rollout                    → shipping-and-launch, ci-cd
WebSocket connection scaling             → async-python-patterns, fastify-websockets
email transactional deliverability       → python-background-jobs, database-migration (off)
SOC 2 GDPR compliance data               → documentation-overview, multi-cloud (off)
decimal money currency precision         → vue-debug-v-model-number, architecture-patterns
time zone UTC DST                        → python-background-jobs, postmortem-writing (off)
cursor pagination REST API               → api-design-principles, sql-optimization-patterns
```
