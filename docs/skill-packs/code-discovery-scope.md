# Code Discovery Skill Pack — Scope (BUC-1573)

A pack of worker-LLM-facing fragments tuned to a recurring family of code-navigation queries: "where is X used", "where do we find Y", "explain how A interacts with B", "what should we modernize". The fragments inject grounding rules and discovery procedures so the synth/worker LLM produces concrete, file-cited answers instead of speculative module paths.

## Pack metadata

- **Name:** `code-discovery`
- **Tier:** `domain`
- **Status:** opt-in
- **Depends on:** `core`, `engineering`
- **Phase scope:** primarily `build`, secondary `spec` and `qa`

## Fragment inventory

| # | Skill ID | domain_tags | Trigger exemplars |
|---|---|---|---|
| 1 | `find-by-symbol-name` | symbol-lookup, references, callers, callees, lsp | "where is `program_id` used?", "what models reference `Campaign`?", "show me callers of `dispatchTurn`" |
| 2 | `find-by-concept` | hybrid-retrieval, candidate-locations, verify | "where can we find campaign IDs?", "where is creative metadata stored?", "where do we track plan budgets?" |
| 3 | `endpoint-locator` | http-routes, handlers, request-shape | "where is the endpoint that uploads creatives?", "which route handles spec submission?" |
| 4 | `cross-service-interaction` | cross-service, protocol, env-vars, code-paths | "explain how the orchestrator interacts with code-indexer", "how does Forge call Manifest?" |
| 5 | `optimization-scan` | dep-audit, dead-code, deprecations, hotspots | "what optimizations can be done?", "scan for deprecations and modernizations", "what should we refactor first?" |
| 6 | `data-model-trace` | data-model, schema, migrations, propagation | "what models and where are `program_ids` used?", "trace the `task_id` field across the schema" |
| 7 | `grounding-rules-for-discovery` | grounding, citations, hallucination-prevention | always-on grounding clause for any "where/how/which file" query |

## Fragment-by-fragment

### 1. find-by-symbol-name
**Trigger:** queries that name an exact symbol (function, class, type, constant, env var) and ask for its definition site, callers, or call-sites.
**Guidance:** Use the project's static call graph (LSP "find references", jcodemunch `search_symbols`/`find_references`, gitnexus `impact`) before scanning files by name. Distinguish definition vs. references vs. shadowed declarations (re-exports). Report file path + line + role (def/call/import) for every hit. Refuse to invent module paths — if the indexer returns nothing, say so and suggest a broader concept search.

### 2. find-by-concept
**Trigger:** "where can we find <thing>" where the thing is a domain concept rather than a literal symbol (campaign IDs, creative metadata, billing periods).
**Guidance:** Run hybrid retrieval — both literal substring search (BM25-style) for likely identifier spellings (`campaign_id`, `campaignId`, `CampaignID`) AND a semantic search over the codebase index. Return a ranked list of *candidate* locations and, for each, a one-line "how to verify this is the right one" check (read schema column, run a test, inspect a route handler). Never return a single answer with high confidence when the search was concept-based.

### 3. endpoint-locator
**Trigger:** "where is the endpoint that <verb>s <noun>?", "which route handles X?", "what HTTP path does Y hit?".
**Guidance:** The answer must include three artifacts: (a) the route registration file and line (`app.post('/upload', ...)` or framework-equivalent), (b) the handler function and its file, (c) the request body / params shape (Zod schema, OpenAPI spec, or the destructured params). Also report the HTTP method, the auth/middleware stack, and the response shape. If the endpoint is proxied (e.g. through Vite or an API gateway), show both the client-visible path and the upstream target.

### 4. cross-service-interaction
**Trigger:** "explain how X interacts with Y", "how does service A talk to service B".
**Guidance:** Name both sides: (i) the calling-side adapter/client file, (ii) the receiving-side route or subscriber. Identify the protocol (HTTP, WebSocket, message queue, in-process function call, MCP). List every relevant env var (base URL, API key, timeout) and the config file that sets defaults. Walk one concrete code path end-to-end with file:line citations. Call out failure modes (timeout, retry policy, fallback adapter) — these are the load-bearing parts when something breaks.

### 5. optimization-scan
**Trigger:** "what optimizations can be done?", "scan for deprecations / modernizations", "where is tech debt concentrated?".
**Guidance:** Methodical inventory beats generic suggestions. Cover, in order: (1) dependency audit — `npm audit`, `pip-audit`, deprecated packages, major-version-behind libs; (2) dead code — unreachable exports, unused files, never-imported symbols; (3) lint config gaps — disabled rules, missing strict-mode flags, unused TS strict options; (4) deprecated API usage — `Buffer()` constructor, `componentWillMount`, callback-style fs, etc.; (5) performance hotspots — N+1 queries, sync I/O on hot paths, missing indexes; (6) test coverage cliffs. For each finding, cite file:line and propose a *graded* fix (quick-win, medium, refactor) so the user can plan, not just react.

### 6. data-model-trace
**Trigger:** "what models use <field>?", "trace <field> across the schema", "where does <id> get persisted vs. logged?".
**Guidance:** Start at the schema definition (`prisma/schema.prisma`, SQL migrations, ORM model files). Enumerate every table/model that declares the field, including FK relationships. Then trace the field's flow: where it is produced (request handler, ingest job), where it is read (queries, joins), where it is logged or audited, and where it is exposed in API responses. Migrations history is in scope — show when the field was added/renamed. Cite file:line for every step. Distinguish "field declared" from "field used by name" (string-literal usage in logs, raw SQL).

### 7. grounding-rules-for-discovery
**Trigger:** any discovery-shaped question (where/how/which/what file). Acts as the always-on guardrail for the pack.
**Guidance:** Hard rules: (a) every claim about a file's existence or contents must include a path and (when relevant) a line number from the index, not from memory; (b) if the indexer returned no result, say "not found in index" instead of guessing a plausible path; (c) module paths are never inferred from naming conventions — verify with a search; (d) if multiple candidates exist, return all of them ranked, not one with false confidence; (e) tests count as code — include `*.test.*` files in results, but mark them as tests so the user knows.

## Mapping to user-supplied query patterns

| User query pattern | Primary fragment | Supporting |
|---|---|---|
| "where can we find campaign IDs?" | find-by-concept | data-model-trace, grounding-rules |
| "where is the endpoint that the creative is uploaded?" | endpoint-locator | grounding-rules |
| "what models and where are program_ids used and called?" | data-model-trace | find-by-symbol-name, grounding-rules |
| "explain how X codebase interacts with Y" | cross-service-interaction | grounding-rules |
| "what optimizations / deprecations / modernizations" | optimization-scan | grounding-rules |

## Non-goals

- Not a refactor execution guide (covered by `refactoring` pack).
- Not a debugger (covered by `core/debugging-systematic`).
- Not language-specific syntax (covered by language packs).

This pack is *retrieval-time* guidance: how to find things and how to write the answer when you do.
