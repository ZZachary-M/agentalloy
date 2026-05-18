---
description: Fetch skill context before starting any SDD coding task
trigger: always_on
---

# Skillsmith — skill context

A local skillsmith service runs at `http://localhost:{port}` with a curated corpus of engineering skills.

**Health-gate.** Before using, verify: `curl -fs http://localhost:{port}/health`. If unreachable, ignore this block.

**Session start — determine phase.** Check `.skillsmith/phase` for the current phase. If it exists, use that phase. If not, evaluate user intent:
- SDD work (coding, testing, debugging, designing, spec writing) -> pick the matching phase
- Casual chat, questions, non-SDD work -> skip Skillsmith entirely

**When in an SDD phase, before starting work:**
```bash
curl -s -X POST http://localhost:{port}/compose/text \
  -H 'Content-Type: application/json' \
  -d '{"task": "<one sentence describing what you are about to do>", "phase": "<phase from .skillsmith/phase>"}'
```

**Phase transitions.** If the user's activity clearly shifts to a different SDD phase, update `.skillsmith/phase` and call `/compose` with the new phase.

Phases: `spec`, `design`, `build`, `qa`, `ops`.