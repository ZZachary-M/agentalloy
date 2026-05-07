# Pack Expansion Roadmap — 2026-05-06

**Author:** Nate Meyers · **Method:** popularity × coverage-gap ranking

After shipping 17 packs (~75 skills) the corpus is broad but shallow. Some packs are reasonably saturated at 5 skills; others barely scratch the surface of what working developers query against daily. This document ranks existing packs for expansion priority.

## Methodology

- **Popularity** = approximate share of working developers who touch this daily (informed estimate, not telemetry).
- **Coverage gap** = how much authoritative canonical content remains uncaptured by the existing 3-5 skills.
- **Skills shipped** = current count in `src/skillsmith/_packs/<pack>/`.
- **Estimated ceiling** = a rough cap where adding more skills starts to duplicate or pad rather than add retrieval value.

The two-axis framing matters: a pack can be popular but already saturated (engineering, refactoring); another can have huge canonical depth but a niche audience (temporal). Investment goes furthest where both axes are high.

## Tier S — invest here first

Massive popularity AND massive remaining knowledge. Each easily justifies 15–25 more skills before diminishing returns.

| Rank | Pack | Shipped | Ceiling | Untouched canonical content |
|---|---|---:|---:|---|
| 1 | **react** | 5 | ~25 | forms + react-hook-form, error boundaries, refs/imperatives deep, context patterns, performance + profiling, react-testing-library, transitions/useDeferredValue, react-router/tanstack-router, react-query, hydration nuances, animations, a11y |
| 2 | **typescript** | 5 | ~25 | declaration files, ambient types, conditional types, mapped types, template literals, decorators (stage-3), module resolution modes, project references, strictness flags, narrowing patterns, JSX type system, build tooling integration |
| 3 | **python** | 5 | ~25 | dataclasses + attrs, enum, typing.Protocol, asyncio deep (TaskGroup, cancellation), multiprocessing, generators/coroutines, descriptors, metaclasses, packaging (pyproject + uv), debugging, profiling, GIL realities, structural pattern matching |
| 4 | **nextjs** | 5 | ~20 | middleware deep, ISR/PPR, parallel routes deep, intercepting routes, instrumentation, OpenTelemetry, Edge runtime quirks, image optimization, font loading, draft mode, dynamic vs static rendering trade-offs, deployment, telemetry |
| 5 | **nodejs** | 5 | ~20 | streams deep (web streams, transform), worker threads, native test runner, performance hooks, fs/promises patterns, child_process + spawn, child workers, profiling (clinic/0x), npm internals, semver, native ESM edge cases |
| 6 | **fastapi** | 5 | ~15 | middleware (custom), SSE/streaming responses, file uploads, WebSockets, testing (TestClient + AsyncClient), CORS, OpenAPI customization, dependency injection deep, security (OAuth2 flows complete) |

## Tier A — high-yield expansion

Strong popularity, moderate-to-large gap. ~10–15 more skills each.

| Rank | Pack | Shipped | Ceiling | Untouched |
|---|---|---:|---:|---|
| 7 | **testing** | 3 | ~15 | TDD discipline, contract testing, property-based testing, integration patterns, performance testing, flaky-test diagnostics, fixture libraries deep, test data builders, snapshot strategies, coverage interpretation |
| 8 | **github-actions** | 5 | ~15 | composite actions deep, OIDC + cloud auth, self-hosted runners, security hardening (pinned actions, allow-list), monorepo workflows, deployment patterns, secrets scanning, advanced caching strategies, larger runners |
| 9 | **redis** | 5 | ~15 | clustering, replication, Sentinel, persistence (RDB/AOF), Lua scripting, modules (RedisJSON, RediSearch), security/ACL, pipelining, transactions (MULTI/EXEC), keyspace notifications, debugging slow queries |
| 10 | **java** | 5 | ~20 | Spring core (DI, Boot config), JPA/Hibernate, Reactive (WebFlux/Project Reactor), build tools (Maven, Gradle), Spring Security, testing (JUnit 5 + Mockito + Testcontainers), Spring Data, observability (Micrometer) |
| 11 | **ui-design** | 5 | ~15 | motion/animation systems, design-system architecture, component-library patterns, color science (OKLCH, contrast), typography scales, layout primitives, form UX, empty states, loading patterns, error states |
| 12 | **linting** | 5 | ~12 | stylelint, ESLint plugin authoring, custom rules, ruff plugin/config deep, golangci-lint, pre-commit, lint-staged, CI integration patterns, performance (lint speed), shareable configs |

## Tier B — moderate ROI

Good packs but smaller upside. ~5–10 more skills each before saturation.

| Rank | Pack | Shipped | Ceiling | Untouched |
|---|---|---:|---:|---|
| 13 | **data-engineering** | 5 | ~12 | Spark patterns, Iceberg / lakehouse, dimensional modeling, slowly-changing dimensions, data quality frameworks (Great Expectations), CDC patterns, Delta Lake |
| 14 | **vue** | 5 | ~12 | Pinia state management deep, vue-router patterns, suspense + async deep, custom directives, plugins, transitions deep, SSR/Nuxt integration, testing (vitest + vue-test-utils) |
| 15 | **snowflake** | 5 | ~10 | Snowpipe + auto-ingest deep, dynamic tables, Cortex AI/ML, masking + RBAC deep, search optimization, cost monitoring, change data capture, Snowpark |
| 16 | **nestjs** | 5 | ~10 | microservices transports, GraphQL integration, WebSockets, queues (Bull/BullMQ), caching, OpenAPI/Swagger, testing patterns, authentication flows complete |
| 17 | **fastify** | 4 | ~8 | error-handling (deferred — fold in), TypeScript integration, schemas with TypeBox, decorators deep, lifecycle hooks deep, performance tuning |
| 18 | **webhooks** | 5 | ~8 | replay/dead-letter patterns, observability for webhook delivery, fan-out architectures, customer-facing portal patterns |

## Tier C — keep mostly as-is

Either intentionally tight or already at reasonable saturation. Further expansion would dilute precision.

- **core** (12) — already broad; adding more starts duplicating language packs.
- **engineering** (5) — foundation; should stay cross-cutting.
- **refactoring / performance / documentation** — foundation, intentionally compact.
- **temporal / redshift / csharp-dotnet / go / rust** — narrower audiences; current 5 cover the surface.
- **sdd / intake / design-review / code-review / rest** — concept/workflow packs, low expansion yield.

## Suggested sequencing

1. **Tier S #1–3 (react, typescript, python)** — biggest immediate retrieval-quality lift; these are what most users query against. Each gets a focused 5–10-skill expansion batch.
2. **Tier S #4–6 (nextjs, nodejs, fastapi)** — completes the modern web-app surface.
3. **Tier A #7–9 (testing, github-actions, redis)** — infrastructure that everyone touches.
4. **Tier A #10–12 (java, ui-design, linting)** — complete the cross-cutting surface.
5. **Tier B** opportunistically.

## Authoring approach

The hand-author bypass proved its worth on the needs-human recovery pass — 10 hand-authored skills approved on first try where the local 14B+30B couldn't converge. Recommended split for expansion:

- **First-attempt route**: local 14B+30B bounce loop with `python -m skillsmith.authoring run`. ~80% approve in 1-2 rounds.
- **Hand-author route**: when granite flags repeatable issues across 3+ bounces, escalate to Opus directly. The bypass YAML write took ~5 min/skill and approved cleanly.

For Tier S expansion, expect ~5/skill needs hand-authoring out of every 25 — budget accordingly.

## Open questions for product

- Should `core` and `engineering` be allowed to grow, or are they truly capped? They're cross-cutting and may absorb new patterns over time.
- Is there a v1 → ga progression for `snowflake` / `redshift` / `temporal` (which I wrote at 5 skills each) once they prove their precision in production retrieval?
- Telemetry is the only honest answer to which packs need more — once v2 routing logs which queries fall through to "no skill matched," that data should re-rank this list.
