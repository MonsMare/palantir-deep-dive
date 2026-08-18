from __future__ import annotations

import pytest

from aifde.tools.validation import ShaclValidator
from aifde.platform.ontology_ir import (
    ClassIR,
    OntologyIR,
    OntologyIRCompiler,
    PropertyIR,
    RelationshipIR,
)


def _ir(*, evidence: tuple[str, ...] = ("evidence:1",)) -> OntologyIR:
    return OntologyIR(
        ontology_id="procurement-ontology",
        version="1.0.0",
        namespace="urn:aifde:procurement:",
        classes=(
            ClassIR(
                name="PurchaseOrder",
                label="Purchase order",
                evidence_refs=evidence,
                version="1.0.0",
            ),
            ClassIR(
                name="Supplier",
                label="Supplier",
                evidence_refs=evidence,
                version="1.0.0",
            ),
        ),
        properties=(
            PropertyIR(
                name="supplierId",
                label="Supplier ID",
                domain="PurchaseOrder",
                value_type="string",
                min_count=1,
                evidence_refs=evidence,
                version="1.0.0",
            ),
        ),
        relationships=(
            RelationshipIR(
                name="placedWith",
                label="placed with",
                source="PurchaseOrder",
                target="Supplier",
                evidence_refs=evidence,
                version="1.0.0",
            ),
        ),
        evidence_refs=evidence,
    )


def test_ir_compiler_emits_typed_rdfs_and_shacl() -> None:
    artifacts = OntologyIRCompiler().compile(_ir())

    assert "rdfs:Class" in artifacts.ontology_text
    assert "rdfs:domain" in artifacts.ontology_text
    assert "rdfs:range xsd:string" in artifacts.ontology_text
    assert "sh:NodeShape" in artifacts.shapes_text
    assert "sh:minCount 1" in artifacts.shapes_text
    assert artifacts.release_eligible is True
    assert len(artifacts.artifact_hash) == 64

    validation = ShaclValidator().validate(
        """@prefix ex: <urn:aifde:procurement:> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
ex:po-1 a ex:PurchaseOrder ; ex:supplierId "supplier:1" .
""",
        artifacts.shapes_text,
    )
    assert validation.passed is True


def test_ir_compile_hash_is_stable_for_same_semantics() -> None:
    compiler = OntologyIRCompiler()

    first = compiler.compile(_ir())
    second = compiler.compile(_ir())

    assert first.artifact_hash == second.artifact_hash
    assert first.ontology_hash == second.ontology_hash
    assert first.shapes_hash == second.shapes_hash


def test_candidate_without_evidence_cannot_be_released() -> None:
    artifacts = OntologyIRCompiler().compile(_ir(evidence=()))

    assert artifacts.release_eligible is False
    assert any("evidence" in item for item in artifacts.violations)
    with pytest.raises(ValueError, match="evidence"):
        artifacts.require_release()


def test_ir_rejects_relationship_to_unknown_class() -> None:
    broken = _ir().model_copy(
        update={
            "relationships": (
                RelationshipIR(
                    name="placedWith",
                    label="placed with",
                    source="PurchaseOrder",
                    target="Unknown",
                    evidence_refs=("evidence:1",),
                    version="1.0.0",
                ),
            )
        }
    )

    with pytest.raises(ValueError, match="unknown class"):
        OntologyIRCompiler().compile(broken)
