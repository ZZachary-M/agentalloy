# Contract 2: skillsmith phase CLI Subcommand

## Objective

Create `src/skillsmith/install/subcommands/phase.py` implementing three actions (`get`, `set <phase>`, `clear`) and wire it into the CLI dispatcher in `src/skillsmith/install/__main__.py`.

## Pattern: Follow doctor.py Exactly

The implementation must follow the exact pattern from `src/skillsmith/install/subcommands/doctor.py`:

**doctor.py structure:**
- Module docstring describing the subcommand
- `from __future__ import annotations`
- Imports (argparse, sys, json, pathlib, etc.)
- `SCHEMA_VERSION = 1`
- Implementation function(s) (e.g., `run_doctor()`)
- `add_parser(subparsers)` — registers with argparse
- `_run(args)` — CLI entry point, calls implementation, outputs JSON, returns exit code

**Phase subcommand spec:**
- `skillsmith phase` (no sub-args) — print current phase from `.skillsmith/phase`
- `skillsmith phase set <phase>` — write/update the phase lock file
- `skillsmith phase clear` — remove `.skillsmith/phase` (reset to no phase)

## Phase Lock File Format

Location: `.skillsmith/phase` in the project root
Format: YAML (use `pyyaml` if available, otherwise write simple YAML manually)

```yaml
phase: build
started_at: "2026-05-16T21:00:00Z"
last_updated: "2026-05-16T21:30:00Z"
workflow: sdd-build
```

## Valid Phases

`spec`, `design`, `build`, `qa`, `ops`

Validate against this list. Reject invalid phases with a clear error listing valid options.

## Implementation Details

1. **`run_phase_get(root)`** — Read `.skillsmith/phase`, parse YAML, return current phase info. If file doesn't exist, return `{"phase": null, "message": "No active phase"}`.

2. **`run_phase_set(phase, root)`** — Validate phase, write `.skillsmith/phase` with timestamps. Create `.skillsmith/` directory if needed. If file exists, update `last_updated` and `phase` (preserve `started_at` from original).

3. **`run_phase_clear(root)`** — Delete `.skillsmith/phase` file. Return success message.

4. **`add_parser(subparsers)`** — Register `phase` subcommand with `set` and `clear` as sub-subcommands or positional args.

5. **`_run(args)`** — Route to appropriate function, output JSON to stdout, return exit code (0=success, 1=error).

## CLI Wiring

In `src/skillsmith/install/__main__.py`:

1. Add `phase` to the imports from `skillsmith.install.subcommands`
2. Add `phase` to the `_SUBCOMMANDS` list (place it near `doctor`, `status`, etc.)

**Existing main.py for reference:**

```python
from skillsmith.install.subcommands import (
    detect,
    doctor,
    # ... other imports ...
    wire_harness,
    write_env,
)

_SUBCOMMANDS = [
    preflight,
    setup,
    wire,
    # ... others ...
    doctor,
    # Add phase here
]

def build_parser():
    parser = argparse.ArgumentParser(...)
    subparsers = parser.add_subparsers(dest="subcommand")
    for mod in _SUBCOMMANDS:
        mod.add_parser(subparsers)
    return parser
```

## Acceptance Criteria

- `skillsmith phase set build` creates/updates `.skillsmith/phase` with correct YAML
- `skillsmith phase` prints current phase as JSON
- `skillsmith phase clear` removes `.skillsmith/phase`
- `skillsmith phase set invalid` rejects with error listing valid phases
- The subcommand is wired into `__main__.py` and accessible via `python -m skillsmith.install phase`
- `.skillsmith/` directory is created automatically if it doesn't exist
- Exit codes: 0 for success, 1 for errors
