"""Typed, mock-only Action request and outcome contracts."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from math import isfinite
from typing import Any, Literal, Mapping, Self
from uuid import uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)


class _ImmutableList(list[Any]):
    """List-shaped defensive JSON container."""

    def _immutable(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("immutable action value")

    __setitem__ = __delitem__ = append = clear = extend = insert = pop = remove = reverse = sort = _immutable
    __iadd__ = __imul__ = _immutable


class _ImmutableDict(dict[str, Any]):
    """Dict-shaped defensive JSON container."""

    def _immutable(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("immutable action value")

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = _immutable


def _immutable_json(value: Any) -> Any:
    """Validate JSON-like data and recursively remove mutation methods."""

    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("action payload floats must be finite")
        return value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("action payload mapping keys must be strings")
        return _ImmutableDict({key: _immutable_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return _ImmutableList(_immutable_json(item) for item in value)
    raise TypeError("action payload must contain JSON-compatible values")


def _canonical_json_hash(value: Mapping[str, Any]) -> str:
    """Hash parameters independently of input dict order."""

    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise TypeError("action parameters must be JSON-compatible") from exc
    return sha256(encoded).hexdigest()


class ActionRequest(BaseModel):
    """A request for a mock action; caller fields never grant authority."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    action_id: str
    action_type: str
    target_id: str
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    requested_by: str
    idempotency_key: str
    execution_mode: Literal["mock"] = "mock"
    policy_id: str
    policy_version: str
    validation_id: str
    validated_by: str
    validation_status: Literal["pending", "passed", "failed"] = "pending"
    approval_id: str
    approval_actor: str
    approval_role: str
    approval_status: Literal["pending", "approved", "rejected"] = "pending"
    audit_ref: str
    audit_actor: str
    outcome_status: Literal["pending", "succeeded", "failed"] = "pending"

    @property
    def parameters_hash(self) -> str:
        """Return the canonical fingerprint used by idempotency checks."""

        return _canonical_json_hash(self.parameters)

    def with_parameters(self, parameters: Mapping[str, JsonValue]) -> Self:
        """Return a revalidated request with replacement parameters."""

        return self.model_copy(update={"parameters": dict(parameters)}, deep=True)

    def model_copy(
        self, *, update: Mapping[str, Any] | None = None, deep: bool = False
    ) -> Self:
        """Copy an action request through full governance validation."""

        values = self.model_dump(mode="python")
        if deep:
            values = deepcopy(values)
        if update:
            values.update(dict(update))
        return type(self).model_validate(values)

    @field_validator(
        "action_id",
        "action_type",
        "target_id",
        "requested_by",
        "idempotency_key",
        "policy_id",
        "policy_version",
        "validation_id",
        "validated_by",
        "approval_id",
        "approval_actor",
        "approval_role",
        "audit_ref",
        "audit_actor",
    )
    @classmethod
    def reject_blank_identity(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("must not be empty")
        if value != value.strip():
            raise ValueError("must use a canonical identity")
        return value

    @field_validator("parameters", mode="before")
    @classmethod
    def validate_parameters(cls, value: Any) -> dict[str, JsonValue]:
        if not isinstance(value, Mapping):
            raise TypeError("parameters must be a mapping")
        # ``JsonValue`` keeps the public request shape compatible; this local
        # normalization solely proves the values can enter canonical hashing.
        _canonical_json_hash(dict(value))
        return dict(value)

    @model_validator(mode="after")
    def reject_self_approval(self) -> ActionRequest:
        if self.approval_actor == self.requested_by:
            raise ValueError("requester cannot approve their own action")
        return self


class ActionValidation(BaseModel):
    """The deterministic, non-authoritative result of action validation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed: bool
    missing_fields: tuple[str, ...] = ()
    approval_required: bool = True
    policy_reason: str

    @field_validator("missing_fields", mode="before")
    @classmethod
    def normalize_missing_fields(cls, value: Any) -> tuple[str, ...]:
        if isinstance(value, str):
            raise TypeError("missing_fields must be an iterable of identities")
        try:
            fields = tuple(value)
        except TypeError as exc:
            raise TypeError("missing_fields must be an iterable of identities") from exc
        if any(not isinstance(field, str) or not field.strip() for field in fields):
            raise ValueError("missing_fields must contain non-empty identities")
        return fields

    @field_validator("policy_reason")
    @classmethod
    def reject_blank_reason(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("policy_reason must be a non-empty string")
        return value.strip()


class ExternalReceipt(BaseModel):
    """A receipt returned solely by the in-memory mock adapter."""

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    external_ref: str
    status: Literal["succeeded", "failed"]
    retryable: bool
    response_payload: Any = Field(default_factory=_ImmutableDict)

    @field_validator("external_ref")
    @classmethod
    def reject_blank_external_ref(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("external_ref must be a non-empty string")
        return value.strip()

    @field_validator("response_payload", mode="before")
    @classmethod
    def normalize_response_payload(cls, value: Any) -> _ImmutableDict:
        if not isinstance(value, Mapping):
            raise TypeError("response_payload must be a mapping")
        normalized = _immutable_json(value)
        assert isinstance(normalized, _ImmutableDict)
        return normalized

    def model_copy(
        self, *, update: Mapping[str, Any] | None = None, deep: bool = False
    ) -> Self:
        values = self.model_dump(mode="python")
        if deep:
            values = deepcopy(values)
        if update:
            values.update(dict(update))
        return type(self).model_validate(values)


class ActionOutcome(BaseModel):
    """Immutable action outcome persisted by the mock-only broker."""

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    outcome_id: str = Field(default_factory=lambda: str(uuid4()))
    request_id: str
    action_id: str
    actor: str
    action_type: str
    target_id: str
    parameters_hash: str
    status: Literal["succeeded", "failed"]
    retryable: bool
    external_ref: str
    executed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    response_payload: Any = Field(default_factory=_ImmutableDict)

    @property
    def success(self) -> bool:
        """Compatibility boolean for callers that only need terminal success."""

        return self.status == "succeeded"

    @field_validator(
        "outcome_id",
        "request_id",
        "action_id",
        "actor",
        "action_type",
        "target_id",
        "parameters_hash",
        "external_ref",
    )
    @classmethod
    def reject_blank_identity(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("must be a non-empty identity")
        return value.strip()

    @field_validator("parameters_hash")
    @classmethod
    def validate_parameters_hash(cls, value: str) -> str:
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError("parameters_hash must be a SHA-256 hexadecimal digest")
        return value

    @field_validator("executed_at")
    @classmethod
    def require_aware_execution_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("executed_at must be timezone-aware")
        return value

    @field_validator("response_payload", mode="before")
    @classmethod
    def normalize_response_payload(cls, value: Any) -> _ImmutableDict:
        if not isinstance(value, Mapping):
            raise TypeError("response_payload must be a mapping")
        normalized = _immutable_json(value)
        assert isinstance(normalized, _ImmutableDict)
        return normalized

    def model_copy(
        self, *, update: Mapping[str, Any] | None = None, deep: bool = False
    ) -> Self:
        values = self.model_dump(mode="python")
        if deep:
            values = deepcopy(values)
        if update:
            values.update(dict(update))
        return type(self).model_validate(values)


__all__ = [
    "ActionOutcome",
    "ActionRequest",
    "ActionValidation",
    "ExternalReceipt",
]
