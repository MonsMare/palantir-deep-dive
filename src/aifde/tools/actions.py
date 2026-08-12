"""Mock-only Action Broker behind the Task-4 Tool Gateway."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from aifde.domain.actions import (
    ActionOutcome,
    ActionRequest,
    ActionValidation,
    ExternalReceipt,
)
from aifde.policy.capabilities import (
    ApprovedActionRecord,
    ApprovalVerifier,
    Capability,
    PolicyEngine,
    ToolContext,
)
from aifde.policy.gateway import ToolGateway
from aifde.tools.protocol import ToolResult


class ActionPolicy(BaseModel):
    """A small allowlist policy for one mock Action type."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action_type: str
    required_parameters: tuple[str, ...] = ()
    approval_required: bool = True

    @field_validator("action_type")
    @classmethod
    def reject_blank_action_type(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("action_type must be a non-empty string")
        if value != value.strip():
            raise ValueError("action_type must be canonical")
        return value

    @field_validator("required_parameters", mode="before")
    @classmethod
    def normalize_required_parameters(cls, value: Any) -> tuple[str, ...]:
        if isinstance(value, str):
            raise TypeError("required_parameters must be an iterable of names")
        try:
            names = tuple(value)
        except TypeError as exc:
            raise TypeError("required_parameters must be an iterable of names") from exc
        if any(not isinstance(name, str) or not name.strip() for name in names):
            raise ValueError("required_parameters must contain non-empty names")
        if any(name != name.strip() for name in names):
            raise ValueError("required_parameters must be canonical")
        if len(set(names)) != len(names):
            raise ValueError("required_parameters must not contain duplicates")
        return names


class ActionAuditRecord(BaseModel):
    """One immutable audit record for a broker decision or terminal event."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    audit_id: str = Field(default_factory=lambda: str(uuid4()))
    event: Literal["allow", "deny", "duplicate", "failure", "exception"]
    action_id: str
    request_id: str
    actor: str
    reason: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("audit_id", "action_id", "request_id", "actor", "reason")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("must be a non-empty string")
        return value.strip()

    @field_validator("created_at")
    @classmethod
    def require_aware_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value


class MockActionAdapter:
    """The only adapter supplied by the MVP; it never leaves process memory."""

    def execute(
        self, action_type: str, target_id: str, parameters: dict[str, Any]
    ) -> ExternalReceipt:
        """Produce a deterministic in-memory receipt or simulated retryable failure."""

        if parameters.get("simulate_failure") is True:
            return ExternalReceipt(
                external_ref=f"mock://{action_type}/{target_id}/failed",
                status="failed",
                retryable=True,
                response_payload={
                    "adapter": "mock",
                    "action_type": action_type,
                    "target_id": target_id,
                    "simulated": True,
                },
            )
        return ExternalReceipt(
            external_ref=f"mock://{action_type}/{target_id}/succeeded",
            status="succeeded",
            retryable=False,
            response_payload={
                "adapter": "mock",
                "action_type": action_type,
                "target_id": target_id,
                "simulated": False,
            },
        )


@dataclass(frozen=True)
class _IdempotencyEntry:
    """Private immutable identity snapshot retained for one idempotency key."""

    fingerprint: tuple[str, str, str, str, str]
    outcome: ActionOutcome


class _GatewayMockActionTool:
    """Gateway-only wrapper around the supplied mock adapter."""

    tool_id = "execute_mock_action"
    required_capabilities = frozenset({Capability.EXECUTE})
    allowed_stage_ids = frozenset({"decision.contract"})

    def __init__(self, adapter: MockActionAdapter) -> None:
        self._adapter = adapter

    def call(self, context: ToolContext, payload: dict[str, Any]) -> ToolResult:
        """Execute the adapter only after the gateway's token guard has admitted it."""

        receipt = self._adapter.execute(
            payload["action_type"],
            payload["target_id"],
            deepcopy(payload["parameters"]),
        )
        if not isinstance(receipt, ExternalReceipt):
            raise TypeError("mock adapter must return an ExternalReceipt")
        return ToolResult(
            status=receipt.status,
            payload={
                "external_ref": receipt.external_ref,
                "status": receipt.status,
                "retryable": receipt.retryable,
                "response_payload": receipt.response_payload,
            },
        )


class _GatewayMockActionAuthorizationTool:
    """Gateway-only authorization check that deliberately cannot execute an adapter."""

    tool_id = "authorize_mock_action"
    required_capabilities = frozenset({Capability.EXECUTE})
    allowed_stage_ids = frozenset({"decision.contract"})

    def call(self, _context: ToolContext, _payload: dict[str, Any]) -> ToolResult:
        """Return only after the Task-4 Gateway has checked the protected record."""

        return ToolResult(status="authorized")


class ActionBroker:
    """Validate, authorize, execute, and retain outcomes for mock Actions only.

    The broker owns no production connector.  Before the adapter runs it asks
    the Task-4 ``ToolGateway`` to authorize a trusted Release Owner against a
    protected ``ApprovedActionRecord``.  Request approval/actor fields are
    consistency checks only and can never establish that authority.
    """

    def __init__(
        self,
        *,
        approved_actions: Iterable[ApprovedActionRecord]
        | Mapping[str, ApprovedActionRecord]
        | None = None,
        approval_verifier: ApprovalVerifier | None = None,
        action_policies: Iterable[ActionPolicy] | None = None,
        adapter: MockActionAdapter | None = None,
    ) -> None:
        if approval_verifier is not None and approved_actions is not None:
            raise ValueError("provide approval_verifier or approved_actions, not both")
        policies = (
            (ActionPolicy(action_type="ReplanSprint", required_parameters=("capacity",)),)
            if action_policies is None
            else tuple(action_policies)
        )
        policy_by_type: dict[str, ActionPolicy] = {}
        for policy in policies:
            if not isinstance(policy, ActionPolicy):
                raise TypeError("action_policies must contain ActionPolicy values")
            if policy.action_type in policy_by_type:
                raise ValueError(f"duplicate action policy: {policy.action_type}")
            policy_by_type[policy.action_type] = policy.model_copy(deep=True)

        self._policies = policy_by_type
        self._approval_verifier = approval_verifier or ApprovalVerifier(approved_actions)
        self._adapter = adapter or MockActionAdapter()
        if not isinstance(self._adapter, MockActionAdapter):
            raise TypeError("adapter must be a MockActionAdapter")
        self._gateway = ToolGateway(
            [
                _GatewayMockActionTool(self._adapter),
                _GatewayMockActionAuthorizationTool(),
            ],
            policy=PolicyEngine(stage_ids=["decision.contract"]),
            approval_verifier=self._approval_verifier,
        )
        self._outcomes: dict[str, ActionOutcome] = {}
        self._idempotency: dict[str, _IdempotencyEntry] = {}
        self._audit_records: list[ActionAuditRecord] = []

    @property
    def audit_records(self) -> list[ActionAuditRecord]:
        """Return independently validated audit copies."""

        return [record.model_copy(deep=True) for record in self._audit_records]

    @property
    def gateway_audit_records(self) -> list[Any]:
        """Expose defensive Gateway audit copies for end-to-end audit inspection."""

        return self._gateway.audit_records

    def validate(self, request: ActionRequest) -> ActionValidation:
        """Check only deterministic action/parameter policy facts."""

        if not isinstance(request, ActionRequest):
            raise TypeError("request must be an ActionRequest")
        policy = self._policies.get(request.action_type)
        if policy is None:
            return ActionValidation(
                allowed=False,
                missing_fields=(),
                approval_required=True,
                policy_reason=f"unknown mock Action type: {request.action_type}",
            )
        missing = tuple(
            field
            for field in policy.required_parameters
            if field not in request.parameters or request.parameters[field] is None
        )
        if missing:
            return ActionValidation(
                allowed=False,
                missing_fields=missing,
                approval_required=policy.approval_required,
                policy_reason="required Action parameters are missing",
            )
        return ActionValidation(
            allowed=True,
            missing_fields=(),
            approval_required=policy.approval_required,
            policy_reason="mock Action policy and parameters are valid",
        )

    def execute(self, request: ActionRequest, actor: str) -> ActionOutcome:
        """Execute one approved mock Action or return its idempotent outcome."""

        if not isinstance(request, ActionRequest):
            raise TypeError("request must be an ActionRequest")
        actor = _canonical_actor(actor)
        request_id = str(uuid4())
        validation = self.validate(request)
        if not validation.allowed:
            self._record("deny", request, request_id, actor, validation.policy_reason)
            raise ValueError(validation.policy_reason)
        try:
            record = self._verified_record(request)
            self._validate_request_against_record(request, record)
        except PermissionError as exc:
            self._record("deny", request, request_id, actor, str(exc))
            raise
        payload = {
            "action_id": record.action_id,
            "action_type": request.action_type,
            "target_id": request.target_id,
            "parameters": deepcopy(request.parameters),
            "execution_mode": request.execution_mode,
            "requested_by": request.requested_by,
            "validation_status": request.validation_status,
            "approval_status": request.approval_status,
            "approval_actor": request.approval_actor,
            "approval_role": request.approval_role,
        }
        try:
            context = self._gateway.issue_context(
                actor_id=actor,
                project_id="mock-actions",
                stage_id="decision.contract",
                artifact_ids=(),
                capability=Capability.EXECUTE,
                request_id=request_id,
            )
            self._gateway.call("authorize_mock_action", context, payload)
        except PermissionError as exc:
            self._record("deny", request, request_id, actor, str(exc))
            raise
        except Exception as exc:
            self._record("exception", request, request_id, actor, str(exc))
            raise

        fingerprint = _request_fingerprint(request)
        existing = self._idempotency.get(request.idempotency_key)
        if existing is not None:
            if existing.fingerprint != fingerprint:
                reason = "idempotency key conflict: request does not match the original Action"
                self._record("deny", request, request_id, actor, reason)
                raise ValueError(reason)
            if existing.outcome.actor != actor:
                reason = "idempotent outcome is restricted to the original execution actor"
                self._record("deny", request, request_id, actor, reason)
                raise PermissionError(reason)
            self._record("duplicate", request, request_id, actor, "idempotent outcome returned")
            return existing.outcome.model_copy(deep=True)

        try:
            result = self._gateway.call("execute_mock_action", context, payload)
        except PermissionError as exc:
            self._record("deny", request, request_id, actor, str(exc))
            raise
        except Exception as exc:
            self._record("exception", request, request_id, actor, str(exc))
            raise

        receipt = _receipt_from_tool_result(result)
        outcome = ActionOutcome(
            request_id=request_id,
            action_id=request.action_id,
            actor=actor,
            action_type=request.action_type,
            target_id=request.target_id,
            parameters_hash=request.parameters_hash,
            status=receipt.status,
            retryable=receipt.retryable,
            external_ref=receipt.external_ref,
            executed_at=datetime.now(timezone.utc),
            response_payload=receipt.response_payload,
        )
        stored = outcome.model_copy(deep=True)
        self._outcomes[request.action_id] = stored
        self._idempotency[request.idempotency_key] = _IdempotencyEntry(
            fingerprint=fingerprint,
            outcome=stored,
        )
        self._record("allow", request, request_id, actor, "mock Action executed")
        if outcome.status == "failed":
            self._record("failure", request, request_id, actor, "mock Action failed")
        return stored.model_copy(deep=True)

    def get_outcome(self, action_id: str) -> ActionOutcome:
        """Return an outcome copy; absence is deliberately explicit."""

        if not isinstance(action_id, str) or not action_id.strip():
            raise ValueError("action_id must be a non-empty string")
        try:
            return self._outcomes[action_id].model_copy(deep=True)
        except KeyError as exc:
            raise KeyError(f"no ActionOutcome recorded for {action_id}") from exc

    def _verified_record(self, request: ActionRequest) -> ApprovedActionRecord:
        record = self._approval_verifier.verify(request.action_id)
        if record is None:
            raise PermissionError("an approved Action approval record is required")
        if not isinstance(record, ApprovedActionRecord):
            raise PermissionError("approval verifier returned an invalid record")
        return record

    def _validate_request_against_record(
        self, request: ActionRequest, record: ApprovedActionRecord
    ) -> None:
        expected = {
            "action_type": record.action_type,
            "execution_mode": record.execution_mode,
            "requested_by": record.requested_by,
            "validation_status": record.validation_status,
            "approval_id": record.approval_id,
            "approval_actor": record.approval_actor,
            "approval_role": record.approval_role.value,
            "approval_status": record.approval_status,
        }
        for field, value in expected.items():
            if getattr(request, field) != value:
                raise PermissionError(
                    f"Action {field} does not match its protected approval record"
                )

    def _record(
        self,
        event: Literal["allow", "deny", "duplicate", "failure", "exception"],
        request: ActionRequest,
        request_id: str,
        actor: str,
        reason: str,
    ) -> None:
        self._audit_records.append(
            ActionAuditRecord(
                event=event,
                action_id=request.action_id,
                request_id=request_id,
                actor=actor,
                reason=reason,
            )
        )


def _canonical_actor(actor: str) -> str:
    if not isinstance(actor, str) or not actor.strip():
        raise ValueError("actor must be a non-empty identity")
    if actor != actor.strip():
        raise ValueError("actor must use a canonical identity")
    return actor


def _request_fingerprint(request: ActionRequest) -> tuple[str, str, str, str, str]:
    return (
        request.action_id,
        request.action_type,
        request.target_id,
        request.parameters_hash,
        request.requested_by,
    )


def _receipt_from_tool_result(result: ToolResult) -> ExternalReceipt:
    payload = result.payload
    return ExternalReceipt(
        external_ref=payload["external_ref"],
        status=payload["status"],
        retryable=payload["retryable"],
        response_payload=payload["response_payload"],
    )


__all__ = [
    "ActionAuditRecord",
    "ActionBroker",
    "ActionPolicy",
    "MockActionAdapter",
]
