"""Replaceable model adapters with a small transparent tabular baseline."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any, Protocol

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor


class ModelAdapter(Protocol):
    def fit(self, rows: Sequence[Mapping[str, Any]], targets: Sequence[float]) -> "FittedModel": ...

    def predict(self, fitted: "FittedModel", rows: Sequence[Mapping[str, Any]]) -> tuple[float, ...]: ...

    def explain(self, fitted: "FittedModel", row: Mapping[str, Any]) -> Mapping[str, Any]: ...


def _number(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"model feature must be numeric: {value!r}") from exc


@dataclass(frozen=True)
class FittedModel:
    estimator: Any
    feature_names: tuple[str, ...]
    model_version: str
    training_data_hash: str
    adapter: "TabularModelAdapter"

    def predict(self, values: dict[str, Any]) -> dict[str, float]:
        value = self.adapter.predict(self, [values])[0]
        return {"value": value, "confidence": 0.5}


class TabularModelAdapter:
    """Numeric tabular adapter; enterprise adapters can implement the same protocol."""

    def __init__(self, feature_names: Sequence[str], *, model_version: str = "tabular-v1") -> None:
        self.feature_names = tuple(str(item) for item in feature_names)
        if not self.feature_names or any(not item.strip() for item in self.feature_names):
            raise ValueError("feature_names must not be empty")
        self.model_version = model_version.strip()
        if not self.model_version:
            raise ValueError("model_version must not be empty")

    def fit(self, rows: Sequence[Mapping[str, Any]], targets: Sequence[float]) -> FittedModel:
        if not rows or not targets or len(rows) != len(targets):
            raise ValueError("training rows and targets must be non-empty and aligned")
        matrix = self._matrix(rows)
        values = np.asarray([_number(item) for item in targets], dtype=float)
        if not np.isfinite(values).all():
            raise ValueError("training targets must be finite")
        estimator = HistGradientBoostingRegressor(
            max_iter=80,
            max_depth=3,
            learning_rate=0.08,
            random_state=20260814,
            loss="squared_error",
        )
        estimator.fit(matrix, values)
        digest = sha256(
            json.dumps(
                {"features": self.feature_names, "rows": [dict(row) for row in rows], "targets": list(values)},
                sort_keys=True,
                default=str,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return FittedModel(
            estimator=estimator,
            feature_names=self.feature_names,
            model_version=self.model_version,
            training_data_hash=digest,
            adapter=self,
        )

    def predict(self, fitted: FittedModel, rows: Sequence[Mapping[str, Any]]) -> tuple[float, ...]:
        if not isinstance(fitted, FittedModel):
            raise TypeError("fitted must be a FittedModel")
        if tuple(fitted.feature_names) != self.feature_names:
            raise ValueError("fitted model feature schema does not match adapter")
        if not rows:
            return ()
        return tuple(float(value) for value in fitted.estimator.predict(self._matrix(rows)))

    def explain(self, fitted: FittedModel, row: Mapping[str, Any]) -> Mapping[str, Any]:
        values = {name: _number(row.get(name)) for name in self.feature_names}
        return {
            "model_version": fitted.model_version,
            "feature_values": values,
            "training_data_hash": fitted.training_data_hash,
        }

    def _matrix(self, rows: Sequence[Mapping[str, Any]]) -> np.ndarray:
        return np.asarray(
            [[_number(row.get(name)) for name in self.feature_names] for row in rows],
            dtype=float,
        )


class BaselineMedianAdapter:
    """Baseline model that is intentionally simple and always explainable."""

    def __init__(self, *, model_version: str = "baseline-median-v1") -> None:
        self.model_version = model_version

    def fit(self, rows: Sequence[Mapping[str, Any]], targets: Sequence[float]) -> FittedModel:
        if not targets:
            raise ValueError("baseline requires targets")
        median = float(np.median(np.asarray([_number(item) for item in targets], dtype=float)))
        return FittedModel(
            estimator=median,
            feature_names=(),
            model_version=self.model_version,
            training_data_hash=sha256(json.dumps(list(targets), default=str).encode("utf-8")).hexdigest(),
            adapter=self,  # type: ignore[arg-type]
        )

    def predict(self, fitted: FittedModel, rows: Sequence[Mapping[str, Any]]) -> tuple[float, ...]:
        return tuple(float(fitted.estimator) for _ in rows)

    def explain(self, fitted: FittedModel, row: Mapping[str, Any]) -> Mapping[str, Any]:
        return {"strategy": "median", "value": float(fitted.estimator)}


__all__ = ["BaselineMedianAdapter", "FittedModel", "ModelAdapter", "TabularModelAdapter"]
