"""Domain-neutral Ontology intermediate representation and compiler.

The IR is the boundary between evidence-backed semantic candidates and
runtime-specific representations.  A domain pack may provide classes,
properties, relationships, events, states, and metrics, while this module is
responsible only for deterministic validation and typed RDFS/SHACL output.
"""

from __future__ import annotations

from hashlib import sha256
import json
import re
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


IRStatus = Literal["proposed", "accepted", "rejected", "deprecated"]

_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
_RDFS = "http://www.w3.org/2000/01/rdf-schema#"
_XSD = "http://www.w3.org/2001/XMLSchema#"
_SH = "http://www.w3.org/ns/shacl#"

_TYPE_MAP = {
    "string": "xsd:string",
    "text": "xsd:string",
    "integer": "xsd:integer",
    "int": "xsd:integer",
    "number": "xsd:double",
    "float": "xsd:double",
    "boolean": "xsd:boolean",
    "bool": "xsd:boolean",
    "date": "xsd:date",
    "datetime": "xsd:dateTime",
    "date-time": "xsd:dateTime",
}


def _text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    return value.strip()


def _refs(value: Any, field_name: str = "evidence_refs") -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        value = (value,)
    if not isinstance(value, (tuple, list, set, frozenset)):
        raise TypeError(f"{field_name} must be a sequence of strings")
    result = tuple(_text(item, field_name) for item in value)
    if len(set(result)) != len(result):
        raise ValueError(f"{field_name} must not contain duplicates")
    return result


def _safe_local(value: str) -> str:
    local = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_")
    if not local:
        raise ValueError("ontology names must contain an alphanumeric character")
    if local[0].isdigit():
        local = f"_{local}"
    return local


def _literal(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


class IRItem(BaseModel):
    """Common metadata for an evidence-backed semantic declaration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    label: str
    evidence_refs: tuple[str, ...] = ()
    version: str
    status: IRStatus = "proposed"

    @field_validator("name", "label", "version")
    @classmethod
    def validate_text(cls, value: str, info: Any) -> str:
        return _text(value, info.field_name)

    @field_validator("evidence_refs", mode="before")
    @classmethod
    def normalize_evidence_refs(cls, value: Any) -> tuple[str, ...]:
        return _refs(value)


class ClassIR(IRItem):
    """A business object or event type."""

    description: str | None = None


class PropertyIR(IRItem):
    """A scalar or typed value owned by a class."""

    domain: str
    value_type: str
    range: str | None = None
    min_count: int = Field(default=0, ge=0)
    max_count: int | None = Field(default=None, ge=0)

    @field_validator("domain", "value_type", "range")
    @classmethod
    def validate_type_text(cls, value: str | None, info: Any) -> str | None:
        if value is None:
            return None
        return _text(value, info.field_name)

    @model_validator(mode="after")
    def validate_cardinality(self) -> PropertyIR:
        if self.max_count is not None and self.max_count < self.min_count:
            raise ValueError("property max_count must be >= min_count")
        return self


class RelationshipIR(IRItem):
    """A typed relation between two business classes."""

    source: str
    target: str
    min_count: int = Field(default=0, ge=0)
    max_count: int | None = Field(default=None, ge=0)

    @field_validator("source", "target")
    @classmethod
    def validate_endpoint(cls, value: str, info: Any) -> str:
        return _text(value, info.field_name)

    @model_validator(mode="after")
    def validate_cardinality(self) -> RelationshipIR:
        if self.max_count is not None and self.max_count < self.min_count:
            raise ValueError("relationship max_count must be >= min_count")
        return self


class EventIR(IRItem):
    """An event that changes or observes a business object."""

    subject: str | None = None
    event_time_field: str | None = None

    @field_validator("subject", "event_time_field")
    @classmethod
    def validate_optional_text(cls, value: str | None, info: Any) -> str | None:
        if value is None:
            return None
        return _text(value, info.field_name)


class StateIR(IRItem):
    """A governed finite state set for a business object."""

    subject: str
    values: tuple[str, ...]

    @field_validator("subject")
    @classmethod
    def validate_subject(cls, value: str) -> str:
        return _text(value, "subject")

    @field_validator("values", mode="before")
    @classmethod
    def normalize_values(cls, value: Any) -> tuple[str, ...]:
        values = _refs(value, "values")
        if not values:
            raise ValueError("state values must not be empty")
        return values


class MetricIR(IRItem):
    """A declared metric whose execution belongs to the compute runtime."""

    subject: str
    value_type: str = "number"
    expression: str
    time_grain: str

    @field_validator("subject", "value_type", "expression", "time_grain")
    @classmethod
    def validate_metric_text(cls, value: str, info: Any) -> str:
        return _text(value, info.field_name)


class OntologyIR(BaseModel):
    """A versioned, evidence-aware semantic model candidate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ontology_id: str
    version: str
    namespace: str
    classes: tuple[ClassIR, ...] = ()
    properties: tuple[PropertyIR, ...] = ()
    relationships: tuple[RelationshipIR, ...] = ()
    events: tuple[EventIR, ...] = ()
    states: tuple[StateIR, ...] = ()
    metrics: tuple[MetricIR, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    status: IRStatus = "proposed"

    @field_validator("ontology_id", "version", "namespace")
    @classmethod
    def validate_identity_text(cls, value: str, info: Any) -> str:
        return _text(value, info.field_name)

    @field_validator(
        "classes",
        "properties",
        "relationships",
        "events",
        "states",
        "metrics",
        mode="before",
    )
    @classmethod
    def normalize_items(cls, value: Any) -> tuple[Any, ...]:
        if value is None:
            return ()
        if not isinstance(value, (tuple, list)):
            raise TypeError("ontology declarations must be a sequence")
        return tuple(value)

    @field_validator("evidence_refs", mode="before")
    @classmethod
    def normalize_ir_refs(cls, value: Any) -> tuple[str, ...]:
        return _refs(value)

    @model_validator(mode="after")
    def validate_unique_names(self) -> OntologyIR:
        declarations = (
            *self.classes,
            *self.properties,
            *self.relationships,
            *self.events,
            *self.states,
            *self.metrics,
        )
        names = [item.name for item in declarations]
        if len(names) != len(set(names)):
            raise ValueError("ontology declaration names must be unique")
        return self

    def declarations(self) -> tuple[IRItem, ...]:
        return (
            *self.classes,
            *self.properties,
            *self.relationships,
            *self.events,
            *self.states,
            *self.metrics,
        )


class OntologyArtifacts(BaseModel):
    """Deterministic compiler output and release readiness."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ontology_id: str
    version: str
    ontology_text: str
    shapes_text: str
    data_schema: dict[str, Any]
    ontology_hash: str
    shapes_hash: str
    schema_hash: str
    artifact_hash: str
    evidence_refs: tuple[str, ...]
    release_eligible: bool
    violations: tuple[str, ...] = ()

    def require_release(self) -> OntologyArtifacts:
        if not self.release_eligible:
            reason = "; ".join(self.violations) or "ontology artifacts are not release eligible"
            raise ValueError(f"cannot release ontology artifacts: {reason}")
        return self


class OntologyIRCompiler:
    """Compile semantic IR into deterministic typed RDFS and SHACL text."""

    compiler_version = "ontology-ir-compiler-v1"

    def compile(self, ir: OntologyIR) -> OntologyArtifacts:
        if not isinstance(ir, OntologyIR):
            raise TypeError("ir must be an OntologyIR")
        class_names = {item.name for item in ir.classes}
        for property_ir in ir.properties:
            if property_ir.domain not in class_names:
                raise ValueError(f"property {property_ir.name!r} has unknown class domain {property_ir.domain!r}")
            if property_ir.range and property_ir.range not in class_names and property_ir.range not in _TYPE_MAP:
                raise ValueError(f"property {property_ir.name!r} has unknown class range {property_ir.range!r}")
        for relation in ir.relationships:
            if relation.source not in class_names or relation.target not in class_names:
                raise ValueError(f"relationship {relation.name!r} references unknown class")
        for event in ir.events:
            if event.subject is not None and event.subject not in class_names:
                raise ValueError(f"event {event.name!r} references unknown class")
        for state in ir.states:
            if state.subject not in class_names:
                raise ValueError(f"state {state.name!r} references unknown class")
        for metric in ir.metrics:
            if metric.subject not in class_names:
                raise ValueError(f"metric {metric.name!r} references unknown class")

        violations = self._release_violations(ir)
        ontology_text = self._render_ontology(ir)
        shapes_text = self._render_shapes(ir)
        schema = self._render_schema(ir)
        ontology_hash = _hash_text(ontology_text)
        shapes_hash = _hash_text(shapes_text)
        schema_hash = _hash_json(schema)
        artifact_hash = _hash_json(
            {
                "compiler_version": self.compiler_version,
                "ontology_hash": ontology_hash,
                "shapes_hash": shapes_hash,
                "schema_hash": schema_hash,
                "evidence_refs": ir.evidence_refs,
                "violations": violations,
            }
        )
        return OntologyArtifacts(
            ontology_id=ir.ontology_id,
            version=ir.version,
            ontology_text=ontology_text,
            shapes_text=shapes_text,
            data_schema=schema,
            ontology_hash=ontology_hash,
            shapes_hash=shapes_hash,
            schema_hash=schema_hash,
            artifact_hash=artifact_hash,
            evidence_refs=ir.evidence_refs,
            release_eligible=not violations,
            violations=violations,
        )

    @staticmethod
    def _release_violations(ir: OntologyIR) -> tuple[str, ...]:
        violations: list[str] = []
        if not ir.evidence_refs:
            violations.append("ontology candidate requires evidence_refs before release")
        allowed = set(ir.evidence_refs)
        for item in ir.declarations():
            if not item.evidence_refs:
                violations.append(f"declaration {item.name!r} requires evidence_refs before release")
            elif not set(item.evidence_refs).issubset(allowed):
                violations.append(f"declaration {item.name!r} references evidence outside ontology closure")
            if item.status == "rejected":
                violations.append(f"declaration {item.name!r} is rejected")
        if ir.status == "rejected":
            violations.append("ontology candidate is rejected")
        return tuple(violations)

    @staticmethod
    def _render_ontology(ir: OntologyIR) -> str:
        lines = [
            "@prefix ex: <" + ir.namespace + "> .",
            "@prefix rdf: <" + _RDF + "> .",
            "@prefix rdfs: <" + _RDFS + "> .",
            "@prefix xsd: <" + _XSD + "> .",
            "",
            f"ex:Ontology a rdfs:Class ; rdfs:label {_literal(ir.ontology_id)} ; ex:version {_literal(ir.version)} .",
        ]
        for item in sorted(ir.classes, key=lambda value: value.name):
            lines.append(
                f"ex:{_safe_local(item.name)} a rdfs:Class ; rdfs:label {_literal(item.label)} ."
            )
        for item in sorted(ir.events, key=lambda value: value.name):
            subject = f"ex:{_safe_local(item.name)}"
            lines.append(
                f"{subject} a rdfs:Class ; rdfs:label {_literal(item.label)} ; rdfs:subClassOf ex:Event ."
            )
        for item in sorted(ir.properties, key=lambda value: value.name):
            range_term = _range_term(item.value_type, item.range, {item.name for item in ir.classes})
            lines.append(
                f"ex:{_safe_local(item.name)} a rdf:Property ; rdfs:label {_literal(item.label)} ; "
                f"rdfs:domain ex:{_safe_local(item.domain)} ; rdfs:range {range_term} ."
            )
        for item in sorted(ir.relationships, key=lambda value: value.name):
            lines.append(
                f"ex:{_safe_local(item.name)} a rdf:Property ; rdfs:label {_literal(item.label)} ; "
                f"rdfs:domain ex:{_safe_local(item.source)} ; rdfs:range ex:{_safe_local(item.target)} ."
            )
        for item in sorted(ir.metrics, key=lambda value: value.name):
            lines.append(
                f"ex:{_safe_local(item.name)} a rdf:Property ; rdfs:label {_literal(item.label)} ; "
                f"rdfs:domain ex:{_safe_local(item.subject)} ; rdfs:range {_range_term(item.value_type, None, set())} ."
            )
        for item in sorted(ir.states, key=lambda value: value.name):
            lines.append(
                f"ex:{_safe_local(item.name)} a rdfs:Class ; rdfs:label {_literal(item.label)} ; "
                f"ex:subject ex:{_safe_local(item.subject)} ."
            )
        return "\n".join(lines) + "\n"

    @staticmethod
    def _render_shapes(ir: OntologyIR) -> str:
        lines = [
            "@prefix ex: <" + ir.namespace + "> .",
            "@prefix rdf: <" + _RDF + "> .",
            "@prefix sh: <" + _SH + "> .",
            "@prefix xsd: <" + _XSD + "> .",
            "",
        ]
        declarations: list[tuple[str, str, int, int | None, str | None, str | None]] = []
        for item in ir.properties:
            declarations.append((item.domain, item.name, item.min_count, item.max_count, item.value_type, item.range))
        for item in ir.relationships:
            declarations.append((item.source, item.name, item.min_count, item.max_count, None, item.target))
        for item in ir.metrics:
            declarations.append((item.subject, item.name, 0, None, item.value_type, None))
        grouped: dict[str, list[tuple[str, int, int | None, str | None, str | None]]] = {}
        for subject, path, minimum, maximum, value_type, range_type in declarations:
            grouped.setdefault(subject, []).append((path, minimum, maximum, value_type, range_type))
        for class_ir in sorted(ir.classes, key=lambda value: value.name):
            class_local = _safe_local(class_ir.name)
            lines.append(
                f"ex:{class_local}Shape a sh:NodeShape ; sh:targetClass ex:{class_local} ."
            )
            for path, minimum, maximum, value_type, range_type in sorted(grouped.get(class_ir.name, [])):
                shape_local = f"{class_local}_{_safe_local(path)}Shape"
                lines.append(
                    f"ex:{class_local}Shape sh:property ex:{shape_local} ."
                )
                lines.append(
                    f"ex:{shape_local} sh:path ex:{_safe_local(path)} ; sh:minCount {minimum}"
                    + (f" ; sh:maxCount {maximum}" if maximum is not None else "")
                    + _shape_type(value_type, range_type, {item.name for item in ir.classes})
                    + " ."
                )
        return "\n".join(lines) + "\n"

    @staticmethod
    def _render_schema(ir: OntologyIR) -> dict[str, Any]:
        return {
            "ontology_id": ir.ontology_id,
            "version": ir.version,
            "namespace": ir.namespace,
            "classes": [item.name for item in sorted(ir.classes, key=lambda value: value.name)],
            "properties": [
                {
                    "name": item.name,
                    "domain": item.domain,
                    "value_type": item.value_type,
                    "range": item.range,
                    "min_count": item.min_count,
                    "max_count": item.max_count,
                }
                for item in sorted(ir.properties, key=lambda value: value.name)
            ],
            "relationships": [
                {"name": item.name, "source": item.source, "target": item.target}
                for item in sorted(ir.relationships, key=lambda value: value.name)
            ],
            "events": [item.name for item in sorted(ir.events, key=lambda value: value.name)],
            "states": [
                {"name": item.name, "subject": item.subject, "values": item.values}
                for item in sorted(ir.states, key=lambda value: value.name)
            ],
            "metrics": [
                {"name": item.name, "subject": item.subject, "expression": item.expression}
                for item in sorted(ir.metrics, key=lambda value: value.name)
            ],
        }


def _range_term(value_type: str, range_type: str | None, class_names: set[str]) -> str:
    candidate = range_type or value_type
    normalized = candidate.strip().lower()
    if normalized in _TYPE_MAP:
        return _TYPE_MAP[normalized]
    if candidate in class_names:
        return f"ex:{_safe_local(candidate)}"
    if "://" in candidate:
        return f"<{candidate}>"
    return f"ex:{_safe_local(candidate)}"


def _shape_type(value_type: str | None, range_type: str | None, class_names: set[str]) -> str:
    if value_type is None and range_type is None:
        return ""
    candidate = range_type or value_type or "string"
    normalized = candidate.strip().lower()
    if normalized in _TYPE_MAP:
        return f" ; sh:datatype {_TYPE_MAP[normalized]}"
    if candidate in class_names:
        return f" ; sh:class ex:{_safe_local(candidate)}"
    return ""


def _hash_text(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _hash_json(value: Mapping[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=_json_default)
    return _hash_text(payload)


def _json_default(value: Any) -> Any:
    if isinstance(value, tuple):
        return list(value)
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


__all__ = [
    "ClassIR",
    "EventIR",
    "IRItem",
    "IRStatus",
    "MetricIR",
    "OntologyArtifacts",
    "OntologyIR",
    "OntologyIRCompiler",
    "PropertyIR",
    "RelationshipIR",
    "StateIR",
]
