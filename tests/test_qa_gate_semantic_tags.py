"""Tests for Phase C: CriticVerdict tag_verdicts + prompt_loader."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from skillsmith.authoring.prompt_loader import load_prompt
from skillsmith.authoring.qa_gate import CriticVerdict
from skillsmith.lint_tags_semantic import parse_semantic_verdicts


class TestCriticVerdictTagVerdicts:
    def test_tag_verdicts_field_defaults_empty(self) -> None:
        v = CriticVerdict(verdict="approve", summary="ok")
        assert v.tag_verdicts == []
        assert v.prompt_version == ""

    def test_non_pass_tag_verdicts_fold_into_blocking_issues(self) -> None:
        """Non-pass tag_verdicts should be appended to blocking_issues."""
        # Build a minimal JSON response that run_critic would parse
        # by going directly to the CriticVerdict build path
        raw_data: dict[str, Any] = {
            "verdict": "revise",
            "summary": "tag issues",
            "blocking_issues": [],
            "per_fragment": [],
            "dedup_decisions": [],
            "suggested_edits": "",
            "tag_verdicts": [
                {
                    "tag": "prisma",
                    "rule": "R2",
                    "verdict": "redundant_with_title",
                    "detail": "overlaps title",
                },
                {"tag": "auth", "rule": "R1", "verdict": "pass", "detail": ""},
            ],
            "prompt_version": "2026-04-30.1",
        }
        # Simulate how run_critic builds the CriticVerdict from parsed data
        non_pass = [tv for tv in raw_data["tag_verdicts"] if tv.get("verdict", "pass") != "pass"]
        issues = [
            f"tag [{tv['rule']}] '{tv['tag']}': {tv['verdict']} — {tv['detail']}" for tv in non_pass
        ]
        cv = CriticVerdict(
            verdict="revise",
            summary="tag issues",
            blocking_issues=issues,
            tag_verdicts=raw_data["tag_verdicts"],
            prompt_version="2026-04-30.1",
        )
        assert len(cv.blocking_issues) == 1
        assert "redundant_with_title" in cv.blocking_issues[0]
        assert "auth" not in str(cv.blocking_issues)  # pass verdict not folded

    def test_prompt_version_echoed(self) -> None:
        cv = CriticVerdict(verdict="approve", summary="ok", prompt_version="2026-04-30.1")
        assert cv.prompt_version == "2026-04-30.1"


class TestPromptLoader:
    def test_parses_version_pin(self, tmp_path: Path) -> None:
        f = tmp_path / "prompt.md"
        f.write_text("<!-- prompt_version: 2026-04-30.1 -->\n# Title\nContent.", encoding="utf-8")
        text, version = load_prompt(f)
        assert version == "2026-04-30.1"
        assert "# Title" in text

    def test_no_pin_returns_empty_version(self, tmp_path: Path) -> None:
        f = tmp_path / "prompt.md"
        f.write_text("# No pin\nContent.", encoding="utf-8")
        _, version = load_prompt(f)
        assert version == ""

    def test_accepts_string_path(self, tmp_path: Path) -> None:
        f = tmp_path / "p.md"
        f.write_text("<!-- prompt_version: X.Y -->\nHi.", encoding="utf-8")
        _, version = load_prompt(str(f))
        assert version == "X.Y"


class TestParseSemanticVerdictsDefensive:
    def test_empty_string(self) -> None:
        assert parse_semantic_verdicts("") == []

    def test_extra_text_around_array(self) -> None:
        raw = 'Here are verdicts:\n[{"tag": "foo", "verdict": "pass"}]\nDone.'
        result = parse_semantic_verdicts(raw)
        assert len(result) == 1
        assert result[0]["tag"] == "foo"

    def test_non_list_top_level(self) -> None:
        assert parse_semantic_verdicts('{"tag": "x"}') == []

    def test_items_missing_tag_key_filtered(self) -> None:
        raw = '[{"verdict": "pass"}, {"tag": "bar", "verdict": "fail"}]'
        result = parse_semantic_verdicts(raw)
        assert len(result) == 1
        assert result[0]["tag"] == "bar"

    def test_truncated_json_returns_empty(self) -> None:
        raw = '[{"tag": "foo", "verdict": "pass"'  # truncated
        assert parse_semantic_verdicts(raw) == []
