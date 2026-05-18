"""One-off Critic-only audit for already-merged YAMLs.

Bypasses the full QA gate (deterministic checks + dedup) and calls
``qa_gate.run_critic`` directly so we get a critic-model second opinion
on skills that are already in the corpus (which would otherwise self-dup).

Outputs ``<skill_id>.critic.md`` next to each skill's existing ``.qa.md``
under ``docs/skill-review-history/<batch>/``.

Usage:
    set -a && source ~/.config/skillsmith/skillsmith.env && set +a
    uv run python scripts/critic_only_audit.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from skillsmith.authoring.lm_client import OpenAICompatClient
from skillsmith.authoring.prompt_loader import load_prompt
from skillsmith.authoring.qa_gate import run_critic
from skillsmith.config import get_settings

REPO = Path(__file__).resolve().parents[1]

# (yaml_path, qa_dir) — qa_dir is where to write the .critic.md report
TARGETS: list[tuple[Path, Path]] = [
    *[
        (
            REPO / "src/skillsmith/_packs/go" / f"{stem}.yaml",
            REPO / "docs/skill-review-history/2026-05-05-go-pack",
        )
        for stem in (
            "go-concurrency-and-context",
            "go-error-handling",
            "go-generics-and-types",
            "go-modules-and-dependencies",
            "go-testing-idioms",
        )
    ],
    *[
        (
            REPO / "src/skillsmith/_packs/rust" / f"{stem}.yaml",
            REPO / "docs/skill-review-history/2026-05-05-rust-pack",
        )
        for stem in (
            "rust-ownership-and-borrowing",
            "rust-error-handling",
            "rust-async-and-concurrency",
            "rust-cargo-and-features",
            "rust-testing-idioms",
        )
    ],
]


def render_report(skill_id: str, verdict_obj) -> str:  # type: ignore[no-untyped-def]
    lines = [
        f"# Critic-only audit: {skill_id}",
        "",
        f"- **Reviewer:** {get_settings().require_authoring_config().critic_model} "
        "via qa_gate.run_critic (no dedup, no SOURCE SKILL.md)",
        f"- **Verdict:** `{verdict_obj.verdict}`",
        f"- **Summary:** {verdict_obj.summary}",
        "",
    ]
    if verdict_obj.blocking_issues:
        lines += ["## Blocking issues", ""]
        lines += [f"- {b}" for b in verdict_obj.blocking_issues]
        lines.append("")
    if verdict_obj.per_fragment:
        lines += ["## Per-fragment notes", ""]
        for pf in verdict_obj.per_fragment:
            lines.append(f"- seq {pf.get('sequence', '?')}: {pf.get('note', '')}")
        lines.append("")
    if verdict_obj.suggested_edits:
        lines += ["## Suggested edits", "", verdict_obj.suggested_edits, ""]
    if verdict_obj.tag_verdicts:
        lines += ["## Tag verdicts", ""]
        for tv in verdict_obj.tag_verdicts:
            lines.append(
                f"- [{tv.get('rule', '?')}] {tv.get('tag', '?')}: "
                f"{tv.get('verdict', '?')} — {tv.get('detail', '')}"
            )
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    settings = get_settings()
    ac = settings.require_authoring_config()
    qa_prompt, version = load_prompt(REPO / "fixtures" / "skill-qa-agent.md")
    print(f"[init] critic={ac.critic_model}  prompt_version={version or '(none)'}")
    client = OpenAICompatClient(ac.lm_studio_base_url)

    summary: list[tuple[str, str, str]] = []
    for yaml_path, qa_dir in TARGETS:
        skill_id = yaml_path.stem
        text = yaml_path.read_text(encoding="utf-8")
        print(f"[run ] {skill_id}  ({len(text)} bytes) → {ac.critic_model}", flush=True)
        verdict = run_critic(
            client=client,
            model=ac.critic_model,
            qa_prompt=qa_prompt,
            source_md="(no source SKILL.md — critic-only audit of already-shipped YAML)",
            draft_yaml_text=text,
            soft_dups=[],
            semantic_tag_block="",
        )
        report_path = qa_dir / f"{skill_id}.critic.md"
        report_path.write_text(render_report(skill_id, verdict), encoding="utf-8")
        print(f"[done] {skill_id}: {verdict.verdict} → {report_path.relative_to(REPO)}")
        summary.append((skill_id, verdict.verdict, verdict.summary[:120]))

    print("\n=== Summary ===")
    for sid, v, s in summary:
        print(f"  {v:<8} {sid:<35} {s}")

    # Aggregate JSON for downstream consumption
    agg = REPO / "docs/skill-review-history/critic-only-audit-2026-05-05.json"
    agg.write_text(
        json.dumps(
            [{"skill_id": sid, "verdict": v, "summary": s} for sid, v, s in summary],
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nWrote aggregate: {agg.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
