"""HTTP contract tests for the Shipyard Workbench application API."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from aifde.api.app import create_app
from aifde.domain.artifacts import Artifact
from aifde.gates.engine import GateEngine
from aifde.registry.sqlite import SQLiteRegistry
from aifde.shipyard.identity import FakeIdentityProvider
from aifde.shipyard.service import ShipyardApplicationService
from aifde.shipyard.provenance import build_artifact_input_snapshot


pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


REQUIRED_GATES = frozenset({"semantic.integrity", "release.governance"})


def workspace_payload(workspace_id: str = "ws-1") -> dict[str, Any]:
    return {
        "workspace_id": workspace_id,
        "project_id": "project-1",
        "name": "Delivery Workbench",
        "domain_pack": "software_delivery",
    }


def decision_case_payload(case_id: str = "case-1") -> dict[str, Any]:
    return {
        "case_id": case_id,
        "name": "Prioritize delivery work",
        "objective": "Choose the next work item",
        "decision_owner": "alice",
        "users": ["delivery-lead"],
        "trigger": "A work item is ready",
        "inputs": ["backlog"],
        "actions": ["prioritize"],
        "baseline": "manual review",
        "success_definition": "The highest-value item is selected",
        "failure_definition": "A blocked item is selected",
    }


def proposal_payload(proposal_id: str = "proposal-1") -> dict[str, Any]:
    return {
        "proposal_id": proposal_id,
        "task_packet_id": "packet-1",
        "proposed_changes": {"kind": "DecisionContract", "status": "draft"},
        "affected_artifact_ids": [],
        "evidence_refs": [],
        "validation_results": [{"status": "passed"}],
        "confidence": 0.8,
        "risks": ["forecast drift"],
        "open_questions": ["which horizon"],
        "next_step": "request human review",
    }


def gate_payload(
    gate_id: str,
    artifact: Artifact,
    *,
    gate_run_id: str | None = None,
    status: str = "passed",
) -> dict[str, Any]:
    input_snapshot = build_artifact_input_snapshot([artifact])
    definition = GateEngine().get_definition(gate_id)
    return {
        "gate_run_id": gate_run_id or f"{gate_id}:run-1",
        "gate_id": gate_id,
        "severity": "hard",
        "status": status,
        "artifact_hashes": input_snapshot.artifact_hashes,
        "artifact_versions": input_snapshot.artifact_versions,
        "source_snapshot_id": input_snapshot.source_snapshot_id,
        "source_snapshot_hash": input_snapshot.source_snapshot_hash,
        "input_snapshot_hash": input_snapshot.input_snapshot_hash,
        "validator_version": definition.validator_version,
        "definition_fingerprint": definition.definition_fingerprint,
        "violations": [],
        "warnings": [],
        "evidence_refs": input_snapshot.evidence_refs,
        "stale": False,
    }


@pytest.fixture
def service(tmp_path):
    registry = SQLiteRegistry(tmp_path / "shipyard.db")
    identity = FakeIdentityProvider()
    identity.bind("alice", "human", {"workspace-owner", "release-owner"})
    identity.bind("bob", "human", {"workspace-owner", "release-owner"})
    identity.bind("agent-1", "agent", {"builder"})
    identity.bind("gate-runner", "system", {"gate-runner"})
    application = ShipyardApplicationService(
        registry,
        identity_provider=identity,
        required_gate_ids=REQUIRED_GATES,
    )
    try:
        yield application
    finally:
        registry.close()


@pytest.fixture
def client(service: ShipyardApplicationService) -> TestClient:
    app = create_app(
        registry=service.registry,
        gate_engine=SimpleNamespace(),
        stage_runner=SimpleNamespace(),
        action_broker=SimpleNamespace(),
        shipyard_service=service,
    )
    return TestClient(app)


def test_create_workspace_uses_authenticated_header_not_request_actor(
    client: TestClient,
) -> None:
    response = client.post(
        "/workspaces",
        headers={"X-Shipyard-Identity": "alice"},
        json=workspace_payload(),
    )

    assert response.status_code == 201
    assert response.json()["owner"] == "alice"


def test_request_body_actor_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/workspaces",
        headers={"X-Shipyard-Identity": "alice"},
        json=workspace_payload() | {"actor": "attacker"},
    )

    assert response.status_code == 422


@pytest.mark.parametrize("forbidden_field", ["actor", "authority", "approval"])
def test_workspace_request_rejects_all_authority_claim_fields(
    client: TestClient,
    forbidden_field: str,
) -> None:
    response = client.post(
        "/workspaces",
        headers={"X-Shipyard-Identity": "alice"},
        json=workspace_payload() | {forbidden_field: "attacker"},
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("headers", "status_code"),
    [({}, 401), ({"X-Shipyard-Identity": "unknown"}, 403)],
)
def test_identity_header_is_required_and_must_be_bound(
    client: TestClient,
    headers: dict[str, str],
    status_code: int,
) -> None:
    response = client.get("/workspaces", headers=headers)

    assert response.status_code == status_code


def test_workspaces_can_be_created_listed_and_read(client: TestClient) -> None:
    created = client.post(
        "/workspaces",
        headers={"X-Shipyard-Identity": "alice"},
        json=workspace_payload(),
    )

    assert created.status_code == 201
    assert created.json()["revision"] == 1

    listed = client.get("/workspaces", headers={"X-Shipyard-Identity": "alice"})
    detail = client.get(
        "/workspaces/ws-1", headers={"X-Shipyard-Identity": "alice"}
    )

    assert listed.status_code == 200
    assert listed.json()[0]["workspace_id"] == "ws-1"
    assert detail.status_code == 200
    assert detail.json()["workspace_id"] == "ws-1"


def test_decision_case_create_and_list_delegate_to_service(
    client: TestClient,
) -> None:
    client.post(
        "/workspaces",
        headers={"X-Shipyard-Identity": "alice"},
        json=workspace_payload(),
    )

    created = client.post(
        "/workspaces/ws-1/decision-cases",
        headers={"X-Shipyard-Identity": "alice"},
        json=decision_case_payload(),
    )
    listed = client.get(
        "/workspaces/ws-1/decision-cases",
        headers={"X-Shipyard-Identity": "alice"},
    )

    assert created.status_code == 201
    assert created.json()["workspace_id"] == "ws-1"
    assert listed.status_code == 200
    assert [item["case_id"] for item in listed.json()] == ["case-1"]


def test_agent_proposal_uses_header_identity_and_decision_body_is_strict(
    client: TestClient,
) -> None:
    client.post(
        "/workspaces",
        headers={"X-Shipyard-Identity": "alice"},
        json=workspace_payload(),
    )

    submitted = client.post(
        "/workspaces/ws-1/proposals",
        headers={"X-Shipyard-Identity": "agent-1"},
        json=proposal_payload(),
    )
    decided = client.post(
        "/proposals/proposal-1/decision",
        headers={"X-Shipyard-Identity": "alice"},
        json={"decision": "return"},
    )
    rejected = client.post(
        "/proposals/proposal-1/decision",
        headers={"X-Shipyard-Identity": "alice"},
        json={"decision": "accept", "actor": "attacker"},
    )

    assert submitted.status_code == 201
    assert submitted.json()["producer"] == "agent-1"
    assert decided.status_code == 200
    assert decided.json()["status"] == "returned"
    assert rejected.status_code == 422


def test_roles_are_enforced_at_the_service_boundary(client: TestClient, service) -> None:
    agent_workspace = client.post(
        "/workspaces",
        headers={"X-Shipyard-Identity": "agent-1"},
        json=workspace_payload("agent-workspace"),
    )
    created = client.post(
        "/workspaces",
        headers={"X-Shipyard-Identity": "alice"},
        json=workspace_payload(),
    )
    artifact = Artifact.build(
        artifact_id="artifact-1",
        project_id="project-1",
        kind="DecisionContract",
        content={"objective": "forecast"},
        owner="alice",
    )
    service.register_artifact(
        "ws-1",
        artifact,
        service.identity_provider.resolve({"X-Shipyard-Identity": "alice"}),
    )

    agent_proposal = client.post(
        "/workspaces/ws-1/proposals",
        headers={"X-Shipyard-Identity": "agent-1"},
        json=proposal_payload(),
    )
    human_proposal = client.post(
        "/workspaces/ws-1/proposals",
        headers={"X-Shipyard-Identity": "alice"},
        json=proposal_payload("proposal-human"),
    )
    human_gate = client.post(
        "/workspaces/ws-1/gate-reviews",
        headers={"X-Shipyard-Identity": "alice"},
        json=gate_payload("semantic.integrity", artifact),
    )
    system_gate = client.post(
        "/workspaces/ws-1/gate-reviews",
        headers={"X-Shipyard-Identity": "gate-runner"},
        json=gate_payload("semantic.integrity", artifact),
    )
    agent_decision = client.post(
        "/proposals/proposal-1/decision",
        headers={"X-Shipyard-Identity": "agent-1"},
        json={"decision": "reject"},
    )
    agent_release = client.post(
        "/workspaces/ws-1/release-candidates",
        headers={"X-Shipyard-Identity": "agent-1"},
        json={"artifact_ids": ["artifact-1"], "gate_run_ids": []},
    )

    assert agent_workspace.status_code == 403
    assert created.status_code == 201
    assert agent_proposal.status_code == 201
    assert human_proposal.status_code == 403
    assert human_gate.status_code == 403
    assert system_gate.status_code == 201
    assert agent_decision.status_code == 403
    assert agent_release.status_code == 403


def test_stale_proposal_decision_is_a_conflict(client: TestClient, service) -> None:
    client.post(
        "/workspaces",
        headers={"X-Shipyard-Identity": "alice"},
        json=workspace_payload(),
    )
    client.post(
        "/workspaces/ws-1/proposals",
        headers={"X-Shipyard-Identity": "agent-1"},
        json=proposal_payload(),
    )
    artifact = Artifact.build(
        artifact_id="artifact-1",
        project_id="project-1",
        kind="DecisionContract",
        content={"objective": "forecast"},
        owner="alice",
    )
    service.register_artifact(
        "ws-1",
        artifact,
        service.identity_provider.resolve({"X-Shipyard-Identity": "alice"}),
    )

    response = client.post(
        "/proposals/proposal-1/decision",
        headers={"X-Shipyard-Identity": "alice"},
        json={"decision": "accept"},
    )

    assert response.status_code == 409


def test_release_candidate_route_returns_conflict_when_gate_is_not_passed(
    client: TestClient,
) -> None:
    client.post(
        "/workspaces",
        headers={"X-Shipyard-Identity": "alice"},
        json=workspace_payload(),
    )

    response = client.post(
        "/workspaces/ws-1/release-candidates",
        headers={"X-Shipyard-Identity": "alice"},
        json={"artifact_ids": ["artifact-1"], "gate_run_ids": []},
    )

    assert response.status_code == 409


def test_gate_reviews_and_release_candidates_are_json_contracts(
    client: TestClient,
    service,
) -> None:
    client.post(
        "/workspaces",
        headers={"X-Shipyard-Identity": "alice"},
        json=workspace_payload(),
    )
    artifact = Artifact.build(
        artifact_id="artifact-1",
        project_id="project-1",
        kind="DecisionContract",
        content={"objective": "forecast"},
        owner="alice",
    )
    service.register_artifact(
        "ws-1",
        artifact,
        service.identity_provider.resolve({"X-Shipyard-Identity": "alice"}),
    )

    for gate_id in sorted(REQUIRED_GATES):
        review = client.post(
            "/workspaces/ws-1/gate-reviews",
            headers={"X-Shipyard-Identity": "gate-runner"},
            json=gate_payload(gate_id, artifact),
        )
        assert review.status_code == 201
        assert review.json()["workspace_id"] == "ws-1"

    candidate = client.post(
        "/workspaces/ws-1/release-candidates",
        headers={"X-Shipyard-Identity": "alice"},
        json={
            "artifact_ids": ["artifact-1"],
            "gate_run_ids": [
                "release.governance:run-1",
                "semantic.integrity:run-1",
            ],
        },
    )

    assert candidate.status_code == 201
    assert candidate.json()["status"] == "ready"
    json.dumps(candidate.json())


def test_snapshot_is_fully_serializable_and_missing_records_are_404(
    client: TestClient,
) -> None:
    client.post(
        "/workspaces",
        headers={"X-Shipyard-Identity": "alice"},
        json=workspace_payload(),
    )

    snapshot = client.get(
        "/workspaces/ws-1/snapshot",
        headers={"X-Shipyard-Identity": "alice"},
    )
    missing_workspace = client.get(
        "/workspaces/missing",
        headers={"X-Shipyard-Identity": "alice"},
    )
    missing_decisions = client.get(
        "/workspaces/missing/decision-cases",
        headers={"X-Shipyard-Identity": "alice"},
    )

    assert snapshot.status_code == 200
    json.dumps(snapshot.json())
    assert snapshot.json()["workspace"]["workspace_id"] == "ws-1"
    assert missing_workspace.status_code == 404
    assert missing_decisions.status_code == 404


def test_workspace_owner_policy_blocks_cross_workspace_reads_and_writes(
    client: TestClient,
    service,
) -> None:
    created = client.post(
        "/workspaces",
        headers={"X-Shipyard-Identity": "alice"},
        json=workspace_payload("ws-owner-api"),
    )
    assert created.status_code == 201

    listed_by_bob = client.get(
        "/workspaces", headers={"X-Shipyard-Identity": "bob"}
    )
    detail_by_bob = client.get(
        "/workspaces/ws-owner-api", headers={"X-Shipyard-Identity": "bob"}
    )
    decisions_by_bob = client.get(
        "/workspaces/ws-owner-api/decision-cases",
        headers={"X-Shipyard-Identity": "bob"},
    )
    snapshot_by_bob = client.get(
        "/workspaces/ws-owner-api/snapshot",
        headers={"X-Shipyard-Identity": "bob"},
    )
    decision_write_by_bob = client.post(
        "/workspaces/ws-owner-api/decision-cases",
        headers={"X-Shipyard-Identity": "bob"},
        json=decision_case_payload("case-owner-api"),
    )

    submitted = client.post(
        "/workspaces/ws-owner-api/proposals",
        headers={"X-Shipyard-Identity": "agent-1"},
        json=proposal_payload("proposal-owner-api"),
    )
    proposal_decision_by_bob = client.post(
        "/proposals/proposal-owner-api/decision",
        headers={"X-Shipyard-Identity": "bob"},
        json={"decision": "return"},
    )

    artifact = Artifact.build(
        artifact_id="artifact-owner-api",
        project_id="project-1",
        kind="DecisionContract",
        content={"objective": "forecast"},
        owner="alice",
    )
    service.register_artifact(
        "ws-owner-api",
        artifact,
        service.identity_provider.resolve({"subject": "alice"}),
    )
    for gate_id in sorted(REQUIRED_GATES):
        gate = client.post(
            "/workspaces/ws-owner-api/gate-reviews",
            headers={"X-Shipyard-Identity": "gate-runner"},
            json=gate_payload(gate_id, artifact),
        )
        assert gate.status_code == 201
    release_by_bob = client.post(
        "/workspaces/ws-owner-api/release-candidates",
        headers={"X-Shipyard-Identity": "bob"},
        json={
            "artifact_ids": [artifact.artifact_id],
            "gate_run_ids": [
                "release.governance:run-1",
                "semantic.integrity:run-1",
            ],
        },
    )

    assert listed_by_bob.status_code == 200
    assert listed_by_bob.json() == []
    assert detail_by_bob.status_code == 403
    assert decisions_by_bob.status_code == 403
    assert snapshot_by_bob.status_code == 403
    assert decision_write_by_bob.status_code == 403
    assert submitted.status_code == 201
    assert proposal_decision_by_bob.status_code == 403
    assert release_by_bob.status_code == 403


def test_workbench_router_is_only_mounted_when_service_is_supplied(tmp_path) -> None:
    registry = SQLiteRegistry(tmp_path / "legacy.db")
    try:
        app = create_app(
            registry=registry,
            gate_engine=SimpleNamespace(),
            stage_runner=SimpleNamespace(),
            action_broker=SimpleNamespace(),
        )
        response = TestClient(app).get("/workspaces")

        assert response.status_code == 404
    finally:
        registry.close()
