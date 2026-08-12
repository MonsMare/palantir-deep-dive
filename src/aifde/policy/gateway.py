"""The audited, capability-checked boundary for every tool invocation."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from contextvars import ContextVar
from copy import copy
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from aifde.policy.capabilities import (
    ActorRole,
    ApprovedActionRecord,
    ApprovalVerifier,
    AuditRecord,
    Capability,
    PolicyDecision,
    PolicyEngine,
    ToolContext,
    _denied,
    _normalize_stage_ids,
    _validate_tool_shape,
)
from aifde.tools.protocol import Tool, ToolResult


@dataclass(frozen=True)
class _ToolSnapshot:
    tool_id: str
    required_capabilities: frozenset[Capability]
    allowed_stage_ids: frozenset[str]
    call: Any



class _InvocationToken:
    """Opaque, single-use proof installed only around a gateway invocation."""

    __slots__ = ("gateway", "tool_id", "context", "consumed")

    def __init__(self, gateway: ToolGateway, tool_id: str, context: ToolContext) -> None:
        self.gateway = gateway
        self.tool_id = tool_id
        self.context = context
        self.consumed = False


_ACTIVE_INVOCATION: ContextVar[_InvocationToken | None] = ContextVar(
    "aifde_active_tool_invocation", default=None
)


class ToolGateway:
    """Resolve, authorize, audit, and invoke tools through one narrow boundary."""

    def __init__(
        self,
        tools: Iterable[Tool] | Mapping[str, Tool],
        *,
        policy: PolicyEngine | None = None,
        approved_actions: Iterable[ApprovedActionRecord]
        | Mapping[str, ApprovedActionRecord]
        | None = None,
        approval_verifier: ApprovalVerifier | None = None,
    ) -> None:
        source_policy = policy or PolicyEngine()
        self._policy = source_policy.snapshot()
        self._tools: dict[str, _ToolSnapshot] = {}
        self._audit_records: list[AuditRecord] = []
        if approval_verifier is not None and approved_actions is not None:
            raise ValueError("provide approval_verifier or approved_actions, not both")
        self._approval_verifier = approval_verifier or ApprovalVerifier(approved_actions)

        source = tools.values() if isinstance(tools, Mapping) else tools
        for tool in source:
            snapshot = self._register_tool(tool)
            if snapshot.tool_id in self._tools:
                raise ValueError(f"duplicate tool_id: {snapshot.tool_id}")
            self._tools[snapshot.tool_id] = snapshot

    @property
    def audit_records(self) -> list[AuditRecord]:
        """Return defensive copies of all attempted calls."""

        return [record.model_copy(deep=True) for record in self._audit_records]

    @property
    def audit_log(self) -> list[AuditRecord]:
        """Backward-friendly alias for callers that name the collection a log."""

        return self.audit_records

    def list_audit_records(self) -> list[AuditRecord]:
        """Return the audited invocation history."""

        return self.audit_records

    def issue_context(
        self,
        *,
        actor_id: str,
        project_id: str,
        stage_id: str,
        artifact_ids: Iterable[str] = (),
        capability: Capability,
        request_id: str,
    ) -> ToolContext:
        """Issue a trusted context through this gateway's policy snapshot."""

        return self._policy.issue_context(
            actor_id=actor_id,
            project_id=project_id,
            stage_id=stage_id,
            artifact_ids=artifact_ids,
            capability=capability,
            request_id=request_id,
        )

    def call(
        self, tool_id: str, context: ToolContext, payload: dict[str, Any]
    ) -> ToolResult:
        """Authorize and invoke one tool with a trusted, isolated context."""

        if not isinstance(context, ToolContext):
            raise TypeError("context must be a ToolContext")
        if type(payload) is not dict:
            raise TypeError("payload must be a dict")
        if not isinstance(tool_id, str) or not tool_id.strip():
            raise ValueError("tool_id must be a non-empty string")
        canonical_tool_id = tool_id.strip()
        try:
            tool = self._tools[canonical_tool_id]
        except KeyError as exc:
            decision = PolicyDecision(
                allowed=False,
                reason=f"unknown tool: {canonical_tool_id}",
            )
            self._record(context, canonical_tool_id, decision)
            raise KeyError(f"unknown tool: {canonical_tool_id}") from exc

        if not context._is_trusted(self._policy._authority):
            decision = _denied(
                "context was not issued by the trusted policy",
                None,
            )
            self._record(context, canonical_tool_id, decision)
            raise PermissionError(decision.reason)

        # Keep two independent snapshots: one is private audit state and the
        # other is the isolated object handed to the tool.  Even a malicious
        # tool using object.__setattr__ cannot rewrite the audit identity.
        audit_context = context.model_copy(deep=True)
        tool_context = audit_context.model_copy(deep=True)
        decision = self._policy.authorize(audit_context, tool)
        if not decision.allowed:
            self._record(audit_context, canonical_tool_id, decision)
            raise PermissionError(decision.reason)

        try:
            invocation_payload = deepcopy(payload)
        except Exception as exc:
            self._record(
                audit_context,
                canonical_tool_id,
                decision,
                outcome_status="invalid_payload",
            )
            raise TypeError("payload must be deeply copyable") from exc

        action_decision = self._authorize_action(
            tool, audit_context, invocation_payload
        )
        if action_decision is not None and not action_decision.allowed:
            self._record(audit_context, canonical_tool_id, action_decision)
            raise PermissionError(action_decision.reason)

        token = _InvocationToken(self, canonical_tool_id, tool_context)
        token_var = _ACTIVE_INVOCATION.set(token)
        try:
            # The snapshot's guarded adapter is the only callable retained by
            # the gateway.  It consumes the opaque token before delegating to
            # the original implementation, making re-entry/direct execution
            # fail closed as well.
            result = tool.call(tool_context, invocation_payload)
        except Exception:
            self._record(
                audit_context,
                canonical_tool_id,
                decision,
                outcome_status="error",
            )
            raise
        finally:
            _ACTIVE_INVOCATION.reset(token_var)

        if not isinstance(result, ToolResult):
            self._record(
                audit_context,
                canonical_tool_id,
                decision,
                outcome_status="invalid_result",
            )
            raise TypeError("tool.call must return a ToolResult")

        try:
            result = ToolResult.model_validate(
                {
                    **result.model_dump(mode="python"),
                    "audit_id": decision.audit_id,
                }
            )
        except Exception:
            self._record(
                audit_context,
                canonical_tool_id,
                decision,
                outcome_status="invalid_result",
            )
            raise
        self._record(
            audit_context,
            canonical_tool_id,
            decision,
            outcome_status=result.status,
        )
        return result

    def _register_tool(self, tool: Tool) -> _ToolSnapshot:
        _validate_tool_shape(tool)
        tool_id = tool.tool_id.strip()

        required = _require_declared_capabilities(tool.required_capabilities)

        try:
            allowed_stages = _normalize_stage_ids(
                tool.allowed_stage_ids,
                self._policy.known_stage_ids,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("tool.allowed_stage_ids must contain known canonical stages") from exc
        if not allowed_stages:
            raise ValueError("tool.allowed_stage_ids must not be empty")

        execution_tool = _copy_tool_for_execution(tool)
        _validate_tool_shape(execution_tool)
        try:
            setattr(execution_tool, "tool_id", tool_id)
            setattr(execution_tool, "required_capabilities", required)
            setattr(execution_tool, "allowed_stage_ids", allowed_stages)
        except Exception as exc:
            raise TypeError("tool metadata must be snapshot-compatible") from exc

        raw_call = getattr(execution_tool, "call")
        guarded_call = _install_call_guard(execution_tool, raw_call, self, tool_id)
        _install_call_guard(tool, getattr(tool, "call"), self, tool_id)
        return _ToolSnapshot(
            tool_id=tool_id,
            required_capabilities=required,
            allowed_stage_ids=allowed_stages,
            call=guarded_call,
        )

    def _authorize_action(
        self,
        tool: _ToolSnapshot,
        context: ToolContext,
        payload: Mapping[str, Any],
    ) -> PolicyDecision | None:
        if Capability.EXECUTE not in tool.required_capabilities:
            return None

        required = Capability.EXECUTE
        if self._policy.role_for(context.actor_id) != ActorRole.RELEASE_OWNER.value:
            return _denied(
                "only the trusted release owner may execute an Action",
                required,
            )

        action_id = payload.get("action_id")
        if not isinstance(action_id, str) or not action_id.strip():
            return _denied(
                "an approved mock Action record is required",
                required,
            )
        record = self._approval_verifier.verify(action_id.strip())
        if record is None:
            return _denied(
                "an approved mock Action record is required",
                required,
            )
        if not isinstance(record, ApprovedActionRecord):
            return _denied("approval verifier returned an invalid record", required)
        if record.execution_mode != "mock":
            return _denied("only mock Actions may be executed", required)
        if record.validation_status != "passed":
            return _denied("Action validation must have passed", required)
        if record.approval_status != "approved":
            return _denied("an Action must be approved before execution", required)
        if record.approval_role is not ActorRole.DOMAIN_OWNER:
            return _denied("only a Domain Owner may approve an Action", required)
        if self._policy.role_for(record.approval_actor) != ActorRole.DOMAIN_OWNER.value:
            return _denied("approval actor is not a trusted Domain Owner", required)
        if record.approval_actor == record.requested_by:
            return _denied("requester cannot approve their own Action", required)
        if self._policy.actor_binding(record.requested_by) is None:
            return _denied("Action requester is not a trusted actor", required)

        # Optional payload fields are only consistency checks.  They never
        # supply the authorization facts used above.
        for field in ("action_type", "execution_mode", "requested_by"):
            if field in payload and payload[field] != getattr(record, field):
                return _denied(f"Action {field} does not match its record", required)
        for field in (
            "approval_status",
            "approval_actor",
            "approval_role",
            "validation_status",
        ):
            if field in payload:
                expected = getattr(record, field)
                actual = payload[field]
                if isinstance(expected, ActorRole):
                    expected = expected.value
                if actual != expected:
                    return _denied(f"Action {field} does not match its record", required)
        return None

    def _record(
        self,
        context: ToolContext,
        tool_id: str,
        decision: PolicyDecision,
        *,
        outcome_status: str | None = None,
    ) -> None:
        self._audit_records.append(
            AuditRecord(
                audit_id=decision.audit_id,
                request_id=context.request_id,
                tool_id=tool_id,
                actor_id=context.actor_id,
                project_id=context.project_id,
                stage_id=context.stage_id,
                capability=context.capability,
                allowed=decision.allowed,
                reason=decision.reason,
                required_capability=decision.required_capability,
                outcome_status=outcome_status,
            )
        )


def _install_call_guard(
    tool: Tool,
    raw_call: Any,
    gateway: ToolGateway,
    tool_id: str,
) -> Any:
    """Replace the public method with a gateway-issued-token guard.

    A generic Python object cannot hide a method that its owner deliberately
    exposes.  Failing closed at registration for non-patchable objects, then
    guarding the method on patchable tools, gives this compatibility layer a
    concrete direct-call rejection while keeping the brief's two-argument
    ``Tool.call(context, payload)`` shape.
    """

    def guarded_call(context: ToolContext, payload: dict[str, Any]) -> ToolResult:
        token = _ACTIVE_INVOCATION.get()
        if (
            token is None
            or token.gateway is not gateway
            or token.tool_id != tool_id
            or token.context is not context
            or token.consumed
        ):
            raise PermissionError("Tool.call requires a ToolGateway invocation token")
        token.consumed = True
        return raw_call(context, payload)

    setattr(guarded_call, "_aifde_gateway_guard", True)
    try:
        setattr(tool, "call", guarded_call)
    except Exception as exc:
        raise TypeError("tool.call must be gateway-guardable") from exc
    if getattr(tool, "call", None) is not guarded_call:
        raise TypeError("tool.call must be gateway-guardable")
    return guarded_call


def _copy_tool_for_execution(tool: Tool) -> Tool:
    try:
        execution_tool = copy(tool)
    except Exception as exc:
        raise TypeError("tool must be copyable for gateway registration") from exc
    current_call = getattr(execution_tool, "call", None)
    if getattr(current_call, "_aifde_gateway_guard", False):
        try:
            delattr(execution_tool, "call")
        except AttributeError:
            pass
    return execution_tool


def _require_declared_capabilities(values: Any) -> frozenset[Capability]:
    if isinstance(values, Capability) or isinstance(values, str):
        raise TypeError("tool.required_capabilities must be a non-empty Capability set")
    try:
        declared = tuple(values)
    except TypeError as exc:
        raise TypeError("tool.required_capabilities must be iterable") from exc
    if not declared:
        raise ValueError("tool.required_capabilities must not be empty")
    if any(not isinstance(value, Capability) for value in declared):
        raise TypeError("tool.required_capabilities must contain Capability values")
    return frozenset(declared)


__all__ = ["ToolGateway"]
