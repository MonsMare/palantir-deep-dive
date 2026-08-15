from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from aifde.domain.artifacts import Artifact
from aifde.registry.sqlite import SQLiteRegistry
from aifde.shipyard.contracts import GateReviewSnapshot
from aifde.shipyard.identity import (
    FakeIdentityProvider,
    Principal,
    UnauthorizedError,
)
from aifde.shipyard.service import (
    RecordNotFoundError,
    ReleaseBlockedError,
    ShipyardApplicationService,
    StaleRevisionError,
)


REQUIRED_GATES = frozenset({"semantic.integrity", "release.governance"})
UTC = timezone.utc


def human_principal(subject: str = "alice") -> Principal:
    return Principal(
        subject=subject,
        kind="human",
        roles=frozenset({"workspace-owner", "release-owner"}),
    )


def agent_principal(subject: str = "agent-1") -> Principal:
    return Principal(subject=subject, kind="agent", roles=frozenset({"builder"}))


def system_principal(subject: str = "gate-runner") -> Principal:
    return Principal(subject=subject, kind="system", roles=frozenset({"gate-runner"}))


def workspace_input(
    workspace_id: str = "ws-1", project_id: str = "project-1"
) -> dict[str, Any]:
    return {
        "workspace_id": workspace_id,
        "project_id": project_id,
        "name": "Delivery Workbench",
        "domain_pack": "software_delivery",
    }


def decision_case_input(case_id: str = "case-1") -> dict[str, Any]:
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


def proposal_input(proposal_id: str = "proposal-1") -> dict[str, Any]:
    return {
        "proposal_id": proposal_id,
        "task_packet_id": "packet-1",
        "producer": "json-claimed-actor",
        "proposed_changes": {"kind": "DecisionContract", "status": "draft"},
        "affected_artifact_ids": [],
        "evidence_refs": [],
        "validation_results": [{"status": "passed"}],
        "confidence": 0.8,
        "risks": ["forecast drift"],
        "open_questions": ["which horizon"],
        "next_step": "request human review",
    }


def passed_gate(
    workspace_id: str,
    artifact: Artifact,
    gate_id: str,
    *,
    gate_run_id: str | None = None,
    status: str = "passed",
    stale: bool = False,
) -> GateReviewSnapshot:
    return GateReviewSnapshot(
        gate_run_id=gate_run_id or f"{gate_id}:run-1",
        workspace_id=workspace_id,
        gate_id=gate_id,
        severity="hard",
        status=status,
        artifact_hashes={artifact.artifact_id: artifact.content_hash},
        validator_version="validator-1",
        stale=stale,
        created_at=datetime(2026, 8, 15, 9, 0, tzinfo=UTC),
    )


@pytest.fixture
def service(tmp_path):
    registry = SQLiteRegistry(tmp_path / "shipyard.db")
    identity = FakeIdentityProvider()
    identity.bind("alice", "human", {"workspace-owner", "release-owner"})
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


def test_fake_identity_requires_explicit_binding_and_ignores_claimed_kind() -> None:
    provider = FakeIdentityProvider()
    provider.bind("agent-1", "agent", {"builder"})

    resolved = provider.resolve(
        {"subject": "agent-1", "kind": "human", "actor": "human-attacker"}
    )

    assert resolved == Principal(
        subject="agent-1", kind="agent", roles=frozenset({"builder"})
    )
    with pytest.raises(UnauthorizedError):
        provider.resolve({"subject": "agent-1-prefix-attacker"})
    with pytest.raises(UnauthorizedError):
        provider.resolve({"actor": "agent-1"})


@pytest.mark.parametrize(
    ("subject", "kind"),
    [("", "human"), ("alice", "unknown")],
)
def test_principal_rejects_blank_subjects_and_unknown_kinds(subject: str, kind: str) -> None:
    with pytest.raises(ValueError):
        Principal(subject=subject, kind=kind, roles=frozenset())  # type: ignore[arg-type]


def test_human_agent_and_system_operations_have_separate_boundaries(service) -> None:
    with pytest.raises(UnauthorizedError):
        service.create_workspace(workspace_input(), agent_principal())
    with pytest.raises(UnauthorizedError):
        service.create_workspace(workspace_input(), system_principal())

    workspace = service.create_workspace(workspace_input(), human_principal())
    with pytest.raises(UnauthorizedError):
        service.create_decision_case(
            workspace.workspace_id, decision_case_input(), agent_principal()
        )
    with pytest.raises(UnauthorizedError):
        service.submit_agent_proposal(
            workspace.workspace_id, proposal_input(), human_principal()
        )


def test_agent_proposal_is_recorded_but_does_not_change_workspace_revision(service) -> None:
    workspace = service.create_workspace(workspace_input(), human_principal())
    before = workspace.revision

    proposal = service.submit_agent_proposal(
        workspace.workspace_id, proposal_input(), agent_principal()
    )

    assert proposal.status == "proposed"
    assert proposal.producer == "agent-1"
    snapshot = service.get_workspace_snapshot(workspace.workspace_id)
    assert snapshot["workspace"].revision == before
    assert snapshot["proposals"] == [proposal]


def test_agent_cannot_accept_or_create_release_candidate(service) -> None:
    workspace = service.create_workspace(workspace_input(), human_principal())
    service.submit_agent_proposal(
        workspace.workspace_id, proposal_input(), agent_principal()
    )

    with pytest.raises(UnauthorizedError):
        service.decide_proposal("proposal-1", "accept", agent_principal())
    with pytest.raises(UnauthorizedError):
        service.create_release_candidate(
            workspace.workspace_id, [], [], agent_principal()
        )


def test_proposal_decision_is_an_append_only_revision_and_requires_human(service) -> None:
    workspace = service.create_workspace(workspace_input(), human_principal())
    proposal = service.submit_agent_proposal(
        workspace.workspace_id, proposal_input(), agent_principal()
    )

    decided = service.decide_proposal(
        proposal.proposal_id, "return", human_principal()
    )

    assert decided.revision == proposal.revision + 1
    assert decided.status == "returned"
    assert [item.revision for item in service.get_workspace_snapshot(workspace.workspace_id)["proposals"]] == [1, 2]
    assert service.get_workspace_snapshot(workspace.workspace_id)["workspace"].revision == 2


def test_stale_proposal_is_persisted_as_new_revision_and_cannot_be_accepted(service) -> None:
    workspace = service.create_workspace(workspace_input(), human_principal())
    proposal = service.submit_agent_proposal(
        workspace.workspace_id, proposal_input(), agent_principal()
    )
    artifact = Artifact.build(
        artifact_id="artifact-1",
        project_id=workspace.project_id,
        kind="DecisionContract",
        content={"objective": "forecast"},
        owner="alice",
    )
    service.register_artifact(workspace.workspace_id, artifact, human_principal())

    with pytest.raises(StaleRevisionError):
        service.decide_proposal(proposal.proposal_id, "accept", human_principal())

    proposals = service.get_workspace_snapshot(workspace.workspace_id)["proposals"]
    assert proposals[-1].revision == proposal.revision + 1
    assert proposals[-1].status == "stale"
    assert service.get_workspace_snapshot(workspace.workspace_id)["workspace"].revision == 2


def test_gate_review_recording_is_system_only_and_audited(service) -> None:
    workspace = service.create_workspace(workspace_input(), human_principal())
    artifact = Artifact.build(
        artifact_id="artifact-1",
        project_id=workspace.project_id,
        kind="DecisionContract",
        content={"objective": "forecast"},
        owner="alice",
    )
    service.register_artifact(workspace.workspace_id, artifact, human_principal())
    gate = passed_gate(workspace.workspace_id, artifact, "semantic.integrity")

    with pytest.raises(UnauthorizedError):
        service.record_gate_review(gate, human_principal())
    with pytest.raises(UnauthorizedError):
        service.record_gate_review(gate, agent_principal())

    saved = service.record_gate_review(gate, system_principal())
    assert saved == gate
    assert service.get_workspace_snapshot(workspace.workspace_id)["workspace"].revision == 3
    assert [event.event_type for event in service.get_workspace_snapshot(workspace.workspace_id)["audit_events"]] == [
        "workspace.created",
        "artifact.registered",
        "gate_review.recorded",
    ]


def test_release_candidate_requires_current_passed_nonstale_gates(service) -> None:
    workspace = service.create_workspace(workspace_input(), human_principal())
    artifact = Artifact.build(
        artifact_id="artifact-1",
        project_id=workspace.project_id,
        kind="DecisionContract",
        content={"objective": "forecast"},
        owner="alice",
    )
    service.register_artifact(workspace.workspace_id, artifact, human_principal())
    service.record_gate_review(
        passed_gate(workspace.workspace_id, artifact, "semantic.integrity"),
        system_principal(),
    )

    with pytest.raises(ReleaseBlockedError, match="missing required gate"):
        service.create_release_candidate(
            workspace.workspace_id,
            [artifact.artifact_id],
            ["semantic.integrity:run-1"],
            human_principal(),
        )


@pytest.mark.parametrize(
    ("status", "stale"),
    [("failed", False), ("passed", True)],
)
def test_release_candidate_rejects_failed_or_stale_gate_reviews(
    service, status: str, stale: bool
) -> None:
    workspace = service.create_workspace(workspace_input(), human_principal())
    artifact = Artifact.build(
        artifact_id="artifact-1",
        project_id=workspace.project_id,
        kind="DecisionContract",
        content={"objective": "forecast"},
        owner="alice",
    )
    service.register_artifact(workspace.workspace_id, artifact, human_principal())
    reviews = [
        passed_gate(
            workspace.workspace_id,
            artifact,
            gate_id,
            status=status,
            stale=stale,
        )
        for gate_id in REQUIRED_GATES
    ]
    for review in reviews:
        service.record_gate_review(review, system_principal())

    with pytest.raises(ReleaseBlockedError):
        service.create_release_candidate(
            workspace.workspace_id,
            [artifact.artifact_id],
            [review.gate_run_id for review in reviews],
            human_principal(),
        )


def test_release_candidate_rejects_old_or_cross_workspace_references(service) -> None:
    workspace = service.create_workspace(workspace_input(), human_principal())
    artifact_v1 = Artifact.build(
        artifact_id="artifact-1",
        project_id=workspace.project_id,
        kind="DecisionContract",
        version="1.0.0",
        content={"objective": "forecast"},
        owner="alice",
    )
    service.register_artifact(workspace.workspace_id, artifact_v1, human_principal())
    old_reviews = [
        passed_gate(workspace.workspace_id, artifact_v1, gate_id)
        for gate_id in REQUIRED_GATES
    ]
    for review in old_reviews:
        service.record_gate_review(review, system_principal())

    artifact_v2 = artifact_v1.model_copy(
        update={"version": "2.0.0", "content": {"objective": "forecast-v2"}}
    )
    service.register_artifact(workspace.workspace_id, artifact_v2, human_principal())

    with pytest.raises(ReleaseBlockedError, match="current Artifact"):
        service.create_release_candidate(
            workspace.workspace_id,
            [artifact_v1.artifact_id],
            [review.gate_run_id for review in old_reviews],
            human_principal(),
        )

    other = service.create_workspace(
        workspace_input("ws-2", "project-2"), human_principal("bob")
    )
    foreign_artifact = Artifact.build(
        artifact_id="foreign-artifact",
        project_id=other.project_id,
        kind="DecisionContract",
        content={"objective": "foreign"},
        owner="bob",
    )
    service.register_artifact(other.workspace_id, foreign_artifact, human_principal("bob"))
    with pytest.raises(ReleaseBlockedError, match="workspace"):
        service.create_release_candidate(
            workspace.workspace_id,
            [foreign_artifact.artifact_id],
            ["foreign-gate"],
            human_principal(),
        )


def test_release_candidate_is_ready_with_deterministic_manifest(service) -> None:
    workspace = service.create_workspace(workspace_input(), human_principal())
    artifacts = [
        Artifact.build(
            artifact_id=artifact_id,
            project_id=workspace.project_id,
            kind="DecisionContract",
            content={"objective": artifact_id},
            owner="alice",
        )
        for artifact_id in ("artifact-b", "artifact-a")
    ]
    for artifact in artifacts:
        service.register_artifact(workspace.workspace_id, artifact, human_principal())
    reviews = [
        passed_gate(workspace.workspace_id, artifacts[0], gate_id)
        for gate_id in REQUIRED_GATES
    ]
    for review in reviews:
        review = review.model_copy(
            update={
                "artifact_hashes": {
                    artifact.artifact_id: artifact.content_hash for artifact in artifacts
                }
            }
        )
        service.record_gate_review(review, system_principal())

    candidate = service.create_release_candidate(
        workspace.workspace_id,
        [artifact.artifact_id for artifact in reversed(artifacts)],
        [review.gate_run_id for review in reversed(reviews)],
        human_principal(),
    )

    assert candidate.status == "ready"
    assert candidate.artifact_ids == ["artifact-a", "artifact-b"]
    assert candidate.gate_run_ids == sorted(review.gate_run_id for review in reviews)
    assert candidate.manifest["artifact_hashes"] == {
        "artifact-a": next(item for item in artifacts if item.artifact_id == "artifact-a").content_hash,
        "artifact-b": next(item for item in artifacts if item.artifact_id == "artifact-b").content_hash,
    }
    assert candidate.manifest["gate_run_ids"] == candidate.gate_run_ids


def test_state_and_audit_event_roll_back_as_one_transaction(service, monkeypatch) -> None:
    from aifde.shipyard import service as service_module

    def fail_audit(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("audit construction failed")

    monkeypatch.setattr(service_module.AuditEvent, "build", fail_audit)

    with pytest.raises(RuntimeError, match="audit construction failed"):
        service.create_workspace(workspace_input(), human_principal())

    with pytest.raises(RecordNotFoundError):
        service.get_workspace_snapshot("ws-1")
