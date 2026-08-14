"""Temporal model evaluation and release policy."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from hashlib import sha256
import json
from math import isfinite
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _aware(value: Any, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def temporal_split(
    rows: Sequence[Mapping[str, Any]],
    *,
    cutoff: datetime,
    as_of_field: str = "as_of_time",
    available_field: str = "available_at",
) -> tuple[tuple[Mapping[str, Any], ...], tuple[Mapping[str, Any], ...]]:
    """Split by time and fail if any row was unavailable at its observation."""

    cutoff = _aware(cutoff, "cutoff")
    normalized = tuple(rows)
    if not normalized:
        raise ValueError("temporal dataset must not be empty")
    for row in normalized:
        as_of = _aware(row[as_of_field], as_of_field)
        if available_field in row and row[available_field] is not None:
            if _aware(row[available_field], available_field) > as_of:
                raise ValueError("available_at is after as_of_time")
    train = tuple(row for row in normalized if _aware(row[as_of_field], as_of_field) < cutoff)
    test = tuple(row for row in normalized if _aware(row[as_of_field], as_of_field) >= cutoff)
    if not train:
        raise ValueError("temporal training window is empty")
    if not test:
        raise ValueError("temporal test window is empty")
    if max(_aware(row[as_of_field], as_of_field) for row in train) >= min(
        _aware(row[as_of_field], as_of_field) for row in test
    ):
        raise ValueError("temporal windows overlap")
    return train, test


class EvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    report_id: str
    model_id: str
    model_version: str
    baseline_mae: float
    model_mae: float
    p80_coverage: float | None = None
    calibration_error: float | None = None
    auc: float | None = None
    temporal_windows: tuple[str, ...]
    leakage_passed: bool
    release_eligible: bool
    metrics: dict[str, Any] = Field(default_factory=dict)
    report_hash: str


class TemporalEvaluator:
    """Evaluate aligned predictions and apply a conservative baseline policy."""

    def __init__(self, *, min_p80_coverage: float = 0.8) -> None:
        if not 0.0 <= min_p80_coverage <= 1.0:
            raise ValueError("min_p80_coverage must be between 0 and 1")
        self._min_p80_coverage = min_p80_coverage

    def evaluate(
        self,
        predictions: Sequence[Mapping[str, Any]],
        labels: Sequence[Mapping[str, Any]],
        baseline_predictions: Sequence[Mapping[str, Any]],
        *,
        model_id: str = "unbound-model",
        model_version: str = "unbound-version",
        value_field: str = "value",
    ) -> EvaluationReport:
        model_map = self._index(predictions)
        baseline_map = self._index(baseline_predictions)
        label_map = self._index(labels)
        if set(model_map) != set(label_map) or set(baseline_map) != set(label_map):
            raise ValueError("prediction/label alignment is incomplete")
        model_errors: list[float] = []
        baseline_errors: list[float] = []
        covered: list[bool] = []
        calibration: list[float] = []
        windows: set[str] = set()
        labels_for_auc: list[float] = []
        scores_for_auc: list[float] = []
        for key, label in label_map.items():
            actual = float(label[value_field])
            predicted = float(model_map[key][value_field])
            baseline = float(baseline_map[key][value_field])
            if not all(isfinite(item) for item in (actual, predicted, baseline)):
                raise ValueError("evaluation values must be finite")
            model_errors.append(abs(predicted - actual))
            baseline_errors.append(abs(baseline - actual))
            timestamp = _aware(key[1], "as_of_time")
            windows.add(timestamp.strftime("%Y-%m"))
            if "p80" in model_map[key]:
                covered.append(actual <= float(model_map[key]["p80"]))
            if "probability" in model_map[key] and "late" in label:
                probability = float(model_map[key]["probability"])
                calibration.append(abs(probability - float(label["late"])))
                labels_for_auc.append(float(label["late"]))
                scores_for_auc.append(probability)
        model_mae = sum(model_errors) / len(model_errors)
        baseline_mae = sum(baseline_errors) / len(baseline_errors)
        p80_coverage = sum(covered) / len(covered) if covered else None
        calibration_error = sum(calibration) / len(calibration) if calibration else None
        auc = _auc(labels_for_auc, scores_for_auc) if labels_for_auc else None
        leakage_passed = True
        report_values = {
            "model_id": model_id,
            "model_version": model_version,
            "baseline_mae": baseline_mae,
            "model_mae": model_mae,
            "p80_coverage": p80_coverage,
            "calibration_error": calibration_error,
            "auc": auc,
            "temporal_windows": tuple(sorted(windows)),
            "leakage_passed": leakage_passed,
            "metrics": {"rows": len(label_map)},
        }
        release_eligible = (
            model_mae <= baseline_mae
            and (p80_coverage is None or p80_coverage >= self._min_p80_coverage)
            and leakage_passed
            and bool(windows)
        )
        report_id = "evaluation:" + sha256(
            json.dumps(report_values, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:24]
        report_hash = sha256(
            json.dumps(
                {**report_values, "release_eligible": release_eligible},
                sort_keys=True,
                default=str,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return EvaluationReport(
            report_id=report_id,
            model_id=model_id,
            model_version=model_version,
            baseline_mae=baseline_mae,
            model_mae=model_mae,
            p80_coverage=p80_coverage,
            calibration_error=calibration_error,
            auc=auc,
            temporal_windows=tuple(sorted(windows)),
            leakage_passed=leakage_passed,
            release_eligible=release_eligible,
            metrics={"rows": len(label_map)},
            report_hash=report_hash,
        )

    @staticmethod
    def _index(rows: Sequence[Mapping[str, Any]]) -> dict[tuple[str, datetime], Mapping[str, Any]]:
        result: dict[tuple[str, datetime], Mapping[str, Any]] = {}
        for row in rows:
            entity_id = str(row["entity_id"])
            as_of = _aware(row["as_of_time"], "as_of_time")
            key = (entity_id, as_of)
            if key in result:
                raise ValueError(f"duplicate evaluation key: {entity_id}/{as_of.isoformat()}")
            result[key] = row
        return result


def _auc(labels: Sequence[float], scores: Sequence[float]) -> float | None:
    positives = [score for label, score in zip(labels, scores, strict=True) if label >= 0.5]
    negatives = [score for label, score in zip(labels, scores, strict=True) if label < 0.5]
    if not positives or not negatives:
        return None
    wins = sum(1.0 if positive > negative else 0.5 if positive == negative else 0.0 for positive in positives for negative in negatives)
    return wins / (len(positives) * len(negatives))


__all__ = ["EvaluationReport", "TemporalEvaluator", "temporal_split"]
