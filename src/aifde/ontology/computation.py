"""Version-bound computation contracts for an ontology-centered decision loop.

The descriptive ontology is only one layer of a production system.  This
module makes the executable layers explicit and forces every transition to
carry the same ontology release, point-in-time feature snapshot, model
version, and lineage references.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from typing import Any, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aifde.builder.compiler import CompileResult, _parse_datetime


def _nonblank(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must not be empty")
    if value != value.strip():
        raise ValueError(f"{name} must use canonical text")
    return value


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, BaseModel):
        return _jsonable(value.model_dump(mode="python"))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _stable_hash(value: Any) -> str:
    payload = json.dumps(
        _jsonable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def _tuple_texts(value: Any, name: str, *, required: bool = True) -> tuple[str, ...]:
    if isinstance(value, str):
        raise TypeError(f"{name} must be an iterable of identities")
    try:
        result = tuple(_nonblank(item, name) for item in value)
    except TypeError as exc:
        raise TypeError(f"{name} must be an iterable of identities") from exc
    if required and not result:
        raise ValueError(f"{name} must not be empty")
    if len(set(result)) != len(result):
        raise ValueError(f"{name} must not contain duplicates")
    return result


class FeatureDefinition(BaseModel):
    """A point-in-time feature contract, not merely a column list."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    feature_id: str
    entity_type: str
    grain: str
    feature_fields: tuple[str, ...]
    computation_expression: str
    time_window: str
    availability_lag_seconds: int = Field(ge=0)
    missing_policy: Literal["unknown", "null", "zero", "fail"]
    version: str
    ontology_version: str
    leakage_policy: str
    lineage_refs: tuple[str, ...]

    @field_validator(
        "feature_id",
        "entity_type",
        "grain",
        "computation_expression",
        "time_window",
        "version",
        "ontology_version",
        "leakage_policy",
    )
    @classmethod
    def validate_text(cls, value: str, info: Any) -> str:
        return _nonblank(value, info.field_name)

    @field_validator("feature_fields", "lineage_refs", mode="before")
    @classmethod
    def validate_identity_tuples(cls, value: Any, info: Any) -> tuple[str, ...]:
        return _tuple_texts(value, info.field_name)


class LabelDefinition(BaseModel):
    """A future-outcome contract used for training and evaluation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    label_id: str
    entity_type: str
    grain: str
    target_field: str
    label_window: str
    outcome_available_lag_seconds: int = Field(ge=0)
    missing_policy: Literal["unknown", "null", "fail"]
    version: str
    ontology_version: str
    lineage_refs: tuple[str, ...]

    @field_validator(
        "label_id",
        "entity_type",
        "grain",
        "target_field",
        "label_window",
        "version",
        "ontology_version",
    )
    @classmethod
    def validate_label_text(cls, value: str, info: Any) -> str:
        return _nonblank(value, info.field_name)

    @field_validator("lineage_refs", mode="before")
    @classmethod
    def validate_label_refs(cls, value: Any) -> tuple[str, ...]:
        return _tuple_texts(value, "lineage_refs")


class LabelRecord(BaseModel):
    """One outcome label with its own availability and evidence boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    entity_id: str
    value: Any
    observed_at: datetime
    available_at: datetime
    source_evidence_refs: tuple[str, ...]
    lineage_refs: tuple[str, ...]

    @field_validator("entity_id")
    @classmethod
    def validate_label_entity(cls, value: str) -> str:
        return _nonblank(value, "entity_id")

    @field_validator("observed_at", "available_at")
    @classmethod
    def validate_label_times(cls, value: datetime, info: Any) -> datetime:
        return _aware(value, info.field_name)

    @field_validator("source_evidence_refs", "lineage_refs", mode="before")
    @classmethod
    def validate_label_record_refs(cls, value: Any, info: Any) -> tuple[str, ...]:
        return _tuple_texts(value, info.field_name)

    @model_validator(mode="after")
    def validate_label_temporal_order(self) -> LabelRecord:
        if self.observed_at > self.available_at:
            raise ValueError("label available_at must not precede observed_at")
        return self


class LabelSnapshot(BaseModel):
    """Immutable label materialization separated from inference features."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: str
    label_definition_id: str
    label_definition_version: str
    ontology_release_id: str
    ontology_version: str
    data_product_hash: str
    feature_as_of_time: datetime
    label_as_of_time: datetime
    values: tuple[LabelRecord, ...]
    lineage_refs: tuple[str, ...]

    @field_validator(
        "snapshot_id",
        "label_definition_id",
        "label_definition_version",
        "ontology_release_id",
        "ontology_version",
        "data_product_hash",
    )
    @classmethod
    def validate_label_snapshot_text(cls, value: str, info: Any) -> str:
        return _nonblank(value, info.field_name)

    @field_validator("feature_as_of_time", "label_as_of_time")
    @classmethod
    def validate_label_snapshot_times(cls, value: datetime, info: Any) -> datetime:
        return _aware(value, info.field_name)

    @field_validator("lineage_refs", mode="before")
    @classmethod
    def validate_label_snapshot_refs(cls, value: Any) -> tuple[str, ...]:
        return _tuple_texts(value, "lineage_refs")

    @model_validator(mode="after")
    def require_future_label_window(self) -> LabelSnapshot:
        if self.label_as_of_time <= self.feature_as_of_time:
            raise ValueError("label_as_of_time must be after feature_as_of_time")
        return self


class FeatureRecord(BaseModel):
    """One feature entity at one as-of point with field-independent lineage."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    entity_id: str
    values: dict[str, Any]
    observed_at: datetime
    available_at: datetime
    as_of_time: datetime
    source_evidence_refs: tuple[str, ...]
    mapping_ids: tuple[str, ...] = ()
    lineage_refs: tuple[str, ...]

    @field_validator("entity_id")
    @classmethod
    def validate_entity_id(cls, value: str) -> str:
        return _nonblank(value, "entity_id")

    @field_validator("values", mode="before")
    @classmethod
    def normalize_values(cls, value: Any) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise TypeError("feature values must be a mapping")
        return dict(value)

    @field_validator("source_evidence_refs", "mapping_ids", "lineage_refs", mode="before")
    @classmethod
    def validate_refs(cls, value: Any, info: Any) -> tuple[str, ...]:
        return _tuple_texts(value, info.field_name, required=info.field_name != "mapping_ids")

    @field_validator("observed_at", "available_at", "as_of_time")
    @classmethod
    def validate_times(cls, value: datetime, info: Any) -> datetime:
        return _aware(value, info.field_name)

    @model_validator(mode="after")
    def validate_temporal_order(self) -> FeatureRecord:
        if self.observed_at > self.available_at:
            raise ValueError("feature available_at must not precede observed_at")
        if self.available_at > self.as_of_time:
            raise ValueError("feature available_at must not be after as_of_time")
        return self


class FeatureSnapshot(BaseModel):
    """Immutable, point-in-time materialization consumed by model code."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: str
    feature_definition_id: str
    feature_definition_version: str
    ontology_release_id: str
    ontology_version: str
    data_product_hash: str
    as_of_time: datetime
    generated_at: datetime
    values: tuple[FeatureRecord, ...]
    lineage_refs: tuple[str, ...]

    @field_validator(
        "snapshot_id",
        "feature_definition_id",
        "feature_definition_version",
        "ontology_release_id",
        "ontology_version",
        "data_product_hash",
    )
    @classmethod
    def validate_identity(cls, value: str, info: Any) -> str:
        return _nonblank(value, info.field_name)

    @field_validator("as_of_time", "generated_at")
    @classmethod
    def validate_snapshot_times(cls, value: datetime, info: Any) -> datetime:
        return _aware(value, info.field_name)

    @field_validator("lineage_refs", mode="before")
    @classmethod
    def validate_snapshot_refs(cls, value: Any) -> tuple[str, ...]:
        return _tuple_texts(value, "lineage_refs")


class PredictionArtifact(BaseModel):
    """A prediction tied to the exact feature and ontology context used."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    prediction_id: str
    entity_id: str
    target: str
    value: float
    model_id: str
    model_version: str
    ontology_release_id: str
    ontology_version: str
    feature_snapshot_id: str
    feature_definition_version: str
    as_of_time: datetime
    generated_at: datetime
    confidence: float = Field(ge=0, le=1)
    lineage_refs: tuple[str, ...]

    @field_validator(
        "prediction_id",
        "entity_id",
        "target",
        "model_id",
        "model_version",
        "ontology_release_id",
        "ontology_version",
        "feature_snapshot_id",
        "feature_definition_version",
    )
    @classmethod
    def validate_prediction_text(cls, value: str, info: Any) -> str:
        return _nonblank(value, info.field_name)

    @field_validator("as_of_time", "generated_at")
    @classmethod
    def validate_prediction_times(cls, value: datetime, info: Any) -> datetime:
        return _aware(value, info.field_name)

    @field_validator("lineage_refs", mode="before")
    @classmethod
    def validate_prediction_refs(cls, value: Any) -> tuple[str, ...]:
        return _tuple_texts(value, "lineage_refs")


class DecisionCandidate(BaseModel):
    """A ranked, constraint-checked candidate action."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision_id: str
    entity_id: str
    action_type: str
    objective: str
    objective_value: float
    rank: int = Field(gt=0)
    constraint_status: Literal["feasible", "infeasible", "unknown"]
    parameters: dict[str, Any] = Field(default_factory=dict)
    prediction_ids: tuple[str, ...]
    ontology_release_id: str
    ontology_version: str
    feature_snapshot_id: str
    model_versions: tuple[str, ...]
    as_of_time: datetime
    lineage_refs: tuple[str, ...]

    @field_validator(
        "decision_id",
        "entity_id",
        "action_type",
        "objective",
        "ontology_release_id",
        "ontology_version",
        "feature_snapshot_id",
    )
    @classmethod
    def validate_decision_text(cls, value: str, info: Any) -> str:
        return _nonblank(value, info.field_name)

    @field_validator("prediction_ids", "model_versions", "lineage_refs", mode="before")
    @classmethod
    def validate_decision_refs(cls, value: Any, info: Any) -> tuple[str, ...]:
        return _tuple_texts(value, info.field_name)

    @field_validator("as_of_time")
    @classmethod
    def validate_decision_time(cls, value: datetime) -> datetime:
        return _aware(value, "as_of_time")


class GovernedActionRequest(BaseModel):
    """An action request whose authority and computation context are explicit."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action_id: str
    decision_id: str
    target_id: str
    action_type: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    ontology_release_id: str
    ontology_version: str
    prediction_ids: tuple[str, ...]
    feature_snapshot_id: str
    as_of_time: datetime
    requested_at: datetime
    requested_by: str
    policy_id: str
    policy_version: str
    approval_id: str
    approval_status: Literal["pending", "approved", "rejected"]
    validation_id: str
    validation_status: Literal["pending", "passed", "failed"]
    approval_actor: str = "domain-owner-1"
    approval_role: str = "domain-owner"
    validated_by: str = "computation-chain-validator"
    audit_ref: str = "computation-chain-audit"
    audit_actor: str = "computation-chain-validator"
    lineage_refs: tuple[str, ...]

    @field_validator(
        "action_id",
        "decision_id",
        "target_id",
        "action_type",
        "ontology_release_id",
        "ontology_version",
        "feature_snapshot_id",
        "requested_by",
        "policy_id",
        "policy_version",
        "approval_id",
        "validation_id",
        "approval_actor",
        "approval_role",
        "validated_by",
        "audit_ref",
        "audit_actor",
    )
    @classmethod
    def validate_action_text(cls, value: str, info: Any) -> str:
        return _nonblank(value, info.field_name)

    @field_validator("prediction_ids", "lineage_refs", mode="before")
    @classmethod
    def validate_action_refs(cls, value: Any, info: Any) -> tuple[str, ...]:
        return _tuple_texts(value, info.field_name)

    @field_validator("as_of_time", "requested_at")
    @classmethod
    def validate_action_time(cls, value: datetime, info: Any) -> datetime:
        return _aware(value, info.field_name)

    @model_validator(mode="after")
    def require_governance_evidence(self) -> GovernedActionRequest:
        if self.approval_status != "approved":
            raise ValueError("governed action requires approved status")
        if self.validation_status != "passed":
            raise ValueError("governed action requires passed validation")
        return self

    def to_legacy_action_request(
        self,
        *,
        audit_ref: str | None = None,
        audit_actor: str | None = None,
    ) -> Any:
        """Adapt to the existing mock-only broker without dropping context.

        The legacy broker remains the authority boundary.  The computation
        context is copied into parameters so its idempotency/audit record can
        be joined back to this immutable request.
        """

        from aifde.domain.actions import ActionRequest

        return ActionRequest(
            action_id=self.action_id,
            action_type=self.action_type,
            target_id=self.target_id,
            parameters={
                **self.parameters,
                "ontology_release_id": self.ontology_release_id,
                "ontology_version": self.ontology_version,
                "decision_id": self.decision_id,
                "feature_snapshot_id": self.feature_snapshot_id,
                "prediction_ids": list(self.prediction_ids),
            },
            requested_by=self.requested_by,
            idempotency_key=f"{self.action_id}:{self.ontology_release_id}",
            execution_mode="mock",
            policy_id=self.policy_id,
            policy_version=self.policy_version,
            validation_id=self.validation_id,
            validated_by=self.validated_by,
            validation_status="passed",
            approval_id=self.approval_id,
            approval_actor=self.approval_actor,
            approval_role=self.approval_role,
            approval_status="approved",
            audit_ref=audit_ref or self.audit_ref,
            audit_actor=audit_actor or self.audit_actor,
            outcome_status="pending",
        )


class ActionOutcomeLink(BaseModel):
    """The immutable link from an executed action back to its reasoning."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome_id: str
    action_id: str
    decision_id: str
    target_id: str
    status: Literal["succeeded", "failed"]
    external_ref: str
    executed_at: datetime
    ontology_release_id: str
    ontology_version: str
    prediction_ids: tuple[str, ...]
    feature_snapshot_id: str
    lineage_refs: tuple[str, ...]

    @field_validator(
        "outcome_id",
        "action_id",
        "decision_id",
        "target_id",
        "external_ref",
        "ontology_release_id",
        "ontology_version",
        "feature_snapshot_id",
    )
    @classmethod
    def validate_outcome_text(cls, value: str, info: Any) -> str:
        return _nonblank(value, info.field_name)

    @field_validator("prediction_ids", "lineage_refs", mode="before")
    @classmethod
    def validate_outcome_refs(cls, value: Any, info: Any) -> tuple[str, ...]:
        return _tuple_texts(value, info.field_name)

    @field_validator("executed_at")
    @classmethod
    def validate_outcome_time(cls, value: datetime) -> datetime:
        return _aware(value, "executed_at")


class FeedbackLink(BaseModel):
    """Outcome/label feedback linked back to the decision chain."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    feedback_id: str
    artifact_kind: Literal["Prediction", "Decision", "ActionOutcome"]
    artifact_id: str
    value: Any
    source: str
    created_at: datetime
    ontology_release_id: str
    ontology_version: str
    feature_snapshot_id: str
    as_of_time: datetime
    prediction_id: str | None = None
    decision_id: str | None = None
    action_id: str | None = None
    lineage_refs: tuple[str, ...]

    @field_validator(
        "feedback_id",
        "artifact_id",
        "source",
        "ontology_release_id",
        "ontology_version",
        "feature_snapshot_id",
    )
    @classmethod
    def validate_feedback_text(cls, value: str, info: Any) -> str:
        return _nonblank(value, info.field_name)

    @field_validator("prediction_id", "decision_id", "action_id")
    @classmethod
    def validate_optional_feedback_refs(cls, value: str | None, info: Any) -> str | None:
        return None if value is None else _nonblank(value, info.field_name)

    @field_validator("lineage_refs", mode="before")
    @classmethod
    def validate_feedback_refs(cls, value: Any) -> tuple[str, ...]:
        return _tuple_texts(value, "lineage_refs")

    @field_validator("created_at")
    @classmethod
    def validate_feedback_time(cls, value: datetime) -> datetime:
        return _aware(value, "created_at")

    @field_validator("as_of_time")
    @classmethod
    def validate_feedback_as_of(cls, value: datetime) -> datetime:
        return _aware(value, "as_of_time")


class ComputationChainReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    chain_id: str
    ontology_release_id: str
    feature_snapshot_id: str
    artifact_ids: tuple[str, ...]
    violations: tuple[str, ...] = ()


class FeatureMaterializer:
    """Materialize only facts available at the requested point in time."""

    def materialize(
        self,
        compile_result: CompileResult,
        definition: FeatureDefinition,
        *,
        ontology_release_id: str,
        as_of_time: datetime,
        generated_at: datetime | None = None,
    ) -> FeatureSnapshot:
        if not isinstance(compile_result, CompileResult):
            raise TypeError("compile_result must be a CompileResult")
        if not isinstance(definition, FeatureDefinition):
            raise TypeError("definition must be a FeatureDefinition")
        ontology_release_id = _nonblank(ontology_release_id, "ontology_release_id")
        as_of_time = _parse_datetime(as_of_time, "as_of_time")
        as_of_time = _aware(as_of_time, "as_of_time")
        if definition.ontology_version != compile_result.ontology_candidate.version:
            raise ValueError("feature definition ontology_version does not match compile result")
        rows = compile_result.materialize_as_of(as_of_time)
        records: list[FeatureRecord] = []
        for row in rows:
            field_provenance = row.get("field_provenance", {})
            values = {
                field_name: row[field_name]
                for field_name in definition.feature_fields
                if field_name in row
                and isinstance(field_provenance, Mapping)
                and field_name in field_provenance
                and _aware(
                    _parse_datetime(
                        field_provenance[field_name]["available_at"],
                        f"{field_name}.available_at",
                    ),
                    f"{field_name}.available_at",
                )
                + timedelta(seconds=definition.availability_lag_seconds)
                <= as_of_time
            }
            missing = [field_name for field_name in definition.feature_fields if field_name not in values]
            if missing and definition.missing_policy == "fail":
                raise ValueError(
                    f"feature materialization missing required fields for {row.get('purchase_order_id')}: "
                    + ", ".join(missing)
                )
            observed_at = _parse_datetime(row["observed_at"], "observed_at")
            available_at = _parse_datetime(row["available_at"], "available_at")
            records.append(
                FeatureRecord(
                    entity_id=str(row["purchase_order_id"]),
                    values=values,
                    observed_at=observed_at,
                    available_at=available_at,
                    as_of_time=as_of_time,
                    source_evidence_refs=tuple(row.get("evidence_refs", ())),
                    mapping_ids=tuple(row.get("mapping_ids", ())),
                    lineage_refs=tuple(
                        [
                            f"urn:aifde:data-product:{compile_result.artifact_hashes['canonical_product']}",
                            *definition.lineage_refs,
                        ]
                    ),
                )
            )
        lineage_refs = (
            f"urn:aifde:ontology-release:{ontology_release_id}",
            f"urn:aifde:data-product:{compile_result.artifact_hashes['canonical_product']}",
            *definition.lineage_refs,
        )
        snapshot_id = "feature-snapshot:" + _stable_hash(
            {
                "definition": definition,
                "ontology_release_id": ontology_release_id,
                "as_of_time": as_of_time,
                "data_product_hash": compile_result.artifact_hashes["canonical_product"],
                "records": records,
            }
        )
        return FeatureSnapshot(
            snapshot_id=snapshot_id,
            feature_definition_id=definition.feature_id,
            feature_definition_version=definition.version,
            ontology_release_id=ontology_release_id,
            ontology_version=definition.ontology_version,
            data_product_hash=compile_result.artifact_hashes["canonical_product"],
            as_of_time=as_of_time,
            generated_at=_aware(generated_at or as_of_time, "generated_at"),
            values=tuple(records),
            lineage_refs=lineage_refs,
        )


class LabelMaterializer:
    """Materialize future outcomes separately from point-in-time features."""

    def materialize(
        self,
        compile_result: CompileResult,
        definition: LabelDefinition,
        *,
        ontology_release_id: str,
        feature_as_of_time: datetime,
        label_as_of_time: datetime,
    ) -> LabelSnapshot:
        if not isinstance(compile_result, CompileResult):
            raise TypeError("compile_result must be a CompileResult")
        if not isinstance(definition, LabelDefinition):
            raise TypeError("definition must be a LabelDefinition")
        feature_as_of_time = _aware(
            _parse_datetime(feature_as_of_time, "feature_as_of_time"),
            "feature_as_of_time",
        )
        label_as_of_time = _aware(
            _parse_datetime(label_as_of_time, "label_as_of_time"),
            "label_as_of_time",
        )
        if label_as_of_time <= feature_as_of_time:
            raise ValueError("label_as_of_time must be after feature_as_of_time")
        if definition.ontology_version != compile_result.ontology_candidate.version:
            raise ValueError("label definition ontology_version does not match compile result")
        records: list[LabelRecord] = []
        for row in compile_result.canonical_rows:
            provenance = row.get("field_provenance", {}).get(definition.target_field)
            if provenance is None or not hasattr(provenance, "available_at"):
                continue
            available_at = _aware(
                _parse_datetime(provenance.available_at, "label.available_at"),
                "label.available_at",
            )
            if available_at > label_as_of_time:
                continue
            records.append(
                LabelRecord(
                    entity_id=str(row["purchase_order_id"]),
                    value=row.get(definition.target_field),
                    observed_at=_aware(
                        _parse_datetime(provenance.observed_at, "label.observed_at"),
                        "label.observed_at",
                    ),
                    available_at=available_at,
                    source_evidence_refs=tuple(provenance.evidence_refs),
                    lineage_refs=(*definition.lineage_refs, f"urn:aifde:data-product:{compile_result.artifact_hashes['canonical_product']}"),
                )
            )
        lineage_refs = (
            f"urn:aifde:ontology-release:{ontology_release_id}",
            f"urn:aifde:data-product:{compile_result.artifact_hashes['canonical_product']}",
            *definition.lineage_refs,
        )
        snapshot_id = "label-snapshot:" + _stable_hash(
            {
                "definition": definition,
                "release": ontology_release_id,
                "feature_as_of_time": feature_as_of_time,
                "label_as_of_time": label_as_of_time,
                "records": records,
            }
        )
        return LabelSnapshot(
            snapshot_id=snapshot_id,
            label_definition_id=definition.label_id,
            label_definition_version=definition.version,
            ontology_release_id=ontology_release_id,
            ontology_version=definition.ontology_version,
            data_product_hash=compile_result.artifact_hashes["canonical_product"],
            feature_as_of_time=feature_as_of_time,
            label_as_of_time=label_as_of_time,
            values=tuple(records),
            lineage_refs=lineage_refs,
        )


class ComputationChainValidator:
    """Validate cross-layer referential integrity before action execution."""

    @staticmethod
    def validate(
        snapshot: FeatureSnapshot,
        *artifacts: PredictionArtifact | DecisionCandidate | GovernedActionRequest | ActionOutcomeLink | FeedbackLink,
    ) -> ComputationChainReport:
        if not isinstance(snapshot, FeatureSnapshot):
            raise TypeError("snapshot must be a FeatureSnapshot")
        violations: list[str] = []
        predictions: dict[str, PredictionArtifact] = {}
        decisions: dict[str, DecisionCandidate] = {}
        actions: dict[str, GovernedActionRequest] = {}
        outcomes: dict[str, ActionOutcomeLink] = {}
        feedback: list[FeedbackLink] = []
        known_entities = {item.entity_id for item in snapshot.values}

        def bind(item: Any, name: str) -> None:
            for attr in ("ontology_release_id", "ontology_version", "feature_snapshot_id"):
                expected = (
                    snapshot.ontology_release_id
                    if attr == "ontology_release_id"
                    else snapshot.ontology_version
                    if attr == "ontology_version"
                    else snapshot.snapshot_id
                )
                actual = getattr(item, attr)
                if actual != expected:
                    violations.append(f"{name} {attr} is not bound to the feature snapshot/release")
            if hasattr(item, "as_of_time") and item.as_of_time != snapshot.as_of_time:
                violations.append(f"{name} as_of_time does not match feature snapshot")

        for item in artifacts:
            if isinstance(item, PredictionArtifact):
                predictions[item.prediction_id] = item
                bind(item, f"prediction {item.prediction_id}")
                if item.entity_id not in known_entities:
                    violations.append(f"prediction {item.prediction_id} references unknown entity")
            elif isinstance(item, DecisionCandidate):
                decisions[item.decision_id] = item
                bind(item, f"decision {item.decision_id}")
                if item.entity_id not in known_entities:
                    violations.append(f"decision {item.decision_id} references unknown entity")
            elif isinstance(item, GovernedActionRequest):
                actions[item.action_id] = item
                bind(item, f"action {item.action_id}")
                if item.as_of_time != snapshot.as_of_time:
                    violations.append(f"action {item.action_id} as_of_time does not match feature snapshot")
                if item.decision_id not in decisions:
                    pass
            elif isinstance(item, ActionOutcomeLink):
                outcomes[item.outcome_id] = item
                bind(item, f"outcome {item.outcome_id}")
            elif isinstance(item, FeedbackLink):
                feedback.append(item)
                bind(item, f"feedback {item.feedback_id}")
            else:
                raise TypeError(f"unsupported computation artifact {type(item).__name__}")

        for decision in decisions.values():
            missing = set(decision.prediction_ids) - set(predictions)
            if missing:
                violations.append(f"decision {decision.decision_id} references missing predictions: {sorted(missing)}")
        for action in actions.values():
            decision = decisions.get(action.decision_id)
            if decision is None:
                violations.append(f"action {action.action_id} references missing decision")
            elif set(action.prediction_ids) != set(decision.prediction_ids):
                violations.append(f"action {action.action_id} prediction set differs from decision")
        for outcome in outcomes.values():
            action = actions.get(outcome.action_id)
            if action is None:
                violations.append(f"outcome {outcome.outcome_id} references missing action")
            elif outcome.target_id != action.target_id:
                violations.append(f"outcome {outcome.outcome_id} target differs from action")
            if outcome.decision_id not in decisions:
                violations.append(f"outcome {outcome.outcome_id} references missing decision")
        for item in feedback:
            if item.prediction_id is not None and item.prediction_id not in predictions:
                violations.append(f"feedback {item.feedback_id} references missing prediction")
            if item.decision_id is not None and item.decision_id not in decisions:
                violations.append(f"feedback {item.feedback_id} references missing decision")
            if item.action_id is not None and item.action_id not in actions:
                violations.append(f"feedback {item.feedback_id} references missing action")

        if violations:
            raise ValueError("computation chain validation failed: " + "; ".join(dict.fromkeys(violations)))
        chain_id = "computation-chain:" + _stable_hash(
            {"snapshot": snapshot, "artifacts": artifacts}
        )
        artifact_ids = tuple(
            getattr(item, field_name)
            for item in artifacts
            for field_name in ("prediction_id", "decision_id", "action_id", "outcome_id", "feedback_id")
            if hasattr(item, field_name)
        )
        return ComputationChainReport(
            passed=True,
            chain_id=chain_id,
            ontology_release_id=snapshot.ontology_release_id,
            feature_snapshot_id=snapshot.snapshot_id,
            artifact_ids=artifact_ids,
        )


__all__ = [
    "ActionOutcomeLink",
    "ComputationChainReport",
    "ComputationChainValidator",
    "DecisionCandidate",
    "FeatureDefinition",
    "FeatureMaterializer",
    "FeatureRecord",
    "FeatureSnapshot",
    "FeedbackLink",
    "GovernedActionRequest",
    "LabelMaterializer",
    "LabelDefinition",
    "LabelRecord",
    "LabelSnapshot",
    "PredictionArtifact",
]
