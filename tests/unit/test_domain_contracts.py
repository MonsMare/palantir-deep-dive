from datetime import datetime, timezone
from math import inf, nan

import pytest
from pydantic import ValidationError

from aifde.domain.actions import ActionRequest
from aifde.domain.artifacts import Artifact, content_hash_for
from aifde.domain.evidence import Claim
from aifde.domain.stages import StageState


def test_artifact_requires_identity_and_kind():
    with pytest.raises(ValidationError):
        Artifact(project_id="p1", kind="OntologyModel")


def test_artifact_hash_is_stable_for_same_content():
    first = Artifact.build(
        project_id="p1",
        kind="DecisionContract",
        content={"decision": "accept_change", "metadata": {"z": 1, "a": 2}},
        owner="owner-1",
    )
    second = Artifact.build(
        project_id="p1",
        kind="DecisionContract",
        content={"metadata": {"a": 2, "z": 1}, "decision": "accept_change"},
        owner="owner-1",
    )
    assert first.content_hash == second.content_hash


def test_artifact_uses_strict_three_part_semantic_versions():
    artifact = Artifact.build(
        project_id="p1",
        kind="DecisionContract",
        content={"decision": "accept_change"},
        owner="owner-1",
    )

    assert artifact.version == "1.0.0"
    assert Artifact.build(
        project_id="p1",
        kind="DecisionContract",
        content={"decision": "accept_change"},
        owner="owner-1",
        version="2.10.3",
    ).version == "2.10.3"
    assert Artifact.build(
        project_id="p1",
        kind="DecisionContract",
        content={"decision": "accept_change"},
        owner="owner-1",
        version=2,
    ).version == "2.0.0"

    for invalid_version in ("2", "2.1", "02.1.0", "1.0.0-dev", "1.0.0.1"):
        with pytest.raises(ValidationError):
            Artifact.build(
                project_id="p1",
                kind="DecisionContract",
                content={"decision": "accept_change"},
                owner="owner-1",
                version=invalid_version,
            )


def test_artifact_rejects_forged_content_hash():
    with pytest.raises(ValidationError):
        Artifact(
            artifact_id="a1",
            project_id="p1",
            kind="DecisionContract",
            owner="owner-1",
            content={"decision": "accept_change"},
            content_hash="forged",
        )


def test_artifact_copy_cannot_inject_content_hash():
    artifact = Artifact.build(
        project_id="p1",
        kind="DecisionContract",
        content={"decision": "accept_change"},
        owner="owner-1",
    )

    with pytest.raises(ValueError):
        artifact.model_copy(update={"content_hash": "forged"})


def test_artifact_new_metadata_is_backward_compatible_and_hash_is_stable():
    artifact = Artifact.build(
        project_id="p1", kind="DecisionContract", content={"objective": "forecast"}, owner="alice"
    )

    assert artifact.parent_artifact_ids == []
    assert artifact.content_hash == content_hash_for(artifact.content)
    assert artifact.validation_results == []
    assert artifact.created_at is not None
    assert artifact.created_at.tzinfo is not None
    assert artifact.created_at.utcoffset() == timezone.utc.utcoffset(artifact.created_at)

    timestamped = Artifact.build(
        project_id="p1",
        kind="DecisionContract",
        content={"objective": "forecast"},
        owner="alice",
        created_at=datetime(2026, 8, 15, 8, 0, tzinfo=timezone.utc),
    )
    assert timestamped.created_at is not None
    assert timestamped.created_at.tzinfo is not None

    copied = artifact.model_copy(
        update={
            "parent_artifact_ids": ["parent-1"],
            "producer": "agent-1",
            "validation_results": [{"status": "passed"}],
        },
        deep=True,
    )
    assert copied.parent_artifact_ids == ["parent-1"]
    assert copied.producer == "agent-1"
    assert copied.validation_results == [{"status": "passed"}]
    assert copied.content_hash == content_hash_for(copied.content)


def test_legacy_artifact_without_created_at_gets_a_utc_compatibility_timestamp():
    artifact = Artifact.build(
        artifact_id="artifact-1",
        project_id="p1",
        kind="DecisionContract",
        content={"objective": "forecast"},
        owner="alice",
    )
    legacy_payload = artifact.model_dump(exclude={"created_at"})

    restored_legacy = Artifact.model_validate(legacy_payload)

    assert restored_legacy.created_at is not None
    assert restored_legacy.created_at.tzinfo is not None
    assert artifact == restored_legacy


def test_artifact_hash_changes_when_content_changes_and_survives_round_trip():
    artifact = Artifact.build(
        project_id="p1",
        kind="DecisionContract",
        content={"decision": "accept_change"},
        owner="owner-1",
    )
    original_hash = artifact.content_hash

    artifact.content["decision"] = "reject_change"

    assert artifact.content_hash != original_hash
    restored = Artifact.model_validate_json(artifact.model_dump_json())
    assert restored.content == artifact.content
    assert restored.content_hash == artifact.content_hash


@pytest.mark.parametrize("value", [nan, inf, -inf])
def test_artifact_rejects_non_finite_json_numbers(value):
    with pytest.raises(ValidationError):
        Artifact.build(
            project_id="p1",
            kind="DecisionContract",
            content={"value": value},
            owner="owner-1",
        )


@pytest.mark.parametrize("value", [nan, inf, -inf])
def test_artifact_copy_rejects_non_finite_json_numbers(value):
    artifact = Artifact.build(
        project_id="p1",
        kind="DecisionContract",
        content={"value": 1},
        owner="owner-1",
    )

    with pytest.raises(ValidationError):
        artifact.model_copy(update={"content": {"value": value}})


def test_claim_rejects_unknown_claim_type():
    with pytest.raises(ValidationError):
        Claim(
            claim_id="c1",
            artifact_id="a1",
            claim_type="guess",
            text="unsupported",
        )


def test_critical_claim_requires_evidence():
    with pytest.raises(ValidationError):
        Claim(
            claim_id="c1",
            artifact_id="a1",
            claim_type="fact",
            criticality="critical",
            text="unsupported without evidence",
        )


def test_critical_claim_marks_required_evidence_and_preserves_claim_type():
    claim = Claim(
        claim_id="c1",
        artifact_id="a1",
        claim_type="inference",
        criticality="critical",
        evidence_refs=["e1"],
        text="supported inference",
    )

    assert claim.claim_type == "inference"
    assert claim.required_evidence is True


def test_critical_claim_rejects_blank_evidence_reference():
    with pytest.raises(ValidationError):
        Claim(
            claim_id="c1",
            artifact_id="a1",
            claim_type="fact",
            criticality="critical",
            evidence_refs=["  "],
            text="blank evidence reference",
        )


def test_critical_claim_copy_cannot_remove_required_evidence():
    claim = Claim(
        claim_id="c1",
        artifact_id="a1",
        claim_type="fact",
        criticality="critical",
        evidence_refs=["e1"],
        text="supported fact",
    )

    with pytest.raises(ValidationError):
        claim.model_copy(update={"evidence_refs": []})


def valid_action_request_kwargs():
    return {
        "action_id": "action-1",
        "action_type": "update_decision",
        "target_id": "artifact-1",
        "parameters": {"decision": "accept"},
        "requested_by": "builder-1",
        "idempotency_key": "idem-1",
        "execution_mode": "mock",
        "policy_id": "policy-1",
        "policy_version": "v1",
        "validation_id": "validation-1",
        "validated_by": "validator-1",
        "validation_status": "pending",
        "approval_id": "approval-1",
        "approval_actor": "reviewer-1",
        "approval_role": "domain_reviewer",
        "approval_status": "pending",
        "audit_ref": "audit-1",
        "audit_actor": "audit-service",
        "outcome_status": "pending",
    }


def test_action_request_is_a_typed_mock_boundary():
    request = ActionRequest(**valid_action_request_kwargs())

    assert request.execution_mode == "mock"
    assert request.validation_status == "pending"
    assert request.outcome_status == "pending"


def test_action_request_rejects_non_mock_execution_mode():
    values = valid_action_request_kwargs()
    values["execution_mode"] = "real"

    with pytest.raises(ValidationError):
        ActionRequest(**values)


@pytest.mark.parametrize("field", ["action_type", "idempotency_key"])
def test_action_request_rejects_empty_action_identity_fields(field):
    values = valid_action_request_kwargs()
    values[field] = "  "

    with pytest.raises(ValidationError):
        ActionRequest(**values)


@pytest.mark.parametrize(
    "field",
    [
        "requested_by",
        "policy_id",
        "validation_id",
        "validated_by",
        "approval_id",
        "approval_actor",
        "approval_role",
        "audit_ref",
        "audit_actor",
    ],
)
def test_action_request_requires_approval_validation_and_audit_identities(field):
    values = valid_action_request_kwargs()
    values.pop(field)

    with pytest.raises(ValidationError):
        ActionRequest(**values)


def test_action_request_rejects_builder_self_approval():
    values = valid_action_request_kwargs()
    values["approval_actor"] = values["requested_by"]

    with pytest.raises(ValidationError):
        ActionRequest(**values)


@pytest.mark.parametrize(
    "update",
    [
        {"execution_mode": "real"},
        {"approval_actor": "builder-1"},
    ],
)
def test_action_request_copy_revalidates_governance_constraints(update):
    request = ActionRequest(**valid_action_request_kwargs())

    with pytest.raises(ValidationError):
        request.model_copy(update=update)


def test_stage_state_has_blocked_state():
    assert StageState.BLOCKED.value == "blocked"
