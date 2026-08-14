from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aifde.ml.evaluation import TemporalEvaluator, temporal_split


UTC = timezone.utc


def _rows() -> list[dict]:
    return [
        {"entity_id": "A", "as_of_time": datetime(2026, 8, 1, tzinfo=UTC), "available_at": datetime(2026, 8, 1, tzinfo=UTC)},
        {"entity_id": "B", "as_of_time": datetime(2026, 8, 2, tzinfo=UTC), "available_at": datetime(2026, 8, 2, tzinfo=UTC)},
        {"entity_id": "A", "as_of_time": datetime(2026, 8, 3, tzinfo=UTC), "available_at": datetime(2026, 8, 3, tzinfo=UTC)},
        {"entity_id": "B", "as_of_time": datetime(2026, 8, 4, tzinfo=UTC), "available_at": datetime(2026, 8, 4, tzinfo=UTC)},
    ]


def test_temporal_split_has_disjoint_time_windows_and_rejects_future_availability() -> None:
    train, test = temporal_split(_rows(), cutoff=datetime(2026, 8, 3, tzinfo=UTC))
    assert {row["as_of_time"].day for row in train} == {1, 2}
    assert {row["as_of_time"].day for row in test} == {3, 4}

    leaked = _rows()
    leaked[0]["available_at"] = datetime(2026, 8, 2, tzinfo=UTC)
    with pytest.raises(ValueError, match="available_at"):
        temporal_split(leaked, cutoff=datetime(2026, 8, 3, tzinfo=UTC))


def test_temporal_evaluation_compares_baseline_and_emits_release_eligibility() -> None:
    labels = [
        {"entity_id": "A", "as_of_time": _rows()[2]["as_of_time"], "value": 2.0, "late": 1},
        {"entity_id": "B", "as_of_time": _rows()[3]["as_of_time"], "value": 4.0, "late": 0},
    ]
    predictions = [
        {"entity_id": "A", "as_of_time": labels[0]["as_of_time"], "value": 2.5, "p80": 3.0, "probability": 0.8},
        {"entity_id": "B", "as_of_time": labels[1]["as_of_time"], "value": 4.2, "p80": 5.0, "probability": 0.2},
    ]
    baseline = [
        {"entity_id": "A", "as_of_time": labels[0]["as_of_time"], "value": 5.0, "p80": 6.0, "probability": 0.5},
        {"entity_id": "B", "as_of_time": labels[1]["as_of_time"], "value": 5.0, "p80": 6.0, "probability": 0.5},
    ]

    report = TemporalEvaluator().evaluate(predictions, labels, baseline)

    assert report.model_mae < report.baseline_mae
    assert report.p80_coverage == 1.0
    assert report.leakage_passed
    assert report.release_eligible
    assert report.report_hash


def test_temporal_evaluation_blocks_missing_or_future_aligned_prediction() -> None:
    labels = [{"entity_id": "A", "as_of_time": datetime(2026, 8, 3, tzinfo=UTC), "value": 2.0, "late": 1}]
    bad_prediction = [{"entity_id": "A", "as_of_time": datetime(2026, 8, 4, tzinfo=UTC), "value": 2.0}]
    with pytest.raises(ValueError, match="alignment"):
        TemporalEvaluator().evaluate(bad_prediction, labels, bad_prediction)
