"""Versioned source connector boundary for evidence capture."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from threading import RLock
from typing import Protocol

from pydantic import BaseModel, ConfigDict, field_validator

from aifde.builder.contracts import SourceAsset, SourceSnapshot
from aifde.builder.sources import SourceRegistry


_SUPPORTED_LOCAL_TYPES = {"json", "csv", "markdown", "text"}


def _text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must not be empty")
    return value.strip()


class CaptureRequest(BaseModel):
    """The immutable temporal and extraction metadata for one capture."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str
    observed_at: datetime
    available_at: datetime
    extraction_version: str

    @field_validator("version", "extraction_version")
    @classmethod
    def validate_text(cls, value: str, info: object) -> str:
        field_name = getattr(info, "field_name", "value")
        return _text(value, str(field_name))

    @field_validator("observed_at", "available_at")
    @classmethod
    def validate_aware_time(cls, value: datetime, info: object) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            field_name = getattr(info, "field_name", "time")
            raise ValueError(f"{field_name} must be timezone-aware")
        return value


class SourceDescriptor(BaseModel):
    """Public connector metadata; it never contains source content."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_asset_id: str
    uri: str
    source_type: str
    owner: str
    authority_level: int
    classification: str
    access_policy_id: str
    schema_fingerprint: str
    connector_version: str


class SourceConnector(Protocol):
    def describe(self) -> SourceDescriptor: ...

    def capture(self, request: CaptureRequest) -> SourceSnapshot: ...


class LocalFileConnector:
    """A deterministic local connector used for fixtures and self-hosted runs."""

    def __init__(
        self,
        *,
        path: Path,
        asset: SourceAsset,
        connector_version: str,
        registry: SourceRegistry | None = None,
    ) -> None:
        self._path = path
        self._asset = asset
        self._connector_version = _text(connector_version, "connector_version")
        self._registry = registry
        if registry is not None:
            registry.register(asset)

    @classmethod
    def from_path(
        cls,
        path: str | Path,
        *,
        owner: str,
        authority_level: int,
        classification: str,
        access_policy_id: str,
        source_type: str | None = None,
        connector_version: str = "local-file-v1",
        registry: SourceRegistry | None = None,
    ) -> LocalFileConnector:
        resolved = Path(path).expanduser().resolve()
        inferred = source_type or _infer_source_type(resolved)
        if inferred not in _SUPPORTED_LOCAL_TYPES:
            raise ValueError(f"unsupported source type: {inferred}")
        uri = f"file://{resolved.as_posix()}"
        asset_id = f"source:{sha256(uri.encode('utf-8')).hexdigest()}"
        schema_fingerprint = sha256(
            f"{inferred}|{connector_version}".encode("utf-8")
        ).hexdigest()
        asset = SourceAsset.register(
            asset_id,
            uri,
            inferred,
            owner,
            authority_level,
            classification,
            access_policy_id,
            schema_fingerprint,
            {"path": str(resolved), "connector_version": connector_version},
        )
        return cls(
            path=resolved,
            asset=asset,
            connector_version=connector_version,
            registry=registry,
        )

    def describe(self) -> SourceDescriptor:
        return SourceDescriptor(
            source_asset_id=self._asset.source_asset_id,
            uri=self._asset.uri,
            source_type=self._asset.source_type,
            owner=self._asset.owner,
            authority_level=self._asset.authority_level,
            classification=self._asset.classification,
            access_policy_id=self._asset.access_policy_id,
            schema_fingerprint=self._asset.schema_fingerprint,
            connector_version=self._connector_version,
        )

    def capture(self, request: CaptureRequest) -> SourceSnapshot:
        if not self._path.exists():
            raise FileNotFoundError(str(self._path))
        if not self._path.is_file():
            raise ValueError(f"source path is not a file: {self._path}")
        content = self._path.read_bytes()
        if self._registry is None:
            return SourceSnapshot.capture(
                self._asset,
                request.version,
                content,
                request.observed_at,
                request.available_at,
                request.extraction_version,
            )
        return self._registry.capture(
            self._asset.source_asset_id,
            request.version,
            content,
            request.observed_at,
            request.available_at,
            request.extraction_version,
        )


class ConnectorRegistry:
    """Append-only connector registry keyed by source asset identity."""

    def __init__(self) -> None:
        self._connectors: dict[str, SourceConnector] = {}
        self._descriptors: dict[str, SourceDescriptor] = {}
        self._lock = RLock()

    def register(self, connector: SourceConnector) -> SourceDescriptor:
        if not hasattr(connector, "describe") or not hasattr(connector, "capture"):
            raise TypeError("connector must implement describe and capture")
        descriptor = connector.describe()
        with self._lock:
            existing = self._descriptors.get(descriptor.source_asset_id)
            if existing is not None and existing != descriptor:
                raise ValueError("source connector identity is immutable")
            self._connectors[descriptor.source_asset_id] = connector
            self._descriptors[descriptor.source_asset_id] = descriptor
            return descriptor.model_copy(deep=True)

    def get(self, source_asset_id: str) -> SourceConnector:
        with self._lock:
            try:
                return self._connectors[source_asset_id]
            except KeyError as exc:
                raise KeyError(source_asset_id) from exc

    def list(self) -> list[SourceDescriptor]:
        with self._lock:
            return [
                self._descriptors[key].model_copy(deep=True)
                for key in sorted(self._descriptors)
            ]


def _infer_source_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return "json"
    if suffix == ".csv":
        return "csv"
    if suffix in {".md", ".markdown"}:
        return "markdown"
    if suffix in {".txt", ".log"}:
        return "text"
    return suffix.lstrip(".") or "unknown"


__all__ = [
    "CaptureRequest",
    "ConnectorRegistry",
    "LocalFileConnector",
    "SourceConnector",
    "SourceDescriptor",
]
