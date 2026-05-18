# Plan: Intake Activation Workflow — Wire "Start Session" into the Harness

## Goal

Replace the current "compose on every task" harness behavior with a conditional activation workflow:

1. Agent starts a session and runs the intake workflow (intent gathering + phase determination)
2. If the user is doing SDD-related work, the agent calls `/compose` with the determined phase
3. If the user is just chatting or doing non-SDD work, the agent skips `/compose` entirely
4. Phase state persists across prompts via a phase lock file
5. Per-prompt re-evaluation allows mid-session phase transitions

## Current State

### What exists today
- **Harness templates** (`src/skillsmith/install/harness_templates/hermes-agent.md`): Tell the agent to call `/compose/text` on EVERY task with no gating. Phase is a required Literal field with no null option.
- **Intake skills** (`skill-source/intake/`): Three skills define the intake workflow concept:
  - `intake-workflow-and-handoff`: Signal schema (intent, artifact_type, scope, urgency), 4-phase structure (gather -> propose -> verify -> hand_off)
  - `intake-router-and-confidence`: Qwen-based router with confidence thresholds (>=0.6 propose, 0.4-0.6 alternates, <0.4 clarify)
  - `intake-verification-and-workflow-execution`: Verification UX, exit gates, scope checks, v1 simplification (hard scope, no auto re-route)
- **SDD workflow skills** (`skill-source/sdd/`): Five skills mapping to SDD phases (spec, design, build, verify, deliver)
- **System governance skills** (`fixtures/system/`): Three fixture skills (always-apply, build-phase-only, design-category-only)
- **`/compose` endpoint**: Requires `phase` as a Literal type. No bootstrap/intake phase. No phase lock file awareness.

### The gap
The intake workflow is designed in skills but NOT wired into the harness. The agent has no instructions to run intake first, and the `/compose` endpoint has no bootstrap mechanism. The intake skills are not yet ingested into the LadybugDB corpus.

## Proposed Approach

### Phase 1: Solve the bootstrap chicken-and-egg

**Problem**: The harness template says "pull the intake skill on load", but Skillsmith requires a phase to retrieve skills. Circular dependency.

**Solution: Static stub in harness template (option b from conversation)**

Put a ~10-line static instruction in the harness template that IS the intake logic. This avoids a cold-start API call. The stub tells the agent:
1. Evaluate the user's intent from their first message
2. If it's clearly SDD work, pick a phase and call `/compose`
3. If it's chat/ambiguous, skip Skillsmith and proceed normally
4. Optionally ask 1-2 clarifying questions if intent is unclear

This is the "minimize template injection" approach. The full intake skills are ingested into the corpus so the agent can retrieve them later for more sophisticated routing once in an active phase.

### Phase 2: Phase lock file

**What**: A `.skillsmith/phase` file in the project root containing the current phase and session metadata.

**Format** (YAML):
```yaml
phase: build
started_at: "2026-05-16T21:00:00Z"
last_updated: "2026-05-16T21:30:00Z"
workflow: sdd-build
```

**Git-ignored**: `.skillsmith/` is already in `.gitignore` (verified) — no action needed.

**Where it's checked**: Client-side by the agent. The agent reads `.skillsmith/phase` at the start of each prompt to know the current phase without re-evaluating. The agent writes/updates it when:
- Intake determines the initial phase
- Phase transitions are detected mid-session
- User explicitly switches phases
- Via the `skillsmith phase` CLI subcommand (see Phase 3)

**Session resume**: The harness template instructs the agent to check `.skillsmith/phase` but re-evaluate intent if the user's message seems to indicate a different context.

**No server-side awareness**: The `/compose` endpoint doesn't read the lock file. The agent passes the phase from the lock file in the compose request. This keeps Skillsmith server stateless and decoupled from project file paths.

### Phase 3: `skillsmith phase` CLI subcommand

**What**: A new CLI subcommand for manual phase management.

**Commands**:
- `skillsmith phase` — print current phase from `.skillsmith/phase`
- `skillsmith phase set <phase>` — write/update the phase lock file
- `skillsmith phase clear` — remove `.skillsmith/phase` (reset to no phase)

**Why**: Gives the user direct control over phase state without needing to go through the agent. Useful for debugging, CI scripts, or when the agent misclassifies.

**Implementation**: New file `src/skillsmith/install/subcommands/phase.py`. Wires into the existing CLI alongside `serve`, `doctor`, `wire`, etc.

### Phase 4: Ingest intake skills into the corpus

**What**: The three intake skills in `skill-source/intake/` are valid SKILL.md files but not yet ingested into the LadybugDB corpus. Ingest them so the agent can retrieve them via `/compose` once in an active phase.

**Implementation**: Run the existing authoring pipeline on the intake skills, or add them to the next `skillsmith seed-corpus` / `skillsmith install-packs` run. Verify they appear in LadybugDB with `skill_class: "workflow"`.

### Phase 5: Updated harness templates

Update all harness templates (`hermes-agent.md`, `claude-code.md`, `cursor.mdc`, etc.) with the new activation logic:

```markdown
## Skillsmith — skill context

A local skillsmith service may be running at `http://localhost:{port}`.

**Health-gate.** Before using, verify:
```bash
curl -fs http://localhost:{port}/health
```
If that fails, ignore this block.

**Session start — determine phase.** On each new task, check `.skillsmith/phase` for the current phase. If it exists, use that phase. If not, evaluate user intent:
- SDD work (coding, testing, debugging, designing, spec writing) -> pick the matching phase
- Casual chat, questions, non-SDD work -> skip Skillsmith

**When in an SDD phase, before starting work, run:**
```bash
curl -s -X POST http://localhost:{port}/compose/text \
  -H 'Content-Type: application/json' \
  -d '{"task": "<one sentence>", "phase": "<phase from .skillsmith/phase>"}'
```

**Phase transitions.** If the user's activity clearly shifts to a different SDD phase, update `.skillsmith/phase` and call `/compose` with the new phase.

Phases: `spec`, `design`, `build`, `qa`, `ops`.
```

## Step-by-Step Implementation

### Step 1: Ingest intake skills into the corpus
- Run the authoring pipeline on `skill-source/intake/` skills
- Verify they land in LadybugDB with `skill_class: "workflow"`
- Run `skillsmith reembed` to generate embeddings for the new skills

### Step 2: Add `skillsmith phase` CLI subcommand
- Create `src/skillsmith/install/subcommands/phase.py`
- Implement three actions: `get` (default), `set <phase>`, `clear`
- Wire into the CLI argument parser in `src/skillsmith/install/__main__.py`
- Validate phase values against the Phase Literal enum
- Write/update `.skillsmith/phase` with timestamps

### Step 3: Update harness templates (all files in `src/skillsmith/install/harness_templates/`)
- Rewrite `hermes-agent.md` with intake activation logic (health-gate, phase lock file, skip-if-non-SDD)
- Rewrite `claude-code.md`, `cursor.mdc`, `github-copilot.md`, `windsurf.md`, `gemini-cli.md` with equivalent logic adapted to each harness's syntax
- Rewrite `opencode.md`, `cline.md`, `aider.md` similarly
- All templates reference `.skillsmith/phase` and include the "skip if non-SDD" guidance

### Step 4: Add phase lock file documentation
- Create `docs/phase-lock-file.md` explaining the format, lifecycle, and agent behavior around `.skillsmith/phase`

### Step 5: Update intake skills to reference the new flow
- Update `skill-source/intake/intake-workflow-and-handoff/SKILL.md` to reflect the static-stub approach vs. the full Qwen router (which is v2)
- Note that v1 uses the harness template stub for phase determination, not the Qwen-based router

### Step 6: Update tests
- Update `tests/install/test_wire_harness.py` to verify new template content contains intake activation markers
- Add test for `skillsmith phase` CLI subcommand (set/get/clear)
- Add test verifying `.skillsmith/phase` file format on set/clear

## Files to Change

### New files:
- `src/skillsmith/install/subcommands/phase.py` — CLI subcommand implementation
- `docs/phase-lock-file.md` — phase lock file documentation

### Template files (content rewrite — 9 files):
- `src/skillsmith/install/harness_templates/hermes-agent.md`
- `src/skillsmith/install/harness_templates/claude-code.md`
- `src/skillsmith/install/harness_templates/cursor.mdc`
- `src/skillsmith/install/harness_templates/github-copilot.md`
- `src/skillsmith/install/harness_templates/windsurf.md`
- `src/skillsmith/install/harness_templates/gemini-cli.md`
- `src/skillsmith/install/harness_templates/opencode.md`
- `src/skillsmith/install/harness_templates/cline.md`
- `src/skillsmith/install/harness_templates/aider.md`

### Documentation/skills:
- `skill-source/intake/intake-workflow-and-handoff/SKILL.md` (update v1 note)

### CLI wiring:
- `src/skillsmith/install/__main__.py` (wire `phase` subcommand)

### Tests:
- `tests/install/test_wire_harness.py` (verify new template content)
- `tests/install/test_phase_cli.py` (new — test `skillsmith phase` subcommand)

## Files NOT Changing (v1)
- `src/skillsmith/api/compose_models.py` — phase stays required Literal
- `src/skillsmith/orchestration/compose.py` — no bootstrap endpoint yet
- `src/skillsmith/retrieval/domain.py` — no phase lock file awareness
- `src/skillsmith/install/subcommands/wire_harness.py` — no code change, just template content

## Tests / Validation

1. **Intake skills ingested**: Query LadybugDB to verify all three intake skills appear with `skill_class: "workflow"`
2. **Phase CLI**: Run `skillsmith phase set build`, verify `.skillsmith/phase` exists with correct YAML. Run `skillsmith phase`, verify it prints `build`. Run `skillsmith phase clear`, verify file is removed.
3. **Phase CLI validation**: Run `skillsmith phase set invalid`, verify it rejects with an error listing valid phases.
4. **Harness template content**: Verify all templates contain intake activation logic, phase lock file references, and "skip if non-SDD" guidance.
5. **Wire harness test**: `tests/install/test_wire_harness.py` — ensure generated files contain expected markers.
6. **Git-ignored**: Verify `.skillsmith/` does not appear in `git status` after creating the phase file.
7. **Manual verification**: Run `skillsmith wire-harness hermes-agent` and inspect the generated `SOUL.md` / `AGENTS.md` content.
8. **End-to-end**: Start a fresh session, verify the agent:
   - Evaluates intent from the first message
   - Creates `.skillsmith/phase` when SDD work is detected
   - Calls `/compose` with the correct phase
   - Skips `/compose` when the user is just chatting

## Risks and Tradeoffs

### Risks
- **Agent compliance**: The agent may not follow the intake instructions consistently. This is inherently an LLM behavior issue — no code change guarantees compliance. The template language needs to be clear and directive.
- **Phase lock file as source of truth**: If the agent forgets to update it, subsequent prompts use stale phase info. Mitigation: The harness template instructs the agent to re-evaluate intent per-prompt, not just trust the lock file blindly.
- **Intake skill ingestion timing**: The intake skills need to be ingested before any agent session can retrieve them. If the corpus is seeded after wiring the harness, there's a brief window where retrieval fails. Mitigation: Seed intake skills as part of the `install-packs` step so they're present before the first session.

### Tradeoffs
- **Static stub vs full intake skill**: The static stub is simpler but less flexible. The full Qwen-based router (already designed in intake skills) requires a bootstrap endpoint and adds a cold-start API call. V1 uses the stub; v2 can graduate to the full router.
- **Client-side phase lock vs server-side**: Client-side keeps the server stateless but puts the burden on the agent. Server-side would couple Skillsmith to file paths.

## Resolved Decisions

1. **`.skillsmith/phase` is gitignored** — `.skillsmith/` is already in `.gitignore` (verified) — no action needed.
2. **Session resume behavior** — Agent checks `.skillsmith/phase` but re-evaluates intent if the user's message indicates a different context.
3. **`skillsmith phase` CLI subcommand** — Added as Step 2 above. Supports `get`, `set <phase>`, and `clear` actions.
4. **Intake skills are ingested** — Added as Step 1 above. Three intake skills from `skill-source/intake/` are run through the authoring pipeline and embedded so they're retrievable via `/compose`.
