"""Capability contracts, trusted identities, and policy snapshots.

The context carried by a request is deliberately only a request *claim*.  A
``PolicyEngine`` issues the trusted binding used by the gateway; a caller that
constructs or edits a context directly cannot turn that claim into authority.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, ClassVar, Self
from uuid import uuid4
import weakref

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator


class Capability(str, Enum):
    """The only capabilities a tool invocation may carry."""

    READ = "read"
    PROPOSE = "propose"
    VALIDATE = "validate"
    APPROVE = "approve"
    EXECUTE = "execute"


class ActorRole(str, Enum):
    """Platform roles resolved only by the trusted actor directory."""

    BUILDER = "builder"
    CHALLENGER = "challenger"
    DETERMINISTIC_VERIFIER = "deterministic-verifier"
    DOMAIN_OWNER = "domain-owner"
    RELEASE_OWNER = "release-owner"


# These are the canonical stage IDs defined by the Builder lifecycle.  A tool
# declaration may only name a stage from this registry; callers cannot create a
# new authorization scope by putting an arbitrary string in an allowlist.
KNOWN_STAGE_IDS = frozenset(
    {
        "project.charter",
        "decision.contract",
        "workflow.observation",
        "requirements.distill",
        "solution.design",
        "data.registration",
        "data.product",
        "ontology.design",
        "model.training",
        "decision.optimization",
        "application.delivery",
        "operations.feedback",
    }
)


_DEFAULT_PERMISSIONS: Mapping[str, frozenset[Capability]] = MappingProxyType(
    {
        ActorRole.BUILDER.value: frozenset(
            {Capability.READ, Capability.PROPOSE, Capability.VALIDATE}
        ),
        ActorRole.CHALLENGER.value: frozenset(
            {Capability.READ, Capability.VALIDATE}
        ),
        ActorRole.DETERMINISTIC_VERIFIER.value: frozenset(
            {Capability.READ, Capability.VALIDATE}
        ),
        ActorRole.DOMAIN_OWNER.value: frozenset(
            {Capability.READ, Capability.APPROVE}
        ),
        ActorRole.RELEASE_OWNER.value: frozenset(
            {Capability.READ, Capability.APPROVE, Capability.EXECUTE}
        ),
    }
)

_DEFAULT_ACTOR_ROLES: Mapping[str, ActorRole] = MappingProxyType(
    {
        # Role names are explicit identities too.  The suffixed identities are
        # the fixtures used by the local platform tests.  No prefix matching
        # is performed, so e.g. ``release-owner-attacker`` is unknown.
        "builder": ActorRole.BUILDER,
        "builder-1": ActorRole.BUILDER,
        "challenger": ActorRole.CHALLENGER,
        "challenger-1": ActorRole.CHALLENGER,
        "deterministic-verifier": ActorRole.DETERMINISTIC_VERIFIER,
        "deterministic-verifier-1": ActorRole.DETERMINISTIC_VERIFIER,
        "domain-owner": ActorRole.DOMAIN_OWNER,
        "domain-owner-1": ActorRole.DOMAIN_OWNER,
        "release-owner": ActorRole.RELEASE_OWNER,
        "release-owner-1": ActorRole.RELEASE_OWNER,
    }
)


def _nonblank(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty identity")
    return value


def _canonical_identity(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty identity")
    if value != value.strip():
        raise ValueError(f"{name} must use a canonical identity")
    return value


def _context_fingerprint(context: ToolContext) -> tuple[Any, ...]:
    return (
        context.actor_id,
        context.project_id,
        context.stage_id,
        context.artifact_ids,
        context.capability,
        context.request_id,
    )


class _ContextAuthority:
    """Private issuer-side registry for immutable context claims."""

    __slots__ = ("_issued",)

    def __init__(self) -> None:
        self._issued: dict[int, tuple[weakref.ReferenceType[ToolContext], tuple[Any, ...]]] = {}

    def bind(self, context: ToolContext) -> None:
        self._issued[id(context)] = (weakref.ref(context), _context_fingerprint(context))

    def verify(self, context: ToolContext) -> bool:
        entry = self._issued.get(id(context))
        return bool(
            entry is not None
            and entry[0]() is context
            and entry[1] == _context_fingerprint(context)
        )


class ActorBinding(BaseModel):
    """An immutable actor-to-role/capability binding owned by the platform."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    actor_id: str
    role: ActorRole | None = None
    capabilities: frozenset[Capability] | None = None

    @field_validator("actor_id")
    @classmethod
    def reject_blank_actor(cls, value: str) -> str:
        return _canonical_identity(value, "actor_id")

    @field_validator("capabilities", mode="before")
    @classmethod
    def normalize_capabilities(
        cls, value: Iterable[Capability | str] | None
    ) -> frozenset[Capability] | None:
        if value is None:
            return None
        return _normalize_capabilities(value)


class ToolContext(BaseModel):
    """An immutable request context with a private policy-issued binding."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        arbitrary_types_allowed=True,
    )

    actor_id: str
    project_id: str
    stage_id: str
    artifact_ids: tuple[str, ...] = Field(default_factory=tuple)
    capability: Capability
    request_id: str

    _authority: _ContextAuthority | None = PrivateAttr(default=None)

    @field_validator("actor_id", "project_id", "stage_id", "request_id")
    @classmethod
    def reject_blank_identity(cls, value: str, info: Any) -> str:
        return _nonblank(value, info.field_name)

    @field_validator("artifact_ids", mode="before")
    @classmethod
    def normalize_artifact_ids(cls, value: Iterable[str]) -> tuple[str, ...]:
        if isinstance(value, str):
            raise TypeError("artifact_ids must be an iterable of identities")
        try:
            values = tuple(value)
        except TypeError as exc:
            raise TypeError("artifact_ids must be an iterable of identities") from exc
        if any(not isinstance(item, str) or not item.strip() for item in values):
            raise ValueError("artifact_ids must contain non-empty identities")
        if any(item != item.strip() for item in values):
            raise ValueError("artifact_ids must use canonical identities")
        return values

    @classmethod
    def _trusted(
        cls, values: Mapping[str, Any], authority: _ContextAuthority
    ) -> ToolContext:
        context = cls.model_validate(dict(values))
        object.__setattr__(context, "_authority", authority)
        authority.bind(context)
        return context

    def _is_trusted(self, authority: _ContextAuthority) -> bool:
        return self._authority is authority and authority.verify(self)

    def with_capability(self, capability: Capability) -> ToolContext:
        """Request a capability; the gateway still re-authorizes the actor."""

        if not isinstance(capability, Capability):
            try:
                capability = Capability(capability)
            except (TypeError, ValueError) as exc:
                raise ValueError("capability must be a Capability") from exc
        return self.model_copy(update={"capability": capability})

    def model_copy(
        self, *, update: Mapping[str, Any] | None = None, deep: bool = False
    ) -> Self:
        """Copy with validation and drop authority when identity scope changes.

        Pydantic's default ``model_copy(update=...)`` intentionally skips
        validation.  More importantly, it would make a caller-supplied actor
        look just as authoritative as a platform-issued actor.  Capability-only
        requests retain the policy binding and are checked again by the policy;
        any other update becomes an untrusted context and is denied by the
        gateway.
        """

        values = self.model_dump(mode="python")
        if deep:
            from copy import deepcopy

            values = deepcopy(values)
        changed = set(update or {})
        if update:
            values.update(dict(update))
        copied = type(self).model_validate(values)
        if (
            self._authority is not None
            and self._authority.verify(self)
            and changed <= {"capability"}
        ):
            object.__setattr__(copied, "_authority", self._authority)
            self._authority.bind(copied)
        return copied


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


class ApprovedActionRecord(BaseModel):
    """Protected Task-4 approval record consumed by the future ActionBroker."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action_id: str
    action_type: str
    execution_mode: str
    requested_by: str
    validation_status: str
    approval_id: str
    approval_actor: str
    approval_role: ActorRole
    approval_status: str

    @field_validator(
        "action_id",
        "action_type",
        "execution_mode",
        "requested_by",
        "validation_status",
        "approval_id",
        "approval_actor",
        "approval_status",
    )
    @classmethod
    def reject_blank_action_fields(cls, value: str, info: Any) -> str:
        return _nonblank(value, info.field_name)

    @field_validator("execution_mode")
    @classmethod
    def only_mock_execution(cls, value: str) -> str:
        if value != "mock":
            raise ValueError("only mock Actions may be registered")
        return value

    def model_copy(
        self, *, update: Mapping[str, Any] | None = None, deep: bool = False
    ) -> Self:
        values = self.model_dump(mode="python")
        if deep:
            from copy import deepcopy

            values = deepcopy(values)
        if update:
            values.update(dict(update))
        return type(self).model_validate(values)


class ApprovalVerifier:
    """A snapshot-backed approval verifier for Task 5's future broker.

    The gateway accepts this typed interface instead of trusting approval
    fields in an invocation payload.  Records are copied at construction and
    returned as fresh validated copies.
    """

    def __init__(
        self,
        records: Iterable[ApprovedActionRecord]
        | Mapping[str, ApprovedActionRecord]
        | None = None,
    ) -> None:
        source = records.values() if isinstance(records, Mapping) else (records or ())
        snapshot: dict[str, ApprovedActionRecord] = {}
        for record in source:
            if not isinstance(record, ApprovedActionRecord):
                raise TypeError("approval records must be ApprovedActionRecord values")
            if record.action_id in snapshot:
                raise ValueError(f"duplicate approval action_id: {record.action_id}")
            snapshot[record.action_id] = record.model_copy(deep=True)
        self._records: Mapping[str, ApprovedActionRecord] = MappingProxyType(snapshot)

    def get(self, action_id: str) -> ApprovedActionRecord | None:
        record = self._records.get(action_id)
        return None if record is None else record.model_copy(deep=True)

    def verify(self, action_id: str) -> ApprovedActionRecord | None:
        """Alias suitable for a future ActionBroker adapter."""

        return self.get(action_id)


class PolicyEngine:
    """Authorize tools from immutable actor, permission, and stage snapshots."""

    # Public compatibility constants are immutable mappings.  The constructor
    # uses private module constants so reassigning this attribute cannot alter
    # either an existing or a newly-created platform policy.
    DEFAULT_PERMISSIONS: ClassVar[Mapping[str, frozenset[Capability]]] = (
        _DEFAULT_PERMISSIONS
    )
    DEFAULT_ACTOR_ROLES: ClassVar[Mapping[str, ActorRole]] = _DEFAULT_ACTOR_ROLES
    KNOWN_STAGE_IDS: ClassVar[frozenset[str]] = KNOWN_STAGE_IDS

    def __init__(
        self,
        actor_capabilities: Mapping[str, Iterable[Capability | str]] | None = None,
        *,
        actor_bindings: Mapping[
            str, ActorBinding | ActorRole | str | Mapping[str, Any]
        ]
        | None = None,
        actor_roles: Mapping[str, ActorRole | str] | None = None,
        stage_ids: Iterable[str] | None = None,
    ) -> None:
        self._authority = _ContextAuthority()
        self._version = 1
        self._permissions: Mapping[str, frozenset[Capability]] = MappingProxyType(
            {role: frozenset(capabilities) for role, capabilities in _DEFAULT_PERMISSIONS.items()}
        )
        self._stage_ids = (
            frozenset(KNOWN_STAGE_IDS) if stage_ids is None else frozenset(stage_ids)
        )
        if not self._stage_ids or any(
            _canonical_stage_id(stage_id, KNOWN_STAGE_IDS) != stage_id
            for stage_id in self._stage_ids
        ):
            raise ValueError("stage_ids must contain known canonical stage IDs")

        bindings: dict[str, ActorBinding] = {
            actor_id: ActorBinding(actor_id=actor_id, role=role)
            for actor_id, role in _DEFAULT_ACTOR_ROLES.items()
        }
        for actor_id, role in (actor_roles or {}).items():
            _canonical_identity(actor_id, "actor_id")
            bindings[actor_id] = ActorBinding(
                actor_id=actor_id,
                role=_coerce_role(role),
            )
        for actor_id, value in (actor_bindings or {}).items():
            _canonical_identity(actor_id, "actor_id")
            bindings[actor_id] = _coerce_binding(actor_id, value)
        for actor_id, capabilities in (actor_capabilities or {}).items():
            _canonical_identity(actor_id, "actor_id")
            bindings[actor_id] = ActorBinding(
                actor_id=actor_id,
                capabilities=_normalize_capabilities(capabilities),
            )
        self._actor_bindings: Mapping[str, ActorBinding] = MappingProxyType(bindings)

    @classmethod
    def _from_snapshot(
        cls,
        *,
        permissions: Mapping[str, frozenset[Capability]],
        actor_bindings: Mapping[str, ActorBinding],
        stage_ids: frozenset[str],
        version: int = 1,
    ) -> PolicyEngine:
        policy = object.__new__(cls)
        policy._authority = _ContextAuthority()
        policy._version = version
        policy._permissions = MappingProxyType(
            {role: frozenset(capabilities) for role, capabilities in permissions.items()}
        )
        policy._actor_bindings = MappingProxyType(dict(actor_bindings))
        policy._stage_ids = frozenset(stage_ids)
        return policy

    def snapshot(self) -> PolicyEngine:
        """Return an isolated policy snapshot for a registered gateway."""

        return type(self)._from_snapshot(
            permissions=self._permissions,
            actor_bindings=self._actor_bindings,
            stage_ids=self._stage_ids,
            version=self._version,
        )

    @property
    def policy_version(self) -> int:
        return self._version

    @property
    def known_stage_ids(self) -> frozenset[str]:
        return self._stage_ids

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
        """Issue a context only for a precisely registered actor and stage."""

        if self._binding_for(actor_id) is None:
            raise PermissionError(f"unknown actor: {actor_id}")
        if stage_id not in self._stage_ids:
            raise PermissionError(f"unknown stage: {stage_id}")
        return ToolContext._trusted(
            {
                "actor_id": actor_id,
                "project_id": project_id,
                "stage_id": stage_id,
                "artifact_ids": tuple(artifact_ids),
                "capability": capability,
                "request_id": request_id,
            },
            self._authority,
        )

    def authorize(self, context: ToolContext, tool: Any) -> PolicyDecision:
        """Authorize a trusted context against a validated tool declaration."""

        if not isinstance(context, ToolContext):
            raise TypeError("context must be a ToolContext")
        if not context._is_trusted(self._authority):
            return _denied("context was not issued by the trusted policy", None)

        _validate_tool_shape(tool)
        required = _normalize_capabilities(tool.required_capabilities)
        required_capability = _first_capability(required)
        if not required:
            return _denied(
                "tool must declare at least one required capability",
                required_capability,
            )

        if context.stage_id not in self._stage_ids:
            return _denied(
                f"unknown stage: {context.stage_id}",
                required_capability,
            )
        allowed_stages = _normalize_stage_ids(tool.allowed_stage_ids, self._stage_ids)
        if context.stage_id not in allowed_stages:
            return _denied(
                f"tool {tool.tool_id} is not allowed in stage {context.stage_id}",
                required_capability,
            )

        binding = self._binding_for(context.actor_id)
        if binding is None:
            return _denied(f"unknown actor: {context.actor_id}", required_capability)
        actor_capabilities = self._capabilities_for(binding)
        if context.capability not in actor_capabilities:
            return _denied(
                f"actor {context.actor_id} is not allowed capability "
                f"{context.capability.value}",
                required_capability,
            )
        if context.capability not in required:
            return _denied(
                f"tool {tool.tool_id} requires one of "
                f"{', '.join(capability.value for capability in sorted(required, key=lambda item: item.value))}",
                required_capability,
            )
        return PolicyDecision(
            allowed=True,
            reason="capability and stage policy allowed the tool call",
            required_capability=context.capability,
        )

    def capabilities_for(self, actor_id: str) -> frozenset[Capability]:
        binding = self._binding_for(actor_id)
        return frozenset() if binding is None else self._capabilities_for(binding)

    def role_for(self, actor_id: str) -> str | None:
        binding = self._binding_for(actor_id)
        return None if binding is None or binding.role is None else binding.role.value

    def actor_binding(self, actor_id: str) -> ActorBinding | None:
        binding = self._binding_for(actor_id)
        return None if binding is None else binding.model_copy(deep=True)

    def with_actor_role(
        self,
        actor_id: str,
        role: ActorRole | str,
    ) -> PolicyEngine:
        """Return a new policy snapshot with one explicit actor-role binding."""

        actor_id = _canonical_identity(actor_id, "actor_id")
        bindings = dict(self._actor_bindings)
        bindings[actor_id] = ActorBinding(
            actor_id=actor_id,
            role=_coerce_role(role),
        )
        return type(self)._from_snapshot(
            permissions=self._permissions,
            actor_bindings=bindings,
            stage_ids=self._stage_ids,
            version=self._version + 1,
        )

    def with_actor_capabilities(
        self,
        actor_id: str,
        capabilities: Iterable[Capability | str],
    ) -> PolicyEngine:
        """Return a new policy snapshot with explicit actor capabilities."""

        actor_id = _canonical_identity(actor_id, "actor_id")
        bindings = dict(self._actor_bindings)
        bindings[actor_id] = ActorBinding(
            actor_id=actor_id,
            capabilities=_normalize_capabilities(capabilities),
        )
        return type(self)._from_snapshot(
            permissions=self._permissions,
            actor_bindings=bindings,
            stage_ids=self._stage_ids,
            version=self._version + 1,
        )

    def _binding_for(self, actor_id: str) -> ActorBinding | None:
        if not isinstance(actor_id, str) or not actor_id.strip():
            return None
        return self._actor_bindings.get(actor_id)

    def _capabilities_for(self, binding: ActorBinding) -> frozenset[Capability]:
        if binding.capabilities is not None:
            return binding.capabilities
        if binding.role is None:
            return frozenset()
        return self._permissions[binding.role.value]


def _coerce_role(value: ActorRole | str) -> ActorRole:
    try:
        return value if isinstance(value, ActorRole) else ActorRole(value)
    except (TypeError, ValueError) as exc:
        raise TypeError("actor role must be a registered ActorRole") from exc


def _coerce_binding(
    actor_id: str,
    value: ActorBinding | ActorRole | str | Mapping[str, Any],
) -> ActorBinding:
    if isinstance(value, ActorBinding):
        if value.actor_id != actor_id:
            raise ValueError("actor binding key must match actor_id")
        return value
    if isinstance(value, (ActorRole, str)):
        return ActorBinding(actor_id=actor_id, role=_coerce_role(value))
    if isinstance(value, Mapping):
        return ActorBinding.model_validate({"actor_id": actor_id, **dict(value)})
    raise TypeError("actor binding must be an ActorBinding or ActorRole")


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
        normalized = {
            value if isinstance(value, Capability) else Capability(value)
            for value in values
        }
    except (TypeError, ValueError) as exc:
        raise TypeError("capabilities must contain Capability values") from exc
    return frozenset(normalized)


def _canonical_stage_id(value: str, known_stages: Iterable[str]) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("stage IDs must be non-blank canonical strings")
    if value not in known_stages:
        raise ValueError(f"unknown stage ID: {value}")
    return value


def _normalize_stage_ids(
    values: Iterable[str] | str,
    known_stages: Iterable[str] = KNOWN_STAGE_IDS,
) -> frozenset[str]:
    if isinstance(values, str):
        values = [values]
    try:
        normalized = frozenset(
            _canonical_stage_id(value, known_stages) for value in values
        )
    except TypeError as exc:
        raise TypeError("allowed_stage_ids must be iterable") from exc
    return normalized


def _first_capability(values: frozenset[Capability]) -> Capability | None:
    return min(values, key=lambda item: item.value) if values else None


def _denied(
    reason: str,
    required_capability: Capability | None,
) -> PolicyDecision:
    return PolicyDecision(
        allowed=False,
        reason=reason,
        required_capability=required_capability,
    )


__all__ = [
    "ActorBinding",
    "ActorRole",
    "ApprovedActionRecord",
    "ApprovalVerifier",
    "AuditRecord",
    "Capability",
    "KNOWN_STAGE_IDS",
    "PolicyDecision",
    "PolicyEngine",
    "ToolContext",
]
