# Contract 3: Rewrite All 9 Harness Templates

## Objective

Rewrite all 9 harness templates with the new intake activation logic. Each template must include:
1. Health-gate check
2. Session start phase determination (check `.skillsmith/phase` first)
3. Skip-if-non-SDD guidance
4. Phase transition instructions
5. The `/compose` curl command referencing `.skillsmith/phase`

## New Template Content for Each File

Write the following content to each file. The `{port}` placeholder is filled at wire time by the `wire_harness` subcommand — DO NOT replace it.

### 1. hermes-agent.md (src/skillsmith/install/harness_templates/hermes-agent.md)

```markdown
## Skillsmith — skill context

A local skillsmith service may be running at `http://localhost:{port}` with a curated corpus of engineering skills.

**Health-gate.** Before using, verify:
```bash
curl -fs http://localhost:{port}/health
```
If that fails, ignore this block — skillsmith is not wired for this project.

**Session start — determine phase.** On each new task, check `.skillsmith/phase` for the current phase. If it exists, use that phase. If not, evaluate user intent:
- SDD work (coding, testing, debugging, designing, spec writing) -> pick the matching phase
- Casual chat, questions, non-SDD work -> skip Skillsmith entirely

**When in an SDD phase, before starting work, run:**
```bash
curl -s -X POST http://localhost:{port}/compose/text \
  -H 'Content-Type: application/json' \
  -d '{"task": "<one sentence>", "phase": "<phase from .skillsmith/phase>"}'
```

**Phase transitions.** If the user's activity clearly shifts to a different SDD phase, update `.skillsmith/phase` and call `/compose` with the new phase.

Phases: `spec`, `design`, `build`, `qa`, `ops`.
```

### 2. claude-code.md (src/skillsmith/install/harness_templates/claude-code.md)

```markdown
## Skillsmith — skill context

A local skillsmith service runs at `http://localhost:{port}` with a curated corpus of engineering skills.

**Health-gate.** Before using, verify: `curl -fs http://localhost:{port}/health`. If unreachable, ignore this block.

**Session start — determine phase.** Check `.skillsmith/phase` for the current phase. If it exists, use that phase. If not, evaluate user intent:
- SDD work (coding, testing, debugging, designing, spec writing) -> pick the matching phase
- Casual chat, questions, non-SDD work -> skip Skillsmith entirely

**When in an SDD phase, before starting work, run:**
```bash
curl -s -X POST http://localhost:{port}/compose/text \
  -H 'Content-Type: application/json' \
  -d '{"task": "<one sentence describing what you are about to do>", "phase": "<phase from .skillsmith/phase>"}'
```

**Phase transitions.** If the user's activity clearly shifts to a different SDD phase, update `.skillsmith/phase` and call `/compose` with the new phase.

Phases: `spec`, `design`, `build`, `qa`, `ops`. Match the phase to the lifecycle stage of the task.
```

### 3. cursor.mdc (src/skillsmith/install/harness_templates/cursor.mdc)

```markdown
---
description: Fetch skill context before starting any SDD coding task
globs: ["**/*"]
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
```

### 4. github-copilot.md (src/skillsmith/install/harness_templates/github-copilot.md)

Same content as claude-code.md (identical format).

### 5. windsurf.md (src/skillsmith/install/harness_templates/windsurf.md)

```markdown
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
```

### 6. gemini-cli.md (src/skillsmith/install/harness_templates/gemini-cli.md)

```markdown
## Skillsmith — skill context

A local skillsmith service runs at `http://localhost:{port}` with a curated corpus of engineering skills.

**Health-gate.** Before using, verify: `curl -fs http://localhost:{port}/health`. If unreachable, ignore this block.

**Session start — determine phase.** Check `.skillsmith/phase` for the current phase. If it exists, use that phase. If not, evaluate user intent:
- SDD work (coding, testing, debugging, designing, spec writing) -> pick the matching phase
- Casual chat, questions, non-SDD work -> skip Skillsmith entirely

**When in an SDD phase, before starting work, use your shell tool to run:**
```bash
curl -s -X POST http://localhost:{port}/compose/text \
  -H 'Content-Type: application/json' \
  -d '{"task": "<one sentence describing what you are about to do>", "phase": "<phase from .skillsmith/phase>"}'
```

**Phase transitions.** If the user's activity clearly shifts to a different SDD phase, update `.skillsmith/phase` and call `/compose` with the new phase.

Phases: `spec`, `design`, `build`, `qa`, `ops`. Match the phase to the lifecycle stage of the task.
```

### 7. opencode.md (src/skillsmith/install/harness_templates/opencode.md)

```markdown
## Skillsmith — skill context

**Health-gate.** Verify: `curl -fs http://localhost:{port}/health`. If unreachable, skip.

**Session start — determine phase.** Check `.skillsmith/phase`. If it exists, use that phase. If not:
- SDD work -> pick the matching phase
- Non-SDD work -> skip Skillsmith entirely

**When in an SDD phase, before starting work, POST to `/compose/text` with `{"task": "...", "phase": "<phase from .skillsmith/phase>"}`. Read the response before generating code.

**Phase transitions.** Update `.skillsmith/phase` if activity shifts.

Phases: `spec`, `design`, `build`, `qa`, `ops`.
```

### 8. cline.md (src/skillsmith/install/harness_templates/cline.md)

```markdown
# Skillsmith — skill context

A local skillsmith service runs at http://localhost:{port}.

**Health-gate.** Verify: `curl -fs http://localhost:{port}/health`. If unreachable, skip.

**Session start — determine phase.** Check `.skillsmith/phase`. If it exists, use that phase. If not:
- SDD work (coding, testing, debugging, designing, spec writing) -> pick the matching phase
- Non-SDD work -> skip Skillsmith entirely

**When in an SDD phase, before starting work, POST to `/compose/text` with `{"task": "...", "phase": "<phase from .skillsmith/phase>"}`. Read the response before generating code.

**Phase transitions.** Update `.skillsmith/phase` if activity shifts.

Phases: `spec`, `design`, `build`, `qa`, `ops`.
```

### 9. aider.md (src/skillsmith/install/harness_templates/aider.md)

```markdown
## Skillsmith — skill context

**Health-gate.** Verify: `curl -fs http://localhost:{port}/health`. If unreachable, skip.

**Session start — determine phase.** Check `.skillsmith/phase`. If it exists, use that phase. If not:
- SDD work -> pick the matching phase
- Non-SDD work -> skip Skillsmith entirely

**When in an SDD phase, POST to `/compose/text` with `{"task": "...", "phase": "<phase from .skillsmith/phase>"}`. Read the response before generating code.

**Phase transitions.** Update `.skillsmith/phase` if activity shifts.

Phases: `spec`, `design`, `build`, `qa`, `ops`.
```

## Acceptance Criteria

- All 9 template files are rewritten with intake activation logic
- Each template contains: health-gate, phase lock file reference, skip-if-non-SDD guidance, phase transition instructions
- The `{port}` placeholder is preserved (not replaced)
- Template-specific formatting is maintained (YAML frontmatter for cursor.mdc/windsurf.md, brevity for aider.md/opencode.md/cline.md)
