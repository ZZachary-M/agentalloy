# skillsmith

Runtime skill composition service. Accepts a task description and SDD phase, retrieves the most relevant skill fragments from a versioned graph + vector store, auto-includes applicable governance, and returns concatenated raw fragment text plus provenance for the inference model to consume. Logs structured composition traces.

The runtime path holds **no generative LLM** — only an embedding service. The agent that calls the API does its own assembly inside its own prompt context.

See `memory/` for per-issue contracts. See the Linear project **Skillsmith v1.0** for spec, design, and milestones. See `docs/experiments/poc-composed-vs-flat.md` for empirical findings.

## Requirements

- Python 3.12
- [mise](https://mise.jdx.dev/) (runtime manager)
- An OpenAI-compatible embedding service (see [Platform Setup](#platform-setup))
- For the **authoring pipeline only**: an OpenAI-compatible chat completion service

## Platform Setup

The runtime requires only an embedding service. Pick the preset that matches your hardware, copy it to `.env`, and follow the setup comments inside:

| Preset | Hardware | Embedding backend | RAM / VRAM minimum |
|--------|----------|-------------------|--------------------|
| `cpu` | Any x86_64 / ARM64 | Ollama on CPU | 8 GB RAM |
| `apple-silicon` | Apple M1/M2/M3/M4 | Ollama (Metal) | 8 GB unified |
| `nvidia` | NVIDIA GPU (CUDA) | Ollama (CUDA) | 4 GB VRAM |
| `radeon` | AMD Radeon dGPU | LM Studio (Vulkan) | 4 GB VRAM |

```bash
# Example: CPU-only setup
skillsmith install setup --preset cpu
ollama pull qwen3-embedding:0.6b
```

All presets use `qwen3-embedding:0.6b` (1024-dim) for embeddings. `cpu`, `apple-silicon`, and `nvidia` use Ollama at `localhost:11434`; `radeon` uses LM Studio's Vulkan backend at `localhost:1234`. The `OpenAICompatClient` is backend-agnostic — any server exposing `/v1/embeddings` works.

For authoring (generating new skills via the LLM pipeline), you also need a chat model. See the preset comments for recommended models per platform. Authoring is optional — you can run the service with pre-ingested skills and no generation model.

## Setup

```bash
mise install
```

## Run

```bash
python -m skillsmith
# service on http://localhost:8000
curl localhost:8000/health
```

## Run via container (no Python install required)

For evaluators or anyone who'd rather not install Python + uv on the host:

```bash
podman compose up -d         # or: docker compose up -d
curl http://localhost:8000/health
```

This brings up two services:

- `skillsmith` — the FastAPI service on port 8000, built from `Containerfile` with the pre-seeded corpus baked in
- `ollama` — Ollama on port 11434 with `qwen3-embedding:0.6b` auto-pulled on first start

Persistent state:
- The host's `./data` directory is bind-mounted into the skillsmith container, so any skills you ingest at runtime persist on the host
- Ollama's downloaded models live in a named volume (`skillsmith-ollama-models`) so the embedding model isn't re-pulled on container restart

To stop and clean up:

```bash
podman compose down              # stop containers, keep volumes
podman compose down -v           # also remove the ollama-models volume
```

## Test

```bash
ruff check .
ruff format --check .
pyright
pytest                    # unit tests only
pytest -m integration     # integration tests (requires Ollama with qwen3-embedding:0.6b)
```

## Configuration

Environment variables:

| Variable | Default | Purpose |
|----------|---------|---------|
| `RUNTIME_EMBED_BASE_URL` | `http://localhost:11434` | Embedding endpoint (Ollama; `http://localhost:1234` for radeon preset) |
| `RUNTIME_EMBEDDING_MODEL` | `qwen3-embedding:0.6b` | Embedding model for retrieve / compose |
| `LADYBUG_DB_PATH` | `./data/ladybug` | LadybugDB directory |
| `DUCKDB_PATH` | `./data/skills.duck` | DuckDB vector + telemetry store |
| `AUTHORING_MODEL` | `qwen/qwen3.6-35b-a3b` | Model for skill generation (authoring only) |
| `CRITIC_MODEL` | `qwen/qwen3.6-35b-a3b` | Model for authoring critic (authoring only) |
| `AUTHORING_EMBEDDING_MODEL` | `qwen3-embedding:0.6b` | Authoring-pipeline embedding model (authoring only) |
| `DEDUP_HARD_THRESHOLD` | `0.92` | Dedup hard cosine threshold |
| `DEDUP_SOFT_THRESHOLD` | `0.80` | Dedup soft cosine threshold |
| `BOUNCE_BUDGET` | `3` | Max retrieval bounces |
| `LOG_LEVEL` | `INFO` | Log verbosity |

## Architecture

- **Embedding service** (configurable) runs `qwen3-embedding:0.6b` (1024-dim). Backend-agnostic — Ollama, LM Studio, vLLM all work via the OpenAI-compatible API.
- **DuckDB** holds 1024-dim L2-normalized fragment vectors, BM25 FTS index, and composition traces.
- **LadybugDB (Kùzu)** holds the skill graph (Skill → SkillVersion → Fragment).
- **Compose flow**: agent → POST /compose → embed task → DuckDB cosine search → hydrate fragments → return raw concatenated text. Agent assembles in its own prompt context.
- **No generative LLM in the runtime path.** The agent that calls the API does its own generation.

## Empirical results

See `docs/experiments/poc-composed-vs-flat.md` §13 for the first-round POC findings. Headline:

> **60% smaller prompts. 25% faster runs. Same model — and answers improve, not degrade.**

Reproduce: `AGENT_MODEL=qwen/qwen3.6-35b-a3b uv run python -m eval.run_poc --n 3` (requires running skillsmith + LM Studio with the agent model loaded).
