# Skillsmith Pack Inventory — Prioritized

**Status:** Working inventory for v1 + general access planning
**Last updated:** 2026-04-29

This document captures the full skill_class / tier / pack hierarchy with packs ordered by build priority within each tier. Markers: `[v1]` for NaviStone v1 scope, `[ga]` for general-access additions, `[gap]` for items from `CORPUS-AUDIT-2026-04-28.md`.

Within each tier, packs are ordered by what I'd build first to last. The reasoning differs by tier — sometimes user reach (how many people need this), sometimes foundational dependence (other things build on this), sometimes quality-of-existing-resources (where Claude can add the most value over what's already out there).

---

## Level 1 — skill_class

The retrieval contract a skill operates under. Three values, no others.

```
system
domain
workflow
```

---

## Level 2 — pack tier

The policy band within a skill_class.

For `system`: no tier (system skills bypass retrieval).

For `domain`, the nine tiers in `_VALID_PACK_TIERS`:

```
foundation
language
framework
store
cross-cutting
platform
tooling
domain
protocol
```

For `workflow`, one tier:

```
workflow
```

---

## Level 3 — packs (prioritized within each tier)

### System-class packs (always-injected, no tier)

```
1. meta              [v1]   — skill-authoring guidance, contract docs, R-rules
2. conventions       [v1]   — writing style, output format, naming
3. governance-generic [ga]  — generic governance template for OSS
4. licensing         [ga]   — license selection, contributions, copyright
5. governance        [v1]   — NaviStone-specific (stays internal)
```

Meta and conventions ship first because every other pack depends on them existing — you can't author skills consistently without the contract and conventions in place. Governance-generic and licensing are next because OSS users hit these on day one. NaviStone governance is last because it's internal and doesn't block general release.

### Domain-class packs at `foundation` tier (recall-favored)

```
1. core              [v1]   — fundamental cross-stack patterns
2. engineering       [v1]   — engineering practices, testing philosophy, code review
3. debugging         [ga]   — systematic debugging, bisection, log analysis
4. documentation     [ga]   — README, API docs, ADRs
5. refactoring       [ga]   — refactoring patterns, technical debt
6. performance       [ga]   — profiling, optimization fundamentals
```

Core and engineering are the universal substrate — every other pack assumes these exist. Debugging is third because it's underrepresented in existing resources and high-value. Documentation is fourth because OSS projects need it badly and most do it poorly. Refactoring and performance are valuable but less foundational.

### Domain-class packs at `language` tier (precision-favored)

```
1. typescript        [v1]   — TS patterns, type system, tooling
2. python            [v1]   — Python idioms, async, packaging
3. javascript        [ga]   — vanilla JS patterns
4. nodejs            [v1]   — Node runtime, event loop
5. go                [ga]   — Go idioms, concurrency
6. rust              [ga]   — Rust ownership, lifetimes
7. shell-bash        [ga]   — bash/zsh scripting
8. sql               [v1]   — SQL across dialects
9. csharp-dotnet     [v1]   — .NET patterns
10. java             [ga]   — Java patterns, JVM
11. ruby             [ga]   — Ruby idioms
12. kotlin           [ga]   — Kotlin/Android, coroutines
13. swift            [ga]   — Swift, iOS
14. php              [ga]   — modern PHP
15. elixir           [ga]   — Elixir/OTP
```

TypeScript and Python lead because they're the two languages with the largest active developer base in modern web/AI work. JavaScript is third even though TS subsumes it for many users — vanilla JS is still the lingua franca for many tasks. Node, Go, Rust round out the systems-and-backend tier. Bash sits at 7 because everyone uses it daily and most people use it badly — high-leverage. SQL is universal but not as language-of-development. .NET, Java, Ruby, Kotlin, Swift, PHP, Elixir are real but progressively narrower audiences.

### Domain-class packs at `framework` tier (precision-favored)

```
1. react             [v1]   — components, hooks, state
2. nextjs            [v1]   — routing, server components, deployment
3. fastapi           [ga]   — Python async API framework
4. express           [ga]   — Node minimalist HTTP
5. django            [ga]   — Django ORM, views
6. shadcn-ui         [ga]   — design system patterns
7. vue               [v1]   — Vue 3, Composition API
8. flask             [ga]   — Flask, blueprints
9. svelte            [ga]   — Svelte/SvelteKit
10. spring-boot      [ga]   — Spring Boot, Java enterprise
11. astro            [ga]   — Astro islands, content collections
12. rails            [ga]   — Rails conventions, ActiveRecord
13. nestjs           [v1]   — Node enterprise framework
14. fastify          [ga]   — Node high-performance HTTP
15. nuxt             [ga]   — Nuxt 3, SSR
16. remix            [ga]   — Remix routing, data loading
17. angular          [ga]   — Angular, RxJS
18. laravel          [ga]   — Laravel, Eloquent
19. solid            [ga]   — SolidJS reactivity
20. htmx             [ga]   — htmx hypermedia patterns
21. react-native     [ga]   — RN, Expo
```

React and Next.js are non-negotiable — they're where most modern frontend work happens. FastAPI and Express are the most common backend frameworks for Python and Node respectively. Django at 5 because Python web devs split between it and FastAPI. Shadcn-ui at 6 because design system adoption is exploding. Vue at 7 because it's a meaningful minority of the React audience. Spring/Rails further down because their communities are well-served by existing resources. Angular near the bottom because its share is shrinking. Solid, htmx, React Native are smaller communities but have engaged users.

### Domain-class packs at `store` tier (precision-favored)

```
1. postgres          [v1]   — Postgres features, indexing, query planning
2. redis             [v1]   — caching, pub/sub, data structures
3. sqlite            [ga]   — SQLite, embedded patterns
4. mongodb           [gap]  — document modeling
5. prisma            [gap]  — Prisma ORM patterns
6. drizzle           [ga]   — TS lightweight ORM
7. sqlalchemy        [ga]   — Python ORM
8. mysql             [ga]   — MySQL/MariaDB specifics
9. postgres-deep     [gap]  — advanced Postgres
10. s3               [ga]   — object storage patterns
11. dynamodb         [ga]   — DynamoDB modeling, GSIs
12. snowflake        [v1]   — warehouse patterns, cost optimization
13. clickhouse       [ga]   — analytical queries
14. duckdb           [v1]   — embedded analytics
15. elasticsearch    [ga]   — search patterns, mappings
16. opensearch       [ga]   — OpenSearch (post-fork)
17. typeorm          [ga]   — TS/Node ORM
18. redshift         [v1]   — warehouse patterns
19. kafka            [v1]   — event streaming
20. neo4j            [ga]   — graph patterns, Cypher
21. rabbitmq         [ga]   — message queue patterns
22. cassandra        [ga]   — wide-column patterns
23. temporal         [v1]   — durable execution
```

Postgres leads because it's the default OLTP for the modern stack and used by everyone. Redis is second because almost every production app needs caching or pub/sub. SQLite at 3 because it's everywhere — local dev, mobile, embedded — and undersold. MongoDB at 4 because it's the second-most-used database. Prisma/Drizzle/SQLAlchemy cluster at 5-7 because ORM selection is a daily question for most developers. Postgres-deep is separated from postgres because advanced patterns warrant their own pack but only after the basics. DynamoDB before Snowflake because more people hit DynamoDB than warehouses. Kafka, Neo4j, Cassandra, Temporal are specialized — useful but narrower.

### Domain-class packs at `cross-cutting` tier (recall-favored)

```
1. auth              [v1]   — authentication, OAuth, SSO
2. api-design        [v1]   — REST/GraphQL/RPC design, versioning
3. error-handling    [ga]   — error patterns, graceful degradation
4. observability     [v1]   — logging, metrics, tracing
5. caching           [ga]   — cache strategies, invalidation
6. security          [v1]   — secrets management, vulnerability patterns
7. data-validation   [v1]   — validation across layers
8. rate-limiting     [ga]   — rate limit patterns
9. accessibility     [ga]   — a11y patterns
10. encryption       [ga]   — encryption at rest/transit, key management
11. i18n             [ga]   — internationalization, locale handling
```

Auth leads because it's the cross-cutting concern most likely to be done wrong, and the cost of doing it wrong is highest. API design is second because every backend pack depends on it. Error handling at 3 because it's universally relevant and rarely well-treated. Observability at 4 — most teams know they need it but few do it well. Caching, security, and validation cluster in the middle. Rate limiting and accessibility are important but more situational. Encryption and i18n are valuable but specific.

### Domain-class packs at `platform` tier (mixed)

```
1. github-actions    [v1]   — GitHub Actions specifics
2. docker            [v1]   — Docker-specific
3. containers        [v1]   — generic container patterns
4. aws               [v1]   — AWS service patterns
5. terraform         [v1]   — Terraform-specific
6. kubernetes        [v1]   — K8s patterns
7. vercel            [ga]   — Vercel deployment, edge functions
8. cloudflare        [ga]   — Workers, Pages, R2, edge
9. cicd              [v1]   — generic pipeline patterns
10. docker-compose   [ga]   — local orchestration
11. iac              [v1]   — generic IaC patterns
12. monorepo         [v1]   — Nx, Turborepo, Bazel
13. gcp              [ga]   — GCP service patterns
14. fly-io           [ga]   — Fly.io patterns
15. nginx            [ga]   — nginx config, reverse proxy
16. serverless       [v1]   — Lambda, FaaS architecture
17. helm             [ga]   — Helm charts
18. azure            [ga]   — Azure service patterns
19. podman           [gap]  — Podman-specific
20. ansible          [ga]   — config management
21. gitlab-ci        [v1]   — GitLab-specific
22. netlify          [ga]   — Netlify patterns
23. caddy            [ga]   — Caddy server
```

GitHub Actions leads because it's the CI most OSS projects use, and most people configure it badly. Docker second because containers are everywhere. AWS at 4 because it's still the default cloud despite GCP/Azure presence. Terraform at 5 because IaC pattern leadership matters. Kubernetes at 6 — yes it's huge but it's specialized. Vercel/Cloudflare cluster at 7-8 because edge/modern hosting is increasingly the answer. GCP/Azure further down than AWS because their audiences are smaller. Podman near bottom because it's high-quality but the audience is narrow vs. Docker. GitLab-CI low because GitHub Actions dominates the OSS world.

### Domain-class packs at `tooling` tier (precision-favored)

```
1. git               [ga]   — git workflows, advanced patterns
2. testing           [v1]   — generic testing strategy
3. vitest            [ga]   — Vitest specifics
4. pytest            [v1]   — Python testing
5. linting           [v1]   — eslint, prettier, language linters
6. claude-code       [v1]   — Claude Code patterns, skill authoring
7. playwright        [v1]   — E2E testing, browser automation
8. mise              [v1]   — runtime version management
9. ruff              [ga]   — Python linter
10. biome            [ga]   — JS/TS linter (modern alternative)
11. uv               [ga]   — Python uv (modern dep mgmt)
12. pnpm             [v1]   — package management
13. github-cli       [v1]   — gh CLI
14. esbuild          [ga]   — esbuild
15. vite             [gap]  — Vite
16. neovim           [ga]   — Neovim, LSP
17. vscode           [ga]   — VS Code patterns
18. git-rebase       [ga]   — interactive rebase, history rewriting
19. storybook        [ga]   — component development
20. bun              [ga]   — Bun runtime, package manager
21. webpack          [ga]   — Webpack config
22. swc              [ga]   — SWC compilation
23. just             [ga]   — just task runner
24. makefile         [ga]   — Makefile patterns
25. jest             [ga]   — Jest, RTL
26. cypress          [ga]   — E2E testing alternative
27. mocha-chai       [gap]  — Mocha/Chai
28. rspec            [ga]   — Ruby testing
29. go-test          [ga]   — Go testing patterns
30. poetry           [ga]   — Python dependency management
31. yarn             [ga]   — Yarn-specific
32. npm              [ga]   — npm-specific
33. nvm              [ga]   — Node version management
34. asdf             [ga]   — multi-language version mgmt
35. deno             [ga]   — Deno runtime
36. parcel           [ga]   — Parcel
37. rollup           [ga]   — Rollup library bundling
38. turbopack        [ga]   — Turbopack patterns
39. gitlab-cli       [ga]   — glab CLI
40. percy            [ga]   — visual regression alternative
41. chromatic        [ga]   — visual regression
```

Git leads because everyone uses it and almost everyone uses it badly. Testing as a strategy pack precedes specific test frameworks. Vitest before Jest because it's the modern choice. Pytest at 4 because Python testing is its own world. Linting and Claude Code cluster — both are everyday-use tooling. Playwright over Cypress because it's winning. Modern tools (ruff, biome, uv) cluster in the early teens because they're rapidly displacing predecessors and users want guidance on the new hotness. Webpack low because its audience is shrinking toward esbuild/vite/turbopack. Mocha-chai near the bottom of the testing cluster because most new projects pick Vitest or Jest. The version-management packs (nvm, asdf) are deprioritized vs. mise because mise is the modern superset.

### Domain-class packs at `domain` tier (recall-favored)

```
1. llm-engineering   [v1]   — prompt engineering, RAG, eval, fine-tuning
2. agents            [v1]   — agent design patterns, MCP integration
3. cli-design        [ga]   — CLI UX, argument parsing
4. ml-fundamentals   [ga]   — training basics, evaluation, pitfalls
5. embeddings        [ga]   — embedding patterns, semantic search
6. ui-design         [v1]   — design system patterns, accessibility
7. saas-patterns     [ga]   — multi-tenancy, billing, onboarding
8. analytics         [v1]   — product analytics, instrumentation
9. data-engineering  [v1]   — ETL patterns, dbt, data modeling
10. vector-databases [v1]   — Pinecone, Weaviate, Qdrant, pgvector
11. mobile-patterns  [ga]   — mobile architecture, offline-first
12. realtime-collab  [ga]   — CRDT, OT, presence
13. dbt              [ga]   — dbt-specific patterns
14. data-viz         [ga]   — D3, observable, viz best practices
15. chatbots         [ga]   — chatbot/conversational design
16. ecommerce        [ga]   — generic ecommerce patterns
17. browser-extensions [ga] — Chrome/Firefox extension patterns
18. tui-development  [ga]   — terminal UI patterns
19. desktop-apps     [ga]   — Electron, Tauri patterns
20. fintech          [ga]   — financial application patterns, precision math
21. b2b              [ga]   — B2B patterns
22. cms              [ga]   — CMS patterns, headless CMS
23. airflow          [ga]   — workflow orchestration
24. geospatial       [ga]   — GIS, mapping, geo data
25. healthcare       [ga]   — HIPAA, FHIR
26. gamedev          [ga]   — game development patterns
27. martech-saas     [v1]   — martech (NaviStone-internal)
28. direct-mail      [v1]   — direct mail (NaviStone-internal)
29. arr-metrics      [v1]   — ARR/MRR (NaviStone-internal)
```

LLM engineering leads because it's the highest-demand domain right now and most existing resources are bad. Agents second because the MCP/agent ecosystem is exploding and lacks good patterns. CLI design at 3 because every developer hits it and almost no one does it well. ML fundamentals and embeddings cluster at 4-5. UI design at 6 because design systems are core to modern frontend. SaaS patterns at 7 because every B2B startup hits multi-tenancy. Analytics is universally needed. Data engineering, vector databases, mobile cluster in the middle. Niche industry packs (fintech, healthcare, gamedev) at the bottom because they have engaged but small audiences. NaviStone-internal packs are at the very bottom because they're not for general release.

### Domain-class packs at `protocol` tier (precision-favored, tightest ceiling)

```
1. rest              [v1]   — REST API design
2. jwt               [ga]   — JWT patterns, validation, pitfalls
3. oauth             [v1]   — OAuth flows
4. graphql           [v1]   — schema, resolvers, subscriptions
5. webhooks          [v1]   — webhook patterns
6. websockets        [ga]   — real-time patterns
7. oidc              [ga]   — OpenID Connect
8. mcp               [v1]   — Model Context Protocol
9. sse               [ga]   — Server-Sent Events
10. trpc             [ga]   — tRPC patterns
11. grpc             [ga]   — gRPC, protobuf
12. saml             [ga]   — SAML SSO
13. json-rpc         [ga]   — JSON-RPC patterns
14. mqtt             [ga]   — IoT messaging
```

REST leads because every API pack assumes REST literacy. JWT second because it's the most-misused thing in this tier — everyone uses JWTs and most do it wrong. OAuth third because the OAuth/OIDC complexity catches everyone. GraphQL at 4 because it's mainstream and confusing. Webhooks/websockets cluster for real-time. MCP at 8 because the audience is growing fast but still a slice of the broader developer population. Niche protocols (gRPC, SAML, JSON-RPC, MQTT) at the bottom.

### Workflow-class packs at `workflow` tier

```
1. sdd               [v1]   — sdd-spec, sdd-design, sdd-plan, sdd-testgen, sdd-build, sdd-verify, sdd-deliver
2. intake            [v1]   — v2 intake/routing workflow
3. code-review       [v1]   — code review checklists
4. release           [v1]   — release procedures
5. incident          [ga]   — incident response playbooks
6. postmortem        [ga]   — postmortem authoring and follow-through
7. rfc               [v1]   — RFC authoring guides
8. migration         [ga]   — large migration project management
9. design-review     [v1]   — design review workflows
10. arch-review      [v1]   — architecture review workflows
11. prd              [v1]   — product requirements document authoring
12. onboarding       [ga]   — new contributor onboarding flows
13. deprecation      [ga]   — feature/API deprecation playbooks
14. security-review  [ga]   — security review workflows
15. refactoring-workflow [ga] — large refactoring management
16. performance-review-workflow [ga] — performance investigation
```

SDD leads because it's the showpiece workflow that demonstrates the workflow class works end-to-end. Intake second because v2 routing depends on it. Code-review third because it's universally relevant and high-leverage. Release fourth because every project ships and most ship badly. Incident and postmortem cluster — incident response and learning from incidents are the highest-leverage operational workflows. RFC and migration at 7-8 because they're project-management-shaped and most teams need them but don't have them. The review workflows (design, arch, security) are valuable but more situational. Onboarding and deprecation are real but lower-frequency. Refactoring and performance workflows at the bottom because they overlap with other packs and the unique workflow value is narrower.

---

## Prioritization philosophy

Within each tier, packs are ordered by what would maximize value-per-pack across the user base. That's slightly different from prioritizing by demand alone. Some packs near the top (debugging, CLI design, git, JWT) are there because they're universally relevant and underserved by existing resources — Claude can add the most value where the ecosystem is weakest. Some packs near the bottom (Angular, webpack, mocha-chai) are there because their audiences are well-served by existing tooling and documentation — Claude adds less marginal value.

This is the order for build sequencing if choosing freely. Actual priorities should shift based on real NaviStone team needs versus general-release ambitions — these are starting points, not commandments.

## Pack count summary

```
v1 (NaviStone) packs:        ~29
ga additions:                ~155
total general-release:       ~185
estimated skill range:       900–1800 skills total at 5–10 skills per pack
```

The full ~185-pack inventory is the eventual destination, not the launch state. Recommended rollout:

1. Ship NaviStone v1 first (~29 packs). Architecture stabilizes.
2. Add the "core 50" general-access packs next: language packs (5–7), most common framework packs (8–10), must-have store packs (8–10), cross-cutting essentials (5–7), cloud providers (3–4), workflow expansions (5–8). Total roughly 80–85 packs.
3. Add the long tail (~100 more packs) opportunistically, prioritizing by what users actually request. Telemetry from v2 routing will tell you which packs are missing because routing will fail to find skills for certain queries. That's better signal than guessing.

## Notes on what's intentionally NOT included

- **Cloud-provider sub-services as separate packs.** No `aws-lambda`, `aws-rds`, `aws-s3` — those go inside the `aws` pack as skills. Pack layer is for coherent technologies, not every product within them.
- **Framework-specific testing packs.** No `react-testing`, `django-testing` — those belong inside the framework pack or the generic testing pack. Adding them as separate packs creates fragmentation.
- **Version-specific packs.** No `react-19`, `python-3.12`. Versions belong as content within the language/framework pack, not as separate packs. Otherwise the corpus accretes packs every six months.
- **Company-or-product-specific tooling beyond what's load-bearing.** Things like `notion-api`, `linear-api`, `slack-api` would be a separate "integrations" tier or domain — worth considering if the general-release corpus wants that breadth, but recommended deferred until v2 routing surfaces actual demand.
