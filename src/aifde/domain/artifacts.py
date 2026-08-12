"""Artifact domain contract."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, JsonValue, field_validator


class Artifact(BaseModel):
    """A versioned project artifact with traceable evidence dependencies."""

    artifact_id: str
    project_id: str
    kind: str
    version: int = Field(default=1, ge=1)
    status: str = "draft"
    owner: str
    content: JsonValue
    depends_on: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    content_hash: str
    metadata: dict[str, Any] = Field(default_factory=dict)

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
        canonical_content = json.dumps(
            content,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        content_hash = hashlib.sha256(canonical_content.encode("utf-8")).hexdigest()
        return cls(
            artifact_id=artifact_id or str(uuid4()),
            project_id=project_id,
            kind=kind,
            version=version,
            status=status,
            owner=owner,
            content=content,
            depends_on=depends_on or [],
            evidence_refs=evidence_refs or [],
            content_hash=content_hash,
            metadata=metadata or {},
        )
