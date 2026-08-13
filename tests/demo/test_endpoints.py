from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from aifde.tools.actions import ActionBroker, ActionPolicy
from software_delivery_demo.analytics import build_project_snapshot
from software_delivery_demo.actions import register_demo_actions
from software_delivery_demo.app import DemoContext, create_demo_app


pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def client(project_config, bundle, products, tmp_path):
    broker = ActionBroker(
        action_policies=[
            ActionPolicy(action_type="ReplanSprint", required_parameters=("capacity",)),
        ],
        approved_actions=[],
    )
    register_demo_actions(broker)
    context = DemoContext(
        registry=SimpleNamespace(),
        gate_engine=SimpleNamespace(),
        action_broker=broker,
        snapshot_provider=lambda as_of: build_project_snapshot(products, as_of),
        project_root=tmp_path,
        bundle=bundle,
        products=products,
    )
    return TestClient(create_demo_app(context))


def test_demo_endpoint_exposes_change_impact(client: TestClient, bundle) -> None:
    change_id = bundle.changes[0, "change_id"]
    response = client.post(
        f"/demo/change-requests/{change_id}/impact",
        json={"as_of_time": "2026-05-01T00:00:00Z"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["evidence_refs"]
    assert payload["gate_status"]
    assert len(payload["candidate_plans"]) >= 5


def test_requirements_and_requirement_detail_are_read_models(client: TestClient, bundle) -> None:
    listed = client.get("/demo/requirements")
    assert listed.status_code == 200
    requirement_id = listed.json()[0]["requirement_id"]
    detail = client.get(f"/demo/requirements/{requirement_id}")
    assert detail.status_code == 200
    assert detail.json()["requirement_id"] == requirement_id
    assert "work_items" in detail.json()
    assert "evidence_refs" in detail.json()


def test_forecast_payload_contains_baseline_and_model_versions(
    client: TestClient, bundle
) -> None:
    work_item_id = bundle.work_items[0, "work_item_id"]
    response = client.get(
        f"/demo/work-items/{work_item_id}/forecast",
        params={"as_of_time": "2026-03-01T00:00:00Z"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["baseline_version"]
    assert payload["feature_snapshot_id"]
    assert payload["model_version"]


def test_unknown_demo_object_returns_404(client: TestClient) -> None:
    assert client.get("/demo/requirements/unknown").status_code == 404
    assert client.get("/demo/work-items/unknown/forecast").status_code == 404
