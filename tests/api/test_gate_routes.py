"""HTTP contract tests for the gate and action routes."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from aifde.api.app import create_app


pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


class FakeRegistry:
    def get_project(self, project_id: str) -> SimpleNamespace:
        if project_id != "p1":
            raise KeyError(project_id)
        return SimpleNamespace(project_id=project_id)

    def list_artifacts(self, project_id: str) -> list[SimpleNamespace]:
        self.get_project(project_id)
        return [
            SimpleNamespace(
                artifact_id="decision-1",
                kind="DecisionContract",
                version="1.0.0",
                status="draft",
                content_hash="hash-1",
                updated_at="2026-08-11T00:00:00+00:00",
            )
        ]

    def list_gates(self, project_id: str) -> list[SimpleNamespace]:
        self.get_project(project_id)
        return [
            SimpleNamespace(
                gate_id="semantic.integrity",
                severity="hard",
                status="failed",
                stage_id="decision.contract",
                latest_run_id="gate-run-1",
            )
        ]


class FakeGateEngine:
    pass


class FakeActionBroker:
    def __init__(self) -> None:
        self.requests: list[tuple[object, str]] = []

    def execute(self, request: object, actor: str) -> SimpleNamespace:
        self.requests.append((request, actor))
        return SimpleNamespace(
            outcome_id="outcome-1",
            action_id="action-1",
            status="succeeded",
            success=True,
        )


@pytest.fixture
def action_broker() -> FakeActionBroker:
    return FakeActionBroker()


@pytest.fixture
def client(action_broker: FakeActionBroker) -> TestClient:
    app = create_app(
        registry=FakeRegistry(),
        gate_engine=FakeGateEngine(),
        stage_runner=SimpleNamespace(),
        action_broker=action_broker,
    )
    return TestClient(app)


def test_project_artifact_list_returns_artifact_summary(client: TestClient) -> None:
    response = client.get("/projects/p1/artifacts")

    assert response.status_code == 200
    assert response.json() == [
        {
            "artifact_id": "decision-1",
            "kind": "DecisionContract",
            "version": "1.0.0",
            "status": "draft",
            "content_hash": "hash-1",
            "updated_at": "2026-08-11T00:00:00+00:00",
        }
    ]


def test_project_gate_list_exposes_hard_failure(client: TestClient) -> None:
    response = client.get("/projects/p1/gates")

    assert response.status_code == 200
    assert response.json()[0]["gate_id"] == "semantic.integrity"
    assert response.json()[0]["severity"] == "hard"
    assert response.json()[0]["status"] == "failed"


def test_unknown_project_gate_list_returns_not_found(client: TestClient) -> None:
    response = client.get("/projects/missing/gates")

    assert response.status_code == 404


def test_action_route_delegates_to_broker_boundary(
    client: TestClient, action_broker: FakeActionBroker
) -> None:
    response = client.post(
        "/actions",
        json={
            "action_id": "action-1",
            "action_type": "ReplanSprint",
            "target_id": "sprint-1",
            "parameters": {"capacity": 8},
            "requested_by": "builder-1",
            "idempotency_key": "idem-1",
            "actor": "release-owner-1",
        },
    )

    assert response.status_code == 200
    assert response.json()["outcome_id"] == "outcome-1"
    assert action_broker.requests[0][1] == "release-owner-1"


def test_action_route_does_not_accept_caller_forged_outcome(client: TestClient) -> None:
    response = client.post(
        "/actions",
        json={
            "action_id": "action-1",
            "action_type": "ReplanSprint",
            "target_id": "sprint-1",
            "parameters": {},
            "requested_by": "builder-1",
            "idempotency_key": "idem-1",
            "actor": "release-owner-1",
            "success": True,
            "status": "succeeded",
            "approval_status": "approved",
        },
    )

    assert response.status_code in {200, 422}
    if response.status_code == 200:
        assert "success" not in response.json() or response.json()["success"] is not True
