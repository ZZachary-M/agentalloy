"""Compose endpoint router — real handler wired to ComposeOrchestrator."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse

from skillsmith.api.compose_models import (
    ComposedResult,
    ComposeRequest,
    EmptyResult,
    ErrorResponse,
)
from skillsmith.orchestration.compose import ComposeOrchestrator

router = APIRouter()


# Dependency provider — overridden in tests via app.dependency_overrides[].
def get_orchestrator() -> ComposeOrchestrator:
    raise RuntimeError("get_orchestrator must be bound during app lifespan; no default available")


@router.post(
    "/compose",
    response_model=ComposedResult | EmptyResult,
    responses={
        503: {"model": ErrorResponse, "description": "Retrieval or assembly stage failure"},
    },
    summary="Compose task-specific guidance",
    description=(
        "Returns assembled guidance from active domain fragments plus applicable "
        "system-skill fragments. System-skill inclusion is stubbed in M1 and lands "
        "with NXS-771/NXS-772 in M2."
    ),
)
async def compose(
    req: ComposeRequest,
    orchestrator: ComposeOrchestrator = Depends(get_orchestrator),
) -> ComposedResult | EmptyResult:
    return await orchestrator.compose(req)


@router.post(
    "/compose/text",
    response_class=PlainTextResponse,
    summary="Compose task-specific guidance as plain text",
    description="Returns only the assembled skill text — no JSON wrapper. Intended for agent curl calls.",
)
async def compose_text(
    req: ComposeRequest,
    orchestrator: ComposeOrchestrator = Depends(get_orchestrator),
) -> PlainTextResponse:
    result = await orchestrator.compose(req)
    return PlainTextResponse(content=result.output)
