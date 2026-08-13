from __future__ import annotations

import pytest

from aifde.policy.capabilities import ActorRole, ApprovedActionRecord
from aifde.tools.actions import ActionBroker, ActionPolicy
from software_delivery_demo.actions import build_demo_action_request, register_demo_actions


@pytest.fixture
def demo_action_broker() -> ActionBroker:
    broker = ActionBroker(
        action_policies=[
            ActionPolicy(action_type="ReplanSprint", required_parameters=("capacity",)),
            ActionPolicy(action_type="CreateChangeRequest", required_parameters=("title",)),
            ActionPolicy(action_type="RequestClarification", required_parameters=("question",)),
            ActionPolicy(action_type="ApproveRequirement", required_parameters=("requirement_id",)),
        ],
        approved_actions=[],
    )
    register_demo_actions(broker)
    return broker


def test_replan_action_requires_project_manager_approval(demo_action_broker: ActionBroker) -> None:
    request = build_demo_action_request(
        action_id="action-replan-1",
        action_type="ReplanSprint",
        target_id="sprint-001",
        parameters={"capacity": 20},
        requested_by="builder-1",
        approval_actor="project-manager",
        approval_status="pending",
    )
    with pytest.raises(PermissionError):
        demo_action_broker.execute(request, actor="release-owner-1")


def test_replan_action_writes_outcome_when_protected_approval_exists() -> None:
    action_id = "action-replan-2"
    approval = ApprovedActionRecord(
        action_id=action_id,
        action_type="ReplanSprint",
        execution_mode="mock",
        requested_by="builder-1",
        validation_status="passed",
        approval_id="approval-replan-2",
        approval_actor="domain-owner-1",
        approval_role=ActorRole.DOMAIN_OWNER,
        approval_status="approved",
    )
    broker = ActionBroker(
        approved_actions=[approval],
        action_policies=[ActionPolicy(action_type="ReplanSprint", required_parameters=("capacity",))],
    )
    request = build_demo_action_request(
        action_id=action_id,
        action_type="ReplanSprint",
        target_id="sprint-001",
        parameters={"capacity": 20},
        requested_by="builder-1",
        approval_actor="domain-owner-1",
        approval_status="approved",
        approval_id="approval-replan-2",
    )
    outcome = broker.execute(request, actor="release-owner-1")
    assert outcome.success is True
    assert broker.get_outcome(action_id).outcome_id == outcome.outcome_id
