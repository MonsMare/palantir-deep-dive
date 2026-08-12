"""Artifact domain contract."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any, Mapping, Self
from uuid import uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    computed_field,
    field_validator,
    model_validator,
)


def canonical_json_bytes(value: JsonValue) -> bytes:
    """Serialize JSON content deterministically using strict JSON semantics."""
    try:
        canonical = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("content must contain only finite JSON values") from exc
    return canonical.encode("utf-8")


def content_hash_for(value: JsonValue) -> str:
    """Return the SHA-256 hash of strict canonical JSON content."""
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


class Artifact(BaseModel):
    """A versioned project artifact with traceable evidence dependencies."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    artifact_id: str
    project_id: str
    kind: str
    version: int = Field(default=1, ge=1)
    status: str = "draft"
    owner: str
    content: JsonValue
    depends_on: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @computed_field
    @property
    def content_hash(self) -> str:
        """Derive the hash from current content so it cannot become stale."""
        return content_hash_for(self.content)

    def model_copy(
        self, *, update: Mapping[str, Any] | None = None, deep: bool = False
    ) -> Self:
        """Copy an artifact through validation without permitting a forged hash."""
        if update and "content_hash" in update:
            raise ValueError("content_hash is a derived field and cannot be updated")

        values = self.model_dump(mode="python", exclude={"content_hash"})
        if deep:
            values = deepcopy(values)
        if update:
            values.update(update)
        return type(self).model_validate(values)

    @model_validator(mode="before")
    @classmethod
    def validate_supplied_content_hash(cls, data: Any) -> Any:
        if isinstance(data, cls) or not isinstance(data, dict):
            return data

        values = dict(data)
        if "content" in values:
            try:
                expected_hash = content_hash_for(values["content"])
            except ValueError as exc:
                raise ValueError(str(exc)) from exc

            if "content_hash" in values:
                supplied_hash = values.pop("content_hash")
                if supplied_hash != expected_hash:
                    raise ValueError("content_hash does not match canonical content")
        else:
            values.pop("content_hash", None)
        return values

    @field_validator("artifact_id", "project_id", "kind", "owner")
    @classmethod
    def reject_empty_identity(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value

    @classmethod
    def build(
        cls,
        *,
        project_id: str,
        kind: str,
        content: JsonValue,
        owner: str,
        artifact_id: str | None = None,
        version: int = 1,
        status: str = "draft",
        depends_on: list[str] | None = None,
        evidence_refs: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Artifact:
        """Build an artifact with a deterministic SHA-256 content hash."""
        return cls(
            artifact_id=artifact_id if artifact_id is not None else str(uuid4()),
            project_id=project_id,
            kind=kind,
            version=version,
            status=status,
            owner=owner,
            content=content,
            depends_on=depends_on or [],
            evidence_refs=evidence_refs or [],
            metadata=metadata or {},
        )
