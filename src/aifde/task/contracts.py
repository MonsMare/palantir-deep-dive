"""Immutable task contracts and lifecycle records."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .lifecycle import TaskStatus


def _normalize_nonblank(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    return value.strip()


def _normalize_sequence(value: Any, field_name: str) -> tuple[str, ...]:
    if isinstance(value, str) or value is None:
        raise ValueError(f"{field_name} must be a sequence of strings")
    try:
        items = tuple(value)
    except TypeError as exc:
        raise ValueError(f"{field_name} must be a sequence of strings") from exc
    return tuple(_normalize_nonblank(item, field_name) for item in items)


class TaskContract(BaseModel):
    """The immutable scope and governance contract for one task."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: str
    project_id: str
    domain_pack: str
    task_kind: str
    objective: str
    decision_owner: str
    required_outputs: tuple[str, ...] = Field(min_length=1)
    acceptance: tuple[str, ...] = Field(min_length=1)
    evidence_refs: tuple[str, ...] = ()
    risk_tier: str = "medium"
    human_checkpoints: tuple[str, ...] = ()
    max_fix_rounds: int = Field(default=3, ge=0)
    timeout_seconds: int = Field(default=3600, gt=0)

    @field_validator(
        "task_id",
        "project_id",
        "domain_pack",
        "task_kind",
        "objective",
        "decision_owner",
        "risk_tier",
    )
    @classmethod
    def require_nonblank(cls, value: str, info: Any) -> str:
        return _normalize_nonblank(value, info.field_name)

    @field_validator("required_outputs", "acceptance", "human_checkpoints", mode="before")
    @classmethod
    def normalize_sequences(cls, value: Any, info: Any) -> tuple[str, ...]:
        return _normalize_sequence(value, info.field_name)

    @field_validator("evidence_refs", mode="before")
    @classmethod
    def normalize_evidence_refs(cls, value: Any) -> tuple[str, ...]:
        refs = _normalize_sequence(value, "evidence_refs")
        return tuple(dict.fromkeys(refs))


class TaskContractVersion(BaseModel):
    """A numbered immutable version of a task contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: TaskContract
    version: int = Field(default=1, ge=1)
    created_at: datetime | None = None


class TaskRecord(BaseModel):
    """The current lifecycle projection for one task."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: str
    contract: TaskContract
    status: TaskStatus = TaskStatus.INTAKE
    contract_version: int = Field(default=1, ge=1)


class TaskEvent(BaseModel):
    """An immutable record describing one attempted state transition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    task_id: str
    event_name: str
    actor: str
    previous_state: TaskStatus
    new_state: TaskStatus
    run_id: str | None = None
    contract_version: int = Field(default=1, ge=1)

    @field_validator("event_id", "task_id", "event_name", "actor")
    @classmethod
    def require_nonblank(cls, value: str, info: Any) -> str:
        return _normalize_nonblank(value, info.field_name)
