## Skillsmith — skill context

**Health-gate.** Verify: `curl -fs http://localhost:{port}/health`. If unreachable, skip.

**Session start — determine phase.** Check `.skillsmith/phase`. If it exists, use that phase. If not:
- SDD work -> pick the matching phase
- Non-SDD work -> skip Skillsmith entirely

**When in an SDD phase, before starting work, POST to `/compose/text` with `{"task": "...", "phase": "<phase from .skillsmith/phase>"}`. Read the response before generating code.

**Phase transitions.** Update `.skillsmith/phase` if activity shifts.

Phases: `spec`, `design`, `build`, `qa`, `ops`.