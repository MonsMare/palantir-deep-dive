"""Future-outcome label materialization separated from inference features."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from collections.abc import Mapping
from typing import Any

from aifde.builder.compiler import CompileResult, _parse_datetime
from aifde.ontology.computation import LabelDefinition, LabelRecord, LabelSnapshot


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump(mode="python"))
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _stable_hash(value: Any) -> str:
    return sha256(
        json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


class LabelRuntime:
    """Build labels at a later availability boundary than features."""

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
        feature_as_of = _aware(
            _parse_datetime(feature_as_of_time, "feature_as_of_time"), "feature_as_of_time"
        )
        label_as_of = _aware(
            _parse_datetime(label_as_of_time, "label_as_of_time"), "label_as_of_time"
        )
        if label_as_of <= feature_as_of:
            raise ValueError("label_as_of_time must be after feature_as_of_time")
        if definition.ontology_version != compile_result.ontology_candidate.version:
            raise ValueError("label definition ontology_version does not match compile result")
        records: list[LabelRecord] = []
        for row in compile_result.canonical_rows:
            fields = row.get("field_provenance")
            if not isinstance(fields, Mapping):
                raise ValueError("canonical row requires field provenance")
            provenance = fields.get(definition.target_field)
            if provenance is None:
                continue
            available_at = _aware(
                _parse_datetime(provenance.available_at, "label.available_at"),
                "label.available_at",
            ) + timedelta(seconds=definition.outcome_available_lag_seconds)
            if available_at > label_as_of:
                continue
            entity_id = row.get(compile_result.primary_key_field, row.get("entity_id"))
            if entity_id in (None, ""):
                raise ValueError(
                    f"canonical row requires primary key {compile_result.primary_key_field!r}"
                )
            records.append(
                LabelRecord(
                    entity_id=str(entity_id),
                    value=row.get(definition.target_field),
                    observed_at=_aware(
                        _parse_datetime(provenance.observed_at, "label.observed_at"),
                        "label.observed_at",
                    ),
                    available_at=available_at,
                    source_evidence_refs=tuple(provenance.evidence_refs),
                    lineage_refs=tuple(
                        dict.fromkeys(
                            (
                                *definition.lineage_refs,
                                f"urn:aifde:data-product:{compile_result.artifact_hashes['canonical_product']}",
                            )
                        )
                    ),
                )
            )
        data_product_hash = compile_result.artifact_hashes["canonical_product"]
        lineage_refs = tuple(
            dict.fromkeys(
                (
                    f"urn:aifde:ontology-release:{ontology_release_id}",
                    f"urn:aifde:data-product:{data_product_hash}",
                    *definition.lineage_refs,
                )
            )
        )
        snapshot_id = "label-snapshot:" + _stable_hash(
            {
                "definition": definition,
                "release": ontology_release_id,
                "feature_as_of_time": feature_as_of,
                "label_as_of_time": label_as_of,
                "records": records,
            }
        )
        return LabelSnapshot(
            snapshot_id=snapshot_id,
            label_definition_id=definition.label_id,
            label_definition_version=definition.version,
            ontology_release_id=ontology_release_id,
            ontology_version=definition.ontology_version,
            data_product_hash=data_product_hash,
            feature_as_of_time=feature_as_of,
            label_as_of_time=label_as_of,
            values=tuple(records),
            lineage_refs=lineage_refs,
        )


__all__ = ["LabelRuntime"]
