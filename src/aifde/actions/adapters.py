"""Approval-gated Action Broker and replaceable external adapter boundary."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from aifde.ontology.computation import (
    ActionOutcomeLink,
    ComputationChainValidator,
    DecisionCandidate,
    FeatureSnapshot,
    GovernedActionRequest,
    PredictionArtifact,
)

from .reconciliation import ReconciliationLedger, ReconciliationRecord


def _nonblank(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must not be empty")
    return value.strip()


def _fingerprint(request: GovernedActionRequest) -> str:
    payload = json.dumps(
        request.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256(payload).hexdigest()


class DryRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action_id: str
    accepted: bool
    effect_hash: str
    preview: dict[str, Any] = Field(default_factory=dict)


class AdapterReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    external_ref: str
    status: Literal["succeeded", "failed"]
    retryable: bool = False
    response_payload: dict[str, Any] = Field(default_factory=dict)
    executed_at: datetime

    @field_validator("external_ref")
    @classmethod
    def validate_external_ref(cls, value: str) -> str:
        return _nonblank(value, "external_ref")

    @field_validator("executed_at")
    @classmethod
    def validate_executed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("executed_at must be timezone-aware")
        return value.astimezone(timezone.utc)


class AdapterValidation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    accepted: bool
    reason: str


class ActionAdapter(Protocol):
    def validate(self, request: GovernedActionRequest) -> AdapterValidation: ...

    def dry_run(self, request: GovernedActionRequest) -> DryRunResult: ...

    def execute(self, request: GovernedActionRequest) -> AdapterReceipt: ...

    def reconcile(
        self, request: GovernedActionRequest, receipt: AdapterReceipt
    ) -> tuple[str, str]:
        """Return ``(external_ref, observed_fingerprint)``."""

    def rollback(self, request: GovernedActionRequest, receipt: AdapterReceipt) -> AdapterReceipt: ...


class MemoryActionAdapter:
    """Production-shaped test adapter; it writes nowhere outside memory."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.execute_count = 0

    def validate(self, request: GovernedActionRequest) -> AdapterValidation:
        return AdapterValidation(accepted=bool(request.parameters), reason="parameters present")

    def dry_run(self, request: GovernedActionRequest) -> DryRunResult:
        return DryRunResult(
            action_id=request.action_id,
            accepted=True,
            effect_hash=_fingerprint(request),
            preview={"target_id": request.target_id, "action_type": request.action_type},
        )

    def execute(self, request: GovernedActionRequest) -> AdapterReceipt:
        self.execute_count += 1
        status: Literal["succeeded", "failed"] = "failed" if self.fail else "succeeded"
        return AdapterReceipt(
            external_ref=f"memory://{request.action_type}/{request.target_id}",
            status=status,
            retryable=self.fail,
            response_payload={
                "action_id": request.action_id,
                "request_fingerprint": _fingerprint(request),
            },
            executed_at=datetime.now(timezone.utc),
        )

    def reconcile(
        self, request: GovernedActionRequest, receipt: AdapterReceipt
    ) -> tuple[str, str]:
        observed = (
            _fingerprint(request)
            if receipt.status == "succeeded"
            else "0" * 64
        )
        return receipt.external_ref, observed

    def rollback(self, request: GovernedActionRequest, receipt: AdapterReceipt) -> AdapterReceipt:
        return receipt.model_copy(
            update={
                "response_payload": {
                    **receipt.response_payload,
                    "rolled_back": True,
                }
            }
        )


class JsonlFileActionAdapter:
    """A local production-shaped adapter with append-only external receipts.

    It is intentionally a file system integration, not an ERP/Jira claim.  A
    real connector can implement the same protocol while preserving the
    broker's approval, idempotency, and reconciliation rules.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def validate(self, request: GovernedActionRequest) -> AdapterValidation:
        if not request.parameters:
            return AdapterValidation(accepted=False, reason="action parameters are empty")
        return AdapterValidation(accepted=True, reason="file adapter accepts the request")

    def dry_run(self, request: GovernedActionRequest) -> DryRunResult:
        return DryRunResult(
            action_id=request.action_id,
            accepted=True,
            effect_hash=_fingerprint(request),
            preview={
                "path": str(self._path),
                "operation": "append_action_record",
                "target_id": request.target_id,
            },
        )

    def execute(self, request: GovernedActionRequest) -> AdapterReceipt:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        executed_at = datetime.now(timezone.utc)
        record = {
            "action_id": request.action_id,
            "action_type": request.action_type,
            "target_id": request.target_id,
            "parameters": request.parameters,
            "request_fingerprint": _fingerprint(request),
            "executed_at": executed_at.isoformat(),
        }
        with self._path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        return AdapterReceipt(
            external_ref=f"file://{self._path.resolve()}#{request.action_id}",
            status="succeeded",
            response_payload=record,
            executed_at=executed_at,
        )

    def reconcile(
        self, request: GovernedActionRequest, receipt: AdapterReceipt
    ) -> tuple[str, str]:
        expected = _fingerprint(request)
        if receipt.response_payload.get("request_fingerprint") == expected:
            return receipt.external_ref, expected
        return receipt.external_ref, "0" * 64

    def rollback(self, request: GovernedActionRequest, receipt: AdapterReceipt) -> AdapterReceipt:
        # Rollback is another append-only instruction; it never deletes the
        # original receipt, which keeps audit and reconciliation replayable.
        self._path.parent.mkdir(parents=True, exist_ok=True)
        executed_at = datetime.now(timezone.utc)
        record = {
            "action_id": request.action_id,
            "rollback_of": receipt.external_ref,
            "executed_at": executed_at.isoformat(),
        }
        with self._path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        return AdapterReceipt(
            external_ref=f"file://{self._path.resolve()}#{request.action_id}:rollback",
            status="succeeded",
            response_payload=record,
            executed_at=executed_at,
        )


@dataclass(frozen=True)
class ActionExecutionResult:
    receipt: AdapterReceipt
    reconciliation: ReconciliationRecord
    outcome_link: ActionOutcomeLink


class GovernedActionBroker:
    """Broker that prevents unapproved or non-idempotent external writes."""

    def __init__(
        self,
        *,
        adapter: ActionAdapter,
        reconciliation: ReconciliationLedger | None = None,
    ) -> None:
        self._adapter = adapter
        self._reconciliation = reconciliation or ReconciliationLedger()
        self._dry_runs: dict[str, tuple[str, DryRunResult]] = {}
        self._executions: dict[str, ActionExecutionResult] = {}

    @property
    def reconciliation(self) -> ReconciliationLedger:
        return self._reconciliation

    def dry_run(self, request: GovernedActionRequest, *, actor: str) -> DryRunResult:
        self._authorize(request, actor)
        validation = self._adapter.validate(request)
        if not validation.accepted:
            raise ValueError(f"adapter validation failed: {validation.reason}")
        preview = self._adapter.dry_run(request)
        if not preview.accepted:
            raise ValueError("adapter dry-run was rejected")
        self._dry_runs[request.action_id] = (_fingerprint(request), preview)
        return preview

    def execute(self, request: GovernedActionRequest, *, actor: str) -> ActionExecutionResult:
        self._authorize(request, actor)
        fingerprint = _fingerprint(request)
        existing = self._executions.get(request.action_id)
        if existing is not None:
            if existing.reconciliation.expected_fingerprint != fingerprint:
                raise ValueError("action idempotency conflict")
            return existing
        dry_run = self._dry_runs.get(request.action_id)
        if dry_run is None or dry_run[0] != fingerprint:
            raise ValueError("action requires a matching dry-run before execute")
        receipt = self._adapter.execute(request)
        external_ref, observed_fingerprint = self._adapter.reconcile(request, receipt)
        reconciliation = self._reconciliation.record(
            action_id=request.action_id,
            external_ref=external_ref,
            expected_fingerprint=fingerprint,
            observed_fingerprint=observed_fingerprint,
            observed_at=receipt.executed_at,
        )
        outcome_link = ActionOutcomeLink(
            outcome_id=f"outcome-link:{request.action_id}",
            action_id=request.action_id,
            decision_id=request.decision_id,
            target_id=request.target_id,
            status=receipt.status,
            external_ref=receipt.external_ref,
            executed_at=receipt.executed_at,
            ontology_release_id=request.ontology_release_id,
            ontology_version=request.ontology_version,
            prediction_ids=request.prediction_ids,
            feature_snapshot_id=request.feature_snapshot_id,
            lineage_refs=tuple(
                dict.fromkeys(
                    (
                        *request.lineage_refs,
                        f"urn:aifde:reconciliation:{reconciliation.reconciliation_id}",
                    )
                )
            ),
        )
        result = ActionExecutionResult(receipt, reconciliation, outcome_link)
        self._executions[request.action_id] = result
        return result

    def execute_with_chain(
        self,
        snapshot: FeatureSnapshot,
        predictions: Iterable[PredictionArtifact],
        decision: DecisionCandidate,
        request: GovernedActionRequest,
        *,
        actor: str,
    ) -> ActionExecutionResult:
        """Validate the complete computation chain before the adapter write."""

        if not isinstance(snapshot, FeatureSnapshot):
            raise TypeError("snapshot must be a FeatureSnapshot")
        if not isinstance(decision, DecisionCandidate):
            raise TypeError("decision must be a DecisionCandidate")
        if not isinstance(request, GovernedActionRequest):
            raise TypeError("request must be a GovernedActionRequest")
        prediction_items = tuple(predictions)
        ComputationChainValidator.validate(
            snapshot,
            *prediction_items,
            decision,
            request,
        )
        return self.execute(request, actor=actor)

    @staticmethod
    def _authorize(request: GovernedActionRequest, actor: str) -> None:
        if not isinstance(request, GovernedActionRequest):
            raise TypeError("request must be a GovernedActionRequest")
        actor = _nonblank(actor, "actor")
        if request.approval_status != "approved":
            raise PermissionError("action requires approved status")
        if request.validation_status != "passed":
            raise PermissionError("action requires passed validation")


__all__ = [
    "ActionAdapter",
    "ActionExecutionResult",
    "AdapterReceipt",
    "AdapterValidation",
    "DryRunResult",
    "GovernedActionBroker",
    "JsonlFileActionAdapter",
    "MemoryActionAdapter",
]
