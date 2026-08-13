"""Typed business objects and immutable event facts for the demo project."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from enum import Enum
from hashlib import sha256
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _StringEnum(str, Enum):
    @classmethod
    def _missing_(cls, value: object):
        if isinstance(value, str):
            normalized = value.lower().replace(" ", "_")
            for member in cls:
                if member.value == normalized:
                    return member
        return None


class RequirementStatus(_StringEnum):
    NEW = "new"
    CLARIFICATION = "clarification"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"


class ChangeRequestStatus(_StringEnum):
    PROPOSED = "proposed"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    IMPLEMENTED = "implemented"


class WorkItemStatus(_StringEnum):
    BACKLOG = "backlog"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    IN_REVIEW = "in_review"
    DONE = "done"
    CANCELLED = "cancelled"


class ActionStatus(_StringEnum):
    PENDING = "pending"
    APPROVED = "approved"
    EXECUTED = "executed"
    FAILED = "failed"
    REJECTED = "rejected"


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


def _nonblank(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty")
    return value.strip()


class ProjectConfig(BaseModel):
    """Seeded generator configuration with explicit project scale."""

    model_config = ConfigDict(extra="forbid")

    seed: int
    team_count: int
    people_count: int
    module_count: int
    sprint_count: int
    requirement_count: int
    work_item_count: int
    change_request_count: int
    start_date: date
    sprint_length_days: int
    ingestion_delay_days: int = 1

    @classmethod
    def load(cls, path: Path) -> "ProjectConfig":
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError("project config must be a YAML mapping")
        aliases = {
            "teams": "team_count",
            "people": "people_count",
            "modules": "module_count",
            "sprints": "sprint_count",
            "requirements": "requirement_count",
            "work_items": "work_item_count",
            "change_requests": "change_request_count",
        }
        normalized = {aliases.get(key, key): value for key, value in raw.items()}
        return cls.model_validate(normalized)

    @field_validator(
        "team_count",
        "people_count",
        "module_count",
        "sprint_count",
        "requirement_count",
        "work_item_count",
        "change_request_count",
        "sprint_length_days",
    )
    @classmethod
    def positive_counts(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("project scale values must be positive")
        return value

    @field_validator("ingestion_delay_days")
    @classmethod
    def nonnegative_delay(cls, value: int) -> int:
        if value < 0:
            raise ValueError("ingestion_delay_days must be non-negative")
        return value


class DomainEvent(BaseModel):
    """An immutable fact; current entity state is derived from these events."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    entity_type: str
    entity_id: str
    event_type: str
    event_time: datetime
    observed_time: datetime
    actor_id: str = "system"
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "event_id", "entity_type", "entity_id", "event_type", "actor_id"
    )
    @classmethod
    def validate_identity(cls, value: str, info: Any) -> str:
        return _nonblank(value, info.field_name)

    @field_validator("event_time", "observed_time")
    @classmethod
    def validate_time(cls, value: datetime, info: Any) -> datetime:
        return _aware(value, info.field_name)

    @model_validator(mode="after")
    def observed_after_event(self) -> "DomainEvent":
        if self.observed_time < self.event_time:
            raise ValueError("observed_time cannot precede event_time")
        return self


class Requirement(BaseModel):
    model_config = ConfigDict(extra="allow")

    requirement_id: str
    title: str = ""
    goal: str | None = None
    owner: str | None = None
    status: RequirementStatus = RequirementStatus.NEW
    module_id: str | None = None
    priority: int = Field(default=3, ge=1, le=5)
    acceptance_criteria: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
    committed_date: datetime | None = None

    @field_validator("requirement_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _nonblank(value, "requirement_id")


class ChangeRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    change_id: str
    requirement_id: str | None = None
    title: str = ""
    requested_at: datetime | None = None
    observed_at: datetime | None = None
    requester: str | None = None
    status: ChangeRequestStatus = ChangeRequestStatus.PROPOSED
    added_scope_hours: float = Field(default=0.0, ge=0.0)
    acceptance_delta: str = ""
    priority: int = Field(default=3, ge=1, le=5)

    @field_validator("change_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _nonblank(value, "change_id")

    @field_validator("requested_at", "observed_at")
    @classmethod
    def validate_optional_time(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _aware(value, "change timestamp")


class WorkItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    work_item_id: str
    requirement_id: str | None = None
    module_id: str | None = None
    team_id: str | None = None
    sprint_id: str | None = None
    title: str = ""
    task_type: str = "feature"
    status: WorkItemStatus = WorkItemStatus.BACKLOG
    priority: int = Field(default=3, ge=1, le=5)
    estimate_hours: float = Field(default=8.0, ge=0.0)
    committed_date: datetime | None = None
    acceptance_criteria_complete: bool = True
    required_skill: str = "general"
    approved: bool = False
    actual_start_at: datetime | None = None
    actual_complete_at: datetime | None = None

    @field_validator("work_item_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _nonblank(value, "work_item_id")

    @field_validator("committed_date", "actual_start_at", "actual_complete_at")
    @classmethod
    def validate_optional_time(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _aware(value, "work item timestamp")


class Sprint(BaseModel):
    sprint_id: str
    start_at: datetime
    end_at: datetime
    capacity_hours: float = Field(ge=0.0)
    committed_hours: float = Field(default=0.0, ge=0.0)
    status: str = "planned"

    @model_validator(mode="after")
    def valid_interval(self) -> "Sprint":
        if self.end_at < self.start_at:
            raise ValueError("sprint end cannot precede start")
        _aware(self.start_at, "start_at")
        _aware(self.end_at, "end_at")
        return self


class Dependency(BaseModel):
    dependency_id: str
    predecessor_id: str
    successor_id: str
    dependency_type: str = "finish_to_start"
    status: str = "unresolved"

    @model_validator(mode="after")
    def no_self_dependency(self) -> "Dependency":
        if self.predecessor_id == self.successor_id:
            raise ValueError("dependency cannot point to itself")
        return self


class Person(BaseModel):
    person_id: str
    team_id: str
    role: str = "engineer"
    skills: list[str] = Field(default_factory=lambda: ["general"])
    availability_ratio: float = Field(default=1.0, ge=0.0, le=1.0)


class Team(BaseModel):
    team_id: str
    name: str
    skills: list[str] = Field(default_factory=lambda: ["general"])
    default_capacity_hours: float = Field(default=320.0, ge=0.0)


class CapacitySnapshot(BaseModel):
    capacity_id: str
    team_id: str
    sprint_id: str
    snapshot_at: datetime
    capacity_hours: float = Field(ge=0.0)
    allocated_hours: float = Field(default=0.0, ge=0.0)

    @field_validator("snapshot_at")
    @classmethod
    def validate_snapshot_time(cls, value: datetime) -> datetime:
        return _aware(value, "snapshot_at")


class Feedback(BaseModel):
    feedback_id: str
    target_type: str
    target_id: str
    feedback_type: str
    value: Any
    source: str
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        return _aware(value, "created_at")


def generate_id(prefix: str, seed: int, ordinal: int) -> str:
    """Generate a stable, namespaced identifier without using process randomness."""
    prefix = _nonblank(prefix, "prefix").lower().replace(" ", "-")
    digest = sha256(f"{prefix}:{seed}:{ordinal}".encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{ordinal:04d}-{digest}"


def utc_from_date(value: date) -> datetime:
    return datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc)


__all__ = [
    "ActionStatus",
    "CapacitySnapshot",
    "ChangeRequest",
    "ChangeRequestStatus",
    "Dependency",
    "DomainEvent",
    "Feedback",
    "Person",
    "ProjectConfig",
    "Requirement",
    "RequirementStatus",
    "Sprint",
    "Team",
    "WorkItem",
    "WorkItemStatus",
    "generate_id",
    "utc_from_date",
]
