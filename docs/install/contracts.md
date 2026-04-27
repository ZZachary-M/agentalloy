# Install — Contracts

Companion to [`spec.md`](./spec.md). Authoritative for every CLI subcommand's input/output shape, the install-state file, hardware-detect normalization, the model-runner table, preset template format, and the enumerated `verify` / `doctor` checks.

All JSON examples are **canonical**. An implementer should treat these as the source of truth and the prose in `spec.md` as commentary.

## Conventions

- **All subcommands write JSON to stdout** on success, human progress to stderr.
- **Exit codes:** `0` success, `1` user-correctable failure (precondition not met), `2` system failure (unexpected exception), `3` schema-version mismatch, `4` already-completed (idempotent skip with no-op).
- **Schema version**: every output JSON includes a top-level `schema_version: int` field. Bumped when the output shape changes incompatibly.
- **Timestamps**: ISO-8601 UTC (`2026-04-26T14:22:00Z`).
- **Paths**: absolute, POSIX-style. Windows paths normalized to forward-slashes in JSON output.

## User-scoped layout (schema v2)

Skillsmith state is **user-scoped**, not per-repo, so a single install can serve every project the user opens.

| Concern | Path |
|---|---|
| Install state | `${XDG_CONFIG_HOME:-~/.config}/skillsmith/install-state.json` |
| `.env` (mode `0600`) | `${XDG_CONFIG_HOME:-~/.config}/skillsmith/.env` |
| Subcommand outputs | `${XDG_DATA_HOME:-~/.local/share}/skillsmith/outputs/` |
| Corpus (writable) | `${XDG_DATA_HOME:-~/.local/share}/skillsmith/corpus/` |
| Bundled corpus (read-only) | `<wheel>/skillsmith/_corpus/` (copied to user dir on first `seed-corpus`) |

Repos contain only sentinel-bounded blocks injected into agent config files (`CLAUDE.md`, `.cursor/rules/skillsmith.mdc`, etc.). The list of those files is recorded in `harness_files_written` in the user-scope state. There is no per-repo state directory.

---

## `install-state.json`

Path: `${XDG_CONFIG_HOME:-~/.config}/skillsmith/install-state.json`. Created on first subcommand run.

```json
{
  "schema_version": 2,
  "install_started_at": "2026-04-26T14:22:00Z",
  "completed_steps": [
    {
      "step": "detect",
      "completed_at": "2026-04-26T14:22:05Z",
      "output_digest": "sha256:abcd...",
      "output_path": "/home/user/.local/share/skillsmith/outputs/detect.json"
    },
    {
      "step": "recommend-host-targets",
      "completed_at": "2026-04-26T14:22:30Z",
      "selected": "iGPU"
    },
    {
      "step": "recommend-models",
      "completed_at": "2026-04-26T14:22:45Z",
      "selected": {
        "preset": "apple-silicon",
        "embed_model": "qwen3-embedding:0.6b",
        "embed_runner": "ollama"
      }
    },
    {
      "step": "seed-corpus",
      "completed_at": "2026-04-26T14:23:30Z",
      "skill_count": 153,
      "fragment_count": 1655
    },
    {
      "step": "pull-models",
      "completed_at": "2026-04-26T14:24:00Z",
      "models_pulled": ["ollama:qwen3-embedding:0.6b"]
    },
    {
      "step": "write-env",
      "completed_at": "2026-04-26T14:24:10Z",
      "env_path": "/home/user/.config/skillsmith/.env",
      "port": 8000
    },
    {
      "step": "wire-harness",
      "completed_at": "2026-04-26T14:24:30Z"
    },
    {
      "step": "verify",
      "completed_at": "2026-04-26T14:25:00Z",
      "all_checks_passed": true
    }
  ],
  "harness_files_written": [
    {
      "path": "/home/user/dev/project-a/CLAUDE.md",
      "harness": "claude-code",
      "repo_root": "/home/user/dev/project-a",
      "action": "injected_block",
      "sentinel_begin": "<!-- BEGIN skillsmith install -->",
      "sentinel_end": "<!-- END skillsmith install -->",
      "content_sha256": "sha256:..."
    },
    {
      "path": "/home/user/dev/project-b/.cursor/rules/skillsmith.mdc",
      "harness": "cursor",
      "repo_root": "/home/user/dev/project-b",
      "action": "wrote_new_file",
      "content_sha256": "sha256:..."
    }
  ],
  "models_pulled": ["ollama:qwen3-embedding:0.6b"],
  "env_path": "/home/user/.config/skillsmith/.env",
  "port": 8000,
  "last_verify_passed_at": "2026-04-26T14:25:00Z"
}
```

**Field rules:**
- `completed_steps` is append-only within an install run. `reset-step <name>` removes the named entry (and any later entries that depend on it).
- `output_path` is set for steps with large outputs (>4KB JSON); inline `output` for small ones. Implementer's choice for cutoff but document it.
- `harness_files_written` is the only thing `uninstall` / `unwire` consult to remove injections. Each entry carries its own `harness` and `repo_root` so the same state file can describe multiple wired projects. The cwd-derived repo root (NOT the entry's `repo_root`) is the trusted bound for containment checks; entries belonging to other repos are skipped at the current invocation. The basename / suffix of `path` must match a known harness target (`CLAUDE.md`, `GEMINI.md`, `.cursor/rules/skillsmith.mdc`, etc.) — anything else is rejected as tampered state.
- `models_pulled` entries are `<runner>:<model>` strings (e.g. `"ollama:qwen3-embedding:0.6b"`).
- `port` is validated as an int in `[1, 65535]`. Non-int / out-of-range values cause SystemExit(2).

**Schema migrations of the state file:**
- v0 → v1: backfilled missing fields (initial release).
- v1 → v2: state moved from per-repo to user-scope. Top-level `harness` field dropped; each `harness_files_written[]` entry now carries its own `harness` (inherited from the legacy top-level value). Top-level `repo_root` dropped; each entry inherits the legacy value.
- Newer-than-CLI versions raise SystemExit(3) with a "update skillsmith" message.
- A legacy v1 state file at `<repo>/.skillsmith/install-state.json` is detected on first user-scope load and printed as a stderr warning with a one-line `mv` migration hint.

---

## CLI verb composition

The 13 step subcommands above are the building blocks. The 5 user-facing **verbs** below compose them — they're what most users actually run. All verbs and steps are dispatched by the same `python -m skillsmith.install <name>` CLI; the `skillsmith` console script (registered via `[project.scripts]`) is just a shorter alias.

| Verb | Composes | Purpose |
|---|---|---|
| `setup` | detect → recommend-host-targets → recommend-models → pull-models → seed-corpus → write-env | One-shot user-scope install. Stops at the first non-zero exit (use `--continue-on-error` to attempt every step). Emits a top-level summary JSON to `${XDG_DATA_HOME}/skillsmith/outputs/setup.json`. |
| `wire` | wire-harness | Per-repo. Auto-detects the harness from cwd markers (`.cursor/`, `CLAUDE.md`, `GEMINI.md`, etc.). Reads port from user state. `--harness <name>` overrides detection; `--port <n>` overrides state. |
| `unwire` | uninstall (cwd-only, no `--remove-data`) | Per-repo. Removes sentinel blocks for entries whose `repo_root` matches cwd; entries from other repos surface as `different repo` warnings. Does NOT touch user state, `.env`, or the corpus. |
| `serve` | (uvicorn) | Sources `${XDG_CONFIG_HOME}/skillsmith/.env` into the process environment (process-env values take precedence) then `os.execvp`s `python -m uvicorn skillsmith.app:app` on the configured port. Foreground; same idiom as `ollama serve`. |
| `status` | (read-only) | Snapshot: completed user-scope steps, wired repos grouped by `repo_root`, corpus presence at user data dir, service reachability via TCP connect to `127.0.0.1:<port>`. Never mutates state. |

The verbs are thin composers — they don't implement new behavior, they just route arguments and read intermediate output files between the underlying steps. Operators who need flag overrides on a specific step should run that step standalone.

---

## `detect`

**Input:** none.

**Output:**

```json
{
  "schema_version": 1,
  "os": {
    "kind": "linux",
    "distro": "ubuntu",
    "version": "24.04",
    "kernel": "6.17.0-1017-oem",
    "arch": "x86_64"
  },
  "cpu": {
    "vendor": "amd",
    "model": "AMD Ryzen AI 9 HX 370",
    "cores_physical": 12,
    "cores_logical": 24,
    "max_freq_mhz": 5100
  },
  "memory_gb": 64,
  "disk_free_gb": 850,
  "gpu": {
    "discrete": [],
    "integrated": [
      {"vendor": "amd", "model": "Radeon 890M", "vram_gb": 8}
    ]
  },
  "npu": {
    "present": true,
    "vendor": "amd",
    "model": "AMD XDNA NPU"
  },
  "metal": false,
  "cuda": null,
  "rocm": false
}
```

**`os.kind` values:** `linux` | `macos` | `windows`.

**Per-OS detection commands** (the implementer's responsibility to invoke and normalize):

| Field | Linux | macOS | Windows |
|---|---|---|---|
| `os.distro`/`os.version` | `lsb_release -a` or `/etc/os-release` | `sw_vers` | `Get-CimInstance Win32_OperatingSystem` |
| `os.kernel` | `uname -r` | `uname -r` | `[System.Environment]::OSVersion.Version` |
| `os.arch` | `uname -m` | `uname -m` | `$env:PROCESSOR_ARCHITECTURE` |
| `cpu.*` | `lscpu` + `/proc/cpuinfo` | `sysctl -a \| grep machdep.cpu` | `Get-CimInstance Win32_Processor` |
| `memory_gb` | `/proc/meminfo` | `sysctl hw.memsize` | `Get-CimInstance Win32_ComputerSystem` |
| `disk_free_gb` | `df -BG /` | `df -g /` | `Get-PSDrive C` |
| `gpu.discrete` | `nvidia-smi -L`, `lspci \| grep -i vga`, `rocm-smi` | `system_profiler SPDisplaysDataType` | `Get-CimInstance Win32_VideoController` |
| `gpu.integrated` | `lspci \| grep -i 'vga\|3d'` | same as above | same as above |
| `npu` | `lspci \| grep -i 'npu\|neural'` + AMD XDNA driver check via `/sys/class/accel` | `system_profiler` + Apple Neural Engine check via `ioreg -l` | `Get-CimInstance Win32_PnPEntity \| ?{$_.Name -match "NPU"}` |
| `metal` (bool) | always false | `system_profiler SPDisplaysDataType` shows Metal | always false |
| `cuda` (string\|null) | `nvidia-smi --query-gpu=driver_version --format=csv` → driver version | null | `nvidia-smi` if installed |
| `rocm` (bool) | `rocm-smi --version` exit 0 | false | false (rare) |

If a detection command isn't available (`nvidia-smi` not installed), the field is `null` or `false` — never an error. The runbook surfaces "NVIDIA GPU detected but `nvidia-smi` not in PATH — driver missing?" only when both signals point at NVIDIA hardware without driver tooling.

**User confirm step:** the runbook presents this JSON in plain English to the user. If user corrects, the corrected JSON replaces the detect output as the input to subsequent steps.

---

## `recommend-host-targets`

**Input:** `--hardware <path-to-detect-json>`.

**Output:**

```json
{
  "schema_version": 1,
  "targets": [
    {
      "target": "dGPU",
      "available": false,
      "recommended": false,
      "reason": "No discrete GPU detected",
      "notes": null
    },
    {
      "target": "iGPU",
      "available": true,
      "recommended": true,
      "reason": "Radeon 890M with 8 GB shared VRAM",
      "notes": "Works for embedding. Shared with display compositor — may lag on heavy GPU load."
    },
    {
      "target": "CPU+RAM",
      "available": true,
      "recommended": false,
      "reason": "Always available; 64 GB RAM provides headroom",
      "notes": "Slower than GPU; acceptable for runtime path (<200ms embed)."
    }
  ]
}
```

**Recommendation order** (dGPU > iGPU > CPU+RAM): `recommended: true` is set on the first available target in that order. Exactly one target has `recommended: true`.

**`target` values:** `dGPU` | `iGPU` | `CPU+RAM`.

---

## `recommend-models`

**Input:** `--hardware <path>` `--host <target>`.

**Output:**

```json
{
  "schema_version": 1,
  "host_target": "iGPU",
  "preset": "apple-silicon",
  "options": [
    {
      "default": true,
      "embed_model": "qwen3-embedding:0.6b",
      "embed_runner": "ollama",
      "embed_runner_install_hint": "ollama is installed; will run `ollama pull qwen3-embedding:0.6b`"
    }
  ],
  "preset_resolution_table": {
    "(amd-x86_64, dGPU)": "radeon",
    "(apple-silicon, iGPU)": "apple-silicon",
    "(nvidia, dGPU)": "nvidia",
    "(any, CPU+RAM)": "cpu"
  }
}
```

**`preset` is the resolved preset name** for `(hardware, host_target)`. Values: `cpu` | `apple-silicon` | `nvidia` | `radeon`.

**`embed_runner` values:** `ollama` | `lm-studio` | `vllm` | `mlx`.

The `*_install_hint` field is human-readable text the runbook surfaces if the runner isn't installed.

---

## Model runner table

Authoritative for `pull-models`. Each runner has its own pull command, install URL, and host-target compatibility.

| Runner | Install URL | Pull command | Cross-platform | Auto-pull supported | Host targets |
|---|---|---|---|---|---|
| `ollama` | https://ollama.com | `ollama pull <model>` | Linux, macOS, Windows | yes | CPU+RAM, iGPU (Apple Metal), dGPU (NVIDIA CUDA) |
| `lm-studio` | https://lmstudio.ai | (no CLI pull — GUI only) | Linux, macOS, Windows | **no — manual user step** | iGPU (Metal, Vulkan), dGPU (CUDA, Vulkan) |
| `vllm` | `pip install vllm` | (loads on `vllm serve`) | Linux primarily | partial — runtime download | dGPU (NVIDIA only) |
| `mlx` | `pip install mlx-lm` | `mlx_lm.convert` (manual) | macOS only | partial | iGPU (Apple Metal) |

**Manual-pull runners (`lmstudio`, `vllm`, `mlx`):** when these are selected, `pull-models` does NOT attempt to pull. It emits a `manual_steps_required` array in its output with copy-pasteable instructions for the runbook to surface to the user. The runbook stops and waits for confirmation before proceeding.

**`pull-models` output:**

```json
{
  "schema_version": 1,
  "auto_pulled": [
    {"runner": "ollama", "model": "qwen3-embedding:0.6b", "size_mb": 622, "duration_ms": 14200}
  ],
  "manual_steps_required": [
    {
      "runner": "lmstudio",
      "model": "qwen/qwen3.6-35b-a3b",
      "instruction": "Open LM Studio, search for 'qwen/qwen3.6-35b-a3b', click Download. Confirm when complete."
    }
  ],
  "skipped_already_present": []
}
```

---

## `seed-corpus` (rev 5: presence check, no download)

**Input:** none.

**Output:**

```json
{
  "schema_version": 1,
  "action": "verified_present",
  "corpus_path": "/home/user/.local/share/skillsmith/corpus",
  "corpus_schema_version": 3,
  "skill_count": 153,
  "fragment_count": 1655,
  "embedding_model": "qwen3-embedding:0.6b",
  "embedding_dim": 1024,
  "duration_ms": 80
}
```

**`action` values:** `verified_present` | `seeded` | `missing_files` | `schema_mismatch`. `seeded` is returned on the first run (when the bundled corpus was just copied into the user data dir); subsequent runs return `verified_present`.

**Behavior:**

The corpus ships **inside the wheel** as package data at `skillsmith/_corpus/skills.duck` and `skillsmith/_corpus/ladybug`. On first run, `seed-corpus` copies it (atomically, via `.part` siblings + `os.replace`) into the user data dir at `${XDG_DATA_HOME:-~/.local/share}/skillsmith/corpus/` — that's the writable copy `install-pack` augments. Subsequent runs just verify the user copy.

1. Resolve `bundled_corpus_dir()` via `importlib.resources` (sentinel-checked: `skills.duck` must exist inside, otherwise reject).
2. If `${user_corpus}/skills.duck` AND `${user_corpus}/ladybug` are both present, skip the seed.
3. Otherwise atomically copy each missing file from the bundled location to the user location.
4. Verify the user-scope `skills.duck` is a readable DuckDB file. On miss → `action: missing_files`, exit 1, remediation: reinstall skillsmith.
5. Verify `${user_corpus}/ladybug` is a readable Kuzu file.
6. Read the corpus's embedded `schema_version` and compare to the code's expected version. On mismatch → `action: schema_mismatch`, exit 3, remediation: `python -m skillsmith.install update`.
7. Read `skill_count` from DuckDB. Require ≥ `MIN_SKILL_COUNT` (default 50). On under-count → `action: missing_files`, exit 1.
8. Return the metadata.

No network call. No manifest URL. No tarball download. (`install-pack` is a separate subcommand for adding *additional* skills to the user corpus from a published manifest.)

Embeddings are pre-computed in the shipped DuckDB; **no `reembed` is needed after install**.

---

## `write-env`

**Input:** `--preset <name>` `[--port <n>]` `[--overrides KEY=VALUE [KEY=VALUE ...]]`.

**Output:**

```json
{
  "schema_version": 1,
  "env_path": "/home/user/.config/skillsmith/.env",
  "preset": "apple-silicon",
  "port": 8000,
  "values_written": {
    "RUNTIME_EMBED_BASE_URL": "http://localhost:11434",
    "RUNTIME_EMBEDDING_MODEL": "qwen3-embedding:0.6b",
    "DEDUP_HARD_THRESHOLD": "0.92",
    "DEDUP_SOFT_THRESHOLD": "0.80",
    "BOUNCE_BUDGET": "3",
    "LOG_LEVEL": "INFO"
  }
}
```

`.env` is written to `${XDG_CONFIG_HOME:-~/.config}/skillsmith/.env` with mode `0600` (owner-only) on POSIX. `DUCKDB_PATH` and `LADYBUG_DB_PATH` are intentionally **not** in the preset — they're computed at runtime from the user corpus dir (`${XDG_DATA_HOME:-~/.local/share}/skillsmith/corpus/`).

**Preset templates** live in `src/skillsmith/install/presets/<name>.yaml`. Format:

```yaml
preset: apple-silicon
description: "Apple Silicon (M1/M2/M3/M4) with Metal acceleration via Ollama"
defaults:
  RUNTIME_EMBED_BASE_URL: "http://localhost:11434"
  RUNTIME_EMBEDDING_MODEL: "qwen3-embedding:0.6b"
  DEDUP_HARD_THRESHOLD: "0.92"
  DEDUP_SOFT_THRESHOLD: "0.80"
  BOUNCE_BUDGET: "3"
  LOG_LEVEL: "INFO"
```

**Port handling.** Preset URLs reference fixed *runner* ports (Ollama 11434, LM Studio 1234). The `--port` flag is the **Skillsmith service port** (where this FastAPI service listens, default 8000). It does not appear in `.env` — it's recorded in `install-state.json` and read by `wire-harness` (to inject the correct URL into harness configs) and `verify` (to check the right port is reachable). Override runner URLs via `--overrides` if you run them on non-default ports.

**Validation:** `write-env` rejects unknown keys in `--overrides` (typo guard). It also refuses to write if `.env` exists and was not produced by a previous `write-env` run (no overwriting hand-edited files without `--force`).

---

## `verify`

**Input:** none. Reads `install-state.json` to know URLs, ports, expected skill count.

**Output:**

```json
{
  "schema_version": 1,
  "all_checks_passed": true,
  "checks": [
    {"name": "embedding_endpoint_reachable", "passed": true, "duration_ms": 23, "detail": "GET http://localhost:11434/v1/models returned 200"},
    {"name": "embedding_endpoint_returns_1024_dim", "passed": true, "duration_ms": 312, "detail": "POST /v1/embeddings with model=qwen3-embedding:0.6b returned 1024-dim vector"},
    {"name": "duckdb_present", "passed": true, "duration_ms": 5, "detail": "/home/user/.local/share/skillsmith/corpus/skills.duck has 1655 fragments"},
    {"name": "ladybug_present", "passed": true, "duration_ms": 4, "detail": "/home/user/.local/share/skillsmith/corpus/ladybug has 153 skills"},
    {"name": "skill_count_meets_minimum", "passed": true, "duration_ms": 3, "detail": "153 >= 50 (MIN_SKILL_COUNT)"},
    {"name": "harness_config_present", "passed": true, "duration_ms": 2, "detail": "/home/user/dev/project-a/CLAUDE.md contains skillsmith sentinel block"},
    {"name": "harness_config_url_matches", "passed": true, "duration_ms": 1, "detail": "Injected URL http://localhost:8000 matches configured port"},
    {"name": "runtime_port_available", "passed": true, "duration_ms": 1, "detail": "Port 8000 is available (or already bound by skillsmith)"}
  ]
}
```

**Enumerated checks** (the implementer must implement all of these):

1. `embedding_endpoint_reachable` — HTTP GET to `RUNTIME_EMBED_BASE_URL/v1/models`, expect 200.
2. `embedding_endpoint_returns_1024_dim` — POST to `/v1/embeddings` with `RUNTIME_EMBEDDING_MODEL` and the test string `"hello world"`, expect a 1024-element float array.
3. `duckdb_present` — file at `DUCKDB_PATH` exists, `fragments` table has rows.
4. `ladybug_present` — directory at `LADYBUG_DB_PATH` exists, has at least one Skill node.
5. `skill_count_meets_minimum` — Skill node count ≥ `MIN_SKILL_COUNT` (constant, default 50).
6. `harness_config_present` — for the chosen harness, the expected file exists and contains the sentinel block.
7. `harness_config_url_matches` — the URL injected in the harness config matches `http://localhost:<port>` from state.
8. `runtime_port_available` — the configured port is either free or already bound by a skillsmith process.

**On failure:** any failed check has `passed: false`, `error: "<message>"`, and `remediation: "<hint>"`. The runbook auto-invokes `doctor` after a failed `verify` so the user sees both outputs in one go.

---

## `doctor`

**Input:** none.

**Output:** same shape as `verify` but additionally includes runtime-specific checks. Reads `install-state.json` and probes the live system.

**Additional checks beyond `verify`:**

9. `skillsmith_service_reachable` — HTTP GET to `http://localhost:<port>/health`, expect 200 with `status: ok`.
10. `compose_endpoint_works` — POST a minimal request to `/compose`, expect non-empty fragment array.
11. `state_file_consistent` — `install-state.json` exists, harness files in `harness_files_written` still contain matching sentinel blocks (sha256 match logged but mismatch is a warning not failure).
12. `runner_processes_present` — for the configured `embed_runner`, the expected process is running (e.g., `ollama serve` for Ollama presets, LM Studio for the radeon preset).

`doctor` is the diagnostic command. Failures include cross-references to entries in `error-catalog.md` (TBD if we add one) for common-failure remediation.

---

## `wire-harness`

**Input:** `--harness <name>` `[--mcp-fallback]`.

**Output:**

```json
{
  "schema_version": 1,
  "harness": "claude-code",
  "integration_vector": "markdown_injection",
  "files_written": [
    {
      "path": "/home/user/dev/project-a/CLAUDE.md",
      "harness": "claude-code",
      "repo_root": "/home/user/dev/project-a",
      "action": "injected_block",
      "sentinel_begin": "<!-- BEGIN skillsmith install -->",
      "sentinel_end": "<!-- END skillsmith install -->",
      "content_sha256": "sha256:..."
    }
  ]
}
```

**`integration_vector` values:** `markdown_injection` | `system_prompt_snippet` | `mcp_server_config`.

Each entry in `files_written` carries its own `harness` and `repo_root` so the same user-scope state file can describe wirings across multiple repos. The wire operation merges new entries with prior ones keyed by `path`, so re-wiring with a different harness in the same repo doesn't drop the prior harness's entries — `uninstall` walks the whole list to clean each one up.

The actual injected content per harness is in [`harness-catalog.md`](./harness-catalog.md). The CLI reads templates from `src/skillsmith/install/harness_templates/<harness>.md` (or `.json` for MCP).

**`action` values per file:** `injected_block` (sentinel-bounded insert/replace), `wrote_new_file` (file didn't exist before), `wrote_user_dotfile` (e.g., MCP servers config in `~/.claude/`).

---

## `uninstall`

**Input:** `[--remove-data]` `[--force]`. (`--keep-data` is accepted as a no-op alias for the default behavior.)

**Output:**

```json
{
  "schema_version": 1,
  "files_modified": [
    {"path": "/home/user/dev/project-a/CLAUDE.md", "action": "removed_sentinel_block"}
  ],
  "files_removed": [
    {"path": "/home/user/.config/skillsmith/.env", "action": "deleted"},
    {"path": "/home/user/.config/skillsmith", "action": "deleted_state_directory"}
  ],
  "data_kept": ["/home/user/.local/share/skillsmith/corpus"],
  "warnings": []
}
```

**Behavior:**
- Reads `harness_files_written` from state.
- For each entry: verify `content_sha256` matches what's currently between the sentinels. If mismatch (user edited inside the block), warn and skip unless `--force`. If sentinels are gone entirely, warn and skip unless `--force`.
- Removes `.env` (always), `install-state.json` (always).
- **Preserves `data/` by default** (locked decision in `spec.md`). Removes `data/` only when `--remove-data` is passed.

---

## `reset-step`

**Input:** `<step-name>`.

**Output:**

```json
{
  "schema_version": 1,
  "step_cleared": "write-env",
  "dependent_steps_also_cleared": ["wire-harness", "verify"]
}
```

Clearing a step also clears any later steps in `completed_steps` that depend on it (e.g., clearing `recommend-host-targets` clears `recommend-models`, `seed-corpus`, etc.). The dependency map is part of the install module:

```python
STEP_DEPENDENCIES = {
    "detect": [],
    "recommend-host-targets": ["detect"],
    "recommend-models": ["recommend-host-targets"],
    "seed-corpus": [],  # independent of host target choice
    "pull-models": ["recommend-models"],
    "write-env": ["recommend-models"],
    "wire-harness": ["write-env"],
    "verify": ["wire-harness", "pull-models", "seed-corpus"],
}
```

---

## Error message catalog (representative samples)

The implementer should follow this format for all surfaced errors:

```
ERROR: <one-line description>
CAUSE: <one-line cause>
FIX:   <one-line remediation, copy-pasteable command if applicable>
```

Examples:

```
ERROR: Embedding endpoint http://localhost:11434/v1/models returned 404
CAUSE: Ollama is not running, or running on a different port
FIX:   Start Ollama with `ollama serve`, then re-run `python -m skillsmith.install verify`

ERROR: Schema version mismatch: code expects v3, available corpus release is v2
CAUSE: This codebase is newer than the latest published corpus snapshot
FIX:   Run `python -m skillsmith.install update` to migrate your local corpus in-place

ERROR: Cannot write .env: file exists and was not produced by a prior install
CAUSE: A hand-edited or third-party .env is present at ${XDG_CONFIG_HOME:-~/.config}/skillsmith/.env
FIX:   Either move the existing file aside, or run `write-env --force` to overwrite

ERROR: Harness config CLAUDE.md was modified inside the sentinel block since install
CAUSE: User content was added between BEGIN/END markers; uninstall would lose it
FIX:   Either move that content outside the markers, or run `uninstall --force` to remove anyway
```
