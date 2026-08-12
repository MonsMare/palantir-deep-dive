"""Contract tests for the mock-only Action Broker."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from aifde.domain.actions import ActionRequest
from aifde.policy.capabilities import ActorRole, ApprovedActionRecord
from aifde.tools.actions import ActionBroker, ActionPolicy, MockActionAdapter


def make_request(
    *,
    action_id: str = "action-001",
    idempotency_key: str = "replan-sprint-001",
    parameters: dict[str, Any] | None = None,
) -> ActionRequest:
    """Build an execution-stage request whose facts match ``make_record``."""

    return ActionRequest(
        action_id=action_id,
        action_type="ReplanSprint",
        target_id="sprint-2026-08",
        parameters={"capacity": 8} if parameters is None else parameters,
        requested_by="builder-1",
        idempotency_key=idempotency_key,
        execution_mode="mock",
        policy_id="mock-actions",
        policy_version="1",
        validation_id=f"validation-{action_id}",
        validated_by="deterministic-verifier-1",
        validation_status="passed",
        approval_id=f"approval-{action_id}",
        approval_actor="domain-owner-1",
        approval_role="domain-owner",
        approval_status="approved",
        audit_ref=f"audit-{action_id}",
        audit_actor="audit-service",
        outcome_status="pending",
    )


def make_record(action_id: str = "action-001") -> ApprovedActionRecord:
    """Build the protected Task-4 record for one request."""

    return ApprovedActionRecord(
        action_id=action_id,
        action_type="ReplanSprint",
        execution_mode="mock",
        requested_by="builder-1",
        validation_status="passed",
        approval_id=f"approval-{action_id}",
        approval_actor="domain-owner-1",
        approval_role=ActorRole.DOMAIN_OWNER,
        approval_status="approved",
    )


@pytest.fixture
def approved_request() -> ActionRequest:
    return make_request()


@pytest.fixture
def action_broker(approved_request: ActionRequest) -> ActionBroker:
    return ActionBroker(approved_actions=[make_record(approved_request.action_id)])


def test_action_requires_a_protected_approval_record(approved_request: ActionRequest) -> None:
    broker = ActionBroker()

    with pytest.raises(PermissionError, match="approval"):
        broker.execute(approved_request, actor="release-owner-1")

    assert broker.audit_records[-1].event == "deny"


def test_action_rejects_caller_forged_approval_or_execution_actor(
    action_broker: ActionBroker, approved_request: ActionRequest
) -> None:
    forged_approval = approved_request.model_copy(
        update={"approval_actor": "challenger-1"}
    )

    with pytest.raises(PermissionError, match="approval"):
        action_broker.execute(forged_approval, actor="release-owner-1")
    with pytest.raises(PermissionError):
        action_broker.execute(approved_request, actor="builder-1")

    assert [record.event for record in action_broker.audit_records] == [
        "deny",
        "deny",
    ]


def test_action_policy_validates_known_actions_and_required_parameters(
    approved_request: ActionRequest,
) -> None:
    broker = ActionBroker(
        approved_actions=[make_record()],
        action_policies=[
            ActionPolicy(
                action_type="ReplanSprint",
                required_parameters=("capacity", "reason"),
            )
        ],
    )

    missing = broker.validate(approved_request)
    unknown = broker.validate(
        approved_request.model_copy(update={"action_type": "UnknownAction"})
    )

    assert missing.allowed is False
    assert missing.missing_fields == ("reason",)
    assert missing.approval_required is True
    assert unknown.allowed is False
    assert "unknown" in unknown.policy_reason.lower()


def test_an_explicit_empty_action_policy_allowlist_rejects_every_action(
    approved_request: ActionRequest,
) -> None:
    broker = ActionBroker(
        approved_actions=[make_record()],
        action_policies=[],
    )

    validation = broker.validate(approved_request)

    assert validation.allowed is False
    assert "unknown" in validation.policy_reason.lower()


def test_same_idempotency_key_returns_a_defensive_copy_of_same_outcome(
    action_broker: ActionBroker, approved_request: ActionRequest
) -> None:
    first = action_broker.execute(approved_request, actor="release-owner-1")
    second = action_broker.execute(approved_request, actor="release-owner-1")

    assert first.outcome_id == second.outcome_id
    assert first.request_id == second.request_id
    assert first.parameters_hash == approved_request.parameters_hash
    assert [record.event for record in action_broker.audit_records] == [
        "allow",
        "duplicate",
    ]
    assert [record.tool_id for record in action_broker.gateway_audit_records] == [
        "authorize_mock_action",
        "execute_mock_action",
        "authorize_mock_action",
    ]


def test_duplicate_cannot_replay_with_a_different_actor(
    action_broker: ActionBroker, approved_request: ActionRequest
) -> None:
    action_broker.execute(approved_request, actor="release-owner-1")

    with pytest.raises(PermissionError):
        action_broker.execute(approved_request, actor="builder-1")

    assert action_broker.audit_records[-1].event == "deny"


def test_duplicate_cannot_replay_with_a_different_trusted_release_owner(
    action_broker: ActionBroker, approved_request: ActionRequest
) -> None:
    action_broker.execute(approved_request, actor="release-owner-1")

    with pytest.raises(PermissionError, match="original execution actor"):
        action_broker.execute(approved_request, actor="release-owner")

    assert action_broker.audit_records[-1].event == "deny"


def test_idempotency_key_conflict_is_denied_before_a_second_execution(
    action_broker: ActionBroker, approved_request: ActionRequest
) -> None:
    action_broker.execute(approved_request, actor="release-owner-1")

    with pytest.raises(ValueError, match="idempotency key conflict"):
        action_broker.execute(
            approved_request.with_parameters({"capacity": 13}),
            actor="release-owner-1",
        )

    assert action_broker.audit_records[-1].event == "deny"


def test_mock_failure_produces_a_retryable_failed_outcome() -> None:
    request = make_request(
        action_id="action-fails",
        idempotency_key="replan-sprint-fails",
        parameters={"capacity": 8, "simulate_failure": True},
    )
    broker = ActionBroker(approved_actions=[make_record(request.action_id)])

    outcome = broker.execute(request, actor="release-owner-1")

    assert outcome.success is False
    assert outcome.status == "failed"
    assert outcome.retryable is True
    assert outcome.external_ref.startswith("mock://")
    assert [record.event for record in broker.audit_records] == ["allow", "failure"]


def test_outcomes_and_audits_are_defensive_copies(
    action_broker: ActionBroker, approved_request: ActionRequest
) -> None:
    outcome = action_broker.execute(approved_request, actor="release-owner-1")
    retrieved = action_broker.get_outcome(approved_request.action_id)

    assert retrieved.outcome_id == outcome.outcome_id
    assert outcome.actor == "release-owner-1"
    assert outcome.action_type == approved_request.action_type
    assert outcome.target_id == approved_request.target_id
    assert outcome.executed_at.tzinfo is not None
    with pytest.raises(TypeError):
        outcome.response_payload["forged"] = True
    with pytest.raises(ValidationError):
        outcome.status = "failed"  # type: ignore[misc]

    copied_audit = action_broker.audit_records
    copied_audit.clear()
    assert action_broker.audit_records


def test_mock_adapter_exception_is_audited_without_a_real_connector(
    approved_request: ActionRequest,
) -> None:
    class ExplodingMockAdapter(MockActionAdapter):
        def execute(
            self, action_type: str, target_id: str, parameters: dict[str, Any]
        ) -> Any:
            raise RuntimeError("mock adapter exploded")

    broker = ActionBroker(
        approved_actions=[make_record(approved_request.action_id)],
        adapter=ExplodingMockAdapter(),
    )

    with pytest.raises(RuntimeError, match="mock adapter exploded"):
        broker.execute(approved_request, actor="release-owner-1")

    assert broker.audit_records[-1].event == "exception"
