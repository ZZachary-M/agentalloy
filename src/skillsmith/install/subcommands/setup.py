"""``setup`` verb — one-shot user-scope install.

Composes the existing subcommand surface into a single command:
``detect → recommend-host-targets → recommend-models → pull-models →
seed-corpus → write-env → enable-service``. Stops on the first non-zero
exit (other than the documented EXIT_NOOP=4 idempotent skip). Each
step's already-existing stdout JSON is preserved so the runbook LLM (or
operator) can read each result.

Note: ``wire-harness`` is intentionally NOT part of setup. Wiring is
per-repo and runs separately via ``skillsmith wire`` from inside each
repo. Setup is the one-time global ceremony.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any

from skillsmith.install import state as install_state

SCHEMA_VERSION = 1

_INTERACTIVE = sys.stdin.isatty()

_SETUP_STEPS = (
    ("detect", "skillsmith.install.subcommands.detect"),
    ("recommend-host-targets", "skillsmith.install.subcommands.recommend_host_targets"),
    ("recommend-models", "skillsmith.install.subcommands.recommend_models"),
    ("pull-models", "skillsmith.install.subcommands.pull_models"),
    ("seed-corpus", "skillsmith.install.subcommands.seed_corpus"),
    ("write-env", "skillsmith.install.subcommands.write_env"),
    ("enable-service", "skillsmith.install.subcommands.enable_service"),
)


def add_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
) -> None:
    p: argparse.ArgumentParser = subparsers.add_parser(
        "setup",
        help="One-shot user-scope install: detect → recommend → pull → seed → env → enable-service.",
    )
    p.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Don't stop at the first failed step — run all steps and report at the end.",
    )
    p.set_defaults(func=_run)


def _run(args: argparse.Namespace) -> int:
    """Run the setup composer.

    Each step is invoked via its own argparse-compatible ``add_parser``
    function — we look up the step's module and call its registered
    handler so behavior stays identical to the standalone subcommand.
    """
    t0 = time.monotonic()
    results: list[dict[str, Any]] = []
    failed_steps: list[str] = []

    print("skillsmith setup: starting user-scope install", file=sys.stderr, flush=True)

    for step_name, module_path in _SETUP_STEPS:
        print(f"  → {step_name}", file=sys.stderr, flush=True)
        # Prerequisite check: a step that needs an upstream output file
        # gets a clear "skipping — upstream X missing" rather than an
        # opaque argparse "argument --host: required" error when
        # --continue-on-error is set.
        missing_prereq = _missing_prereq(step_name)
        if missing_prereq:
            print(
                f"    skipping {step_name}: prerequisite output {missing_prereq} "
                f"not found (upstream step likely failed).",
                file=sys.stderr,
            )
            results.append({"step": step_name, "exit_code": 1, "skipped": True})
            failed_steps.append(step_name)
            if not getattr(args, "continue_on_error", False):
                break
            continue
        exit_code = _invoke_step(step_name, module_path, args)
        results.append({"step": step_name, "exit_code": exit_code})
        if exit_code not in (0, 4):  # 4 = EXIT_NOOP idempotent skip
            failed_steps.append(step_name)
            if not getattr(args, "continue_on_error", False):
                break

    duration_ms = int((time.monotonic() - t0) * 1000)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "action": "setup_complete" if not failed_steps else "setup_failed",
        "steps": results,
        "failed_steps": failed_steps,
        "duration_ms": duration_ms,
    }
    install_state.save_output_file(summary, "setup.json")
    json.dump(summary, sys.stdout, indent=2)
    sys.stdout.write("\n")

    if failed_steps:
        print(
            f"\nsetup: {len(failed_steps)} step(s) failed: {', '.join(failed_steps)}",
            file=sys.stderr,
        )
        print(
            "FIX:   Inspect the per-step output above and re-run that step "
            "directly via `python -m skillsmith.install <step>`.",
            file=sys.stderr,
        )
        return 1
    return 0


def _invoke_step(step_name: str, module_path: str, parent_args: argparse.Namespace) -> int:
    """Invoke a subcommand via its registered argparse `add_parser` function.

    We build a fresh argparse parser, register the step's parser into it,
    parse a synthetic argv that targets that step, then dispatch. This
    keeps the step's exit-code semantics identical to invoking it
    standalone — no special-casing per step.
    """
    import importlib

    mod = importlib.import_module(module_path)
    parser = argparse.ArgumentParser(prog=f"skillsmith install {step_name}")
    subparsers = parser.add_subparsers(dest="subcommand")
    mod.add_parser(subparsers)

    argv = _argv_for_step(step_name, parent_args)
    try:
        step_args = parser.parse_args(argv)
    except SystemExit as exc:
        # argparse's auto-exit on parse failure
        return exc.code if isinstance(exc.code, int) else 2

    try:
        rc = step_args.func(step_args)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    except Exception as exc:  # noqa: BLE001 — the composer must keep going
        # Subprocess / file IO / validation errors that the underlying
        # step didn't translate into SystemExit. Without this catch the
        # composer crashes mid-pipeline and `--continue-on-error` becomes
        # a lie.
        print(
            f"setup: step '{step_name}' raised {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 2
    # A step that returns None (rather than 0/1/...) is a bug in that
    # step, but treat it as success so the composer doesn't crash on
    # `int` arithmetic later.
    return rc if isinstance(rc, int) else 0


def _argv_for_step(step_name: str, parent_args: argparse.Namespace) -> list[str]:
    """Build the argv slice each step's subparser expects.

    Most steps need composed inputs threaded from the previous step's
    saved output JSON. Setup keeps the wiring narrow — operators who
    need flag overrides run individual steps standalone.
    """
    _ = parent_args  # reserved for future per-step flag passthrough
    outputs = install_state.outputs_dir()
    if step_name == "recommend-host-targets":
        return [step_name, "--hardware", str(outputs / "detect.json")]
    if step_name == "recommend-models":
        host = _read_recommended_host()
        if host is None:
            # recommend-host-targets failed or didn't write its file;
            # let recommend-models's required-arg failure surface a
            # clear error.
            return [step_name]
        return [
            step_name,
            "--hardware",
            str(outputs / "detect.json"),
            "--host",
            host,
        ]
    if step_name == "pull-models":
        return [step_name, "--models", str(outputs / "recommend-models.json")]
    if step_name == "write-env":
        preset = _read_preset()
        if preset is None:
            # Fall through with a placeholder so argparse's choices error
            # surfaces clearly rather than us guessing wrong.
            return [step_name]
        return [step_name, "--preset", preset]
    if step_name == "enable-service":
        # enable-service has interactive prompts. In a non-TTY environment
        # (CI, piped invocation) default to manual so setup doesn't hang
        # waiting for input that will never come.
        if not _INTERACTIVE:
            return [step_name, "--mode", "manual"]
        return [step_name]
    return [step_name]


_PREREQS: dict[str, tuple[str, ...]] = {
    "recommend-host-targets": ("detect.json",),
    "recommend-models": ("detect.json", "recommend-host-targets.json"),
    "pull-models": ("recommend-models.json",),
    "write-env": ("recommend-models.json",),
}


def _missing_prereq(step_name: str) -> str | None:
    """Return the path of a missing upstream output file, or None if the
    step has all its prerequisites in place."""
    outputs = install_state.outputs_dir()
    for fname in _PREREQS.get(step_name, ()):
        fp = outputs / fname
        if not fp.exists():
            return str(fp)
    return None


def _read_recommended_host() -> str | None:
    """Read the `recommended: true` target name from recommend-host-targets."""
    fp = install_state.outputs_dir() / "recommend-host-targets.json"
    if not fp.exists():
        return None
    try:
        data = json.loads(fp.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    for target in data.get("targets", []):
        if target.get("recommended"):
            return target.get("target")
    return None


def _read_preset() -> str | None:
    """Read the preset name from recommend-models output."""
    fp = install_state.outputs_dir() / "recommend-models.json"
    if not fp.exists():
        return None
    try:
        data = json.loads(fp.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    return data.get("preset")
