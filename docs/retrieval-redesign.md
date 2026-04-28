# Retrieval Redesign + Core Product Scope

**Status:** Design approved, ready for implementation
**Author handoff:** Plan finalized 2026-04-27, implementation deferred to a fresh session

## Why

The OpenCode dry-run session (`ses_23077c561ffeAeyiTsXKuSSGP3`, transcript at `~/.local/share/opencode/`) exposed two structural problems with retrieval quality:

1. **Score compression.** `/retrieve` returns top-K cosine scores clustered in [0.27, 0.40] across all queries. No separation between rank-1 and rank-5 (gap ~0.05). The same 4–5 generic skills (`frontend-ui-engineering`, `react-state-management`, `browser-testing-with-devtools`, `context-engineering`) win every query regardless of intent — a textbook "centroid attractor" failure of weak embedders over a topically-overlapping corpus.
2. **No lexical leg.** Token-literal queries ("JWT", "Prisma", "NestJS") return zero literal-match skills. Pure dense cosine over a 300M-param Gemma embedder cannot recover token-level recall.

A planning conversation also surfaced a **product scope question**: should authoring be in the core install? The cpu/apple-silicon/nvidia presets ship `qwen3.5:0.8b` as `AUTHORING_MODEL`/`CRITIC_MODEL`. At 0.8B params, that model is too small to reliably draft and self-critique structured skill prose — it's checkbox compatibility, not capability. Only strix-point's `qwen3.6-35B` is realistically capable. Decision: **authoring is removed from the core product**. Code stays in the repo but is not pulled or executed by the default install path.

## What "core product" means going forward

The runtime path is LLM-free (per the v5.4 architecture note in `src/skillsmith/orchestration/compose.py:1-7,42-44`). Core product = retrieval API + corpus + skill instructions returned to a calling agent. The calling agent's main LLM does all reasoning. Skillsmith never invokes a generative model at runtime.

## Goals

- Top-1 cosine score ≥ 0.65 with clear separation from rank-2 on representative queries (vs. current 0.38–0.45 ceiling).
- Token-literal queries surface their literal-match skills in the top 5.
- Default install footprint ≤ 1GB. No LLM weights pulled by default.
- No hard runtime dependency on any LLM runner — `/compose` and `/retrieve` need only the embedder runner.
- `/retrieve` exposes raw scores without `diversity_select` mutation, for ongoing observability.

## Three coordinated fixes

### Fix 1 — Replace embedder with `qwen3-embedding:0.6b`

**Why this model:** MTEB English v2 retrieval score 61.83 — about 7 points stronger than mxbai-embed-large (~55) at the same install size, and within 1 point of NV-Embed-v2 which is 13× larger. Released 2025-06, 1.8M Ollama pulls. Code-retrieval trained, instruction-aware, 32K context, Matryoshka 32–1024 dim.

**Capabilities to leverage:**

- **Instruction prefix.** Prepend `"Given a software engineering task description, retrieve relevant skill instruction fragments: "` (or similar) to the query before embedding. Documented to add 2–5 retrieval points on instruction-aware models.
- **Index-time/query-time prefix consistency.** Whatever prefix convention is used at retrieval time MUST match the convention used at embed-time during authoring. Mismatched conventions kill recall.
- **Default to 1024 dim** for v1; revisit if index size becomes a concern.

**Files to modify:**

| File | Change |
|---|---|
| `src/skillsmith/install/presets/cpu.yaml` | Set embed model to `qwen3-embedding:0.6b` (Ollama runner) |
| `src/skillsmith/install/presets/apple-silicon.yaml` | Same |
| `src/skillsmith/install/presets/nvidia.yaml` | Same |
| `src/skillsmith/install/presets/strix-point.yaml` | Keep FastFlowLM as runner; verify FastFlowLM catalog for `qwen3-embedding:0.6b` (or comparable Qwen3-family variant). If unavailable, fall back to Ollama for strix-point's embed leg and document the fallback in a YAML comment. |
| `src/skillsmith/config.py:60,68` | Update code-level default to `qwen3-embedding:0.6b` |
| `src/skillsmith/retrieval/domain.py:129` | Wrap query in instruction prefix before `lm.embed()` |
| `src/skillsmith/authoring/qa_gate.py:486` | Match the same instruction-prefix convention so authored fragments are encoded consistently with retrieval queries |
| `tests/` | Update preset-shape assertions, add prefix-consistency tests |

**After swap:** the existing user-scope corpus must be re-embedded. The `skillsmith reembed` CLI exists at `src/skillsmith/reembed/cli.py`. **Verify before assuming** that it handles full model-change reindexing correctly (read the implementation, add tests if gaps found).

`pull-models` in install will auto-pull `qwen3-embedding:0.6b` via Ollama for the affected presets. No new runner type.

### Fix 2 — BM25 hybrid retrieval with RRF fusion

Add a lexical retrieval leg over the same fragment table. Fuse with the existing dense leg via Reciprocal Rank Fusion (k=60). Token-literal queries hit BM25 directly; semantic queries lean on dense. Each leg covers the other's weakness.

DuckDB has a native FTS extension that indexes text columns for BM25 scoring — single SQL join, no new storage, no new process.

**Files to modify:**

| File | Change |
|---|---|
| `src/skillsmith/retrieval/domain.py` | Add `_bm25_search(task) -> list[(fragment_id, rank)]` and `_rrf_fuse(dense_ranks, bm25_ranks, k=60) -> list[fragment_id]`. Replace the direct dense sort at `domain.py:129` with the fused output. |
| `src/skillsmith/storage/vector_store.py` | Extend `open_or_create()` to also build the FTS index on the fragment-prose column. One-time cost on first open; verify by checking `fts_main_*` table existence. |
| `src/skillsmith/retrieval/domain.py:170-172` | Add `request.raw_scores: bool` flag (or expose a separate response field) so `/retrieve` can return pre-`diversity_select` order for inspection. `/compose` keeps the diversity reshuffle. |
| `tests/test_retrieval_domain.py` (or equivalent) | Add cases for token-literal queries that should hit BM25 dominantly, and semantic queries that should hit dense. |

RRF is parameter-light (just `k=60`); no per-leg weighting needed for v1.

### Fix 3 — Remove authoring from core install

Authoring becomes opt-in, deferred from core. The cpu/apple-silicon/nvidia/strix-point presets stop pulling qwen-LLM weights by default.

**Files to modify:**

| File | Change |
|---|---|
| `src/skillsmith/install/presets/cpu.yaml` | Remove `AUTHORING_MODEL`, `CRITIC_MODEL` env vars and `ingest_model` entry |
| `src/skillsmith/install/presets/apple-silicon.yaml` | Same |
| `src/skillsmith/install/presets/nvidia.yaml` | Same |
| `src/skillsmith/install/presets/strix-point.yaml` | Same (qwen-35B no longer pulled by default) |
| `src/skillsmith/install/subcommands/recommend_models.py` | Remove `ingest_model` / `ingest_runner` recommendation logic, OR gate it behind a future `--with-authoring` flag |
| `src/skillsmith/install/subcommands/pull_models.py:128` | Drop the `("ingest_model", "ingest_runner")` tuple from the pull list |
| `src/skillsmith/config.py` | `authoring_model`, `critic_model` etc. become optional with no default values; raise a clear error if authoring code paths are invoked without them set |
| `src/skillsmith/authoring/__init__.py` (or per-module headers) | Add a top-of-module note that authoring requires explicit configuration |
| `README.md` / `docs/operator.md` | Note that core install is retrieval-only; authoring is a separate, advanced workflow requiring a 35B-class LLM (deferred to future release) |

Authoring code stays in the repo. It just isn't reachable through the default CLI/install.

## Suggested order of execution

1. **Fix 3 first** — smallest surface, biggest install-footprint win, simplifies preset YAMLs that Fix 1 will also touch.
2. **Fix 2 second** — embedder-agnostic, gives an immediate win on token-literal queries even before reembedding.
3. **Fix 1 last** — most disruptive (corpus reindex required) but biggest dense-quality lift.

This order also lets you measure each fix independently: re-run the probe set after each step, attribute the score lift to the correct change.

## Prerequisite already shipped

`/diagnostics/runtime` was 500ing because `diagnostics_router.py` referenced a removed `assembly_runtime` dependency key while `health_router` emits `runtime_cache`. Fix committed at `59b5ee8` on main (4 files, 9 insertions / 10 deletions).

A side-effect during that fix: the running uvicorn (PID 2162402, started by an earlier OpenCode session) was bound to the stale `~/dev/skill-api` repo with cwd-relative state, while the user-scope corpus at `~/.local/share/skillsmith/corpus/` had only a 16K stub of ladybug. The populated stores (27MB ladybug + 9MB skills.duck) were copied from `~/dev/skill-api/src/skillsmith/_corpus/` to `~/.local/share/skillsmith/corpus/`. The new server reports 153 skills loaded, store↔cache consistent. Mention this if a fresh session sees `cache_loaded: false` or empty `store_state`.

## Verification

Run from `~/dev/skillsmith` against a server pointed at the user-scope corpus.

### Probe set

`curl` `/retrieve` with `k=10`:

| Query | Phase | Expected top-3 contains |
|---|---|---|
| `add a darkmode toggle button to a webpage` | build | a UI/theming skill (frontend-ui-engineering OK; tailwind-design-system or design-system-patterns better) |
| `implement JWT refresh token rotation in a NestJS backend with Prisma` | spec | an auth skill OR (BM25 leg) any skill mentioning JWT/Prisma literally |
| `add prisma migration for new column` | build | BM25 should surface skills with literal "prisma" |
| `cqrs read model projection` | spec | cqrs-implementation, projection-patterns (these worked before — sanity check) |
| `make this form feel less janky` | build | a UX/interaction skill — pure semantic, no shared keywords with skill prose |

### Pass criteria

- Top-1 score ≥ 0.65 on at least 3 of 5 probes (vs. current 0.38–0.45 ceiling)
- Top-3 includes at least one task-relevant skill on all 5 probes (vs. current 0/4 in the OpenCode session)
- Score gap between rank-1 and rank-5 ≥ 0.15 (vs. current ~0.05)
- "Make this form feel less janky" probe (no keyword overlap) demonstrates dense leg is doing real work — should still surface a relevant UX skill

### Install verification

- Fresh install on a non-strix machine pulls only `qwen3-embedding:0.6b` (no qwen-LLM weights). Total download ≤ 700MB.
- `skillsmith setup` completes without prompting for LM Studio.
- `skillsmith status` reports retrieval ready, no authoring components mentioned in default flow.

### Test commands

```bash
cd ~/dev/skillsmith
uv run pytest tests/ -v
uv run ruff check src/ tests/
uv run pyright src/skillsmith/retrieval/ src/skillsmith/storage/ src/skillsmith/install/
.venv/bin/uvicorn skillsmith.app:app --host 127.0.0.1 --port 47950 &
# then run the probe set above
```

## Out of scope (deferred)

- **Authoring pipeline as a first-class user feature.** Code stays in repo, removed from default CLI/install. Becomes a separate "advanced workflow" with its own install path requiring a 35B-class LLM (local or remote). Re-scope when prioritized.
- **Cross-encoder reranker.** Qwen3 ships a matching reranker family (Qwen3-Reranker-0.6B/4B/8B). Adds a model dep + latency. Natural upgrade path if the dense+BM25 hybrid still has gaps after this redesign lands.
- **Runtime query rewriter / phase inference.** OpenCode session evidence (caveman-speak +0.07 score lift, no ranking change) shows this isn't the lever for the current quality problem. BM25 hybrid is. Document "have your agent expand the task into keywords before calling /compose" as a free user-side optimization pattern. Skillsmith should not embed an LLM in the runtime path.
- **Live A/B against LHC corpus** at `~/experiments/skillsmith-ab/` (5 replay tickets, 10 worktrees prepared). Runs after this fix lands.

## Reference: rejected alternatives

For posterity. None of these should be re-litigated unless new evidence emerges.

- **`bge-m3` unified retrieval (dense + learned sparse + ColBERT in one model).** Quadruples install footprint to ~1.1GB, slower queries, walks back the install-footprint goal, replaces a 150-LOC BM25 leg with custom sparse-vector storage. Capability we'd be paying for and not using.
- **`mxbai-embed-large` or `snowflake-arctic-embed:l`.** Same install footprint as Qwen3-Embedding-0.6B but ~7 MTEB points weaker on retrieval. Battle-tested but the quality gap doesn't justify the choice.
- **`nomic-embed-text:v1.5` (the original ≤300MB pick).** Lightest install but ~10 MTEB points weaker than Qwen3. Acceptable only if absolute minimum footprint is the dominant constraint.
- **Qwen-0.8B as runtime query rewriter** (instead of authoring). Re-introduces an LLM into the runtime path that v5.4 deliberately removed. Adds latency and a hard runner dependency. Caveman-speak evidence shows query rewriting alone doesn't fix the ranking problem — BM25 does.

## Open verification step for the implementer

Before editing `presets/strix-point.yaml`, list FastFlowLM's model catalog (`flm list` or equivalent) and confirm whether it serves `qwen3-embedding:0.6b` or a comparable Qwen3-family embedding variant. If yes, point strix-point at FastFlowLM. If no, route strix-point's embed leg through Ollama like the other presets and add a YAML comment explaining the fallback. This is the only architectural decision left ambiguous in the plan.
