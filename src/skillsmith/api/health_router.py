"""Enhanced health endpoint with dependency checks (NXS-775)."""

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

from skillsmith.lm_client import LMClientError, OpenAICompatClient
from skillsmith.storage.ladybug import LadybugStore
from skillsmith.storage.vector_store import VectorStore

router = APIRouter()

DepStatus = Literal["ok", "unavailable"]
OverallStatus = Literal["healthy", "degraded", "unavailable"]


class DependencyStatus(BaseModel):
    status: DepStatus
    impact: str | None = None
    detail: str | None = None


class HealthResponse(BaseModel):
    status: OverallStatus
    dependencies: dict[str, DependencyStatus] | None = None


class HealthChecker:
    def __init__(
        self,
        store: LadybugStore,
        lm: OpenAICompatClient,
        vector_store: VectorStore,
        embedding_model: str,
        *,
        runtime_load_error: str | None = None,
    ) -> None:
        self._store = store
        self._lm = lm
        self._vector_store = vector_store
        self._embedding_model = embedding_model
        self._runtime_load_error = runtime_load_error

    async def check(self) -> HealthResponse:
        store_ok, tel_ok, embed_ok = await asyncio.gather(
            asyncio.to_thread(self._probe_runtime_store),
            asyncio.to_thread(self._probe_telemetry_store),
            asyncio.to_thread(self._probe_embed_model),
        )

        # NXS-777: reflect startup cache load result
        cache_err = self._runtime_load_error

        deps: dict[str, DependencyStatus] = {
            "runtime_store": DependencyStatus(
                status="ok" if store_ok is None else "unavailable",
                impact="compose and retrieve requests will fail" if store_ok else None,
                detail=store_ok,
            ),
            "telemetry_store": DependencyStatus(
                status="ok" if tel_ok is None else "unavailable",
                impact="trace persistence degraded; runtime requests remain successful"
                if tel_ok
                else None,
                detail=tel_ok,
            ),
            "embedding_runtime": DependencyStatus(
                status="ok" if embed_ok is None else "unavailable",
                impact="semantic retrieve and compose will fail; by-id retrieve and read-skill remain available"
                if embed_ok
                else None,
                detail=embed_ok,
            ),
            "runtime_cache": DependencyStatus(
                status="ok" if cache_err is None else "unavailable",
                impact="compose and retrieve requests will fail; restart required to reload active data"
                if cache_err
                else None,
                detail=cache_err,
            ),
        }

        if store_ok is not None or cache_err is not None:
            overall: OverallStatus = "unavailable"
        elif embed_ok is not None or tel_ok is not None:
            overall = "degraded"
        else:
            overall = "healthy"

        return HealthResponse(status=overall, dependencies=deps)

    def _probe_runtime_store(self) -> str | None:
        try:
            self._store.scalar("RETURN 1")
            return None
        except Exception as exc:
            return str(exc)

    def _probe_telemetry_store(self) -> str | None:
        try:
            # DuckDB ``composition_traces`` lives in the same VectorStore.
            # A successful count() proves the table is open and queryable.
            self._vector_store.count_traces()
            return None
        except Exception as exc:
            return str(exc)

    def _probe_embed_model(self) -> str | None:
        """FastFlowLM hides the embedding slot from /v1/models, so we probe by
        actually embedding a short string. A 768-dim (or any non-empty) result
        proves both the endpoint and the model are responsive."""
        try:
            vectors = self._lm.embed(model=self._embedding_model, texts=["health"])
            if not vectors or not vectors[0]:
                return f"embed model {self._embedding_model!r} returned empty vector"
            return None
        except LMClientError as exc:
            return str(exc)
        except Exception as exc:
            return str(exc)


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Service health and dependency readiness",
)
async def health(request: Request) -> HealthResponse:
    checker: HealthChecker | None = getattr(request.app.state, "health_checker", None)
    if checker is None:
        return HealthResponse(status="healthy")
    return await checker.check()
