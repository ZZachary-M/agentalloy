# Skillsmith — Install Runbook

> **For the calling LLM:** Read this file top-to-bottom. Each numbered step tells you what to do. When you see a `> RUN` block, execute that command and capture the output. When you see a `> ASK` block, ask the user the question and wait for their answer before proceeding. When you see a `> CONFIRM` block, present the result to the user and wait for them to confirm or correct.
>
> Skip steps already marked complete in the user-scope state file at `${XDG_CONFIG_HOME:-~/.config}/skillsmith/install-state.json`. If that file doesn't exist yet, you're on a fresh install. (You can read it with `skillsmith status`.)
>
> If any subcommand exits with a non-zero status, surface the error to the user and run `skillsmith doctor` for remediation hints. Do not continue past a failed step.

---

## What this installs

A local **Skillsmith** service that gives your coding agent (this LLM, or another) access to a curated corpus of engineering skills — testing patterns, error handling, deployment recipes, observability, security, etc. — composed dynamically per task.

The runtime is a small FastAPI service backed by:
- An embedding model (`qwen3-embedding:0.6b`, 1024-dim) — runs on any hardware via Ollama or LM Studio
- A skill corpus split into **packs** that the user opts into at install time (default: `core` + `engineering`; opt-in: `nodejs`, `typescript`, `nestjs`, `react`, `vue`, `agents`, `auth`, `observability`, etc.). Pack source YAMLs ship in the wheel; the binary corpus (LadybugDB + DuckDB) is generated locally on first install.
- Your handoff harness (Claude Code / Cursor / Continue.dev / etc.) — wired so it can query the API

**Skillsmith is user-scoped, not per-repo.** You install once; every project the user opens can wire to the same service. State lives at `${XDG_CONFIG_HOME:-~/.config}/skillsmith/`; corpus at `${XDG_DATA_HOME:-~/.local/share}/skillsmith/corpus/`. Repos contain only sentinel-bounded blocks injected into agent config files (`CLAUDE.md`, `.cursor/rules/skillsmith.mdc`, etc.).

Total install time: usually 3–5 minutes on a warm machine.

---

## TL;DR

Most users want exactly this:

```bash
# One-time: install the CLI into PATH so it works from any directory.
uv tool install --editable .

# Once per machine — installs everything user-scoped.
# Will prompt: "Do you want skillsmith to run persistently as a background service?"
skillsmith setup

# Once per repo — wire this project to the service. Auto-detects the harness.
cd ~/dev/some-project && skillsmith wire

# If you chose manual mode during setup, start the service now:
skillsmith serve
```

If you want to walk the user through this carefully (recommended for first install on the machine), the rest of this runbook drills into each step the LLM should take.

---

## Prerequisites

You need:
- **Python 3.12+** with [`uv`](https://github.com/astral-sh/uv) installed
- A network connection (for model downloads — the corpus is already in the wheel)
- One of the supported handoff harnesses installed (we'll ask which one in step 5)

The runbook itself runs `skillsmith preflight` (Step 0 below) to verify these. **Never bypass a failed preflight check** — every later step assumes the prereqs are met, and skipping a fatal failure here is what causes the LLM to hand-roll workarounds (`~/.local/bin/skillsmith install-packs --list` etc.) midstream.

For missing binaries (`uv`, `ollama`), **stop and ask the user to install them**. Do not auto-execute install scripts — that's a non-reversible action that requires the human in the loop. Install commands:

- **uv:** see https://docs.astral.sh/uv/getting-started/installation/
- **Ollama (Linux):** `curl -fsSL https://ollama.com/install.sh | sh`
- **Ollama (macOS):** `brew install ollama`, or https://ollama.com/download/mac
- **Ollama (Windows / other):** see https://ollama.com/download

After installing Ollama, the user must have `ollama serve` running (the official installer sets this up as a service on macOS/Windows; on Linux the install script registers a systemd unit). Step 0's runner-phase preflight confirms reachability.

---

## Step 0: Preflight (run this first, every time)

> RUN
> ```bash
> uv run python -m skillsmith.install preflight
> ```

This runs the host-agnostic checks: Python ≥ 3.12, `uv` present, `skillsmith` resolvable on PATH (i.e. `~/.local/bin` is in `$PATH`), XDG dirs writable, network reachable, default port `47950` free.

> CONFIRM
>
> If `preflight` exits non-zero, the JSON output lists `fatal_failures` and a `remediation` line for each. **Surface every fatal remediation to the user verbatim and STOP.** Do not run `skillsmith setup`, do not move on to Step 1, and do not invent workarounds. Once the user has applied the fixes, re-run Step 0 until it exits 0.

If `cli_on_path` fails before Step 1b has run, that's expected — Step 1b installs the CLI. Run Step 1 + Step 1b first, then re-run Step 0 to confirm `cli_on_path` now passes.

---

## Step 1: Pre-flight

> RUN
> ```bash
> uv sync
> ```

This installs the skillsmith Python dependencies into a project-local `.venv`. Should take under 30 seconds on a warm cache.

If `uv sync` fails:
- Network issue → retry or check proxy settings
- Python version mismatch → `python --version` should be ≥ 3.12

---

## Step 1b: Install the CLI user-scoped

> RUN
> ```bash
> uv tool install --editable .
> ```

This installs the `skillsmith` command into the user's PATH (at `~/.local/bin/skillsmith` or equivalent) so it works from any directory — not just from inside this repo. Required so `skillsmith wire`, `skillsmith serve`, and `skillsmith status` work after you `cd` into a project repo.

Verify it landed by re-running preflight (which is the authoritative PATH check):

> RUN
> ```bash
> skillsmith preflight
> ```

If `cli_on_path` still fails, the JSON `remediation` field gives the exact `export PATH=...` line to add. Surface it to the user verbatim and **STOP** until they confirm they've fixed their shell profile and `which skillsmith` resolves to `~/.local/bin/skillsmith`.

---

## Step 2: Hardware detection

> RUN
> ```bash
> skillsmith detect
> ```

This emits a JSON document describing the hardware. Read it. The output is also written to `${XDG_DATA_HOME:-~/.local/share}/skillsmith/outputs/detect.json` so subsequent steps can refer to it.

> CONFIRM
>
> Tell the user, in plain English, what was detected. For example:
> > "I detected a MacBook Pro with Apple Silicon (M3 Pro), 36 GB unified memory, macOS 14.5. No discrete GPU. Metal acceleration is available. Does that look right?"
>
> Wait for the user to confirm or correct. If they correct, replace the corresponding fields in your working memory and use the corrected values for subsequent steps.

---

## Step 3: Host target selection

> RUN
> ```bash
> skillsmith recommend-host-targets --hardware ~/.local/share/skillsmith/outputs/detect.json
> ```

The output lists which host targets are available on this hardware. Exactly one will be flagged `recommended: true`.

> ASK
>
> Present the recommendation first, then list alternatives. For example:
> > "I recommend running the embedding model on the **iGPU** (Apple Metal), because it's faster than CPU and your Mac has it available. Alternatives: dGPU (not available on this hardware), or CPU+RAM (slower but works).
> >
> > Use the recommendation, or pick a different target?"
>
> Wait for an answer. Default to the recommendation if the user just hits enter.

---

## Step 4: Model variant selection

> RUN
> ```bash
> skillsmith recommend-models --hardware ~/.local/share/skillsmith/outputs/detect.json --host <chosen-target>
> ```

The output lists `{embed_model, embed_runner}` options valid for the chosen host target, with one flagged `default: true`. The `preset` field tells you which `.env` preset will be used.

> ASK
>
> Most users want the default. For example:
> > "For Apple Silicon + iGPU, I'll use **qwen3-embedding:0.6b** via Ollama. Use this default, or pick a different runner?"
>
> Wait for confirmation.

---

## Step 5: Pull models

> RUN
> ```bash
> skillsmith pull-models --models ~/.local/share/skillsmith/outputs/recommend-models.json
> ```

The output may include `manual_steps_required` if the user picked a runner without auto-pull (LM Studio, MLX, vLLM). If so:

> CONFIRM
>
> Read the `manual_steps_required` instructions to the user verbatim. Wait for them to confirm they've completed those steps before proceeding.

If `recommend-models` ran non-interactively and defaulted to `ollama` but the user has `llama-server` installed, pass `--runner llama-server` to override:

```bash
skillsmith pull-models --models ~/.local/share/skillsmith/outputs/recommend-models.json --runner llama-server
```

---

## Step 6: Initialize the corpus directory

> RUN
> ```bash
> skillsmith seed-corpus
> ```

This creates the user-scoped corpus directory at `${XDG_DATA_HOME:-~/.local/share}/skillsmith/corpus/` and initializes empty LadybugDB + DuckDB stores. The wheel no longer ships pre-built skills — Step 8 below populates the corpus from packs the user picks.

---

## Step 7: Start the embedding server

> RUN
> ```bash
> skillsmith start-embed-server --models ~/.local/share/skillsmith/outputs/recommend-models.json
> ```

This brings the embedding backend online before pack ingestion. What happens depends on the runner chosen in Step 4:

- **llama-server**: spawns `llama-server --embeddings --port 11436 --ubatch-size 2048` in the background and waits up to 120 seconds for the server to accept connections. The log is written to `~/.local/share/skillsmith/logs/embed-server.log`.
- **ollama**: fires `ollama serve` (idempotent — safe if already running) and polls port 11436.
- **lm-studio / other**: prints instructions for you to start the server manually. Start it before proceeding to Step 8.

The step is idempotent: if port 11436 is already listening it exits 0 immediately.

> CONFIRM
>
> Wait for this step to exit 0 before continuing. If it times out, check the log at `~/.local/share/skillsmith/logs/embed-server.log` for startup errors.

---

## Step 8: Pick and install skill packs

First, preview available packs:

> RUN
> ```bash
> skillsmith install-packs --list
> ```

Then install selected packs:

> RUN
> ```bash
> skillsmith install-packs
> ```

The user is shown a numbered list of available packs (each with description + skill count) and asked to pick which ones to install. Two packs (`core`, `engineering`) are always installed automatically.

> ASK
>
> Tell the user:
> > "Skillsmith's corpus is split into packs. You opt in to the ones that match your stack. `core` and `engineering` install automatically. The most common picks for backend work: `nodejs`, `typescript`, plus your framework (e.g., `nestjs`, `fastify`). For agentic dev, add `agents`. Pick now or type `defaults` to go with always-on packs only — you can install more packs later with `skillsmith install-pack <name>`."
>
> Read the available packs from the CLI's interactive prompt. Wait for the user's selection. The prompt accepts: pack names (comma-separated), pack numbers (e.g. `1,3,5`), `all`, `defaults`, or blank — all install only the always-on packs.

The command ingests each chosen pack and runs one bulk re-embed pass at the end. **Expect 5–10 minutes** on a warm-cache iGPU for a moderate selection (e.g., core + engineering + nodejs + typescript = ~115 skills, ~700 fragments).

Non-interactive / scripted environments: pass `--packs <name1,name2,...>` (or `--packs all`) to skip the prompt. With no flag in non-TTY mode, only the always-on packs install. Unknown pack names in `--packs` cause the command to fail fast with the available pack list; pass `--ignore-unknown` to skip unrecognized names and continue with the known subset.

If the bulk re-embed fails partway (e.g., the embedding server crashes mid-run), the install state records what landed and the embed step is idempotent — just re-run `skillsmith reembed` to finish.

---

## Step 9: Write `.env`

> RUN
> ```bash
> skillsmith write-env --preset <chosen-preset>
> ```

(Substitute the preset name from step 4's `preset` field, e.g., `apple-silicon`.) The `.env` is written to `${XDG_CONFIG_HOME:-~/.config}/skillsmith/.env` with mode `0600` (owner read/write only).

If the user wants a non-default port (because 47950 is taken on their machine), pass `--port <n>`. Otherwise let it default to 47950.

---

## Step 10: Handoff harness selection

> ASK
>
> Ask the user which coding harness they're using. Read the list aloud:
> > "What harness will be calling the skill API?
> > 1. Claude Code
> > 2. Gemini CLI
> > 3. Cursor
> > 4. Continue.dev with a closed/cloud model (Anthropic, OpenAI)
> > 5. Continue.dev with a locally-hosted model
> > 6. OpenCode with a local LLM
> > 7. Aider with a local LLM
> > 8. Cline
> > 9. Other / I'll wire it manually
> > 10. I want the strict-tools MCP fallback for one of the above"
>
> Wait for the user's choice. Note: option 10 is a compound — if chosen, follow up with "which of options 1–8 should the MCP server be configured for?"

Record the harness choice. The CLI uses one of: `claude-code`, `gemini-cli`, `cursor`, `continue-closed`, `continue-local`, `opencode`, `aider`, `cline`, `manual`. For the strict-tools MCP fallback, pass `--mcp-fallback` with one of the supported harnesses (claude-code, cursor, continue-closed, continue-local).

---

## Step 11: Wire the harness

> RUN
> ```bash
> cd <user's repo> && skillsmith wire-harness --harness <chosen-harness>
> ```

(Substitute the harness key from step 10.) The shorter form is `skillsmith wire --harness <chosen>` — the verb auto-detects the harness from the cwd if you omit the flag.

**Auto-detection priority** (used when `--harness` is omitted; first match wins):
1. `.cursor/` or `.cursorrules` → `cursor`
2. `.continuerc.json` → `continue-local`
3. `.aider.conf.yml` → `aider`
4. `.opencode/` → `opencode`
5. `.clinerules` → `cline`
6. `GEMINI.md` → `gemini-cli`
7. `CLAUDE.md` → `claude-code`

A repo with multiple markers (e.g. both `.cursor/` and `CLAUDE.md`, common when more than one agent is wired to the project) will pick the higher-priority entry and print a `NOTE:` line so the user can pass `--harness <name>` to override. Tool-specific dotfiles outrank `CLAUDE.md` because the latter is shared by several agents and is a weaker signal.

The output lists which file(s) were modified and where the sentinel-bounded skillsmith block was injected. Tell the user:

> "I added a skillsmith integration block to **CLAUDE.md** in your project. The block is bounded by `<!-- BEGIN skillsmith install -->` / `<!-- END skillsmith install -->` markers — `skillsmith unwire` removes only what's between the markers, so your other content is safe.
>
> Repos are wired one-at-a-time. To wire another project, `cd` into it and run `skillsmith wire` again — Skillsmith state is user-scoped, so you don't need to re-do steps 1–8."

If the user picked `manual`, the output includes copy-pasteable instructions for the user to apply themselves. Read those to the user.

---

## Step 12: Verify

> RUN
> ```bash
> skillsmith verify
> ```

This runs 8 enumerated install-time checks (embedding endpoint reachable, returns 1024-dim, DuckDB present at the user-scope corpus dir, LadybugDB present, skill count meets minimum, harness config present, harness config URL matches, runtime port available).

When the service is running, the corpus checks (`duckdb_present`, `ladybug_present`, `skill_count_meets_minimum`) query `GET /diagnostics/runtime` instead of opening DB files directly — Kùzu's single-writer lock would otherwise make those checks fail spuriously while the service holds the corpus open. `runtime_port_available` accepts `"healthy"` (passes) and `"degraded"` (passes with warning) responses from `/health`.

If `all_checks_passed: true`, proceed to step 13.

If any check fails:
> RUN
> ```bash
> skillsmith doctor
> ```
>
> Read the doctor output to the user. Each failed check has an `error` and a `remediation`. Surface the remediation to the user and ask if they want to retry the failed step or get help.

---

## Step 13: Enable persistent service

> **Note:** If you ran `skillsmith setup`, this step was already prompted interactively as part of that command. Skip to Step 13 if `install-state.json` already contains a `service_mode` entry.

> ASK
> "Do you want Skillsmith to start automatically in the background, or will you start it manually each session?
>  1. Persistent — native service (systemd on Linux / launchd on macOS, starts at login)
>  2. Persistent — container (podman or docker compose, starts on demand)
>  3. Manual — I'll run `skillsmith serve` myself"

Then based on the answer:

> RUN
> ```bash
> # For native:
> skillsmith enable-service --mode native
>
> # For container:
> skillsmith enable-service --mode container
>
> # For manual:
> skillsmith enable-service --mode manual
> ```

The subcommand detects the available service manager (systemd/launchd) or container runtime (podman preferred, docker fallback), writes the appropriate unit/plist/compose invocation, starts the service, and polls `/health` for up to 30s to confirm startup. Radeon preset uses `compose.radeon.yaml` (skillsmith-only; LM Studio runs on the host). On success, the mode is recorded in `install-state.json`.

---

## Step 14: Start the service + first-run demo

Start the service in foreground (recommended — same idiom as `ollama serve`):

> RUN
> ```bash
> skillsmith serve
> ```

This sources `${XDG_CONFIG_HOME:-~/.config}/skillsmith/.env` into the process environment, then execs `uvicorn skillsmith.app:app` on the configured port. **Leave it running** in the terminal; open a new shell for the demo curl.

Alternatively, the user can manually run `uv run uvicorn skillsmith.app:app --host 127.0.0.1 --port 47950` from a terminal of their choice — `skillsmith serve` is just the convenience wrapper.

Wait 3 seconds for the service to start, then in another shell:

> RUN
> ```bash
> curl -s -X POST http://localhost:47950/compose \
>   -H 'Content-Type: application/json' \
>   -d '{"task": "write a failing pytest", "phase": "build"}'
> ```

Show the user the response. The `output` field contains concatenated raw skill fragments; `source_skills` lists which skills contributed. Tell the user:

> "The skill API is live. Returned guidance from these skills: [list]. The full text is what your harness will see when it queries this endpoint.
>
> **Try it now:** open your harness (Claude Code / Cursor / etc.) and ask: 'What skills do you have access to right now? Run `curl http://localhost:47950/health` to confirm.' If everything is wired correctly, your harness should respond with a list of skill capabilities pulled from the API."

---

## You're done

State summary:
- Service running at `http://localhost:<port>` (default 47950)
- Service mode recorded: `native` (systemd/launchd), `container` (podman/docker), or `manual` (`skillsmith serve`)
- Skill corpus seeded into `${XDG_DATA_HOME:-~/.local/share}/skillsmith/corpus/`
- Models pulled and on disk
- `.env` written to `${XDG_CONFIG_HOME:-~/.config}/skillsmith/.env`
- This repo's harness wired with sentinel-bounded injection
- All 8 verify checks passed

**To wire another repo to the same service:** `cd ~/dev/other-project && skillsmith wire`. No re-detect, no re-pull, no re-seed needed — the user-scope install serves every repo on this machine.

**To check status across all wired repos:** `skillsmith status` shows the user state, which repos are wired, the corpus location, and whether the service is reachable.

Operator commands the user can run later (these are NOT part of this runbook — they're for reference):

| Command | What it does |
|---|---|
| `skillsmith status` | Show user state + wired repos + service reachability |
| `skillsmith serve` | Start the service in foreground (terminal must stay open) |
| `skillsmith wire` | Wire the current repo (cwd) to the service |
| `skillsmith unwire` | Remove sentinels from the current repo only (keeps user state, `.env`, and corpus) |
| `skillsmith doctor` | Runtime health check on demand |
| `skillsmith update` | Migrate corpus in place after a version bump |
| `skillsmith install-pack <name>` | Add a published skill pack to the user corpus |
| `skillsmith reset-step <name>` | Clear a specific install step (escape hatch for changing config without full uninstall) |
| `skillsmith uninstall` | Full teardown — see below for exactly what's removed |

### Uninstall — what it removes

`skillsmith uninstall` is the one-shot teardown. By default:

- **Sentinel-bounded harness blocks** in *every* repo recorded in install-state.json (CLAUDE.md, GEMINI.md, .clinerules, .cursorrules, .cursor/rules/skillsmith.mdc, .opencode/system-prompt.md, .aider.conf.yml, etc.). The cross-repo walk happens before the CLI is removed; pass `--no-all-repos` to limit to cwd. Tampered blocks (sha256 mismatch — the user edited inside the sentinels) are skipped without `--force`.
- **MCP entries** for `skillsmith` from `~/.claude/mcp_servers.json`, the cwd repo's `.cursor/mcp.json`, and `.continuerc.json`. The files are deleted if `skillsmith` was their only entry.
- **Native service unit + companion ollama unit** on Linux (`~/.config/systemd/user/skillsmith.service`, `~/.config/systemd/user/ollama.service`, sanitized `skillsmith.env`). On macOS the launchd plist at `~/Library/LaunchAgents/ai.skillsmith.plist`.
- **Manual-mode skillsmith server** if it's still listening on the configured port (SIGTERM, escalating to SIGKILL after 10s).
- **User-scope state**: `${XDG_CONFIG_HOME}/skillsmith/.env`, `install-state.json`, the entire state directory.
- **Derivable artifacts**: `${XDG_DATA_HOME}/skillsmith/outputs/` (per-step JSON dumps including preflight) and `server.log`.
- **`uv tool uninstall skillsmith`** — removes the `skillsmith` CLI from `~/.local/bin`.

**Preserved by default**: the corpus DB at `${XDG_DATA_HOME}/skillsmith/corpus/`, pulled Ollama / FastFlowLM models (shared with other projects), the user's own non-skillsmith config.

**Flags**:
- `--remove-data` — also wipes the entire `${XDG_DATA_HOME}/skillsmith/` (corpus included). The post-test "get rid of everything" command.
- `--force` — remove sentinel blocks even when the inner content has been edited.
- `--no-all-repos` — only clean sentinels in cwd (legacy behavior; useful for partial cleanup).

**Full wipe one-liner** (for testers ready to reinstall from scratch):
```bash
skillsmith uninstall --remove-data
```
This used to require a manual `rm -rf ~/.local/share/skillsmith` afterwards — no longer.

---

## If you got stuck

If you (the LLM) hit an unexpected state at any step, **stop and tell the user**. Don't improvise around the runbook. The CLI is the source of truth — if it says a step failed, that step failed; don't assume.

Common stuck-states:
- The CLI prints a `WARNING: Found legacy per-repo state at <repo>/.skillsmith/install-state.json`. That's a Skillsmith install from before the v2 user-scope refactor. Either delete the legacy file or `mv` it to the user-scope location (the warning prints the exact command).
- The CLI exits 3 (schema mismatch). The user has a state file from a different version. Tell them to back it up and re-run install with a fresh state.
- The CLI exits 4 (already-completed). That step ran successfully before. Read the user-scope state file to see what's done; skip ahead. (`skillsmith status` shows this concisely.)
- A required external tool (Ollama, LM Studio) is missing. Tell the user the tool's install URL and wait for them to install it manually. Do NOT auto-execute install scripts.
- A port collision on 47950. Re-run `write-env` with `--port <n>` and re-run `wire-harness` so the harness config gets the new URL.
