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
  <img src="https://img.shields.io/badge/packs-22-orange" alt="22 packs" />
  &nbsp;
  <img src="https://img.shields.io/badge/skills-110+-orange" alt="110+ skills" />
</p>

<p align="center">
A runtime corpus of engineering skills — testing, error handling, deployment, observability, security, framework patterns — composed dynamically per task and served to your agent over HTTP. The runtime holds <b>no generative LLM</b>. Just embeddings + a graph + your agent.
</p>

---

## What it actually does

**60% smaller prompts. 25% faster runs. Same model — and answers improve, not degrade.**
— `docs/experiments/poc-composed-vs-flat.md` §13

```
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

## Quickstart

**1. Clone**

```bash
git clone https://github.com/nrmeyers/skillsmith.git
cd skillsmith
```

**2. Open your coding harness** — Claude Code, Cursor, Gemini CLI, Continue.dev, OpenCode, Aider, Cline.

**3. Tell the agent to install**

```
Install this tool by following INSTALL.md
```

The agent reads `INSTALL.md`, detects your hardware, pulls the embedding model, seeds the corpus, and wires itself up. **3–5 minutes** on a warm machine.

**Headless one-liner** (CI / containers / scripts):

```bash
uv sync
uv run python -m skillsmith.install install-packs --packs all --non-interactive
```

`--packs` accepts `all` or a comma-separated list. Unknown names fail fast in non-interactive mode; pass `--ignore-unknown` to skip them.

---

## Hardware presets

The runtime needs only an embedding service. The install agent picks one for you, but here's the matrix:

| Preset | Hardware | Backend | VRAM / RAM |
|---|---|---|---|
| `cpu` | x86_64 / ARM64 | Ollama (CPU) | 8 GB RAM |
| `apple-silicon` | M1 / M2 / M3 / M4 | Ollama (Metal) | 8 GB unified |
| `nvidia` | NVIDIA + CUDA | Ollama (CUDA) | 4 GB VRAM |
| `radeon` | AMD Radeon dGPU/iGPU | LM Studio (Vulkan) | 4 GB VRAM |

All presets use **`qwen3-embedding:0.6b`** at 1024 dimensions. Ollama presets bind `localhost:11434`; radeon binds `localhost:1234`.

```bash
# Ollama presets
ollama pull qwen3-embedding:0.6b

# Radeon: open LM Studio → search qwen3-embedding:0.6b → Q8 → start server
```

---

## Packs shipping in-tree

The corpus is **packs** — opt-in groups of related skills. As of 2026-05-06, `main` ships **22 packs / ~110 skills**:

<table>
<tr><th>Tier</th><th>Packs</th></tr>
<tr><td><b>system</b></td><td><code>meta</code> · <code>conventions</code></td></tr>
<tr><td><b>foundation</b></td><td><code>core</code> · <code>engineering</code> · <code>documentation</code> · <code>refactoring</code> · <code>performance</code></td></tr>
<tr><td><b>language</b></td><td><code>python</code> · <code>typescript</code> · <code>nodejs</code> · <code>go</code> · <code>rust</code> · <code>csharp-dotnet</code> · <code>java</code></td></tr>
<tr><td><b>framework</b></td><td><code>react</code> · <code>nextjs</code> · <code>fastapi</code> · <code>vue</code> · <code>nestjs</code> · <code>fastify</code></td></tr>
<tr><td><b>store</b></td><td><code>temporal</code></td></tr>
<tr><td><b>tooling</b></td><td><code>linting</code> · <code>pytest</code></td></tr>
</table>

Every skill is sourced from authoritative upstream docs and validated against the **R1–R8 quality contract** in `src/skillsmith/_packs/meta/sys-skill-authoring-rules.md`. Each pack ships with `.qa.md` reports under `docs/skill-review-history/` documenting independent Critic verdicts.

To author a new pack, see `docs/PACK-AUTHORING.md`.

---

## How packs get authored

Three-stage local pipeline. Skillsmith doesn't burn paid LLM tokens to grow the corpus.

```
SKILL.md  →  [14B Author]  →  draft YAML  →  [30B Critic]  →  approve / revise
                                                  ↓
                                          [Opus safety gate]
                                                  ↓
                                            pending-review/  →  ingest
```

| Stage | Model | Where it runs |
|---|---|---|
| **Author** | `Qwen2.5-Coder-14B-Instruct` (Q4_K_M) | local Ollama / LM Studio |
| **Critic** | `granite-4.1-30b` (UD-Q4_K_XL) | local Ollama / LM Studio |
| **Safety gate** | Claude Opus (one-pass review) | only when bounce budget exhausted |

The bounce loop (`python -m skillsmith.authoring run <source-dir>`) bounces drafts between author and critic up to `bounce_budget=3` times. ~80% of skills converge in 1 round; ~15% in 2; the residue routes to `needs-human/` for hand-authoring.

---

## Run via container

For evaluators or CI environments — no Python required:

```bash
podman compose up -d            # or: docker compose up -d
curl http://localhost:47950/health
```

This brings up:
- `skillsmith` — FastAPI service on port 47950, pre-seeded corpus baked in
- `ollama` — Ollama on port 11434 with `qwen3-embedding:0.6b` auto-pulled

Persistent state:
- `./data` bind-mounted — runtime ingestions persist on the host
- Ollama models in a named volume (`skillsmith-ollama-models`)

```bash
podman compose down              # stop, keep volumes
podman compose down -v           # stop, remove ollama-models volume
```

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
- **Retrieval** — hybrid BM25 + dense cosine fused via Reciprocal Rank Fusion. Token-literal queries (`"JWT"`, `"Prisma"`) hit BM25; semantic queries hit dense.
- **No generative LLM in the runtime path.** The agent owns generation; skillsmith owns retrieval.

For a deeper look at the dual-DB design (and why it's the right shape for code intelligence too), see `docs/code-indexer-architecture-1pager.md`.

---

## Test

```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest                    # unit tests only
uv run pytest -m integration     # requires Ollama with qwen3-embedding:0.6b
```

---

## Configuration

Environment variables (written automatically by `skillsmith install write-env`):

| Variable | Default | Purpose |
|---|---|---|
| `RUNTIME_EMBED_BASE_URL` | `http://localhost:11434` | Embedding endpoint (`http://localhost:1234` for radeon) |
| `RUNTIME_EMBEDDING_MODEL` | `qwen3-embedding:0.6b` | Embedding model for retrieve / compose |
| `LADYBUG_DB_PATH` | `./data/ladybug` | LadybugDB directory |
| `DUCKDB_PATH` | `./data/skills.duck` | DuckDB vector + telemetry store |
| `AUTHORING_MODEL` | `hf.co/unsloth/Qwen2.5-Coder-14B-Instruct-GGUF:Q4_K_M` | Author model (authoring only) |
| `CRITIC_MODEL` | `hf.co/unsloth/granite-4.1-30b-GGUF:UD-Q4_K_XL` | Critic model (authoring only) |
| `AUTHORING_LM_BASE_URL` | (falls back to `LM_STUDIO_BASE_URL`) | Author endpoint (lets author + critic run on different ports) |
| `AUTHORING_EMBEDDING_MODEL` | `qwen3-embedding:0.6b` | Authoring-pipeline embedding model |
| `DEDUP_HARD_THRESHOLD` | `0.92` | Dedup hard cosine threshold |
| `DEDUP_SOFT_THRESHOLD` | `0.80` | Dedup soft cosine threshold |
| `BOUNCE_BUDGET` | `3` | Max author↔critic revision rounds |
| `LOG_LEVEL` | `INFO` | Log verbosity |

---

## Empirical results

See `docs/experiments/poc-composed-vs-flat.md` §13. Headline:

> **60% smaller prompts. 25% faster runs. Same model — and answers improve, not degrade.**

Reproduce: `AGENT_MODEL=<your-agent-model> uv run python -m eval.run_poc --n 3` (requires running skillsmith + the agent model loaded locally).

---

## License

MIT. See [LICENSE](LICENSE).
