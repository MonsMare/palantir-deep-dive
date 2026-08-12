"""Evidence and claim domain contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class Evidence(BaseModel):
    """Captured source material that supports one or more claims."""

    evidence_id: str
    source_uri: str
    locator: str
    content_hash: str
    captured_at: datetime
    classification: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class Claim(BaseModel):
    """A stated fact, inference, assumption, or explicitly unknown assertion."""

    claim_id: str
    artifact_id: str
    claim_type: Literal["fact", "inference", "assumption", "unknown"]
    text: str
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    validation_status: str = "pending"

    @field_validator("claim_id", "artifact_id", "text")
    @classmethod
    def reject_empty_required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value
