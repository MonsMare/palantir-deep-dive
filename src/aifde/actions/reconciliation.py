"""Append-only external action reconciliation records."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from threading import RLock
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator


class ReconciliationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    reconciliation_id: str
    action_id: str
    external_ref: str
    expected_fingerprint: str
    observed_fingerprint: str
    status: Literal["matched", "remediation"]
    observed_at: datetime

    @field_validator(
        "reconciliation_id",
        "action_id",
        "external_ref",
        "expected_fingerprint",
        "observed_fingerprint",
    )
    @classmethod
    def validate_text(cls, value: str, info):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{info.field_name} must not be empty")
        return value.strip()

    @field_validator("observed_at")
    @classmethod
    def validate_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        return value.astimezone(timezone.utc)


class ReconciliationLedger:
    """Store exactly one immutable reconciliation result per action."""

    def __init__(self) -> None:
        self._records: dict[str, ReconciliationRecord] = {}
        self._lock = RLock()

    def record(
        self,
        *,
        action_id: str,
        external_ref: str,
        expected_fingerprint: str,
        observed_fingerprint: str,
        observed_at: datetime,
    ) -> ReconciliationRecord:
        status = "matched" if expected_fingerprint == observed_fingerprint else "remediation"
        digest = sha256(
            json.dumps(
                {
                    "action_id": action_id,
                    "external_ref": external_ref,
                    "expected": expected_fingerprint,
                    "observed": observed_fingerprint,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        record = ReconciliationRecord(
            reconciliation_id=f"reconciliation:{digest[:24]}",
            action_id=action_id,
            external_ref=external_ref,
            expected_fingerprint=expected_fingerprint,
            observed_fingerprint=observed_fingerprint,
            status=status,
            observed_at=observed_at,
        )
        with self._lock:
            existing = self._records.get(action_id)
            if existing is not None:
                if existing != record:
                    raise ValueError("reconciliation record is append-only")
                return existing
            self._records[action_id] = record
            return record

    def get(self, action_id: str) -> ReconciliationRecord:
        with self._lock:
            try:
                return self._records[action_id]
            except KeyError as exc:
                raise KeyError(f"unknown reconciliation action: {action_id}") from exc

    def list(self) -> tuple[ReconciliationRecord, ...]:
        with self._lock:
            return tuple(self._records.values())


__all__ = ["ReconciliationLedger", "ReconciliationRecord"]
