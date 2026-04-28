"""``doctor`` subcommand — runtime health check.

Extends ``verify``'s 8 checks with 4 additional runtime checks:

 9. skillsmith_service_reachable
10. compose_endpoint_works
11. state_file_consistent
12. runner_processes_present
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from skillsmith.install import state as install_state
from skillsmith.install.subcommands.verify import run_checks as verify_checks

SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# Additional runtime checks (9–12)
# ---------------------------------------------------------------------------


def _check_service_reachable(port: int) -> dict[str, Any]:
    """Check 9: GET http://localhost:<port>/health returns 200 + status ok."""
    url = f"http://localhost:{port}/health"
    t0 = time.monotonic()
    try:
        req = Request(url, method="GET")
        with urlopen(req, timeout=10) as resp:  # noqa: S310
            body = json.loads(resp.read())
            duration = int((time.monotonic() - t0) * 1000)
            if body.get("status") == "ok":
                return {
                    "name": "skillsmith_service_reachable",
                    "passed": True,
                    "duration_ms": duration,
                    "detail": f"GET {url} → status ok",
                }
            return {
                "name": "skillsmith_service_reachable",
                "passed": False,
                "duration_ms": duration,
                "error": f"Unexpected response: {body}",
                "remediation": f"Start skillsmith: `uv run python -m skillsmith` or check port {port}",
            }
    except (URLError, OSError, json.JSONDecodeError) as exc:
        duration = int((time.monotonic() - t0) * 1000)
        return {
            "name": "skillsmith_service_reachable",
            "passed": False,
            "duration_ms": duration,
            "error": str(exc),
            "remediation": f"Start the service: `uv run python -m skillsmith`, or check that port {port} is correct",
        }


def _check_compose_endpoint(port: int) -> dict[str, Any]:
    """Check 10: POST /compose with a minimal request returns fragments."""
    url = f"http://localhost:{port}/compose"
    payload = json.dumps({"task": "write a unit test", "phase": "build"}).encode()
    t0 = time.monotonic()
    try:
        req = Request(
            url, data=payload, method="POST", headers={"Content-Type": "application/json"}
        )
        with urlopen(req, timeout=30) as resp:  # noqa: S310
            body = json.loads(resp.read())
            duration = int((time.monotonic() - t0) * 1000)
            if body.get("output"):
                return {
                    "name": "compose_endpoint_works",
                    "passed": True,
                    "duration_ms": duration,
                    "detail": f"POST /compose returned {len(body.get('source_skills', []))} source skills",
                }
            return {
                "name": "compose_endpoint_works",
                "passed": False,
                "duration_ms": duration,
                "error": "Empty output from /compose",
                "remediation": "Check that the corpus is loaded and the embedding endpoint is running",
            }
    except (URLError, OSError, json.JSONDecodeError) as exc:
        duration = int((time.monotonic() - t0) * 1000)
        return {
            "name": "compose_endpoint_works",
            "passed": False,
            "duration_ms": duration,
            "error": str(exc),
            "remediation": "Ensure skillsmith is running and the embedding endpoint is reachable",
        }


def _check_state_consistent(st: dict[str, Any]) -> dict[str, Any]:
    """Check 11: install-state.json is present and internally consistent."""
    t0 = time.monotonic()
    warnings: list[str] = []

    if not st.get("completed_steps"):
        duration = int((time.monotonic() - t0) * 1000)
        return {
            "name": "state_file_consistent",
            "passed": False,
            "duration_ms": duration,
            "error": "No completed steps in install state",
            "remediation": "Run the install flow from the beginning: follow INSTALL.md",
        }

    # Check harness files still have matching sentinels
    for entry in st.get("harness_files_written", []):
        path = Path(entry.get("path", ""))
        if not path.exists():
            warnings.append(f"Harness file missing: {path}")
            continue
        content = path.read_text()
        sentinel = entry.get("sentinel_begin", "")
        if sentinel and sentinel not in content:
            warnings.append(f"Sentinel block missing from {path}")

    duration = int((time.monotonic() - t0) * 1000)
    detail = "State file consistent"
    if warnings:
        detail += f" (warnings: {'; '.join(warnings)})"
    return {
        "name": "state_file_consistent",
        "passed": True,
        "duration_ms": duration,
        "detail": detail,
    }


def _check_runner_processes(st: dict[str, Any]) -> dict[str, Any]:
    """Check 12: expected runner processes are running."""
    t0 = time.monotonic()
    models_pulled = st.get("models_pulled", [])

    # Map runner names to process names to check
    runner_process_map = {
        "ollama": "ollama",
        "fastflowlm": "flm",
    }
    known_runners = frozenset(runner_process_map.keys())

    runners_needed: set[str] = set()
    malformed: list[str] = []
    for entry in models_pulled:
        if not isinstance(entry, str) or ":" not in entry:
            malformed.append(str(entry))
            continue
        runner = entry.split(":", 1)[0]
        if runner not in known_runners:
            malformed.append(entry)
            continue
        runners_needed.add(runner)

    missing: list[str] = []
    skipped: list[str] = []

    for runner in runners_needed:
        proc_name = runner_process_map[runner]
        binary = shutil.which(proc_name)
        if not binary:
            missing.append(f"{proc_name} not in PATH")
            continue
        # Check if process is running via pgrep. On Windows or systems
        # without pgrep, mark the check as skipped — passing silently
        # would falsely greenlight a system where the runner isn't up.
        try:
            result = subprocess.run(  # noqa: S603 — fixed args, no shell
                ["pgrep", "-x", proc_name],
                capture_output=True,
                timeout=5,
            )
            if result.returncode != 0:
                missing.append(f"{proc_name} not running")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            skipped.append(proc_name)

    duration = int((time.monotonic() - t0) * 1000)
    if missing:
        return {
            "name": "runner_processes_present",
            "passed": False,
            "duration_ms": duration,
            "error": "; ".join(missing),
            "remediation": "Start the model runners: `ollama serve` and/or `flm serve`",
        }
    if malformed:
        return {
            "name": "runner_processes_present",
            "passed": False,
            "duration_ms": duration,
            "error": f"Malformed models_pulled entries (expected 'runner:model'): {malformed}",
            "remediation": (
                "Run `python -m skillsmith.install reset-step pull-models` then "
                "re-run pull-models to rebuild state."
            ),
        }
    detail_parts: list[str] = []
    if runners_needed:
        detail_parts.append(f"runners present: {', '.join(sorted(runners_needed))}")
    else:
        detail_parts.append("no runners configured")
    if skipped:
        detail_parts.append(
            f"process check skipped (pgrep unavailable): {', '.join(sorted(skipped))}"
        )
    return {
        "name": "runner_processes_present",
        "passed": True,
        "duration_ms": duration,
        "detail": "; ".join(detail_parts),
    }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def run_doctor(root: Path | None = None) -> dict[str, Any]:
    """Run all 12 checks (verify's 8 + doctor's 4)."""
    from skillsmith.install.state import _repo_root  # pyright: ignore[reportPrivateUsage]

    root = root or _repo_root()
    st = install_state.load_state(root)
    port = install_state.validate_port(st.get("port", 47950))

    # Run verify's 8 checks
    verify_result = verify_checks(st, root)
    checks = list(verify_result["checks"])

    # Add doctor's 4 additional checks
    checks.append(_check_service_reachable(port))
    checks.append(_check_compose_endpoint(port))
    checks.append(_check_state_consistent(st))
    checks.append(_check_runner_processes(st))

    all_passed = all(c["passed"] for c in checks)
    return {
        "schema_version": SCHEMA_VERSION,
        "all_checks_passed": all_passed,
        "checks": checks,
    }


# ---------------------------------------------------------------------------
# Subcommand interface
# ---------------------------------------------------------------------------


def add_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
) -> None:
    p: argparse.ArgumentParser = subparsers.add_parser(
        "doctor",
        help="Runtime health check across all components.",
    )
    p.set_defaults(func=_run)


def _run(args: argparse.Namespace) -> int:
    result = run_doctor()
    install_state.save_output_file(result, "doctor.json")
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")

    if not result["all_checks_passed"]:
        failed = [c for c in result["checks"] if not c["passed"]]
        print(f"\n{len(failed)} check(s) failed:", file=sys.stderr)
        for c in failed:
            # ASCII marker — Windows legacy code pages reject ✗ and crash
            # the failure-reporting path before the user sees the summary.
            print(f"  FAIL {c['name']}: {c.get('error', 'unknown')}", file=sys.stderr)
            if c.get("remediation"):
                print(f"    FIX: {c['remediation']}", file=sys.stderr)
        return 1
    return 0
