# Contract 1: Ingest Intake Skills

## Objective

Run the existing authoring pipeline on the 3 intake skills located in `skill-source/intake/`, verify they land in LadybugDB with `skill_class: "workflow"`, and reembed.

## Intake Skills to Process

Three skills exist in `skill-source/intake/`:

1. `skill-source/intake/intake-workflow-and-handoff/SKILL.md` — Signal schema (intent, artifact_type, scope, urgency), 4-phase structure (gather -> propose -> verify -> hand_off)
2. `skill-source/intake/intake-router-and-confidence/SKILL.md` — Qwen-based router with confidence thresholds (>=0.6 propose, 0.4-0.6 alternates, <0.4 clarify)
3. `skill-source/intake/intake-verification-and-workflow-execution/SKILL.md` — Verification UX, exit gates, scope checks, v1 simplification (hard scope, no auto re-route)

## Steps

1. Run the authoring pipeline on each of the 3 intake skills. The pipeline entry point is `src/skillsmith/authoring/__main__.py`. You can run it via:
   ```bash
   cd /home/nmeyers/dev/skillsmith
   python -m skillsmith.authoring --skill-source skill-source/intake/intake-workflow-and-handoff/SKILL.md
   python -m skillsmith.authoring --skill-source skill-source/intake/intake-router-and-confidence/SKILL.md
   python -m skillsmith.authoring --skill-source skill-source/intake/intake-verification-and-workflow-execution/SKILL.md
   ```
   Or use the `skillsmith install` subcommand approach if that's the standard method. Check `src/skillsmith/authoring/__main__.py` for the correct invocation.

2. Verify all 3 skills appear in LadybugDB with `skill_class: "workflow"`. Query the DB directly using sqlite3 or the authoring pipeline's verification tools.

3. Run `skillsmith reembed` (or `python -m skillsmith.install reembed`) to generate embeddings for the newly ingested skills so they are retrievable via `/compose`.

## Acceptance Criteria

- All 3 intake skills are ingested into the LadybugDB corpus
- Each has `skill_class: "workflow"` set correctly
- Embeddings are generated and the skills are retrievable via the `/compose` endpoint
- No errors during pipeline execution
