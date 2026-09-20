"""Generic point-in-time feature materialization."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from collections.abc import Mapping
from typing import Any

from aifde.builder.compiler import CompileResult, _parse_datetime
from aifde.ontology.computation import FeatureDefinition, FeatureRecord, FeatureSnapshot


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _stable_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(payload.encode("utf-8")).hexdigest()


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump(mode="python"))
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


class FeatureRuntime:
    """Execute feature contracts without using facts unavailable at as-of."""

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
        if not isinstance(ontology_release_id, str) or not ontology_release_id.strip():
            raise ValueError("ontology_release_id must not be empty")
        as_of = _aware(_parse_datetime(as_of_time, "as_of_time"), "as_of_time")
        if definition.ontology_version != compile_result.ontology_candidate.version:
            raise ValueError("feature definition ontology_version does not match compile result")
        if not compile_result.validation_report.passed:
            raise ValueError("feature runtime requires a validated compile result")

        records: list[FeatureRecord] = []
        for row in compile_result.canonical_rows:
            fields = row.get("field_provenance")
            if not isinstance(fields, Mapping):
                raise ValueError("canonical row requires field provenance")
            values: dict[str, Any] = {}
            evidence_refs: list[str] = []
            mapping_ids: list[str] = []
            visible_times: list[tuple[datetime, datetime]] = []
            for field_name in definition.feature_fields:
                provenance = fields.get(field_name)
                if provenance is None:
                    continue
                available_at = _aware(
                    _parse_datetime(provenance.available_at, f"{field_name}.available_at"),
                    f"{field_name}.available_at",
                )
                if available_at + timedelta(seconds=definition.availability_lag_seconds) > as_of:
                    continue
                values[field_name] = row[field_name]
                evidence_refs.extend(provenance.evidence_refs)
                mapping_ids.extend(provenance.mapping_ids)
                visible_times.append(
                    (
                        _aware(_parse_datetime(provenance.observed_at, f"{field_name}.observed_at"), f"{field_name}.observed_at"),
                        available_at,
                    )
                )
            missing = [field_name for field_name in definition.feature_fields if field_name not in values]
            if missing and definition.missing_policy == "fail":
                entity_id = row.get(compile_result.primary_key_field, row.get("entity_id", ""))
                raise ValueError(
                    f"feature materialization missing required fields for {entity_id}: "
                    + ", ".join(missing)
                )
            if definition.missing_policy == "null":
                values.update({field_name: None for field_name in missing})
            elif definition.missing_policy == "zero":
                values.update({field_name: 0 for field_name in missing})
            if not visible_times:
                # A row with no visible feature cannot be represented without
                # lying about its availability; omit it rather than creating a
                # future-valued feature record.
                continue
            observed_at = max(item[0] for item in visible_times)
            available_at = max(item[1] for item in visible_times)
            entity_id = row.get(compile_result.primary_key_field, row.get("entity_id"))
            if entity_id in (None, ""):
                raise ValueError(
                    f"canonical row requires primary key {compile_result.primary_key_field!r}"
                )
            records.append(
                FeatureRecord(
                    entity_id=str(entity_id),
                    values=values,
                    observed_at=observed_at,
                    available_at=available_at,
                    as_of_time=as_of,
                    source_evidence_refs=tuple(dict.fromkeys(evidence_refs)),
                    mapping_ids=tuple(dict.fromkeys(mapping_ids)),
                    lineage_refs=tuple(
                        dict.fromkeys(
                            (
                                f"urn:aifde:data-product:{compile_result.artifact_hashes['canonical_product']}",
                                *definition.lineage_refs,
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
        snapshot_id = "feature-snapshot:" + _stable_hash(
            {
                "definition": _jsonable(definition),
                "ontology_release_id": ontology_release_id,
                "as_of_time": as_of.isoformat(),
                "data_product_hash": data_product_hash,
                "records": _jsonable(records),
            }
        )
        return FeatureSnapshot(
            snapshot_id=snapshot_id,
            feature_definition_id=definition.feature_id,
            feature_definition_version=definition.version,
            ontology_release_id=ontology_release_id,
            ontology_version=definition.ontology_version,
            data_product_hash=data_product_hash,
            as_of_time=as_of,
            generated_at=_aware(generated_at or as_of, "generated_at"),
            values=tuple(records),
            lineage_refs=lineage_refs,
        )


__all__ = ["FeatureRuntime"]
