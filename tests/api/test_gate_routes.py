"""HTTP contract tests for the gate and action routes."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from aifde.api.app import create_app
from aifde.domain.actions import ActionRequest
from aifde.policy.capabilities import ActorRole, ApprovedActionRecord
from aifde.tools.actions import ActionBroker


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


def governed_action_payload(
    *, action_id: str = "action-1", target_id: str = "sprint-1"
) -> dict[str, Any]:
    """Build the explicit governed request shape accepted by the API."""

    return {
        "request": {
            "action_id": action_id,
            "action_type": "ReplanSprint",
            "target_id": target_id,
            "parameters": {"capacity": 8},
            "requested_by": "builder-1",
            "idempotency_key": f"idem-{action_id}",
            "execution_mode": "mock",
            "policy_id": "mock-actions",
            "policy_version": "1",
            "validation_id": f"validation-{action_id}",
            "validated_by": "deterministic-verifier-1",
            "validation_status": "passed",
            "approval_id": f"approval-{action_id}",
            "approval_actor": "domain-owner-1",
            "approval_role": "domain-owner",
            "approval_status": "approved",
            "audit_ref": f"audit-{action_id}",
            "audit_actor": "audit-service",
            "outcome_status": "pending",
        },
        "actor": "release-owner-1",
    }


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
    response = client.post("/actions", json=governed_action_payload())

    assert response.status_code == 200
    assert response.json()["outcome_id"] == "outcome-1"
    assert action_broker.requests[0][1] == "release-owner-1"
    assert isinstance(action_broker.requests[0][0], ActionRequest)


def test_action_route_rejects_ungoverned_request_before_fake_broker(
    client: TestClient, action_broker: FakeActionBroker
) -> None:
    response = client.post(
        "/actions",
        json={
            "request": {
                "action_id": "action-1",
                "action_type": "ReplanSprint",
                "target_id": "sprint-1",
                "parameters": {"capacity": 8},
                "requested_by": "builder-1",
                "idempotency_key": "idem-1",
            },
            "actor": "release-owner-1",
        },
    )

    assert response.status_code == 422
    assert action_broker.requests == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("success", True),
        ("status", "succeeded"),
        ("approval_status", "approved"),
        ("outcome_id", "forged-outcome"),
    ],
)
def test_action_route_rejects_caller_forged_outcome_or_approval_fields(
    client: TestClient, action_broker: FakeActionBroker, field: str, value: Any
) -> None:
    payload = governed_action_payload()
    payload[field] = value
    response = client.post("/actions", json=payload)

    assert response.status_code == 422
    assert action_broker.requests == []


def test_real_action_broker_rejects_mismatched_approval_claim() -> None:
    payload = governed_action_payload()
    payload["request"]["approval_id"] = "forged-approval"
    record = ApprovedActionRecord(
        action_id="action-1",
        action_type="ReplanSprint",
        execution_mode="mock",
        requested_by="builder-1",
        validation_status="passed",
        approval_id="approval-action-1",
        approval_actor="domain-owner-1",
        approval_role=ActorRole.DOMAIN_OWNER,
        approval_status="approved",
    )
    broker = ActionBroker(approved_actions=[record])
    app = create_app(
        registry=FakeRegistry(),
        gate_engine=FakeGateEngine(),
        stage_runner=SimpleNamespace(),
        action_broker=broker,
    )

    response = TestClient(app).post("/actions", json=payload)

    assert response.status_code == 403
    assert broker.audit_records
    assert broker.audit_records[-1].event == "deny"
    with pytest.raises(KeyError):
        broker.get_outcome("action-1")


def test_real_action_broker_executes_only_a_fully_governed_request() -> None:
    payload = governed_action_payload()
    record = ApprovedActionRecord(
        action_id="action-1",
        action_type="ReplanSprint",
        execution_mode="mock",
        requested_by="builder-1",
        validation_status="passed",
        approval_id="approval-action-1",
        approval_actor="domain-owner-1",
        approval_role=ActorRole.DOMAIN_OWNER,
        approval_status="approved",
    )
    broker = ActionBroker(approved_actions=[record])
    app = create_app(
        registry=FakeRegistry(),
        gate_engine=FakeGateEngine(),
        stage_runner=SimpleNamespace(),
        action_broker=broker,
    )

    response = TestClient(app).post("/actions", json=payload)

    assert response.status_code == 200
    assert response.json()["status"] == "succeeded"
    assert broker.get_outcome("action-1").action_id == "action-1"


def test_real_action_broker_rejects_missing_governance_without_fallback_execution() -> None:
    broker = ActionBroker()
    app = create_app(
        registry=FakeRegistry(),
        gate_engine=FakeGateEngine(),
        stage_runner=SimpleNamespace(),
        action_broker=broker,
    )

    minimal_request = {
        key: governed_action_payload()["request"][key]
        for key in (
            "action_id",
            "action_type",
            "target_id",
            "parameters",
            "requested_by",
            "idempotency_key",
        )
    }
    response = TestClient(app).post(
        "/actions",
        json={"request": minimal_request, "actor": "release-owner-1"},
    )

    assert response.status_code == 422
    assert broker.audit_records == []


def test_real_action_broker_denies_unapproved_execution() -> None:
    broker = ActionBroker()
    app = create_app(
        registry=FakeRegistry(),
        gate_engine=FakeGateEngine(),
        stage_runner=SimpleNamespace(),
        action_broker=broker,
    )

    response = TestClient(app).post("/actions", json=governed_action_payload())

    assert response.status_code == 403
    with pytest.raises(KeyError):
        broker.get_outcome("action-1")
    assert broker.audit_records[-1].event == "deny"
