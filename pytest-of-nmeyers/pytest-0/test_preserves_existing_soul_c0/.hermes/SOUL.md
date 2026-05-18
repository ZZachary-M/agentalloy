# My persona

Be terse.

<!-- BEGIN skillsmith install -->
## Skillsmith — skill context

A local skillsmith service may be running at `http://localhost:8000` with a curated corpus of engineering skills (testing, error handling, deployment, observability, security, etc.).

**Health-gate before using.** This block is loaded into every Hermes session, but skillsmith is per-project. Before invoking `/compose`, verify the service is reachable:

```bash
curl -fs http://localhost:8000/health
```

If that fails, ignore this block for this session — skillsmith is not wired for the current project.

**When healthy, before starting any task** (spec, design, build, test, debug), run:

```bash
curl -s -X POST http://localhost:8000/compose/text \
  -H 'Content-Type: application/json' \
  -d '{"task": "<one sentence describing what you are about to do>", "phase": "build"}'
```

The response is plain text — your skill context for this task. Read it and apply it before generating code or a plan.

Phases: `spec`, `design`, `build`, `qa`, `ops`. Match the phase to the lifecycle stage of the task.

<!-- END skillsmith install -->
