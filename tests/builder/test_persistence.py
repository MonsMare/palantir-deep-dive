from __future__ import annotations

from pathlib import Path

import pytest

from aifde.builder.persistence import SQLiteBuilderRegistry
from software_delivery_demo.builder_demo import run_supplier_delay_builder_demo


PROJECT_ROOT = Path("projects/supplier-delay-builder-demo")


def test_builder_registry_persists_source_provenance_and_release_across_restart(tmp_path: Path) -> None:
    result = run_supplier_delay_builder_demo(PROJECT_ROOT, persistence_path=str(tmp_path / "builder.db"))
    package = result.release_package
    assert package is not None

    database = tmp_path / "builder.db"
    reopened = SQLiteBuilderRegistry(database)
    field = reopened.get_field_provenance("PO-001", "actual_delivery_date")
    assert field["value"] == "2026-09-07"
    assert field["available_at"].startswith("2026-09-08")
    restored = reopened.get_release_manifest(package.release_id)
    assert restored["ontology_version"] == package.ontology_version
    assert reopened.verify_release_manifest(package.release_id) is True
    reopened.close()


def test_builder_registry_is_append_only_and_detects_tampering(tmp_path: Path) -> None:
    result = run_supplier_delay_builder_demo(PROJECT_ROOT)
    package = result.release_package
    assert package is not None
    registry = SQLiteBuilderRegistry(tmp_path / "builder.db")
    registry.append_compile_result(result.compile_result)
    registry.append_release_manifest(package)

    with pytest.raises(ValueError, match="append-only"):
        registry.append_release_manifest(package)

    registry.connection.execute(
        "UPDATE builder_release_manifests SET payload_json = ? WHERE release_id = ?",
        ('{"tampered":true}', package.release_id),
    )
    with pytest.raises(ValueError, match="hash"):
        registry.verify_release_manifest(package.release_id)
    registry.close()
