"""Composition root for the single-process Local Shipyard Web Runtime."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from aifde.api.app import create_shipyard_app
from aifde.api.static import resolve_workbench_dist
from aifde.deployment.health import HealthCheck, ReadinessReport
from aifde.registry.sqlite import SQLiteRegistry
from aifde.shipyard.config import LocalRuntimeConfig, ShipyardPaths
from aifde.shipyard.identity import LocalOwnerIdentityProvider
from aifde.shipyard.service import ShipyardApplicationService


class LocalShipyardRuntime:
    """Own all resources created for one Local Profile process."""

    def __init__(
        self,
        *,
        config: LocalRuntimeConfig,
        paths: ShipyardPaths,
        registry: SQLiteRegistry,
        identity: LocalOwnerIdentityProvider,
        service: ShipyardApplicationService,
        frontend_dir: Path,
    ) -> None:
        self.config = config
        self.paths = paths
        self.registry = registry
        self.identity = identity
        self.service = service
        self.frontend_dir = frontend_dir
        self.closed = False
        self.app = create_shipyard_app(
            shipyard_service=service,
            runtime_config=config,
            frontend_dir=frontend_dir,
            readiness=self.readiness,
        )

    @property
    def url(self) -> str:
        return "http://" + self.config.server.host + ":" + str(self.config.server.port)

    def readiness(self) -> ReadinessReport:
        registry_ready = self.paths.database_path.exists() and not self.closed
        artifact_ready = self.paths.artifact_path.is_dir()
        frontend_ready = (
            self.frontend_dir.is_dir()
            and (self.frontend_dir / "index.html").is_file()
        )
        checks = {
            "registry": HealthCheck(
                component="registry",
                status="ready" if registry_ready else "not_ready",
                detail=(
                    "SQLite registry is open"
                    if registry_ready
                    else "SQLite registry is closed or missing"
                ),
            ),
            "artifact_store": HealthCheck(
                component="artifact_store",
                status="ready" if artifact_ready else "not_ready",
                detail=(
                    "Artifact directory is available"
                    if artifact_ready
                    else "Artifact directory is missing"
                ),
            ),
            "frontend": HealthCheck(
                component="frontend",
                status="ready" if frontend_ready else "not_ready",
                detail=(
                    "Workbench assets are available"
                    if frontend_ready
                    else "Workbench index.html is missing"
                ),
            ),
        }
        return ReadinessReport(
            ready=all(check.status == "ready" for check in checks.values()),
            checks=checks,
        )

    def close(self) -> None:
        """Close the Registry exactly once without deleting local state."""

        if self.closed:
            return
        try:
            self.registry.close()
        finally:
            self.closed = True


def build_local_runtime(config: LocalRuntimeConfig) -> LocalShipyardRuntime:
    """Validate assets, then assemble the governed local application."""

    paths = config.paths
    paths.ensure_directories()
    frontend_dir = resolve_workbench_dist(
        config.project_root,
        config.resolve_frontend_dir(),
    )
    registry: SQLiteRegistry | None = None
    try:
        registry = SQLiteRegistry(paths.database_path)
        identity = LocalOwnerIdentityProvider(config.owner)
        service = ShipyardApplicationService(
            registry,
            identity_provider=identity,
            required_gate_ids=frozenset(config.required_gate_ids),
        )
        return LocalShipyardRuntime(
            config=config,
            paths=paths,
            registry=registry,
            identity=identity,
            service=service,
            frontend_dir=frontend_dir,
        )
    except BaseException:
        if registry is not None:
            registry.close()
        raise


__all__ = ["LocalShipyardRuntime", "build_local_runtime"]
