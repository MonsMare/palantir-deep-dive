from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from aifde.shipyard.contracts import (
    AgentProposal,
    AuditEvent,
    DecisionCase,
    GateReviewSnapshot,
    ProjectWorkspace,
    ReleaseCandidate,
)


UTC_TIMESTAMP = datetime(2026, 8, 15, 8, 0, tzinfo=timezone.utc)


def workspace_values() -> dict[str, object]:
    return {
        "workspace_id": "ws-1",
        "project_id": "p1",
        "name": "delivery forecast",
        "domain_pack": "software_delivery",
        "owner": "alice",
        "status": "active",
        "current_phase": "intake",
        "revision": 1,
        "decision_case_ids": [],
        "artifact_ids": [],
        "proposal_ids": [],
        "gate_review_ids": [],
        "release_candidate_ids": [],
        "created_at": UTC_TIMESTAMP,
        "updated_at": UTC_TIMESTAMP,
    }


def proposal_values() -> dict[str, object]:
    return {
        "proposal_id": "proposal-1",
        "revision": 1,
        "workspace_id": "ws-1",
        "task_packet_id": "packet-1",
        "producer": "agent-1",
        "producer_kind": "agent",
        "proposed_changes": {"kind": "DecisionContract"},
        "affected_artifact_ids": ["artifact-1"],
        "evidence_refs": ["evidence-1"],
        "validation_results": [{"status": "passed"}],
        "confidence": 0.8,
        "risks": ["forecast drift"],
        "open_questions": ["which horizon"],
        "next_step": "request human review",
        "base_revision": 1,
        "status": "proposed",
        "created_at": UTC_TIMESTAMP,
    }


def test_decision_case_requires_a_decision_owner_and_action() -> None:
    with pytest.raises(ValidationError):
        DecisionCase(
            case_id="case-1",
            workspace_id="ws-1",
            name="delivery forecast",
            objective="forecast duration",
            decision_owner="",
            users=["pm"],
            trigger="change request arrives",
            inputs=["requirement"],
            actions=[],
            constraints=[],
            kpis=["on_time_rate"],
            baseline="manual review",
            success_definition="fewer surprises",
            failure_definition="silent delay",
        )


def test_agent_proposal_cannot_claim_human_authority() -> None:
    with pytest.raises(ValidationError):
        AgentProposal.model_validate(
            {
                "proposal_id": "proposal-1",
                "workspace_id": "ws-1",
                "task_packet_id": "packet-1",
                "producer": "agent-1",
                "producer_kind": "human",
                "proposed_changes": {"kind": "DecisionContract"},
                "base_revision": 1,
            }
        )


def test_workbench_records_use_typed_statuses_and_revision_defaults() -> None:
    workspace = ProjectWorkspace(
        workspace_id="ws-1",
        project_id="p1",
        name="delivery forecast",
        domain_pack="software_delivery",
        owner="alice",
        current_phase="intake",
    )
    proposal = AgentProposal(
        proposal_id="proposal-1",
        workspace_id="ws-1",
        task_packet_id="packet-1",
        producer="agent-1",
        proposed_changes={"kind": "DecisionContract"},
        base_revision=1,
    )

    assert workspace.revision == 1
    assert workspace.status == "active"
    assert proposal.revision == 1
    assert proposal.producer_kind == "agent"
    assert proposal.status == "proposed"

    with pytest.raises(ValidationError):
        ProjectWorkspace.model_validate(workspace_values() | {"status": "unknown"})
    with pytest.raises(ValidationError):
        AgentProposal.model_validate(proposal_values() | {"revision": 0})


def test_records_reject_blank_identities_and_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ProjectWorkspace.model_validate(workspace_values() | {"owner": "  "})
    with pytest.raises(ValidationError):
        ProjectWorkspace.model_validate(workspace_values() | {"unexpected": True})
    with pytest.raises(ValidationError):
        AgentProposal.model_validate(proposal_values() | {"unexpected": True})


def test_record_timestamps_are_aware_and_normalized_to_utc() -> None:
    local_timestamp = datetime(
        2026, 8, 15, 16, 0, tzinfo=timezone(timedelta(hours=8))
    )
    workspace = ProjectWorkspace(
        workspace_id="ws-1",
        project_id="p1",
        name="delivery forecast",
        domain_pack="software_delivery",
        owner="alice",
        current_phase="intake",
        created_at=local_timestamp,
        updated_at=local_timestamp,
    )

    assert workspace.created_at == UTC_TIMESTAMP
    assert workspace.updated_at == UTC_TIMESTAMP

    with pytest.raises(ValidationError):
        AgentProposal.model_validate(
            proposal_values() | {"created_at": datetime(2026, 8, 15, 8, 0)}
        )


def test_gate_review_and_release_candidate_require_traceable_references() -> None:
    gate = GateReviewSnapshot(
        gate_run_id="gate-run-1",
        revision=2,
        workspace_id="ws-1",
        gate_id="semantic.integrity",
        severity="hard",
        status="passed",
        artifact_hashes={"artifact-1": "a" * 64},
        validator_version="validator-1",
        violations=[],
        warnings=[],
        evidence_refs=["evidence-1"],
        stale=False,
        created_at=UTC_TIMESTAMP,
    )
    candidate = ReleaseCandidate(
        candidate_id="candidate-1",
        revision=2,
        workspace_id="ws-1",
        artifact_ids=["artifact-1"],
        gate_run_ids=[gate.gate_run_id],
        manifest={"artifact_hashes": gate.artifact_hashes},
        status="ready",
        created_at=UTC_TIMESTAMP,
        created_by="alice",
    )

    assert gate.status == "passed"
    assert gate.revision == 2
    assert len(gate.content_hash) == 64
    assert candidate.status == "ready"
    assert candidate.revision == 2
    assert len(candidate.content_hash) == 64

    with pytest.raises(ValidationError):
        ReleaseCandidate.model_validate(candidate.model_dump() | {"content_hash": "f" * 64})

    with pytest.raises(ValidationError):
        ReleaseCandidate.model_validate(
            {
                "candidate_id": "candidate-1",
                "revision": 1,
                "workspace_id": "ws-1",
                "artifact_ids": ["artifact-1"],
                "gate_run_ids": [gate.gate_run_id],
                "manifest": {},
                "created_by": "alice",
            }
        )

    with pytest.raises(ValidationError):
        ReleaseCandidate.model_validate(
            {
                "candidate_id": "candidate-1",
                "revision": 1,
                "workspace_id": "ws-1",
                "artifact_ids": ["artifact-1"],
                "gate_run_ids": [gate.gate_run_id],
                "manifest": {"artifact_hashes": {"artifact-1": "forged"}},
                "created_by": "alice",
            }
        )

    with pytest.raises(ValidationError):
        GateReviewSnapshot.model_validate(
            {
                "gate_run_id": "gate-run-1",
                "revision": 1,
                "workspace_id": "ws-1",
                "gate_id": "semantic.integrity",
                "severity": "hard",
                "status": "passed",
                "artifact_hashes": {"artifact-1": "not-a-sha256"},
                "validator_version": "validator-1",
            }
        )


def test_release_candidate_rejects_ambiguous_manifest_hash_fields() -> None:
    with pytest.raises(ValidationError, match="exactly one reserved hash field"):
        ReleaseCandidate(
            candidate_id="candidate-1",
            workspace_id="ws-1",
            artifact_ids=["artifact-1"],
            gate_run_ids=["gate-run-1"],
            manifest={
                "artifact_hashes": {"artifact-1": "a" * 64},
                "content_hash": "not-a-sha256",
            },
            created_by="alice",
        )


def test_audit_event_builds_and_rejects_tampered_hashes() -> None:
    event = AuditEvent.build(
        workspace_id="ws-1",
        event_type="workspace.created",
        actor="alice",
        actor_kind="human",
        payload={"revision": 1, "name": "delivery forecast"},
        predecessor_hash="0" * 64,
    )

    assert len(event.event_hash) == 64
    assert event.created_at.tzinfo is not None

    with pytest.raises(ValidationError):
        AuditEvent.model_validate(
            event.model_dump(mode="python") | {"event_hash": "f" * 64}
        )
    with pytest.raises(ValidationError):
        AuditEvent.model_validate(
            event.model_dump(mode="python")
            | {"payload": {"revision": 2, "name": "tampered"}}
        )

    with pytest.raises(ValidationError):
        AuditEvent.model_validate(
            event.model_dump(mode="python") | {"event_id": "audit:other"}
        )
    with pytest.raises(ValidationError):
        AuditEvent.model_validate(
            event.model_dump(mode="python")
            | {"created_at": UTC_TIMESTAMP.replace(hour=9)}
        )


def test_audit_event_accepts_only_known_actor_kinds() -> None:
    with pytest.raises(ValidationError):
        AuditEvent.build(
            workspace_id="ws-1",
            event_type="workspace.created",
            actor="alice",
            actor_kind="human-admin",
            payload={},
            predecessor_hash="0" * 64,
        )
