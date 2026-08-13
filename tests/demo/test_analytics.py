from __future__ import annotations

from datetime import datetime, timezone

from software_delivery_demo.analytics import (
    build_project_snapshot,
    calculate_capacity_metrics,
    calculate_delivery_metrics,
    calculate_dependency_metrics,
    calculate_requirement_metrics,
)


def test_snapshot_excludes_events_after_observation(products) -> None:
    as_of = datetime(2026, 3, 1, tzinfo=timezone.utc)
    snapshot = build_project_snapshot(products, as_of)
    assert snapshot.events.filter(snapshot.events["event_time"] > as_of).height == 0
    assert snapshot.as_of_time == as_of
    assert snapshot.evidence_snapshot_id


def test_delivery_metrics_have_required_baseline_columns(snapshot) -> None:
    metrics = calculate_delivery_metrics(snapshot)
    assert {"team_id", "completed_count", "median_cycle_days"} <= set(metrics.columns)


def test_all_metric_families_have_rows(snapshot) -> None:
    assert calculate_requirement_metrics(snapshot).height > 0
    assert calculate_capacity_metrics(snapshot).height > 0
    assert calculate_dependency_metrics(snapshot).height > 0


def test_snapshot_watermark_is_not_after_as_of(snapshot) -> None:
    assert snapshot.source_watermark <= snapshot.as_of_time
