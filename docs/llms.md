# Skillsmith Retrieval & Skill Assembly: Architecture & Proposed Improvements

## 1. Architecture Overview
Skillsmith currently operates as a **deterministic, dual-path Retrieval-Augmented Generation (RAG) context assembly engine**. Critically, it **does not perform LLM generation on the hot path**. Instead, it transforms an incoming task prompt into a structured, skill-augmented context string, which is then handed off to a downstream inference model.

The pipeline is divided into three core stages:
1. **Parallel Retrieval**: Semantic (dense vector) and lexical (BM25) searches run concurrently.
2. **Deterministic Filtering & Fusion**: Results are merged via Reciprocal Rank Fusion (RRF) and filtered by hard-coded applicability rules.
3. **Context Assembly**: System governance instructions are prepended to domain fragments, structured by skill, and returned as plaintext.

## 2. Prompt-to-Skill Execution Flow
When a `POST /compose` request hits `src/skillsmith/api/compose_router.py`, the following occurs:

### A. Request Routing & Orchestration
- `ComposeOrchestrator.compose(req)` spawns two async tasks via `asyncio.gather`:
  - **Domain Retrieval**: `retrieve_domain_candidates()` in `retrieval/domain.py`
  - **System Retrieval**: `_retrieve_system_sync()` in `orchestration/compose.py`

### B. Domain Retrieval (Hybrid Search)
1. **Query Preparation**: The raw `task` prompt is wrapped in a Qwen3-Embedding canonical template:
   `Instruct: Given a software engineering task description, retrieve relevant skill instruction fragments\nQuery:{task}`
2. **Dense Leg**: `lm.embed()` generates a 1024-dim vector. `vector_store.search_similar()` computes cosine distances against L2-normalized fragment embeddings.
3. **Lexical Leg**: `vector_store.search_bm25()` runs DuckDB's native FTS extension over the `prose` column.
4. **RRF Fusion**: `_rrf_fuse()` combines both legs using `k=60`. Fragments ranking highly in *both* semantic and lexical matches surface first.
5. **Hydration & Tag Filtering**: Fused IDs are intersected with active `ActiveFragment` records from LadybugDB. Optional `domain_tags` are applied as a hard filter.
6. **Structural Diversity**: `diversity_select()` greedily picks fragments to guarantee a mix of `setup`, `execution`, and `verification` types.

### C. System Skill Filtering (Rule-Based)
- `applicability.py` runs pure predicate logic against `ActiveSkill` records:
  - `always_apply=True` → Always included.
  - `phase_scope` / `category_scope` → Matched against request context.
  - No LLM parsing occurs; governance rules are strictly deterministic.

### D. Context Assembly & Response
- Fragments are grouped by `skill_id`, wrapped in markdown headers, and joined into a single string.
- Telemetry is recorded to DuckDB.
- `ComposedResult` is returned with the raw context, provenance metadata, and `recommended_max_tokens` hints.

## 3. The LLM-First Extraction Risk
Your concern regarding **LLM-first prompt breakdown** is well-founded. Introducing an LLM to parse intents, extract keywords, or categorize sub-tasks before retrieval would introduce:
- **Provider Variance**: Different models (or even temperature settings) would extract inconsistent slots, causing unpredictable skill retrieval.
- **Latency Spikes**: An additional ~200-500ms inference step on every `/compose` request.
- **Hallucination Drift**: LLMs may invent tags or phases not present in the corpus, breaking RRF scoring and applicability filters.
- **Cost Overhead**: Significant token consumption purely for retrieval routing.

The current architecture wisely avoids this by relying on **stable embedding models + exact lexical matching + deterministic fusion**. This ensures reproducible results regardless of the downstream generative LLM used.

## 4. Proposed Deterministic Improvements
To enhance precision and stability *without* introducing LLM variance, consider these targeted improvements:

### A. Rule-Based Keyword Extraction (BM25 Boosting)
Instead of an LLM, use lightweight regex/NLP to extract high-signal technical terms (languages, frameworks, file extensions, phase keywords) and inject them as explicit BM25 query modifiers.
- **File**: `retrieval/domain.py`
- **Impact**: Increases lexical recall for niche jargon without semantic drift.

### B. RRF Leg Weighting & Parameter Tuning
The current RRF uses a symmetric `k=60`. Introduce configurable weights (`dense_weight`, `bm25_weight`) or phase-specific `k` values to bias toward semantic or lexical matches depending on corpus characteristics.
- **File**: `retrieval/domain.py`
- **Impact**: Allows fine-tuning retrieval behavior per phase (e.g., `qa` phases may benefit from higher BM25 weighting for exact error codes).

### C. Embedding Query Caching
Hash the `Instruct:...\nQuery:` string and cache the resulting vector. Repeated or similar prompts avoid redundant embedding API calls.
- **File**: `retrieval/domain.py` or `lm_client.py`
- **Impact**: Reduces latency and API costs for recurring task patterns.

### D. Post-Retrieval Semantic Lint
Add a lightweight validation step that cross-references retrieved fragments against requested `domain_tags` using a fixed embedding similarity threshold, ensuring strict tag adherence before assembly.
- **File**: `orchestration/compose.py`
- **Impact**: Prevents off-topic fragments from slipping through RRF noise.

## 5. Next Steps for Dev Repo Implementation
When you open the Aider session in your `dev` repository, we will:
1. Identify the exact files to modify (`retrieval/domain.py`, `applicability.py`, `orchestration/compose.py`).
2. Implement the chosen improvements using type-safe, deterministic Python.
3. Add unit tests in `tests/` to verify RRF scoring, diversity selection, and applicability filtering.
4. Ensure backward compatibility with existing `ComposeRequest` shapes and telemetry schemas.

**Recommended First PR**: Implement Rule-Based Keyword Extraction + RRF Weighting. This provides immediate precision gains with zero LLM dependency.

Let me know which improvement you'd like to prioritize, and I'll generate the exact code patches for your dev session.
