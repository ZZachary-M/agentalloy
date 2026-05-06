# Reverse-Engineering an Existing Codebase — One-Pager

**Question:** "Is this architecture capable of reverse-engineering an existing codebase?"
**Short answer:** Yes — and it is already doing it on this repo (3615 symbols, 8389 relationships, 267 execution flows extracted, no prior docs required).
**Author:** Nate Meyers · Last updated: 2026-05-06

## What "reverse engineer a codebase" decomposes into

A useful code-intelligence system has to answer four classes of question without pre-existing documentation:

| Question | Layer | Example |
|---|---|---|
| **What is this?** | Symbol table | "Show me `validateUser`'s signature, file, members." |
| **What's connected to it?** | Structural graph | "Who calls `validateUser`? What does it depend on?" |
| **What does it mean conceptually?** | Semantic search | "Find the auth validator." (no identifier known) |
| **What does it participate in?** | Process / flow detection | "Show me the request path for POST /login." |

Each requires a different storage primitive. A single engine answers two of the four well at most.

## The architecture

Two engines, one query plane:

```
                ┌─────────────────────────────────────────┐
                │           Query coordinator             │
                └────────────────┬────────────────────────┘
                                 │
          ┌──────────────────────┴──────────────────────┐
          ▼                                             ▼
┌───────────────────────┐                  ┌──────────────────────────┐
│  DuckDB               │                  │  Graph DB (LadyBugDB)    │
│  ─────────────────    │                  │  ───────────────────     │
│  • Vector index       │                  │  • Symbol nodes          │
│    (embedding/HNSW)   │                  │  • SymbolAtCommit nodes  │
│  • BM25 / FTS over    │                  │  • CodeChunk nodes       │
│    raw chunk text     │                  │  • CALLS / IMPORTS /     │
│  • Stores chunk body  │                  │    EXTENDS / IMPLEMENTS  │
│                       │                  │    / OVERRIDES /         │
│  Answers              │                  │    PARTICIPATES_IN edges │
│  "find by concept"    │                  │                          │
│                       │                  │  Answers                 │
│                       │                  │  "what it means /        │
│                       │                  │  depends on"             │
└───────────────────────┘                  └──────────────────────────┘
          ▲                                             ▲
          └──── chunk_id / symbol_id are join keys ─────┘
```

| Concern | DuckDB | LadyBugDB |
|---|---|---|
| Find chunks by concept (embedding) | ✓ | – |
| Find chunks by identifier (BM25) | ✓ | – |
| "Who calls X?" | – | ✓ |
| "What does X depend on?" | – | ✓ |
| "Show me code conceptually similar to X" | ✓ | – |
| "Show me code structurally connected to X" | – | ✓ |
| Versioning / commit-pinning | – | ✓ |
| Process / execution flow detection | – | ✓ |

## How reverse-engineering actually runs

**Phase 1 — Static extraction (Tree-sitter or equivalent):**

- Parse every source file → symbol table (functions, classes, methods, types).
- Resolve references → emit edges (`CALLS`, `IMPORTS`, `EXTENDS`, `IMPLEMENTS`, `OVERRIDES`).
- Chunk each symbol's body + docstring → store in DuckDB.
- Embed chunks with a code-aware model (qwen3-coder-embedding, jina-code, etc.).

**Phase 2 — Process inference:**

- Cluster symbols by shared call-graph reachability + naming co-occurrence.
- Detect entry points (HTTP handlers, CLI commands, message subscribers).
- Trace transitive `CALLS` from each entry point until terminal sinks.
- Each trace = one "execution flow," materialized as a Process node with ordered participants.

**Phase 3 — Query.** The same indexed corpus answers all four question classes from the table above by routing across the two engines.

## Canonical workflows the architecture supports out of the box

| Workflow | How it runs |
|---|---|
| **"How does login work?"** | Concept search → entry point handler → walk `CALLS` downstream → return ordered execution flow with file:line annotations. |
| **"Where's the rate limiter?"** | Vector search on `"rate limit token bucket throttle"` → top-K chunks → resolve to symbols → return file:line. No identifier known up front. |
| **"What breaks if I rename `validateUser`?"** | Graph walk `← CALLS / ← IMPORTS` from `validateUser` to depth 3. Returns d=1 (will-break), d=2 (likely affected), d=3 (test impact). |
| **"What modules talk to each other?"** | Graph projection of `IMPORTS` collapsed to module nodes → render as dependency diagram. |
| **"Show me all places that touch the order schema."** | Vector search + `ACCESSES` traversal from the schema symbol. |

## What it can do (concrete)

- **Symbol resolution** across files/packages, including overloads and method dispatch on declared types.
- **Call graphs** with confidence scores (1.0 for static, <1.0 for inferred polymorphic dispatch).
- **Import / dependency graphs** at file, module, and package granularity.
- **Type / inheritance hierarchies.**
- **Execution flow detection** — synthesizes "how a request flows through the code" from static structure plus heuristics.
- **Concept search** — find functionality you can describe but can't name.
- **Impact analysis** — blast radius before edits, with risk grading (LOW / MED / HIGH / CRITICAL).
- **Safe refactors** — `rename` is graph-aware (updates every caller) instead of textual.
- **Cross-commit history** — `Symbol HAS_VERSION SymbolAtCommit` lets you ask "how did this function look 3 months ago?"

## Honest limitations

- **Dynamic dispatch** (reflection, eval, runtime DI containers) — best-effort. Calls below 0.7 confidence are flagged.
- **Cross-language boundaries** (FFI, RPC, GraphQL resolvers, message-queue consumers) — need explicit edge declarations or schema-driven inference. Not free.
- **Generated code** — only indexed if generation runs before the indexer. Add to the build step.
- **Behavior-driving config** (Kubernetes YAML, Terraform, OpenAPI) — out of the structural graph; needs config-aware extractors as separate node types.
- **Runtime characteristics** — performance, race conditions, memory profile. Out of scope; this is static + semantic, not dynamic instrumentation.
- **Comment / docstring drift** — concept search is only as good as the prose attached to the code. Stale comments mislead.

## Why neither engine alone reverse-engineers well

- **Pure vector store:** "Find the auth validator" works. "Who calls it?" doesn't — vector neighbors aren't structural callers.
- **Pure graph DB:** "Who calls `validateUser`?" works. "Find the auth validator (don't know its name)" doesn't — graphs match on identity, not similarity.
- **Hybrid engines** (graph DBs with vector extensions, vector DBs with relationship tables) currently lose on either query latency or lifecycle stability. Kùzu's VECTOR extension has a known load-time circular-dependency that breaks restartable services. We picked split engines deliberately.

## Operational reality

- **Two engines = two writers.** Indexer commits graph first, embeddings follow within seconds. Eventual consistency at the chunk level is acceptable.
- **Re-embedding** (model upgrade) only touches DuckDB. Graph schema changes only touch LadyBugDB. Independent failure domains.
- **Cost:** ~50ms p95 query latency, ~0.5 SRE for monitoring + backups + version drift, ~50MB on-disk per 1M LOC indexed.
- **Incremental updates** are O(changed-files), not O(repo-size). A normal commit re-indexes in seconds.

## Recommendation

Use this architecture when the codebase is large enough (>50K LOC) that grep + tree-sitter alone don't scale, and at least two of these queries matter operationally:

- "Where is X?" (concept search, no name known)
- "Who depends on X?" (impact analysis)
- "How does X work?" (execution flow trace)
- "Is it safe to rename X?" (graph-aware refactor)

Skip it if your team only ever does the first ("where is X?") with known identifiers — ripgrep is cheaper.

## References

- Working implementation on this repo: `gitnexus` MCP server (3615 symbols, 8389 relationships, 267 flows already extracted).
- Storage layer: `src/skillsmith/storage/{ladybug.py,vector_store.py,schema_cypher.py}`
- Same split powers Skillsmith's skill corpus (prose-about-code) — the architecture is isomorphic between "indexing code" and "indexing what code teaches."
