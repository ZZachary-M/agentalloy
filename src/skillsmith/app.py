"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from skillsmith.api.compose_models import ErrorResponse
from skillsmith.api.compose_router import get_orchestrator
from skillsmith.api.compose_router import router as compose_router
from skillsmith.api.diagnostics_router import DiagnosticsChecker
from skillsmith.api.diagnostics_router import router as diagnostics_router
from skillsmith.api.health_router import HealthChecker
from skillsmith.api.health_router import router as health_router
from skillsmith.api.retrieve_router import get_retrieve_orchestrator
from skillsmith.api.retrieve_router import router as retrieve_router
from skillsmith.api.skill_router import get_skill_store
from skillsmith.api.skill_router import router as skill_router
from skillsmith.config import get_settings
from skillsmith.lm_client import OpenAICompatClient
from skillsmith.orchestration.compose import (
    AssemblyStageError,
    ComposeOrchestrator,
    RetrievalStageError,
)
from skillsmith.orchestration.retrieve import RetrieveOrchestrator
from skillsmith.reads import InconsistentActiveVersion
from skillsmith.runtime_state import RuntimeCache, load_runtime_cache
from skillsmith.storage.ladybug import LadybugStore
from skillsmith.storage.vector_store import VectorStore, open_or_create
from skillsmith.telemetry import DuckDBTelemetryWriter

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open the runtime store + Ollama client for the app lifetime.

    Loads the active-skill cache at startup (NXS-777).  If loading fails the
    app still starts — ``app.state.runtime`` is ``None`` and the health
    endpoint reflects ``unavailable`` while runtime handlers 503.

    In tests we override ``get_orchestrator`` via ``app.dependency_overrides``
    so no real LadybugDB or Ollama connection is created.
    """
    settings = get_settings()
    settings.ensure_data_dirs()
    store = LadybugStore(settings.ladybug_db_path)
    store.open()
    vector_store: VectorStore = open_or_create(settings.duckdb_path)
    embed_client = OpenAICompatClient(settings.runtime_embed_base_url)
    telemetry = DuckDBTelemetryWriter(vector_store)

    # --- NXS-777: startup-time cache load ---
    runtime: RuntimeCache | None = None
    runtime_load_error: str | None = None
    try:
        runtime = load_runtime_cache(store)
    except Exception as exc:
        logger.error("Runtime cache load failed — service will start in degraded mode: %s", exc)
        runtime_load_error = str(exc)

    app.state.runtime = runtime
    app.state.runtime_load_error = runtime_load_error

    # Wire orchestrators: prefer cache when available, fall back to store so
    # existing store-backed code paths still work (e.g. skill inspection).
    source = runtime if runtime is not None else store

    orchestrator = ComposeOrchestrator(
        source,
        embed_client,
        vector_store,
        telemetry,
        embedding_model=settings.runtime_embedding_model,
    )
    retrieve_orch = RetrieveOrchestrator(
        source,
        embed_client,
        vector_store,
        telemetry,
        embedding_model=settings.runtime_embedding_model,
    )
    app.dependency_overrides[get_orchestrator] = lambda: orchestrator
    app.dependency_overrides[get_retrieve_orchestrator] = lambda: retrieve_orch
    app.dependency_overrides[get_skill_store] = lambda: store  # inspection always live
    health_checker = HealthChecker(
        store,
        embed_client,
        vector_store,
        settings.runtime_embedding_model,
        runtime_load_error=runtime_load_error,
    )
    app.state.health_checker = health_checker
    app.state.diagnostics_checker = DiagnosticsChecker(store, runtime, health_checker)
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_orchestrator, None)
        app.dependency_overrides.pop(get_retrieve_orchestrator, None)
        app.dependency_overrides.pop(get_skill_store, None)
        telemetry.close()
        embed_client.close()
        vector_store.close()
        store.close()


def _stage_error_response(stage: str, err: object) -> JSONResponse:
    assert isinstance(err, RetrievalStageError | AssemblyStageError)
    body = ErrorResponse(
        stage=stage,  # type: ignore[arg-type]
        code=err.code,
        message=err.message,
        available=err.available,
    )
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content=body.model_dump(),
    )


def create_app(*, use_default_lifespan: bool = True) -> FastAPI:
    """Build the FastAPI app.

    ``use_default_lifespan=False`` skips the production lifespan (which opens
    LadybugDB and the Ollama client). Tests pass ``False`` and wire their own
    dependency overrides via ``app.dependency_overrides``.
    """
    app = FastAPI(
        title="skillsmith",
        version="0.1.0",
        description="Runtime skill composition service.",
        lifespan=lifespan if use_default_lifespan else None,
    )

    @app.exception_handler(RetrievalStageError)
    async def _retrieval_handler(_req: Request, err: RetrievalStageError) -> JSONResponse:
        return _stage_error_response("retrieval", err)

    @app.exception_handler(AssemblyStageError)
    async def _assembly_handler(_req: Request, err: AssemblyStageError) -> JSONResponse:
        return _stage_error_response("assembly", err)

    @app.exception_handler(InconsistentActiveVersion)
    async def _inconsistent_version_handler(
        _req: Request, err: InconsistentActiveVersion
    ) -> JSONResponse:
        body = {
            "code": "inconsistent_active_version",
            "skill_id": err.skill_id,
            "detail": str(err),
        }
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=body,
        )

    app.include_router(health_router)
    app.include_router(compose_router)
    app.include_router(retrieve_router)
    app.include_router(skill_router)
    app.include_router(diagnostics_router)

    return app


app = create_app()
