# Install — Test Plan

Companion to [`spec.md`](./spec.md), [`contracts.md`](./contracts.md), [`harness-catalog.md`](./harness-catalog.md). Authoritative for acceptance criteria.

The install path is genuinely cross-platform and integrates with multiple external tools (Ollama, LM Studio, harness configs). Test coverage has three layers:

1. **Unit tests** — pure-Python, no external services. Schema validation, idempotency logic, state file handling, preset templating.
2. **Integration tests (containerized)** — Linux container with Ollama mocked or real, exercising end-to-end install minus harness wiring.
3. **Manual acceptance walk-throughs** — human-driven on real hardware/OS combos.

---

## Layer 1: Unit tests

Location: `tests/install/`. Run with `uv run pytest tests/install/`.

### State file handling (`tests/install/test_state.py`)

| Test | Asserts |
|---|---|
| `test_state_file_created_on_first_subcommand` | After `detect`, `<repo>/.skillsmith/install-state.json` exists with schema_version 1 |
| `test_state_file_append_only_within_run` | `completed_steps` is appended, never reordered |
| `test_state_file_schema_v0_to_v1_migration` | Reading a v0 state file triggers migration; result is valid v1 |
| `test_state_file_newer_than_code_errors` | Reading a v2 state file with v1 code exits with code 3 (schema mismatch) |
| `test_state_file_consistent_after_concurrent_writes` | Two subcommands writing in sequence produce a valid state file (no JSON corruption) |

### Idempotency (`tests/install/test_idempotency.py`)

| Test | Asserts |
|---|---|
| `test_detect_idempotent_within_session` | Two `detect` calls in the same install run return identical output |
| `test_seed_corpus_skipped_when_present` | If `data/skills.duck` exists with skill_count >= MIN, action is `skipped_already_present` |
| `test_pull_models_skipped_when_present` | Mocked Ollama: re-running `pull-models` with already-pulled models returns empty `auto_pulled` list |
| `test_write_env_replaces_existing_block` | Re-running `write-env` replaces the prior `.env` (no append) |
| `test_wire_harness_replaces_sentinel_block` | Re-running `wire-harness` replaces existing sentinel block, doesn't duplicate |

### Reset-step + dependencies (`tests/install/test_reset_step.py`)

| Test | Asserts |
|---|---|
| `test_reset_step_clears_named_step` | After `reset-step write-env`, the entry is gone from completed_steps |
| `test_reset_step_clears_dependent_steps` | Resetting `recommend-models` also clears `pull-models`, `write-env`, `wire-harness`, `verify` |
| `test_reset_step_independent_chains_preserved` | Resetting `recommend-host-targets` does NOT clear `seed-corpus` (independent) |
| `test_reset_step_unknown_step_errors` | `reset-step bogus` exits non-zero with clear error |

### Preset templating (`tests/install/test_presets.py`)

| Test | Asserts |
|---|---|
| `test_preset_loaded_from_yaml` | `apple-silicon.yaml` loads cleanly into a Pydantic model |
| `test_port_substitution` | `{port}` in template values is replaced with `--port` arg or 47950 default |
| `test_overrides_validated_against_known_keys` | `--overrides UNKNOWN_KEY=foo` is rejected |
| `test_existing_env_not_overwritten_without_force` | `write-env` errors if `.env` exists and wasn't written by prior install |

### Sentinel injection (`tests/install/test_sentinels.py`)

| Test | Asserts |
|---|---|
| `test_sentinel_block_inserted_into_existing_file` | Existing `CLAUDE.md` content preserved; our block appended after blank line |
| `test_sentinel_block_replaced_on_reinstall` | Re-running `wire-harness` replaces only between sentinels |
| `test_uninstall_removes_only_sentinel_block` | After `uninstall`, user content is intact, sentinel block is gone |
| `test_tampered_sentinel_block_warns` | If content_sha256 mismatches what's on disk, `uninstall` warns and skips |
| `test_force_overrides_tamper_warning` | `uninstall --force` removes the block even when tampered |
| `test_crlf_line_endings_preserved` | A CRLF-encoded `CLAUDE.md` stays CRLF after our injection |

---

## Layer 2: Integration tests (containerized)

Location: `tests/install/integration/`. Run via `podman-compose -f tests/install/integration/compose.yaml up --abort-on-container-exit`.

The compose stack:

```yaml
services:
  skillsmith-test:
    build:
      context: ../../..
      dockerfile: tests/install/integration/Dockerfile
    depends_on: [ollama]
    environment:
      RUNTIME_EMBED_BASE_URL: "http://ollama:11434"
    command: pytest tests/install/integration/

  ollama:
    image: ollama/ollama:latest
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:11434/v1/models"]
```

Tests in this layer hit a real Ollama instance.

### End-to-end install (`tests/install/integration/test_e2e.py`)

| Test | Asserts |
|---|---|
| `test_full_install_cpu_preset` | Run `detect` → `recommend-host-targets` (auto-confirm CPU+RAM) → `recommend-models` → `seed-corpus` (mocked release URL) → `pull-models` → `write-env` → `wire-harness --harness manual` → `verify` exits 0 with all checks passing |
| `test_resume_after_partial_failure` | Run install, kill mid-step, re-run — completes from where it left off without redoing prior work |
| `test_uninstall_clean` | After full install, `uninstall` leaves no skillsmith artifacts on disk (except `data/` if `--keep-data`) |
| `test_update_in_place_migration` | Stage a corpus at schema v2, bump code to v3, run `update`, verify corpus is migrated in-place to v3 (no re-download) |

### Embedding round-trip (`tests/install/integration/test_embedding.py`)

| Test | Asserts |
|---|---|
| `test_ollama_returns_1024_dim` | `verify` check `embedding_endpoint_returns_1024_dim` passes against real Ollama with `qwen3-embedding:0.6b` pulled |
| `test_wrong_embedding_model_caught` | `verify` fails clearly when the configured model returns a different dim |

### Seed corpus integrity (`tests/install/integration/test_seed.py`)

The corpus ships in-repo (rev 5). `seed-corpus` is now a presence + integrity check, not a download.

| Test | Asserts |
|---|---|
| `test_seed_corpus_passes_on_fresh_clone` | After `git clone`, `seed-corpus` returns `action: verified_present` with expected skill count |
| `test_seed_corpus_missing_files_remediation` | Delete `data/skills.duck` → `seed-corpus` returns `action: missing_files`, exit 1, with hint to run `git checkout -- data/` |
| `test_seed_corpus_schema_mismatch` | Stage a corpus with embedded schema older than code expects → `action: schema_mismatch`, exit 3, with hint pointing at `update` |
| `test_seed_corpus_under_minimum_skill_count` | Stage a corpus with < MIN_SKILL_COUNT skills → `action: missing_files`, exit 1 |
| `test_seed_corpus_no_network_calls` | Mock the HTTP client; `seed-corpus` makes zero network calls |

---

## Layer 3: Manual acceptance walk-throughs

Per-platform checklist, run by a human. One walk-through per OS × harness combination supported in v1.

### Platform matrix

| OS | Hardware | Host Target | Status |
|---|---|---|---|
| Linux x86_64 | Intel CPU only | CPU+RAM | required |
| Linux x86_64 | NVIDIA GPU | dGPU | required |
| Linux x86_64 | AMD Radeon iGPU (e.g. 890M) | iGPU (radeon preset) | required (your dev workstation) |
| macOS | Apple Silicon M-series | iGPU | required |
| Windows 11 | NVIDIA GPU | dGPU | nice-to-have v1, required v1.1 |
| Windows 11 | AMD Radeon dGPU | dGPU | nice-to-have v1, required v1.1 |

### Harness matrix

| Harness | OS coverage | Status |
|---|---|---|
| Claude Code | Linux + macOS minimum | required |
| Gemini CLI | Linux + macOS minimum | required |
| Cursor | Linux + macOS minimum | required |
| Continue.dev (closed model) | Linux + macOS minimum | required |
| Continue.dev (local model) | Linux minimum | required |
| OpenCode + local LLM | Linux minimum | required |
| Aider + local LLM | Linux minimum | required |
| Cline | Linux + macOS minimum | nice-to-have v1 |
| MCP fallback (Claude Code) | Linux + macOS minimum | required (sanity-check the fallback path) |

### Per-walkthrough acceptance criteria

For each (OS × hardware × harness) combination:

1. **Fresh clone**, no prior install state.
2. From the LLM (the harness being tested or a separate session): `clone the repo and follow INSTALL.md`.
3. The LLM walks the runbook end to end.
4. Acceptance gates:
   - [ ] `detect` produces correct hardware identification (user confirms accurately)
   - [ ] `recommend-host-targets` lists at least the recommended target with `recommended: true`
   - [ ] `recommend-models` returns at least one option with `default: true`
   - [ ] `seed-corpus` completes; `data/skills.duck` has ≥50 fragments; pre-computed embeddings present (no `reembed` needed)
   - [ ] `pull-models` succeeds (or surfaces clear manual-step instructions for `lmstudio`/`mlx`/`vllm`)
   - [ ] `write-env` produces a valid `.env` consumable by `uvicorn skillsmith.app:app`
   - [ ] `wire-harness` produces the expected file at the expected path with sentinel-bounded content
   - [ ] `verify` passes all 8 enumerated checks
   - [ ] First-run demo: a real `/compose` request returns non-empty fragments
   - [ ] User test: open the harness, ask "what skills do you have access to?" — harness responds correctly using the injected instructions
5. **Uninstall verification:**
   - [ ] `uninstall` removes only sentinel-bounded content
   - [ ] User content elsewhere in `CLAUDE.md` (or equivalent) is preserved
   - [ ] `--keep-data` preserves `data/`; default removes it (or vice versa, per locked decision)
   - [ ] Re-running `install` after `uninstall` works cleanly (no orphaned state)
6. **Resume verification:**
   - [ ] Kill `pull-models` mid-download. Re-run install. Resumes correctly.
   - [ ] `reset-step write-env` clears state; next install run re-runs `write-env` and downstream steps.

### Recording results

Each walk-through produces a markdown report at `docs/install/walkthrough-results/<os>-<hw>-<harness>-<date>.md` with:

- The `install-state.json` at completion
- Stdout/stderr captures from each subcommand
- A pass/fail line per acceptance gate above
- Any deviations or surprises

These reports are checked into the repo as install regression evidence.

---

## CI strategy

**Layer 1 (unit) on every PR.** Fast, deterministic. Required to merge.

**Layer 2 (integration) on every PR to `main`.** Slower (~3 min for the container stack). Required for merge to main.

**Layer 3 (manual) before each release tag.** Documented in the release checklist. Skipping a platform/harness combination requires explicit sign-off.

---

## Coverage gaps acknowledged in v1

- No automated test of the actual harness behavior (we don't programmatically launch Claude Code and ask it to invoke the curl command). That's verified by the manual walk-through user-test gate.
- Windows integration tests are not run in CI. v1.1 should add a Windows runner.
- We don't test the corpus snapshot itself for content quality — that's covered by the existing `tests/test_compose_*` and POC eval suites.
- MCP server functional tests are deferred to v1.1 (MCP is the fallback path, not the default).
