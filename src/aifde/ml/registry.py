"""Append-only model registry with governed promotion and rollback."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from hashlib import sha256
import json
from threading import RLock
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _nonblank(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must not be empty")
    return value.strip()


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _jsonable(value.model_dump(mode="python"))
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _artifact_hash(values: Mapping[str, Any]) -> str:
    payload = json.dumps(
        _jsonable(values), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256(payload).hexdigest()


class ModelArtifact(BaseModel):
    """Immutable identity of a model and all training dependencies."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_id: str
    model_version: str
    feature_definition_id: str
    feature_definition_version: str
    ontology_release_id: str
    training_snapshot_id: str
    training_data_hash: str
    code_version: str
    artifact_uri: str
    model_type: str
    artifact_hash: str
    created_at: datetime
    status: Literal["candidate", "approved", "retired"] = "candidate"
    evaluation_report_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "model_id",
        "model_version",
        "feature_definition_id",
        "feature_definition_version",
        "ontology_release_id",
        "training_snapshot_id",
        "training_data_hash",
        "code_version",
        "artifact_uri",
        "model_type",
        "artifact_hash",
    )
    @classmethod
    def validate_text(cls, value: str, info: Any) -> str:
        return _nonblank(value, info.field_name)

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value.astimezone(timezone.utc)

    @classmethod
    def create(cls, **values: Any) -> "ModelArtifact":
        values = dict(values)
        values.setdefault("status", "candidate")
        values.setdefault("metadata", {})
        values["artifact_hash"] = _artifact_hash(cls._hash_values(values))
        return cls(**values)

    @classmethod
    def _hash_values(cls, values: Mapping[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in values.items()
            if key not in {"artifact_hash", "status", "evaluation_report_id"}
        }

    def recompute_hash(self) -> str:
        return _artifact_hash(self._hash_values(self.model_dump(mode="python")))


class ModelRegistry:
    """Content-addressed model identities and explicit release pointer."""

    def __init__(self) -> None:
        self._artifacts: dict[tuple[str, str], ModelArtifact] = {}
        self._runtime: dict[tuple[str, str], Any] = {}
        self._approved: dict[str, str] = {}
        self._lock = RLock()

    def register(self, artifact: ModelArtifact, runtime_object: Any = None) -> ModelArtifact:
        if not isinstance(artifact, ModelArtifact):
            raise TypeError("artifact must be a ModelArtifact")
        key = (artifact.model_id, artifact.model_version)
        with self._lock:
            existing = self._artifacts.get(key)
            if existing is not None:
                if existing != artifact:
                    raise ValueError("model artifact identity is immutable")
                if runtime_object is not None and key not in self._runtime:
                    self._runtime[key] = runtime_object
                return existing
            if not self.verify(artifact):
                raise ValueError("model artifact hash is invalid")
            self._artifacts[key] = artifact
            if runtime_object is not None:
                self._runtime[key] = runtime_object
            return artifact

    def get(self, model_id: str, model_version: str) -> ModelArtifact:
        key = (_nonblank(model_id, "model_id"), _nonblank(model_version, "model_version"))
        with self._lock:
            try:
                return self._artifacts[key]
            except KeyError as exc:
                raise KeyError(f"unknown model artifact: {key[0]}@{key[1]}") from exc

    def runtime_object(self, model_id: str, model_version: str) -> Any:
        key = (_nonblank(model_id, "model_id"), _nonblank(model_version, "model_version"))
        with self._lock:
            if key not in self._runtime:
                raise KeyError(f"no runtime object for model artifact: {key[0]}@{key[1]}")
            return self._runtime[key]

    def promote(self, model_id: str, model_version: str, evaluation: Any) -> ModelArtifact:
        artifact = self.get(model_id, model_version)
        if evaluation is None:
            raise ValueError("model promotion requires an evaluation report")
        if getattr(evaluation, "model_id", None) != artifact.model_id:
            raise ValueError("evaluation model_id does not match artifact")
        if getattr(evaluation, "model_version", None) != artifact.model_version:
            raise ValueError("evaluation model_version does not match artifact")
        if not getattr(evaluation, "release_eligible", False):
            raise ValueError("model evaluation is not release eligible")
        report_id = _nonblank(str(getattr(evaluation, "report_id", "")), "evaluation.report_id")
        approved = artifact.model_copy(
            update={"status": "approved", "evaluation_report_id": report_id}
        )
        with self._lock:
            self._artifacts[(artifact.model_id, artifact.model_version)] = approved
            self._approved[artifact.model_id] = artifact.model_version
        return approved

    def rollback(self, model_id: str, model_version: str, *, actor: str) -> ModelArtifact:
        actor = _nonblank(actor, "actor")
        artifact = self.get(model_id, model_version)
        if artifact.status != "approved":
            raise ValueError("rollback target must be an approved model artifact")
        with self._lock:
            self._approved[artifact.model_id] = artifact.model_version
        return artifact

    def current(self, model_id: str) -> ModelArtifact:
        model_id = _nonblank(model_id, "model_id")
        with self._lock:
            version = self._approved.get(model_id)
        if version is None:
            raise KeyError(f"no approved model for {model_id}")
        return self.get(model_id, version)

    @staticmethod
    def verify(artifact: ModelArtifact) -> bool:
        if not isinstance(artifact, ModelArtifact):
            raise TypeError("artifact must be a ModelArtifact")
        return artifact.artifact_hash == artifact.recompute_hash()

    def list(self, model_id: str | None = None) -> tuple[ModelArtifact, ...]:
        with self._lock:
            values = tuple(self._artifacts.values())
        if model_id is not None:
            values = tuple(item for item in values if item.model_id == model_id)
        return tuple(sorted(values, key=lambda item: (item.model_id, item.model_version)))


__all__ = ["ModelArtifact", "ModelRegistry"]
