"""Mock Action registration and governed request construction for the demo."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Any

from aifde.domain.actions import ActionRequest
from aifde.tools.actions import ActionBroker, ActionPolicy


DEMO_ACTION_POLICIES = (
    ActionPolicy(action_type="CreateChangeRequest", required_parameters=("title",)),
    ActionPolicy(action_type="RequestClarification", required_parameters=("question",)),
    ActionPolicy(action_type="ApproveRequirement", required_parameters=("requirement_id",)),
    ActionPolicy(action_type="ReplanSprint", required_parameters=("capacity",)),
    ActionPolicy(action_type="ReassignWorkItem", required_parameters=("assignee",)),
    ActionPolicy(action_type="AdjustCommitmentDate", required_parameters=("commitment_date",)),
    ActionPolicy(action_type="EscalateRisk", required_parameters=("risk",)),
    ActionPolicy(action_type="RejectChangeRequest", required_parameters=("reason",)),
)


def register_demo_actions(action_broker: ActionBroker) -> None:
    """Register the sample Action allowlist on the supplied broker."""
    if not isinstance(action_broker, ActionBroker):
        raise TypeError("action_broker must be an ActionBroker")
    action_broker.register_policies(DEMO_ACTION_POLICIES)


def build_demo_action_request(
    *,
    action_id: str,
    action_type: str,
    target_id: str,
    parameters: dict[str, Any],
    requested_by: str,
    approval_actor: str,
    approval_status: str = "approved",
    approval_id: str | None = None,
    approval_role: str = "domain-owner",
) -> ActionRequest:
    parameter_hash = sha256(
        json.dumps(parameters, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:12]
    return ActionRequest(
        action_id=action_id,
        action_type=action_type,
        target_id=target_id,
        parameters=parameters,
        requested_by=requested_by,
        idempotency_key=f"demo:{action_id}:{parameter_hash}",
        execution_mode="mock",
        policy_id=f"demo-policy:{action_type}",
        policy_version="1.0.0",
        validation_id=f"validation:{action_id}",
        validated_by="deterministic-verifier-1",
        validation_status="passed" if approval_status == "approved" else "pending",
        approval_id=approval_id or f"approval:{action_id}",
        approval_actor=approval_actor,
        approval_role=approval_role,
        approval_status=approval_status,
        audit_ref=f"audit:{action_id}",
        audit_actor=requested_by,
        outcome_status="pending",
    )


__all__ = ["build_demo_action_request", "register_demo_actions"]
