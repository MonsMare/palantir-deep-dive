from __future__ import annotations

from datetime import datetime, timezone

from aifde.actions.reconciliation import ReconciliationLedger


UTC = timezone.utc


def test_reconciliation_is_append_only_and_detects_external_mismatch() -> None:
    ledger = ReconciliationLedger()
    matched = ledger.record(
        action_id="action:1",
        external_ref="erp://PO-001",
        expected_fingerprint="a" * 64,
        observed_fingerprint="a" * 64,
        observed_at=datetime(2026, 8, 14, 10, tzinfo=UTC),
    )
    assert matched.status == "matched"

    remediation = ledger.record(
        action_id="action:2",
        external_ref="erp://PO-002",
        expected_fingerprint="b" * 64,
        observed_fingerprint="c" * 64,
        observed_at=datetime(2026, 8, 14, 10, tzinfo=UTC),
    )
    assert remediation.status == "remediation"
    assert ledger.get("action:2").status == "remediation"
