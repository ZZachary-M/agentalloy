# Skillsmith — Install & Adoption Spec

Status: draft (rev 5 — corpus ships in-repo)
Owner: Nate
Last updated: 2026-04-26

## Companion documents

This file is the master design spec. Implementation contracts and operational details live alongside it:

- [`contracts.md`](./contracts.md) — JSON schemas for every CLI subcommand output, `install-state.json` schema, hardware-detect schema, model runner table, preset template format, enumerated `verify` and `doctor` checks
- [`harness-catalog.md`](./harness-catalog.md) — per-harness file paths, actual injection text, edge cases
- [`test-plan.md`](./test-plan.md) — per-platform acceptance criteria

The runbook the calling LLM reads top-to-bottom is `INSTALL.md` at the repo root (separate from this directory).

## CLI framework + entry point

- **Framework:** `argparse` (matches existing `skillsmith.ingest`, `skillsmith.bootstrap` pattern). No new dependency.
- **Entry point:** `python -m skillsmith.install <subcommand> [args]`. Single top-level dispatcher in `src/skillsmith/install/__main__.py`.
- **Subcommand modules:** one Python module per subcommand under `src/skillsmith/install/subcommands/`. Each exposes `add_parser(subparsers)` and `run(args) -> int`.
- **Output format:** all subcommands emit JSON to stdout on success (machine-readable for the runbook LLM); human-readable progress to stderr. Exit code 0 success, non-zero failure.

## Goal

A user points their LLM (cloud-hosted coding agent or local model) at the skillsmith GitHub repo and says "install this." The LLM clones the repo, follows the install runbook, runs a guided Q&A with the user, and lands the user in a working state with a pre-seeded corpus, a wired-up handoff harness, and a working demo — within minutes, with no manual config-editing.

Success criteria:
- Zero hand-edited config files
- Zero "why isn't this working" support questions on the happy path
- The user sees skills returned by their handoff agent inside the first install session
- Re-running install is safe (idempotent) and resumable on failure
- Partial-failure state is recoverable without a clean wipe

---

## Architecture: Hybrid Installer

The installer is split between a markdown runbook the calling LLM reads and a Python CLI the runbook tells the LLM to invoke.

**Why split:** LLMs are good at conversational Q&A and natural-language clarification. Python is good at deterministic validation, idempotent operations, and writing valid config files. Letting an LLM hand-write JSON config or skip a verification step is how installs silently break. Letting a CLI prompt loop run the Q&A loses the LLM's strength.

### Components

**`INSTALL.md`** — top-level runbook the calling LLM reads top-to-bottom. Orchestrates the install: tells the LLM when to run a CLI subcommand, when to ask the user a question, when to confirm a result, when to stop and wait. Source of truth for install steps.

**`skillsmith install` CLI** — idempotent subcommands the runbook invokes. Each subcommand is testable in isolation, validates its own preconditions, and is safe to re-run. The runbook does not write JSON or `.env` files directly — it tells the LLM to invoke the CLI to do it.

**`install-state.json`** — breadcrumb file at `<repo-root>/.skillsmith/install-state.json` (gitignored, same scope as `.env`). Each subcommand writes its completion + outputs here. Used by `doctor` to diagnose partial installs and by re-runs to skip completed steps. Repo-local so two clones (e.g. `~/dev/skillsmith` and `~/eval/skillsmith`) don't clobber each other's state. Schema is an internal CLI contract and not guaranteed stable across major versions.

### Subcommands

Subcommands are tagged by tier:

- **Runbook-tier** — invoked by the calling LLM during the happy-path install. The user never needs to know these names; they're the LLM's tools while walking through `INSTALL.md`.
- **Operator-tier** — invoked later by the user (or their LLM) for ongoing maintenance, recovery, or experimentation. Documented in `docs/operator.md`, not part of the install runbook.

| Tier | Subcommand | Purpose | Output |
|---|---|---|---|
| runbook | `detect` | Run platform-appropriate hardware detection | JSON: CPU, GPU, NPU, OS, RAM, disk |
| runbook | `recommend-host-targets --hardware <json>` | Given confirmed hardware, return valid host targets (dGPU/iGPU/CPU+RAM) with tradeoff notes and a single `recommended: true` flagged target | JSON: `[{target, available, recommended, reason, notes}]` |
| runbook | `recommend-models --hardware <json> --host <target>` | Given hardware + chosen host target, return valid embedding model options and the resolved preset name | JSON: `[{embed_model, embed_runner, preset, default}]` |
| runbook | `seed-corpus [--manifest <url>]` | Download + unpack pre-seeded corpus snapshot **including pre-computed embeddings**. Idempotent: skips if ladybug has ≥N skills at correct schema version. Default manifest URL: `<TBD: corpus release URL — fill in when repo path is finalized>` | JSON: skills loaded, schema version, manifest hash |
| runbook | `pull-models --runtime-embed X` | Idempotent model pulls (Ollama, LM Studio, etc.) | progress + final state |
| runbook | `write-env --preset <name> [--overrides ...] [--port <n>]` | Validate + write `.env` from the preset template. Templates values from Q&A answers, doesn't just copy the file. | path to written file |
| runbook | `verify` | Install-time smoke test (embed → retrieve → 1024-dim out, harness config readable) | JSON: pass/fail per check |
| runbook | `wire-harness --harness <name> [--mcp-fallback]` | Emit harness-specific integration with sentinel markers for clean removal later | path(s) to written files |
| operator | `doctor` | Runtime health check across all components, reads `install-state.json` to diagnose partial installs. Also auto-invoked by the runbook on `verify` failure. | JSON: per-component status + remediation hints |
| operator | `update` | Pull latest, run schema migrations in-place on existing corpus, re-pull model variants if defaults changed | summary of changes |
| operator | `uninstall [--keep-data]` | Remove harness wiring (sentinel-bounded), stop services, optionally preserve `data/` | confirmation |
| operator | `install-pack <pack-name>` | Pull a published skill pack into the corpus | summary of skills/fragments added |
| operator | `reset-step <name>` | Clear a step's entry from `install-state.json` so the next install run will re-execute it. Escape hatch for changing your mind on `write-env`, `wire-harness`, etc. without a full uninstall. | confirmation |

**`verify` vs `doctor`:** `verify` runs once at install time and checks the install completed correctly (a runbook gate). `doctor` runs on demand and checks runtime health — endpoint reachability, corpus presence, harness config validity, port availability. The runbook auto-invokes `doctor` if `verify` fails so the user gets remediation hints in the same session.

---

## Install Q&A Flow

Each step has a clear stop-and-confirm gate before proceeding. State is persisted to `install-state.json` after each successful step so re-runs skip completed work.

### 1. Pre-flight

LLM clones repo, runs `uv sync`. Verifies `uv` is present.

**`uv` bootstrap policy:** if `uv` is missing, the runbook **shows the install command to the user and waits for them to run it** — it does not auto-execute `curl | sh`. This keeps the human in the loop for the one non-reversible bootstrap action.

### 2. Hardware detection + confirm

- Runbook: tell the LLM to run `skillsmith install detect`.
- CLI runs platform-appropriate commands (`lscpu` / `nvidia-smi` / `system_profiler` / `wmic` / `sysctl`) and emits structured hardware JSON.
- LLM presents the result to the user in plain English.
- **User confirms or corrects.** Corrected JSON is what subsequent steps use.

### 3. Host target selection

- Runbook: `skillsmith install recommend-host-targets --hardware <json>` returns valid host targets for this hardware with tradeoff notes and one entry flagged `recommended: true` based on a fixed preference order (dGPU > iGPU > CPU+RAM).
- LLM presents options to user, leading with the recommended target and surfacing the others as alternatives.
- User picks one (defaults to recommended on enter). Choice is the input to step 4.

This step now has CLI backing (previously the LLM was eyeballing hardware JSON to offer host targets — that logic now lives in Python where it can be tested) and the recommendation is encoded in the CLI output rather than reconstructed by each LLM.

### 4. Model variant selection

- Runbook: `skillsmith install recommend-models --hardware <json> --host <target>` returns valid `{embed_model, embed_runner}` options for the chosen host target.
- The locked-in embedding model is `qwen3-embedding:0.6b` (1024-dim). The variant picker selects which *runner* for the user's host target: Ollama for cpu/apple-silicon/nvidia presets, LM Studio (Vulkan) for the radeon preset.
- User picks (defaults are typically fine).

### 5. Handoff harness selection

Two branches, with Continue.dev split based on which model the user runs through it:

- **Closed harness** — Claude Code, Gemini CLI, Cursor, Continue.dev with paid cloud models
- **Open harness with a local LLM** — OpenCode + Qwen, Aider with local model, Cline with local, Continue.dev with local LLM

The answer determines the integration path the next step writes.

### 6. Seed corpus

- Runbook: `skillsmith install seed-corpus`.
- The pre-seeded corpus **ships in the repo** at `data/skills.duck` and `data/ladybug`, so `seed-corpus` is now a **presence check + integrity verification**, not a download. It confirms the corpus files exist, the schema version matches what the code expects, and reports the skill/fragment counts. No network call.
- If the corpus files are missing (e.g., the user deleted `data/`), `seed-corpus` exits with a clear remediation hint pointing at `git checkout -- data/skills.duck data/ladybug` to restore them from the working tree.

### 7. Pull models

`skillsmith install pull-models --runtime-embed ... --ingest-model ...`. Idempotent — skips models already present.

### 8. Write `.env`

`skillsmith install write-env --preset <chosen> [--port <n>]`. Templates Q&A answers (host target URLs, model names, optional port override) into a fresh `.env`. Doesn't blindly copy a preset file.

The preset name is **resolved from `(hardware, host_target)`** by `recommend-models`, not picked separately by the user:

| `(hardware_arch, host_target)` | Preset |
|---|---|
| AMD x86_64 + dGPU | `radeon` |
| Apple Silicon + iGPU (Metal) | `apple-silicon` |
| NVIDIA + dGPU | `nvidia` |
| any + CPU+RAM or iGPU | `cpu` |

`recommend-models` returns the resolved preset in its output, and the runbook passes that preset name straight to `write-env`. The user never types a preset name.

### 9. Wire harness

The integration vector depends on the harness branch chosen in step 5:

| Harness | Default integration | Tokens (always-loaded) | Why default |
|---|---|---|---|
| Claude Code | `CLAUDE.md` instruction + Bash/curl, sentinel-bounded | 200–400 | No server process; multi-harness portable; aligns with native context-injection |
| Gemini CLI | `GEMINI.md` + shell tool, sentinel-bounded | 200–400 | Same |
| Cursor | `.cursorrules` block, sentinel-bounded | 200–400 | Same |
| Continue.dev (closed model) | `.continuerc.json` system message + custom command, sentinel-bounded | 200–400 | Continue.dev supports both system messages and MCP; system message is lower-overhead |
| Continue.dev (local model) | System-prompt snippet + curl pattern via custom command | ~50 | Local model gets the cheap path; harness just provides the integration shell |
| Open + local LLM (OpenCode + Qwen, Aider, Cline) | System-prompt snippet + curl pattern | ~50 | No harness markdown layer; one-line instruction to POST to `/compose` |
| **Any of the above, opt-in fallback** | Lean MCP server (one tool: `get_skill_for(task, phase)`) | 200–400 | Strict tool-call validation, restricted-permission environments, harness's per-tool approval UX |

**Sentinel-bounded injections:** every markdown injection is wrapped between unique markers like `<!-- BEGIN skillsmith install -->` / `<!-- END skillsmith install -->`. `uninstall` removes only what's between the sentinels, leaving user content intact. This is the contract that makes uninstall safe.

**Decision: markdown injection is the default for closed harnesses; MCP is the explicit opt-in fallback.** The kitchen-sink MCP pattern is rejected — token burner with no upside over markdown injection.

### 10. Verify

`skillsmith install verify`. Embeds a sample string, retrieves, returns 1024-dim → green/red. Each check is one line; failures include remediation hints. Fail-fast: if verify fails, the runbook stops and `doctor` is invoked.

### 11. First-run demo

Runbook's last action — closes the "did it work?" loop:

- LLM submits a sample `/compose` request with a real coding task
- LLM shows the user the returned fragments
- LLM outputs a copy-pasteable prompt for the user to try in their harness ("ask your LLM: 'what skills can you access?' — it should list X, Y, Z")

Adoption psychology: visible value within 60 seconds of install completing.

---

## Decisions (promoted from open questions)

### Corpus versioning (rev 5: ships in-repo)

**The pre-seeded corpus ships in the repo** at:

- `data/skills.duck` (~9 MB) — DuckDB with 1024-dim embeddings
- `data/ladybug` (~38 MB) — Kuzu skill graph

A fresh `git clone` produces a working corpus immediately. **No download, no manifest, no release artifact required for first install.** The corpus version is implicit — it's whatever the cloned commit shipped.

This reverses the original rev-2 design (download a release artifact at install time). Reasoning: the strongest adoption argument is "clone produces a working state," and saving 47 MB of repo size by keeping the corpus external doesn't outweigh the install-flow simplification.

**`seed-corpus` subcommand becomes a presence check.** It verifies:
1. `data/skills.duck` exists and is readable
2. `data/ladybug` exists and is readable
3. The schema version embedded in the corpus matches what the code expects
4. Skill count meets the minimum threshold (~50 skills)

If anything is missing, the remediation hint is `git checkout -- data/skills.duck data/ladybug` (the user accidentally deleted the files but they're still in the working tree's HEAD).

**Update path:** `update` runs schema migrations **in-place on the existing corpus**. Because the corpus tracks the code, schema migrations ship with the same `git pull` that introduced the schema change. No separate version-tracking is needed.

**Optional future:** publish corpus snapshots as GitHub release artifacts for `skillsmith install update --to-release X` use cases (e.g., a user wants to upgrade only the corpus without pulling code changes). Out of scope for v1.

### Partial-failure state tracking

Every subcommand writes its completion + outputs to `<repo-root>/.skillsmith/install-state.json` on success (gitignored, repo-local). The file structure:

```json
{
  "install_started_at": "2026-04-26T14:22:00Z",
  "schema_version": 3,
  "completed_steps": [
    {"step": "detect", "completed_at": "...", "output": {...}},
    {"step": "recommend-host-targets", "completed_at": "...", "selected": "iGPU"},
    ...
  ],
  "harness": "claude-code",
  "harness_files_written": [
    {"path": "/home/user/CLAUDE.md", "sentinel": "skillsmith install"}
  ],
  "models_pulled": ["qwen3-embedding:0.6b"],
  "env_path": "/home/user/dev/skillsmith/.env",
  "last_verify_passed_at": "2026-04-26T14:25:30Z"
}
```

Re-running install reads this file and skips completed steps. `doctor` reads it to diagnose what's missing or inconsistent. `uninstall` reads `harness_files_written` to know exactly which files to clean and which sentinels bound the injections. `reset-step <name>` (operator-tier) clears a specific entry so the next install run will re-execute that step — escape hatch for changing your mind on `write-env`, `wire-harness`, etc. without a full uninstall.

### `write-env` mechanism

`write-env` **templates** values into `.env` from a preset template, it does not copy the preset file blindly. The CLI knows about a fixed set of preset names (`cpu`, `apple-silicon`, `nvidia`, `radeon`) and a fixed set of overridable values (URLs, model names, port). User-supplied overrides come from `--overrides key=value` or are inferred from the Q&A answers stored in `install-state.json`.

This means existing `.env.cpu`, `.env.apple-silicon`, etc. files in the repo become **template references** for documentation, not the literal source of `.env` — the CLI owns the schema.

---

## Adoption-ease items (locked-in)

### Must-haves (top tier)

1. **Pre-seeded corpus.** Now backed by `seed-corpus` subcommand and the corpus-versioning decision above. `data/` stays gitignored; install pulls the matching release artifact.

2. **`skillsmith doctor`.** Runtime health check (distinct from `verify`). Reads `install-state.json` to know what should exist; checks: embedding endpoint reachable + returns 1024-dim, DuckDB exists with expected skill count, harness config file present and contains the sentinel block, runtime cache loaded, configured port reachable. Cuts support cost dramatically.

3. **First-run demo / verification step.** Step 11 of Q&A above. Sends a real `/compose` request, shows fragments, gives the user a one-liner to test in their harness.

4. **Uninstaller.** `uninstall [--keep-data]` removes harness wiring **using the sentinels recorded in `install-state.json`** so user content is never clobbered. Stops services. Prompts about preserving `data/`. "I'll try this" gets much easier when "I'll undo it" is one safe command.

### Should-haves (mid tier)

5. **Containerized install target.** Podman / Docker Compose that bundles skillsmith + Ollama + the seed corpus. Project preference is Podman, but Compose-compatible files so both work. Captures evaluators / CI users who won't install Python on the host.

6. **Update path.** `update` pulls main, runs DuckDB / Ladybug schema migrations **in-place on the existing corpus**, re-pulls model variants if defaults changed. Does not depend on a fresh release artifact existing for the new schema — migrations ship with the code.

7. **Skill packs.** `install-pack <name>` pulls a published skill bundle into the corpus. Future surface for community contribution.

### Nice-to-have

8. **Failure-mode handbook in `INSTALL.md`.** Common failures (Ollama not running, port collision, model download timeout) mapped to recovery commands. `doctor` cross-references it.

9. **Profiles.** Named `.env` snapshots so a user can swap between cloud vs local, NVIDIA-laptop vs Strix-desktop. `skillsmith install profile use <name>`.

### Skipped

- ~~Corpus browser CLI~~ — not in scope.

---

## Cross-cutting concerns

### Port configurability

The default API port is 8000, but it can be overridden with `--port <n>` on `write-env`. The chosen port is recorded in `install-state.json` and read by `wire-harness` so the injected curl/MCP config points at the right URL. `doctor` checks port availability before writing anything and surfaces a collision early.

### Sentinel-based injection contract

Every harness file we write to has a unique sentinel pair:

```
<!-- BEGIN skillsmith install -->
... our content ...
<!-- END skillsmith install -->
```

`wire-harness` always writes the full block between sentinels (idempotent: replaces existing block on re-run). `uninstall` removes only what's between sentinels. This is the only thing that makes uninstall safe across user-edited harness configs.

### Continue.dev branching

Continue.dev is unusual because it can run either a closed model (Anthropic, OpenAI) or a local model. We resolve this in step 5 by asking the user which model they're running through Continue.dev, and pick the integration vector accordingly:

- Closed model in Continue.dev → markdown-style injection via system message in `.continuerc.json`
- Local model in Continue.dev → cheap sysprompt snippet via custom command

Same harness, two integration vectors based on what's downstream of it.

### Harness extensibility

The v1 supported harness list is Claude Code, Gemini CLI, Cursor, Continue.dev, OpenCode, Aider, Cline. **Other harnesses on the radar but not v1:** Windsurf (Codeium), GitHub Copilot agent mode, OpenAI Codex CLI, Zed AI. The sentinel-based injection architecture is intentionally extensible — adding a new harness is a `wire-harness` branch that emits the right config file with the standard `<!-- BEGIN skillsmith install -->` markers, plus a row in step 9's table. No core architectural change required. Tracking these as future work, not blockers for v1.

---

## Decision: `uninstall --keep-data` default

The default behavior of `uninstall` is to **preserve `data/`** (the seeded corpus and any subsequent ingestions). The `--keep-data` flag is therefore a **no-op explicit opt-in for the default**, kept for clarity. To remove data, use `uninstall --remove-data`.

Rationale: re-downloading the seed corpus on reinstall is slow (8+ seconds plus network). Preserving by default lowers reinstall friction; users who want a clean wipe state it explicitly.

---

## Open questions

- **Skill pack registry shape.** When `install-pack frontend` runs, where does it pull from? Public GitHub repo per pack? A central registry? TBD; not in scope for v1 install but the install architecture should not foreclose it.
- **Harness auto-detection.** Should the installer try to *detect* the calling harness (look for `.claude/`, `~/.gemini`, `.continuerc.json`) and pre-fill the answer to the harness Q? Probably yes for v2; v1 just asks.
- **Telemetry posture.** Default off; opt-in for "share install success" beacon. Needs explicit design before any phone-home behavior.
- **Multi-host installs.** A user might want `skillsmith` on a workstation but their harness on a laptop. Out of scope for v1 (single-host assumed) but the URL configurability already handles the simplest cross-host case.
- **OpenCode config path verification.** The harness catalog's OpenCode entry is provisional. Verify against current OpenCode docs before implementing that branch.

---

## Non-goals (for v1 install)

- GUI installer
- Web dashboard for managing the corpus
- Per-user / per-workspace install (single-user, single-workspace assumed)
- Cloud-hosted skillsmith as a service (out of scope; product is local-first)
- Auto-detection of the calling harness (deferred to v2)

---

## Implementation ordering (rough)

1. Stub the `skillsmith install` CLI with all subcommands as no-ops returning the expected JSON shape. Lock down the contract. Define `install-state.json` schema.
2. Implement `detect`, `recommend-host-targets`, `recommend-models`, `write-env`, `verify` (the deterministic core).
3. Build the seeded-corpus release artifact pipeline + implement `seed-corpus`.
4. Author `INSTALL.md` runbook against the implemented CLI. Manual walk-through with Claude Code on the dev workstation.
5. Implement `pull-models` (idempotent Ollama pulls; LM Studio requires manual GUI download).
6. Implement `wire-harness` for closed harnesses (markdown-injection variant with sentinels).
7. Implement `wire-harness` for open harness (sysprompt snippet variant).
8. Implement `doctor`, `uninstall`.
9. Implement `update`, `install-pack`.
10. Containerized install target.
11. MCP fallback variant of `wire-harness`.

Each step is shippable on its own. The install can be limited to fewer harnesses in early versions and expand later.
