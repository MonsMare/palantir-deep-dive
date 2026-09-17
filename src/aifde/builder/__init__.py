"""Evidence-driven ontology builder contracts and source registration."""

from .contracts import (
    EvidenceFragment,
    FieldEvidenceLocation,
    FieldValueProvenance,
    SourceAsset,
    SourceSnapshot,
)
from .compiler import (
    CompileResult,
    CompileValidation,
    MappingCompiler,
    MappingSpec,
    OntologyCandidate,
)
from .flow import BuilderRunConfig, BuilderRunResult, EvidenceDrivenOntologyBuilder
from .gates import BuilderGateReport, BuilderGateRunner, OntologyReleasePackage
from .sources import SourceRegistry
from .persistence import BuilderRegistry, SQLiteBuilderRegistry

__all__ = [
    "CompileResult",
    "CompileValidation",
    "EvidenceFragment",
    "FieldEvidenceLocation",
    "FieldValueProvenance",
    "MappingCompiler",
    "MappingSpec",
    "OntologyCandidate",
    "SourceAsset",
    "SourceRegistry",
    "SourceSnapshot",
    "BuilderGateReport",
    "BuilderGateRunner",
    "BuilderRunConfig",
    "BuilderRunResult",
    "EvidenceDrivenOntologyBuilder",
    "OntologyReleasePackage",
    "BuilderRegistry",
    "SQLiteBuilderRegistry",
]
