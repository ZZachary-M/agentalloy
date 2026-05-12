# Plan: Two-Model Pipeline — Linear Issue → Compose → Execute

## Context

The sdd-build workflow needs a local, fully-offline execution pipeline. When the user approves
the build phase, the pipeline should:
1. Read the Linear issue via Linear API
2. Send it to the **reasoning model** (llama-server :11434 via Manifest) to extract a structured
   `ComposeRequest` (task, phase, domain_tags)
3. POST to `skillsmith /compose` — which embeds via the **third llama-server** (embedding model)
   and returns assembled skill fragments
4. Send fragments + task to the **coder model** (llama-server :11435 via Manifest) to execute

Manifest acts as a single HTTP entry-point routing to the two chat model backends by model ID
(or custom header — `OpenAICompatClient` will be extended to support either).

---

## Architecture

```
sdd-build skill (Claude Code)
    │
    └─ $ skillsmith run-issue --issue LIN-123
               │
               ├─ A. reasoning_lm.chat(model=REASONING_MODEL, …) → {task, phase, domain_tags}
               │      Manifest :MANIFEST_PORT → llama-server :11434
               │
               ├─ B. POST skillsmith:47950/compose {task, phase, domain_tags}
               │      embed_lm.embed(model=EMBEDDING_MODEL, …)
               │      Third llama-server :EMBED_PORT → DuckDB vector + BM25 + RRF
               │      ← ComposedResult.output (assembled fragment text)
               │
               └─ C. coder_lm.chat(model=CODER_MODEL, system=fragments, user=task)
                      Manifest :MANIFEST_PORT → llama-server :11435
```

---

## Files to Modify

### 1. `src/skillsmith/config.py`
Add to `Settings`:
```python
# Two-model pipeline (reasoning → compose → coder)
manifest_base_url: str = "http://localhost:11436"   # Manifest proxy
reasoning_model: str = "reasoning"                  # model ID Manifest routes to :11434
coder_model: str = "coder"                          # model ID Manifest routes to :11435
linear_api_key: str | None = None                   # SKILLSMITH_LINEAR_API_KEY
skillsmith_base_url: str = "http://localhost:47950"  # self-reference for pipeline calls
```
`runtime_embed_base_url` already exists — user sets it to the third llama-server port.

### 2. `src/skillsmith/lm_client.py`
Add `extra_headers: dict[str, str] | None = None` to `OpenAICompatClient.__init__`. Merge into
the httpx Client headers dict (alongside the existing `Authorization` header). This lets Manifest
header-key routing work without changing call sites.

### 3. `src/skillsmith/pipeline/` (new package)
- `__init__.py` — empty
- `run_issue.py` — pipeline logic:

  **`fetch_linear_issue(issue_id, api_key) -> dict`**
  GraphQL POST to `https://api.linear.app/graphql`. Returns `{title, description, identifier}`.

  **`extract_compose_request(lm, model, issue_text) -> dict`**
  Single `lm.chat()` call to the reasoning model with a structured-output prompt.
  Returns `{"task": str, "phase": Phase, "domain_tags": list[str] | None}`.
  Uses `response_format={"type": "json_object"}`.

  **`call_compose(skillsmith_url, task, phase, domain_tags, k) -> str`**
  `httpx.post(f"{skillsmith_url}/compose/text", …)` — uses the `/compose/text` plain-text
  endpoint (already exists at `compose_router.py:44`) to get fragments without JSON parsing.

  **`run_issue_pipeline(issue_id, settings) -> str`**
  Orchestrates A→B→C, streams coder output to stdout, returns final content string.

### 4. `src/skillsmith/install/subcommands/run_issue.py` (new)
CLI subcommand wiring:
```
skillsmith run-issue --issue LIN-123 [--phase build] [--k 4] [--stream]
```
Loads `get_settings()`, calls `run_issue_pipeline()`, prints output.

### 5. `src/skillsmith/__main__.py`
Register the `run-issue` subcommand alongside existing subcommands.

---

## Reasoning Prompt (extract_compose_request)

```
System: You are a software engineering task classifier. Given a Linear issue, extract:
  - task: one-sentence action description for the engineer
  - phase: one of spec|design|build|qa|ops|meta|governance
  - domain_tags: 0-3 short technology/domain labels (e.g. ["fastapi", "postgres"])

Respond with valid JSON only: {"task": "...", "phase": "...", "domain_tags": [...]}

User: {issue_text}
```

---

## Config env vars (user sets in environment or `.env`)

| Env var | Purpose |
|---|---|
| `SKILLSMITH_MANIFEST_BASE_URL` | Manifest single entry-point URL |
| `SKILLSMITH_REASONING_MODEL` | model ID → routes to :11434 |
| `SKILLSMITH_CODER_MODEL` | model ID → routes to :11435 |
| `SKILLSMITH_LINEAR_API_KEY` | Linear personal API token |
| `SKILLSMITH_RUNTIME_EMBED_BASE_URL` | Third llama-server (embedding) |
| `SKILLSMITH_BASE_URL` | Where the skillsmith service is running |

---

## Skill Updates Required

### sdd-design workflow skill
The reasoning model must compute the skillsmith compose prompt during design and write it into the
Linear issue coding contract as a `skillsmith_compose` block:
```yaml
skillsmith_compose:
  task: "..."
  phase: build
  domain_tags: [...]
```
This eliminates the classification step entirely during build — the coder never has to reason
about what to ask skillsmith.

`run_issue.py` should check for this block first and skip `extract_compose_request()` when present.

### sdd-build workflow skill
The sdd-build skill is strictly codified (not fragmented). Add an explicit **Step 0** before any
implementation steps:
1. Read the `skillsmith_compose` block from the Linear contract
2. POST `{task, phase, domain_tags}` to skillsmith `/compose/text`
3. Treat the returned fragment text as active guidance for all subsequent steps

Without this step the coder model executes the contract with no skill context injected.

---

## Verification

1. **Unit tests**: Add `tests/test_pipeline_run_issue.py` — mock `lm.chat`, `lm.embed`, and the
   `/compose` HTTP call; assert the three stages are called in order with correct payloads.
2. **Integration smoke test**:
   ```bash
   skillsmith run-issue --issue LIN-123
   ```
   Observe:
   - Reasoning model call logged with extracted task/phase
   - `/compose` response logged with fragment count
   - Coder model output printed to stdout
3. **Config validation**: `skillsmith doctor` (or `skillsmith preflight`) should surface missing
   `SKILLSMITH_LINEAR_API_KEY` or unreachable Manifest URL as a structured warning.
