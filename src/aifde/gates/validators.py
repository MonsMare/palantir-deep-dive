"""Typed contracts for deterministic gate validators."""

from __future__ import annotations

from hashlib import sha256
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from aifde.domain.artifacts import canonical_json_bytes


class ValidationContext(BaseModel):
    """The immutable inputs a validator used to produce a gate result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stage_run_id: str
    artifact_ids: list[str] = Field(default_factory=list)
    evidence_snapshot_id: str
    evidence_snapshot_hash: str | None = None
    configuration: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("stage_run_id", "evidence_snapshot_id")
    @classmethod
    def reject_blank_identity(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value

    @field_validator("evidence_snapshot_hash")
    @classmethod
    def reject_blank_optional_hash(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be empty")
        return value

    @model_validator(mode="after")
    def validate_artifact_snapshot(self) -> ValidationContext:
        if not self.artifact_ids or any(not artifact_id.strip() for artifact_id in self.artifact_ids):
            raise ValueError("artifact_ids must contain non-empty identities")
        if len(set(self.artifact_ids)) != len(self.artifact_ids):
            raise ValueError("artifact_ids must not contain duplicates")
        return self

    @property
    def configuration_hash(self) -> str:
        """Hash canonical JSON configuration so changes are comparable and auditable."""
        return sha256(canonical_json_bytes(self.configuration)).hexdigest()


class ValidationResult(BaseModel):
    """A validator outcome with the provenance required for invalidation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    violations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    validator_version: str
    input_hashes: dict[str, str] = Field(default_factory=dict)

    @field_validator("validator_version")
    @classmethod
    def reject_blank_validator_version(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value

    @field_validator("input_hashes")
    @classmethod
    def reject_empty_input_hashes(cls, value: dict[str, str]) -> dict[str, str]:
        if not value or any(not key.strip() or not item.strip() for key, item in value.items()):
            raise ValueError("input_hashes must contain non-empty artifact ids and hashes")
        return value


class Validator(Protocol):
    """A deterministic validation boundary used by a gate definition."""

    def validate(self, context: ValidationContext) -> ValidationResult:
        """Evaluate one gate's inputs and return its traceable result."""
