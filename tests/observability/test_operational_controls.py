from __future__ import annotations

import pytest

from aifde.deployment.health import ReadinessChecker
from aifde.builder.persistence import SQLiteBuilderRegistry
from aifde.observability.audit import AppendOnlyAuditLog, AuditIntegrityError
from aifde.observability.metrics import MetricsRegistry


def test_metrics_are_aggregated_by_name_and_labels() -> None:
    metrics = MetricsRegistry()
    metrics.increment("ontology.compile", labels={"domain": "supplier-delay"})
    metrics.increment("ontology.compile", labels={"domain": "supplier-delay"}, amount=2)
    metrics.observe("model.mae", 0.25, labels={"model": "v1"})

    snapshot = metrics.snapshot()

    assert snapshot["ontology.compile|domain=supplier-delay"] == 3
    assert snapshot["model.mae|model=v1"] == pytest.approx(0.25)


def test_audit_log_detects_tampering_and_is_append_only() -> None:
    audit = AppendOnlyAuditLog()
    event = audit.append(
        event_type="ontology.release",
        actor="release-owner-1",
        subject_id="ontology-release:1",
        payload={"ontology_hash": "a" * 64},
    )

    assert audit.verify()
    assert event.sequence == 1
    audit._events[0] = event.model_copy(update={"payload_hash": "0" * 64})  # noqa: SLF001
    with pytest.raises(AuditIntegrityError, match="payload hash"):
        audit.verify()


def test_readiness_fails_closed_when_required_dependency_is_down() -> None:
    report = ReadinessChecker(
        {
            "persistence": lambda: True,
            "model-registry": lambda: False,
            "policy": lambda: True,
        }
    ).check()

    assert report.ready is False
    assert report.checks["model-registry"].status == "not_ready"


def test_sqlite_builder_registry_replays_audit_events(tmp_path) -> None:
    audit = AppendOnlyAuditLog()
    event = audit.append(
        event_type="agent.run",
        actor="ontology-engineer",
        subject_id="agent-run:1",
        payload={"status": "succeeded"},
    )
    database = tmp_path / "audit.db"
    registry = SQLiteBuilderRegistry(database)
    registry.append_audit_event(event)
    assert registry.list_audit_events()[0]["event_id"] == event.event_id
    assert registry.verify_audit_events()
    registry.close()

    reopened = SQLiteBuilderRegistry(database)
    assert reopened.verify_audit_events()
    reopened.close()
