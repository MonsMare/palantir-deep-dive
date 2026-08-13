"""Software-delivery RDF projection and SHACL semantic gate adapter."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, XSD

from aifde.ontology.rdf import graph_hash
from aifde.tools.validation import ShaclValidator, ValidationResult

from .generator import DatasetBundle


EX = Namespace("urn:software-delivery:")
ONTOLOGY_ROOT = Path("projects/software-delivery-demo/ontology")


def _uri(kind: str, identifier: str) -> URIRef:
    return URIRef(f"{EX}{kind}/{identifier}")


def _normalize_subject(value: str) -> URIRef:
    if "://" in value:
        return URIRef(value)
    if "/" in value:
        kind, identifier = value.split("/", 1)
        return _uri(kind, identifier)
    return URIRef(f"{EX}{value}")


def _normalize_predicate(value: str) -> URIRef:
    if "://" in value:
        return URIRef(value)
    return URIRef(f"{EX}{value}")


@dataclass
class OntologyDocument:
    graph: Graph
    ontology_version: str = "1.0.0"
    source_refs: list[str] | None = None

    def __post_init__(self) -> None:
        self.source_refs = list(self.source_refs or [])

    @property
    def data_hash(self) -> str:
        return graph_hash(self.graph)

    def serialize(self, format: str = "turtle") -> str:
        rendered = self.graph.serialize(format=format)
        return rendered.decode("utf-8") if isinstance(rendered, bytes) else str(rendered)

    def add_type(self, subject: str, class_name: str) -> None:
        self.graph.add((_normalize_subject(subject), RDF.type, _normalize_subject(class_name)))

    def remove_link(self, subject: str, predicate: str, object_id: str) -> None:
        self.graph.remove(
            (_normalize_subject(subject), _normalize_predicate(predicate), _normalize_subject(object_id))
        )


def project_objects_to_graph(bundle: DatasetBundle) -> OntologyDocument:
    graph = Graph()
    graph.bind("ex", EX)
    graph.add((EX.ontology, RDF.type, EX.Ontology))
    graph.add((EX.ontology, EX.version, Literal("1.0.0")))
    graph.add((EX.ontology, EX.sourceRef, Literal("synthetic-fixture")))
    for row in bundle.requirements.iter_rows(named=True):
        subject = _uri("Requirement", row["requirement_id"])
        graph.add((subject, RDF.type, EX.Requirement))
        for field in ("requirement_id", "goal", "owner", "status"):
            value = row.get(field)
            if value is not None and str(value) != "":
                graph.add((subject, EX[field], Literal(value)))
        graph.add((subject, EX.module, _uri("Module", str(row["module_id"]))))
    requirement_by_id = {
        row["requirement_id"]: row for row in bundle.requirements.iter_rows(named=True)
    }
    for row in bundle.changes.iter_rows(named=True):
        subject = _uri("ChangeRequest", row["change_id"])
        graph.add((subject, RDF.type, EX.ChangeRequest))
        for field in ("change_id", "requested_at", "requester", "status"):
            value = row.get(field)
            if value is not None and str(value) != "":
                graph.add((subject, EX[field], Literal(value)))
        if row["requirement_id"] in requirement_by_id:
            graph.add((subject, EX.changes, _uri("Requirement", row["requirement_id"])))
    for row in bundle.work_items.iter_rows(named=True):
        subject = _uri("WorkItem", row["work_item_id"])
        graph.add((subject, RDF.type, EX.WorkItem))
        for field in ("work_item_id", "status"):
            graph.add((subject, EX[field], Literal(row[field])))
        graph.add((subject, EX.requirement, _uri("Requirement", row["requirement_id"])))
        graph.add((subject, EX.module, _uri("Module", row["module_id"])))
        graph.add((subject, EX.team, _uri("Team", row["team_id"])))
        graph.add((subject, EX.plannedIn, _uri("Sprint", row["sprint_id"])))
        graph.add((_uri("Requirement", row["requirement_id"]), EX.decomposedInto, subject))
    for row in bundle.dependencies.iter_rows(named=True):
        subject = _uri("Dependency", row["dependency_id"])
        graph.add((subject, RDF.type, EX.Dependency))
        graph.add((subject, EX.predecessor, _uri("WorkItem", row["predecessor_id"])))
        graph.add((subject, EX.successor, _uri("WorkItem", row["successor_id"])))
        graph.add((subject, EX.dependency_type, Literal(row["dependency_type"])))
        graph.add((subject, EX.status, Literal(row["status"])))
    return OntologyDocument(
        graph=graph,
        ontology_version="1.0.0",
        source_refs=["synthetic-fixture"],
    )


def build_domain_graph(bundle: DatasetBundle) -> OntologyDocument:
    return project_objects_to_graph(bundle)


def load_domain_graph(path: Path) -> OntologyDocument:
    graph = Graph()
    graph.parse(path, format="turtle")
    version = next((str(value) for value in graph.objects(EX.ontology, EX.version)), "1.0.0")
    sources = [str(value) for value in graph.objects(EX.ontology, EX.sourceRef)]
    return OntologyDocument(graph=graph, ontology_version=version, source_refs=sources)


def validate_domain_graph(document: OntologyDocument) -> ValidationResult:
    if not isinstance(document, OntologyDocument):
        raise TypeError("document must be a software delivery OntologyDocument")
    shapes_path = ONTOLOGY_ROOT / "shapes.ttl"
    return ShaclValidator().validate(
        document.serialize("turtle"),
        shapes_path.read_text(encoding="utf-8"),
    )


__all__ = [
    "OntologyDocument",
    "build_domain_graph",
    "load_domain_graph",
    "project_objects_to_graph",
    "validate_domain_graph",
]
