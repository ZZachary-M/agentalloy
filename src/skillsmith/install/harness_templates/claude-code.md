## Skillsmith — skill context

A local skillsmith service runs at `http://localhost:{port}` with a curated corpus of engineering skills (testing, error handling, deployment, observability, security, etc.).

**Before starting any task** (spec, design, build, test, debug), run:

```bash
curl -s -X POST http://localhost:{port}/compose/text \
  -H 'Content-Type: application/json' \
  -d '{"task": "<one sentence describing what you are about to do>", "phase": "build"}'
```

The response is plain text — your skill context for this task. Read it and apply it before generating code or a plan.

Phases: `spec`, `design`, `build`, `qa`, `ops`. Match the phase to the lifecycle stage of the task.

Health check: `curl -s http://localhost:{port}/health` → `{"status":"ok"}`. If unreachable, run `skillsmith doctor` from the skillsmith repo.
