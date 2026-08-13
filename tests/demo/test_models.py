from __future__ import annotations

from datetime import datetime, timezone

import polars as pl

from software_delivery_demo.features import build_features
from software_delivery_demo.labels import build_labels
from software_delivery_demo.models import (
    BaselineModel,
    DeliveryModel,
    EvaluationReport,
    ModelVersion,
    evaluate_model,
    release_model,
    temporal_split,
)


def test_temporal_split_has_no_future_training_rows(products) -> None:
    features = build_features(
        products,
        [
            datetime(2026, 1, 15, tzinfo=timezone.utc),
            datetime(2026, 3, 1, tzinfo=timezone.utc),
            datetime(2026, 5, 1, tzinfo=timezone.utc),
        ],
    )
    train, test = temporal_split(features, cutoff=datetime(2026, 5, 1, tzinfo=timezone.utc))
    assert train["as_of_time"].max() < test["as_of_time"].min()


def test_baseline_and_candidate_produce_traceable_predictions(products) -> None:
    observations = [datetime(2026, 1, 15, tzinfo=timezone.utc), datetime(2026, 3, 1, tzinfo=timezone.utc)]
    features = build_features(products, observations)
    labels = build_labels(products, observations)
    baseline = BaselineModel.fit(features, labels)
    baseline_predictions = baseline.predict(features)
    model = DeliveryModel.fit(features, labels)
    predictions = model.predict(features)
    assert baseline_predictions.height == predictions.height
    assert {"entity_id", "as_of_time", "p50_days", "p80_days", "late_probability", "model_version", "feature_snapshot_id"} <= set(predictions.columns)
    assert model.model_version.model_version


def test_evaluation_records_baseline_comparison(products) -> None:
    observations = [datetime(2026, 1, 15, tzinfo=timezone.utc), datetime(2026, 3, 1, tzinfo=timezone.utc)]
    features = build_features(products, observations)
    labels = build_labels(products, observations)
    baseline = BaselineModel.fit(features, labels).predict(features)
    predictions = DeliveryModel.fit(features, labels).predict(features)
    report = evaluate_model(predictions, labels, baseline)
    assert report.baseline_mae is not None
    assert report.model_mae is not None
    assert report.p80_coverage is not None
    assert report.temporal_windows


def test_model_not_released_when_worse_than_baseline() -> None:
    report = EvaluationReport(
        baseline_mae=2.0,
        model_mae=2.1,
        p80_coverage=0.95,
        calibration=0.1,
        group_metrics={},
        leakage_passed=True,
        temporal_windows=["2026-Q1"],
    )
    decision = release_model(report)
    assert decision.released is False
    assert decision.reason == "MODEL_NOT_BETTER_THAN_BASELINE"


def test_no_label_history_falls_back_to_baseline() -> None:
    features = pl.DataFrame(
        {
            "entity_id": ["wi-1"],
            "as_of_time": [datetime(2026, 1, 1, tzinfo=timezone.utc)],
            "feature_snapshot_id": ["snap-1"],
            "estimate_hours": [8.0],
            "team_id": ["team-1"],
            "task_type": ["feature"],
        }
    )
    labels = pl.DataFrame()
    predictions = BaselineModel.fit(features, labels).predict(features)
    assert predictions[0, "model_version"] == "baseline-median-v1"
