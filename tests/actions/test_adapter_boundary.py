from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aifde.actions.adapters import (
    AdapterReceipt,
    GovernedActionBroker,
    JsonlFileActionAdapter,
    MemoryActionAdapter,
)
from aifde.ontology.computation import GovernedActionRequest


UTC = timezone.utc


def _request(action_id: str = "action:1") -> GovernedActionRequest:
    return GovernedActionRequest(
        action_id=action_id,
        decision_id="decision:1",
        target_id="PO-001",
        action_type="expedite_supplier_followup",
        parameters={"channel": "phone"},
        ontology_release_id="ontology-release:1",
        ontology_version="0.1.0",
        prediction_ids=("prediction:1",),
        feature_snapshot_id="feature-snapshot:1",
        as_of_time=datetime(2026, 8, 14, 9, tzinfo=UTC),
        requested_at=datetime(2026, 8, 14, 10, tzinfo=UTC),
        requested_by="procurement-agent",
        policy_id="policy:procurement",
        policy_version="1.0.0",
        approval_id="approval:1",
        approval_status="approved",
        validation_id="validation:1",
        validation_status="passed",
        lineage_refs=("evidence:1",),
    )


def test_dry_run_does_not_write_and_execute_requires_dry_run() -> None:
    adapter = MemoryActionAdapter()
    broker = GovernedActionBroker(adapter=adapter)
    request = _request()

    with pytest.raises(ValueError, match="dry-run"):
        broker.execute(request, actor="release-owner-1")
    preview = broker.dry_run(request, actor="release-owner-1")
    assert preview.accepted
    assert adapter.execute_count == 0


def test_approved_execution_is_idempotent_and_returns_reconciliation() -> None:
    adapter = MemoryActionAdapter()
    broker = GovernedActionBroker(adapter=adapter)
    request = _request()
    broker.dry_run(request, actor="release-owner-1")

    first = broker.execute(request, actor="release-owner-1")
    second = broker.execute(request, actor="release-owner-1")

    assert isinstance(first.receipt, AdapterReceipt)
    assert first.receipt.external_ref == second.receipt.external_ref
    assert adapter.execute_count == 1
    assert first.reconciliation.status == "matched"
    assert first.outcome_link.action_id == request.action_id


def test_unapproved_or_adapter_failure_never_looks_like_success() -> None:
    adapter = MemoryActionAdapter(fail=True)
    broker = GovernedActionBroker(adapter=adapter)
    request = _request()
    broker.dry_run(request, actor="release-owner-1")
    failed = broker.execute(request, actor="release-owner-1")

    assert failed.receipt.status == "failed"
    assert failed.outcome_link.status == "failed"
    assert failed.reconciliation.status == "remediation"

    unapproved = request.model_copy(update={"approval_status": "pending"})
    with pytest.raises(PermissionError, match="approved"):
        GovernedActionBroker(adapter=MemoryActionAdapter()).dry_run(
            unapproved, actor="release-owner-1"
        )


def test_file_adapter_writes_only_after_governed_execute(tmp_path) -> None:
    path = tmp_path / "external-actions.jsonl"
    broker = GovernedActionBroker(adapter=JsonlFileActionAdapter(path))
    request = _request("action:file")
    broker.dry_run(request, actor="release-owner-1")
    assert not path.exists()
    result = broker.execute(request, actor="release-owner-1")
    assert path.exists()
    assert result.reconciliation.status == "matched"
