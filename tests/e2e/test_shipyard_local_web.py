"""End-to-end contract for the local Shipyard Web Runtime."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from aifde.api.static import FrontendNotBuiltError
from aifde.shipyard.config import LocalRuntimeConfig
from aifde.shipyard.runtime import LocalShipyardRuntime, build_local_runtime

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def runtime(tmp_path: Path) -> LocalShipyardRuntime:
    frontend = tmp_path / "workbench" / "dist"
    frontend.mkdir(parents=True)
    (frontend / "index.html").write_text(
        "<!doctype html><html><body><div id='root'>Workbench</div></body></html>",
        encoding="utf-8",
    )
    value = build_local_runtime(
        LocalRuntimeConfig(project_root=tmp_path, owner="alice"),
    )
    try:
        yield value
    finally:
        value.close()


@pytest.fixture
def client(runtime: LocalShipyardRuntime) -> TestClient:
    return TestClient(runtime.app)


def workspace_payload(workspace_id: str = "ws-e2e") -> dict[str, Any]:
    return {
        "workspace_id": workspace_id,
        "project_id": "project-e2e",
        "name": "Local Workbench",
        "domain_pack": "software_delivery",
    }


def test_local_web_serves_workbench_and_runtime_contract(
    client: TestClient,
) -> None:
    health = client.get("/healthz")
    ready = client.get("/readyz")
    runtime_config = client.get("/runtime-config")
    index = client.get("/")

    assert health.status_code == 200
    assert health.json() == {"status": "ok", "profile": "local"}
    assert ready.status_code == 200
    assert ready.json()["ready"] is True
    assert index.status_code == 200
    assert "Workbench" in index.text
    assert runtime_config.status_code == 200
    assert runtime_config.json() == {
        "profile": "local",
        "api_base_url": "",
        "identity": "alice",
    }
    assert "database_path" not in runtime_config.text
    assert "project_root" not in runtime_config.text
    assert "api_key" not in runtime_config.text


def test_local_web_uses_runtime_owner_for_workspace_authorization(
    client: TestClient,
) -> None:
    created = client.post(
        "/workspaces",
        headers={"X-Shipyard-Identity": "alice"},
        json=workspace_payload(),
    )
    missing_identity = client.get("/workspaces")
    other_owner = client.get(
        "/workspaces",
        headers={"X-Shipyard-Identity": "bob"},
    )

    assert created.status_code == 201
    assert created.json()["owner"] == "alice"
    assert missing_identity.status_code == 401
    assert other_owner.status_code == 403


def test_readiness_reports_closed_runtime_as_unavailable(
    runtime: LocalShipyardRuntime,
) -> None:
    client = TestClient(runtime.app)
    runtime.close()

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["detail"]["ready"] is False


def test_missing_frontend_fails_before_opening_database(tmp_path: Path) -> None:
    config = LocalRuntimeConfig(project_root=tmp_path, owner="alice")

    with pytest.raises(FrontendNotBuiltError, match="npm run build"):
        build_local_runtime(config)

    assert not config.paths.database_path.exists()
