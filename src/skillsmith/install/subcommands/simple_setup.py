"""``skillsmith setup`` — interactive one-shot install wizard.

Mirrors the code-indexer-service UX:

    pipx install git+https://github.com/navistone/skillsmith.git
    skillsmith setup          # interactive: questions -> execution -> validation

The command:
1. **Asks questions** -- prompts the user for runner, model, port, service mode, packs, harness
2. **Executes** -- runs all install steps with the gathered config
3. **Validates** -- confirms embedder is listening, corpus is healthy, harness is wired

After setup, per-repo commands still work:

    cd ~/my-project && skillsmith wire
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from typing import Any

from skillsmith.install import state as install_state
from skillsmith.install.subcommands import (
    detect,
    enable_service,
    install_packs,
    preflight,
    pull_models,
    seed_corpus,
    start_embed_server,
    verify,
    wire_harness,
    write_env,
)

try:
    from rich.console import Console  # type: ignore[import-untyped]

    console: Console | None = Console()  # type: ignore[assignment]
except ImportError:
    console = None  # type: ignore[assignment]


def _print(*args: Any, **kwargs: Any) -> None:  # type: ignore[no-untyped-def]
    """Print with Rich if available, plain stdout otherwise."""
    if console is not None:
        console.print(*args, **kwargs)  # type: ignore[union-attr, arg-type]
    else:
        print(*args, **kwargs)


@dataclass
class SetupConfig:
    """User-facing configuration gathered during the interactive wizard."""

    runner: str = "ollama"
    model: str = "qwen3-embedding:0.6b"
    port: int = 47950
    mode: str = "persistent"  # "persistent" or "manual"
    packs: str = ""  # comma-separated, empty = always-on only
    harness: str = "manual"
    preset: str = ""  # filled by auto-detect: "cpu", "nvidia", etc.
    non_interactive: bool = False

    # Resolved during execution -- not user-facing.
    detected_runner: str | None = None  # from detect.json (e.g. "ollama", "llama-server")
    recommended_host: str | None = None  # from recommend-host-targets.json
    models_output: dict[str, Any] = field(default_factory=dict)  # type: ignore[type-arg]


_MODEL_DEFAULTS: dict[str, str] = {
    "ollama": "qwen3-embedding:0.6b",
    "llama-server": "Qwen3-Embedding-0.6B-Q8_0.gguf",
}


# Map (runner, hardware_target) -> write_env preset name.
_PRESET_MAP: dict[tuple[str, str], str] = {
    ("ollama", "cpu"): "cpu",
    ("ollama", "apple-silicon"): "apple-silicon",
    ("ollama", "nvidia"): "nvidia",
    ("ollama", "radeon"): "radeon",
    ("llama-server", "cpu"): "cpu-llama-server",
    ("llama-server", "apple-silicon"): "apple-silicon-llama-server",
    ("llama-server", "nvidia"): "nvidia-llama-server",
    ("llama-server", "radeon"): "radeon-llama-server",
}


def _resolve_preset(cfg: SetupConfig) -> str:
    """Resolve the write-env preset from runner + detected hardware.

    Falls back to "cpu" if the combination is unknown.
    """
    runner = cfg.runner
    hw = cfg.recommended_host or "cpu"
    key = (runner, hw)
    preset = _PRESET_MAP.get(key)
    if preset is None:
        _print(f"  [dim]Warning: no preset for ({runner}, {hw}), falling back to cpu.[/dim]")
        preset = "cpu" if runner == "ollama" else "cpu-llama-server"
    cfg.preset = preset
    return preset


def _build_namespace(cfg: SetupConfig, **overrides: Any) -> argparse.Namespace:  # type: ignore[no-untyped-def]
    """Build an argparse.Namespace from SetupConfig for subcommand dispatch.

    Each subcommand's .run() expects an argparse.Namespace with specific
    attributes. This function bridges the gap between our typed config and
    the argparse contract.
    """
    attrs: dict[str, Any] = {
        "port": cfg.port,
        "preset": cfg.preset,
        "runner": cfg.runner,
        "non_interactive": cfg.non_interactive,
        "packs": cfg.packs,
        "mode": "native" if cfg.mode == "persistent" else "manual",
        "harness": cfg.harness,
        "phase": "early",
        "models": None,
        "force": False,
        "ignore_unknown": False,
        "list": False,
        "runtime": None,
        "hardware": None,
        "host": None,
        "timeout": 120.0,  # start_embed_server timeout
        "overrides": None,  # write_env overrides
        "scope": "user",  # wire_harness scope
        "mcp_fallback": False,  # wire_harness mcp_fallback
    }
    attrs.update(overrides)  # type: ignore[arg-type]
    return argparse.Namespace(**attrs)


def _prompt(text: str, default: Any = None) -> str:
    """Interactive prompt with default. Returns default if non-TTY."""
    if not sys.stdin.isatty():
        return str(default) if default is not None else ""
    return input(f"{text} [{default}]: ") or (str(default) if default is not None else "")


def run_setup(cfg: SetupConfig) -> int:
    """Execute the simple interactive setup flow."""
    t0 = time.monotonic()

    # -- Phase 0: Auto-detect hardware --

    _print("\n[dim]Detecting hardware...[/dim]")
    detect_result = detect.run(_build_namespace(cfg))
    if detect_result not in (0, 4):
        _print("  [red]Hardware detection failed. Continuing with defaults.[/red]")

    # Read detect output to determine host target
    detect_fp = install_state.outputs_dir() / "detect.json"
    if detect_fp.exists():
        detect_data = json.loads(detect_fp.read_text())
        cfg.detected_runner = detect_data.get("runner")
        cfg.recommended_host = detect_data.get("recommended_host")
    else:
        cfg.recommended_host = "cpu"

    _print(f"  Detected host: {cfg.recommended_host or 'cpu'}")

    # -- Phase 1: Gather config --

    _print("\n[bold]skillsmith setup[/bold]\n")

    # 1. Runner
    if cfg.runner == "ollama" and not cfg.non_interactive:
        cfg.runner = _prompt("  Embedding runner", default="ollama")
    if cfg.runner not in ("ollama", "llama-server"):
        _print(f"  [red]Invalid runner: {cfg.runner}. Choose ollama or llama-server.[/red]")
        return 1
    _print(f"  Runner: {cfg.runner}")

    # 2. Model (default varies by runner)
    if not cfg.non_interactive:
        cfg.model = _prompt(
            "  Model",
            default=_MODEL_DEFAULTS.get(cfg.runner, "qwen3-embedding:0.6b"),
        )
    else:
        cfg.model = _MODEL_DEFAULTS.get(cfg.runner, "qwen3-embedding:0.6b")
    _print(f"  Model: {cfg.model}")

    # 3. Port
    if not cfg.non_interactive:
        port_str = _prompt("  Service port", default=47950)
        try:
            cfg.port = int(port_str)
        except ValueError:
            _print(f"  [red]Invalid port: {port_str}[/red]")
            return 1
    _print(f"  Port: {cfg.port}")

    # 4. Service mode
    if not cfg.non_interactive:
        cfg.mode = _prompt("  Service mode (persistent/manual)", default="persistent")
    if cfg.mode not in ("persistent", "manual"):
        _print(f"  [red]Invalid mode: {cfg.mode}. Use persistent or manual.[/red]")
        return 1
    _print(f"  Mode: {cfg.mode}")

    # 5. Packs
    if not cfg.non_interactive:
        cfg.packs = _prompt(
            "  Skill packs (comma-separated, 'all', or blank for always-on)",
            default="",
        )
    _print(f"  Packs: {cfg.packs or '(always-on only)'}")

    # 6. Harness
    if not cfg.non_interactive:
        cfg.harness = _prompt(
            "  Harness (claude-code / cursor / continue / manual)",
            default="manual",
        )
    _print(f"  Harness: {cfg.harness}")

    # 7. Resolve preset (auto -- no prompt)
    preset = _resolve_preset(cfg)
    _print(f"  Preset: {preset}")

    # -- Phase 2: Execute install steps --

    _print("\n[bold]Running setup steps...[/bold]")

    # Step a: Preflight (early)
    _print("  [dim]-> Preflight (early)[/dim]")
    preflight_result = preflight.run_preflight(phase="early", port=cfg.port)
    fatal = [
        c["name"]
        for c in preflight_result.get("checks", [])
        if not c["passed"] and c.get("severity") == "fatal"
    ]
    if fatal:
        _print("  [red]Preflight failed:[/red]")
        for name in fatal:
            check = next(c for c in preflight_result["checks"] if c["name"] == name)
            _print(f"    - {name}: {check.get('error', 'unknown')}")
            if check.get("remediation"):
                _print(f"      FIX: {check['remediation']}")
        _print("  [red]Fix the issues above and re-run setup.[/red]")
        return 1
    _print("  [green]  Preflight (early) passed.[/green]")

    # Step b: Preflight (runner)
    _print("  [dim]-> Preflight (runner)[/dim]")
    runner_preflight = preflight.run_preflight(phase="runner", runner=cfg.runner, port=cfg.port)
    runner_fatal = [
        c["name"]
        for c in runner_preflight.get("checks", [])
        if not c["passed"] and c.get("severity") == "fatal"
    ]
    if runner_fatal:
        _print("  [red]Runner preflight failed:[/red]")
        for name in runner_fatal:
            check = next(c for c in runner_preflight["checks"] if c["name"] == name)
            _print(f"    - {name}: {check.get('error', 'unknown')}")
        _print("  [red]Install/start the runner and re-run setup.[/red]")
        return 1
    _print("  [green]  Preflight (runner) passed.[/green]")

    # Step c: Write .env
    _print("  [dim]-> Writing .env[/dim]")
    ns = _build_namespace(cfg, preset=preset, port=cfg.port, overrides=None, force=False)
    rc = write_env.run(ns)
    if rc not in (0, 4):
        _print(f"  [red]  write-env failed (exit {rc}).[/red]")
        return rc
    _print("  [green]  Done.[/green]")

    # Step d: Pull model
    _print("  [dim]-> Pulling model[/dim]")
    # Build a minimal recommend-models.json for pull_models to consume
    models_json = {
        "preset": preset,
        "models": [{"name": cfg.model, "runner": cfg.runner}],
        "selected_runner": cfg.runner,
    }
    models_fp = install_state.outputs_dir() / "recommend-models.json"
    models_fp.write_text(json.dumps(models_json))
    rc = pull_models.run(_build_namespace(cfg, models=str(models_fp), runner=cfg.runner))
    if rc not in (0, 4):
        _print(f"  [yellow]  pull-models returned {rc} (model may already be present).[/yellow]")
    _print("  [green]  Done.[/green]")

    # Step e: Seed corpus
    _print("  [dim]-> Seeding corpus[/dim]")
    rc = seed_corpus.run(_build_namespace(cfg))
    if rc not in (0, 4):  # 4 = EXIT_NOOP
        _print(f"  [red]  seed-corpus failed (exit {rc}).[/red]")
        return rc
    _print("  [green]  Done.[/green]")

    # Step f: Start embed server
    _print("  [dim]-> Starting embed server[/dim]")
    rc = start_embed_server.run(_build_namespace(cfg, models=str(models_fp), timeout=120.0))
    if rc not in (0, 4):
        _print(f"  [red]  start-embed-server failed (exit {rc}).[/red]")
        return rc
    _print("  [green]  Done.[/green]")

    # Step g: Install packs
    _print("  [dim]-> Installing packs[/dim]")
    rc = install_packs.run(
        _build_namespace(
            cfg,
            packs=cfg.packs,
            non_interactive=cfg.non_interactive,
            ignore_unknown=False,
            list=False,
        )
    )
    if rc not in (0, 4):
        _print(f"  [red]  install-packs failed (exit {rc}).[/red]")
        return rc
    _print("  [green]  Done.[/green]")

    # Step h: Enable service
    _print("  [dim]-> Enabling service[/dim]")
    mode_flag = "native" if cfg.mode == "persistent" else "manual"
    rc = enable_service.run(_build_namespace(cfg, mode=mode_flag, runtime=None, port=cfg.port))
    if rc not in (0, 4):
        _print(f"  [red]  enable-service failed (exit {rc}).[/red]")
        return rc
    _print("  [green]  Done.[/green]")

    # Step i: Wire harness (if requested)
    if cfg.harness and cfg.harness != "manual":
        _print(f"  [dim]-> Wiring harness ({cfg.harness})[/dim]")
        rc = wire_harness.run(_build_namespace(cfg, harness=cfg.harness, force=False))
        if rc not in (0, 4):
            _print(f"  [red]  wire-harness failed (exit {rc}).[/red]")
            return rc
        _print("  [green]  Done.[/green]")

    # -- Phase 3: Validate --

    _print("\n[bold]Validating installation...[/bold]")
    rc = verify.run(_build_namespace(cfg))
    if rc not in (0, 4):
        _print("  [red]Validation failed.[/red]")
        return rc
    _print("  [green]All checks passed.[/green]")

    # -- Done --

    _print(f"\n[green]  Setup complete in {int((time.monotonic() - t0) * 1000)}ms[/green]\n")
    _print(f"  Service: {cfg.mode}")
    _print(f"  URL:     http://localhost:{cfg.port}")
    _print(f"  Config:  {install_state.user_config_dir()}")
    _print(f"  Data:    {install_state.user_data_dir()}")
    _print("\n  [bold]Next:[/bold] cd to your project repo and run [bold]skillsmith wire[/bold]")
    return 0


def add_parser(
    subparsers: Any,  # type: ignore[type-arg]
) -> None:  # type: ignore[no-untyped-def]
    """Register 'setup' as a subcommand in the existing argparse dispatcher."""
    p: argparse.ArgumentParser = subparsers.add_parser(
        "setup",
        help="Interactive setup wizard: detect, configure, install, validate.",
    )
    p.add_argument(
        "--non-interactive",
        "-n",
        action="store_true",
        help="Accept all defaults without prompting.",
    )
    p.add_argument(
        "--runner",
        choices=["ollama", "llama-server"],
        default=None,
        help="Embedding runner (default: ollama).",
    )
    p.add_argument(
        "--model",
        default=None,
        help="Embedding model name.",
    )
    p.add_argument(
        "--port",
        type=int,
        default=None,
        help="Service port (default: 47950).",
    )
    p.add_argument(
        "--mode",
        choices=["persistent", "manual"],
        default=None,
        help="Service mode (default: persistent).",
    )
    p.add_argument(
        "--packs",
        default=None,
        help="Comma-separated pack names, 'all', or blank for always-on.",
    )
    p.add_argument(
        "--harness",
        default=None,
        help="IDE harness to wire (default: manual).",
    )
    p.set_defaults(func=_run_from_args)


def _run_from_args(args: argparse.Namespace) -> int:
    """Bridge from argparse.Namespace to SetupConfig -> run_setup()."""
    cfg = SetupConfig(
        runner=args.runner or "ollama",
        model=args.model or "",
        port=args.port or 47950,
        mode=args.mode or "persistent",
        packs=args.packs or "",
        harness=args.harness or "manual",
        non_interactive=args.non_interactive,
    )
    # Override model default based on runner if not explicitly set
    if cfg.model == "":
        cfg.model = _MODEL_DEFAULTS.get(cfg.runner, "qwen3-embedding:0.6b")
    return run_setup(cfg)
