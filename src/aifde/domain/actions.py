"""Action request domain contract."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Literal, Mapping, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)


class ActionRequest(BaseModel):
    """A request for an external action; it does not grant approval authority."""

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

    def model_copy(
        self, *, update: Mapping[str, Any] | None = None, deep: bool = False
    ) -> Self:
        """Copy an action request through full governance validation."""
        values = self.model_dump(mode="python")
        if deep:
            values = deepcopy(values)
        if update:
            values.update(update)
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
        if not value.strip():
            raise ValueError("must not be empty")
        return value

    @model_validator(mode="after")
    def reject_self_approval(self) -> ActionRequest:
        if self.approval_actor == self.requested_by:
            raise ValueError("requester cannot approve their own action")
        return self
