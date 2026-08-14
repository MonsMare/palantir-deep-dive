"""Append-only audit chain with payload and predecessor hashes."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from threading import RLock
from typing import Any, Mapping, Self
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator


class AuditIntegrityError(ValueError):
    """Raised when an audit payload or chain link no longer verifies."""


class AuditEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(default_factory=lambda: f"audit:{uuid4()}")
    sequence: int
    event_type: str
    actor: str
    subject_id: str
    payload: JsonValue
    payload_hash: str
    previous_hash: str
    chain_hash: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("event_type", "actor", "subject_id")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("audit identity must not be blank")
        return value.strip()

    @field_validator("created_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("audit created_at must be timezone-aware")
        return value.astimezone(timezone.utc)


class AppendOnlyAuditLog:
    """In-memory append-only audit log; storage adapters can persist events."""

    def __init__(self) -> None:
        self._events: list[AuditEvent] = []
        self._lock = RLock()

    def append(
        self,
        *,
        event_type: str,
        actor: str,
        subject_id: str,
        payload: JsonValue,
        created_at: datetime | None = None,
    ) -> AuditEvent:
        with self._lock:
            sequence = len(self._events) + 1
            previous_hash = self._events[-1].chain_hash if self._events else "0" * 64
            payload_hash = _hash(payload)
            chain_hash = _hash(
                {
                    "sequence": sequence,
                    "event_type": event_type,
                    "actor": actor,
                    "subject_id": subject_id,
                    "payload_hash": payload_hash,
                    "previous_hash": previous_hash,
                }
            )
            event = AuditEvent(
                sequence=sequence,
                event_type=event_type,
                actor=actor,
                subject_id=subject_id,
                payload=payload,
                payload_hash=payload_hash,
                previous_hash=previous_hash,
                chain_hash=chain_hash,
                created_at=created_at or datetime.now(timezone.utc),
            )
            self._events.append(event)
            return event.model_copy(deep=True)

    def events(self) -> tuple[AuditEvent, ...]:
        with self._lock:
            return tuple(event.model_copy(deep=True) for event in self._events)

    def verify(self) -> bool:
        with self._lock:
            previous_hash = "0" * 64
            for expected_sequence, event in enumerate(self._events, start=1):
                if event.sequence != expected_sequence:
                    raise AuditIntegrityError("audit sequence is not append-only")
                if event.previous_hash != previous_hash:
                    raise AuditIntegrityError("audit predecessor hash mismatch")
                if event.payload_hash != _hash(event.payload):
                    raise AuditIntegrityError("audit payload hash mismatch")
                expected_chain = _hash(
                    {
                        "sequence": event.sequence,
                        "event_type": event.event_type,
                        "actor": event.actor,
                        "subject_id": event.subject_id,
                        "payload_hash": event.payload_hash,
                        "previous_hash": event.previous_hash,
                    }
                )
                if event.chain_hash != expected_chain:
                    raise AuditIntegrityError("audit chain hash mismatch")
                previous_hash = event.chain_hash
            return True


def _hash(value: Any) -> str:
    payload = json.dumps(
        _jsonable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _jsonable(value.model_dump(mode="python"))
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


__all__ = ["AppendOnlyAuditLog", "AuditEvent", "AuditIntegrityError"]
