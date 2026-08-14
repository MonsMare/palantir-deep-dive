from __future__ import annotations

from pathlib import Path

import pytest

from aifde.builder.flow import BuilderRunConfig, EvidenceDrivenOntologyBuilder
from aifde.domains import DomainAdapterRegistry
from aifde.platform.ontology_ir import OntologyIRCompiler
from software_delivery_demo.builder_demo import run_supplier_delay_builder_demo


FIXTURE = Path(__file__).parent / "fixtures" / "software_requirements.json"
SUPPLIER_ROOT = Path("projects/supplier-delay-builder-demo")


def test_domain_registry_exposes_two_explicit_packs_and_typed_ir() -> None:
    registry = DomainAdapterRegistry()

    assert {pack.pack_id for pack in registry.list()} == {
        "supplier-delay",
        "software-delivery",
    }
    for pack in registry.list():
        artifacts = OntologyIRCompiler().compile(pack.ontology)
        assert artifacts.ontology_hash
        assert artifacts.shapes_hash


def test_builder_runs_software_delivery_without_supplier_specific_paths(tmp_path: Path) -> None:
    result = EvidenceDrivenOntologyBuilder().run(
        BuilderRunConfig(
            project_id="software-domain-test",
            domain="software-delivery",
            domain_pack_id="software-delivery",
            ontology_version="0.1.0",
            actor_id="builder-1",
            source_paths=(str(FIXTURE),),
            approval_actor="domain-owner-1",
            persistence_path=str(tmp_path / "software.db"),
        )
    )

    assert result.state == "released"
    assert result.domain_pack_id == "software-delivery"
    assert result.compile_result.domain_pack_id == "software-delivery"
    assert result.compile_result.primary_key_field == "requirement_id"
    assert [row["requirement_id"] for row in result.compile_result.canonical_rows] == [
        "REQ-001",
        "REQ-002",
    ]
    assert "Requirement" in result.compile_result.ontology_turtle
    assert result.compile_result.validation_report.passed
    assert result.gate_report.all_required_gates_passed


def test_supplier_delay_behavior_remains_pack_selected() -> None:
    result = run_supplier_delay_builder_demo(SUPPLIER_ROOT)

    assert result.state == "released"
    assert result.domain_pack_id == "supplier-delay"
    assert result.compile_result.domain_pack_id == "supplier-delay"
    assert len(result.compile_result.canonical_rows) == 3


def test_unknown_domain_pack_fails_closed_before_source_capture() -> None:
    with pytest.raises(KeyError, match="unknown domain pack"):
        EvidenceDrivenOntologyBuilder().run(
            BuilderRunConfig(
                project_id="unknown-domain",
                domain="unknown",
                domain_pack_id="does-not-exist",
                ontology_version="0.1.0",
                actor_id="builder-1",
                source_paths=(str(FIXTURE),),
                approval_actor="domain-owner-1",
            )
        )
