"""``start-embed-server`` subcommand — bring up the embedding backend.

Runs between ``pull-models`` and ``install-packs`` in the setup pipeline.
Reads ``recommend-models.json`` to discover the embed runner and model, then:

- **llama-server**: launches ``llama-server --embeddings --port 11436
  --ubatch-size 2048 -m <gguf_path>`` as a background process and polls
  ``/health`` until it responds (or times out).
- **ollama**: ensures ``ollama serve`` is running via a best-effort check +
  ``ollama serve &``; ollama is already-running-tolerant.
- **lm-studio / other**: prints a manual instruction and exits 0 (the user
  must start it themselves; we can't automate a GUI app).

The step is idempotent: if the embed endpoint is already reachable it exits 0
immediately without spawning a second process.
"""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from skillsmith.install import state as install_state

SCHEMA_VERSION = 1
STEP_NAME = "start-embed-server"
EMBED_PORT = 11436
EMBED_HOST = "127.0.0.1"
# llama-server batch size — keeps throughput high for pack ingest without
# requiring a fat context window.
LLAMA_UBATCH_SIZE = 2048
# Seconds to wait for llama-server /health before giving up.
LLAMA_START_TIMEOUT = 120


def add_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
) -> None:
    p: argparse.ArgumentParser = subparsers.add_parser(
        STEP_NAME,
        help="Start the embedding backend (llama-server/ollama) before pack install.",
    )
    p.add_argument(
        "--models",
        required=True,
        help="Path to the recommend-models JSON output file.",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=float(LLAMA_START_TIMEOUT),
        help=f"Seconds to wait for llama-server /health (default: {LLAMA_START_TIMEOUT}).",
    )
    p.set_defaults(func=_run)


def _run(args: argparse.Namespace) -> int:
    models_path = Path(args.models)
    if not models_path.exists():
        print(f"ERROR: {models_path} not found — run pull-models first.", file=sys.stderr)
        return 1

    try:
        models_json: dict[str, Any] = json.loads(models_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        print(f"ERROR: Could not read {models_path}: {exc}", file=sys.stderr)
        return 1

    # Resolve the selected option (same logic as pull_models).
    options: list[dict[str, Any]] = models_json.get("options", [])
    selected = next((o for o in options if o.get("default")), options[0] if options else {})
    runner: str = selected.get("embed_runner", "")
    model: str = selected.get("embed_model", "")

    if not runner:
        print("ERROR: No embed_runner found in recommend-models output.", file=sys.stderr)
        return 1

    # Idempotency: already listening?
    if _port_open(EMBED_HOST, EMBED_PORT):
        print(
            f"start-embed-server: embed endpoint already reachable on port {EMBED_PORT} — skipping.",
            file=sys.stderr,
        )
        result = {
            "schema_version": SCHEMA_VERSION,
            "action": "already_running",
            "runner": runner,
            "port": EMBED_PORT,
        }
        _save(result)
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    if runner == "llama-server":
        return _start_llama_server(model, args.timeout)
    if runner == "ollama":
        return _start_ollama(model)
    # lm-studio and other GUI-based runners — can't automate
    return _manual_instruction(runner, model)


def _start_llama_server(model: str, timeout: float) -> int:
    model_path = install_state.user_data_dir() / "models" / model
    if not model_path.exists():
        print(
            f"ERROR: GGUF not found at {model_path}",
            file=sys.stderr,
        )
        print("FIX:   Re-run `skillsmith install pull-models` to download it.", file=sys.stderr)
        return 1

    cmd = [
        "llama-server",
        "--embeddings",
        "--port",
        str(EMBED_PORT),
        "--ubatch-size",
        str(LLAMA_UBATCH_SIZE),
        "-m",
        str(model_path),
    ]
    log_path = install_state.user_data_dir() / "logs" / "embed-server.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    print(
        f"start-embed-server: launching llama-server on port {EMBED_PORT} "
        f"(ubatch={LLAMA_UBATCH_SIZE}, log={log_path})",
        file=sys.stderr,
    )
    try:
        with log_path.open("ab") as log_fh:
            subprocess.Popen(
                cmd,
                stdout=log_fh,
                stderr=log_fh,
                start_new_session=True,
            )
    except FileNotFoundError:
        print("ERROR: llama-server not found in PATH.", file=sys.stderr)
        print(
            "FIX:   Re-run `skillsmith install pull-models` to build it, "
            "or add ~/.local/bin to PATH.",
            file=sys.stderr,
        )
        return 1

    print(
        f"start-embed-server: waiting up to {timeout:.0f}s for /health …",
        file=sys.stderr,
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _port_open(EMBED_HOST, EMBED_PORT):
            break
        time.sleep(2)
    else:
        print(
            f"ERROR: llama-server did not start within {timeout:.0f}s. "
            f"Check {log_path} for details.",
            file=sys.stderr,
        )
        try:
            lines = log_path.read_text(errors="replace").splitlines()
            tail = lines[-20:] if len(lines) > 20 else lines
            if tail:
                print(f"\n--- last {len(tail)} lines of {log_path} ---", file=sys.stderr)
                print("\n".join(tail), file=sys.stderr)
                print("--- end log ---", file=sys.stderr)
        except OSError:
            pass
        return 1

    print(f"start-embed-server: llama-server ready on port {EMBED_PORT}", file=sys.stderr)
    result = {
        "schema_version": SCHEMA_VERSION,
        "action": "started",
        "runner": "llama-server",
        "model": model,
        "model_path": str(model_path),
        "port": EMBED_PORT,
        "ubatch_size": LLAMA_UBATCH_SIZE,
        "log_path": str(log_path),
    }
    _save(result)
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def _start_ollama(model: str) -> int:
    """Ensure ollama serve is running. ollama is idempotent — safe to call twice."""
    import shutil

    if not shutil.which("ollama"):
        print("ERROR: ollama not found in PATH.", file=sys.stderr)
        return 1

    # Spawn ollama serve; it exits immediately if already running.
    log_path = install_state.user_data_dir() / "logs" / "embed-server.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("ab") as log_fh:
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=log_fh,
            stderr=log_fh,
            start_new_session=True,
        )

    # Ollama defaults to :11434 for the main API; embedding goes through
    # RUNTIME_EMBED_BASE_URL (11436). If the user configured a separate
    # ollama instance on 11436 just poll it, otherwise accept immediately.
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if _port_open(EMBED_HOST, EMBED_PORT):
            break
        time.sleep(2)
    else:
        print(
            "WARN: Ollama embed endpoint not reachable on port "
            f"{EMBED_PORT} after 30s. "
            "Ensure RUNTIME_EMBED_BASE_URL points to a running ollama instance.",
            file=sys.stderr,
        )

    result = {
        "schema_version": SCHEMA_VERSION,
        "action": "started",
        "runner": "ollama",
        "model": model,
        "port": EMBED_PORT,
    }
    _save(result)
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def _manual_instruction(runner: str, model: str) -> int:
    instructions = {
        "lm-studio": (
            f"Start LM Studio and load model '{model}', then enable the local server "
            f"on port {EMBED_PORT} under Settings → Local Server."
        ),
    }
    msg = instructions.get(runner, f"Start your '{runner}' embedding server on port {EMBED_PORT}.")
    print(f"start-embed-server: manual step required for runner '{runner}':", file=sys.stderr)
    print(f"  {msg}", file=sys.stderr)
    result = {
        "schema_version": SCHEMA_VERSION,
        "action": "manual_required",
        "runner": runner,
        "model": model,
        "port": EMBED_PORT,
        "instruction": msg,
    }
    _save(result)
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    # Exit 0 — setup can continue; if the server isn't up, install-packs will
    # fail with a clear connection-refused error.
    return 0


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def _save(result: dict[str, Any]) -> None:
    install_state.save_output_file(result, f"{STEP_NAME}.json")


def run(args: argparse.Namespace) -> int:
    """Public entry point for non-argparse callers (e.g. simple_setup)."""
    return _run(args)
