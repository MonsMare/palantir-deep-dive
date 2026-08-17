"""Shipyard Workbench domain contracts."""

from typing import Any

from .config import LocalRuntimeConfig, ShipyardPaths, write_default_config
from .contracts import (
    AgentProposal,
    AuditEvent,
    DecisionCase,
    GateReviewSnapshot,
    ProjectWorkspace,
    ReleaseCandidate,
)
from .identity import LocalOwnerIdentityProvider

__all__ = [
    "AgentProposal",
    "AuditEvent",
    "DecisionCase",
    "GateReviewSnapshot",
    "LocalRuntimeConfig",
    "LocalOwnerIdentityProvider",
    "LocalShipyardRuntime",
    "ProjectWorkspace",
    "ReleaseCandidate",
    "ShipyardPaths",
    "build_local_runtime",
    "write_default_config",
]


def __getattr__(name: str) -> Any:
    if name in {"LocalShipyardRuntime", "build_local_runtime"}:
        from .runtime import LocalShipyardRuntime, build_local_runtime

        return {
            "LocalShipyardRuntime": LocalShipyardRuntime,
            "build_local_runtime": build_local_runtime,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
