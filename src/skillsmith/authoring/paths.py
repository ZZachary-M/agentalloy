"""Staging directory layout for the authoring pipeline.

All directories are rooted at ``skill-source/`` by default. Each stage of
the pipeline corresponds to one directory; moving a YAML between them is
the state machine.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PipelinePaths:
    root: Path

    @property
    def pending_qa(self) -> Path:
        """Author emits drafts here; QA picks them up."""
        return self.root / "pending-qa"

    @property
    def pending_review(self) -> Path:
        """QA-approved drafts awaiting human ingest."""
        return self.root / "pending-review"

    @property
    def pending_revision(self) -> Path:
        """QA asked the author to iterate; back into pending-qa after rewrite."""
        return self.root / "pending-revision"

    @property
    def rejected(self) -> Path:
        """QA rejected — not iterable."""
        return self.root / "rejected"

    @property
    def needs_human(self) -> Path:
        """Bounce budget exhausted or critic output unparseable."""
        return self.root / "needs-human"

    @property
    def qa_state(self) -> Path:
        return self.root / ".qa-state.json"

    def ensure_all(self) -> None:
        for d in (
            self.pending_qa,
            self.pending_review,
            self.pending_revision,
            self.rejected,
            self.needs_human,
        ):
            d.mkdir(parents=True, exist_ok=True)


def default_paths(repo_root: Path) -> PipelinePaths:
    return PipelinePaths(root=repo_root / "skill-source")
