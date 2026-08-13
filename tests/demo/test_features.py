from __future__ import annotations

from datetime import datetime, timezone

import polars as pl

from software_delivery_demo.features import (
    build_features,
    build_features_with_intentional_leak,
    check_no_leakage,
    load_feature_definitions,
)
from software_delivery_demo.labels import build_labels


def test_feature_definition_contains_time_and_lineage_fields() -> None:
    definition = load_feature_definitions()[0]
    assert definition.entity_type
    assert definition.grain
    assert definition.as_of_time
    assert definition.availability_lag
    assert definition.lineage
    assert definition.version
    assert definition.leakage_policy


def test_features_do_not_include_future_events(products) -> None:
    as_of_times = [datetime(2026, 3, 1, tzinfo=timezone.utc)]
    features = build_features(products, as_of_times)
    assert features.filter(pl.col("source_event_time") > pl.col("as_of_time")).height == 0
    assert features.filter(pl.col("source_observed_time") > pl.col("as_of_time")).height == 0


def test_labels_are_future_outcomes_and_features_have_snapshot_identity(products) -> None:
    observation_times = [datetime(2026, 3, 1, tzinfo=timezone.utc)]
    labels = build_labels(products, observation_times)
    features = build_features(products, observation_times)
    assert labels.height > 0
    assert {"entity_id", "as_of_time", "remaining_duration_days", "late"} <= set(labels.columns)
    assert features["feature_snapshot_id"].n_unique() == 1


def test_leakage_check_catches_actual_completion_date(products) -> None:
    features = build_features_with_intentional_leak(products)
    observation_times = [datetime(2026, 3, 1, tzinfo=timezone.utc)]
    labels = build_labels(products, observation_times)
    report = check_no_leakage(features, labels, load_feature_definitions())
    assert report.passed is False
    assert "actual_complete_at" in report.leaked_columns


def test_clean_feature_frame_passes_leakage_check(products) -> None:
    observation_times = [datetime(2026, 3, 1, tzinfo=timezone.utc)]
    features = build_features(products, observation_times)
    labels = build_labels(products, observation_times)
    report = check_no_leakage(features, labels, load_feature_definitions())
    assert report.passed is True
