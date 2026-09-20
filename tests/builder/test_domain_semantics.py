from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from aifde.builder.compiler import MappingCompiler
from software_delivery_demo.builder_demo import run_supplier_delay_builder_demo


PROJECT_ROOT = Path("projects/supplier-delay-builder-demo")


def test_domain_candidate_contains_operational_objects_and_derived_semantics() -> None:
    result = run_supplier_delay_builder_demo(PROJECT_ROOT)
    candidate = result.compile_result.ontology_candidate

    assert {
        "PurchaseOrderLine",
        "PromisedDelivery",
        "PromisedDateRevision",
        "DeliveryEvent",
        "DeliveryException",
    } <= set(candidate.classes)
    assert {"Delayed", "OnTime", "Unknown"} <= set(candidate.states)
    assert "delayDays" in candidate.properties
    assert "hasLine" in {predicate for _, predicate, _ in candidate.relationships}


def test_delayed_and_unknown_states_are_materialized_as_of_time() -> None:
    result = run_supplier_delay_builder_demo(PROJECT_ROOT)
    compiled = result.compile_result

    before = compiled.materialize_as_of(
        datetime(2026, 9, 7, 23, 59, tzinfo=timezone.utc)
    )
    after = compiled.materialize_as_of(
        datetime(2026, 9, 8, 12, tzinfo=timezone.utc)
    )
    before_po = next(item for item in before if item["purchase_order_id"] == "PO-001")
    after_po = next(item for item in after if item["purchase_order_id"] == "PO-001")
    unknown_po = next(item for item in before if item["purchase_order_id"] == "PO-002")

    assert before_po["delay_state"] == "Unknown"
    assert "delay_days" not in before_po
    assert after_po["delay_state"] == "Delayed"
    assert after_po["delay_days"] == 6
    assert unknown_po["delay_state"] == "Unknown"


def test_rendered_rdf_is_typed_and_has_domain_range_constraints() -> None:
    result = run_supplier_delay_builder_demo(PROJECT_ROOT)
    ontology = result.compile_result.ontology_turtle
    data = result.compile_result.data_turtle
    shapes = result.compile_result.shapes_turtle

    assert "http://www.w3.org/2001/XMLSchema#date" in ontology
    assert "ex:hasLine" in ontology
    assert "rdfs:domain ex:PurchaseOrderLine" in ontology
    assert "rdfs:domain ex:PromisedDelivery" in ontology
    assert "rdfs:domain ex:PurchaseOrder" in ontology
    assert '"2026-09-07"^^xsd:date' in data
    assert "PromisedDateRevision" in ontology
    assert "sh:datatype xsd:date" in shapes
    assert "sh:in" in shapes


def test_compiler_rejects_invalid_delay_state() -> None:
    result = run_supplier_delay_builder_demo(PROJECT_ROOT)
    broken_row = dict(result.compile_result.canonical_rows[0])
    broken_row["delay_state"] = "InventedState"

    from dataclasses import replace

    broken = replace(
        result.compile_result,
        canonical_rows=[broken_row, *result.compile_result.canonical_rows[1:]],
    )

    try:
        MappingCompiler().validate(broken)
    except ValueError as exc:
        assert "delay_state" in str(exc)
    else:
        raise AssertionError("invalid delay state was accepted")
