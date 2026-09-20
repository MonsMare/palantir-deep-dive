from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import replace
import json
from pathlib import Path
import shutil

import pytest

from aifde.builder.compiler import CompileResult, MappingCompiler
from aifde.builder.contracts import FieldValueProvenance
from software_delivery_demo.builder_demo import run_supplier_delay_builder_demo


PROJECT_ROOT = Path("projects/supplier-delay-builder-demo")


def test_actual_delivery_field_retains_its_later_available_time() -> None:
    result = run_supplier_delay_builder_demo(PROJECT_ROOT)
    row = next(
        item for item in result.compile_result.canonical_rows
        if item["purchase_order_id"] == "PO-001"
    )

    actual = row["field_provenance"]["actual_delivery_date"]

    assert isinstance(actual, FieldValueProvenance)
    assert actual.event_time == datetime(2026, 9, 7, 12, tzinfo=timezone.utc)
    assert actual.available_at == datetime(2026, 9, 8, 12, tzinfo=timezone.utc)
    assert actual.available_at > datetime(2026, 8, 13, 10, tzinfo=timezone.utc)


def test_as_of_materialization_hides_future_actual_delivery() -> None:
    result = run_supplier_delay_builder_demo(PROJECT_ROOT)
    compiled: CompileResult = result.compile_result

    before_event = compiled.materialize_as_of(
        datetime(2026, 9, 7, 23, 59, tzinfo=timezone.utc)
    )
    after_available = compiled.materialize_as_of(
        datetime(2026, 9, 8, 12, tzinfo=timezone.utc)
    )

    before_po = next(item for item in before_event if item["purchase_order_id"] == "PO-001")
    after_po = next(item for item in after_available if item["purchase_order_id"] == "PO-001")
    assert "actual_delivery_date" not in before_po
    assert "actual_delivery_date" in after_po
    assert before_po["delay_state"] == "Unknown"
    assert after_po["delay_state"] == "Delayed"


def test_compiler_rejects_field_provenance_that_is_not_closed() -> None:
    result = run_supplier_delay_builder_demo(PROJECT_ROOT)
    broken_row = dict(result.compile_result.canonical_rows[0])
    broken_fields = dict(broken_row["field_provenance"])
    broken_fields["actual_delivery_date"] = broken_fields["promised_delivery_date"]
    broken_row["field_provenance"] = broken_fields
    broken = replace(
        result.compile_result,
        canonical_rows=[broken_row, *result.compile_result.canonical_rows[1:]],
    )

    with pytest.raises(ValueError, match="field provenance"):
        MappingCompiler().validate(broken)


def test_conflict_bearing_probable_supplier_used_by_product_blocks_release(tmp_path: Path) -> None:
    ambiguous_root = tmp_path / "ambiguous-supplier"
    shutil.copytree(PROJECT_ROOT, ambiguous_root)
    purchase_orders_path = ambiguous_root / "fixtures" / "purchase_orders.json"
    payload = json.loads(purchase_orders_path.read_text(encoding="utf-8"))
    del payload["purchase_orders"][1]["supplier_external_key"]
    purchase_orders_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    result = run_supplier_delay_builder_demo(ambiguous_root)

    assert result.state == "blocked"
    assert result.release_package is None
    assert "probable" in " ".join(result.blocking_reasons).lower()
