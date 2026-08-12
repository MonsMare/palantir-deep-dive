"""Action request domain contract."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ActionRequest(BaseModel):
    """A request for an external action; it does not grant approval authority."""

    action_id: str
    action_type: str
    target_id: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    requested_by: str
    idempotency_key: str
    approval_id: str | None = None
