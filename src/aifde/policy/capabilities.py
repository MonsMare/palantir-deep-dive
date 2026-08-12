"""Capability contracts and the default authorization policy."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, Self
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Capability(str, Enum):
    """The only capabilities a tool invocation may carry."""

    READ = "read"
    PROPOSE = "propose"
    VALIDATE = "validate"
    APPROVE = "approve"
    EXECUTE = "execute"


class ToolContext(BaseModel):
    """Auditable, request-scoped context supplied to every tool call."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    actor_id: str
    project_id: str
    stage_id: str
    artifact_ids: list[str] = Field(default_factory=list)
    capability: Capability
    request_id: str

    @field_validator("actor_id", "project_id", "stage_id", "request_id")
    @classmethod
    def reject_blank_identity(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("must be a non-empty identity")
        return value.strip()

    @field_validator("artifact_ids")
    @classmethod
    def reject_blank_artifact_ids(cls, value: list[str]) -> list[str]:
        if any(not isinstance(item, str) or not item.strip() for item in value):
            raise ValueError("artifact_ids must contain non-empty identities")
        return [item.strip() for item in value]

    def with_capability(self, capability: Capability) -> ToolContext:
        """Return a revalidated copy carrying one requested capability."""
        if not isinstance(capability, Capability):
            try:
                capability = Capability(capability)
            except (TypeError, ValueError) as exc:
                raise ValueError("capability must be a Capability") from exc
        values = self.model_dump(mode="python")
        values["capability"] = capability
        return type(self).model_validate(values)

    def model_copy(
        self, *, update: Mapping[str, Any] | None = None, deep: bool = False
    ) -> Self:
        """Copy through full validation so callers cannot forge context fields."""
        values = self.model_dump(mode="python")
        if deep:
            from copy import deepcopy

            values = deepcopy(values)
        if update:
            values.update(update)
        return type(self).model_validate(values)


class PolicyDecision(BaseModel):
    """Typed authorization result produced before a tool is invoked."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed: bool
    reason: str
    required_capability: Capability | None = None
    audit_id: str = Field(default_factory=lambda: str(uuid4()))

    @field_validator("reason", "audit_id")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value


class AuditRecord(BaseModel):
    """Immutable audit entry for one attempted gateway invocation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    audit_id: str
    request_id: str
    tool_id: str
    actor_id: str
    project_id: str
    stage_id: str
    capability: Capability
    allowed: bool
    reason: str
    required_capability: Capability | None = None
    outcome_status: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator(
        "audit_id",
        "request_id",
        "tool_id",
        "actor_id",
        "project_id",
        "stage_id",
        "reason",
    )
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value


class PolicyEngine:
    """Authorize tools using least privilege and actor role defaults.

    The current domain contracts identify actors by stable IDs rather than by
    a separate role field.  The conventional IDs used by the platform are
    therefore recognized as ``<role>`` or ``<role>-<suffix>``.  Unknown actors
    are denied by default; callers may provide explicit actor capabilities for
    integrations that use a different identity format.
    """

    DEFAULT_PERMISSIONS: Mapping[str, frozenset[Capability]] = {
        "builder": frozenset(
            {Capability.READ, Capability.PROPOSE, Capability.VALIDATE}
        ),
        "challenger": frozenset({Capability.READ, Capability.VALIDATE}),
        "deterministic-verifier": frozenset(
            {Capability.READ, Capability.VALIDATE}
        ),
        "domain-owner": frozenset({Capability.READ, Capability.APPROVE}),
        "release-owner": frozenset(
            {Capability.READ, Capability.APPROVE, Capability.EXECUTE}
        ),
    }

    def __init__(
        self,
        actor_capabilities: Mapping[str, Iterable[Capability]] | None = None,
    ) -> None:
        self._actor_capabilities: dict[str, frozenset[Capability]] = {}
        for actor_id, capabilities in (actor_capabilities or {}).items():
            self._actor_capabilities[_canonical_identity(actor_id, "actor_id")] = (
                _normalize_capabilities(capabilities)
            )

    def authorize(self, context: ToolContext, tool: Any) -> PolicyDecision:
        """Return a decision without invoking the tool or touching a registry."""
        if not isinstance(context, ToolContext):
            raise TypeError("context must be a ToolContext")
        _validate_tool_shape(tool)

        required = _normalize_capabilities(tool.required_capabilities)
        required_capability = _first_capability(required)
        if not required:
            return _denied(
                "tool must declare at least one required capability",
                required_capability=None,
            )

        allowed_stages = _normalize_stage_ids(tool.allowed_stage_ids)
        if context.stage_id not in allowed_stages:
            return _denied(
                f"tool {tool.tool_id} is not allowed in stage {context.stage_id}",
                required_capability=required_capability,
            )

        actor_capabilities = self.capabilities_for(context.actor_id)
        if context.capability not in actor_capabilities:
            return _denied(
                f"actor {context.actor_id} is not allowed capability "
                f"{context.capability.value}",
                required_capability=required_capability,
            )

        if context.capability not in required:
            return _denied(
                f"tool {tool.tool_id} requires one of "
                f"{', '.join(capability.value for capability in sorted(required, key=lambda item: item.value))}",
                required_capability=required_capability,
            )

        return PolicyDecision(
            allowed=True,
            reason="capability and stage policy allowed the tool call",
            required_capability=context.capability,
        )

    def capabilities_for(self, actor_id: str) -> frozenset[Capability]:
        """Return an actor's capabilities; unknown identities get none."""
        actor_id = _canonical_identity(actor_id, "actor_id")
        explicit = self._actor_capabilities.get(actor_id)
        if explicit is not None:
            return explicit
        role = self.role_for(actor_id)
        if role is None:
            return frozenset()
        return self.DEFAULT_PERMISSIONS[role]

    def role_for(self, actor_id: str) -> str | None:
        """Resolve a conventional actor ID to a default platform role."""
        actor_id = _canonical_identity(actor_id, "actor_id")
        normalized = _normalize_role_identity(actor_id)
        for role in sorted(self.DEFAULT_PERMISSIONS, key=len, reverse=True):
            if normalized == role or normalized.startswith(role + "-"):
                return role
        return None


def _validate_tool_shape(tool: Any) -> None:
    if tool is None:
        raise TypeError("tool must implement the Tool protocol")
    for field in ("tool_id", "required_capabilities", "allowed_stage_ids"):
        if not hasattr(tool, field):
            raise TypeError(f"tool must declare {field}")
    if not isinstance(tool.tool_id, str) or not tool.tool_id.strip():
        raise TypeError("tool.tool_id must be a non-empty string")
    if not callable(getattr(tool, "call", None)):
        raise TypeError("tool must implement call(context, payload)")


def _normalize_capabilities(
    values: Capability | str | Iterable[Capability | str],
) -> frozenset[Capability]:
    if isinstance(values, (Capability, str)):
        values = [values]
    try:
        normalized = {value if isinstance(value, Capability) else Capability(value) for value in values}
    except (TypeError, ValueError) as exc:
        raise TypeError("capabilities must contain Capability values") from exc
    return frozenset(normalized)


def _normalize_stage_ids(values: Iterable[str] | str) -> frozenset[str]:
    if isinstance(values, str):
        values = [values]
    try:
        normalized = frozenset(_canonical_identity(value, "allowed_stage_id") for value in values)
    except TypeError as exc:
        raise TypeError("allowed_stage_ids must be iterable") from exc
    return normalized


def _first_capability(values: frozenset[Capability]) -> Capability | None:
    return min(values, key=lambda item: item.value) if values else None


def _denied(reason: str, *, required_capability: Capability | None) -> PolicyDecision:
    return PolicyDecision(
        allowed=False,
        reason=reason,
        required_capability=required_capability,
    )


def _canonical_identity(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty identity")
    return value.strip()


def _normalize_role_identity(value: str) -> str:
    return "-".join(value.casefold().replace("_", "-").split())
