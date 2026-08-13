from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import pytest
from pydantic import ValidationError

from aifde.policy.capabilities import (
    ActorRole,
    ApprovedActionRecord,
    Capability,
    PolicyEngine,
    ToolContext,
)
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
def builder_context(gateway: ToolGateway) -> ToolContext:
    return gateway.issue_context(
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
def approved_action() -> ApprovedActionRecord:
    return ApprovedActionRecord(
        action_id="action-1",
        action_type="ReplanSprint",
        execution_mode="mock",
        requested_by="builder-1",
        validation_status="passed",
        approval_id="approval-1",
        approval_actor="domain-owner-1",
        approval_role=ActorRole.DOMAIN_OWNER,
        approval_status="approved",
    )


@pytest.fixture
def gateway(
    tools: list[StubTool], approved_action: ApprovedActionRecord
) -> ToolGateway:
    return ToolGateway(
        tools,
        policy=PolicyEngine(),
        approved_actions=[approved_action],
    )


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
            policy.issue_context(
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
            policy.issue_context(
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
    gateway = ToolGateway(
        tools,
        approved_actions=[
            ApprovedActionRecord(
                action_id="action-1",
                action_type="ReplanSprint",
                execution_mode="mock",
                requested_by="builder-1",
                validation_status="passed",
                approval_id="approval-1",
                approval_actor="domain-owner-1",
                approval_role=ActorRole.DOMAIN_OWNER,
                approval_status="approved",
            )
        ],
    )
    payload = {
            "action_type": "ReplanSprint",
            "action_id": "action-1",
            "execution_mode": "mock",
            "approval_status": "approved",
            "requested_by": "builder-1",
        "approval_actor": "domain-owner-1",
    }
    release_context = gateway.issue_context(
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
    context = gateway.issue_context(
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
    context = gateway.issue_context(
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
            "action_id": "action-1",
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

    trusted_context = gateway.issue_context(
        actor_id="builder-1",
        project_id="project-1",
        stage_id="decision.contract",
        artifact_ids=[],
        capability=Capability.READ,
        request_id="request-invalid-result",
    )
    with pytest.raises(TypeError, match="ToolResult"):
        gateway.call("bad", trusted_context, {})


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


@pytest.mark.parametrize("actor_id", [
    "builder-unknown",
    "release-owner-attacker",
    "RELEASE-OWNER-1",
    " release-owner-1 ",
])
def test_role_shaped_or_noncanonical_actor_is_not_trusted(
    actor_id: str, gateway: ToolGateway
):
    context = ToolContext(
        actor_id=actor_id,
        project_id="project-1",
        stage_id="decision.contract",
        artifact_ids=[],
        capability=Capability.EXECUTE,
        request_id=f"request-{actor_id.strip() or 'blank'}",
    )

    with pytest.raises(PermissionError):
        gateway.call(
            "execute_action",
            context,
            {"action_id": "action-1", "action_type": "ReplanSprint"},
        )

    assert gateway.audit_records[-1].allowed is False
    assert gateway.audit_records[-1].actor_id == actor_id


def test_model_copy_and_assignment_cannot_escalate_authority(
    builder_context: ToolContext, gateway: ToolGateway
):
    forged = builder_context.model_copy(
        update={"actor_id": "release-owner-1", "capability": Capability.EXECUTE}
    )

    with pytest.raises(PermissionError):
        gateway.call(
            "execute_action",
            forged,
            {"action_id": "action-1", "action_type": "ReplanSprint"},
        )
    with pytest.raises(ValidationError):
        builder_context.actor_id = "release-owner-1"  # type: ignore[misc]


def test_low_level_context_mutation_invalidates_the_trusted_binding(
    builder_context: ToolContext, gateway: ToolGateway
):
    object.__setattr__(builder_context, "actor_id", "release-owner-1")
    object.__setattr__(builder_context, "capability", Capability.EXECUTE)

    with pytest.raises(PermissionError):
        gateway.call(
            "execute_action",
            builder_context,
            {"action_id": "action-1", "action_type": "ReplanSprint"},
        )

    assert gateway.audit_records[-1].allowed is False


def test_with_capability_is_rechecked_against_trusted_actor_directory(
    builder_context: ToolContext, gateway: ToolGateway
):
    with pytest.raises(PermissionError):
        gateway.call(
            "execute_action",
            builder_context.with_capability(Capability.EXECUTE),
            {"action_id": "action-1", "action_type": "ReplanSprint"},
        )


def test_approval_must_be_a_typed_record_from_a_domain_owner(
    tools: list[StubTool], approved_action: ApprovedActionRecord
):
    gateway = ToolGateway(
        tools,
        approved_actions=[approved_action],
    )
    context = gateway.issue_context(
        actor_id="release-owner-1",
        project_id="project-1",
        stage_id="decision.contract",
        artifact_ids=[],
        capability=Capability.EXECUTE,
        request_id="request-fake-approval",
    )

    with pytest.raises(PermissionError):
        gateway.call(
            "execute_action",
            context,
            {
                "action_id": "action-1",
                "action_type": "ReplanSprint",
                "approval_status": "approved",
                "approval_actor": "challenger-1",
                "approval_role": "challenger",
                "validation_status": "passed",
            },
        )

    assert gateway.audit_records[-1].allowed is False


def test_unregistered_or_unvalidated_action_cannot_execute(tools: list[StubTool]):
    record = ApprovedActionRecord(
        action_id="action-unvalidated",
        action_type="ReplanSprint",
        execution_mode="mock",
        requested_by="builder-1",
        validation_status="failed",
        approval_id="approval-unvalidated",
        approval_actor="domain-owner-1",
        approval_role=ActorRole.DOMAIN_OWNER,
        approval_status="approved",
    )
    gateway = ToolGateway(tools, approved_actions=[record])
    context = gateway.issue_context(
        actor_id="release-owner-1",
        project_id="project-1",
        stage_id="decision.contract",
        artifact_ids=[],
        capability=Capability.EXECUTE,
        request_id="request-unvalidated",
    )

    with pytest.raises(PermissionError):
        gateway.call(
            "execute_action",
            context,
            {"action_id": "action-unvalidated", "action_type": "ReplanSprint"},
        )


def test_registered_tool_metadata_is_an_immutable_snapshot(
    tools: list[StubTool], gateway: ToolGateway
):
    tool = tools[0]
    tool.tool_id = "mutated-id"
    tool.required_capabilities = frozenset({Capability.READ})
    tool.allowed_stage_ids = frozenset({"model.training"})

    result = gateway.call(
        "create_artifact",
        gateway.issue_context(
            actor_id="builder-1",
            project_id="project-1",
            stage_id="decision.contract",
            artifact_ids=[],
            capability=Capability.PROPOSE,
            request_id="request-tool-snapshot",
        ),
        {"kind": "DecisionContract"},
    )

    assert result.status == "proposed"

    with pytest.raises(KeyError, match="unknown tool"):
        gateway.call(
            "mutated-id",
            gateway.issue_context(
                actor_id="builder-1",
                project_id="project-1",
                stage_id="model.training",
                artifact_ids=[],
                capability=Capability.READ,
                request_id="request-mutated-tool-id",
            ),
            {},
        )


def test_registered_tool_handler_is_an_immutable_execution_snapshot(
    tools: list[StubTool], approved_action: ApprovedActionRecord
):
    gateway = ToolGateway(tools, approved_actions=[approved_action])
    tools[0].handler = lambda _context, _payload: _result(
        "mutated-after-registration", {}
    )

    result = gateway.call(
        "create_artifact",
        gateway.issue_context(
            actor_id="builder-1",
            project_id="project-1",
            stage_id="decision.contract",
            artifact_ids=[],
            capability=Capability.PROPOSE,
            request_id="request-handler-snapshot",
        ),
        {"kind": "DecisionContract"},
    )

    assert result.status == "proposed"


def test_policy_permissions_are_snapshotted_at_gateway_initialization(
    tools: list[StubTool], approved_action: ApprovedActionRecord
):
    policy = PolicyEngine()
    gateway = ToolGateway(tools, policy=policy, approved_actions=[approved_action])
    original_permissions = PolicyEngine.DEFAULT_PERMISSIONS
    PolicyEngine.DEFAULT_PERMISSIONS = {
        **original_permissions,
        "builder": frozenset({Capability.READ, Capability.PROPOSE, Capability.VALIDATE, Capability.EXECUTE}),
    }
    try:
        with pytest.raises(PermissionError):
            gateway.call(
                "execute_action",
                gateway.issue_context(
                    actor_id="builder-1",
                    project_id="project-1",
                    stage_id="decision.contract",
                    artifact_ids=[],
                    capability=Capability.EXECUTE,
                    request_id="request-policy-snapshot",
                ),
                {"action_id": "action-1", "action_type": "ReplanSprint"},
            )
    finally:
        PolicyEngine.DEFAULT_PERMISSIONS = original_permissions


def test_policy_explicit_update_api_creates_a_new_snapshot(
    tools: list[StubTool], approved_action: ApprovedActionRecord
):
    base_policy = PolicyEngine(stage_ids=["decision.contract"])
    first_gateway = ToolGateway(
        [tools[1]],
        policy=base_policy,
        approved_actions=[approved_action],
    )
    updated_policy = base_policy.with_actor_role(
        "release-owner-2", ActorRole.RELEASE_OWNER
    )
    second_gateway = ToolGateway(
        [tools[1]],
        policy=updated_policy,
        approved_actions=[approved_action],
    )

    with pytest.raises(PermissionError):
        first_gateway.issue_context(
            actor_id="release-owner-2",
            project_id="project-1",
            stage_id="decision.contract",
            artifact_ids=[],
            capability=Capability.EXECUTE,
            request_id="request-old-policy",
        )

    context = second_gateway.issue_context(
        actor_id="release-owner-2",
        project_id="project-1",
        stage_id="decision.contract",
        artifact_ids=[],
        capability=Capability.EXECUTE,
        request_id="request-updated-policy",
    )
    result = second_gateway.call(
        "execute_action",
        context,
        {"action_id": "action-1", "action_type": "ReplanSprint"},
    )

    assert result.status == "executed"
    assert base_policy.actor_binding("release-owner-2") is None


def test_tool_receives_isolated_context_and_audit_uses_gateway_snapshot(
    tools: list[StubTool]
):
    observed: list[ToolContext] = []

    def mutating_handler(context: ToolContext, _payload: dict[str, Any]) -> ToolResult:
        observed.append(context)
        with pytest.raises(ValidationError):
            context.project_id = "project-forged"  # type: ignore[misc]
        with pytest.raises(AttributeError):
            context.artifact_ids.append("artifact-forged")  # type: ignore[attr-defined]
        object.__setattr__(context, "actor_id", "release-owner-attacker")
        object.__setattr__(context, "project_id", "project-forged")
        object.__setattr__(context, "stage_id", "release.forced")
        object.__setattr__(context, "request_id", "request-forged")
        return _result("read", {"nested": {"value": "original"}})

    tools[0].handler = mutating_handler
    gateway = ToolGateway(tools)
    caller_context = gateway.issue_context(
        actor_id="builder-1",
        project_id="project-1",
        stage_id="decision.contract",
        artifact_ids=["artifact-1"],
        capability=Capability.PROPOSE,
        request_id="request-context-snapshot",
    )
    result = gateway.call("create_artifact", caller_context, {})

    assert observed[0] is not caller_context
    assert caller_context.project_id == "project-1"
    assert gateway.audit_records[-1].project_id == "project-1"
    assert gateway.audit_records[-1].request_id == "request-context-snapshot"
    assert result.payload["nested"]["value"] == "original"


def test_tool_result_is_deep_immutable_and_audit_is_defensive(
    gateway: ToolGateway, builder_context: ToolContext
):
    result = gateway.call("create_artifact", builder_context.with_capability(Capability.PROPOSE), {"x": 1})

    with pytest.raises(TypeError):
        result.payload["nested"] = {"forged": True}
    with pytest.raises(TypeError):
        result.artifact_ids.append("forged")  # type: ignore[attr-defined]

    audit_records = gateway.audit_records
    audit_records.clear()
    assert gateway.audit_records


@pytest.mark.parametrize(
    ("required_capabilities", "allowed_stage_ids"),
    [
        (frozenset(), frozenset({"decision.contract"})),
        (frozenset({"not-a-capability"}), frozenset({"decision.contract"})),  # type: ignore[arg-type]
        (frozenset({"read"}), frozenset({"decision.contract"})),  # type: ignore[arg-type]
        (frozenset({Capability.READ}), frozenset()),
        (frozenset({Capability.READ}), frozenset({" "})),
        (frozenset({Capability.READ}), frozenset({"future.unknown"})),
        (frozenset({Capability.READ}), frozenset({"DECISION.CONTRACT"})),
    ],
)
def test_invalid_tool_declaration_is_rejected_at_registration(
    required_capabilities: frozenset[Any], allowed_stage_ids: frozenset[str]
):
    tool = StubTool("invalid", required_capabilities, allowed_stage_ids, _result)
    with pytest.raises((TypeError, ValueError)):
        ToolGateway([tool])


def test_tool_id_is_canonicalized_for_registration_and_lookup():
    tool = StubTool(
        "  spaced-tool  ",
        frozenset({Capability.READ}),
        frozenset({"decision.contract"}),
        lambda _context, _payload: _result("read", {}),
    )
    gateway = ToolGateway([tool])
    context = gateway.issue_context(
        actor_id="builder-1",
        project_id="project-1",
        stage_id="decision.contract",
        artifact_ids=[],
        capability=Capability.READ,
        request_id="request-tool-id",
    )

    assert gateway.call("spaced-tool", context, {}).status == "read"


def test_direct_tool_call_requires_a_gateway_invocation(
    tools: list[StubTool], builder_context: ToolContext, gateway: ToolGateway
):
    with pytest.raises(PermissionError, match="ToolGateway"):
        tools[0].call(builder_context, {})

    assert gateway.audit_records == []


def test_tool_exception_is_audited_with_trusted_context(tools: list[StubTool]):
    def raising_handler(_context: ToolContext, _payload: dict[str, Any]) -> ToolResult:
        raise RuntimeError("tool exploded")

    tools[0].handler = raising_handler
    gateway = ToolGateway(tools)
    context = gateway.issue_context(
        actor_id="builder-1",
        project_id="project-1",
        stage_id="decision.contract",
        artifact_ids=[],
        capability=Capability.PROPOSE,
        request_id="request-tool-exception",
    )

    with pytest.raises(RuntimeError, match="tool exploded"):
        gateway.call("create_artifact", context, {})

    assert gateway.audit_records[-1].outcome_status == "error"
    assert gateway.audit_records[-1].request_id == "request-tool-exception"


def test_explicit_actor_directory_can_register_an_exact_release_owner(
    tools: list[StubTool], approved_action: ApprovedActionRecord
):
    policy = PolicyEngine(
        actor_roles={"release-owner-2": ActorRole.RELEASE_OWNER},
        stage_ids=["decision.contract"],
    )
    gateway = ToolGateway(
        [tools[1]],
        policy=policy,
        approved_actions=[approved_action],
    )
    context = gateway.issue_context(
        actor_id="release-owner-2",
        project_id="project-1",
        stage_id="decision.contract",
        artifact_ids=[],
        capability=Capability.EXECUTE,
        request_id="request-explicit-directory",
    )

    assert gateway.call(
        "execute_action",
        context,
        {"action_id": "action-1", "action_type": "ReplanSprint"},
    ).status == "executed"


def test_policy_rejects_empty_or_unknown_stage_registry():
    with pytest.raises(ValueError):
        PolicyEngine(stage_ids=[])
    with pytest.raises(ValueError):
        PolicyEngine(stage_ids=["future.unknown"])


def test_policy_rejects_noncanonical_actor_binding():
    with pytest.raises(ValueError):
        PolicyEngine(actor_roles={" release-owner-2 ": ActorRole.RELEASE_OWNER})


def test_approval_verifier_snapshot_is_not_affected_by_record_mutation(
    tools: list[StubTool], approved_action: ApprovedActionRecord
):
    gateway = ToolGateway(tools, approved_actions=[approved_action])
    object.__setattr__(approved_action, "approval_actor", "challenger-1")
    context = gateway.issue_context(
        actor_id="release-owner-1",
        project_id="project-1",
        stage_id="decision.contract",
        artifact_ids=[],
        capability=Capability.EXECUTE,
        request_id="request-approval-snapshot",
    )

    assert gateway.call(
        "execute_action",
        context,
        {"action_id": "action-1", "action_type": "ReplanSprint"},
    ).status == "executed"


def test_custom_approval_verifier_must_return_a_typed_record(
    tools: list[StubTool]
):
    class FakeVerifier:
        def verify(self, _action_id: str) -> dict[str, str]:
            return {"approval_status": "approved"}

    gateway = ToolGateway(tools, approval_verifier=FakeVerifier())  # type: ignore[arg-type]
    context = gateway.issue_context(
        actor_id="release-owner-1",
        project_id="project-1",
        stage_id="decision.contract",
        artifact_ids=[],
        capability=Capability.EXECUTE,
        request_id="request-untyped-verifier",
    )

    with pytest.raises(PermissionError):
        gateway.call(
            "execute_action",
            context,
            {"action_id": "action-1", "action_type": "ReplanSprint"},
        )


def test_non_json_nested_result_is_audited_as_invalid_result(tools: list[StubTool]):
    tools[0].handler = lambda _context, _payload: ToolResult.model_construct(
        status="read", payload={"not_serializable": object()}, audit_id="forged"
    )
    gateway = ToolGateway(tools)
    context = gateway.issue_context(
        actor_id="builder-1",
        project_id="project-1",
        stage_id="decision.contract",
        artifact_ids=[],
        capability=Capability.PROPOSE,
        request_id="request-invalid-nested-result",
    )

    with pytest.raises(TypeError):
        gateway.call("create_artifact", context, {})

    assert gateway.audit_records[-1].outcome_status == "invalid_result"
