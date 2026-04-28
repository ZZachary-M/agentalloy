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

If `uv` is missing, **stop and ask the user to install it** with the official command at https://docs.astral.sh/uv/getting-started/installation/. Do not auto-execute the install script — that's a non-reversible action that requires the human in the loop.

If step 4 picks **Ollama** as the runner and the `ollama` binary is missing (or `localhost:11434` is unreachable), step 5's pull will fail with a connection error. Same rule as `uv`: **stop and ask the user to install Ollama**. Do not auto-execute. Tell them:

- **Linux:** `curl -fsSL https://ollama.com/install.sh | sh`
- **macOS:** `brew install ollama`, or download from https://ollama.com/download/mac
- **Windows / other:** see https://ollama.com/download

After install, the user must have `ollama serve` running (the official installer sets this up as a service on macOS/Windows; on Linux the install script registers a systemd unit). Confirm with `curl -s http://localhost:11434/api/tags` before re-running step 5.

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

Verify it landed:

> RUN
> ```bash
> skillsmith --help
> ```

If the command is not found, `~/.local/bin` is not in PATH. Fix:

> ASK
>
> Tell the user:
> > "`~/.local/bin` is not in your PATH. Add this line to your shell profile (`~/.bashrc`, `~/.zshrc`, etc.) and restart the shell:
> >
> > ```bash
> > export PATH="$HOME/.local/bin:$PATH"
> > ```
> >
> > Once done, confirm with `which skillsmith`."
>
> Wait for confirmation before continuing.

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

---

## Step 6: Initialize the corpus directory

> RUN
> ```bash
> skillsmith seed-corpus
> ```

This creates the user-scoped corpus directory at `${XDG_DATA_HOME:-~/.local/share}/skillsmith/corpus/` and initializes empty LadybugDB + DuckDB stores. The wheel no longer ships pre-built skills — Step 7 below populates the corpus from packs the user picks.

---

## Step 7: Pick and install skill packs

> RUN
> ```bash
> skillsmith install-packs
> ```

The user is shown a list of available packs (each with description + skill count) and asked to pick which ones to install. Two packs (`core`, `engineering`) are always installed automatically.

> ASK
>
> Tell the user:
> > "Skillsmith's corpus is split into packs. You opt in to the ones that match your stack. `core` and `engineering` install automatically. The most common picks for backend work: `nodejs`, `typescript`, plus your framework (e.g., `nestjs`, `fastify`). For agentic dev, add `agents`. Pick now or accept defaults — you can install more packs later with `skillsmith install-pack <name>`."
>
> Read the available packs from the CLI's interactive prompt. Wait for the user's selection.

The command ingests each chosen pack and runs one bulk re-embed pass at the end. **Expect 5–10 minutes** on a warm-cache iGPU for a moderate selection (e.g., core + engineering + nodejs + typescript = ~115 skills, ~700 fragments).

Non-interactive / scripted environments: pass `--packs <name1,name2,...>` (or `--packs all`) to skip the prompt. With no flag in non-TTY mode, only the always-on packs install.

If the bulk re-embed fails partway (e.g., LM Studio crashes mid-run), the install state records what landed and the embed step is idempotent — just re-run `skillsmith reembed` to finish.

---

## Step 8: Write `.env`

> RUN
> ```bash
> skillsmith write-env --preset <chosen-preset>
> ```

(Substitute the preset name from step 4's `preset` field, e.g., `apple-silicon`.) The `.env` is written to `${XDG_CONFIG_HOME:-~/.config}/skillsmith/.env` with mode `0600` (owner read/write only).

If the user wants a non-default port (because 47950 is taken on their machine), pass `--port <n>`. Otherwise let it default to 47950.

---

## Step 9: Handoff harness selection

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

## Step 10: Wire the harness

> RUN
> ```bash
> cd <user's repo> && skillsmith wire-harness --harness <chosen-harness>
> ```

(Substitute the harness key from step 8.) The shorter form is `skillsmith wire --harness <chosen>` — the verb auto-detects the harness from the cwd if you omit the flag.

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
> Repos are wired one-at-a-time. To wire another project, `cd` into it and run `skillsmith wire` again — Skillsmith state is user-scoped, so you don't need to re-do steps 1–7."

If the user picked `manual`, the output includes copy-pasteable instructions for the user to apply themselves. Read those to the user.

---

## Step 11: Verify

> RUN
> ```bash
> skillsmith verify
> ```

This runs 8 enumerated install-time checks (embedding endpoint reachable, returns 1024-dim, DuckDB present at the user-scope corpus dir, harness config present, port available, etc.).

If `all_checks_passed: true`, proceed to step 11.

If any check fails:
> RUN
> ```bash
> skillsmith doctor
> ```
>
> Read the doctor output to the user. Each failed check has an `error` and a `remediation`. Surface the remediation to the user and ask if they want to retry the failed step or get help.

---

## Step 12: Enable persistent service

> **Note:** If you ran `skillsmith setup`, this step was already prompted interactively as part of that command. Skip to Step 12 if `install-state.json` already contains a `service_mode` entry.

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

## Step 13: Start the service + first-run demo

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
| `skillsmith uninstall` | Full teardown — removes user state, `.env`, corpus, AND sentinels in cwd repo |

---

## If you got stuck

If you (the LLM) hit an unexpected state at any step, **stop and tell the user**. Don't improvise around the runbook. The CLI is the source of truth — if it says a step failed, that step failed; don't assume.

Common stuck-states:
- The CLI prints a `WARNING: Found legacy per-repo state at <repo>/.skillsmith/install-state.json`. That's a Skillsmith install from before the v2 user-scope refactor. Either delete the legacy file or `mv` it to the user-scope location (the warning prints the exact command).
- The CLI exits 3 (schema mismatch). The user has a state file from a different version. Tell them to back it up and re-run install with a fresh state.
- The CLI exits 4 (already-completed). That step ran successfully before. Read the user-scope state file to see what's done; skip ahead. (`skillsmith status` shows this concisely.)
- A required external tool (Ollama, LM Studio) is missing. Tell the user the tool's install URL and wait for them to install it manually. Do NOT auto-execute install scripts.
- A port collision on 47950. Re-run `write-env` with `--port <n>` and re-run `wire-harness` so the harness config gets the new URL.
