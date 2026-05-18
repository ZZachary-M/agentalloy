# Contract 4: Documentation + Intake Skill Update

## Objective

Two independent tasks:
1. Create new documentation: `docs/phase-lock-file.md`
2. Update `skill-source/intake/intake-workflow-and-handoff/SKILL.md` with v1 note

---

## Task A: Create docs/phase-lock-file.md

Create a new documentation file at `docs/phase-lock-file.md` explaining the phase lock file format, lifecycle, and agent behavior.

**Content to write:**

```markdown
# Phase Lock File — `.skillsmith/phase`

## Overview

The phase lock file tells the agent which SDD (Software Delivery Discipline) phase is currently active for the project. It enables persistent phase state across prompts without requiring the agent to re-evaluate intent every time.

## Location

`.skillsmith/phase` in the project root directory.

The `.skillsmith/` directory is gitignored (present in `.gitignore`) — the phase file is local to each developer's environment.

## Format

YAML:

```yaml
phase: build
started_at: "2026-05-16T21:00:00Z"
last_updated: "2026-05-16T21:30:00Z"
workflow: sdd-build
```

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `phase` | string | Current SDD phase: `spec`, `design`, `build`, `qa`, or `ops` |
| `started_at` | ISO timestamp | When the session/phase was first started |
| `last_updated` | ISO timestamp | Last time the phase was set or updated |
| `workflow` | string | Associated workflow identifier (e.g., `sdd-build`) |

## Agent Behavior

### On session start

1. The agent checks for `.skillsmith/phase` in the project root
2. If it exists, the agent uses the recorded phase for `/compose` calls
3. If it does not exist, the agent evaluates the user's intent to determine the appropriate phase

### Per-prompt re-evaluation

The agent should re-evaluate intent on each new user message, not just trust the lock file blindly. If the user's message indicates a different context (e.g., switching from coding to writing a spec), the agent should update the lock file accordingly.

### When to write/update

- Intake determines the initial phase
- Phase transitions are detected mid-session
- User explicitly switches phases
- Via the `skillsmith phase set` CLI subcommand

### When to clear

- User leaves SDD work context entirely
- Via the `skillsmith phase clear` CLI subcommand

## CLI Management

```bash
# View current phase
skillsmith phase

# Set phase
skillsmith phase set build

# Clear phase
skillsmith phase clear
```

## Session Resume

When resuming a session, the agent checks `.skillsmith/phase` but re-evaluates intent if the user's message seems to indicate a different context. This prevents stale phase state from causing incorrect skill retrieval.

## Design Decisions

### Client-side only

The phase lock file is client-side. The `/compose` endpoint does not read it — the agent passes the phase value in the compose request. This keeps Skillsmith server stateless and decoupled from project file paths.

### Git-ignored

`.skillsmith/` is in `.gitignore` so phase state does not leak into version control. Each developer has their own phase state.
```

---

## Task B: Update intake-workflow-and-handoff/SKILL.md

Add a v1 note to the existing `skill-source/intake/intake-workflow-and-handoff/SKILL.md` explaining that v1 uses the static harness template stub for phase determination, not the full Qwen-based router.

The current file exists at `skill-source/intake/intake-workflow-and-handoff/SKILL.md`. It currently describes the v2 intake workflow (full Qwen router with confidence thresholds).

Add the following section near the top, after the Overview section:

```markdown
### V1 vs V2

**V1 (current):** Uses a static stub in the harness template for phase determination. The stub instructs the agent to:
1. Check `.skillsmith/phase` for the current phase
2. If no phase file, evaluate user intent (SDD vs non-SDD)
3. Pick the matching phase and call `/compose`
4. Skip Skillsmith entirely for non-SDD work

This avoids a cold-start API call and the chicken-and-egg problem of needing a phase to retrieve the intake skill.

**V2 (future):** Graduates to the full Qwen-based router described below (signal schema gathering, confidence thresholds, alternate routing). Requires a bootstrap `/compose` endpoint that accepts an `intake` phase.
```

Insert this section after the "## Overview" paragraph and before the "---" separator.

## Acceptance Criteria

- `docs/phase-lock-file.md` exists with comprehensive documentation
- `skill-source/intake/intake-workflow-and-handoff/SKILL.md` has the v1/v2 distinction clearly documented
- Documentation explains format, lifecycle, agent behavior, CLI management, and design decisions
