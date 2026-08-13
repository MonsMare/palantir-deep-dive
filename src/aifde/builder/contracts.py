"""Immutable source and evidence contracts for the builder boundary."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from math import isfinite
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _ImmutableList(list[Any]):
    def _immutable(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("immutable source metadata")

    __setitem__ = __delitem__ = append = clear = extend = insert = pop = remove = reverse = sort = _immutable
    __iadd__ = __imul__ = _immutable


class _ImmutableDict(dict[str, Any]):
    def _immutable(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("immutable source metadata")

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = _immutable


def _immutable_json(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("metadata floats must be finite")
        return value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("metadata mapping keys must be strings")
        return _ImmutableDict({key: _immutable_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return _ImmutableList(_immutable_json(item) for item in value)
    raise TypeError("metadata must contain JSON-compatible values")


def _require_non_blank(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    return value.strip()


def _require_aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _canonical_bytes(value: bytes | bytearray | memoryview) -> bytes:
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise TypeError("content must be bytes-like")
    return bytes(value)


def _content_hash(value: bytes) -> str:
    return sha256(value).hexdigest()


class SourceAsset(BaseModel):
    """A registered external source identity and its access metadata."""

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    source_asset_id: str
    uri: str
    source_type: str
    owner: str
    authority_level: int = Field(ge=0)
    classification: str
    access_policy_id: str
    schema_fingerprint: str
    metadata: dict[str, Any] = Field(default_factory=_ImmutableDict)

    @field_validator(
        "source_asset_id",
        "uri",
        "source_type",
        "owner",
        "classification",
        "access_policy_id",
        "schema_fingerprint",
    )
    @classmethod
    def reject_blank_fields(cls, value: str, info: Any) -> str:
        normalized = _require_non_blank(value, info.field_name)
        if info.field_name in {"uri", "source_type"}:
            markers = ("chat", "prompt", "model-output", "inference")
            if any(marker in normalized.lower() for marker in markers):
                raise ValueError(f"{info.field_name} must not identify model-generated sources")
        return normalized

    @field_validator("metadata", mode="before")
    @classmethod
    def freeze_metadata(cls, value: Any) -> dict[str, Any]:
        if value is None:
            return _ImmutableDict()
        normalized = _immutable_json(value)
        if not isinstance(normalized, _ImmutableDict):
            raise TypeError("metadata must be a mapping")
        return normalized

    @classmethod
    def register(
        cls,
        source_asset_id: str,
        uri: str,
        source_type: str,
        owner: str,
        authority_level: int,
        classification: str,
        access_policy_id: str,
        schema_fingerprint: str,
        metadata: Mapping[str, Any],
    ) -> SourceAsset:
        return cls(
            source_asset_id=source_asset_id,
            uri=uri,
            source_type=source_type,
            owner=owner,
            authority_level=authority_level,
            classification=classification,
            access_policy_id=access_policy_id,
            schema_fingerprint=schema_fingerprint,
            metadata=metadata,
        )

    @property
    def source_uri(self) -> str:
        """Compatibility spelling used by source provenance documents."""
        return self.uri


class SourceSnapshot(BaseModel):
    """An immutable, content-addressed capture of a source asset."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: str
    source_asset_id: str
    version: str
    content: bytes
    content_hash: str
    observed_at: datetime
    available_at: datetime
    extraction_version: str

    @field_validator("snapshot_id", "source_asset_id", "version", "extraction_version")
    @classmethod
    def reject_blank_identity(cls, value: str, info: Any) -> str:
        return _require_non_blank(value, info.field_name)

    @field_validator("content", mode="before")
    @classmethod
    def normalize_content(cls, value: Any) -> bytes:
        return _canonical_bytes(value)

    @field_validator("observed_at", "available_at")
    @classmethod
    def require_aware_datetime(cls, value: datetime, info: Any) -> datetime:
        return _require_aware(value, info.field_name)

    @field_validator("content_hash")
    @classmethod
    def validate_content_hash(cls, value: str) -> str:
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError("content_hash must be a SHA-256 hexadecimal digest")
        return value

    @model_validator(mode="after")
    def validate_content_hash_matches_content(self) -> SourceSnapshot:
        if self.content_hash != _content_hash(self.content):
            raise ValueError("content_hash does not match content")
        return self

    @classmethod
    def capture(
        cls,
        source_asset: SourceAsset,
        version: str,
        content: bytes,
        observed_at: datetime,
        available_at: datetime,
        extraction_version: str,
    ) -> SourceSnapshot:
        canonical_content = _canonical_bytes(content)
        content_hash = _content_hash(canonical_content)
        identity = f"{source_asset.source_asset_id}\x00{version}\x00{content_hash}"
        snapshot_id = f"snapshot:{sha256(identity.encode('utf-8')).hexdigest()}"
        return cls(
            snapshot_id=snapshot_id,
            source_asset_id=source_asset.source_asset_id,
            version=version,
            content=canonical_content,
            content_hash=content_hash,
            observed_at=observed_at,
            available_at=available_at,
            extraction_version=extraction_version,
        )


class EvidenceFragment(BaseModel):
    """A stable, locatable excerpt retaining original and normalized text."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: str
    snapshot_id: str
    source_asset_id: str
    source_version: str
    locator: str
    content: str
    normalized_content: str
    content_hash: str
    source_content_hash: str
    observed_at: datetime
    available_at: datetime
    extraction_method: str
    extraction_version: str
    event_time: datetime | None = None
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator(
        "evidence_id",
        "snapshot_id",
        "source_asset_id",
        "source_version",
        "locator",
        "extraction_method",
        "extraction_version",
    )
    @classmethod
    def reject_blank_identity(cls, value: str, info: Any) -> str:
        return _require_non_blank(value, info.field_name)

    @field_validator("content", "normalized_content")
    @classmethod
    def reject_blank_content(cls, value: str, info: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{info.field_name} must not be empty")
        return value

    @field_validator("observed_at", "available_at", "event_time")
    @classmethod
    def require_aware_datetime(cls, value: datetime | None, info: Any) -> datetime | None:
        if value is None:
            return None
        return _require_aware(value, info.field_name)

    @field_validator("content_hash", "source_content_hash")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError("content hash must be a SHA-256 hexadecimal digest")
        return value

    @model_validator(mode="before")
    @classmethod
    def validate_content_hash_matches_content(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            content = value.get("content")
            content_hash = value.get("content_hash")
            if isinstance(content, str) and isinstance(content_hash, str):
                if content_hash != _content_hash(content.encode("utf-8")):
                    raise ValueError("content_hash does not match content")
        return value

    @classmethod
    def from_snapshot(
        cls,
        snapshot: SourceSnapshot,
        locator: str,
        content: str,
        normalized_content: str | None = None,
        extraction_method: str = "deterministic-text",
        event_time: datetime | None = None,
        confidence: float = 1.0,
    ) -> EvidenceFragment:
        normalized = content if normalized_content is None else normalized_content
        fragment_hash = _content_hash(content.encode("utf-8"))
        identity = f"{snapshot.snapshot_id}\x00{locator}\x00{fragment_hash}"
        evidence_id = f"evidence:{sha256(identity.encode('utf-8')).hexdigest()}"
        return cls(
            evidence_id=evidence_id,
            snapshot_id=snapshot.snapshot_id,
            source_asset_id=snapshot.source_asset_id,
            source_version=snapshot.version,
            locator=locator,
            content=content,
            normalized_content=normalized,
            content_hash=fragment_hash,
            source_content_hash=snapshot.content_hash,
            observed_at=snapshot.observed_at,
            available_at=snapshot.available_at,
            extraction_method=extraction_method,
            extraction_version=snapshot.extraction_version,
            event_time=event_time,
            confidence=confidence,
        )

    @property
    def evidence_fragment_id(self) -> str:
        return self.evidence_id

    @property
    def source_version(self) -> str:
        return self.__dict__["source_version"]

    @property
    def location(self) -> str:
        return self.locator

    @property
    def extractor_version(self) -> str:
        return self.extraction_version

    @property
    def observed_time(self) -> datetime:
        return self.observed_at

    @property
    def available_time(self) -> datetime:
        return self.available_at
