# Skillsmith — skill context

A local skillsmith service runs at http://localhost:{port}. **Before starting any task** (spec, design, build, test, debug), POST to /compose/text with `{"task":"...", "phase":"build|spec|design|qa|ops"}`. The response is plain text — read it before generating code or a plan.
