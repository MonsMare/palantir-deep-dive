"""HTTP API for the AI FDE project cockpit."""

from .app import create_app
from .routes import (
    ActionExecuteRequest,
    ActionOutcomeResponse,
    ArtifactSummary,
    GateSummary,
    StageRunCreateRequest,
    StageRunResponse,
    StageSummary,
    TransitionRequest,
    TransitionResponse,
    build_router,
)

__all__ = [
    "ActionExecuteRequest",
    "ActionOutcomeResponse",
    "ArtifactSummary",
    "GateSummary",
    "StageRunCreateRequest",
    "StageRunResponse",
    "StageSummary",
    "TransitionRequest",
    "TransitionResponse",
    "build_router",
    "create_app",
]
