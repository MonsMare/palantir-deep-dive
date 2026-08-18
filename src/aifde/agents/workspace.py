"""Append-only, evidence-bound workspace for agent proposals."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from threading import RLock
from typing import Any, Mapping, Self
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

from aifde.domain.artifacts import (
    Artifact,
    canonical_json_bytes,
    normalize_semantic_version,
    semantic_version_key,
)

from .roles import AgentRole


class WorkspaceError(RuntimeError):
    """Base class for workspace integrity failures."""


class WorkspaceConflictError(WorkspaceError):
    """Raised when a write would overwrite or race an artifact revision."""


class WorkspaceAccessError(PermissionError):
    """Raised when an agent reads outside its authorized workspace view."""


class ArtifactCandidate(BaseModel):
    """An agent proposal; it is not a published or executable artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_id: str
    project_id: str
    kind: str
    version: str = "1.0.0"
    owner: str
    content: JsonValue
    depends_on: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    producer_role: AgentRole

    @field_validator("artifact_id", "project_id", "kind", "owner")
    @classmethod
    def reject_blank_identity(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("candidate identity must not be blank")
        return value.strip()

    @field_validator("version", mode="before")
    @classmethod
    def normalize_version(cls, value: Any) -> str:
        return normalize_semantic_version(value)

    @field_validator("depends_on", "evidence_refs")
    @classmethod
    def validate_refs(cls, value: list[str]) -> list[str]:
        if any(not isinstance(item, str) or not item.strip() for item in value):
            raise ValueError("candidate references must be non-empty strings")
        return list(dict.fromkeys(value))

    def model_copy(
        self, *, update: Mapping[str, Any] | None = None, deep: bool = False
    ) -> Self:
        values = self.model_dump(mode="python")
        if deep:
            values = deepcopy(values)
        if update:
            values.update(dict(update))
        return type(self).model_validate(values)


class WorkspaceArtifact(BaseModel):
    """An immutable workspace record with dependency and provenance hashes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_id: str
    project_id: str
    kind: str
    version: str
    status: str
    owner: str
    content: JsonValue
    content_hash: str
    depends_on: tuple[str, ...] = Field(default_factory=tuple)
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    dependency_hash: str
    produced_by: AgentRole
    revision_id: str
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value.astimezone(timezone.utc)


class WorkspaceEvent(BaseModel):
    """Append-only event describing a workspace state change."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(default_factory=lambda: str(uuid4()))
    event_type: str
    artifact_id: str
    revision_id: str
    reason: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class _WorkspaceCommitToken:
    pass


class WorkspaceCommitter:
    """Only the scheduler-owned committer can turn candidates into records."""

    def __init__(self, workspace: "ArtifactWorkspace", token: _WorkspaceCommitToken) -> None:
        self._workspace = workspace
        self._token = token

    def commit(self, candidate: ArtifactCandidate) -> WorkspaceArtifact:
        return self._workspace._commit(candidate, self._token)

    def revise(
        self, candidate: ArtifactCandidate, *, parent_version: str
    ) -> WorkspaceArtifact:
        return self._workspace._revise(candidate, parent_version, self._token)


class WorkspaceReadView:
    """Read-only, explicitly scoped view handed to one agent invocation."""

    def __init__(
        self,
        workspace: "ArtifactWorkspace",
        *,
        actor_id: str,
        role: AgentRole,
        allowed_artifact_ids: tuple[str, ...],
    ) -> None:
        self.actor_id = actor_id
        self.role = role
        self.allowed_artifact_ids = frozenset(allowed_artifact_ids)
        self._workspace = workspace

    def read(self, artifact_id: str) -> WorkspaceArtifact:
        if artifact_id not in self.allowed_artifact_ids:
            raise WorkspaceAccessError(
                f"actor {self.actor_id} is not authorized to read artifact {artifact_id}"
            )
        return self._workspace.latest(artifact_id)

    def list_visible(self) -> tuple[str, ...]:
        return tuple(sorted(self.allowed_artifact_ids))


class ArtifactWorkspace:
    """Thread-safe append-only workspace with optimistic revision semantics."""

    def __init__(self, *, project_id: str) -> None:
        if not isinstance(project_id, str) or not project_id.strip():
            raise ValueError("project_id must not be blank")
        self.project_id = project_id.strip()
        self._records: dict[str, list[WorkspaceArtifact]] = {}
        self._stale: set[str] = set()
        self._events: list[WorkspaceEvent] = []
        self._lock = RLock()
        self._commit_token = _WorkspaceCommitToken()

    def system_committer(self) -> WorkspaceCommitter:
        """Return the scheduler boundary; agents only receive ``WorkspaceReadView``."""

        return WorkspaceCommitter(self, self._commit_token)

    def authorized_view(
        self,
        *,
        actor_id: str,
        role: AgentRole,
        allowed_artifact_ids: list[str] | tuple[str, ...] = (),
    ) -> WorkspaceReadView:
        if not isinstance(actor_id, str) or not actor_id.strip():
            raise ValueError("actor_id must not be blank")
        role = role if isinstance(role, AgentRole) else AgentRole(role)
        return WorkspaceReadView(
            self,
            actor_id=actor_id,
            role=role,
            allowed_artifact_ids=tuple(dict.fromkeys(allowed_artifact_ids)),
        )

    def latest(self, artifact_id: str) -> WorkspaceArtifact:
        with self._lock:
            records = self._records.get(artifact_id)
            if not records:
                raise KeyError(f"unknown workspace artifact: {artifact_id}")
            record = records[-1]
            if artifact_id not in self._stale:
                return record.model_copy(deep=True)
            return record.model_copy(update={"status": "stale"}, deep=True)

    def history(self, artifact_id: str) -> tuple[WorkspaceArtifact, ...]:
        with self._lock:
            return tuple(record.model_copy(deep=True) for record in self._records.get(artifact_id, ()))

    def events(self) -> tuple[WorkspaceEvent, ...]:
        with self._lock:
            return tuple(event.model_copy(deep=True) for event in self._events)

    def artifact_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._records))

    def dependency_hash(self, artifact_ids: list[str] | tuple[str, ...]) -> str:
        with self._lock:
            payload = {
                artifact_id: self._latest_record(artifact_id).content_hash
                for artifact_id in sorted(set(artifact_ids))
            }
        return sha256(canonical_json_bytes(payload)).hexdigest()

    def _commit(
        self, candidate: ArtifactCandidate, token: _WorkspaceCommitToken
    ) -> WorkspaceArtifact:
        with self._lock:
            self._check_token(token)
            self._validate_candidate(candidate)
            if candidate.artifact_id in self._records:
                raise WorkspaceConflictError(
                    f"artifact {candidate.artifact_id} already exists; use an explicit revision"
                )
            record = self._materialize(candidate)
            self._records[candidate.artifact_id] = [record]
            self._events.append(
                WorkspaceEvent(
                    event_type="artifact.candidate_committed",
                    artifact_id=record.artifact_id,
                    revision_id=record.revision_id,
                    reason="new candidate submitted by domain agent",
                )
            )
            return record.model_copy(deep=True)

    def _revise(
        self,
        candidate: ArtifactCandidate,
        parent_version: str,
        token: _WorkspaceCommitToken,
    ) -> WorkspaceArtifact:
        with self._lock:
            self._check_token(token)
            self._validate_candidate(candidate)
            current = self._latest_record(candidate.artifact_id)
            parent_version = normalize_semantic_version(parent_version)
            if current.version != parent_version:
                raise WorkspaceConflictError(
                    f"revision parent mismatch: expected {current.version}, got {parent_version}"
                )
            if semantic_version_key(candidate.version) <= semantic_version_key(current.version):
                raise WorkspaceConflictError("revision version must increase monotonically")
            record = self._materialize(candidate)
            self._records[candidate.artifact_id].append(record)
            self._events.append(
                WorkspaceEvent(
                    event_type="artifact.revised",
                    artifact_id=record.artifact_id,
                    revision_id=record.revision_id,
                    reason=f"revision supersedes {current.revision_id}",
                )
            )
            self._propagate_stale(candidate.artifact_id)
            return record.model_copy(deep=True)

    def _materialize(self, candidate: ArtifactCandidate) -> WorkspaceArtifact:
        dependency_hash = self.dependency_hash(candidate.depends_on)
        artifact = Artifact.build(
            artifact_id=candidate.artifact_id,
            project_id=candidate.project_id,
            kind=candidate.kind,
            version=candidate.version,
            status="candidate",
            owner=candidate.owner,
            content=candidate.content,
            depends_on=list(candidate.depends_on),
            evidence_refs=list(candidate.evidence_refs),
            metadata=dict(candidate.metadata),
        )
        created_at = datetime.now(timezone.utc)
        return WorkspaceArtifact(
            artifact_id=artifact.artifact_id,
            project_id=artifact.project_id,
            kind=artifact.kind,
            version=artifact.version,
            status="candidate",
            owner=artifact.owner,
            content=artifact.content,
            content_hash=artifact.content_hash,
            depends_on=tuple(artifact.depends_on),
            evidence_refs=tuple(artifact.evidence_refs),
            dependency_hash=dependency_hash,
            produced_by=candidate.producer_role,
            revision_id=f"{artifact.artifact_id}@{artifact.version}",
            created_at=created_at,
        )

    def _validate_candidate(self, candidate: ArtifactCandidate) -> None:
        if not isinstance(candidate, ArtifactCandidate):
            raise TypeError("workspace accepts ArtifactCandidate only")
        if candidate.project_id != self.project_id:
            raise WorkspaceConflictError("candidate belongs to a different project")
        if not candidate.evidence_refs:
            raise WorkspaceConflictError("candidate must include evidence references")
        for dependency_id in candidate.depends_on:
            if dependency_id not in self._records:
                raise WorkspaceConflictError(f"unknown dependency artifact: {dependency_id}")

    def _latest_record(self, artifact_id: str) -> WorkspaceArtifact:
        records = self._records.get(artifact_id)
        if not records:
            raise KeyError(f"unknown workspace artifact: {artifact_id}")
        return records[-1]

    def _propagate_stale(self, changed_artifact_id: str) -> None:
        queue = [changed_artifact_id]
        visited: set[str] = set()
        while queue:
            changed = queue.pop(0)
            if changed in visited:
                continue
            visited.add(changed)
            for artifact_id, records in self._records.items():
                if artifact_id in visited or not records:
                    continue
                if changed not in records[-1].depends_on:
                    continue
                self._stale.add(artifact_id)
                self._events.append(
                    WorkspaceEvent(
                        event_type="artifact.marked_stale",
                        artifact_id=artifact_id,
                        revision_id=records[-1].revision_id,
                        reason=f"upstream artifact revised: {changed}",
                    )
                )
                queue.append(artifact_id)

    def _check_token(self, token: _WorkspaceCommitToken) -> None:
        if token is not self._commit_token:
            raise WorkspaceAccessError("only the scheduler-owned committer may write artifacts")


__all__ = [
    "ArtifactCandidate",
    "ArtifactWorkspace",
    "WorkspaceAccessError",
    "WorkspaceArtifact",
    "WorkspaceCommitter",
    "WorkspaceConflictError",
    "WorkspaceEvent",
    "WorkspaceReadView",
]
