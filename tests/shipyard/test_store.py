"""Behavioral tests for append-only Shipyard persistence."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import pytest

from aifde.domain.artifacts import Artifact, canonical_json_bytes
from aifde.registry.sqlite import SQLiteRegistry
from aifde.shipyard.contracts import (
    AgentProposal,
    AuditEvent,
    DecisionCase,
    GateReviewSnapshot,
    ProjectWorkspace,
    ReleaseCandidate,
)


UTC = timezone.utc
WORKSPACE_CREATED_AT = datetime(2026, 8, 15, 9, 0, tzinfo=UTC)
WORKSPACE_UPDATED_AT = datetime(2026, 8, 15, 9, 5, tzinfo=UTC)
RECORD_CREATED_AT = datetime(2026, 8, 15, 9, 10, tzinfo=UTC)
ZERO_HASH = "0" * 64


def build_workspace(workspace_id: str) -> ProjectWorkspace:
    return ProjectWorkspace(
        workspace_id=workspace_id,
        project_id=f"project-{workspace_id}",
        name="Delivery Workbench",
        domain_pack="software_delivery",
        owner="alice",
        created_at=WORKSPACE_CREATED_AT,
        updated_at=WORKSPACE_UPDATED_AT,
    )


def build_event(workspace_id: str, event_type: str) -> AuditEvent:
    event_id = f"audit:{workspace_id}:{event_type}"
    payload = {"event": event_type}
    event_payload = {
        "event_id": event_id,
        "workspace_id": workspace_id,
        "event_type": event_type,
        "actor": "system",
        "actor_kind": "system",
        "payload": payload,
        "created_at": RECORD_CREATED_AT.isoformat(),
        "predecessor_hash": ZERO_HASH,
    }
    return AuditEvent(
        event_id=event_id,
        workspace_id=workspace_id,
        event_type=event_type,
        actor="system",
        actor_kind="system",
        payload=payload,
        created_at=RECORD_CREATED_AT,
        predecessor_hash=ZERO_HASH,
        event_hash=sha256(canonical_json_bytes(event_payload)).hexdigest(),
    )


def build_release_candidate(candidate_id: str) -> ReleaseCandidate:
    return ReleaseCandidate(
        candidate_id=candidate_id,
        workspace_id="ws-1",
        manifest={"content_hash": "a" * 64},
        created_by="alice",
        created_at=RECORD_CREATED_AT,
    )


def build_decision_case(case_id: str = "case-1") -> DecisionCase:
    return DecisionCase(
        case_id=case_id,
        workspace_id="ws-1",
        name="Prioritize delivery work",
        objective="Choose the next work item",
        decision_owner="alice",
        users=["delivery-lead"],
        trigger="A work item is ready",
        inputs=["backlog"],
        actions=["prioritize"],
        baseline="manual review",
        success_definition="The highest-value item is selected",
        failure_definition="A blocked item is selected",
    )


def build_proposal(proposal_id: str = "proposal-1", revision: int = 1) -> AgentProposal:
    return AgentProposal(
        proposal_id=proposal_id,
        revision=revision,
        workspace_id="ws-1",
        task_packet_id="task-1",
        producer="agent-1",
        proposed_changes={"status": "active", "revision": revision},
        created_at=RECORD_CREATED_AT,
    )


def build_gate_review(gate_run_id: str = "gate-1") -> GateReviewSnapshot:
    return GateReviewSnapshot(
        gate_run_id=gate_run_id,
        workspace_id="ws-1",
        gate_id="semantic.integrity",
        severity="hard",
        status="passed",
        artifact_hashes={"artifact-1": "b" * 64},
        validator_version="validator-1",
        created_at=RECORD_CREATED_AT,
    )


def test_workspace_and_audit_event_survive_registry_restart(tmp_path: Path) -> None:
    first = SQLiteRegistry(tmp_path / "shipyard.db")
    workspace = build_workspace("ws-1")
    event = build_event(workspace.workspace_id, "workspace.created")
    first.shipyard.put_workspace(workspace)
    first.shipyard.append_audit_event(event)
    first.close()

    second = SQLiteRegistry(tmp_path / "shipyard.db")
    try:
        assert second.shipyard.get_workspace("ws-1") == workspace
        assert second.shipyard.list_audit_events("ws-1")[0] == event
    finally:
        second.close()


def test_release_candidate_rejects_duplicate_identity_and_never_overwrites(
    tmp_path: Path,
) -> None:
    registry = SQLiteRegistry(tmp_path / "shipyard.db")
    try:
        candidate = build_release_candidate("candidate-1")
        registry.shipyard.put_release_candidate(candidate)
        with pytest.raises(ValueError, match="already exists"):
            registry.shipyard.put_release_candidate(candidate)
        assert registry.shipyard.get_release_candidate(candidate.candidate_id) == candidate
    finally:
        registry.close()

def test_revisioned_records_return_latest_without_overwriting_history(tmp_path: Path) -> None:
    registry = SQLiteRegistry(tmp_path / "shipyard.db")
    try:
        workspace_v1 = build_workspace("ws-1")
        workspace_v2 = workspace_v1.model_copy(
            update={"revision": 2, "name": "Updated Workbench", "updated_at": WORKSPACE_UPDATED_AT}
        )
        proposal_v1 = build_proposal()
        proposal_v2 = build_proposal(revision=2)

        registry.shipyard.put_workspace(workspace_v1)
        registry.shipyard.put_workspace(workspace_v2)
        registry.shipyard.put_proposal(proposal_v1)
        registry.shipyard.put_proposal(proposal_v2)

        assert registry.shipyard.get_workspace("ws-1") == workspace_v2
        assert registry.shipyard.list_workspaces("ws-1") == [workspace_v1, workspace_v2]
        assert registry.shipyard.get_proposal("proposal-1") == proposal_v2
        assert registry.shipyard.list_proposals("ws-1") == [proposal_v1, proposal_v2]

        with pytest.raises(ValueError, match="already exists"):
            registry.shipyard.put_workspace(workspace_v1)
        with pytest.raises(ValueError, match="already exists"):
            registry.shipyard.put_proposal(proposal_v1)
    finally:
        registry.close()


def test_all_shipyard_contracts_round_trip_with_hashes_and_timestamps(tmp_path: Path) -> None:
    registry = SQLiteRegistry(tmp_path / "shipyard.db")
    workspace = build_workspace("ws-1")
    decision_case = build_decision_case()
    proposal = build_proposal()
    gate_review = build_gate_review()
    release_candidate = build_release_candidate("candidate-1")
    event = build_event("ws-1", "workspace.created")
    try:
        registry.shipyard.put_workspace(workspace)
        registry.shipyard.put_decision_case(decision_case)
        registry.shipyard.put_proposal(proposal)
        registry.shipyard.put_gate_review(gate_review)
        registry.shipyard.put_release_candidate(release_candidate)
        registry.shipyard.append_audit_event(event)
        registry.close()

        reopened = SQLiteRegistry(tmp_path / "shipyard.db")
        try:
            assert reopened.shipyard.get_workspace("ws-1") == workspace
            assert reopened.shipyard.get_decision_case("case-1") == decision_case
            assert reopened.shipyard.get_proposal("proposal-1") == proposal
            assert reopened.shipyard.list_gate_reviews("ws-1") == [gate_review]
            assert reopened.shipyard.get_release_candidate("candidate-1") == release_candidate
            assert reopened.shipyard.list_audit_events("ws-1") == [event]

            proposal_row = reopened.connection.execute(
                "SELECT content_hash, created_at, payload_json FROM shipyard_proposals "
                "WHERE proposal_id = ? AND revision = ?",
                (proposal.proposal_id, proposal.revision),
            ).fetchone()
            assert proposal_row["content_hash"] == proposal.content_hash
            assert proposal_row["created_at"] == RECORD_CREATED_AT.isoformat()
            assert proposal_row["payload_json"] == canonical_json_bytes(
                proposal.model_dump(mode="json")
            ).decode("utf-8")

            event_row = reopened.connection.execute(
                "SELECT event_hash, created_at FROM shipyard_audit_events WHERE event_id = ?",
                (event.event_id,),
            ).fetchone()
            assert event_row["event_hash"] == event.event_hash
            assert event_row["created_at"] == RECORD_CREATED_AT.isoformat()
        finally:
            reopened.close()
    finally:
        registry.close()


def test_transaction_rolls_back_workspace_and_audit_event_together(tmp_path: Path) -> None:
    registry = SQLiteRegistry(tmp_path / "shipyard.db")
    workspace = build_workspace("ws-1")
    event = build_event("ws-1", "workspace.created")
    try:
        transaction = registry.transaction()
        transaction.shipyard.put_workspace(workspace)
        transaction.shipyard.append_audit_event(event)

        with pytest.raises(ValueError, match="already exists"):
            transaction.shipyard.append_audit_event(event)
        with pytest.raises(RuntimeError, match="aborted"):
            transaction.commit()
        with pytest.raises(KeyError):
            registry.shipyard.get_workspace(workspace.workspace_id)
        assert registry.shipyard.list_audit_events(workspace.workspace_id) == []
    finally:
        registry.close()


def test_artifact_task1_fields_survive_registry_restart(tmp_path: Path) -> None:
    created_at = datetime(2026, 8, 15, 8, 30, tzinfo=UTC)
    artifact = Artifact.build(
        artifact_id="artifact-1",
        project_id="project-1",
        kind="DecisionContract",
        owner="alice",
        content={"decision": "prioritize"},
        parent_artifact_ids=["artifact-parent"],
        producer="builder-1",
        created_at=created_at,
        validation_results=[{"validator": "schema", "passed": True}],
    )
    registry = SQLiteRegistry(tmp_path / "shipyard.db")
    try:
        registry.artifacts.put(artifact)
        registry.close()

        reopened = SQLiteRegistry(tmp_path / "shipyard.db")
        try:
            restored = reopened.artifacts.get("project-1", "artifact-1")
            assert restored.created_at == created_at
            assert restored.parent_artifact_ids == ["artifact-parent"]
            assert restored.producer == "builder-1"
            assert restored.validation_results == [{"validator": "schema", "passed": True}]
            assert restored.content_hash == artifact.content_hash
        finally:
            reopened.close()
    finally:
        registry.close()
