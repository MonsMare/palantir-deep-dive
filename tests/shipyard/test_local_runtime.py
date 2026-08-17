from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aifde.api.static import FrontendNotBuiltError
from aifde.shipyard.config import LocalRuntimeConfig, write_default_config
from aifde.shipyard.runtime import build_local_runtime


def _config_with_frontend(tmp_path: Path) -> LocalRuntimeConfig:
    frontend = tmp_path / "workbench/dist"
    frontend.mkdir(parents=True)
    (frontend / "index.html").write_text("workbench", encoding="utf-8")
    write_default_config(tmp_path, owner="alice")
    return LocalRuntimeConfig.load(tmp_path)


def test_local_runtime_assembles_authenticated_shipyard_app(tmp_path: Path) -> None:
    config = _config_with_frontend(tmp_path)

    runtime = build_local_runtime(config)
    try:
        client = TestClient(runtime.app)
        response = client.post(
            "/workspaces",
            headers={"X-Shipyard-Identity": "alice"},
            json={
                "workspace_id": "ws-local",
                "project_id": "project-local",
                "name": "Local Workbench",
                "domain_pack": "software_delivery",
            },
        )

        assert response.status_code == 201
        assert response.json()["owner"] == "alice"
        assert runtime.url == "http://127.0.0.1:3080"
        assert runtime.readiness().ready is True
    finally:
        runtime.close()


def test_local_runtime_reopens_sqlite_state(tmp_path: Path) -> None:
    config = _config_with_frontend(tmp_path)

    first = build_local_runtime(config)
    first.service.create_workspace(
        {
            "workspace_id": "ws-reopen",
            "project_id": "project-reopen",
            "name": "Reopen",
            "domain_pack": "software_delivery",
        },
        first.identity.principal,
    )
    first.close()

    second = build_local_runtime(config)
    try:
        workspaces = second.service.list_workspaces(second.identity.principal)
        assert [workspace.workspace_id for workspace in workspaces] == ["ws-reopen"]
    finally:
        second.close()


def test_missing_frontend_fails_before_creating_sqlite_database(
    tmp_path: Path,
) -> None:
    write_default_config(tmp_path, owner="alice")
    config = LocalRuntimeConfig.load(tmp_path)

    with pytest.raises(FrontendNotBuiltError, match="npm run build"):
        build_local_runtime(config)

    assert config.paths.database_path.exists() is False


def test_local_runtime_close_is_idempotent(tmp_path: Path) -> None:
    config = _config_with_frontend(tmp_path)
    runtime = build_local_runtime(config)

    runtime.close()
    runtime.close()

    assert runtime.closed is True
    assert runtime.readiness().ready is False
