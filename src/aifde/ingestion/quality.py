"""Deterministic data-product contracts and quality reports."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from hashlib import sha256
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must not be empty")
    return value.strip()


class DataProductContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    product_id: str
    version: str
    grain: str
    unique_key: str
    required_fields: tuple[str, ...] = ()
    max_null_ratio: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("product_id", "version", "grain", "unique_key")
    @classmethod
    def validate_text(cls, value: str, info: Any) -> str:
        return _text(value, info.field_name)

    @field_validator("required_fields", mode="before")
    @classmethod
    def normalize_required_fields(cls, value: Any) -> tuple[str, ...]:
        if value is None:
            return ()
        if isinstance(value, str):
            value = (value,)
        if not isinstance(value, (tuple, list)):
            raise TypeError("required_fields must be a sequence")
        result = tuple(_text(item, "required_fields") for item in value)
        if len(set(result)) != len(result):
            raise ValueError("required_fields must not contain duplicates")
        return result


class DataQualityReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    product_id: str
    version: str
    grain: str
    passed: bool
    row_count: int = Field(ge=0)
    data_hash: str
    metrics: dict[str, float]
    violations: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


class DataQualityEngine:
    """Run contract checks before data enters semantic or compute layers."""

    def run(
        self, rows: Sequence[Mapping[str, Any]], contract: DataProductContract
    ) -> DataQualityReport:
        if not isinstance(contract, DataProductContract):
            raise TypeError("contract must be a DataProductContract")
        normalized_rows: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, Mapping):
                raise TypeError("data product rows must be mapping values")
            normalized_rows.append(dict(row))
        violations: list[str] = []
        if not normalized_rows:
            violations.append("data product contains no rows")
        for field_name in contract.required_fields:
            missing = [index for index, row in enumerate(normalized_rows) if field_name not in row]
            if missing:
                violations.append(f"required field {field_name!r} is missing from rows {missing}")
            null_count = sum(
                1 for row in normalized_rows if field_name in row and row[field_name] is None
            )
            ratio = null_count / len(normalized_rows) if normalized_rows else 1.0
            if ratio > contract.max_null_ratio:
                violations.append(
                    f"field {field_name!r} null ratio {ratio:.6f} exceeds {contract.max_null_ratio:.6f}"
                )
        keys = [row.get(contract.unique_key) for row in normalized_rows]
        if any(key is None or (isinstance(key, str) and not key.strip()) for key in keys):
            violations.append(f"unique key {contract.unique_key!r} contains null or blank values")
        comparable_keys = [self._key_value(key) for key in keys if key is not None]
        if len(comparable_keys) != len(set(comparable_keys)):
            violations.append(f"duplicate values found for unique key {contract.unique_key!r}")
        data_hash = _hash_rows(normalized_rows)
        metrics = {
            "row_count": float(len(normalized_rows)),
            "required_field_count": float(len(contract.required_fields)),
            "violation_count": float(len(violations)),
        }
        return DataQualityReport(
            product_id=contract.product_id,
            version=contract.version,
            grain=contract.grain,
            passed=not violations,
            row_count=len(normalized_rows),
            data_hash=data_hash,
            metrics=metrics,
            violations=tuple(violations),
        )

    @staticmethod
    def _key_value(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _hash_rows(rows: Sequence[Mapping[str, Any]]) -> str:
    payload = json.dumps(
        list(rows), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return sha256(payload.encode("utf-8")).hexdigest()


__all__ = ["DataProductContract", "DataQualityEngine", "DataQualityReport"]
