from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from aifde.builder.contracts import EvidenceFragment, SourceAsset
from aifde.builder.semantic import (
    BuilderContext,
    CandidateProposal,
    DeterministicCandidateProvider,
    SemanticCandidateBuilder,
)
from aifde.builder.sources import SourceRegistry
from aifde.builder.compiler import (
    CompileResult,
    MappingCompiler,
)


FIXTURES = Path(__file__).parent / "fixtures"


def dt(hour: int) -> datetime:
    return datetime(2026, 8, 13, hour, tzinfo=timezone.utc)


def supplier_fragments() -> tuple[SourceRegistry, list[EvidenceFragment]]:
    registry = SourceRegistry()
    json_asset = registry.register(
        SourceAsset.register(
            "erp-purchase-orders",
            "fixture://supplier_purchase_orders.json",
            "json",
            "procurement",
            5,
            "internal",
            "policy:procurement",
            "purchase-order-v1",
            {"format": "json"},
        )
    )
    notes_asset = registry.register(
        SourceAsset.register(
            "procurement-notes",
            "fixture://supplier_notes.md",
            "markdown",
            "procurement",
            3,
            "internal",
            "policy:procurement",
            "notes-v1",
            {"format": "markdown"},
        )
    )
    json_snapshot = registry.capture(
        json_asset.source_asset_id,
        "2026-08-13",
        (FIXTURES / "supplier_purchase_orders.json").read_bytes(),
        dt(9),
        dt(10),
        "raw-v1",
    )
    notes_snapshot = registry.capture(
        notes_asset.source_asset_id,
        "2026-08-13",
        (FIXTURES / "supplier_notes.md").read_bytes(),
        dt(11),
        dt(12),
        "raw-v1",
    )
    fragments = [
        registry.slice(
            json_snapshot.snapshot_id,
            "$.purchase_orders[0]",
            json.dumps(
                {
                    "po_id": "PO-001",
                    "supplier": "Acme Industrial",
                    "promised_date": "2026-09-01",
                    "items": [{"sku": "VALVE-100", "quantity": 20}],
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
        ),
        registry.slice(
            json_snapshot.snapshot_id,
            "$.purchase_orders[1]",
            json.dumps(
                {
                    "po_id": "PO-002",
                    "supplier": "Northstar Components",
                    "promised_date": "2026-09-12",
                    "items": [{"sku": "PUMP-200", "quantity": 8}],
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
        ),
        registry.slice(
            notes_snapshot.snapshot_id,
            "line:3-4",
            "- Acme Industries is the display-name variant for Acme Industrial.\n"
            "- Acme Industries promised date changed to 2026-09-05.",
        ),
    ]
    return registry, fragments


@pytest.fixture
def compiled() -> CompileResult:
    registry, fragments = supplier_fragments()
    context = BuilderContext(
        project_id="supplier-ontology",
        domain="procurement",
        ontology_version="v1",
        known_terms=("supplier", "purchase order", "promised date"),
    )
    proposal = SemanticCandidateBuilder(DeterministicCandidateProvider()).build(
        fragments, context
    )
    return MappingCompiler().compile(proposal, registry, version="0.1.0")


def test_mapping_materializes_canonical_purchase_order_with_lineage(compiled: CompileResult):
    row = next(item for item in compiled.canonical_rows if item["purchase_order_id"] == "PO-001")

    assert row["supplier_id"] == "supplier:acme"
    assert row["promised_delivery_date"] == "2026-09-01"
    assert row["event_time"] == "2026-09-01"
    assert row["observed_at"] <= row["available_at"]
    assert row["evidence_refs"]

    provenance = next(item for item in compiled.provenance_rows if item["target_id"] == "PO-001")
    assert provenance["evidence_refs"]
    assert provenance["source_locations"]


def test_compiler_materializes_each_purchase_order_at_stable_grain(compiled: CompileResult):
    assert [item["purchase_order_id"] for item in compiled.canonical_rows] == [
        "PO-001",
        "PO-002",
    ]
    assert all(item["target_grain"] == "purchase_order" for item in compiled.canonical_rows)


def test_compiler_rejects_invalid_grain(compiled: CompileResult):
    broken = replace(compiled.mapping_specs[0], target_grain="supplier")

    with pytest.raises(ValueError, match="target grain"):
        MappingCompiler().validate(replace(compiled, mapping_specs=[broken]))


def test_compiler_rejects_temporal_inversion(compiled: CompileResult):
    broken_row = dict(compiled.canonical_rows[0])
    broken_row["available_at"] = "2026-08-13T08:00:00+00:00"
    broken_row["observed_at"] = "2026-08-13T09:00:00+00:00"
    broken = replace(compiled, canonical_rows=[broken_row])

    with pytest.raises(ValueError, match="available_at"):
        MappingCompiler().validate(broken)


def test_compiler_rejects_unresolvable_source_path(compiled: CompileResult):
    broken = replace(compiled.mapping_specs[0], source_field_path="$.purchase_orders[*].missing")

    with pytest.raises(ValueError, match="source field path"):
        MappingCompiler().validate(replace(compiled, mapping_specs=[broken]))


def test_compile_rejects_unresolvable_source_path(compiled: CompileResult):
    registry, fragments = supplier_fragments()
    context = BuilderContext(
        project_id="supplier-ontology",
        domain="procurement",
        ontology_version="v1",
        known_terms=("supplier", "purchase order", "promised date"),
    )
    proposal = SemanticCandidateBuilder(DeterministicCandidateProvider()).build(
        fragments, context
    )
    broken_mappings = tuple(
        item.model_copy(update={"source_field_path": "$.purchase_orders[*].missing"})
        for item in proposal.mappings
    )
    broken_proposal = proposal.model_copy(update={"mappings": broken_mappings})

    with pytest.raises(ValueError, match="source field path"):
        MappingCompiler().compile(broken_proposal, registry, version="0.1.0")


def test_compiler_rejects_future_available_time(compiled: CompileResult):
    broken_row = dict(compiled.canonical_rows[0])
    broken_row["available_at"] = "2026-08-13T09:00:00+00:00"
    broken_row["observed_at"] = "2026-08-13T10:00:00+00:00"
    broken = replace(compiled, canonical_rows=[broken_row])

    with pytest.raises(ValueError, match="available_at"):
        MappingCompiler().validate(broken)


def test_rendered_ontology_and_shapes_are_traceable(compiled: CompileResult):
    assert "PurchaseOrder" in compiled.ontology_turtle
    assert "Supplier" in compiled.ontology_turtle
    assert "DeliveryEvent" in compiled.ontology_turtle
    assert "DeliveryException" in compiled.ontology_turtle
    assert "promisedDeliveryDate" in compiled.ontology_turtle
    assert "hasSupplier" in compiled.ontology_turtle
    assert "shapes" in compiled.artifact_hashes
    assert "PurchaseOrderShape" in compiled.shapes_turtle
    assert compiled.validation_report.passed


def test_materialize_requires_evidence_backed_mapping(compiled: CompileResult):
    with pytest.raises(ValueError, match="lineage"):
        replace(compiled.mapping_specs[0], lineage_refs=())
