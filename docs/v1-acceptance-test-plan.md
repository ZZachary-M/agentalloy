# Skillsmith v1 — Acceptance Test Plan

## Overview

This plan defines the representative scenario, pass criteria, and verification steps for Skill API v1. A live Ollama instance with `qwen3-embedding:0.6b` (embedding) is required to run the golden path.

---

## Prerequisites

| Requirement | Check |
|---|---|
| Service running (`uvicorn skillsmith.app:app`) | `GET /health` returns `"status": "healthy"` |
| Ollama reachable at `OLLAMA_BASE_URL` | `GET /health` shows `embedding_runtime: ok` |
| LadybugDB seeded with fixtures | `python -m skillsmith.fixtures` completes without error |
| Service restarted after seeding | Cache loaded — `/health` shows `runtime_store: ok` |

---

## Scenario: Python FastAPI endpoint design task

**Task prompt:** `"Design a Python FastAPI endpoint that validates a JSON request body and returns a structured error response"`  
**Phase:** `design`

This task is expected to:
- Retrieve fragments from **at least two distinct domain skills** (e.g. `py-fastapi-endpoint-design`, `http-error-contract-design`)
- Include **all applicable system skills** automatically (at minimum `sys-governance-always` with `always_apply: true`)

---

## Acceptance Criteria and Verification Steps

### AC-1 — Compose returns assembled guidance from ≥2 source skills

**Endpoint:** `POST /compose`

```json
{
  "task": "Design a Python FastAPI endpoint that validates a JSON request body and returns a structured error response",
  "phase": "design"
}
```

**Pass criteria:**
- HTTP 200
- `result_type` is `"composed"` (not `"empty"`)
- `source_skills` contains at least 2 distinct skill IDs
- `output` is non-empty text

**Verification:**
```bash
curl -s -X POST http://localhost:47950/compose \
  -H "Content-Type: application/json" \
  -d '{"task": "Design a Python FastAPI endpoint that validates a JSON request body and returns a structured error response", "phase": "design"}' \
  | python3 -c "import json,sys; r=json.load(sys.stdin); print('source_skills:', r.get('source_skills')); assert len(r.get('source_skills',[])) >= 2"
```

---

### AC-2 — Applicable system skills included automatically

Using the compose response from AC-1:

**Pass criteria:**
- `system_skills_applied` is `true`
- `system_fragments` is non-empty
- The `output` or assembled content reflects governance framing (Governance section before Guidance)

**Verification:**
```bash
# Check system_skills_applied and system_fragments in the compose response
curl -s -X POST http://localhost:47950/compose \
  -H "Content-Type: application/json" \
  -d '{"task": "Design a Python FastAPI endpoint that validates a JSON request body and returns a structured error response", "phase": "design"}' \
  | python3 -c "import json,sys; r=json.load(sys.stdin); print('system_skills_applied:', r.get('system_skills_applied')); print('system_fragments:', r.get('system_fragments')); assert r.get('system_skills_applied') is True"
```

---

### AC-3 — Direct retrieve by ID returns active skill content

**Endpoint:** `GET /retrieve/{skill_id}`

```bash
curl -s http://localhost:47950/retrieve/py-fastapi-endpoint-design \
  | python3 -c "import json,sys; r=json.load(sys.stdin); print('version_id:', r['active_version']['version_id']); assert r['skill_id'] == 'py-fastapi-endpoint-design'"
```

**Pass criteria:**
- HTTP 200
- `skill_id` matches the request
- `active_version.version_id` is present
- `raw_prose` is non-empty

---

### AC-4 — Semantic retrieve returns ranked skill matches

**Endpoint:** `POST /retrieve`

```bash
curl -s -X POST http://localhost:47950/retrieve \
  -H "Content-Type: application/json" \
  -d '{"task": "fastapi endpoint with error handling", "phase": "design", "k": 3}' \
  | python3 -c "import json,sys; r=json.load(sys.stdin); print('hits:', [h['skill_id'] for h in r['results']]); assert len(r['results']) > 0"
```

**Pass criteria:**
- HTTP 200
- `results` is non-empty
- Each hit has `skill_id`, `version_id`, `score`, `raw_prose`

---

### AC-5 — Read-skill inspection returns full skill detail

**Endpoint:** `GET /skills/{skill_id}`

```bash
curl -s http://localhost:47950/skills/py-fastapi-endpoint-design \
  | python3 -c "import json,sys; r=json.load(sys.stdin); print('fragments:', len(r.get('fragments', []))); assert r['skill_class'] == 'domain'"
```

**Pass criteria:**
- HTTP 200
- `skill_id`, `canonical_name`, `category`, `skill_class` present
- `active_version` has `version_id`, `version_number`, `raw_prose`
- `fragments` is non-empty list

---

### AC-6 — Health endpoint reports all dependencies

**Endpoint:** `GET /health`

```bash
curl -s http://localhost:47950/health \
  | python3 -c "import json,sys; r=json.load(sys.stdin); print(json.dumps(r, indent=2)); assert r['status'] == 'healthy'"
```

**Pass criteria:**
- HTTP 200
- `status` is `"healthy"`
- `dependencies.runtime_store`, `embedding_runtime`, `assembly_runtime`, `telemetry_store` all `"ok"`

---

### AC-7 — Active-version selection: compose uses active version only

**Setup:** Seed a second version of `py-fastapi-endpoint-design` with status `draft` (not active). Restart the service.

**Verification:** The compose response `source_skills` should reference only the active version ID, not the draft version ID. Check via:

```bash
curl -s http://localhost:47950/diagnostics/runtime \
  | python3 -c "import json,sys; r=json.load(sys.stdin); print('consistent:', r['consistency']['consistent']); print('cache_loaded:', r['cache_loaded'])"
```

**Pass criteria:**
- `cache_loaded` is `true`
- `consistency.consistent` is `true` (store and cache agree on active versions)

---

### AC-8 — Composition trace written and queryable

After running the compose request from AC-1, inspect the SQLite telemetry store:

```bash
python3 -c "
import sqlite3, json
conn = sqlite3.connect('./data/telemetry.db')
rows = conn.execute('SELECT composition_id, result_type, task_prompt, source_skill_ids, assembly_tier, latency_total_ms FROM composition_traces ORDER BY timestamp DESC LIMIT 3').fetchall()
for r in rows:
    print(dict(zip(['id','type','task','skills','tier','ms'], r)))
"
```

**Pass criteria:**
- At least one row with `result_type = 'compose'`
- `task_prompt` matches the submitted task text
- `source_skill_ids` is a JSON array with ≥2 skill IDs
- `assembly_tier` is `2`
- `latency_total_ms` is a positive integer

---

## Definition of Ready

The v1 acceptance bar is met when **all 8 criteria pass** in a single end-to-end run against a live service with seeded fixture data. Any failure blocks release.

## Known Skip Conditions

- Ollama not reachable: AC-1, AC-2, AC-4, AC-8 (assembly) require live Ollama. AC-3, AC-5, AC-6, AC-7 can be verified without it.
- Empty fixture store: all ACs fail. Seed first.
