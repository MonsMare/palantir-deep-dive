from __future__ import annotations

from pathlib import Path

import pytest

from software_delivery_demo.builder_demo import run_supplier_delay_builder_demo


PROJECT_ROOT = Path("projects/supplier-delay-builder-demo")


def test_supplier_delay_builder_releases_traceable_ontology():
    result = run_supplier_delay_builder_demo(PROJECT_ROOT)

    assert result.state == "released"
    assert result.release_package is not None
    assert result.release_package.ontology_version == "0.1.0"
    assert result.gate_report.all_hard_gates_passed
    assert len(result.compile_result.canonical_rows) == 3
    assert all(row["evidence_refs"] for row in result.compile_result.canonical_rows)
    assert all(row["mapping_ids"] for row in result.compile_result.canonical_rows)
    assert all(item["evidence_refs"] for item in result.compile_result.provenance_rows)
    po_one = next(
        row for row in result.compile_result.canonical_rows
        if row["purchase_order_id"] == "PO-001"
    )
    assert po_one["actual_delivery_date"] == "2026-09-07"
    po_one_provenance = next(
        item for item in result.compile_result.provenance_rows
        if item["target_id"] == "PO-001"
    )
    note_location = next(
        item for item in po_one_provenance["source_locations"]
        if item["source_asset_id"] == "procurement-notes"
    )
    assert note_location["available_at"].startswith("2026-09-08")
    assert "ex:hasDeliveryEvent" in result.compile_result.data_turtle
    assert "ex:actualDeliveryDate \"2026-09-07\"" in result.compile_result.data_turtle


def test_unresolved_high_impact_merge_blocks_release():
    result = run_supplier_delay_builder_demo(
        PROJECT_ROOT, force_supplier_conflict=True
    )

    assert result.state == "blocked"
    assert "entity" in " ".join(result.blocking_reasons).lower()
    assert result.release_package is None


def test_released_package_contains_rollback_and_dependency_hashes():
    result = run_supplier_delay_builder_demo(PROJECT_ROOT)

    assert result.release_package is not None
    assert result.release_package.rollback_target is None
    assert result.release_package.dependency_versions
    assert result.release_package.mapping_artifact_hash
    assert result.release_package.ontology_artifact_hash
    assert result.release_package.gate_run_ids


def test_builder_actor_cannot_be_release_approver():
    with pytest.raises(PermissionError, match="Builder actor"):
        run_supplier_delay_builder_demo(
            PROJECT_ROOT, approval_actor="builder-1"
        )
