"""The audited, capability-checked boundary for every tool invocation."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from aifde.policy.capabilities import (
    AuditRecord,
    Capability,
    PolicyDecision,
    PolicyEngine,
    ToolContext,
)
from aifde.tools.protocol import Tool, ToolResult


class ToolGateway:
    """Resolve, authorize, audit, and invoke tools through one narrow boundary."""

    def __init__(
        self,
        tools: Iterable[Tool] | Mapping[str, Tool],
        *,
        policy: PolicyEngine | None = None,
    ) -> None:
        self._policy = policy or PolicyEngine()
        self._tools: dict[str, Tool] = {}
        self._audit_records: list[AuditRecord] = []
        source = tools.values() if isinstance(tools, Mapping) else tools
        for tool in source:
            _validate_tool(tool)
            if tool.tool_id in self._tools:
                raise ValueError(f"duplicate tool_id: {tool.tool_id}")
            self._tools[tool.tool_id] = tool

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

    def call(
        self, tool_id: str, context: ToolContext, payload: dict[str, Any]
    ) -> ToolResult:
        """Authorize and invoke one tool with a typed context and payload."""
        if not isinstance(context, ToolContext):
            raise TypeError("context must be a ToolContext")
        if not isinstance(payload, dict):
            raise TypeError("payload must be a dict")
        if not isinstance(tool_id, str) or not tool_id.strip():
            raise ValueError("tool_id must be a non-empty string")
        tool_id = tool_id.strip()
        try:
            tool = self._tools[tool_id]
        except KeyError as exc:
            decision = PolicyDecision(
                allowed=False,
                reason=f"unknown tool: {tool_id}",
            )
            self._record(context, tool_id, decision)
            raise KeyError(f"unknown tool: {tool_id}") from exc

        decision = self._policy.authorize(context, tool)
        if not decision.allowed:
            self._record(context, tool_id, decision)
            raise PermissionError(decision.reason)

        action_decision = self._authorize_action(tool, context, payload)
        if action_decision is not None and not action_decision.allowed:
            self._record(context, tool_id, action_decision)
            raise PermissionError(action_decision.reason)

        try:
            result = tool.call(context, payload)
        except Exception:
            self._record(context, tool_id, decision, outcome_status="error")
            raise
        if not isinstance(result, ToolResult):
            self._record(context, tool_id, decision, outcome_status="invalid_result")
            raise TypeError("tool.call must return a ToolResult")

        result = ToolResult.model_validate(
            {
                **result.model_dump(mode="python"),
                "audit_id": decision.audit_id,
            }
        )
        self._record(context, tool_id, decision, outcome_status=result.status)
        return result

    def _authorize_action(
        self,
        tool: Tool,
        context: ToolContext,
        payload: dict[str, Any],
    ) -> PolicyDecision | None:
        if Capability.EXECUTE not in tool.required_capabilities:
            return None

        required = Capability.EXECUTE
        if self._policy.role_for(context.actor_id) != "release-owner":
            return _denied(
                "only the release owner may execute an Action",
                required_capability=required,
            )
        if payload.get("execution_mode") != "mock":
            return _denied(
                "only mock Actions may be executed",
                required_capability=required,
            )
        if payload.get("approval_status") != "approved":
            return _denied(
                "an Action must be approved before execution",
                required_capability=required,
            )

        requested_by = _identity_from_payload(payload, "requested_by")
        approval_actor = _identity_from_payload(payload, "approval_actor")
        if requested_by is None or approval_actor is None:
            return _denied(
                "an approved Action must identify its requester and approver",
                required_capability=required,
            )
        if requested_by.casefold() == approval_actor.casefold():
            return _denied(
                "requester cannot approve their own Action",
                required_capability=required,
            )
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


def _validate_tool(tool: Tool) -> None:
    if not isinstance(tool.tool_id, str) or not tool.tool_id.strip():
        raise TypeError("tool.tool_id must be a non-empty string")
    if not callable(getattr(tool, "call", None)):
        raise TypeError("tool must implement call(context, payload)")
    if not hasattr(tool, "required_capabilities"):
        raise TypeError("tool must declare required_capabilities")
    if not hasattr(tool, "allowed_stage_ids"):
        raise TypeError("tool must declare allowed_stage_ids")


def _identity_from_payload(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _denied(reason: str, *, required_capability: Capability) -> PolicyDecision:
    return PolicyDecision(
        allowed=False,
        reason=reason,
        required_capability=required_capability,
    )
