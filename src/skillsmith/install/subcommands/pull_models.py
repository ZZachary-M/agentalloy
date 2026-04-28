"""``pull-models`` subcommand.

Idempotent model pulls for the runners selected by ``recommend-models``.

Auto-pull runners (``ollama``, ``fastflowlm``): invokes the CLI pull
command and reports duration + size.

Manual-pull runners (``lmstudio``, ``vllm``, ``mlx``): emits human-readable
instructions for the runbook to surface.  No subprocess call.

Reads the ``recommend-models`` JSON output (either from a file path or
from ``install-state.json``) to determine which models and runners to
pull.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from skillsmith.install import state as install_state

SCHEMA_VERSION = 1
STEP_NAME = "pull-models"

# Runners that support CLI-driven auto-pull.
_AUTO_PULL_RUNNERS: dict[str, tuple[str, list[str]]] = {
    # runner_name -> (binary, [pull, <model> is appended])
    "ollama": ("ollama", ["pull"]),
    "fastflowlm": ("flm", ["pull"]),
}

# Manual-pull runners with instruction templates.
_MANUAL_INSTRUCTIONS: dict[str, str] = {
    "lmstudio": ("Open LM Studio, search for '{model}', click Download. Confirm when complete."),
    "vllm": (
        "vLLM loads models on `vllm serve`. Ensure '{model}' is "
        "accessible (Hugging Face login if gated). No explicit pull needed."
    ),
    "mlx": (
        "Run `mlx_lm.convert --hf-path {model}` to convert for MLX, "
        "or download the MLX-format weights from Hugging Face."
    ),
}


# ---------------------------------------------------------------------------
# Runner presence checks
# ---------------------------------------------------------------------------


def _is_model_present_ollama(model: str) -> bool:
    """Check if a model is already pulled in Ollama."""
    binary = shutil.which("ollama")
    if not binary:
        return False
    try:
        result = subprocess.run(
            [binary, "list"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return False
        # ollama list output: NAME  ID  SIZE  MODIFIED
        # Model names may include tags; match on the name prefix.
        for line in result.stdout.splitlines()[1:]:  # skip header
            name = line.split()[0] if line.strip() else ""
            # Exact match or match without :latest tag
            if name == model or name == f"{model}:latest":
                return True
            # Also match if model has a tag and the listed name matches
            if ":" in model and name.startswith(model.split(":")[0]):
                listed_tag = name.split(":")[-1] if ":" in name else "latest"
                requested_tag = model.split(":")[-1]
                if listed_tag == requested_tag:
                    return True
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return False


def _is_model_present_fastflowlm(model: str) -> bool:
    """Check if a model is loaded in FastFlowLM."""
    binary = shutil.which("flm")
    if not binary:
        return False
    try:
        result = subprocess.run(
            [binary, "list"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return False
        return model in result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return False


_PRESENCE_CHECKS: dict[str, Any] = {
    "ollama": _is_model_present_ollama,
    "fastflowlm": _is_model_present_fastflowlm,
}


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def _collect_model_runner_pairs(option: dict[str, Any]) -> list[tuple[str, str]]:
    """Extract unique (model, runner) pairs from a recommend-models option."""
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for model_key, runner_key in (("embed_model", "embed_runner"),):
        model = option.get(model_key, "")
        runner = option.get(runner_key, "")
        if model and runner and (model, runner) not in seen:
            pairs.append((model, runner))
            seen.add((model, runner))
    return pairs


# Strict model-name pattern. Allowed characters cover the canonical
# `name:tag` form used by ollama/fastflowlm (letters, digits, `_`, `-`,
# `.`, `:`, `/` for org/repo namespaces). Rejects anything that could
# look like a CLI option (leading `-`) or carry shell metacharacters
# even though we run with shell=False — option-injection (e.g. model
# name `--insecure-tls`) is still effective via argv.
_MODEL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/\-]{0,127}$")


def _auto_pull(runner: str, model: str) -> dict[str, Any]:
    """Run the pull command for an auto-pull runner. Returns result dict."""
    binary_name, pull_args = _AUTO_PULL_RUNNERS[runner]
    if not _MODEL_NAME_RE.match(model):
        return {
            "runner": runner,
            "model": model,
            "success": False,
            "error": f"Refusing to pull model name with disallowed characters: {model!r}",
            "hint": "Model names must match [A-Za-z0-9][A-Za-z0-9._:/-]{0,127}.",
        }
    binary = shutil.which(binary_name)
    if not binary:
        hint = f"Install {binary_name} first."
        if runner == "ollama":
            hint = (
                "Install Ollama first (do NOT auto-execute — ask the user). "
                "Linux: `curl -fsSL https://ollama.com/install.sh | sh`. "
                "macOS: `brew install ollama` or https://ollama.com/download/mac. "
                "Other platforms: https://ollama.com/download. "
                "After install, ensure `ollama serve` is running, then re-run pull-models."
            )
        return {
            "runner": runner,
            "model": model,
            "success": False,
            "error": f"{binary_name} not found in PATH",
            "hint": hint,
        }

    # `--` separator prevents argv option-injection if model name slipped
    # through the regex (defense in depth) or future regex relaxations
    # admit a leading-`-` form.
    cmd = [binary, *pull_args, "--", model]
    t0 = time.monotonic()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,  # 10 min for large model downloads
        )
        duration_ms = int((time.monotonic() - t0) * 1000)
        if result.returncode != 0:
            return {
                "runner": runner,
                "model": model,
                "success": False,
                "error": result.stderr.strip() or f"exit code {result.returncode}",
                "duration_ms": duration_ms,
            }
        return {
            "runner": runner,
            "model": model,
            "success": True,
            "duration_ms": duration_ms,
        }
    except subprocess.TimeoutExpired:
        return {
            "runner": runner,
            "model": model,
            "success": False,
            "error": "Pull timed out after 600 seconds",
        }
    except OSError as exc:
        return {
            "runner": runner,
            "model": model,
            "success": False,
            "error": str(exc),
        }


def pull_models(
    models_json: dict[str, Any],
    root: Path | None = None,
) -> dict[str, Any]:
    """Pull models based on recommend-models output.

    Returns contract-shaped JSON with auto_pulled, manual_steps_required,
    and skipped_already_present arrays.
    """
    from skillsmith.install.state import _repo_root  # pyright: ignore[reportPrivateUsage]

    root = root or _repo_root()

    # Idempotency: skip if already done
    st = install_state.load_state(root)
    if install_state.is_step_completed(st, STEP_NAME):
        prev = install_state.get_step_output(st, STEP_NAME)
        json.dump(prev.get("output", {}) if prev else {}, sys.stdout, indent=2)
        sys.stdout.write("\n")
        raise SystemExit(4)

    # Extract the default option (or first option)
    options = models_json.get("options", [])
    if not options:
        print("ERROR: No model options in recommend-models output", file=sys.stderr)
        raise SystemExit(1)

    option = next((o for o in options if o.get("default")), options[0])
    pairs = _collect_model_runner_pairs(option)

    auto_pulled: list[dict[str, Any]] = []
    manual_steps: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for model, runner in pairs:
        # Check presence for auto-pull runners
        presence_fn = _PRESENCE_CHECKS.get(runner)
        if presence_fn and presence_fn(model):
            skipped.append({"runner": runner, "model": model})
            continue

        if runner in _AUTO_PULL_RUNNERS:
            result = _auto_pull(runner, model)
            if result.get("success"):
                auto_pulled.append(
                    {
                        "runner": runner,
                        "model": model,
                        "duration_ms": result.get("duration_ms", 0),
                    }
                )
            else:
                errors.append(result)
        elif runner in _MANUAL_INSTRUCTIONS:
            manual_steps.append(
                {
                    "runner": runner,
                    "model": model,
                    "instruction": _MANUAL_INSTRUCTIONS[runner].format(model=model),
                }
            )
        else:
            print(f"WARNING: Unknown runner '{runner}' for model '{model}'", file=sys.stderr)
            manual_steps.append(
                {
                    "runner": runner,
                    "model": model,
                    "instruction": f"Manually install model '{model}' using runner '{runner}'.",
                }
            )

    output: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "auto_pulled": auto_pulled,
        "manual_steps_required": manual_steps,
        "skipped_already_present": skipped,
    }

    if errors:
        output["errors"] = errors
        # Print errors but don't fail — let the runbook decide
        for err in errors:
            print(
                f"ERROR: Failed to pull {err.get('model', '?')} via {err.get('runner', '?')}: {err.get('error', 'unknown')}",
                file=sys.stderr,
            )
        # Don't record completion when any pull failed — otherwise the
        # idempotency check will permanently skip this step on rerun and
        # the user has no path to retry without `reset-step pull-models`.
        return output

    # Record step (only when every pull either succeeded or was already present)
    st = install_state.record_step(st, STEP_NAME, extra={"output": output})
    # Track which models were pulled for uninstall reference
    st["models_pulled"] = [f"{p['runner']}:{p['model']}" for p in auto_pulled] + [
        f"{s['runner']}:{s['model']}" for s in skipped
    ]
    install_state.save_state(st, root)

    return output


# ---------------------------------------------------------------------------
# Subcommand interface
# ---------------------------------------------------------------------------


def add_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
) -> None:
    p: argparse.ArgumentParser = subparsers.add_parser(
        "pull-models",
        help="Idempotent model pulls for selected runners.",
    )
    p.add_argument(
        "--models",
        required=True,
        help="Path to the recommend-models JSON output file.",
    )
    p.set_defaults(func=_run)


def _run(args: argparse.Namespace) -> int:
    models_path = Path(args.models)
    if not models_path.exists():
        print(f"ERROR: Models file not found: {models_path}", file=sys.stderr)
        print("CAUSE: The recommend-models output file is missing.", file=sys.stderr)
        print("FIX:   Run `recommend-models` first, or pass the correct path.", file=sys.stderr)
        return 1

    models_json = json.loads(models_path.read_text())
    result = pull_models(models_json)
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")

    # Non-zero exit if there were pull errors
    if result.get("errors"):
        return 1
    return 0
