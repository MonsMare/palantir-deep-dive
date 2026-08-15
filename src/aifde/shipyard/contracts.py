"""Immutable-enough contracts for the Shipyard Workbench boundary."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import re
from typing import Any, Literal, Mapping, Self
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from aifde.domain.artifacts import canonical_json_bytes


_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _nonblank(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be blank")
    return value.strip()


def _nonblank_list(value: Any, field_name: str) -> list[str]:
    if isinstance(value, str) or value is None:
        raise TypeError(f"{field_name} must be a sequence of strings")
    try:
        values = list(value)
    except TypeError as exc:
        raise TypeError(f"{field_name} must be a sequence of strings") from exc
    return [_nonblank(item, field_name) for item in values]


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _sha256(value: str, field_name: str) -> str:
    value = _nonblank(value, field_name)
    if not _SHA256_PATTERN.fullmatch(value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 hexadecimal digest")
    return value


def _hash_map(value: Any, field_name: str) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    if not value:
        raise ValueError(f"{field_name} must not be empty")
    normalized: dict[str, str] = {}
    for record_id, record_hash in value.items():
        normalized[_nonblank(record_id, "record_id")] = _sha256(
            record_hash, f"{field_name} hash"
        )
    return normalized


def _content_hash_for_model(model: BaseModel) -> str:
    payload = model.model_dump(mode="json", exclude={"content_hash"})
    return sha256(canonical_json_bytes(payload)).hexdigest()


class _FrozenContract(BaseModel):
    """Shared strict configuration and validated copy semantics."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    def model_copy(
        self, *, update: Mapping[str, Any] | None = None, deep: bool = False
    ) -> Self:
        values = self.model_dump(mode="python", exclude={"content_hash"})
        if deep:
            values = deepcopy(values)
        if update:
            values.update(dict(update))
        return type(self).model_validate(values)


class ProjectWorkspace(_FrozenContract):
    """A revisioned Workbench project workspace projection."""

    workspace_id: str
    project_id: str
    name: str
    domain_pack: str
    owner: str
    status: Literal["draft", "active", "archived"] = "active"
    current_phase: str = "intake"
    revision: int = Field(default=1, ge=1)
    decision_case_ids: list[str] = Field(default_factory=list)
    artifact_ids: list[str] = Field(default_factory=list)
    proposal_ids: list[str] = Field(default_factory=list)
    gate_review_ids: list[str] = Field(default_factory=list)
    release_candidate_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)

    @field_validator("workspace_id", "project_id", "name", "domain_pack", "owner", "current_phase")
    @classmethod
    def normalize_identity(cls, value: str, info: Any) -> str:
        return _nonblank(value, info.field_name)

    @field_validator(
        "decision_case_ids",
        "artifact_ids",
        "proposal_ids",
        "gate_review_ids",
        "release_candidate_ids",
        mode="before",
    )
    @classmethod
    def normalize_record_ids(cls, value: Any, info: Any) -> list[str]:
        return _nonblank_list(value, info.field_name)

    @field_validator("created_at", "updated_at")
    @classmethod
    def normalize_timestamps(cls, value: datetime, info: Any) -> datetime:
        return _aware_utc(value, info.field_name)


class DecisionCase(_FrozenContract):
    """A business decision that the Workbench is expected to systematize."""

    case_id: str
    workspace_id: str
    name: str
    objective: str
    decision_owner: str
    users: list[str]
    trigger: str
    inputs: list[str]
    actions: list[str] = Field(min_length=1)
    constraints: list[str] = Field(default_factory=list)
    kpis: list[str] = Field(default_factory=list)
    baseline: str
    success_definition: str
    failure_definition: str
    status: Literal["draft", "active", "completed", "archived"] = "draft"

    @field_validator(
        "case_id",
        "workspace_id",
        "name",
        "objective",
        "decision_owner",
        "trigger",
        "baseline",
        "success_definition",
        "failure_definition",
    )
    @classmethod
    def normalize_required_text(cls, value: str, info: Any) -> str:
        return _nonblank(value, info.field_name)

    @field_validator("users", "inputs", "actions", "constraints", "kpis", mode="before")
    @classmethod
    def normalize_case_lists(cls, value: Any, info: Any) -> list[str]:
        return _nonblank_list(value, info.field_name)


class AgentProposal(_FrozenContract):
    """An agent-only candidate; it contains no human authority fields."""

    proposal_id: str
    revision: int = Field(default=1, ge=1)
    workspace_id: str
    task_packet_id: str
    producer: str
    producer_kind: Literal["agent"] = "agent"
    proposed_changes: dict[str, JsonValue]
    affected_artifact_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    validation_results: list[JsonValue] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    risks: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    next_step: str = "request human review"
    base_revision: int = Field(default=1, ge=1)
    status: Literal["proposed", "accepted", "rejected", "returned", "stale"] = "proposed"
    created_at: datetime = Field(default_factory=_utc_now)
    content_hash: str = ""

    @field_validator("proposal_id", "workspace_id", "task_packet_id", "producer")
    @classmethod
    def normalize_identity(cls, value: str, info: Any) -> str:
        return _nonblank(value, info.field_name)

    @field_validator(
        "affected_artifact_ids",
        "evidence_refs",
        "risks",
        "open_questions",
        mode="before",
    )
    @classmethod
    def normalize_proposal_lists(cls, value: Any, info: Any) -> list[str]:
        return _nonblank_list(value, info.field_name)

    @field_validator("next_step")
    @classmethod
    def normalize_next_step(cls, value: str) -> str:
        return _nonblank(value, "next_step")

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        return _aware_utc(value, "created_at")

    @model_validator(mode="after")
    def verify_content_hash(self) -> AgentProposal:
        expected = _content_hash_for_model(self)
        if self.content_hash not in ("", expected):
            raise ValueError("content_hash does not match canonical proposal content")
        object.__setattr__(self, "content_hash", expected)
        return self


class GateReviewSnapshot(_FrozenContract):
    """An immutable snapshot of one gate run against exact Artifact hashes."""

    gate_run_id: str
    revision: int = Field(default=1, ge=1)
    workspace_id: str
    gate_id: str
    severity: Literal["hard", "soft"]
    status: Literal["pending", "passed", "failed", "blocked"] = "pending"
    artifact_hashes: dict[str, str]
    validator_version: str
    violations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    stale: bool = False
    created_at: datetime = Field(default_factory=_utc_now)
    content_hash: str = ""

    @field_validator("gate_run_id", "workspace_id", "gate_id", "validator_version")
    @classmethod
    def normalize_identity(cls, value: str, info: Any) -> str:
        return _nonblank(value, info.field_name)

    @field_validator("artifact_hashes", mode="before")
    @classmethod
    def normalize_artifact_hashes(cls, value: Any) -> dict[str, str]:
        return _hash_map(value, "artifact_hashes")

    @field_validator("violations", "warnings", "evidence_refs", mode="before")
    @classmethod
    def normalize_review_lists(cls, value: Any, info: Any) -> list[str]:
        return _nonblank_list(value, info.field_name)

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        return _aware_utc(value, "created_at")

    @model_validator(mode="after")
    def verify_content_hash(self) -> GateReviewSnapshot:
        expected = _content_hash_for_model(self)
        if self.content_hash not in ("", expected):
            raise ValueError("content_hash does not match canonical gate review content")
        object.__setattr__(self, "content_hash", expected)
        return self


class ReleaseCandidate(_FrozenContract):
    """A release manifest candidate awaiting application-level authorization."""

    candidate_id: str
    revision: int = Field(default=1, ge=1)
    workspace_id: str
    artifact_ids: list[str] = Field(default_factory=list)
    gate_run_ids: list[str] = Field(default_factory=list)
    manifest: dict[str, JsonValue]
    status: Literal["draft", "ready", "blocked", "released"] = "draft"
    created_at: datetime = Field(default_factory=_utc_now)
    created_by: str
    content_hash: str = ""

    @field_validator("candidate_id", "workspace_id", "created_by")
    @classmethod
    def normalize_identity(cls, value: str, info: Any) -> str:
        return _nonblank(value, info.field_name)

    @field_validator("artifact_ids", "gate_run_ids", mode="before")
    @classmethod
    def normalize_candidate_ids(cls, value: Any, info: Any) -> list[str]:
        return _nonblank_list(value, info.field_name)

    @field_validator("manifest", mode="before")
    @classmethod
    def validate_manifest(cls, value: Any) -> dict[str, JsonValue]:
        if not isinstance(value, Mapping) or not value:
            raise ValueError("manifest must be a non-empty mapping")

        normalized = dict(value)
        if "artifact_hashes" in normalized:
            normalized["artifact_hashes"] = _hash_map(
                normalized["artifact_hashes"], "manifest.artifact_hashes"
            )
        elif "content_hash" in normalized:
            normalized["content_hash"] = _sha256(
                normalized["content_hash"], "manifest.content_hash"
            )
        elif "manifest_hash" in normalized:
            normalized["manifest_hash"] = _sha256(
                normalized["manifest_hash"], "manifest.manifest_hash"
            )
        else:
            raise ValueError(
                "manifest must include artifact_hashes, content_hash, or manifest_hash"
            )
        return normalized

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        return _aware_utc(value, "created_at")

    @model_validator(mode="after")
    def verify_content_hash(self) -> ReleaseCandidate:
        expected = _content_hash_for_model(self)
        if self.content_hash not in ("", expected):
            raise ValueError("content_hash does not match canonical release candidate content")
        object.__setattr__(self, "content_hash", expected)
        return self


def _event_hash_for(
    *,
    event_id: str,
    workspace_id: str,
    event_type: str,
    actor: str,
    actor_kind: str,
    payload: JsonValue,
    created_at: datetime,
    predecessor_hash: str,
) -> str:
    event_payload = {
        "event_id": event_id,
        "workspace_id": workspace_id,
        "event_type": event_type,
        "actor": actor,
        "actor_kind": actor_kind,
        "payload": payload,
        "created_at": created_at.isoformat(),
        "predecessor_hash": predecessor_hash,
    }
    return sha256(canonical_json_bytes(event_payload)).hexdigest()


class AuditEvent(_FrozenContract):
    """A tamper-evident Workbench event linked to its predecessor hash."""

    event_id: str = Field(default_factory=lambda: f"audit:{uuid4()}")
    workspace_id: str
    event_type: str
    actor: str
    actor_kind: Literal["human", "agent", "system"]
    payload: JsonValue
    created_at: datetime = Field(default_factory=_utc_now)
    predecessor_hash: str
    event_hash: str

    @field_validator("event_id", "workspace_id", "event_type", "actor")
    @classmethod
    def normalize_identity(cls, value: str, info: Any) -> str:
        return _nonblank(value, info.field_name)

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        return _aware_utc(value, "created_at")

    @field_validator("predecessor_hash", "event_hash")
    @classmethod
    def validate_hash(cls, value: str, info: Any) -> str:
        return _sha256(value, info.field_name)

    @model_validator(mode="after")
    def verify_event_hash(self) -> AuditEvent:
        expected = _event_hash_for(
            event_id=self.event_id,
            workspace_id=self.workspace_id,
            event_type=self.event_type,
            actor=self.actor,
            actor_kind=self.actor_kind,
            payload=self.payload,
            created_at=self.created_at,
            predecessor_hash=self.predecessor_hash,
        )
        if self.event_hash != expected:
            raise ValueError("event_hash does not match canonical event payload")
        return self

    @classmethod
    def build(
        cls,
        workspace_id: str,
        event_type: str,
        actor: str,
        actor_kind: Literal["human", "agent", "system"],
        payload: JsonValue,
        predecessor_hash: str,
    ) -> AuditEvent:
        timestamp = _utc_now()
        event_id = f"audit:{uuid4()}"
        normalized_workspace_id = _nonblank(workspace_id, "workspace_id")
        normalized_event_type = _nonblank(event_type, "event_type")
        normalized_actor = _nonblank(actor, "actor")
        normalized_predecessor_hash = _sha256(predecessor_hash, "predecessor_hash")
        event_hash = _event_hash_for(
            event_id=event_id,
            workspace_id=normalized_workspace_id,
            event_type=normalized_event_type,
            actor=normalized_actor,
            actor_kind=actor_kind,
            payload=payload,
            created_at=timestamp,
            predecessor_hash=normalized_predecessor_hash,
        )
        return cls(
            event_id=event_id,
            workspace_id=normalized_workspace_id,
            event_type=normalized_event_type,
            actor=normalized_actor,
            actor_kind=actor_kind,
            payload=payload,
            created_at=timestamp,
            predecessor_hash=normalized_predecessor_hash,
            event_hash=event_hash,
        )


__all__ = [
    "AgentProposal",
    "AuditEvent",
    "DecisionCase",
    "GateReviewSnapshot",
    "ProjectWorkspace",
    "ReleaseCandidate",
]
