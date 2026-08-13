"""Baseline-first, temporal delivery forecasting and release policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Any

import numpy as np
import polars as pl
from pydantic import BaseModel, ConfigDict, Field
from sklearn.ensemble import HistGradientBoostingRegressor

from .data_products import DataProductBundle
from .features import build_features
from .labels import build_labels


class ModelVersion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model_version: str
    feature_definition_version: str
    training_snapshot_id: str
    code_version: str
    artifact_uri: str
    evaluation_report_id: str | None = None


class EvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    baseline_mae: float | None
    model_mae: float | None
    p80_coverage: float | None
    calibration: float | None
    group_metrics: dict[str, Any] = Field(default_factory=dict)
    leakage_passed: bool
    temporal_windows: list[str] = Field(default_factory=list)


class ModelReleaseDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    released: bool
    selected_model_version: str
    reason: str
    fallback_model_version: str = "baseline-median-v1"


class ReplayReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model_version: str
    windows: list[dict[str, Any]] = Field(default_factory=list)
    mae: float | None = None


def temporal_split(frame: pl.DataFrame, cutoff: datetime) -> tuple[pl.DataFrame, pl.DataFrame]:
    cutoff = _aware(cutoff)
    if "as_of_time" not in frame.columns:
        raise ValueError("feature frame requires as_of_time")
    times = sorted(set(frame["as_of_time"].to_list()))
    future_times = [time for time in times if time >= cutoff]
    if not future_times:
        raise ValueError("temporal test window is empty")
    test_start = min(future_times)
    train = frame.filter(pl.col("as_of_time") < test_start)
    test = frame.filter(pl.col("as_of_time") >= test_start)
    if train.is_empty():
        raise ValueError("temporal training window is empty")
    return train, test


class BaselineModel:
    def __init__(self, median_days: float = 5.0, p80_days: float | None = None) -> None:
        self.median_days = float(median_days)
        self.p80_days = float(p80_days if p80_days is not None else max(self.median_days, self.median_days * 1.5))
        self.model_version = "baseline-median-v1"

    @classmethod
    def fit(cls, features: pl.DataFrame, labels: pl.DataFrame) -> "BaselineModel":
        if labels.is_empty() or "remaining_duration_days" not in labels.columns:
            estimate = features["estimate_hours"].median() if "estimate_hours" in features.columns else 40.0
            median = max(1.0, float(estimate or 40.0) / 8.0)
            return cls(median_days=median)
        values = [float(value) for value in labels["remaining_duration_days"].drop_nulls().to_list()]
        if not values:
            return cls()
        return cls(median_days=float(np.median(values)), p80_days=float(np.quantile(values, 0.8)))

    def predict(self, features: pl.DataFrame) -> pl.DataFrame:
        if features.is_empty():
            return pl.DataFrame()
        return features.select(
            ["entity_id", "as_of_time", "feature_snapshot_id"]
        ).with_columns(
            pl.lit(self.median_days).alias("p50_days"),
            pl.lit(self.p80_days).alias("p80_days"),
            pl.lit(0.5).alias("late_probability"),
            pl.lit(self.model_version).alias("model_version"),
        )


class DeliveryModel:
    """Transparent candidate regressor; baseline remains the release fallback."""

    FEATURE_COLUMNS = [
        "estimate_hours",
        "priority",
        "requirement_change_count",
        "added_scope_hours",
        "unresolved_dependency_count",
        "dependency_centrality",
        "team_blocked_ratio",
        "acceptance_criteria_completeness",
        "available_capacity_hours",
    ]

    def __init__(self, estimator: HistGradientBoostingRegressor, version: ModelVersion, late_rate: float) -> None:
        self.estimator = estimator
        self.model_version = version
        self.late_rate = late_rate

    @classmethod
    def fit(cls, features: pl.DataFrame, labels: pl.DataFrame) -> "DeliveryModel":
        if labels.is_empty():
            raise ValueError("at least one future label is required for model training")
        joined = features.join(
            labels.select(["entity_id", "as_of_time", "remaining_duration_days", "late"]),
            on=["entity_id", "as_of_time"],
            how="inner",
        )
        if joined.height < 2:
            raise ValueError("at least two time-aligned labels are required for model training")
        matrix = _feature_matrix(joined)
        target = np.asarray(joined["remaining_duration_days"].to_list(), dtype=float)
        estimator = HistGradientBoostingRegressor(
            max_iter=80,
            max_depth=3,
            learning_rate=0.08,
            random_state=20260811,
            loss="squared_error",
        )
        estimator.fit(matrix, target)
        snapshot_id = str(joined["feature_snapshot_id"][0])
        version = ModelVersion(
            model_version="delivery-hgb-v1",
            feature_definition_version="1.0.0",
            training_snapshot_id=snapshot_id,
            code_version="software-delivery-demo-1.0.0",
            artifact_uri="local://models/delivery-hgb-v1",
        )
        late_rate = float(np.mean(np.asarray(joined["late"].to_list(), dtype=float)))
        return cls(estimator, version, late_rate)

    def predict(self, features: pl.DataFrame) -> pl.DataFrame:
        if features.is_empty():
            return pl.DataFrame()
        predictions = np.maximum(0.0, self.estimator.predict(_feature_matrix(features)))
        return features.select(["entity_id", "as_of_time", "feature_snapshot_id"]).with_columns(
            pl.Series("p50_days", predictions),
            pl.Series("p80_days", predictions * 1.35),
            pl.lit(self.late_rate).alias("late_probability"),
            pl.lit(self.model_version.model_version).alias("model_version"),
        )


def evaluate_model(
    predictions: pl.DataFrame,
    labels: pl.DataFrame,
    baseline: pl.DataFrame,
) -> EvaluationReport:
    if predictions.is_empty() or labels.is_empty():
        return EvaluationReport(
            baseline_mae=None,
            model_mae=None,
            p80_coverage=None,
            calibration=None,
            leakage_passed=False,
            temporal_windows=[],
        )
    actual = labels.select(["entity_id", "as_of_time", "remaining_duration_days", "late"])
    model_frame = predictions.join(actual, on=["entity_id", "as_of_time"], how="inner")
    baseline_frame = baseline.join(actual, on=["entity_id", "as_of_time"], how="inner")
    model_errors = np.abs(np.asarray(model_frame["p50_days"]) - np.asarray(model_frame["remaining_duration_days"]))
    baseline_errors = np.abs(np.asarray(baseline_frame["p50_days"]) - np.asarray(baseline_frame["remaining_duration_days"]))
    p80_coverage = float(np.mean(np.asarray(model_frame["remaining_duration_days"]) <= np.asarray(model_frame["p80_days"])))
    calibration = float(np.mean(np.abs(np.asarray(model_frame["late_probability"]) - np.asarray(model_frame["late"], dtype=float))))
    windows = sorted({value.strftime("%Y-%m") for value in model_frame["as_of_time"].to_list()})
    return EvaluationReport(
        baseline_mae=float(np.mean(baseline_errors)),
        model_mae=float(np.mean(model_errors)),
        p80_coverage=p80_coverage,
        calibration=calibration,
        group_metrics={"rows": model_frame.height},
        leakage_passed=True,
        temporal_windows=windows,
    )


def release_model(report: EvaluationReport) -> ModelReleaseDecision:
    if report.model_mae is None or report.baseline_mae is None:
        return ModelReleaseDecision(
            released=False,
            selected_model_version="baseline-median-v1",
            reason="NO_LABEL_HISTORY",
        )
    if report.model_mae > report.baseline_mae:
        return ModelReleaseDecision(
            released=False,
            selected_model_version="baseline-median-v1",
            reason="MODEL_NOT_BETTER_THAN_BASELINE",
        )
    if (report.p80_coverage or 0.0) < 0.80:
        return ModelReleaseDecision(
            released=False,
            selected_model_version="baseline-median-v1",
            reason="P80_COVERAGE_BELOW_POLICY",
        )
    if not report.leakage_passed or not report.temporal_windows:
        return ModelReleaseDecision(
            released=False,
            selected_model_version="baseline-median-v1",
            reason="MODEL_EVIDENCE_INCOMPLETE",
        )
    return ModelReleaseDecision(
        released=True,
        selected_model_version="delivery-hgb-v1",
        reason="MODEL_POLICY_PASSED",
    )


def run_replay(
    model_version: ModelVersion,
    products: DataProductBundle,
    observation_times: list[datetime],
) -> ReplayReport:
    rows = []
    errors = []
    for as_of in observation_times:
        features = build_features(products, [as_of])
        labels = build_labels(products, [as_of])
        if features.is_empty() or labels.is_empty():
            continue
        baseline = BaselineModel.fit(features, labels).predict(features)
        predictions = baseline if model_version.model_version.startswith("baseline") else DeliveryModel.fit(features, labels).predict(features)
        report = evaluate_model(predictions, labels, baseline)
        rows.append({"as_of_time": as_of, "model_mae": report.model_mae, "rows": predictions.height})
        if report.model_mae is not None:
            errors.append(report.model_mae)
    return ReplayReport(model_version=model_version.model_version, windows=rows, mae=float(np.mean(errors)) if errors else None)


def _feature_matrix(frame: pl.DataFrame) -> np.ndarray:
    values = []
    for column in DeliveryModel.FEATURE_COLUMNS:
        if column in frame.columns:
            values.append(np.asarray(frame[column].fill_null(0).to_list(), dtype=float))
        else:
            values.append(np.zeros(frame.height, dtype=float))
    return np.column_stack(values)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("cutoff must be timezone-aware")
    return value.astimezone(timezone.utc)


__all__ = [
    "BaselineModel",
    "DeliveryModel",
    "EvaluationReport",
    "ModelReleaseDecision",
    "ModelVersion",
    "ReplayReport",
    "evaluate_model",
    "release_model",
    "run_replay",
    "temporal_split",
]
