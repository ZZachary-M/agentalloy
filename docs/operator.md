# Skillsmith v1 — Operator Guide

## Configuration

All settings are read from environment variables (or `.env` file at the project root). Copy a platform preset to `.env`:

```bash
cp .env.cpu .env          # Universal CPU+RAM (any machine)
cp .env.apple-silicon .env # Apple Silicon (Metal)
cp .env.nvidia .env        # NVIDIA GPU (CUDA)
cp .env.radeon .env        # AMD Radeon dGPU or iGPU (LM Studio Vulkan)
```

Or copy `.env.example` and fill in manually. Full reference:

| Variable | Default | Description |
|---|---|---|
| `LADYBUG_DB_PATH` | `./data/ladybug` | LadybugDB (KuzuDB) directory |
| `DUCKDB_PATH` | `./data/skills.duck` | DuckDB vector + telemetry store |
| `LOG_LEVEL` | `INFO` | Python log level |
| `RUNTIME_EMBED_BASE_URL` | `http://localhost:11434` | OpenAI-compatible embedding endpoint |
| `RUNTIME_EMBEDDING_MODEL` | `qwen3-embedding:0.6b` | Embedding model (1024-dim) |
| `AUTHORING_MODEL` | `hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:UD-IQ4_NL_XL` | Author model — MoE, fast for drafting |
| `CRITIC_MODEL` | `hf.co/unsloth/Qwen3.6-27B-GGUF:UD-Q5_K_XL` | Critic model — dense Q5, steadier for grading |
| `AUTHORING_LM_BASE_URL` | (`= LM_STUDIO_BASE_URL`) | Author endpoint; equal to critic endpoint for swap-batched single-GPU use |
| `AUTHORING_EMBEDDING_MODEL` | `qwen3-embedding:0.6b` | Authoring embedding model (authoring only) |
| `DEDUP_HARD_THRESHOLD` | `0.92` | Cosine threshold for hard dedup |
| `DEDUP_SOFT_THRESHOLD` | `0.80` | Cosine threshold for soft dedup |
| `BOUNCE_BUDGET` | `5` | Max authoring bounce attempts |

---

## Starting the Service

```bash
# Install dependencies
uv sync

# Start the server (development)
uv run uvicorn skillsmith.app:app --reload --host 0.0.0.0 --port 47950

# Or use the module entry point
uv run python -m skillsmith
```

The service starts in degraded mode if the runtime cache fails to load (e.g. empty store). The health endpoint will report `runtime_store: unavailable` until the store is seeded and the service restarted.

### Single-writer corpus lock

KuzuDB enforces a single-writer lock on the corpus directory. While a server is running it holds that lock; a second process trying to write (e.g. `install-pack` or `seed-corpus` from another shell) will fail. The CLI provides background-mode lifecycle subcommands so you can release the lock without `kill <pid>`:

```bash
python -m skillsmith.install server-status              # port, pid, reachable
python -m skillsmith.install server-start [--port N]    # detached uvicorn, logs to ~/.local/share/skillsmith/server.log
python -m skillsmith.install server-stop [--timeout 10] # SIGTERM, escalates to SIGKILL
python -m skillsmith.install server-restart
```

`serve` (foreground, blocking) is unchanged for the typical "run it in a terminal and leave it" workflow. Reach for `server-*` when you need to ingest from a second shell or script the lifecycle.

`server-stop` SIGTERMs whatever process is bound to the configured port; it does not verify the target is skillsmith. On a shared port, that's the operator's concern. `server-start` and `serve` use the same `.env` loader, so background and foreground modes produce identical runtime configurations.

`server-stop` exits 0 with `action: "already_stopped"` when nothing is listening on the configured port — running it twice in a row is safe and idempotent.

---

## Skill Category Vocabulary

*(Refined based on implementation discovery — the spec originally conflated SDD phases with content categories.)*

**Domain skill categories** (used in `python -m skillsmith.ingest`):

| Category | Intended content |
|---|---|
| `engineering` | Software design, implementation, testing, code quality |
| `ops` | Deployment, infrastructure, CI/CD, automation |
| `review` | Code review, QA processes, audit workflows |
| `design` | Architecture, API design, system design |
| `tooling` | Developer tools, agents, authoring utilities |
| `quality` | Testing strategy, quality gates, reliability |

**System skill categories** (used in `python -m skillsmith.bootstrap`):

| Category | Intended content |
|---|---|
| `governance` | Rules that apply globally across all work |
| `tooling` | Tool-skills invoked directly by operators (e.g. authoring agents) |
| `safety` | Security, data handling, access rules |
| `quality` | Quality standards, review criteria |
| `observability` | Logging, tracing, alerting standards |
| `operational` | Operational procedures (legacy; prefer `tooling` for agent skills) |

**System skill storage invariant:** Every system skill loads as exactly one Fragment of `fragment_type=guardrail` containing the full prose. This is structurally equivalent to atomic storage but unifies the retrieval path. Do not author system skills with multiple fragments.

**Tool-skill applicability pattern:** System skills with `always_apply: false` and empty `phase_scope`/`category_scope` are stored in LadybugDB for governance but never surfaced in automatic compositions. Use this pattern for operator-invoked tools (e.g. the Skill Authoring Agent) that should not appear in POST /compose responses.

---

## Seeding Fixture Data

Load the bundled skill fixtures into LadybugDB:

```bash
uv run python -m skillsmith.fixtures
```

**Restart the service after seeding** — the runtime cache is loaded once at startup. New data is not visible until restart.

---

## Available Endpoints

### Health

```
GET /health
```

Reports overall service status and per-dependency readiness.

```bash
curl http://localhost:47950/health
```

```json
{
  "status": "healthy",
  "dependencies": {
    "runtime_store": {"status": "ok"},
    "telemetry_store": {"status": "ok"},
    "embedding_runtime": {"status": "ok"},
    "assembly_runtime": {"status": "ok"}
  }
}
```

Possible `status` values: `healthy` | `degraded` | `unavailable`.

---

### Diagnostics

```
GET /diagnostics/runtime
```

Shows whether the in-memory cache is consistent with the store, and per-path readiness.

```bash
curl http://localhost:47950/diagnostics/runtime | python3 -m json.tool
```

Key fields:
- `cache_loaded` — `true` if startup cache load succeeded
- `consistency.consistent` — `true` if store and cache agree on all active versions
- `consistency.version_mismatches` — skills where store and cache disagree (stale cache)
- `dependency_readiness.per_path` — which paths (`compose`, `retrieve`, `inspect`, `telemetry`) are ready

---

### Compose

```
POST /compose
```

Assembles skill guidance for a task. Returns composed text with governance prepended.

```bash
curl -s -X POST http://localhost:47950/compose \
  -H "Content-Type: application/json" \
  -d '{
    "task": "Design a Python FastAPI endpoint that validates a JSON request body",
    "phase": "design",
    "k": 5
  }'
```

Request fields:
- `task` (required) — description of the work being done
- `phase` (required) — `"design"` | `"build"` | `"review"`
- `k` (optional, default 5) — max domain skill candidates
- `domain_tags` (optional) — filter by tags, e.g. `["python", "http"]`

Response when fragments matched: `result_type: "composed"` with `output`, `source_skills`, `domain_fragments`, `system_fragments`, `latency_ms`.

Response when no fragments matched: `result_type: "empty"` — no assembly attempted.

Response on dependency failure: HTTP 503 with `stage` (`retrieval` or `assembly`), `code`, and `message`.

---

### Direct Retrieve

```
GET  /retrieve/{skill_id}    — retrieve by known skill ID
POST /retrieve               — semantic query without assembly
```

```bash
# By ID
curl http://localhost:47950/retrieve/py-fastapi-endpoint-design

# Semantic query
curl -s -X POST http://localhost:47950/retrieve \
  -H "Content-Type: application/json" \
  -d '{"task": "fastapi endpoint with validation", "phase": "design", "k": 3}'
```

---

### Skill Inspection

```
GET /skills/{skill_id}
```

Returns full skill detail: identity, active version metadata, raw prose, and fragment list.

```bash
curl http://localhost:47950/skills/py-fastapi-endpoint-design | python3 -m json.tool
```

---

## Querying Traces

All compose and retrieve requests write a row to `composition_traces` in the SQLite telemetry store. Query directly with sqlite3 or any SQLite client:

```bash
sqlite3 ./data/telemetry.db
```

### Most recent traces

```sql
SELECT composition_id, result_type, phase, latency_total_ms, timestamp
FROM composition_traces
ORDER BY timestamp DESC
LIMIT 10;
```

### Inspect a compose trace

```sql
SELECT
  composition_id,
  result_type,
  task_prompt,
  json(source_skill_ids)   AS skills,
  json(domain_fragment_ids) AS domain_frags,
  json(system_fragment_ids) AS system_frags,
  assembly_tier,
  latency_retrieval_ms,
  latency_assembly_ms,
  latency_total_ms,
  input_tokens,
  output_tokens
FROM composition_traces
WHERE result_type = 'compose'
ORDER BY timestamp DESC
LIMIT 5;
```

### Find errors

```sql
SELECT composition_id, result_type, error_payload, timestamp
FROM composition_traces
WHERE error_payload IS NOT NULL
ORDER BY timestamp DESC;
```

### Trace schema

| Column | Type | Description |
|---|---|---|
| `composition_id` | TEXT (PK) | UUID per request |
| `timestamp` | DATETIME | UTC |
| `result_type` | TEXT | `compose`, `compose_empty`, `retrieve_by_id`, `retrieve_query` |
| `task_prompt` | TEXT | Submitted task text |
| `phase` | TEXT | `design`, `build`, `review` (null for retrieve-by-id) |
| `assembly_tier` | INT | `2` for v1 standard assembly; null for retrieve-only |
| `domain_fragment_ids` | TEXT (JSON) | Array of fragment IDs used |
| `system_fragment_ids` | TEXT (JSON) | Array of system fragment IDs included |
| `source_skill_ids` | TEXT (JSON) | Deduplicated skill IDs contributing fragments |
| `latency_retrieval_ms` | INT | Retrieval stage duration |
| `latency_assembly_ms` | INT | Assembly stage duration (null for retrieve) |
| `latency_total_ms` | INT | End-to-end duration |
| `input_tokens` | INT | Tokens sent to assembly model |
| `output_tokens` | INT | Tokens returned from assembly model |
| `error_payload` | TEXT | JSON error detail if the request failed |

---

## Debugging Composition Problems

### Service reports degraded or unavailable

1. Check `GET /health` — identify which dependency is down
2. Check `GET /diagnostics/runtime` — verify cache loaded and consistent
3. Check Ollama: `curl $OLLAMA_BASE_URL/api/tags` — confirm models are pulled
4. Check LadybugDB: if `runtime_store: unavailable`, the store may be corrupt or missing migrations

### Compose returns empty result

- The task description matched no active domain fragments
- Verify skills are seeded: `GET /skills/<known-skill-id>` should return 200
- Check `diagnostics/runtime` — `cache_loaded` must be `true`
- Try broader task wording or remove `domain_tags` filter
- Inspect eligible fragments via `POST /retrieve` with the same task

### Stale cache after reseed

The cache is loaded once at startup. After reseeding the store:

1. Restart the service
2. Check `GET /diagnostics/runtime` — `consistency.consistent` should be `true`
3. If `version_mismatches` are present, the wrong service instance may still be running

### Tracing a specific compose request

1. Note `composition_id` from the compose response (not currently surfaced in the HTTP response body — query the DB)
2. Query: `SELECT * FROM composition_traces WHERE timestamp > datetime('now', '-5 minutes')`
3. Verify `source_skill_ids`, `domain_fragment_ids`, `system_fragment_ids` match expected skills
4. Check `latency_retrieval_ms` vs `latency_assembly_ms` to identify which stage is slow

---

## Authoring Pipeline

Separate from the runtime `/compose` service. Populates the skill corpus from real-world `SKILL.md` files via an LLM-driven author → QA gate → ingest flow.

### Stages

```
SKILL.md (e.g. skill-source/agent-skills/skills/*/SKILL.md)
    ↓  Author LLM (guided by sys-skill-authoring-agent)
pending-qa/<skill_id>.yaml
    ↓  QA gate
    │    1. deterministic: schema + vocab + skill_id collision (reuses ingest validators)
    │    2. dedup: embed fragments, cosine vs active corpus, 0.80/0.92 thresholds
    │    3. critic LLM (guided by sys-skill-qa-agent), JSON verdict
    ↓
pending-review/  OR  pending-revision/  OR  rejected/  OR  needs-human/
    ↓  if revise: driver.revise_one re-authors with critic feedback, back to pending-qa
    (up to 3 bounces, then escalation to needs-human)
    ↓  operator review of .qa.md reports in pending-review/
python -m skillsmith.ingest skill-source/pending-review/
```

### Bootstrapping the agent fixtures

Both the Author and Critic live as system skills in LadybugDB. Bootstrap them once:

```bash
uv run python -m skillsmith.bootstrap fixtures/skill-authoring-agent.md --yes
uv run python -m skillsmith.bootstrap fixtures/skill-qa-agent.md --yes
```

Both use the tool-skill applicability pattern (`always_apply: false` + empty scopes), so they won't appear in `/compose` responses — they're operator-invoked.

### CLI commands

```bash
# Per-skill loop (default; author → QA ↔ revise converges per file)
uv run python -m skillsmith.authoring run skill-source/agent-skills/skills

# Stage-batched (legacy; author-all → QA-all → revise-all, small batches only)
uv run python -m skillsmith.authoring run-batched skill-source/agent-skills/skills

# Granular stage control (manual pipeline ops)
uv run python -m skillsmith.authoring author <source-dir>   # SKILL.md → pending-qa
uv run python -m skillsmith.authoring qa                    # pending-qa → routed
uv run python -m skillsmith.authoring revise                # pending-revision → pending-qa
uv run python -m skillsmith.authoring summary               # counts per bucket
```

### Configuration (authoring-specific)

Separate from the runtime retrieval settings above. Author and Critic share a single OpenAI-compatible endpoint (Ollama or LM Studio). On a single-GPU host the swap-batched `run` keeps both models from needing to coexist by warming the right one before each phase.

| Variable | Default | Notes |
|---|---|---|
| `AUTHORING_MODEL` | `hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:UD-IQ4_NL_XL` | MoE, 3B active — non-reasoning via `/no_think` |
| `CRITIC_MODEL` | `hf.co/unsloth/Qwen3.6-27B-GGUF:UD-Q5_K_XL` | Dense Q5 — thinking ON for rubric grading |
| `AUTHORING_EMBEDDING_MODEL` | `qwen3-embedding:0.6b` | |
| `DEDUP_HARD_THRESHOLD` | `0.92` | Cosine similarity; matches ≥ this → auto-reject |
| `DEDUP_SOFT_THRESHOLD` | `0.80` | Matches in [soft, hard) → Critic review |
| `BOUNCE_BUDGET` | `5` | Revise passes before needs-human escalation |

### Pipeline state layout

All staging lives under `skill-source/`:

```
skill-source/
    pending-qa/            # author drafts awaiting QA
    pending-review/        # QA-approved; ready for ingest
    pending-revision/      # QA asked for revision (bounce count in .qa-state.json)
    rejected/              # QA hard-rejected (dup, content fabrication, etc.)
    needs-human/           # budget exhausted or critic unparseable
    .qa-state.json         # {skill_id: bounce_count}
```

Each `.yaml` in the terminal dirs has a sibling `<skill_id>.qa.md` with the Critic's human-readable verdict.

---

## v1.5 Migration Preview

Forthcoming architecture change (v5.3 directive). In-flight across the `Compostable Skill API v1.5` Linear project — many of the pieces are already shipped as green-field prework, but the cutover requires coordinated changes.

### What changes

| Concern | v1.0 (current) | v1.5 |
|---|---|---|
| Fragment embeddings | `Fragment.embedding` column in LadybugDB | DuckDB `fragment_embeddings` table at `skills.duck` |
| Composition telemetry | SQLite `data/telemetry.db` | DuckDB `composition_traces` table (same `skills.duck` file) |
| Vector search | Kùzu VECTOR extension + HNSW index | DuckDB `array_cosine_distance` (FLOAT[1024] linear scan, <10ms at current scale) |
| Inference | Ollama (`OllamaClient`) | Ollama OpenAI-compatible endpoint |

### What does NOT change

- v1 API surface — endpoints, request/response shapes, auth posture
- LadybugDB as the graph engine (Skill, SkillVersion, Fragment nodes + all edges)
- sys-skill-authoring and sys-skill-qa fixtures (prose unchanged)
- Review YAML schema; ingest CLI shape

### New configuration (v1.5)

| Variable | Default | Description |
|---|---|---|
| `DUCKDB_PATH` | `./data/skills.duck` | Single DuckDB file for both `fragment_embeddings` and `composition_traces` |

### New CLIs (v1.5)

```bash
# Populate DuckDB from LadybugDB Fragment nodes.
# Idempotent — skips fragments that already have a DuckDB row.
uv run python -m skillsmith.reembed
uv run python -m skillsmith.reembed --dry-run                # report without embedding
uv run python -m skillsmith.reembed --skill-id <id>          # scope to one skill
uv run python -m skillsmith.reembed --skill-id <id> --force  # wipe + re-embed
```

### Migration-day procedure (once all NXS-* tickets land)

1. **Stop the Skill API service** (in-memory caches would otherwise drift).
2. **Back up existing stores**: `cp -r data/ladybug data/ladybug.bak && cp data/telemetry.db data/telemetry.db.bak`.
3. **Pull the v1.5 release** (all NXS-794..802 merged).
4. **Install the new dep**: `uv sync` (adds `duckdb`).
5. **Verify Ollama is up** with `qwen3-embedding:0.6b` loaded: `curl http://localhost:11434/v1/models`.
6. **Populate DuckDB from existing Fragment nodes**: `uv run python -m skillsmith.reembed`. Dry-run first if anxious (`--dry-run`).
7. **Run the integration harness**: `uv run pytest tests/test_v1_5_integration.py -v`. All non-skipped tests should pass.
8. **Restart the service**. `GET /health` should report `healthy` across all dependencies.
9. **Smoke-test** `/compose` with a known task. Confirm a row lands in DuckDB `composition_traces`.
10. **After a soak period**: delete `data/telemetry.db` (no longer written). `data/ladybug.bak` can go too once you're confident.

### Verifying post-migration state

```bash
# DuckDB should have one row per Fragment
duckdb data/skills.duck -c "SELECT count(*) FROM fragment_embeddings;"

# composition_traces writes land here, not SQLite
duckdb data/skills.duck -c "SELECT count(*), min(request_ts), max(request_ts) FROM composition_traces;"

# Embedding dimensionality should be 1024 (qwen3-embedding:0.6b)
duckdb data/skills.duck -c "SELECT array_length(embedding) FROM fragment_embeddings LIMIT 1;"
```
