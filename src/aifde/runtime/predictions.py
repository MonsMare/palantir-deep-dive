"""Governed model adapter boundary for Ontology feature snapshots."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from hashlib import sha256
import json
from math import isfinite
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from aifde.ontology.computation import FeatureRecord, FeatureSnapshot, PredictionArtifact


class PredictionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    value: float
    confidence: float = Field(ge=0.0, le=1.0)


class PredictionAdapter(Protocol):
    def predict(self, values: dict[str, Any]) -> PredictionResult | Mapping[str, Any] | float:
        """Return one prediction for one feature record."""


def _nonblank(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must not be empty")
    return value.strip()


def _stable_id(*parts: str) -> str:
    return sha256("\x00".join(parts).encode("utf-8")).hexdigest()[:24]


class PredictionRuntime:
    """Call a model only over an immutable, point-in-time snapshot."""

    def predict(
        self,
        snapshot: FeatureSnapshot,
        adapter: PredictionAdapter,
        *,
        model_id: str,
        model_version: str,
        target: str,
        generated_at: datetime | None = None,
    ) -> tuple[PredictionArtifact, ...]:
        if not isinstance(snapshot, FeatureSnapshot):
            raise TypeError("snapshot must be a FeatureSnapshot")
        model_id = _nonblank(model_id, "model_id")
        model_version = _nonblank(model_version, "model_version")
        target = _nonblank(target, "target")
        if not hasattr(adapter, "predict"):
            raise TypeError("prediction adapter must expose predict")
        generated = generated_at or datetime.now(timezone.utc)
        if generated.tzinfo is None or generated.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")
        generated = generated.astimezone(timezone.utc)
        predictions: list[PredictionArtifact] = []
        for record in snapshot.values:
            raw = adapter.predict(dict(record.values))
            if isinstance(raw, PredictionResult):
                result = raw
            elif isinstance(raw, Mapping):
                result = PredictionResult.model_validate(raw)
            else:
                result = PredictionResult(value=float(raw), confidence=1.0)
            if not isfinite(result.value):
                raise ValueError("prediction value must be finite")
            prediction_id = (
                f"prediction:{model_id}:{model_version}:"
                f"{record.entity_id}:{_stable_id(snapshot.snapshot_id, record.entity_id, target)}"
            )
            lineage_refs = tuple(
                dict.fromkeys(
                    (
                        f"urn:aifde:model:{model_id}:{model_version}",
                        *record.lineage_refs,
                        *record.source_evidence_refs,
                    )
                )
            )
            predictions.append(
                PredictionArtifact(
                    prediction_id=prediction_id,
                    entity_id=record.entity_id,
                    target=target,
                    value=result.value,
                    model_id=model_id,
                    model_version=model_version,
                    ontology_release_id=snapshot.ontology_release_id,
                    ontology_version=snapshot.ontology_version,
                    feature_snapshot_id=snapshot.snapshot_id,
                    feature_definition_version=snapshot.feature_definition_version,
                    as_of_time=snapshot.as_of_time,
                    generated_at=generated,
                    confidence=result.confidence,
                    lineage_refs=lineage_refs,
                )
            )
        return tuple(predictions)


__all__ = ["PredictionAdapter", "PredictionResult", "PredictionRuntime"]
