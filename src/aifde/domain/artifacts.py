"""Artifact domain contract."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import re
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


_SEMANTIC_VERSION_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_semantic_version(version: str | int) -> str:
    """Normalize legacy integer majors to the strict semantic version format."""
    if isinstance(version, int) and not isinstance(version, bool):
        if version < 0:
            raise ValueError("version major must be non-negative")
        version = f"{version}.0.0"
    if not isinstance(version, str):
        raise ValueError("version must be a semantic version string")
    if not _SEMANTIC_VERSION_PATTERN.fullmatch(version):
        raise ValueError("version must be MAJOR.MINOR.PATCH without leading zeroes")
    return version


def semantic_version_key(version: str) -> tuple[int, int, int]:
    """Return the strict three-part semantic version ordering key."""
    normalize_semantic_version(version)
    return tuple(int(part) for part in version.split("."))  # type: ignore[return-value]


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
    version: str = "1.0.0"
    status: str = "draft"
    owner: str
    content: JsonValue
    depends_on: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    parent_artifact_ids: list[str] = Field(default_factory=list)
    producer: str | None = None
    created_at: datetime = Field(default_factory=_utc_now)
    validation_results: list[JsonValue] = Field(default_factory=list)

    @computed_field
    @property
    def content_hash(self) -> str:
        """Derive the hash from current content so it cannot become stale."""
        return content_hash_for(self.content)

    def __eq__(self, other: object) -> bool:
        """Compare legacy SQLite records without treating their synthesized time as data."""
        if not isinstance(other, Artifact):
            return NotImplemented

        comparable_fields = {"content_hash", "created_at"}
        left = self.model_dump(mode="python", exclude=comparable_fields)
        right = other.model_dump(mode="python", exclude=comparable_fields)
        if left != right:
            return False

        left_has_explicit_time = "created_at" in self.__pydantic_fields_set__
        right_has_explicit_time = "created_at" in other.__pydantic_fields_set__
        if left_has_explicit_time and right_has_explicit_time:
            return self.created_at == other.created_at
        return True

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

    @field_validator("parent_artifact_ids")
    @classmethod
    def reject_blank_parent_artifact_ids(cls, value: list[str]) -> list[str]:
        if any(not isinstance(item, str) or not item.strip() for item in value):
            raise ValueError("parent_artifact_ids must contain non-empty strings")
        return list(value)

    @field_validator("producer")
    @classmethod
    def reject_blank_producer(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("producer must not be empty")
        return value

    @field_validator("created_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value.astimezone(timezone.utc)

    @field_validator("version", mode="before")
    @classmethod
    def normalize_semantic_version(cls, value: Any) -> str:
        """Accept legacy integer majors while requiring strict string semantics."""
        return normalize_semantic_version(value)

    @classmethod
    def build(
        cls,
        *,
        project_id: str,
        kind: str,
        content: JsonValue,
        owner: str,
        artifact_id: str | None = None,
        version: str | int = "1.0.0",
        status: str = "draft",
        depends_on: list[str] | None = None,
        evidence_refs: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        parent_artifact_ids: list[str] | None = None,
        producer: str | None = None,
        created_at: datetime | None = None,
        validation_results: list[JsonValue] | None = None,
    ) -> Artifact:
        """Build an artifact with a deterministic SHA-256 content hash."""
        values: dict[str, Any] = {
            "artifact_id": artifact_id if artifact_id is not None else str(uuid4()),
            "project_id": project_id,
            "kind": kind,
            "version": version,
            "status": status,
            "owner": owner,
            "content": content,
            "depends_on": depends_on or [],
            "evidence_refs": evidence_refs or [],
            "metadata": metadata or {},
            "created_at": created_at if created_at is not None else _utc_now(),
        }
        if parent_artifact_ids is not None:
            values["parent_artifact_ids"] = parent_artifact_ids
        if producer is not None:
            values["producer"] = producer
        if validation_results is not None:
            values["validation_results"] = validation_results
        return cls(**values)
