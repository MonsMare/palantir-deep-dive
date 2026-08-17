"""HTTP endpoints for the Local Shipyard Web Runtime."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from aifde.deployment.health import ReadinessReport
from aifde.shipyard.config import LocalRuntimeConfig


class RuntimeConfigResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    profile: Literal["local"]
    api_base_url: str
    identity: str


def build_runtime_router(
    config: LocalRuntimeConfig,
    readiness: Callable[[], ReadinessReport],
) -> APIRouter:
    """Build health and browser bootstrap endpoints for one local runtime."""

    router = APIRouter(tags=["shipyard-runtime"])

    @router.get("/healthz")
    def health() -> dict[str, str]:
        return {"status": "ok", "profile": config.profile}

    @router.get("/readyz", response_model=ReadinessReport)
    def ready() -> ReadinessReport:
        report = readiness()
        if not report.ready:
            raise HTTPException(
                status_code=503,
                detail=report.model_dump(mode="json"),
            )
        return report

    @router.get("/runtime-config", response_model=RuntimeConfigResponse)
    def runtime_config() -> RuntimeConfigResponse:
        return RuntimeConfigResponse(
            profile=config.profile,
            api_base_url="",
            identity=config.owner,
        )

    return router
