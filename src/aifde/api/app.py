"""FastAPI application factory for the AI-FDE Shipyard API."""

from __future__ import annotations

from typing import Any

from aifde.policy.capabilities import PolicyEngine
from aifde.shipyard.service import ShipyardApplicationService

try:
    from fastapi import FastAPI
except ImportError:  # pragma: no cover - exercised only without the optional extra
    FastAPI = None  # type: ignore[assignment,misc]


def create_app(
    registry: Any,
    gate_engine: Any,
    stage_runner: Any,
    action_broker: Any,
    policy: PolicyEngine | None = None,
    governed_action_broker: Any | None = None,
    shipyard_service: ShipyardApplicationService | None = None,
) -> Any:
    """Build the HTTP app around the already-authoritative domain services."""

    if FastAPI is None:  # pragma: no cover - dependency is present in API test env
        raise RuntimeError(
            "FastAPI is required for the AI-FDE Shipyard API; install the optional API dependency"
        )

    from .routes import build_router

    app = FastAPI(title="AI-FDE Shipyard API")
    app.state.registry = registry
    app.state.gate_engine = gate_engine
    app.state.stage_runner = stage_runner
    app.state.action_broker = action_broker
    app.state.governed_action_broker = governed_action_broker
    app.state.policy = policy or PolicyEngine()
    app.include_router(
        build_router(
            registry=registry,
            gate_engine=gate_engine,
            stage_runner=stage_runner,
            action_broker=action_broker,
            policy=app.state.policy,
            governed_action_broker=governed_action_broker,
        )
    )
    if shipyard_service is not None:
        from .shipyard_routes import build_router as build_shipyard_router

        app.state.shipyard_service = shipyard_service
        app.include_router(build_shipyard_router(shipyard_service))
    return app
