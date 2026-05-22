"""``skillsmith signal`` — signal-layer CLI.

Commands:
    skillsmith signal evaluate-phase   Run pre-filter + gate eval for active phase
    skillsmith signal evaluate-system  Find system skills matching applies_when for a tool
    skillsmith signal watch-contract   Validate contract and invoke compose
    skillsmith signal check            Diagnostics: dump current state
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from skillsmith.signals.predicates import PredicateContext

try:
    from skillsmith.lm_client import OpenAICompatClient
except Exception:  # pragma: no cover
    OpenAICompatClient = None  # type: ignore[assignment,misc]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_phase(project_root: Path) -> str | None:
    phase_file = project_root / ".skillsmith" / "phase"
    if not phase_file.exists():
        return None
    try:
        from typing import cast as _cast

        import yaml as _yaml

        raw = _yaml.safe_load(phase_file.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            data: dict[str, Any] = _cast(dict[str, Any], raw)
            val = data.get("phase")
            return str(val).strip() if val else None
        return str(raw).strip() or None
    except Exception:
        return None


def _write_phase_atomic(project_root: Path, phase: str) -> None:
    import os as _os

    phase_file = project_root / ".skillsmith" / "phase"
    phase_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = phase_file.with_suffix(".tmp")
    tmp.write_text(f"phase: {phase}\n", encoding="utf-8")
    # os.replace is atomic and overwrites cross-platform; Path.rename fails
    # on Windows when the destination exists.
    _os.replace(tmp, phase_file)


def _load_workflow_skill_for_phase(phase: str) -> dict[str, Any] | None:
    """Load the active workflow skill for the given phase from the profile datastore."""
    try:
        import duckdb

        from skillsmith.profiles import detect_profile, profile_datastore_path

        profile = detect_profile(cwd=Path.cwd())
        db_path = profile_datastore_path(profile.name if profile else "default")
        if not db_path.exists():
            return None
        with duckdb.connect(str(db_path), read_only=True) as con:
            row = con.execute(
                """
                SELECT skill_id, raw_prose, applies_to_phases, exit_gates, signal_keywords
                FROM profile_skills
                WHERE skill_class = 'workflow'
                """,
            ).fetchall()
        import json as _json

        for r in row:
            skill_id, raw_prose, applies_to_phases, exit_gates_raw, signal_keywords_raw = r
            applies: list[str] = list(applies_to_phases or [])
            if phase in applies:
                exit_gates: dict[str, Any] = {}
                if exit_gates_raw:
                    import contextlib

                    with contextlib.suppress(Exception):
                        exit_gates = _json.loads(exit_gates_raw)
                signal_keywords: list[str] = list(signal_keywords_raw or [])
                return {
                    "skill_id": skill_id,
                    "raw_prose": raw_prose,
                    "applies_to_phases": applies,
                    "exit_gates": exit_gates,
                    "signal_keywords": signal_keywords,
                }
    except Exception:
        pass
    # Fallback: load from _packs
    return _load_workflow_skill_from_packs(phase)


def _load_workflow_skill_from_packs(phase: str) -> dict[str, Any] | None:
    try:
        import yaml as _yaml

        import skillsmith

        packs_root = Path(skillsmith.__file__).resolve().parent / "_packs" / "sdd"
        for f in packs_root.glob("sdd-*.yaml"):
            data: dict[str, Any] = _yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            if data.get("skill_class") == "workflow" and phase in (
                data.get("applies_to_phases") or []
            ):
                return data
    except Exception:
        pass
    return None


def _build_predicate_context(
    project_root: Path,
    phase: str | None,
    prompt_text: str | None = None,
    tool_name: str | None = None,
    tool_path: str | None = None,
    file_events: list[Path] | None = None,
) -> PredicateContext:
    from skillsmith.signals.predicates import PredicateContext

    recent_tool_use: dict[str, Any] | None = None
    if tool_name:
        recent_tool_use = {"tool": tool_name, "path": tool_path or "", "args": {}}

    return PredicateContext(
        project_root=project_root,
        current_phase=phase,
        recent_prompt_text=prompt_text,
        recent_tool_use=recent_tool_use,
        file_events_since=file_events or [],
        contracts_root=project_root / ".skillsmith" / "contracts",
    )


def _write_telemetry(record: dict[str, Any]) -> None:
    """Write a telemetry record to the vector store (soft-fail)."""
    try:
        import time
        import uuid

        from skillsmith.profiles import domain_datastore_path
        from skillsmith.storage.vector_store import CompositionTrace, append_trace

        db_path = domain_datastore_path()
        if not db_path.exists():
            return
        trace = CompositionTrace(
            trace_id=str(uuid.uuid4()),
            request_ts=int(time.time() * 1000),
            phase=record.get("phase", ""),
            task_prompt=record.get("task", "")[:500],
            status="signal",
            event_type=record.get("event_type", "phase_eval"),
            pre_filter_matched=record.get("pre_filter_matched"),
            gates_met=record.get("gates_met", []),
            gates_unmet=record.get("gates_unmet", []),
            qwen_calls=record.get("qwen_calls", 0),
        )
        append_trace(db_path, trace)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# evaluate-phase
# ---------------------------------------------------------------------------


def _evaluate_phase(args: argparse.Namespace) -> int:
    project_root = Path.cwd()
    current_phase = _read_phase(project_root)

    # Read prompt text
    prompt_text: str | None = None
    prompt_file = getattr(args, "prompt_file", None)
    if prompt_file and prompt_file != "/dev/null":
        import contextlib

        with contextlib.suppress(OSError):
            prompt_text = Path(prompt_file).read_text(encoding="utf-8", errors="replace")

    if current_phase is None:
        print(json.dumps({"matched": False, "reason": "no phase file"}))
        return 0

    skill = _load_workflow_skill_for_phase(current_phase)
    if skill is None:
        print(
            json.dumps({"matched": False, "reason": f"no workflow skill for phase={current_phase}"})
        )
        return 0

    gate_spec: dict[str, Any] = skill.get("exit_gates") or {}
    signal_keywords: list[str] = list(skill.get("signal_keywords") or [])

    ctx = _build_predicate_context(
        project_root,
        phase=current_phase,
        prompt_text=prompt_text,
        tool_name=getattr(args, "tool", None),
        tool_path=getattr(args, "tool_path", None),
    )

    from skillsmith.signals.prefilter import check_prefilter

    match = check_prefilter(signal_keywords, gate_spec, ctx)

    if match is None:
        _write_telemetry(
            {
                "task": prompt_text or "",
                "phase": current_phase,
                "event_type": "phase_eval",
                "pre_filter_matched": None,
            }
        )
        print(json.dumps({"matched": False}))
        return 0

    # Gate evaluation — build embed client (soft-fail: None degrades semantic predicates to UNKNOWN)
    lm_client = None
    try:
        from skillsmith.config import get_settings

        cfg = get_settings()
        if OpenAICompatClient is not None:
            lm_client = OpenAICompatClient(cfg.runtime_embed_base_url)
    except Exception:
        pass

    from skillsmith.signals.gates import decide_transition

    decision = decide_transition(
        current_phase=current_phase,
        gate_spec=gate_spec,
        ctx=ctx,
        lm_client=lm_client,
    )

    _write_telemetry(
        {
            "task": prompt_text or "",
            "phase": current_phase,
            "event_type": "phase_transition" if decision.should_transition else "phase_eval",
            "pre_filter_matched": match.name,
            "gates_met": [g.gate_name for g in decision.gates_met],
            "gates_unmet": [g.gate_name for g in decision.gates_unmet],
            "qwen_calls": decision.qwen_calls,
        }
    )

    if decision.should_transition and decision.to_phase:
        _write_phase_atomic(project_root, decision.to_phase)
        next_skill = _load_workflow_skill_for_phase(decision.to_phase)
        prose = (next_skill or {}).get("raw_prose", "")
        if prose:
            print(f"[skillsmith-workflow]\n{prose}\n[/skillsmith-workflow]")
        print(
            json.dumps(
                {
                    "transition": True,
                    "from": current_phase,
                    "to": decision.to_phase,
                }
            ),
            file=sys.stderr,
        )
    else:
        print(
            json.dumps(
                {
                    "transition": False,
                    "gates_unmet": [g.gate_name for g in decision.gates_unmet],
                }
            )
        )

    for advisory in decision.advisories:
        print(advisory)

    return 0


# ---------------------------------------------------------------------------
# evaluate-system
# ---------------------------------------------------------------------------


def _evaluate_system(args: argparse.Namespace) -> int:
    tool_name = getattr(args, "tool", "") or ""
    project_root = Path.cwd()
    current_phase = _read_phase(project_root)

    ctx = _build_predicate_context(
        project_root,
        phase=current_phase,
        tool_name=tool_name,
    )

    try:
        import duckdb

        from skillsmith.profiles import detect_profile, profile_datastore_path

        profile = detect_profile(cwd=Path.cwd())
        db_path = profile_datastore_path(profile.name if profile else "default")
        if not db_path.exists():
            return 0

        with duckdb.connect(str(db_path), read_only=True) as con:
            rows = con.execute(
                "SELECT skill_id, raw_prose, applies_when FROM profile_skills WHERE skill_class = 'system'"
            ).fetchall()

    except Exception:
        return 0

    import yaml as _yaml

    for skill_id, raw_prose, applies_when_raw in rows:
        if not applies_when_raw:
            continue
        try:
            gate_spec: dict[str, Any] = _yaml.safe_load(applies_when_raw) or {}
        except Exception:
            continue

        from skillsmith.signals.gates import evaluate_node
        from skillsmith.signals.predicates import PredicateResult as PredicateResult_

        qwen_calls: list[int] = [0]
        result, _ = evaluate_node(gate_spec, ctx, None, qwen_calls)
        if result == PredicateResult_.MET:
            print(f"[skillsmith-system:{skill_id}]\n{raw_prose}\n[/skillsmith-system]")
            _write_telemetry(
                {
                    "task": tool_name,
                    "phase": current_phase or "",
                    "event_type": "system_skill_applied",
                }
            )

    return 0


# ---------------------------------------------------------------------------
# watch-contract
# ---------------------------------------------------------------------------


def _watch_contract(args: argparse.Namespace) -> int:
    contract_path_str = getattr(args, "path", "") or ""
    if not contract_path_str:
        print(json.dumps({"error": "no --path provided"}), file=sys.stderr)
        return 0

    contract_path = Path(contract_path_str)
    try:
        from skillsmith.contracts import parse_contract, validate_contract

        contract = parse_contract(contract_path)
        issues = validate_contract(contract, Path.cwd())
        if issues:
            print(
                json.dumps({"warning": "contract validation issues", "issues": issues}),
                file=sys.stderr,
            )
            return 0
    except Exception as exc:
        print(json.dumps({"warning": str(exc)}), file=sys.stderr)
        return 0

    # Invoke compose
    import subprocess

    try:
        from skillsmith.install import state as install_state

        st = install_state.load_state()
        port = st.get("port", 47950)
        subprocess.run(
            [
                "skillsmith",
                "compose",
                "--contract",
                str(contract_path),
                "--inject",
                "--port",
                str(port),
            ],
            capture_output=False,
            timeout=30,
        )
    except Exception as exc:
        print(json.dumps({"warning": f"compose failed: {exc}"}), file=sys.stderr)

    _write_telemetry(
        {
            "task": contract_path_str,
            "phase": contract.phase if "contract" in dir() else "",
            "event_type": "contract_retrieval",
        }
    )
    return 0


# ---------------------------------------------------------------------------
# check (diagnostics)
# ---------------------------------------------------------------------------


def _check(args: argparse.Namespace) -> int:
    project_root = Path.cwd()
    current_phase = _read_phase(project_root)
    skill = _load_workflow_skill_for_phase(current_phase or "") if current_phase else None

    report: dict[str, Any] = {
        "current_phase": current_phase,
        "active_workflow_skill": skill.get("skill_id") if skill else None,
        "signal_keywords": (skill or {}).get("signal_keywords", []),
        "exit_gates_keys": list((skill or {}).get("exit_gates", {}).keys()),
    }
    print(json.dumps(report, indent=2))
    return 0


# ---------------------------------------------------------------------------
# code-indexer-from-contract
# ---------------------------------------------------------------------------


def _code_indexer_from_contract(args: argparse.Namespace) -> int:
    contract_path_str = getattr(args, "path", "") or ""
    if not contract_path_str:
        return 0

    try:
        import urllib.parse
        import urllib.request

        from skillsmith.config import get_settings
        from skillsmith.contracts import code_indexer_query_params, parse_contract

        contract = parse_contract(Path(contract_path_str))
        params = code_indexer_query_params(contract, Path.cwd())
        ci_url = get_settings().code_indexer_url

        results: list[str] = []

        def _fetch(url: str) -> str | None:
            try:
                with urllib.request.urlopen(url, timeout=5) as resp:
                    return resp.read().decode("utf-8", errors="replace")
            except Exception:
                return None

        # Semantic search
        q_semantic = urllib.parse.urlencode(
            {"q": params.semantic_q, "repo": params.repo, "top_k": 5}
        )
        body = _fetch(f"{ci_url}/search/semantic?{q_semantic}")
        if body:
            results.append(f"[code-indexer:semantic]\n{body}\n[/code-indexer:semantic]")

        # Lexical search
        if params.lexical_q:
            q_lexical = urllib.parse.urlencode(
                {"q": params.lexical_q, "repo": params.repo, "top_k": 5}
            )
            body = _fetch(f"{ci_url}/search/lexical?{q_lexical}")
            if body:
                results.append(f"[code-indexer:lexical]\n{body}\n[/code-indexer:lexical]")

        if results:
            print("\n".join(results))

        _write_telemetry(
            {
                "task": params.semantic_q,
                "phase": contract.phase,
                "event_type": "contract_retrieval",
            }
        )
    except Exception as exc:
        print(json.dumps({"warning": f"code-indexer-from-contract: {exc}"}), file=sys.stderr)

    return 0


# ---------------------------------------------------------------------------
# Argparse wiring
# ---------------------------------------------------------------------------


def add_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
) -> None:
    p: argparse.ArgumentParser = subparsers.add_parser(
        "signal", help="Signal-layer: phase gate evaluation and system skill routing"
    )
    sub: argparse._SubParsersAction[argparse.ArgumentParser] = p.add_subparsers(dest="signal_cmd")  # pyright: ignore[reportPrivateUsage]

    ep: argparse.ArgumentParser = sub.add_parser(
        "evaluate-phase", help="Run pre-filter + gate evaluation for the active phase"
    )
    ep.add_argument("--prompt-file", dest="prompt_file", default=None)
    ep.add_argument("--tool", default=None)
    ep.add_argument("--tool-path", dest="tool_path", default=None)

    es: argparse.ArgumentParser = sub.add_parser(
        "evaluate-system", help="Emit system skill prose for matching applies_when"
    )
    es.add_argument("--tool", default="", help="Tool name being used (for PreToolUse hook)")

    wc: argparse.ArgumentParser = sub.add_parser(
        "watch-contract", help="Validate contract and invoke compose"
    )
    wc.add_argument("--path", required=True, help="Path to the contract file")

    ci: argparse.ArgumentParser = sub.add_parser(
        "code-indexer-from-contract", help="Query code-indexer using contract params"
    )
    ci.add_argument("--path", required=True, help="Path to the contract file")

    ck: argparse.ArgumentParser = sub.add_parser(
        "check", help="Diagnostics: dump current signal state"
    )
    ck.add_argument("--json", dest="json_out", action="store_true", default=True)

    p.set_defaults(func=_dispatch)


def _dispatch(args: argparse.Namespace) -> int:
    cmd = getattr(args, "signal_cmd", None)
    if cmd == "evaluate-phase":
        return _evaluate_phase(args)
    if cmd == "evaluate-system":
        return _evaluate_system(args)
    if cmd == "watch-contract":
        return _watch_contract(args)
    if cmd == "code-indexer-from-contract":
        return _code_indexer_from_contract(args)
    if cmd == "check":
        return _check(args)
    print(
        "Usage: skillsmith signal {evaluate-phase,evaluate-system,watch-contract,check}",
        file=sys.stderr,
    )
    return 1
