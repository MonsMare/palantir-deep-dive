from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import pytest
from pydantic import ValidationError

from aifde.policy.capabilities import Capability, PolicyEngine, ToolContext
from aifde.policy.gateway import ToolGateway
from aifde.tools.protocol import ToolResult


@dataclass
class StubTool:
    tool_id: str
    required_capabilities: frozenset[Capability]
    allowed_stage_ids: frozenset[str]
    handler: Callable[[ToolContext, dict[str, Any]], ToolResult]

    def call(self, context: ToolContext, payload: dict[str, Any]) -> ToolResult:
        return self.handler(context, payload)


def _result(status: str, payload: dict[str, Any]) -> ToolResult:
    return ToolResult(status=status, payload=payload)


@pytest.fixture
def builder_context() -> ToolContext:
    return ToolContext(
        actor_id="builder-1",
        project_id="project-1",
        stage_id="decision.contract",
        artifact_ids=["artifact-1"],
        capability=Capability.READ,
        request_id="request-1",
    )


@pytest.fixture
def tools() -> list[StubTool]:
    return [
        StubTool(
            tool_id="create_artifact",
            required_capabilities=frozenset({Capability.PROPOSE}),
            allowed_stage_ids=frozenset({"decision.contract"}),
            handler=lambda _context, payload: _result("proposed", payload),
        ),
        StubTool(
            tool_id="execute_action",
            required_capabilities=frozenset({Capability.EXECUTE}),
            allowed_stage_ids=frozenset({"decision.contract"}),
            handler=lambda _context, payload: _result("executed", payload),
        ),
        StubTool(
            tool_id="train_model",
            required_capabilities=frozenset({Capability.VALIDATE}),
            allowed_stage_ids=frozenset({"model.training"}),
            handler=lambda _context, payload: _result("validated", payload),
        ),
    ]


@pytest.fixture
def gateway(tools: list[StubTool]) -> ToolGateway:
    return ToolGateway(tools, policy=PolicyEngine())


def test_builder_can_propose_but_cannot_execute(builder_context: ToolContext, gateway: ToolGateway):
    result = gateway.call(
        "create_artifact",
        builder_context.with_capability(Capability.PROPOSE),
        {"kind": "DecisionContract"},
    )
    assert result.status == "proposed"
    assert result.audit_id

    with pytest.raises(PermissionError):
        gateway.call(
            "execute_action",
            builder_context.with_capability(Capability.PROPOSE),
            {"action_type": "ReplanSprint"},
        )


def test_stage_scope_is_enforced(gateway: ToolGateway, builder_context: ToolContext):
    context = builder_context.model_copy(update={"stage_id": "ontology.design"})
    with pytest.raises(PermissionError):
        gateway.call("train_model", context.with_capability(Capability.VALIDATE), {"dataset": "future-stage"})


@pytest.mark.parametrize(
    ("actor_id", "allowed", "forbidden"),
    [
        ("builder-1", {Capability.READ, Capability.PROPOSE, Capability.VALIDATE}, {Capability.APPROVE, Capability.EXECUTE}),
        ("challenger-1", {Capability.READ, Capability.VALIDATE}, {Capability.PROPOSE, Capability.APPROVE, Capability.EXECUTE}),
        ("deterministic-verifier-1", {Capability.READ, Capability.VALIDATE}, {Capability.PROPOSE, Capability.APPROVE, Capability.EXECUTE}),
        ("domain-owner-1", {Capability.READ, Capability.APPROVE}, {Capability.PROPOSE, Capability.VALIDATE, Capability.EXECUTE}),
        ("release-owner-1", {Capability.READ, Capability.APPROVE, Capability.EXECUTE}, {Capability.PROPOSE, Capability.VALIDATE}),
    ],
)
def test_default_role_permissions(actor_id: str, allowed: set[Capability], forbidden: set[Capability]):
    policy = PolicyEngine()
    for capability in allowed:
        decision = policy.authorize(
            ToolContext(
                actor_id=actor_id,
                project_id="project-1",
                stage_id="decision.contract",
                artifact_ids=[],
                capability=capability,
                request_id=f"request-{capability.value}",
            ),
            StubTool("tool", frozenset({capability}), frozenset({"decision.contract"}), _result),
        )
        assert decision.allowed is True
    for capability in forbidden:
        decision = policy.authorize(
            ToolContext(
                actor_id=actor_id,
                project_id="project-1",
                stage_id="decision.contract",
                artifact_ids=[],
                capability=capability,
                request_id=f"request-{capability.value}",
            ),
            StubTool("tool", frozenset({capability}), frozenset({"decision.contract"}), _result),
        )
        assert decision.allowed is False


def test_only_release_owner_can_execute_approved_mock_action(tools: list[StubTool]):
    gateway = ToolGateway(tools)
    payload = {
        "action_type": "ReplanSprint",
        "execution_mode": "mock",
        "approval_status": "approved",
        "requested_by": "builder-1",
        "approval_actor": "domain-owner-1",
    }
    release_context = ToolContext(
        actor_id="release-owner-1",
        project_id="project-1",
        stage_id="decision.contract",
        artifact_ids=["artifact-1"],
        capability=Capability.EXECUTE,
        request_id="request-execute",
    )
    result = gateway.call("execute_action", release_context, payload)
    assert result.status == "executed"

    with pytest.raises(PermissionError):
        gateway.call("execute_action", release_context, {**payload, "execution_mode": "real"})


def test_every_execute_tool_requires_an_approved_mock_action():
    tool = StubTool(
        tool_id="write_external_system",
        required_capabilities=frozenset({Capability.EXECUTE}),
        allowed_stage_ids=frozenset({"decision.contract"}),
        handler=lambda _context, payload: _result("executed", payload),
    )
    gateway = ToolGateway([tool])
    context = ToolContext(
        actor_id="release-owner-1",
        project_id="project-1",
        stage_id="decision.contract",
        artifact_ids=[],
        capability=Capability.EXECUTE,
        request_id="request-unapproved-execute",
    )

    with pytest.raises(PermissionError, match="mock Action"):
        gateway.call("write_external_system", context, {"action_type": "ReplanSprint"})


def test_self_approved_action_is_rejected(tools: list[StubTool]):
    gateway = ToolGateway(tools)
    context = ToolContext(
        actor_id="release-owner-1",
        project_id="project-1",
        stage_id="decision.contract",
        artifact_ids=[],
        capability=Capability.EXECUTE,
        request_id="request-self-approved",
    )
    with pytest.raises(PermissionError):
        gateway.call(
            "execute_action",
            context,
            {
                "action_type": "ReplanSprint",
                "execution_mode": "mock",
                "approval_status": "approved",
                "requested_by": "builder-1",
                "approval_actor": "builder-1",
            },
        )


def test_gateway_rejects_untyped_context_and_tool_result(builder_context: ToolContext):
    bad_tool = StubTool(
        tool_id="bad",
        required_capabilities=frozenset({Capability.READ}),
        allowed_stage_ids=frozenset({"decision.contract"}),
        handler=lambda _context, _payload: "not-a-tool-result",  # type: ignore[return-value]
    )
    gateway = ToolGateway([bad_tool])
    with pytest.raises(TypeError, match="ToolContext"):
        gateway.call("bad", object(), {})  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="ToolResult"):
        gateway.call("bad", builder_context, {})


def test_context_copy_revalidates_capability(builder_context: ToolContext):
    with pytest.raises(ValidationError):
        builder_context.model_copy(update={"capability": "not-a-capability"})


def test_every_policy_decision_has_an_audit_record(builder_context: ToolContext, gateway: ToolGateway):
    with pytest.raises(PermissionError):
        gateway.call(
            "execute_action",
            builder_context.with_capability(Capability.PROPOSE),
            {"action_type": "ReplanSprint"},
        )

    assert len(gateway.audit_records) == 1
    assert gateway.audit_records[0].allowed is False
    assert gateway.audit_records[0].request_id == builder_context.request_id
