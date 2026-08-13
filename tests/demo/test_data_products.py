from __future__ import annotations

import polars as pl

from software_delivery_demo.data_products import (
    build_data_products,
    run_quality_checks,
)


def test_work_item_lifecycle_has_one_row_per_state_interval(products) -> None:
    lifecycle = products.work_item_lifecycle
    assert (
        lifecycle.select(["work_item_id", "state_entered_at"])
        .unique()
        .height
        == lifecycle.height
    )


def test_actual_completion_is_after_start(products) -> None:
    completed = products.work_item_lifecycle.filter(pl.col("state") == "done")
    assert (completed["state_exited_at"] >= completed["state_entered_at"]).all()


def test_invalid_dependency_cycle_fails_quality(bundle_with_dependency_cycle) -> None:
    products = build_data_products(bundle_with_dependency_cycle)
    report = run_quality_checks(products)
    assert report.passed is False
    assert "dependency.no-cycle" in report.failed_rule_ids


def test_products_expose_declared_grains(products) -> None:
    assert products.requirements.select("requirement_id").n_unique() == products.requirements.height
    assert products.change_events.select("change_id").n_unique() == products.change_events.height
    assert {"team_id", "sprint_id", "capacity_hours"} <= set(products.capacity.columns)


def test_clean_products_emit_evidence_refs(products) -> None:
    report = run_quality_checks(products)
    assert report.passed is True
    assert report.issue_count == 0
    assert report.evidence_refs
