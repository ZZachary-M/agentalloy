# Skillsmith — Architecture Reference

**Audience:** an AI coding agent reading this as context before working on the codebase.
**State documented:** current tree as of 2026-04-29 (`main` branch, 671 tests passing).
**Scope:** runtime service + authoring pipeline + install/CLI surface. No future state, no design rationale beyond what is in code or pinned constants.

This document is canonical. Where it conflicts with a comment, README sentence, or skill YAML, the source files cited inline win.

---

## 1. What skillsmith is

A FastAPI service + CLI that composes prompt fragments for coding agents. The agent sends a task; skillsmith returns concatenated raw prose drawn from a curated corpus of "skills" (engineering patterns, recipes, gotchas). **The runtime holds no generative LLM** — only an embedding model. Composition is RRF-fused hybrid retrieval (BM25 ⨉ dense) plus deterministic system-skill applicability filtering. The caller's own LLM consumes the output.

The corpus is curated offline through an authoring pipeline that does use LLMs (author + critic) and dedup against the live embedding index.

---

## 2. Repository layout

```
skillsmith/
├── src/skillsmith/             # Python package; 54 modules
│   ├── __main__.py             # `python -m skillsmith` entry point
│   ├── app.py                  # FastAPI app factory + lifespan
│   ├── config.py               # Pydantic Settings (env-driven)
│   ├── runtime_state.py        # RuntimeCache: read-through snapshot of active corpus
│   ├── ingest.py               # YAML → LadybugDB ingest CLI w/ validate + lint
│   ├── bootstrap.py            # System-skill bootstrap from fixtures/
│   ├── migrate.py              # Schema migration CLI
│   ├── applicability.py        # Pure system-skill applicability predicates
│   ├── api/                    # HTTP routers + Pydantic models
│   ├── orchestration/          # ComposeOrchestrator, RetrieveOrchestrator
│   ├── retrieval/              # domain (RRF), system (predicate), similarity
│   ├── reads/                  # Active-version-only DB queries + frozen DTOs
│   ├── storage/                # LadybugDB (Kùzu) + DuckDB vector store
│   ├── telemetry/              # DuckDB-backed composition trace writer
│   ├── authoring/              # Author → QA → revise pipeline
│   ├── skill_md/               # SKILL.md parser for system-skill bootstrap
│   ├── fixtures/               # Fixture loader (agent prompts, guidelines)
│   ├── reembed/                # Re-embed CLI (DuckDB ← LadybugDB sync)
│   ├── install/                # `skillsmith install ...` subcommands
│   │   ├── __main__.py
│   │   ├── mcp_server.py       # Minimal MCP stdio server (compose forwarder)
│   │   ├── server_proc.py      # Background server lifecycle
│   │   ├── state.py            # ~/.config/skillsmith/install-state.json
│   │   ├── presets/            # cpu, nvidia, radeon, apple-silicon
│   │   ├── harness_templates/  # Markdown fragments per harness
│   │   └── subcommands/        # 26 subcommand modules
│   ├── _packs/                 # SHIPPED CORPUS — 36 packs, 468 skill YAMLs
│   └── _corpus/                # (legacy/in-flight; not authoritative)
├── fixtures/                   # Agent prompts, system-skill bootstrap MD
│   ├── skill-authoring-agent.md   # Transform contract (source MD → review YAML)
│   ├── skill-authoring-guidelines.md  # R1–R8 quality rules
│   ├── skill-qa-agent.md       # Critic prompt
│   ├── system/                 # Atomic system-skill MD source
│   └── domain/                 # Test-fixture YAMLs (different shape; not ingestible)
├── docs/
│   ├── ARCHITECTURE.md         # (this file)
│   ├── PACK-AUTHORING.md       # pack.yaml schema reference
│   ├── operator.md             # Operator runbook
│   ├── skill-review-history/   # Adversarial reviews per batch
│   └── …
├── scripts/
│   ├── migrate-seeds-to-packs.py  # Classifier + manifest generator
│   ├── author_skill.py         # End-to-end author wrapper
│   └── export-corpus-to-yaml.py
├── skill-source/               # Authoring staging tree (NOT shipped)
│   ├── pending-qa/             # Author output, awaiting critic
│   ├── pending-review/         # Critic-approved, awaiting human ingest
│   ├── pending-revision/       # Critic-rejected, awaiting re-author
│   ├── needs-human/            # Budget exhausted / parse error
│   ├── rejected/               # Hard-dup or schema-fatal (terminal)
│   └── archive/                # Frozen historical
├── eval/                       # POC eval harness
├── tests/                      # 671 tests
├── compose.yaml                # Podman/Docker bring-up
├── compose.radeon.yaml         # AMD-specific override
├── Containerfile               # Service image
└── pyproject.toml              # Build + script targets
```

**Two YAML shapes coexist and are NOT interchangeable:**

| Shape | Found in | Loader |
|---|---|---|
| Ingest format (flat `raw_prose` + `fragments[]`) | `_packs/*/skill.yaml`, `skill-source/**` | `ingest.py` |
| Test-fixture format (nested `versions[]`) | `fixtures/domain/*.yaml` | `fixtures/loader.py` |

---

## 3. Storage layer

Two engines, no cross-engine joins on the hot path.

### 3.1 LadybugDB (Kùzu graph, structure of record)

`src/skillsmith/storage/ladybug.py` wraps the embedded Kùzu engine. Schema lives in `src/skillsmith/storage/schema_cypher.py` as DDL string constants and is applied by `LadybugStore.migrate()` (idempotent via `IF NOT EXISTS`).

**Node tables:**

| Node | Properties |
|---|---|
| `Skill` | `skill_id`, `canonical_name`, `category`, `skill_class` (`domain`\|`system`), `domain_tags[]`, `deprecated`, `always_apply`, `phase_scope[]`, `category_scope[]` |
| `SkillVersion` | `version_id`, `version_number`, `authored_at`, `author`, `change_summary`, `status` (e.g., `active`, `superseded`), `raw_prose` |
| `Fragment` | `fragment_id`, `fragment_type`, `sequence`, `content` |

**Relationships** (all unweighted, directional):

- `Skill -[:HAS_VERSION]-> SkillVersion`
- `Skill -[:CURRENT_VERSION]-> SkillVersion` (exactly one per skill — enforced by `reads/active.py:_run_consistency_guard`)
- `SkillVersion -[:DECOMPOSES_TO]-> Fragment`
- `Skill -[:REQUIRES_COMPOSITIONAL]-> Skill` (declared dependency)
- `Skill -[:REFERENCES_CONCEPTUAL]-> Skill` (soft cross-reference)

**Public surface** (`LadybugStore`):

- `open() / close()` — connection lifecycle
- `execute(cypher, params) → list[list[Any]]` — eager
- `iter_rows(cypher, params) → Iterator[list[Any]]` — lazy
- `scalar(cypher, params) → Any`
- `migrate()` — apply `NODE_TABLES` + `REL_TABLES` from `schema_cypher.py`

### 3.2 DuckDB (vectors + telemetry)

`src/skillsmith/storage/vector_store.py`. Single `.duck` file. Created by `open_or_create(path)` (idempotent).

**Tables:**

`fragment_embeddings` — primary retrieval index.

| Column | Type |
|---|---|
| `fragment_id` | VARCHAR PRIMARY KEY |
| `embedding` | FLOAT[1024] (L2-normalized at insert) |
| `skill_id` | VARCHAR |
| `category` | VARCHAR |
| `fragment_type` | VARCHAR |
| `embedded_at` | BIGINT (epoch ms) |
| `embedding_model` | VARCHAR |
| `prose` | VARCHAR (raw text used for BM25) |

Indexes: `idx_frag_emb_skill`, `idx_frag_emb_category`, `idx_frag_emb_type`. BM25 FTS index built via `PRAGMA create_fts_index` over `prose`.

`composition_traces` — telemetry.

| Column | Type |
|---|---|
| `trace_id` | VARCHAR PK |
| `request_ts` | TIMESTAMP |
| `phase`, `category`, `task_prompt` | VARCHAR |
| `selected_fragment_ids[]`, `source_skill_ids[]`, `system_skill_ids[]` | VARCHAR[] |
| `assembly_tier`, `assembly_model` | INT, VARCHAR (assembly_tier = 0 in current build; LLM assembly removed in v5.4) |
| `retrieval_latency_ms`, `assembly_latency_ms`, `total_latency_ms` | INT |
| `status`, `error_code` | VARCHAR |
| `response_size_chars` | INT |

Indexes: `idx_traces_ts`, `idx_traces_phase`, `idx_traces_status`.

**Public surface** (`VectorStore`):

- `open_or_create(path) → VectorStore`
- `insert_embeddings(items: Iterable[FragmentEmbedding]) → int` (normalizes at write time)
- `search_similar(query_vec, *, categories, fragment_types, k=10) → list[SimilarityHit]` — `array_cosine_distance` over normalized vectors (collapses to inner product)
- `search_bm25(query, *, categories, k=10) → list[BM25Hit]`
- `record_composition_trace(trace) → None`
- `l2_normalize(vec)` — module-level helper
- `count_embeddings()`, `count_traces()` — ops probes

**Constants:**

- `EMBEDDING_DIM = 1024` — pinned to `qwen3-embedding:0.6b`. Mismatch in `pack.yaml.embedding_dim` is hard-blocked at install time (`install_pack._check_embedding_dim`).

### 3.3 Active-version reads (`src/skillsmith/reads/`)

All compose-time reads go through `reads/active.py`, which enforces "only the current version is visible":

- `get_active_skills(store, *, skill_class=None) → list[ActiveSkill]`
- `get_active_skill_by_id(store, skill_id) → ActiveSkill | None`
- `get_active_fragments(store, *, skill_class, categories, domain_tags) → list[ActiveFragment]`
- `get_active_fragments_for_skill(store, skill_id) → list[ActiveFragment]`
- `get_active_version_by_id(store, version_id) → dict` (raises `InconsistentActiveVersion` if status ≠ `active`)

Each call runs `_run_consistency_guard` first — a cheap Cypher scan that rejects any `CURRENT_VERSION` edge pointing to a non-active version, or any active skill with no `CURRENT_VERSION`.

DTOs in `reads/models.py` are frozen dataclasses (cheaper than Pydantic across the hot path):

- `ActiveSkill(skill_id, canonical_name, category, skill_class, domain_tags, always_apply, phase_scope, category_scope, active_version_id)`
- `ActiveFragment(fragment_id, fragment_type, sequence, content, skill_id, version_id, skill_class, category, domain_tags)`

### 3.4 RuntimeCache (`src/skillsmith/runtime_state.py`)

A startup-loaded read-through snapshot of the active corpus. Loaded once in `app.lifespan` via `load_runtime_cache(store)`. If load fails, `app.state.runtime` is `None` and `/compose` + `/retrieve` return 503.

`RuntimeCache` interface:

- `get_active_skill_by_id(skill_id) → ActiveSkill | None`
- `get_active_skills() → list[ActiveSkill]`
- `get_version_detail(version_id) → VersionDetail | None`
- `get_active_fragments() → list[ActiveFragment]`

`VersionDetail` adds `raw_prose` to the version metadata (kept off `ActiveFragment` to keep that DTO small).

---

## 4. Runtime HTTP API

`src/skillsmith/app.py` is the FastAPI factory. Default port: 47950.

### 4.1 Lifespan & dependency injection

In the lifespan async context manager, `app.py` opens `LadybugStore`, creates the `VectorStore`, opens an `OpenAICompatClient` against the runtime embedding endpoint, builds `ComposeOrchestrator` + `RetrieveOrchestrator`, loads `RuntimeCache`, and registers `HealthChecker` + `DiagnosticsChecker` on `app.state`. On shutdown, all four resources are closed.

Three FastAPI dependencies are bound there for routers:

- `get_orchestrator() → ComposeOrchestrator`
- `get_retrieve_orchestrator() → RetrieveOrchestrator`
- `get_skill_store() → LadybugStore`

Tests override these via `app.dependency_overrides`.

### 4.2 Endpoints

| Method | Path | Module | Auth | Purpose |
|---|---|---|---|---|
| GET | `/health` | `api/health_router.py` | none | Dependency status (runtime_store, telemetry_store, embedding_runtime, runtime_cache) |
| GET | `/diagnostics/runtime` | `api/diagnostics_router.py` | none | Store-vs-cache consistency, per-path readiness |
| POST | `/compose` | `api/compose_router.py` | none | Hybrid retrieval + concatenation → JSON |
| POST | `/compose/text` | `api/compose_router.py` | none | Same as `/compose` but returns `result.output` as `text/plain` |
| POST | `/retrieve` | `api/retrieve_router.py` | none | Semantic retrieval; returns ranked skills (no concatenation) |
| GET | `/retrieve/{skill_id}` | `api/retrieve_router.py` | none | Direct fetch of one active skill's metadata + raw_prose |
| GET | `/skills/{skill_id}` | `api/skill_router.py` | none | Inspection: skill + active version + all fragments |

### 4.3 Compose request / response shapes

All in `src/skillsmith/api/compose_models.py`.

```python
Phase = Literal["spec", "design", "qa", "build", "ops", "meta", "governance"]

DEFAULT_K_BY_PHASE = {
    "build": 2, "ops": 2,
    "qa": 4, "spec": 4, "design": 4, "meta": 4, "governance": 4,
}
DEFAULT_MAX_TOKENS_BY_PHASE = {
    "build": 2048, "ops": 2048,
    "qa": 4096, "spec": 4096, "design": 4096, "meta": 4096, "governance": 4096,
}

class ComposeRequest(BaseModel):
    task: str                                  # min_length=1
    phase: Phase
    domain_tags: list[str] | None = None
    k: int | None = None                       # ge=1, le=50; default per phase
    def resolved_k(self) -> int: ...
```

Successful (200) responses are one of two discriminated types:

```python
class ComposedResult(BaseModel):
    status: Literal["ok"]
    result_type: Literal["composed"]
    task: str
    phase: Phase
    output: str                                # raw concatenated fragment text
    domain_fragments: list[FragmentRef]
    source_skills: list[SkillRef]
    system_fragments: list[FragmentRef]
    system_skills_applied: list[str]
    assembly_tier: int                         # 0 in current build
    latency_ms: LatencyBreakdown               # retrieval_ms, assembly_ms, total_ms
    recommended_max_tokens: int | None         # hint for the caller's downstream LLM call

class EmptyResult(BaseModel):
    status: Literal["ok"]
    result_type: Literal["empty"]
    output: Literal[""]
    reason: Literal["no_domain_fragments_matched"]
    # + system_fragments/system_skills_applied still populated
    recommended_max_tokens: int | None
```

503 responses use `ErrorResponse` with `stage: "retrieval" | "assembly"` and `code` enum. Reserved exception classes: `RetrievalStageError` (raised on embed model unavailable / embed failure) and `AssemblyStageError` (declared, never raised in current build).

### 4.4 Retrieve request / response shapes

`src/skillsmith/api/retrieve_models.py`.

```python
class RetrieveQueryRequest(BaseModel):
    task: str                                  # min_length=1
    phase: Phase
    domain_tags: list[str] | None
    k: int | None = None                       # ge=1, le=50
    def resolved_k(self) -> int: ...

class RetrieveQueryResponse(BaseModel):
    status: Literal["ok"]
    results: list[RetrieveQueryHit]            # skill_id, version_id, canonical_name, raw_prose, score

class RetrieveByIdResponse(BaseModel):
    status: Literal["ok"]
    skill_id: str
    canonical_name: str
    category: str
    skill_class: Literal["domain", "system"]
    active_version: ActiveVersionMeta          # version_id, version_number, authored_at, author, change_summary
    raw_prose: str
```

---

## 5. Compose orchestration

`src/skillsmith/orchestration/compose.py` — `ComposeOrchestrator`.

### 5.1 `POST /compose` request lifecycle

1. `compose_router.compose(req)` — Pydantic-validates `ComposeRequest`.
2. `ComposeOrchestrator.compose(req)` (async) — runs domain + system retrieval concurrently:

   ```python
   asyncio.gather(self.retrieve(req), self.retrieve_system(req))
   ```

3. **Domain leg** — `self.retrieve(req)` calls `retrieval.domain.retrieve_domain_candidates(...)`:

   - Build embedding query: prepend `"Given a software engineering task..."` to the task and embed via the runtime LM client.
   - `vector_store.search_similar(query_vec, categories=phase_to_categories(phase), k=pool_size)` → dense hits.
   - `vector_store.search_bm25(task, categories=..., k=pool_size)` → BM25 hits.
   - `_rrf_fuse(dense_hits, bm25_hits, k=60)` → ranked fragment_ids by reciprocal-rank-fusion score (`1 / (k + rank)`).
   - Hydrate `ActiveFragment` rows from `LadybugStore` (RuntimeCache preferred when loaded) filtered by category + `domain_tags`.
   - If `RUNTIME_DIVERSITY_SELECTION != "off"`, run `diversity_select(pool, k)` — greedy reshuffle that prefers `setup`, `execution`, `verification` types (`_DIVERSITY_PRIORITY`).
   - Return `RetrievalResult(candidates, eligible_count, retrieval_ms, scores_by_id)`.

4. **System leg** — `self.retrieve_system(req)` calls `retrieval.system.retrieve_system_fragments(req.phase)`:

   - Load all active system skills via `get_active_skills(store, skill_class="system")`.
   - Pure-function filter `applicability.filter_applicable_system_skills(...)` — rules (in order):
     - `always_apply == True` → include unconditionally.
     - `phase_scope` set and current phase in it → check `category_scope` (if also set, must match).
     - Otherwise exclude.
   - Collect every fragment from every matching skill.

5. If domain `candidates` is empty → return `EmptyResult` (200) with the system fragments still attached. Telemetry record written with `result_type="compose_empty"`.

6. Otherwise: concatenate domain + system fragment `content` strings into `output`, build `ComposedResult` with latencies + `recommended_max_tokens` (from `DEFAULT_MAX_TOKENS_BY_PHASE`). Telemetry written with `result_type="composed"`.

7. Embedding failure → `RetrievalStageError("embedding_model_unavailable" | "embedding_failed")` → 503 via `app.py` exception handler.

### 5.2 Phase → category map (`retrieval/domain.py:_PHASE_TO_CATEGORIES`)

Domain-fragment retrieval is filtered by phase to avoid cross-phase contamination (e.g., `qa` queries don't surface `governance` skills). The exact mapping is in `retrieval/domain.py`; broadly, each of the 7 phases enables 3–7 of the documented domain categories (`engineering`, `ops`, `review`, `design`, `tooling`, `quality`).

### 5.3 Constants of record

| Constant | Value | File |
|---|---|---|
| `_RRF_K` | 60 | `retrieval/domain.py` |
| `EMBEDDING_DIM` | 1024 | `storage/schema_cypher.py`, `storage/vector_store.py` |
| `_DIVERSITY_PRIORITY` | `("setup", "execution", "verification")` | `retrieval/domain.py` |
| Pool-size multiplier | configured, not pinned | `retrieval/domain.py` |
| `k` upper bound | 50 | `api/compose_models.py`, `api/retrieve_models.py` |

---

## 6. Retrieve orchestration

`src/skillsmith/orchestration/retrieve.py` — `RetrieveOrchestrator`. Two modes:

**`GET /retrieve/{skill_id}` → `by_id(skill_id)`:**

1. `asyncio.to_thread(_get_skill_by_id, skill_id)` — RuntimeCache first, falls back to store.
2. `asyncio.to_thread(_fetch_version_meta_and_prose, active_version_id)` — version metadata + `raw_prose`.
3. Build `RetrieveByIdResponse`. Telemetry `result_type="retrieve_by_id"`.
4. 404 if not found.

**`POST /retrieve` → `by_query(task, phase, domain_tags, k)`:**

1. `asyncio.to_thread(retrieve_domain_candidates, ..., k=k*2, raw_scores=True)` — same domain leg as `/compose` but k doubled (because of dedup in step 2) and diversity-selection skipped.
2. Dedup fragments to one-per-skill (best score wins).
3. Hydrate skill metadata for the survivors. Build `list[RetrieveQueryHit]`.
4. Telemetry `result_type="retrieve_by_query"`.

System-skill applicability is **not** evaluated for `/retrieve` — that's a compose-only concern.

---

## 7. Authoring pipeline

Source: `src/skillsmith/authoring/`.

### 7.1 CLI entry point

`python -m skillsmith.authoring <subcommand>` (`authoring/__main__.py`). Subcommands:

| Subcommand | Effect |
|---|---|
| `author <source-dir>` | Discover `**/SKILL.md`, run author LLM, write drafts to `pending-qa/` |
| `qa` | Run critic gate over `pending-qa/`, route per verdict |
| `revise` | Re-author `pending-revision/` with critic feedback |
| `run <source-dir>` | author → qa → revise loop until terminal verdicts |
| `run-batched <source-dir> [--max-rounds N]` | Same as `run`, capped iteration count |
| `summary` | Print per-skill state across staging dirs |

Exit codes: `EXIT_OK=0`, `EXIT_USAGE=1`, `EXIT_RUNTIME=2`.

### 7.2 Pipeline state machine (`authoring/pipeline.py`)

```
SKILL.md (source)
    │
    ▼ author_one()           [authoring/driver.py]
pending-qa/<skill_id>.yaml
    │
    ▼ qa_one()               [authoring/qa_gate.py]
    ├── deterministic check  → schema/vocab/skill_id collision
    ├── dedup search         → DuckDB cosine ≥ hard_threshold? ≥ soft_threshold?
    └── critic LLM           → approve | revise | reject
    │
    ├── hard dup           → rejected/        (terminal)
    ├── schema fatal       → needs-human/     (terminal)
    ├── approve            → pending-review/  (awaits human ingest)
    ├── revise + budget    → pending-revision/, then revise_one(), back to qa
    ├── budget exhausted   → needs-human/     (terminal)
    └── critic parse error → needs-human/     (terminal)
```

**Bounce budget:** per-skill counter in `qa_state.json` (location: `PipelinePaths.qa_state`). Default 3, configurable via `BOUNCE_BUDGET` env var.

### 7.3 Author stage (`authoring/driver.py`)

- `discover_skill_md(source_dir) → Iterator[Path]` — glob `**/SKILL.md`.
- `author_one(source, *, client, model, system_prompt, paths) → DraftResult`:

  - `client.chat(model=AUTHORING_MODEL, system=fixtures/skill-authoring-agent.md, user=<source>, temperature=0.2)`.
  - Parse YAML, extract `skill_id`, write `paths.pending_qa / f"{skill_id}.yaml"`.

- `revise_one(source, draft_path, *, critic_feedback, ...) → DraftResult` — re-author with critic feedback prepended to the user prompt.
- `load_authoring_prompt(repo_root) → str` — reads `fixtures/skill-authoring-agent.md`.

### 7.4 QA gate (`authoring/qa_gate.py`)

`qa_one(...)` runs three sub-stages:

1. **`run_deterministic`** — load YAML, validate against ingest schema (mirrors `ingest._validate`), check skill_id collision in `LadybugStore`.
2. **`run_dedup`** (`authoring/dedup.py`) — embed draft prose, search corpus:
   - `cosine ≥ 0.92` (`DEDUP_HARD_THRESHOLD`) → hard dup → reject.
   - `0.80 ≤ cosine < 0.92` (`DEDUP_SOFT_THRESHOLD`) → soft hits handed to critic.
3. **`run_critic`** — LLM call: `client.chat(model=CRITIC_MODEL, system=fixtures/skill-qa-agent.md, user=<draft + soft-dups>)` → parsed `CriticVerdict`.

Routing returns `GateResult` with the destination directory + reasoned verdict.

### 7.5 LM client (`authoring/lm_client.py`)

`OpenAICompatClient(base_url, *, api_key, timeout, transport)` — minimal `httpx`-based client targeting OpenAI-compatible endpoints (LM Studio, vLLM, Ollama's OpenAI shim).

- `chat(model, system, user, temperature) → str` — POST `/v1/chat/completions`, returns content of first choice.
- `embed(text, model) → list[float]` — POST `/v1/embeddings`.
- `list_models() → list[str]`.
- Errors: `LMClientError` (base), `LMUnavailable`, `LMTimeout`, `LMBadResponse`, `LMModelNotLoaded`.

No prompt-cache plumbing in code — caching, if any, is the LM Studio backend's responsibility.

### 7.6 Pipeline directory layout (`authoring/paths.py`)

`PipelinePaths(root: Path)` with properties:

- `pending_qa`, `pending_review`, `pending_revision`, `rejected`, `needs_human` — all under `<root>/skill-source/`.
- `qa_state` — `<root>/skill-source/.qa-state.json`.
- `ensure_all()` — `mkdir -p` for each.

---

## 8. Ingest validation (`src/skillsmith/ingest.py`)

`python -m skillsmith.ingest <path> [--force] [--yes] [--strict]`. `<path>` may be a single YAML or a directory (batch mode).

### 8.1 Vocabularies (frozensets)

| Set | Members |
|---|---|
| `_VALID_FRAGMENT_TYPES` | `setup`, `execution`, `verification`, `example`, `guardrail`, `rationale` |
| `_VALID_DOMAIN_CATEGORIES` | `engineering`, `ops`, `review`, `design`, `tooling`, `quality` |
| `_VALID_SYSTEM_CATEGORIES` | `governance`, `operational`, `tooling`, `safety`, `quality`, `observability` |
| `_VALID_PHASES` | `design`, `build`, `review` (note: smaller set than runtime `Phase` literal — system-skill `phase_scope` only uses these) |

### 8.2 Lint thresholds

```python
_FRAG_WORDS_WARN_MIN = 80      # qwen3-embedding:0.6b discriminant floor
_FRAG_WORDS_WARN_MAX = 800     # split-at-semantic-boundary target
_FRAG_WORDS_HARD_MIN = 20      # below this → hard fail
_FRAG_WORDS_HARD_MAX = 2000    # above this → hard fail
_TAGS_WARN_MAX = 5             # retrieval-oriented target
_TAGS_HARD_MAX = 8             # contract ceiling
_HEADING_ONLY_MAX_WORDS = 8    # heading-only fragment detector
```

### 8.3 Hard rules (`_validate`)

- `skill_id`, `canonical_name`, `raw_prose` non-empty.
- `skill_type ∈ {domain, system}`.
- For **system** skills:
  - `skill_id` starts with `sys-`.
  - `category ∈ _VALID_SYSTEM_CATEGORIES`.
  - Applicability: `always_apply=True` OR (`phase_scope` ∪ `category_scope` non-empty); the two are mutually exclusive.
  - `phase_scope ⊆ _VALID_PHASES`.
  - **Must not declare `fragments`** — ingest synthesizes a single `guardrail` fragment from `raw_prose`.
- For **domain** skills:
  - `category ∈ _VALID_DOMAIN_CATEGORIES`.
  - At least one fragment.
  - At least one `execution` fragment.
  - `fragment_type ∈ _VALID_FRAGMENT_TYPES`.
  - Sequences are contiguous integers (no gaps).
  - `len(domain_tags) ≤ _TAGS_HARD_MAX`.
  - Per fragment: non-empty content; `_FRAG_WORDS_HARD_MIN ≤ word_count ≤ _FRAG_WORDS_HARD_MAX`.
  - No heading-only stub fragments (markdown heading + ≤ `_HEADING_ONLY_MAX_WORDS`).

### 8.4 Lint warnings (`_lint`)

Promoted to errors with `--strict`. Otherwise printed to stderr and the file still ingests.

- `len(domain_tags) > _TAGS_WARN_MAX`.
- All fragments are `execution` (no diversity).
- Missing `rationale` (R8 — anchors "why" queries).
- Missing `verification` (R3 — mechanically checkable post-conditions).
- Per fragment:
  - `word_count < _FRAG_WORDS_WARN_MIN` (under floor).
  - `word_count > _FRAG_WORDS_WARN_MAX` (above target).
  - `fragment_type == "execution"` with heavy code fences (likely should be `example` per `fixtures/skill-authoring-agent.md` §"Special cases").
  - `content` is not a contiguous slice of `raw_prose` (modulo whitespace) — drift breaks BM25 retrieval against the canonical body.
- `change_summary` says `"imported from"` but `len(raw_prose) > 4000` (R6 — likely scaffolded, not imported verbatim).

### 8.5 Insert (`_insert`)

Single Cypher transaction:

1. (If `--force` and skill_id exists) `MATCH (s:Skill {skill_id})...DETACH DELETE` cascade.
2. `CREATE (s:Skill {...})`.
3. `CREATE (v:SkillVersion {...status: 'active'})`.
4. `CREATE (s)-[:HAS_VERSION]->(v)` and `CREATE (s)-[:CURRENT_VERSION]->(v)`.
5. For each fragment (or the synthesized system guardrail): `CREATE (f:Fragment {...})` and `CREATE (v)-[:DECOMPOSES_TO]->(f)`.

**`fragment_embeddings` is not written here.** Embedding is a separate `python -m skillsmith.reembed` step (§10).

### 8.6 Exit codes

| Code | Constant | Meaning |
|---|---|---|
| 0 | `EXIT_OK` | Loaded, or duplicate-and-nothing-to-do |
| 1 | `EXIT_USAGE` | Bad args / file not found |
| 2 | `EXIT_VALIDATION` | Schema or lint (in `--strict`) failure |
| 3 | `EXIT_DB` | Cypher / DB-side failure |
| 4 | `EXIT_DUPLICATE` | `skill_id` or `canonical_name` collision (without `--force`); distinct so `install-pack` can treat re-runs as benign |

---

## 9. Pack model

A pack is a directory with one `pack.yaml` manifest plus N skill YAMLs. Active corpus lives at `src/skillsmith/_packs/` (36 packs, 468 skills as of this write).

### 9.1 `pack.yaml` schema

Required:

| Field | Type | Notes |
|---|---|---|
| `name` | str | Lowercase, hyphenated, must match directory |
| `version` | semver str | Bump on any content change |
| `tier` | enum | One of `_VALID_PACK_TIERS` (§9.2). Hard-blocked at install if missing/invalid |
| `description` | str | One sentence; shown in install picker |
| `embed_model` | str | Soft-warned on mismatch with running corpus |
| `embedding_dim` | int | **Hard-blocked** on mismatch — mixing dims silently corrupts cosine search |
| `skills` | list | Each: `{skill_id, file, fragment_count}` (last is inventory check) |

Optional: `author`, `license`, `homepage`, `always_install` (bool, default `false`; only `core` + `engineering` set `true`), `depends_on` (list of pack names).

### 9.2 Pack tiers (`install_pack._VALID_PACK_TIERS`)

```python
frozenset({
    "foundation",     # always-installed (core, engineering)
    "language",       # nodejs, typescript, python, rust, go
    "framework",      # nestjs, react, fastify, vue, nextjs, fastapi (depends on a language)
    "store",          # postgres, mongodb, redis, s3, temporal, prisma
    "cross-cutting",  # auth, security, observability
    "platform",       # containers, iac, cicd, monorepo
    "tooling",        # testing, linting, vite, mocha-chai
    "domain",         # agents, ui-design, data-engineering
    "protocol",       # graphql, webhooks, websockets
})
```

Mapping for the 36 shipped packs is in `scripts/migrate-seeds-to-packs.py:PACK_TIERS`. Adding a new pack requires entries in both `PACK_TIERS` and `PACK_METADATA` there, plus the tier value must be in `_VALID_PACK_TIERS`.

### 9.3 Install-pack flow (`install/subcommands/install_pack.py`)

`skillsmith install install-pack <name>` or `<path>` or `<manifest-url>`.

1. Resolve target. Local dir → `<path>/pack.yaml`. Bare name → URL pattern `https://github.com/navistone/skill-pack-{name}/releases/latest/download/manifest.json`. Manifest URL → fetch and parse.
2. `_read_pack_manifest(pack_dir)` validates required fields, **rejects missing/invalid `tier`**, and cross-checks each `skills[].skill_id` and `fragment_count` against the corresponding YAML on disk (drift detection).
3. `_check_embedding_dim(manifest, root)` — opens the live `VectorStore`, refuses install if `manifest.embedding_dim ≠ vs.embedding_dim()`. Soft-warns on `embed_model` name mismatch when dims agree.
4. Tarball path: download + sha256-verify + extract.
5. Each skill YAML is run through `ingest.main([yaml, "--yes"])`. `EXIT_DUPLICATE` is treated as benign (idempotent re-install).

### 9.4 Migration / classifier (`scripts/migrate-seeds-to-packs.py`)

Provides:

- `PACK_RULES: list[(regex, pack_name)]` — classifies a skill_id into a pack.
- `PACK_TIERS: dict[pack_name, tier]`.
- `PACK_METADATA: dict[pack_name, {description, depends_on, always_install}]`.
- `write_pack_manifest(pack, entries)` — emits `pack.yaml` with `tier` field, raises `ValueError` if pack missing from `PACK_TIERS`.

Usage: `python scripts/migrate-seeds-to-packs.py [--dry-run | --apply]`. Dry-run prints proposed moves; apply executes git-aware moves and regenerates manifests.

---

## 10. Re-embed (`src/skillsmith/reembed/`)

`python -m skillsmith.reembed [options]` populates `fragment_embeddings` from LadybugDB fragments.

| Flag | Effect |
|---|---|
| (none) | Embed only fragments missing from DuckDB |
| `--skill-id <id>` | Limit to one skill |
| `--force` | Delete + reinsert all (full re-embed) |
| `--limit N` | Cap work; useful for tests |

For each fragment:

1. `embed(content, model=RUNTIME_EMBEDDING_MODEL)` against `RUNTIME_EMBED_BASE_URL`.
2. Retry 3 attempts (1s/2s/4s exponential backoff) on `LMTimeout` / `LMUnavailable`. Hard failures abort.
3. Write `(fragment_id, embedding, skill_id, category, fragment_type, embedded_at, embedding_model, prose)` to DuckDB. L2-normalization happens at write.

Idempotent: rerunnable after partial failure.

---

## 11. Configuration (`src/skillsmith/config.py`)

`Settings` is a Pydantic `BaseSettings`. Source order: env vars → `.env` file → defaults.

| Field | Env var | Default | Used by |
|---|---|---|---|
| `ladybug_db_path` | `LADYBUG_DB_PATH` | `$XDG_DATA_HOME/skillsmith/corpus/ladybug` (or `~/.local/share/...`) | runtime, ingest, reembed |
| `duckdb_path` | `DUCKDB_PATH` | `$XDG_DATA_HOME/skillsmith/corpus/skills.duck` | runtime, reembed, telemetry |
| `log_level` | `LOG_LEVEL` | `INFO` | global |
| `runtime_embed_base_url` | `RUNTIME_EMBED_BASE_URL` | `http://localhost:11434` | runtime retrieve/compose |
| `runtime_embedding_model` | `RUNTIME_EMBEDDING_MODEL` | `qwen3-embedding:0.6b` | runtime retrieve/compose, reembed |
| `lm_studio_base_url` | `LM_STUDIO_BASE_URL` | `http://localhost:1234` | authoring |
| `authoring_embed_base_url` | `AUTHORING_EMBED_BASE_URL` | None | authoring (dedup) |
| `authoring_model` | `AUTHORING_MODEL` | None | authoring (author stage) |
| `critic_model` | `CRITIC_MODEL` | None | authoring (qa stage) |
| `authoring_embedding_model` | `AUTHORING_EMBEDDING_MODEL` | None | authoring (dedup) |
| `dedup_hard_threshold` | `DEDUP_HARD_THRESHOLD` | `0.92` | authoring/dedup |
| `dedup_soft_threshold` | `DEDUP_SOFT_THRESHOLD` | `0.80` | authoring/dedup |
| `bounce_budget` | `BOUNCE_BUDGET` | `3` | authoring/pipeline |

Methods:

- `ensure_data_dirs()` — `mkdir -p` for `ladybug_db_path`'s parent and `duckdb_path`'s parent.
- `require_authoring_config() → AuthoringConfig` — raises `RuntimeError` if any authoring field is `None` (so the runtime can boot without authoring credentials).

The .env file generated by `install write-env` lives at `~/.config/skillsmith/.env`.

---

## 12. Install pipeline (`src/skillsmith/install/`)

`python -m skillsmith.install <subcommand>` (also exposed as `skillsmith install ...` script target). Subcommand registry: `install/__main__.py` + `install/subcommands/__init__.py`.

### 12.1 Subcommand inventory

User-facing one-shot:

- `setup` — composes the steps below in order; idempotent. Skips steps already present in install state. Steps: `detect → recommend-host-targets → recommend-models → pull-models → seed-corpus → install-packs → write-env → enable-service`.
- `wire` — auto-detect harness in current repo, inject sentinels.
- `unwire` — reverse `wire`.
- `status` — print install state + wired repos.
- `verify` — health checks against running service.
- `doctor` — extended diagnostics (network, ports, file permissions).
- `update` — re-pull models + re-seed.
- `uninstall` — remove install state, wired blocks, generated env.

Server lifecycle:

- `serve` — foreground uvicorn (calls `os.execvp` so SIGINT propagates clean).
- `server-start` — background spawn via `server_proc.start_background()`; stdout → `~/.local/share/skillsmith/server.log`; waits up to `--wait` (default 15s) for the port to accept connections.
- `server-stop` — port-based PID detection (`ss -tlnpH sport = :<port>`); SIGTERM with `--timeout` (default 10s), escalates to SIGKILL.
- `server-restart` — stop (if running) then start.
- `server-status` — JSON `{port, pid, reachable, log_path}`.
- `enable-service` — write systemd user unit (Linux) or LaunchAgent (macOS).

Standalone install steps (callable inside or outside `setup`):

- `detect`, `recommend-host-targets`, `recommend-models`, `pull-models`, `seed-corpus`, `install-pack`, `install-packs`, `write-env`, `wire-harness`, `reset-step`.

### 12.2 Install state (`install/state.py`)

Single JSON file at `~/.config/skillsmith/install-state.json` (XDG `user_config_dir()`).

```json
{
  "schema_version": 1,
  "completed_steps": [{"step": "...", "completed_at": "...", "...extras": "..."}],
  "harness_files_written": [{"repo_path": "...", "target": "..."}],
  "models_pulled": [{"name": "...", "hash": "..."}],
  "env_path": "~/.config/skillsmith/.env",
  "port": 47950,
  "last_verify_passed_at": "..."
}
```

`schema_version` mismatch returns exit code 3 (forces explicit migration). Per-step intermediate JSONs land under `~/.local/share/skillsmith/outputs/<step>.json`.

### 12.3 Server lifecycle internals (`install/server_proc.py`)

- **No PID files.** Detection is always port-based: parse `ss -tlnpH sport = :<port>` for `pid=N`.
- `start_background(cmd, env, log_path)` — `subprocess.Popen` with `start_new_session=True`, redirected stdout/stderr; returns child PID.
- `is_listening(port, timeout=1.0)` — TCP connect probe.
- `find_pid_on_port(port)` — `ss` parse.
- `stop_pid(pid, timeout)` — SIGTERM, poll `/proc/<pid>/status` for zombie state, SIGKILL on timeout.

Single-writer guarantee: enforced at the `LadybugStore` layer (Kùzu's filesystem lock); `server-start` does **not** add a separate lockfile. Two simultaneous servers will have one fail to open the DB.

### 12.4 Hardware presets (`install/presets/`)

YAML files: `cpu.yaml`, `nvidia.yaml`, `radeon.yaml`, `apple-silicon.yaml`. All write the same env-var set; the only difference is the embedding endpoint (port 11434 for Ollama presets, 1234 for `radeon` LM Studio).

```yaml
# Common (all presets)
RUNTIME_EMBEDDING_MODEL: qwen3-embedding:0.6b
DEDUP_HARD_THRESHOLD: "0.92"
DEDUP_SOFT_THRESHOLD: "0.80"
BOUNCE_BUDGET: "3"
LOG_LEVEL: INFO

# Differs
# cpu / nvidia / apple-silicon:
RUNTIME_EMBED_BASE_URL: http://localhost:11434
# radeon:
RUNTIME_EMBED_BASE_URL: http://localhost:1234
```

`write-env`:

- Loads selected preset.
- Accepts `--overrides KEY=VALUE` (repeatable).
- Writes `~/.config/skillsmith/.env` with sentinel header `# Generated by skillsmith install write-env`.
- Records path in install state.

### 12.5 Harness wiring (`install/subcommands/wire.py`, `wire_harness.py`)

Harness detection priority: tool-specific dotfiles first → `CLAUDE.md` fallback.

| Harness | Target file | Mode | Vector |
|---|---|---|---|
| `claude-code` | `CLAUDE.md` | shared+sentinel | markdown injection |
| `cursor` | `.cursor/rules/skillsmith.mdc` (modern) or `.cursorrules` | dedicated / shared | markdown |
| `gemini-cli` | `GEMINI.md` | shared+sentinel | markdown |
| `aider` | `.skillsmith-aider-instructions.md` | dedicated | system_prompt |
| `cline` | `.clinerules` | shared+sentinel | system_prompt |
| `opencode` | `.opencode/system-prompt.md` | dedicated | system_prompt |
| `continue-closed` | `.continuerc.json` | shared (JSON merge) | markdown |
| `continue-local` | `.continuerc.json` | shared (JSON merge) | system_prompt |
| `manual` | stdout | none | manual copy-paste |

Sentinel block format:

```
<!-- BEGIN skillsmith install -->
... template body with {port} substituted ...
<!-- END skillsmith install -->
```

`--force` overwrites a user-edited block; default refuses if sentinels are missing or unmatched.

`--mcp-fallback` writes an MCP server config instead of markdown — used by harnesses that prefer strict tool calls (see §13).

Templates are markdown fragments under `install/harness_templates/` keyed by harness name.

### 12.6 Doctor / verify

- `doctor` — checks: port reachable, embed endpoint reachable, embed model present (`/v1/models` listing), DuckDB readable, LadybugDB readable.
- `verify` — POSTs a known task to `/compose`, asserts non-empty `output`, records `last_verify_passed_at` in state.

---

## 13. MCP server (`install/mcp_server.py`)

A minimal MCP stdio server with no SDK dependency. Speaks JSON-RPC 2.0 (MCP protocol version 2024-11-05) over stdin/stdout.

**Tools exposed:**

- `get_skill_for(task: str, phase: str)` — forwards to local `POST /compose` and returns the `output` text.

**Run:**

```bash
python -m skillsmith.install.mcp_server --port 47950
```

Used by `wire --mcp-fallback` for harnesses that consume MCP tools.

---

## 14. Telemetry (`src/skillsmith/telemetry/`)

`DuckDBTelemetryWriter` — synchronous inline-before-response writes; failures are logged but never propagated to the HTTP response.

Schema lives in `composition_traces` (§3.2). Captured per request:

- `trace_id` (uuid)
- `request_ts` (UTC)
- `phase`, `category`, `task_prompt`
- `selected_fragment_ids`, `source_skill_ids`, `system_skill_ids`
- `assembly_tier` (always `0` in current build), `assembly_model` (none — assembly removed in v5.4)
- `retrieval_latency_ms`, `assembly_latency_ms` (always 0), `total_latency_ms`
- `status` (`composed` | `compose_empty` | `retrieve_by_id` | `retrieve_by_query` | `error_*`), `error_code`
- `response_size_chars`

There is no separate telemetry transport; all traces stay in the same DuckDB file as embeddings.

---

## 15. Bootstrap & migration

`python -m skillsmith.migrate` — applies LadybugDB DDL + creates DuckDB tables. Idempotent. Run first on a fresh data dir.

`python -m skillsmith.bootstrap [path]` — imports atomic system-skill markdown from `fixtures/system/*.md` (parsed by `skill_md/parser.py`) into LadybugDB. The Skill Authoring Agent itself ships as one such system skill (`fixtures/skill-authoring-agent.md` → `sys-skill-authoring-agent`).

---

## 16. Fixtures vs corpus

| Path | Purpose | Loader |
|---|---|---|
| `fixtures/system/*.md` | System-skill bootstrap source | `bootstrap.py` → `skill_md/parser.py` |
| `fixtures/domain/*.yaml` | **Test fixtures only** — multi-version export shape | `fixtures/loader.py` |
| `fixtures/skill-authoring-agent.md` | Transform contract; loaded as a system skill | `bootstrap.py` |
| `fixtures/skill-qa-agent.md` | Critic prompt | `authoring/qa_gate.py` |
| `fixtures/skill-authoring-guidelines.md` | R1–R8 quality rules (human-readable) | not loaded into corpus |
| `src/skillsmith/_packs/` | **Shipped corpus** — ingest-format YAML | `ingest.py` |
| `skill-source/` | Authoring staging (not shipped) | `authoring/*` + `ingest.py` |

`fixtures/domain/*.yaml` will fail `ingest.py` validation — the shapes are not compatible.

---

## 17. Containers (`compose.yaml`)

Three services on the default network:

| Service | Image | Port | Notes |
|---|---|---|---|
| `ollama` | `docker.io/ollama/ollama:latest` | 11434 | Models persisted to named volume `skillsmith-ollama-models` |
| `ollama-pull` | same image, `command: pull qwen3-embedding:0.6b` | — | One-shot init; `restart: "no"`; runs to completion |
| `skillsmith` | built from `Containerfile` | 47950 | `depends_on: ollama-pull` (`service_completed_successfully`); `./data` bind-mounted to `/app/data` |

Healthchecks:

- `ollama` — `ollama list` every 10s (5s timeout, 12 retries).
- `skillsmith` — HTTP GET `/health` every 15s (5s timeout, 3 retries; 10s `start_period`).

`compose.radeon.yaml` is a Radeon-specific override (LM Studio @ 1234 instead of Ollama).

---

## 18. Module reference (one line each)

`src/skillsmith/`:

| File | Purpose |
|---|---|
| `__init__.py` | Package marker; version. |
| `__main__.py` | `python -m skillsmith` dispatcher. |
| `app.py` | FastAPI app factory + lifespan + exception handlers. |
| `applicability.py` | Pure system-skill applicability predicates. |
| `bootstrap.py` | Import system-skill MD into LadybugDB. |
| `config.py` | Pydantic `Settings`. |
| `ingest.py` | YAML → LadybugDB CLI; `_validate` (hard) + `_lint` (warnings). |
| `migrate.py` | Schema migration CLI. |
| `runtime_state.py` | `RuntimeCache` + `VersionDetail`. |

`src/skillsmith/api/`:

| File | Purpose |
|---|---|
| `compose_models.py` | `Phase`, `ComposeRequest`, `ComposedResult`, `EmptyResult`, defaults. |
| `compose_router.py` | `POST /compose`, `POST /compose/text`. |
| `retrieve_models.py` | `RetrieveQueryRequest/Response`, `RetrieveByIdResponse`. |
| `retrieve_router.py` | `POST /retrieve`, `GET /retrieve/{skill_id}`. |
| `skill_router.py` | `GET /skills/{skill_id}`. |
| `health_router.py` | `GET /health`. |
| `diagnostics_router.py` | `GET /diagnostics/runtime`. |

`src/skillsmith/orchestration/`:

| File | Purpose |
|---|---|
| `compose.py` | `ComposeOrchestrator`. |
| `retrieve.py` | `RetrieveOrchestrator`. |

`src/skillsmith/retrieval/`:

| File | Purpose |
|---|---|
| `domain.py` | RRF-fused hybrid retrieval; phase→category map; diversity selector. |
| `system.py` | Applicability-filtered system fragment retrieval. |
| `similarity.py` | Cosine helpers used across retrieval + tests. |

`src/skillsmith/storage/`:

| File | Purpose |
|---|---|
| `ladybug.py` | Kùzu wrapper. |
| `vector_store.py` | DuckDB vector + telemetry. |
| `schema_cypher.py` | DDL constants. |

`src/skillsmith/reads/`:

| File | Purpose |
|---|---|
| `models.py` | Frozen DTOs (`ActiveSkill`, `ActiveFragment`). |
| `active.py` | Active-version-only Cypher reads + consistency guards. |

`src/skillsmith/authoring/`:

| File | Purpose |
|---|---|
| `__main__.py` | Authoring CLI. |
| `driver.py` | Author + revise stages. |
| `pipeline.py` | Full author→qa→revise loop orchestrator. |
| `qa_gate.py` | Deterministic + dedup + critic gate. |
| `dedup.py` | Embedding-based corpus dedup. |
| `lm_client.py` | OpenAI-compatible HTTP client. |
| `paths.py` | Pipeline staging paths. |

`src/skillsmith/skill_md/`:

| File | Purpose |
|---|---|
| `parser.py` | SKILL.md → ReviewRecord (system-skill bootstrap format). |

`src/skillsmith/install/`:

| File | Purpose |
|---|---|
| `__main__.py` | Install CLI dispatcher. |
| `mcp_server.py` | Minimal MCP stdio server (forwards `get_skill_for` to `/compose`). |
| `server_proc.py` | Background server lifecycle + port-based PID detection. |
| `state.py` | `~/.config/skillsmith/install-state.json` reader/writer. |
| `subcommands/setup.py` | Composes the full setup pipeline. |
| `subcommands/install_pack.py` | Pack manifest validation (incl. `_VALID_PACK_TIERS`) + ingest. |
| `subcommands/install_packs.py` | Multi-pack installer driven by install state. |
| `subcommands/serve.py` | Foreground uvicorn (`os.execvp`). |
| `subcommands/server_*.py` | Background lifecycle verbs. |
| `subcommands/seed_corpus.py` | Bootstrap shipped `_packs` into a fresh corpus. |
| `subcommands/wire.py`, `wire_harness.py`, `unwire.py` | Harness wiring. |
| `subcommands/write_env.py` | Render `.env` from preset. |
| `subcommands/pull_models.py` | Pull embedding model from configured backend. |
| `subcommands/recommend_*.py` | Hardware-aware recommendations. |
| `subcommands/detect.py` | Hardware discovery. |
| `subcommands/doctor.py`, `verify.py`, `status.py` | Ops verbs. |
| `subcommands/update.py`, `uninstall.py`, `reset_step.py` | Maintenance verbs. |
| `subcommands/enable_service.py` | systemd / launchd unit installer. |

`src/skillsmith/reembed/`:

| File | Purpose |
|---|---|
| `__main__.py` | `python -m skillsmith.reembed` entry. |
| `cli.py` | Re-embed implementation (retry + filters). |

`src/skillsmith/telemetry/`:

| File | Purpose |
|---|---|
| `writer.py` | `DuckDBTelemetryWriter` + `TelemetryRecord`. |

---

## 19. Things to verify before acting on this document

This file is a current-state map. Volatile invariants you should re-check via the cited file paths before depending on them in code:

- The exact phase→category mapping in `retrieval/domain.py` (`_PHASE_TO_CATEGORIES`) — small dict, changes occasionally.
- The exact contents of `_VALID_PACK_TIERS` in `install/subcommands/install_pack.py` — changing this requires a coordinated edit in `scripts/migrate-seeds-to-packs.py:PACK_TIERS`.
- All thresholds in `ingest.py` (`_FRAG_WORDS_*`, `_TAGS_*`, `_HEADING_ONLY_MAX_WORDS`).
- Whether `RuntimeCache` is loaded (`app.state.runtime is not None`) before assuming `/compose` will not 503.

---

## 20. What this document does not cover

- Eval harness (`eval/`) — out of scope.
- Per-skill content of the shipped 468 YAMLs — see `docs/skills-inventory.md` and `docs/CORPUS-AUDIT-2026-04-28.md`.
- Adversarial review history — see `docs/skill-review-history/`.
- The R1–R8 quality rules — see `fixtures/skill-authoring-guidelines.md`.
- The pending corpus quality remediation plan — see `docs/skill-review-history/2026-04-28-corpus-yaml-quality-review.md`.
