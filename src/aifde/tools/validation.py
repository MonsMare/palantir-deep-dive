"""SHACL semantic validation behind the audited VALIDATE tool boundary."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from aifde.domain.gates import GateResult
from aifde.gates.validators import ValidationResult as GateValidationResult
from aifde.ontology.rdf import (
    RDF_TYPE,
    _clone_graph,
    _iter_triples,
    _parse_rdf_text,
    _predicate_local_name,
    _term_value,
)
from aifde.ontology.shapes import (
    SHACL_WARNING,
    ShapeConstraint,
    ShapeDocument,
    ShapeLoader,
)
from aifde.policy.capabilities import Capability, ToolContext
from aifde.tools.protocol import ToolResult


VALIDATOR_VERSION = "1.0.0"
_PYSHACL_WARNING = (
    "pySHACL is unavailable; used the deterministic local SHACL subset. "
    "Install the optional 'pyshacl' dependency for full SHACL semantics."
)


class ValidationResult(BaseModel):
    """Stable semantic-validation result with hashes and readable evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    violations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    data_hash: str
    shapes_hash: str
    validator_version: str = VALIDATOR_VERSION
    evidence_refs: list[str] = Field(default_factory=list)
    message: str

    @field_validator("data_hash", "shapes_hash")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        if type(value) is not str or len(value) != 64 or any(
            char not in "0123456789abcdef" for char in value
        ):
            raise ValueError("hashes must be lowercase SHA-256 hex digests")
        return value

    @field_validator("validator_version", "message")
    @classmethod
    def validate_text(cls, value: str) -> str:
        if type(value) is not str or not value.strip():
            raise ValueError("must be a non-empty string")
        return value

    @field_validator("violations", "warnings", "evidence_refs")
    @classmethod
    def validate_string_lists(cls, value: list[str]) -> list[str]:
        if type(value) is not list or any(type(item) is not str or not item.strip() for item in value):
            raise ValueError("references and messages must be lists of non-empty strings")
        if any(item != item.strip() for item in value):
            raise ValueError("references and messages must use canonical text")
        return list(dict.fromkeys(value))


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _evidence_refs(data_hash: str, shapes_hash: str) -> list[str]:
    return [
        f"urn:aifde:semantic-validation:data:{data_hash}",
        f"urn:aifde:semantic-validation:shapes:{shapes_hash}",
    ]


def _objects(graph: Any, subject: Any, predicate: str) -> list[Any]:
    return [
        obj
        for subj, pred, obj in _iter_triples(graph)
        if subj == subject and _term_value(pred) == predicate
    ]


def _subjects_of_class(graph: Any, target_class: str) -> list[Any]:
    return [
        subject
        for subject, predicate, obj in _iter_triples(graph)
        if _term_value(predicate) == RDF_TYPE and _term_value(obj) == target_class
    ]


def _format_focus_node(node: Any) -> str:
    value = _term_value(node)
    return value if value else str(node)


def _format_constraint_failure(
    node: Any, constraint: ShapeConstraint, actual_count: int
) -> str:
    return (
        f"{constraint.message} "
        f"Focus node {_format_focus_node(node)!r} violates path "
        f"{constraint.path!r}: found {actual_count}, required at least "
        f"{constraint.min_count}."
    )


def _fallback_validate(data_graph: Any, shape_document: ShapeDocument) -> tuple[list[str], list[str]]:
    violations: list[str] = []
    warnings: list[str] = []
    for constraint in shape_document.constraints:
        for node in _subjects_of_class(data_graph, constraint.target_class):
            actual_count = len(_objects(data_graph, node, constraint.path))
            if actual_count >= constraint.min_count:
                continue
            message = _format_constraint_failure(node, constraint, actual_count)
            if constraint.severity.endswith("Warning") or constraint.severity == SHACL_WARNING:
                warnings.append(message)
            else:
                violations.append(message)
    return _unique(violations), _unique(warnings)


def _result_messages(result_graph: Any) -> tuple[list[str], list[str]]:
    """Extract human-readable pySHACL result messages without trusting text output."""

    violations: list[str] = []
    warnings: list[str] = []
    for result_node, predicate, obj in _iter_triples(result_graph):
        if _predicate_local_name(predicate).lower() != "resultseverity":
            continue
        severity = _term_value(obj)
        messages = _objects(result_graph, result_node, "http://www.w3.org/ns/shacl#resultMessage")
        message = _term_value(messages[0]) if messages else "SHACL constraint violation."
        focus = _objects(result_graph, result_node, "http://www.w3.org/ns/shacl#focusNode")
        path = _objects(result_graph, result_node, "http://www.w3.org/ns/shacl#resultPath")
        suffix = []
        if focus:
            suffix.append(f"Focus node {_format_focus_node(focus[0])!r}")
        if path:
            suffix.append(f"path {_term_value(path[0])!r}")
        readable = message if not suffix else f"{message} ({', '.join(suffix)})."
        if severity.endswith("Warning") or severity == SHACL_WARNING:
            warnings.append(readable)
        elif severity != "http://www.w3.org/ns/shacl#Info":
            violations.append(readable)
    return _unique(violations), _unique(warnings)


def _try_pyshacl(data_graph: Any, shape_graph: Any) -> tuple[bool, list[str], list[str], str] | None:
    try:
        from pyshacl import validate as pyshacl_validate
    except ImportError:
        return None
    try:
        conforms, results_graph, results_text = pyshacl_validate(
            data_graph=_clone_graph(data_graph),
            shacl_graph=_clone_graph(shape_graph),
            inference="none",
            abort_on_first=False,
            allow_infos=True,
            allow_warnings=True,
            advanced=False,
            meta_shacl=False,
        )
    except Exception as exc:
        raise RuntimeError(f"pySHACL validation failed: {exc}") from exc
    violations, warnings = _result_messages(results_graph)
    if not violations and not conforms and isinstance(results_text, str) and results_text.strip():
        violations = [results_text.strip()]
    return bool(conforms), violations, warnings, "pySHACL"


class ShaclValidator:
    """Validate RDF data against SHACL and produce an immutable provenance record."""

    validator_version = VALIDATOR_VERSION

    def validate(self, data_text: str, shapes_text: str) -> ValidationResult:
        if type(data_text) is not str:
            raise TypeError("data_text must be a string")
        if not data_text.strip():
            raise ValueError("data_text must not be empty")
        if type(shapes_text) is not str:
            raise TypeError("shapes_text must be a string")
        if not shapes_text.strip():
            raise ValueError("shapes_text must not be empty")

        data_graph = _parse_rdf_text(data_text)
        shape_document = ShapeLoader.load(shapes_text)
        data_hash = _semantic_hash(data_graph)
        shapes_hash = shape_document.shapes_hash
        evidence_refs = _evidence_refs(data_hash, shapes_hash)

        pyshacl_result = _try_pyshacl(data_graph, shape_document.graph)
        if pyshacl_result is None:
            violations, warnings = _fallback_validate(data_graph, shape_document)
            warnings = _unique([_PYSHACL_WARNING, *warnings])
            engine_name = "deterministic local SHACL fallback"
            passed = not violations
        else:
            passed, violations, warnings, engine_name = pyshacl_result
            passed = bool(passed and not violations)

        if violations:
            message = "SHACL validation failed: " + " ".join(violations)
        elif warnings:
            message = f"SHACL validation passed using {engine_name}; warnings were emitted."
        else:
            message = f"SHACL validation passed using {engine_name}."
        if pyshacl_result is None:
            message = f"{message} {_PYSHACL_WARNING}"
        return ValidationResult(
            passed=passed,
            violations=violations,
            warnings=warnings,
            data_hash=data_hash,
            shapes_hash=shapes_hash,
            validator_version=self.validator_version,
            evidence_refs=evidence_refs,
            message=message,
        )

    def register_semantic_gate(
        self,
        engine: Any,
        *,
        stage_run_id: str,
        validation_result: ValidationResult,
        context: Any,
    ) -> Any:
        """Register this outcome as the existing hard ``semantic.integrity`` gate.

        The adapter deliberately constructs the platform's gate result type so
        the existing GateEngine remains the sole owner of stage transitions.
        """

        from aifde.gates.validators import ValidationContext

        if not hasattr(engine, "register_result") or not hasattr(engine, "get_definition"):
            raise TypeError("engine must be a GateEngine-compatible object")
        if not isinstance(validation_result, ValidationResult):
            raise TypeError("validation_result must be a semantic ValidationResult")
        if not isinstance(context, ValidationContext):
            raise TypeError("context must be a gates.validators.ValidationContext")
        definition = engine.get_definition("semantic.integrity")
        if definition.severity != "hard":
            raise ValueError("semantic.integrity must remain a hard gate")
        evidence_refs = _unique([*validation_result.evidence_refs, context.evidence_snapshot_id])
        input_hashes = {
            artifact_id: validation_result.data_hash for artifact_id in context.artifact_ids
        }
        gate_result = GateValidationResult(
            passed=validation_result.passed,
            violations=list(validation_result.violations),
            warnings=list(validation_result.warnings),
            evidence_refs=evidence_refs,
            validator_version=validation_result.validator_version,
            input_hashes=input_hashes,
        )
        if gate_result.validator_version != definition.validator_version:
            raise ValueError(
                "semantic validator version does not match semantic.integrity gate definition"
            )
        return engine.register_result(
            stage_run_id,
            gate_id="semantic.integrity",
            result=gate_result,
            context=context,
            gate_result=GateResult.PASSED if validation_result.passed else GateResult.FAILED,
        )


def _semantic_hash(graph: Any) -> str:
    from aifde.ontology.rdf import graph_hash

    return graph_hash(graph)


class SemanticValidationTool:
    """A ToolGateway-registered tool that requires ``Capability.VALIDATE``."""

    tool_id = "semantic_validation"
    required_capabilities = frozenset({Capability.VALIDATE})
    allowed_stage_ids = frozenset({"ontology.design"})

    def __init__(self, validator: ShaclValidator | None = None) -> None:
        if validator is not None and not isinstance(validator, ShaclValidator):
            raise TypeError("validator must be a ShaclValidator")
        self.validator = validator or ShaclValidator()

    def call(self, context: ToolContext, payload: dict[str, Any]) -> ToolResult:
        from aifde.policy.gateway import _ACTIVE_INVOCATION

        if not isinstance(context, ToolContext):
            raise TypeError("context must be a ToolContext")
        invocation = _ACTIVE_INVOCATION.get()
        if (
            invocation is None
            or invocation.tool_id != self.tool_id
            or invocation.context is not context
        ):
            raise PermissionError("SemanticValidationTool.call requires a ToolGateway invocation")
        if context.capability is not Capability.VALIDATE:
            raise PermissionError("semantic validation requires the VALIDATE capability")
        if type(payload) is not dict:
            raise TypeError("payload must be a dict")
        expected = {"data_text", "shapes_text"}
        if set(payload) != expected:
            missing = sorted(expected - set(payload))
            extra = sorted(set(payload) - expected)
            details = []
            if missing:
                details.append(f"missing keys: {', '.join(missing)}")
            if extra:
                details.append(f"unexpected keys: {', '.join(extra)}")
            raise ValueError("invalid semantic validation payload (" + "; ".join(details) + ")")
        result = self.validator.validate(payload["data_text"], payload["shapes_text"])
        return ToolResult(
            status="validated" if result.passed else "failed",
            evidence_refs=result.evidence_refs,
            payload=result.model_dump(mode="json"),
        )


__all__ = [
    "SemanticValidationTool",
    "ShaclValidator",
    "VALIDATOR_VERSION",
    "ValidationResult",
]
