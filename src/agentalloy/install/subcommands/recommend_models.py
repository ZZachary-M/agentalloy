# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false
"""``recommend-models`` subcommand.

Given hardware + chosen host target, return valid
``{embed_model, embed_runner}`` options and the resolved preset name.

Preset resolution table (from contracts.md):
  (apple-silicon, iGPU)    → apple-silicon
  (nvidia, dGPU)           → nvidia
  (amd-x86_64, dGPU)       → radeon
  (amd-x86_64, iGPU)       → radeon  (LM Studio Vulkan works on AMD iGPU)
  (any, CPU+RAM)           → cpu

When running interactively the user is prompted to choose their preferred
embed runner.  Non-interactive invocations (CI, ``--runner`` flag) skip
the prompt.  Each preset has a variant for every supported runner:

  <preset>              — Ollama (default)
  <preset>-llama-server — llama-server (llama.cpp)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from agentalloy.install import state as install_state
from agentalloy.install.output import add_json_flag, print_rich, write_result

SCHEMA_VERSION = 1

# Supported embed runners exposed to the user.
SUPPORTED_RUNNERS = ("ollama", "llama-server")

# ---- Preset resolution ---------------------------------------------------

_PRESET_TABLE: list[tuple[str, str, str]] = [
    # (hardware_class, host_target, preset)
    ("apple-silicon", "iGPU", "apple-silicon"),
    ("nvidia", "dGPU", "nvidia"),
    ("amd-x86_64", "dGPU", "radeon"),
    ("amd-x86_64", "iGPU", "radeon"),  # LM Studio Vulkan works on AMD iGPU
]
_DEFAULT_PRESET = "cpu"

# Full resolution table exposed in output
PRESET_RESOLUTION_TABLE: dict[str, str] = {
    "(apple-silicon, iGPU)": "apple-silicon",
    "(nvidia, dGPU)": "nvidia",
    "(amd-x86_64, dGPU)": "radeon",
    "(amd-x86_64, iGPU)": "radeon",
    "(any, CPU+RAM)": "cpu",
}


# ---- Model options per preset --------------------------------------------
# Each helper returns both runner variants. The ``default`` flag is always
# set on the Ollama option here; interactive selection overrides it at
# runtime by flipping the flag on the chosen option.


def _options_apple_silicon() -> list[dict[str, Any]]:
    return [
        {
            "default": True,
            "embed_model": "qwen3-embedding:0.6b",
            "embed_runner": "ollama",
            "embed_runner_install_hint": "ollama is installed; will run `ollama pull qwen3-embedding:0.6b`",
        },
        {
            "default": False,
            "embed_model": "Qwen3-Embedding-0.6B-Q8_0.gguf",
            "embed_runner": "llama-server",
            "embed_runner_install_hint": (
                "llama-server (llama.cpp) with Metal acceleration; "
                "GGUF will be downloaded from Hugging Face automatically."
            ),
        },
    ]


def _options_nvidia() -> list[dict[str, Any]]:
    return [
        {
            "default": True,
            "embed_model": "qwen3-embedding:0.6b",
            "embed_runner": "ollama",
            "embed_runner_install_hint": "ollama is installed; will run `ollama pull qwen3-embedding:0.6b`",
        },
        {
            "default": False,
            "embed_model": "Qwen3-Embedding-0.6B-Q8_0.gguf",
            "embed_runner": "llama-server",
            "embed_runner_install_hint": (
                "llama-server (llama.cpp) with CUDA acceleration; "
                "GGUF will be downloaded from Hugging Face automatically."
            ),
        },
    ]


def _options_radeon() -> list[dict[str, Any]]:
    return [
        {
            "default": True,
            "embed_model": "qwen3-embedding:0.6b",
            "embed_runner": "lm-studio",
            "embed_runner_install_hint": "LM Studio with Vulkan backend; load qwen3-embedding:0.6b (Q8 recommended)",
        },
        {
            "default": False,
            "embed_model": "Qwen3-Embedding-0.6B-Q8_0.gguf",
            "embed_runner": "llama-server",
            "embed_runner_install_hint": (
                "llama-server (llama.cpp) with Vulkan/ROCm acceleration; "
                "GGUF will be downloaded from Hugging Face automatically."
            ),
        },
    ]


def _options_cpu() -> list[dict[str, Any]]:
    return [
        {
            "default": True,
            "embed_model": "qwen3-embedding:0.6b",
            "embed_runner": "ollama",
            "embed_runner_install_hint": "ollama is installed; will run `ollama pull qwen3-embedding:0.6b`",
        },
        {
            "default": False,
            "embed_model": "Qwen3-Embedding-0.6B-Q8_0.gguf",
            "embed_runner": "llama-server",
            "embed_runner_install_hint": (
                "llama-server (llama.cpp) CPU-only; "
                "GGUF will be downloaded from Hugging Face automatically."
            ),
        },
    ]


_PRESET_OPTIONS: dict[str, Any] = {
    "apple-silicon-iGPU": _options_apple_silicon,
    "nvidia-dGPU": _options_nvidia,
    "radeon-dGPU": _options_radeon,
    "radeon-iGPU": _options_radeon,
    "cpu-CPU+RAM": _options_cpu,
}


# ---- Hardware classification ---------------------------------------------


def _classify_hardware(hw: dict[str, Any]) -> str:
    """Return a hardware class string for preset resolution."""
    os_info = hw.get("os") or {}
    arch = os_info.get("arch", "")
    cpu = hw.get("cpu") or {}
    vendor = (cpu.get("vendor") or "").lower()
    gpu = hw.get("gpu") or {}
    discrete = gpu.get("discrete") or []

    # Apple Silicon
    if arch == "arm64" and os_info.get("kind") == "macos":
        return "apple-silicon"

    # NVIDIA dGPU present
    if any((d.get("vendor") or "").lower() == "nvidia" for d in discrete):
        return "nvidia"

    # AMD x86_64 — resolves to radeon (dGPU or iGPU) or cpu (CPU+RAM)
    if vendor == "amd" and "x86" in arch:
        return "amd-x86_64"

    return "generic"


def _resolve_preset(hw_class: str, host_target: str) -> str:
    """Resolve the preset name from hardware class and host target."""
    for cls, tgt, preset in _PRESET_TABLE:
        if cls == hw_class and tgt == host_target:
            return preset
    return _DEFAULT_PRESET


# ---- Interactive runner selection ----------------------------------------


def _prompt_runner(options: list[dict[str, Any]]) -> str:
    """Interactively ask the user to choose an embed runner.

    Returns the ``embed_runner`` value of the chosen option.
    """
    print("\nChoose your embed runner:", file=sys.stderr)
    for i, opt in enumerate(options, start=1):
        marker = " (default)" if opt.get("default") else ""
        print(f"  {i}) {opt['embed_runner']}{marker}", file=sys.stderr)
        print(f"     {opt['embed_runner_install_hint']}", file=sys.stderr)

    default_runner = next(
        (o["embed_runner"] for o in options if o.get("default")),
        options[0]["embed_runner"],
    )

    while True:
        try:
            raw = input(f"\nEnter choice [1-{len(options)}] (default: 1): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("", file=sys.stderr)
            return default_runner

        if raw == "":
            return default_runner

        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(options):
                return options[idx]["embed_runner"]

        print(
            f"  Invalid choice '{raw}'. Enter a number between 1 and {len(options)}.",
            file=sys.stderr,
        )


def _apply_runner_selection(
    options: list[dict[str, Any]], chosen_runner: str
) -> list[dict[str, Any]]:
    """Return a copy of options with ``default`` set only on the chosen runner."""
    updated: list[dict[str, Any]] = []
    for opt in options:
        updated.append({**opt, "default": opt["embed_runner"] == chosen_runner})
    return updated


# ---- Preset name with runner suffix --------------------------------------


def _preset_with_runner(base_preset: str, runner: str) -> str:
    """Return the full preset name that encodes the runner choice.

    Ollama uses the bare preset name (backward-compatible).
    llama-server appends ``-llama-server``.
    Other runners keep the bare name (forward-compatible).
    """
    if runner == "llama-server":
        return f"{base_preset}-llama-server"
    return base_preset


# ---- Public API ----------------------------------------------------------


def recommend_models(
    hw: dict[str, Any],
    host_target: str,
    runner: str | None = None,
    interactive: bool | None = None,
) -> dict[str, Any]:
    """Evaluate model options for the given hardware and host target.

    Parameters
    ----------
    hw:
        Hardware detection output dict.
    host_target:
        One of ``dGPU``, ``iGPU``, ``CPU+RAM``.
    runner:
        If supplied, skip the interactive prompt and use this runner
        directly.  Must be one of ``SUPPORTED_RUNNERS`` or a recognised
        runner already present in the options list.
    interactive:
        Override TTY detection.  ``True`` forces the prompt; ``False``
        suppresses it.  ``None`` (default) defers to
        ``sys.stdin.isatty()``.
    """
    hw_class = _classify_hardware(hw)
    preset = _resolve_preset(hw_class, host_target)

    options_key = f"{preset}-{host_target}"
    options_fn = _PRESET_OPTIONS.get(options_key, _options_cpu)
    options = options_fn()

    is_tty = sys.stdin.isatty() if interactive is None else interactive

    if runner is not None:
        # Caller-supplied runner (non-interactive or --runner flag).
        available = [o["embed_runner"] for o in options]
        if runner not in available:
            print(
                f"WARNING: Runner '{runner}' not in options for preset '{preset}'; "
                f"falling back to default.",
                file=sys.stderr,
            )
        else:
            options = _apply_runner_selection(options, runner)
    elif is_tty and len(options) > 1:
        chosen = _prompt_runner(options)
        options = _apply_runner_selection(options, chosen)
    # else: non-interactive with no explicit --runner → keep the default option

    # Derive the selected option (first with default=True, else first overall).
    selected_opt = next((o for o in options if o.get("default")), options[0])
    resolved_preset = _preset_with_runner(preset, selected_opt["embed_runner"])

    return {
        "schema_version": SCHEMA_VERSION,
        "host_target": host_target,
        "preset": resolved_preset,
        "base_preset": preset,
        "selected_runner": selected_opt["embed_runner"],
        "options": options,
        "preset_resolution_table": PRESET_RESOLUTION_TABLE,
    }


# ---------------------------------------------------------------------------
# Subcommand interface
# ---------------------------------------------------------------------------


def add_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:  # pyright: ignore[reportPrivateUsage]
    p: argparse.ArgumentParser = subparsers.add_parser(
        "recommend-models",
        help="Given hardware + host target, return valid model pairs and resolved preset.",
    )
    p.add_argument(
        "--hardware",
        required=True,
        help="Path to the detect output JSON file.",
    )
    p.add_argument(
        "--host",
        required=True,
        choices=["dGPU", "iGPU", "CPU+RAM"],
        help="The chosen host target from recommend-host-targets.",
    )
    p.add_argument(
        "--runner",
        choices=list(SUPPORTED_RUNNERS),
        default=None,
        help=(
            "Override interactive runner selection. "
            "Accepts: ollama, llama-server. "
            "If omitted and stdin is a TTY, the user is prompted."
        ),
    )
    add_json_flag(p)
    p.set_defaults(func=run)


def _load_hardware(path_str: str) -> dict[str, Any]:
    p = Path(path_str)
    if not p.exists():
        print(f"ERROR: Hardware file not found: {path_str}", file=sys.stderr)
        print("CAUSE: The detect step may not have run yet.", file=sys.stderr)
        print("FIX:   Run `python -m agentalloy.install detect` first.", file=sys.stderr)
        raise SystemExit(1)
    return json.loads(p.read_text())


def _render_human(result: dict[str, Any]) -> None:
    """Render model recommendations in human-readable format."""
    preset = result.get("preset", "unknown")
    options = result.get("options", [])

    print_rich("\n  [bold]Model Recommendations[/bold]\n")
    print_rich(f"  Preset: [bold]{preset}[/bold]\n")

    for opt in options:
        default_marker = " [green](default)[/green]" if opt.get("default") else ""
        runner = opt.get("embed_runner", "?")
        model = opt.get("embed_model", "?")
        print_rich(f"  {runner}: {model}{default_marker}")

    print_rich()


def run(args: argparse.Namespace) -> int:
    """Execute the recommend-models subcommand."""
    st = install_state.load_state()
    hw = _load_hardware(args.hardware)
    result = recommend_models(hw, args.host, runner=getattr(args, "runner", None))

    fp, digest = install_state.save_output_file(result, "recommend-models.json")

    selected = {}
    for opt in result["options"]:
        if opt.get("default"):
            selected = {
                "preset": result["preset"],
                "embed_model": opt["embed_model"],
                "embed_runner": opt["embed_runner"],
            }
            break

    install_state.record_step(
        st,
        "recommend-models",
        extra={
            "output_digest": digest,
            "output_path": str(fp),
            "selected": selected,
        },
    )
    install_state.save_state(st)

    write_result(result, args, human_fn=_render_human)
    return 0
