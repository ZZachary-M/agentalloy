<p align="center">
  <img src="docs/Skithsmith_cover.png" alt="Skillsmith — Runtime Skill Composition Service" width="720" />
</p>

<p align="center">
  <b>Skills your coding agent doesn't have to memorize.</b>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/github/license/nrmeyers/skillsmith?color=blue" alt="license" /></a>
  &nbsp;
  <img src="https://img.shields.io/badge/python-3.12+-blue.svg" alt="python 3.12+" />
  &nbsp;
  <a href="https://github.com/astral-sh/uv"><img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json" alt="uv" /></a>
  &nbsp;
  <img src="https://img.shields.io/badge/runtime-no--LLM-success" alt="no LLM in runtime" />
  &nbsp;
  <img src="https://img.shields.io/badge/packs-37-orange" alt="37 packs" />
  &nbsp;
  <img src="https://img.shields.io/badge/skills-324-orange" alt="324 declared skills" />
</p>

`skillsmith` is a FastAPI gateway and CLI that serves a curated corpus of engineering skills — testing, error handling, deployment, observability, security, framework patterns — composed dynamically per task and handed to your coding agent over HTTP. The runtime is a hybrid BM25 + dense retriever over [LadybugDB](https://docs.ladybugdb.com/) (an embedded [kuzu](https://kuzudb.com/) fork — no Docker) and DuckDB. **No generative LLM in the hot path** — your agent owns generation, skillsmith owns retrieval.

Use it standalone from your shell, or wire it into your coding harness — the same `/compose` endpoint drives both.

Things your agent can ask for instead of you pasting them into the prompt:

- "How do I write a failing pytest before the implementation?" — TDD + framework idioms, composed from `pytest` + `testing` packs.
- "What's the safe way to add a NOT NULL column to a 50M-row table?" — migration safety, composed from `redis` + `engineering` packs.
- "Wire OpenTelemetry into this FastAPI app." — observability + framework patterns, composed from `fastapi` + `analytics` packs.
- "I'm reviewing this PR — what should I check?" — review heuristics, composed phase-aware from `code-review` packs.

---

## Contents

- [Quickstart](#quickstart)
- [Demo](#demo)
- [Why not just paste skills into CLAUDE.md](#why-not-just-paste-skills-into-claudemd)
- [Two ways to use it](#two-ways-to-use-it)
- [Standalone CLI](#standalone-cli)
- [REST API](#rest-api)
- [Hardware presets](#hardware-presets)
- [Packs shipping in-tree](#packs-shipping-in-tree)
- [How packs get authored](#how-packs-get-authored)
- [Architecture](#architecture)
- [Telemetry](#telemetry)
- [Configuration](#configuration)
- [Development](#development)
- [Empirical results](#empirical-results)
- [License](#license)

---

## Quickstart

```bash
uv tool install --editable .
skillsmith setup                                # one-time interactive install wizard
skillsmith install-packs --packs all            # or: --packs core,engineering,python
skillsmith server-start                         # background daemon on :47950
cd ~/your-project && skillsmith wire            # wire harness in this repo
```

The setup wizard detects your hardware, pulls the embedding model, seeds the corpus, and writes your config. **3–5 minutes** on a warm machine.

`install-packs --packs` accepts `all` or a comma-separated list. Unknown names fail fast in non-interactive mode; pass `--ignore-unknown` to skip them. List available packs with `skillsmith install-packs --list`.

**Agent-driven install.** If you'd rather have your coding harness (Claude Code, Cursor, Windsurf, Continue.dev, Aider, Cline, GitHub Copilot, Gemini CLI, Hermes Agent, OpenCode) drive the install for you, clone the repo and tell it:

```bash
git clone https://github.com/nrmeyers/skillsmith.git && cd skillsmith
# then in your coding harness:
> Install this tool by following INSTALL.md
```

**Container alternative** (no Python required):

```bash
podman compose up -d        # or: docker compose up -d
curl http://localhost:47950/health
```

Brings up `skillsmith` on port 47950 (pre-seeded corpus baked in) plus `ollama` on port 11436 with `qwen3-embedding:0.6b` auto-pulled. Bind-mounts `./data` for persistence.

**Developer / contributor install** (editable + dev deps):

```bash
git clone https://github.com/nrmeyers/skillsmith.git && cd skillsmith
uv sync
uv run python -m skillsmith.install setup
```

---

## Demo

```bash
$ curl -s -X POST http://localhost:47950/compose \
    -H 'Content-Type: application/json' \
    -d '{"task": "write a failing pytest", "phase": "build"}' | jq .

{
  "output": "## TDD: write the failing test first\n\nIn pytest, ...",
  "source_skills": ["test-driven-development", "pytest-fixtures"],
  "tokens_returned": 1840,
  "compose_ms": 47
}
```

Your agent calls `/compose`, gets back the relevant raw skill prose, and assembles it inside its own prompt. No LLM-in-the-loop, no token tax, no API key roulette. Sub-50ms p95 on a warm cache.

---

## Why not just paste skills into CLAUDE.md

Pasting `CLAUDE.md` (or `.cursorrules`, or `.windsurfrules`, or `.github/copilot-instructions.md`) full of skills tops out where skillsmith starts:

- **Composed per task, not loaded every turn.** A skill that's irrelevant to the current task isn't in the prompt at all — RRF + applicability filtering picks the right subset for each request. 60% smaller prompts on average vs. flat injection (see [Empirical results](#empirical-results)).
- **Phase-aware.** Build-phase skills weight differently than QA-phase or review-phase skills. The same task gets a different composition at different points in the lifecycle.
- **Hybrid retrieval, not lexical-only.** Token-literal queries (`"JWT"`, `"Prisma"`) hit BM25; semantic queries ("the auth handler") hit a 1024-dim dense leg. Phase-tuned Reciprocal Rank Fusion picks the better signal per query.
- **No model variance.** Embeddings + lexical match + deterministic fusion. Same task → same composition, regardless of which agent model you swap in tomorrow.
- **Versioned & validated.** Every skill is sourced from authoritative upstream docs and validated against the R1–R8 quality contract; reviewable history under `docs/skill-review-history/`.

---

## Two ways to use it

### 1. Standalone HTTP service

Run skillsmith on its own port; your agent (or your script, or your CI) calls `POST /compose` and reads the response. Zero coupling to a specific harness — works with any agent that can hit an HTTP endpoint.

```bash
uv run python -m skillsmith.app           # default :47950
curl -s http://localhost:47950/health     # {"status":"ok"}
```

### 2. Wired into your coding harness

Use the bundled `wire-harness` subcommand to drop sentinel-bounded skill-access instructions into the right file for your harness. One command, one rules-file. Cleanly removable via `uninstall`.

```bash
uv run python -m skillsmith.install wire-harness --harness <name>
```

Supported harnesses: `claude-code`, `gemini-cli`, `cursor`, `windsurf`, `github-copilot`, `continue-closed`, `continue-local`, `hermes-agent`, `opencode`, `aider`, `cline`, and `manual` (paste-it-yourself). Add `--mcp-fallback` to wire via MCP server config instead of markdown injection (Claude Code, Cursor, Continue). Full catalog in [`docs/install/harness-catalog.md`](docs/install/harness-catalog.md).

---

## Standalone CLI

The `skillsmith.install` module exposes a single CLI with subcommands. All write paths are user-scoped (LadybugDB and pack drafts live under `user_config_dir()`).

| Command | Description |
|---|---|
| `setup` | End-to-end interactive install (calls every step below in order). |
| `preflight` | Gate prereqs (Python, runtimes, ports) before any state changes. |
| `pull-models` | Pull / verify the embedding model is loaded into your backend. |
| `start-embed-server` | Start the embedding backend (llama-server or Ollama) before pack install. |
| `seed-corpus` | One-shot pack ingestion into LadybugDB + DuckDB. |
| `install-packs [--packs <names>] [--list]` | Install/refresh specific pack(s), or `--list` to see what's available. |
| `install-pack [--pack <name>]` | Install a single pack by name. |
| `reembed` | Recompute embeddings for unembedded or updated LadybugDB fragments. |
| `wire [--harness <name>]` | Auto-detect the harness in the current repo and inject sentinels (or pass `--harness` to force). |
| `wire-harness --harness <name>` | Lower-level: explicit harness wiring with full flag control. |
| `unwire` | Remove skillsmith sentinels from the current repo (keeps user state). |
| `write-env` | Write `.env` with the resolved backend / model / paths. |
| `server-start` / `server-stop` / `server-restart` / `server-status` | Manage the background FastAPI daemon on :47950. |
| `serve` | Run the service in the foreground (uvicorn). |
| `enable-service` | Register skillsmith as a persistent background service (systemd-user / launchd). |
| `status` | Show user-scope install state, wired repos, and service reachability. |
| `verify` | Run post-install integrity checks (corpus count, harness sentinels, port). |
| `doctor` | Diagnose a partial / broken install. |
| `update` | Pull the latest packs and re-seed. |
| `uninstall` | Cross-repo sentinel cleanup, optional data-dir wipe. |
| `reset-step <step>` | Roll back one step of an in-progress install. |
| `telemetry` | Query / inspect composition traces from the CLI. |

Each subcommand emits structured JSON on stdout; pair with `jq` for scripting.

---

## REST API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/compose` | Hybrid retrieve + assemble. Returns JSON: `{output, source_skills, tokens_returned, compose_ms}`. |
| `POST` | `/compose/text` | Same as `/compose` but returns `text/plain` — paste-ready for harnesses that take freeform context. |
| `POST` | `/retrieve` | Retrieve only (no assembly). Returns ranked fragment IDs + scores + provenance. |
| `GET` | `/retrieve/{skill_id}` | Look up a single skill's retrievable fragments by id. |
| `GET` | `/skills/{skill_id}` | Inspect a skill — versions, fragments, applicability rules. |
| `GET` | `/telemetry/traces` | Composition trace history. See [Telemetry](#telemetry). |
| `GET` | `/health` | `{"status":"ok"}` liveness probe. |
| `GET` | `/diagnostics/runtime` | Backend / model / DB state for debugging. |

Request body for `/compose`:

```json
{
  "task": "<one-sentence task description>",
  "phase": "spec" | "design" | "build" | "qa" | "ops",
  "domain_tags": ["postgres", "fastapi"]   // optional hard filter
}
```

---

## Hardware presets

The runtime needs only an embedding service. The install agent picks one for you, but here's the matrix:

| Preset | Hardware | Backend | VRAM / RAM |
|---|---|---|---|
| `cpu` | x86_64 / ARM64 | Ollama (CPU) | 8 GB RAM |
| `apple-silicon` | M1 / M2 / M3 / M4 | Ollama (Metal) | 8 GB unified |
| `nvidia` | NVIDIA + CUDA | Ollama (CUDA) | 4 GB VRAM |
| `radeon` | AMD Radeon dGPU/iGPU | LM Studio (Vulkan) | 4 GB VRAM |

All presets use **`qwen3-embedding:0.6b`** at 1024 dimensions and bind `localhost:11436`. The on-disk index is portable across backends — switching is an env-var flip.

```bash
# Ollama presets
ollama pull qwen3-embedding:0.6b

# Radeon: open LM Studio → search qwen3-embedding:0.6b → Q8 → start server
```

---

## Packs shipping in-tree

The corpus is **packs** — opt-in groups of related skills. As of 2026-05-16, `main` ships **35 packs / 324 declared skills** organized across 9 tiers:

<table>
<tr><th>Tier</th><th>Packs</th></tr>
<tr><td><b>foundation</b></td><td><code>core</code> · <code>documentation</code> · <code>engineering</code> · <code>performance</code> · <code>refactoring</code></td></tr>
<tr><td><b>language</b></td><td><code>csharp-dotnet</code> · <code>go</code> · <code>java</code> · <code>nodejs</code> · <code>python</code> · <code>rust</code> · <code>typescript</code></td></tr>
<tr><td><b>framework</b></td><td><code>fastapi</code> · <code>fastify</code> · <code>nestjs</code> · <code>nextjs</code> · <code>react</code> · <code>vue</code></td></tr>
<tr><td><b>tooling</b></td><td><code>linting</code> · <code>pytest</code> · <code>testing</code></td></tr>
<tr><td><b>workflow</b></td><td><code>code-review</code> · <code>design-review</code> · <code>intake</code> · <code>sdd</code></td></tr>
<tr><td><b>domain</b></td><td><code>analytics</code> · <code>data-engineering</code> · <code>ui-design</code></td></tr>
<tr><td><b>platform</b></td><td><code>github-actions</code></td></tr>
<tr><td><b>protocol</b></td><td><code>rest</code> · <code>webhooks</code></td></tr>
<tr><td><b>store</b></td><td><code>redis</code> · <code>redshift</code> · <code>snowflake</code> · <code>temporal</code></td></tr>
</table>

Every skill is sourced from authoritative upstream docs and validated against the **R1–R8 quality contract** in `src/skillsmith/_packs/meta/sys-skill-authoring-rules.md`. Each pack ships with `.qa.md` reports under `docs/skill-review-history/` documenting independent Critic verdicts.

To author a new pack, see `docs/PACK-AUTHORING.md`. For the full authoring pipeline (bounce loop, QA gate, critic tooling), see [skillsmith-authoring](../skillsmith-authoring).

---

## How packs get authored

Local-first three-stage pipeline. Skillsmith doesn't burn paid LLM tokens to grow the corpus.

```
SKILL.md  →  [Author MoE]  →  draft YAML  →  [Critic dense]  →  approve / revise
                                                   ↓
                                           [Opus safety gate]
                                                   ↓
                                             pending-review/  →  ingest
```

| Stage | Model | Where it runs |
|---|---|---|
| **Author** | `Qwen3.6-35B-A3B` (UD-IQ4_NL_XL, MoE — 3B active) | local Ollama |
| **Critic** | `Qwen3.6-27B` (UD-Q5_K_XL, dense) | local Ollama |
| **Safety gate** | Claude Opus (one-pass review) | only when bounce budget exhausted |

**Single-GPU friendly.** The pipeline is *swap-batched*: `run` warms the author model, drafts the whole batch, then warms the critic, grades the whole batch, then swaps back to author for revisions. Two model loads per round instead of two per skill — fits a 24GB-VRAM card (e.g. RTX 3090) where author and critic can't coexist.

```bash
python -m skillsmith.authoring run <source-dir>                # swap-batched (default)
python -m skillsmith.authoring run <source-dir> --single-skill # per-skill (requires both models pre-loaded)
```

The bounce loop iterates author↔critic up to `bounce_budget=5` times per skill. ~70-80% of skills converge in 1 round; ~15% in 2-3; the residue routes to `needs-human/` for hand-authoring.

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│   POST /compose                                          │
│      ↓                                                   │
│   embed task → hybrid retrieve (BM25 + dense, RRF) →    │
│   hydrate fragments → return raw concatenated text       │
│      ↓                                                   │
│   agent assembles in its own prompt context              │
└──────────────────────────────────────────────────────────┘
                ↓                              ↓
   ┌────────────────────────┐    ┌──────────────────────────┐
   │   DuckDB               │    │   LadybugDB (Kùzu)       │
   │   ─────────────        │    │   ────────────────       │
   │   • 1024-dim vectors   │    │   • Skill nodes          │
   │   • BM25 FTS index     │    │   • SkillVersion nodes   │
   │   • Composition traces │    │   • Fragment nodes       │
   │                        │    │   • Pack relationships   │
   │   "what to retrieve"   │    │   "what it means"        │
   └────────────────────────┘    └──────────────────────────┘
```

- **Embedding** — `qwen3-embedding:0.6b` (1024-dim). Backend-agnostic via OpenAI-compatible `/v1/embeddings`.
- **Retrieval** — hybrid BM25 + dense cosine fused via Reciprocal Rank Fusion with phase-specific leg weighting. Token-literal queries hit BM25; semantic queries hit dense.
- **Applicability filter** — pure-rule predicates on `ActiveSkill` records (always_apply, phase_scope, category_scope). No LLM parsing; governance rules are strictly deterministic.
- **Telemetry** — every `/compose` and `/retrieve` call writes a structured trace to DuckDB inline-before-response. See [Telemetry](#telemetry).
- **No generative LLM in the runtime path.** The agent owns generation; skillsmith owns retrieval.

For a deeper look at the dual-DB design (and why it's the right shape for code intelligence too), see `docs/code-indexer-architecture-1pager.md`.

---

## Telemetry

Every `/compose` and `/retrieve` call writes a structured trace to DuckDB **before the response returns** — no async backlog, no dropped traces. Trace-write failures are logged but never propagate; the response always succeeds regardless of telemetry state.

Each trace captures: `trace_id`, `phase`, `task_prompt`, `status`, `selected_fragment_ids`, `source_skill_ids`, `system_skill_ids`, `workflow_skill_ids`, `retrieval_latency_ms`, `assembly_latency_ms`, `total_latency_ms`, `response_size_chars`, and (on failure) `error_code`.

Query via `GET /telemetry/traces` with optional filters:

| Filter | Type | Purpose |
|---|---|---|
| `phase` | string | `spec` / `design` / `build` / `qa` / `ops` |
| `status` | string | success / error / degraded result type |
| `since`, `until` | epoch ms | time-range window |
| `limit`, `offset` | int | pagination (1 ≤ limit ≤ 500, default 50) |

Use it to inspect which skills got composed for a task, profile retrieval latency across phases, or audit governance-rule applicability over time. Traces live in the same DuckDB file as the vector index (`DUCKDB_PATH`).

---

## Configuration

Environment variables (written automatically by `skillsmith install write-env`):

| Variable | Default | Purpose |
|---|---|---|
| `RUNTIME_EMBED_BASE_URL` | `http://localhost:11436` | Embedding endpoint |
| `RUNTIME_EMBEDDING_MODEL` | `qwen3-embedding:0.6b` | Embedding model for retrieve / compose |
| `LADYBUG_DB_PATH` | `~/.local/share/skillsmith/corpus/ladybug` | LadybugDB directory |
| `DUCKDB_PATH` | `~/.local/share/skillsmith/corpus/skills.duck` | DuckDB vector + telemetry store |
| `AUTHORING_MODEL` | `qwen3-14b-instruct` | Author model (authoring only) |
| `AUTHORING_LM_BASE_URL` | `http://localhost:11435` | Author endpoint |
| `LM_STUDIO_BASE_URL` | `http://localhost:11434` | LM Studio endpoint (authoring only) |
| `AUTHORING_EMBED_BASE_URL` | `http://localhost:11436` | Authoring-pipeline embedding endpoint |
| `AUTHORING_EMBEDDING_MODEL` | `qwen3-embedding:0.6b` | Authoring-pipeline embedding model |
| `CRITIC_MODEL` | `qwen3.6-27b` | Critic model (authoring only) |
| `DEDUP_HARD_THRESHOLD` | `0.92` | Dedup hard cosine threshold |
| `DEDUP_SOFT_THRESHOLD` | `0.80` | Dedup soft cosine threshold |
| `BOUNCE_BUDGET` | `3` | Max author↔critic revision rounds |
| `LOG_LEVEL` | `INFO` | Log verbosity |

Copy [`.env.example`](.env.example) and adjust paths for your machine. The example file documents every variable inline.

---

## Development

```bash
uv sync                          # install deps
uv run ruff check .              # lint
uv run ruff format --check .     # format
uv run pyright                   # types
uv run pytest                    # unit tests (fast)
uv run pytest -m integration     # integration — requires Ollama with qwen3-embedding:0.6b
```

Tests live under `tests/` and cover the install pipeline (`tests/install/`), retrieval, composition, applicability filtering, telemetry, and the harness-wiring catalog.

---

## Empirical results

See `docs/experiments/poc-composed-vs-flat.md` §13. Headline:

> **60% smaller prompts. 25% faster runs. Same model — and answers improve, not degrade.**

Reproduce: `AGENT_MODEL=<your-agent-model> uv run python -m eval.run_poc --n 3` (requires running skillsmith + the agent model loaded locally).

---

## License

MIT. See [LICENSE](LICENSE).
