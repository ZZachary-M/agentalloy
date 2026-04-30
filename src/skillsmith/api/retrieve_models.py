"""Pydantic models for the direct retrieve endpoint (NXS-769)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from skillsmith.api.compose_models import DEFAULT_K_BY_PHASE, Phase


class ActiveVersionMeta(BaseModel):
    version_id: str
    version_number: int
    authored_at: datetime
    author: str
    change_summary: str


class RetrieveByIdResponse(BaseModel):
    status: Literal["ok"] = "ok"
    skill_id: str
    canonical_name: str
    category: str
    skill_class: Literal["domain", "system", "workflow"]
    active_version: ActiveVersionMeta
    raw_prose: str


class RetrieveQueryRequest(BaseModel):
    task: Annotated[str, Field(min_length=1)]
    phase: Phase
    domain_tags: list[str] | None = None
    k: Annotated[int | None, Field(ge=1, le=20)] = None

    def resolved_k(self) -> int:
        """Server-side resolution: caller's k if provided, else phase default."""
        return self.k if self.k is not None else DEFAULT_K_BY_PHASE[self.phase]


class RetrieveQueryHit(BaseModel):
    skill_id: str
    version_id: str
    canonical_name: str
    raw_prose: str
    score: float


class RetrieveQueryResponse(BaseModel):
    status: Literal["ok"] = "ok"
    results: list[RetrieveQueryHit]
