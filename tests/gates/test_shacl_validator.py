from __future__ import annotations

from pathlib import Path

import pytest

from aifde.domain.stages import StageRun, StageState
from aifde.gates.engine import GateEngine, TransitionBlocked
from aifde.gates.validators import ValidationContext
from aifde.policy.capabilities import Capability, PolicyEngine
from aifde.policy.gateway import ToolGateway
from aifde.ontology.rdf import OntologyDocument
from aifde.tools.validation import SemanticValidationTool, ShaclValidator


FIXTURES = Path(__file__).parents[1] / "fixtures"
SHAPES_TEXT = (FIXTURES / "software_delivery_shapes.ttl").read_text(encoding="utf-8")

REQUIREMENT_MISSING_OWNER = (FIXTURES / "requirement_missing_owner.ttl").read_text(
    encoding="utf-8"
)
REQUIREMENT_VALID = (FIXTURES / "requirement_valid.ttl").read_text(encoding="utf-8")


def test_requirement_without_owner_fails_shacl_validator():
    result = ShaclValidator().validate(REQUIREMENT_MISSING_OWNER, SHAPES_TEXT)

    assert result.passed is False
    assert result.violations
    assert "owner" in result.message.lower()
    assert result.evidence_refs


def test_valid_requirement_passes_shacl_validator():
    result = ShaclValidator().validate(REQUIREMENT_VALID, SHAPES_TEXT)

    assert result.passed is True
    assert result.violations == []
    assert all(
        "pySHACL is unavailable" in warning for warning in result.warnings
    )


def test_validation_result_hashes_and_document_metadata_are_stable():
    first = ShaclValidator().validate(REQUIREMENT_VALID, SHAPES_TEXT)
    second = ShaclValidator().validate(REQUIREMENT_VALID, SHAPES_TEXT)
    document = OntologyDocument.load(REQUIREMENT_VALID)

    assert first.data_hash == second.data_hash
    assert first.shapes_hash == second.shapes_hash
    assert first.validator_version == second.validator_version
    assert document.data_hash == first.data_hash
    assert document.ontology_version
    assert document.source_refs == []
    assert OntologyDocument.load(document.serialize()).data_hash == document.data_hash


def test_validator_does_not_modify_input_graph():
    document = OntologyDocument.load(REQUIREMENT_MISSING_OWNER)
    before = set(document.graph)

    result = ShaclValidator().validate(REQUIREMENT_MISSING_OWNER, SHAPES_TEXT)

    assert result.passed is False
    assert set(document.graph) == before


def test_semantic_validation_tool_uses_validate_gateway_capability():
    tool = SemanticValidationTool()
    gateway = ToolGateway([tool], policy=PolicyEngine())
    context = gateway.issue_context(
        actor_id="builder-1",
        project_id="p1",
        stage_id="ontology.design",
        artifact_ids=[],
        capability=Capability.VALIDATE,
        request_id="validate-1",
    )

    result = gateway.call(
        "semantic_validation",
        context,
        {"data_text": REQUIREMENT_VALID, "shapes_text": SHAPES_TEXT},
    )

    assert result.status == "validated"
    assert result.payload["passed"] is True
    assert result.audit_id

    with pytest.raises(PermissionError, match="validate"):
        gateway.call(
            "semantic_validation",
            context.with_capability(Capability.PROPOSE),
            {"data_text": REQUIREMENT_VALID, "shapes_text": SHAPES_TEXT},
        )


def test_failed_shacl_result_is_a_hard_ontology_gate():
    validator = ShaclValidator()
    result = validator.validate(REQUIREMENT_MISSING_OWNER, SHAPES_TEXT)
    engine = GateEngine()
    stage_run = StageRun(
        stage_run_id="ontology-run-1",
        project_id="p1",
        stage_id="ontology.design",
        state=StageState.DOMAIN_REVIEW,
        output_artifact_ids=["ontology-artifact-1"],
        evidence_refs=["ontology-evidence-1"],
    )
    context = ValidationContext(
        stage_run_id=stage_run.stage_run_id,
        artifact_ids=stage_run.output_artifact_ids,
        evidence_snapshot_id="ontology-evidence-1",
        evidence_snapshot_hash="ontology-evidence-hash-1",
        configuration={"shape": "software_delivery_shapes"},
    )
    engine.register_stage_run(
        stage_run,
        builder_actor="builder-1",
        validation_context=context,
    )

    gate = validator.register_semantic_gate(
        engine,
        stage_run_id=stage_run.stage_run_id,
        validation_result=result,
        context=context,
    )

    assert gate.result.value == "failed"
    decision = engine.can_transition(stage_run.stage_run_id, StageState.APPROVED)
    assert decision.allowed is False
    assert "semantic.integrity" in decision.blocking_gate_ids
    with pytest.raises(TransitionBlocked, match="required gates"):
        engine.transition(stage_run.stage_run_id, StageState.APPROVED, actor="domain-owner")
