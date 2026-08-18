"""Domain-neutral AI-FDE platform contracts."""

from .domain_pack import DomainPack, DomainPackRegistry
from .ontology_ir import (
    ClassIR,
    EventIR,
    IRItem,
    IRStatus,
    MetricIR,
    OntologyArtifacts,
    OntologyIR,
    OntologyIRCompiler,
    PropertyIR,
    RelationshipIR,
    StateIR,
)

__all__ = [
    "ClassIR",
    "DomainPack",
    "DomainPackRegistry",
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
