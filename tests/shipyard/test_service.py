from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

import pytest

from aifde.domain.artifacts import Artifact, canonical_json_bytes
from aifde.gates.engine import GateEngine
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
from aifde.shipyard.provenance import build_artifact_input_snapshot


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
    input_snapshot = build_artifact_input_snapshot([artifact])
    definition = GateEngine().get_definition(gate_id)
    return GateReviewSnapshot(
        gate_run_id=gate_run_id or f"{gate_id}:run-1",
        workspace_id=workspace_id,
        gate_id=gate_id,
        severity="hard",
        status=status,
        artifact_hashes=input_snapshot.artifact_hashes,
        artifact_versions=input_snapshot.artifact_versions,
        source_snapshot_id=input_snapshot.source_snapshot_id,
        source_snapshot_hash=input_snapshot.source_snapshot_hash,
        input_snapshot_hash=input_snapshot.input_snapshot_hash,
        validator_version=definition.validator_version,
        definition_fingerprint=definition.definition_fingerprint,
        evidence_refs=input_snapshot.evidence_refs,
        stale=stale,
        created_at=datetime(2026, 8, 15, 9, 0, tzinfo=UTC),
    )


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


def test_service_requires_an_explicit_identity_provider(tmp_path) -> None:
    registry = SQLiteRegistry(tmp_path / "shipyard.db")
    try:
        with pytest.raises(ValueError, match="identity_provider"):
            ShipyardApplicationService(
                registry,
                required_gate_ids=REQUIRED_GATES,
            )
    finally:
        registry.close()


def test_service_rejects_unbound_or_mismatched_principals(service) -> None:
    with pytest.raises(UnauthorizedError, match="identity"):
        service.create_workspace(
            workspace_input("unbound"),
            Principal(
                subject="unbound",
                kind="human",
                roles=frozenset({"workspace-owner"}),
            ),
        )

    with pytest.raises(UnauthorizedError, match="identity"):
        service.create_workspace(
            workspace_input("mismatched"),
            Principal(
                subject="alice",
                kind="human",
                roles=frozenset({"forged-role"}),
            ),
        )


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
    service.identity_provider.bind("agent-without-builder", "agent")
    with pytest.raises(UnauthorizedError, match="builder"):
        service.submit_agent_proposal(
            workspace.workspace_id,
            proposal_input("proposal-without-builder"),
            Principal(
                subject="agent-without-builder",
                kind="agent",
                roles=frozenset(),
            ),
        )


def test_agent_proposal_is_recorded_but_does_not_change_workspace_revision(service) -> None:
    workspace = service.create_workspace(workspace_input(), human_principal())
    before = workspace.revision

    proposal = service.submit_agent_proposal(
        workspace.workspace_id, proposal_input(), agent_principal()
    )

    assert proposal.status == "proposed"
    assert proposal.producer == "agent-1"
    snapshot = service.get_workspace_snapshot(workspace.workspace_id, human_principal())
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
    assert [item.revision for item in service.get_workspace_snapshot(workspace.workspace_id, human_principal())["proposals"]] == [1, 2]
    assert service.get_workspace_snapshot(workspace.workspace_id, human_principal())["workspace"].revision == 2


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

    proposals = service.get_workspace_snapshot(workspace.workspace_id, human_principal())["proposals"]
    assert proposals[-1].revision == proposal.revision + 1
    assert proposals[-1].status == "stale"
    assert service.get_workspace_snapshot(workspace.workspace_id, human_principal())["workspace"].revision == 2


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
    assert service.get_workspace_snapshot(workspace.workspace_id, human_principal())["workspace"].revision == 3
    assert [event.event_type for event in service.get_workspace_snapshot(workspace.workspace_id, human_principal())["audit_events"]] == [
        "workspace.created",
        "artifact.registered",
        "gate_review.recorded",
    ]


def test_gate_review_recording_requires_gate_runner_role(service) -> None:
    workspace = service.create_workspace(workspace_input(), human_principal())
    artifact = Artifact.build(
        artifact_id="artifact-1",
        project_id=workspace.project_id,
        kind="DecisionContract",
        content={"objective": "forecast"},
        owner="alice",
    )
    service.register_artifact(workspace.workspace_id, artifact, human_principal())
    service.identity_provider.bind("system-worker", "system", {"worker"})

    with pytest.raises(UnauthorizedError, match="gate-runner"):
        service.record_gate_review(
            passed_gate(workspace.workspace_id, artifact, "semantic.integrity"),
            Principal(subject="system-worker", kind="system", roles=frozenset({"worker"})),
        )


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
        if review.status == "passed" and review.stale:
            with pytest.raises(ReleaseBlockedError, match="stale"):
                service.record_gate_review(review, system_principal())
        else:
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
                },
                "artifact_versions": {
                    artifact.artifact_id: artifact.version for artifact in artifacts
                },
            }
        )
        input_snapshot = build_artifact_input_snapshot(artifacts)
        review = review.model_copy(
            update={
                "source_snapshot_id": input_snapshot.source_snapshot_id,
                "source_snapshot_hash": input_snapshot.source_snapshot_hash,
                "input_snapshot_hash": input_snapshot.input_snapshot_hash,
                "evidence_refs": input_snapshot.evidence_refs,
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

    repeated = service.create_release_candidate(
        workspace.workspace_id,
        [artifact.artifact_id for artifact in artifacts],
        [review.gate_run_id for review in reviews],
        human_principal(),
    )
    digest_payload = {
        "artifact_hashes": candidate.manifest["artifact_hashes"],
        "gate_run_ids": candidate.gate_run_ids,
    }
    expected_digest = sha256(canonical_json_bytes(digest_payload)).hexdigest()
    assert candidate.candidate_id != repeated.candidate_id
    assert candidate.content_hash != repeated.content_hash
    assert candidate.manifest["manifest_digest"] == expected_digest
    assert repeated.manifest["manifest_digest"] == expected_digest


def test_workspace_owner_policy_blocks_cross_workspace_human_access(service) -> None:
    workspace = service.create_workspace(
        workspace_input("ws-owner-policy"), human_principal("alice")
    )
    bob = human_principal("bob")

    assert service.list_workspaces(bob) == []
    with pytest.raises(UnauthorizedError, match="workspace"):
        service.get_workspace(workspace.workspace_id, bob)
    with pytest.raises(UnauthorizedError, match="workspace"):
        service.list_decision_cases(workspace.workspace_id, bob)
    with pytest.raises(UnauthorizedError, match="workspace"):
        service.get_workspace_snapshot(workspace.workspace_id, bob)

    with pytest.raises(UnauthorizedError, match="workspace"):
        service.create_decision_case(
            workspace.workspace_id,
            decision_case_input("case-owner-policy"),
            bob,
        )

    artifact = Artifact.build(
        artifact_id="artifact-owner-policy",
        project_id=workspace.project_id,
        kind="DecisionContract",
        content={"objective": "forecast"},
        owner="alice",
    )
    with pytest.raises(UnauthorizedError, match="workspace"):
        service.register_artifact(workspace.workspace_id, artifact, bob)

    proposal = service.submit_agent_proposal(
        workspace.workspace_id,
        proposal_input("proposal-owner-policy"),
        agent_principal(),
    )
    with pytest.raises(UnauthorizedError, match="workspace"):
        service.decide_proposal(proposal.proposal_id, "return", bob)

    saved = service.register_artifact(
        workspace.workspace_id, artifact, human_principal("alice")
    )
    for gate_id in REQUIRED_GATES:
        service.record_gate_review(
            passed_gate(workspace.workspace_id, saved, gate_id),
            system_principal(),
        )
    with pytest.raises(UnauthorizedError, match="workspace"):
        service.create_release_candidate(
            workspace.workspace_id,
            [saved.artifact_id],
            [f"{gate_id}:run-1" for gate_id in REQUIRED_GATES],
            bob,
        )

    owner_snapshot = service.get_workspace_snapshot(
        workspace.workspace_id, human_principal("alice")
    )
    assert owner_snapshot["workspace"].owner == "alice"

    service.identity_provider.bind("read-only-owner", "human", {"release-owner"})
    read_only_owner = Principal(
        subject="read-only-owner",
        kind="human",
        roles=frozenset({"release-owner"}),
    )
    read_only_workspace = service.create_workspace(
        workspace_input("ws-read-only-owner"), read_only_owner
    )
    assert service.get_workspace(read_only_workspace.workspace_id, read_only_owner)
    with pytest.raises(UnauthorizedError, match="workspace-owner"):
        service.create_decision_case(
            read_only_workspace.workspace_id,
            decision_case_input("case-read-only-owner"),
            read_only_owner,
        )


def test_state_and_audit_event_roll_back_as_one_transaction(service, monkeypatch) -> None:
    from aifde.shipyard import service as service_module

    def fail_audit(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("audit construction failed")

    monkeypatch.setattr(service_module.AuditEvent, "build", fail_audit)

    with pytest.raises(RuntimeError, match="audit construction failed"):
        service.create_workspace(workspace_input(), human_principal())

    with pytest.raises(RecordNotFoundError):
        service.get_workspace_snapshot("ws-1", human_principal())
