from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from aifde.api.app import create_shipyard_app
from aifde.deployment.health import HealthCheck, ReadinessReport
from aifde.registry.sqlite import SQLiteRegistry
from aifde.shipyard.config import LocalRuntimeConfig
from aifde.shipyard.identity import LocalOwnerIdentityProvider
from aifde.shipyard.service import ShipyardApplicationService


def ready_report() -> ReadinessReport:
    return ReadinessReport(
        ready=True,
        checks={
            "registry": HealthCheck(
                component="registry",
                status="ready",
                detail="probe passed",
            )
        },
    )


@pytest.fixture
def shipyard_service(tmp_path: Path):
    registry = SQLiteRegistry(tmp_path / "shipyard.db")
    service = ShipyardApplicationService(
        registry,
        identity_provider=LocalOwnerIdentityProvider("alice"),
        required_gate_ids=frozenset(
            {"semantic.integrity", "release.governance"}
        ),
    )
    try:
        yield service
    finally:
        registry.close()


def test_runtime_routes_expose_health_readiness_and_local_identity(
    tmp_path: Path,
    shipyard_service: ShipyardApplicationService,
) -> None:
    frontend = tmp_path / "dist"
    frontend.mkdir()
    (frontend / "index.html").write_text(
        "<html><body>Shipyard Workbench</body></html>",
        encoding="utf-8",
    )
    config = LocalRuntimeConfig(
        project_root=tmp_path,
        owner="alice",
    )
    app = create_shipyard_app(
        shipyard_service=shipyard_service,
        runtime_config=config,
        frontend_dir=frontend,
        readiness=ready_report,
    )

    client = TestClient(app)

    assert client.get("/healthz").json() == {
        "status": "ok",
        "profile": "local",
    }
    assert client.get("/readyz").status_code == 200
    assert client.get("/runtime-config").json() == {
        "profile": "local",
        "api_base_url": "",
        "identity": "alice",
    }
    home = client.get("/")
    assert home.status_code == 200
    assert "Shipyard Workbench" in home.text


def test_shipyard_routes_remain_before_static_mount(
    tmp_path: Path,
    shipyard_service: ShipyardApplicationService,
) -> None:
    frontend = tmp_path / "dist"
    frontend.mkdir()
    (frontend / "index.html").write_text("workbench", encoding="utf-8")
    config = LocalRuntimeConfig(project_root=tmp_path, owner="alice")
    app = create_shipyard_app(
        shipyard_service=shipyard_service,
        runtime_config=config,
        frontend_dir=frontend,
        readiness=ready_report,
    )

    response = TestClient(app).get("/workspaces")

    assert response.status_code == 401
