"""Typed contracts for deterministic gate validators."""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field


class ValidationContext(BaseModel):
    """The immutable inputs a validator used to produce a gate result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stage_run_id: str
    artifact_ids: list[str] = Field(default_factory=list)
    evidence_snapshot_id: str
    configuration: dict[str, Any] = Field(default_factory=dict)


class ValidationResult(BaseModel):
    """A validator outcome with the provenance required for invalidation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    violations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    validator_version: str
    input_hashes: dict[str, str] = Field(default_factory=dict)


class Validator(Protocol):
    """A deterministic validation boundary used by a gate definition."""

    def validate(self, context: ValidationContext) -> ValidationResult:
        """Evaluate one gate's inputs and return its traceable result."""
