"""Evidence and claim domain contracts."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any, Literal, Mapping, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    field_validator,
    model_validator,
)


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

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    claim_id: str
    artifact_id: str
    claim_type: Literal["fact", "inference", "assumption", "unknown"]
    criticality: Literal["normal", "critical"] = "normal"
    text: str
    evidence_refs: list[str] = Field(default_factory=list)
    required_evidence: StrictBool = False
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    validation_status: str = "pending"

    def model_copy(
        self, *, update: Mapping[str, Any] | None = None, deep: bool = False
    ) -> Self:
        """Copy a claim through full domain-contract validation."""
        values = self.model_dump(mode="python")
        if deep:
            values = deepcopy(values)
        if update:
            values.update(update)
        return type(self).model_validate(values)

    @model_validator(mode="before")
    @classmethod
    def enforce_required_evidence(cls, data: Any) -> Any:
        if isinstance(data, cls) or not isinstance(data, dict):
            return data

        values = dict(data)
        criticality = values.get("criticality", "normal")
        required_evidence = values.get("required_evidence", criticality == "critical")
        if criticality == "critical" and required_evidence is False:
            raise ValueError("critical claims require evidence")
        if required_evidence:
            evidence_refs = values.get("evidence_refs", [])
            if not evidence_refs or any(
                not isinstance(ref, str) or not ref.strip() for ref in evidence_refs
            ):
                raise ValueError("required evidence_refs must be non-empty")
        values["required_evidence"] = required_evidence
        return values

    @field_validator("claim_id", "artifact_id", "text")
    @classmethod
    def reject_empty_required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value

    @field_validator("evidence_refs")
    @classmethod
    def reject_blank_evidence_refs(cls, value: list[str]) -> list[str]:
        if any(not ref.strip() for ref in value):
            raise ValueError("evidence references must not be blank")
        return value
