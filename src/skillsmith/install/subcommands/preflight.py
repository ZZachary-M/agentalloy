"""``preflight`` subcommand — verify host prerequisites before any install step.

Two phases:

- ``early`` (default): host-agnostic checks that gate the rest of the
  install: Python version, ``uv`` on PATH, the ``skillsmith`` CLI on
  PATH (so the runbook LLM doesn't sail past a missing ``~/.local/bin``
  entry), XDG dirs writable, network reachable, default port free.
- ``runner``: runner-specific checks (currently Ollama). Run after
  ``recommend-models`` so we know which runner was selected.

Exit codes follow the project contract (see
``skillsmith.install.__main__``):

    0  all checks passed
    1  one or more user-correctable checks failed
    2  unexpected exception (re-raised by the dispatcher)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from skillsmith.install import state as install_state

SCHEMA_VERSION = 1

_DEFAULT_PORT = 47950
_PHASES = ("early", "runner")


def _check(
    name: str,
    *,
    passed: bool,
    started: float,
    detail: str | None = None,
    error: str | None = None,
    remediation: str | None = None,
    severity: str = "fatal",
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "name": name,
        "passed": passed,
        "severity": severity,
        "duration_ms": int((time.monotonic() - started) * 1000),
    }
    if detail:
        out["detail"] = detail
    if error:
        out["error"] = error
    if remediation:
        out["remediation"] = remediation
    return out


# ---------------------------------------------------------------------------
# Early-phase checks
# ---------------------------------------------------------------------------


def _check_python_version() -> dict[str, Any]:
    t0 = time.monotonic()
    v = sys.version_info
    if v >= (3, 12):
        return _check(
            "python_version",
            passed=True,
            started=t0,
            detail=f"Python {v.major}.{v.minor}.{v.micro}",
        )
    return _check(
        "python_version",
        passed=False,
        started=t0,
        error=f"Python {v.major}.{v.minor}.{v.micro} < 3.12",
        remediation="Install Python 3.12+ (e.g. via mise, pyenv, or your OS package manager).",
    )


def _check_uv_present() -> dict[str, Any]:
    t0 = time.monotonic()
    binary = shutil.which("uv")
    if binary:
        return _check("uv_present", passed=True, started=t0, detail=f"uv at {binary}")
    return _check(
        "uv_present",
        passed=False,
        started=t0,
        error="uv not found on PATH",
        remediation=(
            "Install uv: see https://docs.astral.sh/uv/getting-started/installation/. "
            "Do not auto-execute the install script — confirm with the user first."
        ),
    )


def _path_entries() -> list[str]:
    return [p for p in os.environ.get("PATH", "").split(os.pathsep) if p]


def _check_cli_on_path() -> dict[str, Any]:
    """Verify ``skillsmith`` resolves and the canonical user-bin dir is on PATH.

    The runbook hard-stops here because every later step shells out to
    ``skillsmith ...`` from the user's repo cwd; a missing PATH entry
    silently routes through ``~/.local/bin/skillsmith`` only when the
    LLM happens to use the absolute path, which it shouldn't.
    """
    t0 = time.monotonic()
    binary = shutil.which("skillsmith")
    home = Path.home()
    expected = str(home / ".local" / "bin")
    on_path = expected in _path_entries()

    if binary and on_path:
        return _check(
            "cli_on_path",
            passed=True,
            started=t0,
            detail=f"skillsmith at {binary}; {expected} on PATH",
        )

    parts: list[str] = []
    if not binary:
        parts.append("`skillsmith` not resolvable on PATH")
    if not on_path:
        parts.append(f"{expected} not in PATH")
    error = "; ".join(parts)

    remediation = (
        f"Add this line to your shell profile (~/.bashrc, ~/.zshrc) and "
        f'restart the shell:\n\n    export PATH="{expected}:$PATH"\n\n'
        f"Then re-run `skillsmith preflight`. If `uv tool install --editable .` "
        f"has not been run yet, run it first."
    )
    return _check(
        "cli_on_path",
        passed=False,
        started=t0,
        error=error,
        remediation=remediation,
    )


def _check_xdg_dirs_writable() -> dict[str, Any]:
    t0 = time.monotonic()
    config_home = (
        Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")) / "skillsmith"
    )
    data_home = (
        Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")) / "skillsmith"
    )

    problems: list[str] = []
    for d in (config_home, data_home):
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            problems.append(f"cannot create {d}: {exc}")
            continue
        if not os.access(d, os.W_OK):
            problems.append(f"{d} not writable")

    if problems:
        return _check(
            "xdg_dirs_writable",
            passed=False,
            started=t0,
            error="; ".join(problems),
            remediation=(
                "Ensure your user owns these directories: "
                f"`chown -R $USER {config_home} {data_home}` "
                "and that the parent dirs exist."
            ),
        )
    return _check(
        "xdg_dirs_writable",
        passed=True,
        started=t0,
        detail=f"writable: {config_home}, {data_home}",
    )


def _check_network_reachable() -> dict[str, Any]:
    """HEAD https://github.com — required for model + (some) pack downloads."""
    t0 = time.monotonic()
    try:
        req = Request("https://github.com", method="HEAD")
        with urlopen(req, timeout=3) as resp:  # noqa: S310 — fixed URL
            status = getattr(resp, "status", 200)
    except (URLError, OSError) as exc:
        return _check(
            "network_reachable",
            passed=False,
            started=t0,
            severity="warn",
            error=f"HEAD https://github.com failed: {exc}",
            remediation=(
                "Check network / proxy settings. Offline installs can still "
                "complete with locally-cached models, but pack manifest "
                "downloads will fail."
            ),
        )
    return _check(
        "network_reachable",
        passed=True,
        started=t0,
        detail=f"github.com reachable (HTTP {status})",
    )


def _check_port_free(port: int) -> dict[str, Any]:
    t0 = time.monotonic()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.5)
    try:
        sock.bind(("127.0.0.1", port))
    except OSError as exc:
        return _check(
            "port_free",
            passed=False,
            started=t0,
            severity="warn",
            error=f"port {port} in use: {exc}",
            remediation=(
                f"Either stop the process bound to {port}, or pass "
                f"`--port <n>` to `skillsmith write-env` later."
            ),
        )
    finally:
        sock.close()
    return _check("port_free", passed=True, started=t0, detail=f"port {port} free")


# ---------------------------------------------------------------------------
# Runner-phase checks
# ---------------------------------------------------------------------------


def _check_ollama_present() -> dict[str, Any]:
    t0 = time.monotonic()
    binary = shutil.which("ollama")
    if binary:
        return _check("ollama_present", passed=True, started=t0, detail=f"ollama at {binary}")
    return _check(
        "ollama_present",
        passed=False,
        started=t0,
        error="ollama not found on PATH",
        remediation=(
            "Install Ollama:\n"
            "  Linux:   curl -fsSL https://ollama.com/install.sh | sh\n"
            "  macOS:   brew install ollama (or https://ollama.com/download/mac)\n"
            "  Windows: https://ollama.com/download\n"
            "Do not auto-execute — confirm with the user first."
        ),
    )


def _check_ollama_reachable() -> dict[str, Any]:
    t0 = time.monotonic()
    url = "http://localhost:11436/api/tags"
    try:
        req = Request(url, method="GET")
        with urlopen(req, timeout=2) as resp:  # noqa: S310 — fixed URL
            _ = resp.read(1)
    except (URLError, OSError) as exc:
        return _check(
            "ollama_reachable",
            passed=False,
            started=t0,
            error=f"GET {url} failed: {exc}",
            remediation=(
                "Start the Ollama daemon: `ollama serve` (Linux), or use the "
                "menubar app (macOS/Windows). Re-run preflight once "
                "`curl -s http://localhost:11436/api/tags` returns JSON."
            ),
        )
    return _check("ollama_reachable", passed=True, started=t0, detail=f"GET {url} ok")


def _check_fastflowlm_present() -> dict[str, Any]:
    t0 = time.monotonic()
    binary = shutil.which("flm")
    if binary:
        return _check("fastflowlm_present", passed=True, started=t0, detail=f"flm at {binary}")
    return _check(
        "fastflowlm_present",
        passed=False,
        started=t0,
        error="flm not found on PATH",
        remediation="Install FastFlowLM and ensure `flm` is on PATH.",
    )


# ---------------------------------------------------------------------------
# Phase orchestration
# ---------------------------------------------------------------------------


def _runner_from_models_output() -> str | None:
    """Read the chosen runner from recommend-models.json, if present."""
    fp = install_state.outputs_dir() / "recommend-models.json"
    if not fp.exists():
        return None
    try:
        data = json.loads(fp.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    return data.get("embed_runner") or data.get("runner")


def run_preflight(
    *, phase: str = "early", runner: str | None = None, port: int = _DEFAULT_PORT
) -> dict[str, Any]:
    if phase not in _PHASES:
        raise ValueError(f"invalid phase {phase!r}; must be one of {_PHASES}")

    t0 = time.monotonic()
    checks: list[dict[str, Any]] = []

    if phase == "early":
        checks.append(_check_python_version())
        checks.append(_check_uv_present())
        checks.append(_check_cli_on_path())
        checks.append(_check_xdg_dirs_writable())
        checks.append(_check_network_reachable())
        checks.append(_check_port_free(port))
    else:  # runner
        chosen = runner or _runner_from_models_output()
        if chosen is None:
            checks.append(
                _check(
                    "runner_selected",
                    passed=False,
                    started=t0,
                    error=(
                        "no runner specified and recommend-models output "
                        "not found at "
                        f"{install_state.outputs_dir() / 'recommend-models.json'}"
                    ),
                    remediation=(
                        "Run `skillsmith recommend-models` first, or pass "
                        "`--runner <ollama|fastflowlm>` explicitly."
                    ),
                )
            )
        elif chosen == "ollama":
            checks.append(_check_ollama_present())
            checks.append(_check_ollama_reachable())
        elif chosen == "fastflowlm":
            checks.append(_check_fastflowlm_present())
        else:
            checks.append(
                _check(
                    "runner_supported",
                    passed=True,
                    started=t0,
                    severity="warn",
                    detail=(
                        f"runner {chosen!r} has no preflight coverage "
                        "(manual-pull runner: LM Studio, MLX, vLLM)"
                    ),
                )
            )

    fatal_failed = [c for c in checks if not c["passed"] and c.get("severity", "fatal") == "fatal"]
    warn_failed = [c for c in checks if not c["passed"] and c.get("severity") == "warn"]

    return {
        "schema_version": SCHEMA_VERSION,
        "action": "preflight" if not fatal_failed else "preflight_failed",
        "phase": phase,
        "runner": runner if phase == "runner" else None,
        "all_checks_passed": not fatal_failed and not warn_failed,
        "fatal_failures": [c["name"] for c in fatal_failed],
        "warn_failures": [c["name"] for c in warn_failed],
        "checks": checks,
        "duration_ms": int((time.monotonic() - t0) * 1000),
    }


# ---------------------------------------------------------------------------
# Subcommand interface
# ---------------------------------------------------------------------------


def add_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
) -> None:
    p: argparse.ArgumentParser = subparsers.add_parser(
        "preflight",
        help=(
            "Verify host prerequisites (uv, PATH, network, runner) before "
            "running install steps. Run this first, every time."
        ),
    )
    p.add_argument(
        "--phase",
        choices=_PHASES,
        default="early",
        help="Which phase of checks to run (default: early).",
    )
    p.add_argument(
        "--runner",
        default=None,
        help=(
            "Runner-phase only: which runner to validate. If omitted, read "
            "from recommend-models.json output."
        ),
    )
    p.add_argument(
        "--port",
        type=int,
        default=_DEFAULT_PORT,
        help=f"Port to test for availability (default: {_DEFAULT_PORT}).",
    )
    p.set_defaults(func=_run)


def _run(args: argparse.Namespace) -> int:
    result = run_preflight(phase=args.phase, runner=args.runner, port=args.port)
    install_state.save_output_file(result, f"preflight-{args.phase}.json")
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")

    fatal = [c for c in result["checks"] if not c["passed"] and c.get("severity") == "fatal"]
    warns = [c for c in result["checks"] if not c["passed"] and c.get("severity") == "warn"]

    if fatal:
        print(f"\npreflight ({args.phase}): {len(fatal)} fatal check(s) failed:", file=sys.stderr)
        for c in fatal:
            print(f"  FAIL {c['name']}: {c.get('error', 'unknown')}", file=sys.stderr)
            if c.get("remediation"):
                for line in c["remediation"].splitlines():
                    print(f"    FIX: {line}" if line.strip() else "", file=sys.stderr)
        print(
            "\nDO NOT continue with `skillsmith setup` or any install step "
            "until every fatal check above is resolved.",
            file=sys.stderr,
        )
        return 1

    if warns:
        print(
            f"\npreflight ({args.phase}): {len(warns)} warning(s) — "
            "non-fatal, install can proceed:",
            file=sys.stderr,
        )
        for c in warns:
            print(f"  WARN {c['name']}: {c.get('error', '')}", file=sys.stderr)

    return 0
