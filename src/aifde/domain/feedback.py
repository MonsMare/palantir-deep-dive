"""Feedback domain contract."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class Feedback(BaseModel):
    """Feedback captured against a specific artifact."""

    feedback_id: str
    artifact_id: str
    feedback_type: str
    value: Any
    source: str
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)
