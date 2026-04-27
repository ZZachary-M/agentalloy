# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false
"""``recommend-models`` subcommand.

Given hardware + chosen host target, return valid
``{embed_model, embed_runner}`` options and the resolved preset name.

Preset resolution table (from contracts.md):
  (apple-silicon, iGPU)    → apple-silicon
  (nvidia, dGPU)           → nvidia
  (amd-x86_64, dGPU)       → radeon
  (any, CPU+RAM)           → cpu
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from skillsmith.install import state as install_state

SCHEMA_VERSION = 1

# ---- Preset resolution ---------------------------------------------------

_PRESET_TABLE: list[tuple[str, str, str]] = [
    # (hardware_class, host_target, preset)
    ("apple-silicon", "iGPU", "apple-silicon"),
    ("nvidia", "dGPU", "nvidia"),
    ("amd-x86_64", "dGPU", "radeon"),
]
_DEFAULT_PRESET = "cpu"

# Full resolution table exposed in output
PRESET_RESOLUTION_TABLE: dict[str, str] = {
    "(apple-silicon, iGPU)": "apple-silicon",
    "(nvidia, dGPU)": "nvidia",
    "(amd-x86_64, dGPU)": "radeon",
    "(any, CPU+RAM)": "cpu",
}


# ---- Model options per preset --------------------------------------------


def _options_apple_silicon() -> list[dict[str, Any]]:
    return [
        {
            "default": True,
            "embed_model": "qwen3-embedding:0.6b",
            "embed_runner": "ollama",
            "embed_runner_install_hint": "ollama is installed; will run `ollama pull qwen3-embedding:0.6b`",
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
    ]


def _options_radeon() -> list[dict[str, Any]]:
    return [
        {
            "default": True,
            "embed_model": "qwen3-embedding:0.6b",
            "embed_runner": "lm-studio",
            "embed_runner_install_hint": "LM Studio with Vulkan backend; load qwen3-embedding:0.6b (Q8 recommended)",
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
    ]


_PRESET_OPTIONS: dict[str, Any] = {
    "apple-silicon-iGPU": _options_apple_silicon,
    "nvidia-dGPU": _options_nvidia,
    "radeon-dGPU": _options_radeon,
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

    # AMD x86_64 — resolves to radeon (dGPU) or cpu (iGPU/CPU+RAM)
    if vendor == "amd" and "x86" in arch:
        return "amd-x86_64"

    return "generic"


def _resolve_preset(hw_class: str, host_target: str) -> str:
    """Resolve the preset name from hardware class and host target."""
    for cls, tgt, preset in _PRESET_TABLE:
        if cls == hw_class and tgt == host_target:
            return preset
    return _DEFAULT_PRESET


def recommend_models(hw: dict[str, Any], host_target: str) -> dict[str, Any]:
    """Evaluate model options for the given hardware and host target."""
    hw_class = _classify_hardware(hw)
    preset = _resolve_preset(hw_class, host_target)

    options_key = f"{preset}-{host_target}"
    options_fn = _PRESET_OPTIONS.get(options_key, _options_cpu)
    options = options_fn()

    return {
        "schema_version": SCHEMA_VERSION,
        "host_target": host_target,
        "preset": preset,
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
    p.set_defaults(func=run)


def _load_hardware(path_str: str) -> dict[str, Any]:
    p = Path(path_str)
    if not p.exists():
        print(f"ERROR: Hardware file not found: {path_str}", file=sys.stderr)
        print("CAUSE: The detect step may not have run yet.", file=sys.stderr)
        print("FIX:   Run `python -m skillsmith.install detect` first.", file=sys.stderr)
        raise SystemExit(1)
    return json.loads(p.read_text())


def run(args: argparse.Namespace) -> int:
    """Execute the recommend-models subcommand.

    Always re-evaluates from the supplied --hardware and --host inputs. Caching
    the previous result would silently mask either a corrected hardware file or
    a different host-target choice.
    """
    st = install_state.load_state()
    hw = _load_hardware(args.hardware)
    result = recommend_models(hw, args.host)

    fp, digest = install_state.save_output_file(result, "recommend-models.json")

    # Find the default option to record the selection
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

    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0
