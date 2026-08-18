"""Deterministic decision candidate ranking bound to predictions and features."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from aifde.ontology.computation import DecisionCandidate, FeatureSnapshot, PredictionArtifact


def _nonblank(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must not be empty")
    return value.strip()


class DecisionOption(BaseModel):
    """A solver/model-produced option before ranking and release."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    option_id: str
    entity_id: str
    action_type: str
    objective_value: float
    constraint_status: Literal["feasible", "infeasible", "unknown"]
    prediction_ids: tuple[str, ...]
    parameters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("option_id", "entity_id", "action_type")
    @classmethod
    def validate_text(cls, value: str, info: Any) -> str:
        return _nonblank(value, info.field_name)

    @field_validator("prediction_ids", mode="before")
    @classmethod
    def validate_prediction_ids(cls, value: Any) -> tuple[str, ...]:
        if isinstance(value, str):
            raise TypeError("prediction_ids must be a sequence")
        refs = tuple(_nonblank(item, "prediction_ids item") for item in value)
        if not refs:
            raise ValueError("prediction_ids must not be empty")
        return tuple(dict.fromkeys(refs))


class DecisionRuntime:
    """Rank only feasible options and preserve all causal references."""

    def rank(
        self,
        snapshot: FeatureSnapshot,
        predictions: Sequence[PredictionArtifact],
        options: Sequence[DecisionOption],
        *,
        objective: Literal["minimize", "maximize"] = "minimize",
        top_k: int | None = None,
    ) -> tuple[DecisionCandidate, ...]:
        if not isinstance(snapshot, FeatureSnapshot):
            raise TypeError("snapshot must be a FeatureSnapshot")
        if objective not in {"minimize", "maximize"}:
            raise ValueError("objective must be minimize or maximize")
        prediction_by_id = {item.prediction_id: item for item in predictions}
        if len(prediction_by_id) != len(tuple(predictions)):
            raise ValueError("prediction IDs must be unique")
        for prediction in prediction_by_id.values():
            if (
                prediction.feature_snapshot_id != snapshot.snapshot_id
                or prediction.ontology_release_id != snapshot.ontology_release_id
                or prediction.ontology_version != snapshot.ontology_version
                or prediction.as_of_time != snapshot.as_of_time
            ):
                raise ValueError("prediction is not bound to the feature snapshot")
        feasible: list[DecisionOption] = []
        for option in options:
            if option.constraint_status != "feasible":
                continue
            refs = [prediction_by_id.get(ref) for ref in option.prediction_ids]
            if any(item is None for item in refs):
                raise ValueError(f"decision option {option.option_id} references missing prediction")
            typed_refs = [item for item in refs if item is not None]
            if any(item.entity_id != option.entity_id for item in typed_refs):
                raise ValueError(f"decision option {option.option_id} mixes entity predictions")
            if option.entity_id not in {item.entity_id for item in snapshot.values}:
                raise ValueError(f"decision option {option.option_id} references unknown entity")
            feasible.append(option)
        ordered = sorted(
            feasible,
            key=lambda item: (
                item.objective_value if objective == "minimize" else -item.objective_value,
                item.option_id,
            ),
        )
        if top_k is not None:
            if top_k <= 0:
                raise ValueError("top_k must be positive")
            ordered = ordered[:top_k]
        result: list[DecisionCandidate] = []
        for rank, option in enumerate(ordered, start=1):
            selected = [prediction_by_id[ref] for ref in option.prediction_ids]
            lineage_refs = tuple(
                dict.fromkeys(
                    (
                        f"urn:aifde:decision-runtime:{objective}",
                        *snapshot.lineage_refs,
                        *(ref for item in selected for ref in item.lineage_refs),
                    )
                )
            )
            decision_id = "decision:" + sha256(
                json.dumps(
                    {
                        "snapshot": snapshot.snapshot_id,
                        "option": option.option_id,
                        "objective": objective,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()[:24]
            result.append(
                DecisionCandidate(
                    decision_id=decision_id,
                    entity_id=option.entity_id,
                    action_type=option.action_type,
                    objective=objective,
                    objective_value=option.objective_value,
                    rank=rank,
                    constraint_status="feasible",
                    parameters=dict(option.parameters),
                    prediction_ids=option.prediction_ids,
                    ontology_release_id=snapshot.ontology_release_id,
                    ontology_version=snapshot.ontology_version,
                    feature_snapshot_id=snapshot.snapshot_id,
                    model_versions=tuple(dict.fromkeys(item.model_version for item in selected)),
                    as_of_time=snapshot.as_of_time,
                    lineage_refs=lineage_refs,
                )
            )
        return tuple(result)


__all__ = ["DecisionOption", "DecisionRuntime"]
