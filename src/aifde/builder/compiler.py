"""Compile semantic candidates into executable, traceable ontology artifacts."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any
from uuid import uuid4

from aifde.tools.validation import ShaclValidator

from .contracts import (
    EvidenceFragment,
    FieldEvidenceLocation,
    FieldValueProvenance,
    SourceSnapshot,
)
from .semantic import (
    CandidateProposal,
    MappingCandidate,
    _ContextBindingAuthority,
)
from .sources import SourceRegistry


COMPILER_VERSION = "mapping-compiler-v1"
TARGET_GRAIN = "purchase_order"
_EXPECTED_SOURCE_PATHS = frozenset(
    {
        "$.purchase_orders[*].supplier",
        "$.purchase_orders[*].promised_date",
    }
)
_ALLOWED_DELAY_STATES = frozenset({"OnTime", "AtRisk", "Delayed", "Unknown"})


def _nonblank(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must not be empty")
    return value.strip()


def _hash_text(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _hash_json(value: Any) -> str:
    payload = json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return _hash_text(payload)


def _jsonable(value: Any) -> Any:
    """Convert compiler values to deterministic JSON without losing contracts."""

    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump(mode="python"))
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _iso(value: datetime) -> str:
    return value.isoformat()


def _parse_datetime(value: Any, name: str) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        try:
            result = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{name} must be an ISO datetime") from exc
    else:
        raise ValueError(f"{name} must be an ISO datetime")
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return result


def _date_as_datetime(value: str, name: str) -> datetime:
    """Parse a date-like business value at UTC midnight for temporal joins."""

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO date or datetime") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _safe_local_name(value: str) -> str:
    normalized = "".join(char.lower() if char.isalnum() else "-" for char in value)
    normalized = "-".join(part for part in normalized.split("-") if part)
    return normalized or "unknown"


def _escape_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


@dataclass(frozen=True)
class MappingSpec:
    """Executable source-to-product mapping with lineage and policy."""

    mapping_id: str
    source_field_path: str
    target_product: str
    target_grain: str
    target_field: str
    transform_expression: str
    identity_rule: str
    time_semantics: str
    null_policy: str
    lineage_refs: tuple[str, ...]
    security_policy: str
    version: str

    def __post_init__(self) -> None:
        for name in (
            "mapping_id",
            "source_field_path",
            "target_product",
            "target_grain",
            "target_field",
            "transform_expression",
            "identity_rule",
            "time_semantics",
            "null_policy",
            "security_policy",
            "version",
        ):
            _nonblank(getattr(self, name), name)
        if not self.lineage_refs or any(not isinstance(item, str) or not item.strip() for item in self.lineage_refs):
            raise ValueError("mapping lineage_refs must be non-empty")


@dataclass(frozen=True)
class OntologyCandidate:
    """Versioned semantic model candidate, never a published ontology."""

    candidate_id: str
    version: str
    classes: tuple[str, ...]
    properties: tuple[str, ...]
    relationships: tuple[tuple[str, str, str], ...]
    states: tuple[str, ...]
    events: tuple[str, ...]
    identity_keys: tuple[tuple[str, tuple[str, ...]], ...]
    temporal_semantics: tuple[tuple[str, str], ...]
    access_policies: tuple[tuple[str, str], ...]
    mapping_spec_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    open_questions: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()


@dataclass(frozen=True)
class CompileValidation:
    """Deterministic compiler validation report."""

    passed: bool
    violations: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    compiler_version: str = COMPILER_VERSION


@dataclass
class CompileResult:
    """All candidate artifacts produced by one compiler run."""

    ontology_candidate: OntologyCandidate
    mapping_specs: tuple[MappingSpec, ...]
    canonical_rows: list[dict[str, Any]]
    provenance_rows: list[dict[str, Any]]
    validation_report: CompileValidation
    artifact_hashes: dict[str, str]
    ontology_turtle: str
    shapes_turtle: str
    data_turtle: str = ""
    proposal_evidence_refs: tuple[str, ...] = ()
    source_field_paths: tuple[str, ...] = ()
    artifact_manifest_id: str = ""
    canonical_line_rows: list[dict[str, Any]] | None = None
    canonical_revision_rows: list[dict[str, Any]] | None = None
    # Domain Pack metadata keeps gates and downstream runtimes from guessing
    # which business key or grain a compiler happened to use.  Defaults
    # preserve the public supplier-delay compatibility surface.
    domain_pack_id: str = "supplier-delay"
    primary_key_field: str = "purchase_order_id"
    target_product: str = "purchase_order"
    target_grain: str = "purchase_order"
    required_fields: tuple[str, ...] = ("supplier_id", "promised_delivery_date")
    business_exception_coverage: bool = False

    def materialize_as_of(self, as_of_time: datetime) -> list[dict[str, Any]]:
        """Return only field values available at the requested point in time.

        This is deliberately a projection, not a mutation: the released
        canonical product retains all known facts while a historical feature
        snapshot sees only the fields that were actually available then.
        """

        as_of_time = _parse_datetime(as_of_time, "as_of_time")
        materialized: list[dict[str, Any]] = []
        for row in self.canonical_rows:
            fields = row.get("field_provenance")
            if not isinstance(fields, Mapping):
                raise ValueError("canonical row requires field provenance for as-of materialization")
            projected = {
                key: value
                for key, value in row.items()
                if key not in {"field_provenance", "evidence_refs", "mapping_ids"}
            }
            visible_fields: dict[str, dict[str, Any]] = {}
            visible_evidence: list[str] = []
            visible_mappings: list[str] = []
            for field_name, provenance in fields.items():
                if not isinstance(provenance, FieldValueProvenance):
                    raise ValueError(f"field provenance for {field_name!r} is invalid")
                if not provenance.available_by(as_of_time):
                    projected.pop(field_name, None)
                    continue
                projected[field_name] = provenance.value
                visible_fields[field_name] = _jsonable(provenance)
                visible_evidence.extend(provenance.evidence_refs)
                visible_mappings.extend(provenance.mapping_ids)
            if "actual_delivery_date" not in visible_fields:
                projected["delay_state"] = "Unknown"
                projected.pop("delay_days", None)
                promised_provenance = fields.get("promised_delivery_date")
                if isinstance(promised_provenance, FieldValueProvenance):
                    unknown_provenance = FieldValueProvenance(
                        field_name="delay_state",
                        value="Unknown",
                        evidence_refs=promised_provenance.evidence_refs,
                        mapping_ids=promised_provenance.mapping_ids,
                        source_locations=promised_provenance.source_locations,
                        observed_at=promised_provenance.observed_at,
                        available_at=promised_provenance.available_at,
                    )
                    visible_fields["delay_state"] = _jsonable(unknown_provenance)
            elif "promised_delivery_date" in visible_fields:
                promised = _date_as_datetime(
                    str(visible_fields["promised_delivery_date"]["value"]),
                    "promised_delivery_date",
                )
                actual = _date_as_datetime(
                    str(visible_fields["actual_delivery_date"]["value"]),
                    "actual_delivery_date",
                )
                delay_days = max(0, (actual.date() - promised.date()).days)
                projected["delay_days"] = delay_days
                projected["delay_state"] = "Delayed" if delay_days > 0 else "OnTime"
            projected["field_provenance"] = visible_fields
            projected["evidence_refs"] = list(dict.fromkeys(visible_evidence))
            projected["mapping_ids"] = list(dict.fromkeys(visible_mappings))
            if visible_fields:
                projected["observed_at"] = max(
                    item["observed_at"] for item in visible_fields.values()
                )
                projected["available_at"] = max(
                    item["available_at"] for item in visible_fields.values()
                )
            projected["as_of_time"] = as_of_time.isoformat()
            line_rows = []
            for line in self.canonical_line_rows or []:
                if str(line.get("purchase_order_id")) != str(row.get("purchase_order_id")):
                    continue
                line_fields = line.get("field_provenance")
                if not isinstance(line_fields, Mapping):
                    raise ValueError("canonical line row requires field provenance")
                line_projected = {
                    key: value
                    for key, value in line.items()
                    if key not in {"field_provenance", "evidence_refs", "mapping_ids"}
                }
                visible_line_fields: dict[str, dict[str, Any]] = {}
                line_evidence: list[str] = []
                line_mappings: list[str] = []
                for field_name, provenance in line_fields.items():
                    if not isinstance(provenance, FieldValueProvenance):
                        raise ValueError(f"line field provenance for {field_name!r} is invalid")
                    if not provenance.available_by(as_of_time):
                        line_projected.pop(field_name, None)
                        continue
                    line_projected[field_name] = provenance.value
                    visible_line_fields[field_name] = _jsonable(provenance)
                    line_evidence.extend(provenance.evidence_refs)
                    line_mappings.extend(provenance.mapping_ids)
                line_projected["field_provenance"] = visible_line_fields
                line_projected["evidence_refs"] = list(dict.fromkeys(line_evidence))
                line_projected["mapping_ids"] = list(dict.fromkeys(line_mappings))
                line_projected["as_of_time"] = as_of_time.isoformat()
                line_rows.append(line_projected)
            if line_rows:
                projected["line_rows"] = line_rows
            revision_rows = []
            for revision in self.canonical_revision_rows or []:
                if str(revision.get("purchase_order_id")) != str(row.get("purchase_order_id")):
                    continue
                if _parse_datetime(revision["available_at"], "revision.available_at") <= as_of_time:
                    revision_rows.append(dict(revision))
            if revision_rows:
                projected["revision_rows"] = revision_rows
            materialized.append(projected)
        return materialized


def _rdfs_shape_validation(ontology_turtle: str, shapes_turtle: str) -> Any:
    return ShaclValidator().validate(ontology_turtle, shapes_turtle)


class _ArtifactManifestAuthority:
    """Keep a compiler-issued manifest outside the mutable result object."""

    _manifests: dict[str, dict[str, str]] = {}

    @classmethod
    def issue(cls, hashes: Mapping[str, str]) -> str:
        manifest_id = f"manifest:{uuid4()}"
        cls._manifests[manifest_id] = dict(hashes)
        return manifest_id

    @classmethod
    def verify(cls, manifest_id: str, hashes: Mapping[str, str]) -> bool:
        return bool(manifest_id and cls._manifests.get(manifest_id) == dict(hashes))


class MappingCompiler:
    """Compile the local supplier-delay candidate without hidden side effects."""

    compiler_version = COMPILER_VERSION

    def compile(
        self,
        proposal: CandidateProposal,
        source_registry: SourceRegistry,
        version: str,
    ) -> CompileResult:
        if not isinstance(proposal, CandidateProposal):
            raise TypeError("proposal must be a CandidateProposal")
        if not isinstance(source_registry, SourceRegistry):
            raise TypeError("source_registry must be a SourceRegistry")
        version = _nonblank(version, "version")
        if not proposal.evidence_refs:
            raise ValueError("proposal requires evidence refs before compilation")
        if not proposal.mappings:
            raise ValueError("proposal requires executable mappings before compilation")
        if not _ContextBindingAuthority.verify(
            proposal.context_binding,
            proposal.context_digest,
            proposal.model_dump(mode="python"),
        ):
            raise ValueError("proposal must carry a valid bound Builder context")
        if proposal.context_digest is None or any(
            item.context_digest != proposal.context_digest
            for item in (
                *proposal.terms,
                *proposal.entities,
                *proposal.entity_matches,
                *proposal.assertions,
                *proposal.mappings,
            )
        ):
            raise ValueError("proposal children must share the bound Builder context")

        fragments = self._load_fragments(proposal, source_registry)
        self._validate_proposal_evidence_closure(proposal, fragments)
        mapping_specs = tuple(
            self._mapping_spec(item, fragments, proposal.evidence_refs, version)
            for item in proposal.mappings
        )
        for mapping in mapping_specs:
            self._validate_mapping_spec(mapping, _EXPECTED_SOURCE_PATHS)
        canonical_rows, provenance_rows, canonical_line_rows, canonical_revision_rows = self._materialize_rows(
            proposal, fragments, mapping_specs, version
        )
        ontology_candidate = self._ontology_candidate(proposal, mapping_specs, version)
        ontology_turtle = self.render_turtle(ontology_candidate)
        shapes_turtle = self.render_shapes(ontology_candidate)
        data_turtle = self.render_data(
            canonical_rows, canonical_line_rows, canonical_revision_rows
        )
        validation = CompileValidation(passed=False, evidence_refs=tuple(proposal.evidence_refs))
        result = CompileResult(
            ontology_candidate=ontology_candidate,
            mapping_specs=mapping_specs,
            canonical_rows=canonical_rows,
            provenance_rows=provenance_rows,
            validation_report=validation,
            artifact_hashes={
                "ontology": _hash_text(ontology_turtle),
                "shapes": _hash_text(shapes_turtle),
                "mappings": _hash_json([self._mapping_dict(item) for item in mapping_specs]),
                "canonical_product": _hash_json(
                    {
                        "orders": canonical_rows,
                        "lines": canonical_line_rows,
                        "revisions": canonical_revision_rows,
                    }
                ),
                "provenance": _hash_json(provenance_rows),
                "canonical_rdf": _hash_text(data_turtle),
            },
            ontology_turtle=ontology_turtle,
            shapes_turtle=shapes_turtle,
            data_turtle=data_turtle,
            proposal_evidence_refs=tuple(proposal.evidence_refs),
            source_field_paths=tuple(sorted({item.source_field_path for item in mapping_specs})),
            canonical_line_rows=canonical_line_rows,
            canonical_revision_rows=canonical_revision_rows,
        )
        result.artifact_manifest_id = _ArtifactManifestAuthority.issue(result.artifact_hashes)
        validation = self.validate(result)
        result.validation_report = validation
        return result

    def materialize(
        self,
        mapping_spec: MappingSpec,
        snapshots: Sequence[SourceSnapshot],
    ) -> list[dict[str, Any]]:
        """Materialize one mapping against immutable JSON snapshots."""

        self._validate_mapping_spec(mapping_spec, source_field_paths=_EXPECTED_SOURCE_PATHS)
        rows: list[dict[str, Any]] = []
        for snapshot in snapshots:
            try:
                payload = json.loads(snapshot.content.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("source snapshot is not canonical JSON") from exc
            orders = payload.get("purchase_orders") if isinstance(payload, dict) else None
            if not isinstance(orders, list):
                continue
            for order in orders:
                if not isinstance(order, dict):
                    raise ValueError("purchase_orders must contain objects")
                po_id = _nonblank(str(order.get("po_id", "")), "po_id")
                value = self._extract_mapping_value(order, mapping_spec)
                supplier = _nonblank(str(order.get("supplier", "")), "supplier")
                promised = _nonblank(str(order.get("promised_date", "")), "promised_date")
                rows.append(
                    {
                        "purchase_order_id": po_id,
                        "supplier_id": value if mapping_spec.target_field == "supplier_id" else supplier,
                        "promised_delivery_date": value if mapping_spec.target_field == "promised_delivery_date" else promised,
                        "event_time": promised,
                        "observed_at": _iso(snapshot.observed_at),
                        "available_at": _iso(snapshot.available_at),
                        "target_grain": mapping_spec.target_grain,
                    }
                )
        return rows

    @staticmethod
    def render_data(
        canonical_rows: Sequence[Mapping[str, Any]],
        canonical_line_rows: Sequence[Mapping[str, Any]] = (),
        canonical_revision_rows: Sequence[Mapping[str, Any]] = (),
    ) -> str:
        """Render typed domain instances for non-vacuous SHACL validation."""

        def date_literal(value: Any) -> str:
            return f'"{_escape_literal(str(value))}"^^xsd:date'

        def state_term(value: Any) -> str:
            state = _nonblank(str(value), "delay_state")
            if state not in _ALLOWED_DELAY_STATES:
                raise ValueError(f"delay_state {state!r} is not governed")
            return f"ex:{state}"

        lines = [
            "@prefix ex: <urn:aifde:supplier-delay:> .",
            "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
            "",
        ]
        suppliers: set[str] = set()
        lines_by_po: dict[str, list[str]] = {}
        revisions_by_po: dict[str, list[str]] = {}
        for revision in canonical_revision_rows:
            revision_id = _nonblank(str(revision.get("revision_id", "")), "revision_id")
            po_id = _nonblank(str(revision.get("purchase_order_id", "")), "purchase_order_id")
            revision_slug = _safe_local_name(revision_id)
            revisions_by_po.setdefault(po_id, []).append(revision_slug)
            lines.append(
                f'ex:revision-{revision_slug} a ex:PromisedDateRevision ; '
                f'ex:revisionDate {date_literal(revision.get("revision_date", ""))} ; '
                f'ex:revisionReason "{_escape_literal(str(revision.get("reason", "")))}" ; '
                f'ex:forPurchaseOrder ex:po-{_safe_local_name(po_id)} .'
            )
        for line in canonical_line_rows:
            line_id = _nonblank(str(line.get("line_id", "")), "line_id")
            po_id = _nonblank(str(line.get("purchase_order_id", "")), "purchase_order_id")
            line_slug = _safe_local_name(line_id)
            lines_by_po.setdefault(po_id, []).append(line_slug)
            lines.append(
                f'ex:line-{line_slug} a ex:PurchaseOrderLine ; '
                f'ex:lineId "{_escape_literal(line_id)}" ; '
                f'ex:sku "{_escape_literal(str(line.get("sku", "")))}" ; '
                f'ex:quantity "{_escape_literal(str(line.get("quantity", "")))}"^^xsd:decimal ; '
                f'ex:forPurchaseOrder ex:po-{_safe_local_name(po_id)} .'
            )
        for row in canonical_rows:
            po_id = _nonblank(str(row.get("purchase_order_id", "")), "purchase_order_id")
            supplier_id = _nonblank(str(row.get("supplier_id", "")), "supplier_id")
            supplier_slug = _safe_local_name(supplier_id)
            suppliers.add(supplier_slug + "\t" + supplier_id)
            promised = str(row.get("promised_delivery_date", ""))
            po_parts = [
                f'ex:po-{_safe_local_name(po_id)} a ex:PurchaseOrder',
                f'ex:purchaseOrderId "{_escape_literal(po_id)}"',
                f'ex:promisedDeliveryDate {date_literal(promised)}',
                f'ex:delayState {state_term(row.get("delay_state", "Unknown"))}',
                f'ex:hasSupplier ex:supplier-{supplier_slug}',
                f'ex:hasPromisedDelivery ex:promise-{_safe_local_name(po_id)}',
            ]
            po_parts.extend(
                f'ex:hasLine ex:line-{line_slug}' for line_slug in lines_by_po.get(po_id, [])
            )
            po_parts.extend(
                f'ex:hasDateRevision ex:revision-{revision_slug}'
                for revision_slug in revisions_by_po.get(po_id, [])
            )
            actual_date = row.get("actual_delivery_date")
            if actual_date:
                event_slug = _safe_local_name(po_id)
                po_parts.append(f'ex:hasDeliveryEvent ex:event-{event_slug}')
                po_parts.append(f'ex:hasException ex:exception-{event_slug}')
            if row.get("delay_days") is not None:
                po_parts.append(
                    f'ex:delayDays "{_escape_literal(str(row["delay_days"]))}"^^xsd:integer'
                )
            lines.append(" ;\n    ".join(po_parts) + " .")
            lines.append(
                f'ex:promise-{_safe_local_name(po_id)} a ex:PromisedDelivery ; '
                f'ex:promisedDate {date_literal(promised)} ; '
                f'ex:forPurchaseOrder ex:po-{_safe_local_name(po_id)} .'
            )
            if actual_date:
                lines.append(
                    f'ex:event-{_safe_local_name(po_id)} a ex:DeliveryEvent ; '
                    f'ex:actualDeliveryDate {date_literal(actual_date)} ; '
                    f'ex:eventTime {date_literal(actual_date)} ; '
                    f'ex:forPurchaseOrder ex:po-{_safe_local_name(po_id)} .'
                )
                lines.append(
                    f'ex:exception-{_safe_local_name(po_id)} a ex:DeliveryException ; '
                    f'ex:exceptionState {state_term(row.get("delay_state", "Unknown"))} ; '
                    f'ex:affects ex:po-{_safe_local_name(po_id)} .'
                )
        for entry in sorted(suppliers):
            supplier_slug, supplier_id = entry.split("\t", 1)
            lines.append(
                f'ex:supplier-{supplier_slug} a ex:Supplier ; '
                f'ex:supplierId "{_escape_literal(supplier_id)}" .'
            )
        return "\n".join(lines) + "\n"

    @staticmethod
    def render_turtle(ontology_candidate: OntologyCandidate) -> str:
        lines = [
            "@prefix ex: <urn:aifde:supplier-delay:> .",
            "@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
            "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
            "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
            "",
            "<http://www.w3.org/2001/XMLSchema#date> a rdfs:Datatype .",
            "ex:ontology a ex:Ontology ;",
            f'    ex:version "{ontology_candidate.version}" ;',
            "    ex:sourceRef " + ", ".join(json.dumps(item) for item in ontology_candidate.evidence_refs) + " .",
        ]
        lines.append("")
        for class_name in ontology_candidate.classes:
            lines.append(f"ex:{class_name} a rdfs:Class .")
        lines.append("")
        for property_name in ontology_candidate.properties:
            lines.append(f"ex:{property_name} a rdf:Property .")
        lines.append("")
        property_ranges = {
            "supplierId": ("Supplier", "rdfs:Literal"),
            "purchaseOrderId": ("PurchaseOrder", "rdfs:Literal"),
            "lineId": ("PurchaseOrderLine", "rdfs:Literal"),
            "sku": ("PurchaseOrderLine", "rdfs:Literal"),
            "quantity": ("PurchaseOrderLine", "xsd:decimal"),
            "promisedDeliveryDate": ("PurchaseOrder", "xsd:date"),
            "actualDeliveryDate": ("DeliveryEvent", "xsd:date"),
            "promisedDate": ("PromisedDelivery", "xsd:date"),
            "eventTime": ("DeliveryEvent", "xsd:date"),
            "delayState": ("PurchaseOrder", "DelayState"),
            "exceptionState": ("DeliveryException", "DelayState"),
            "delayDays": ("PurchaseOrder", "xsd:integer"),
            "hasSupplier": ("PurchaseOrder", "Supplier"),
            "hasLine": ("PurchaseOrder", "PurchaseOrderLine"),
            "hasPromisedDelivery": ("PurchaseOrder", "PromisedDelivery"),
            "hasDateRevision": ("PurchaseOrder", "PromisedDateRevision"),
            "hasDeliveryEvent": ("PurchaseOrder", "DeliveryEvent"),
            "hasException": ("PurchaseOrder", "DeliveryException"),
            "forPurchaseOrder": ("DeliveryEvent", "PurchaseOrder"),
            "affects": ("DeliveryException", "PurchaseOrder"),
        }
        for property_name in ontology_candidate.properties:
            domain, range_name = property_ranges.get(property_name, ("Thing", "rdfs:Resource"))
            domain_term = f"ex:{domain}" if not domain.startswith("rdfs:") else domain
            range_term = (
                f"ex:{range_name}" if not range_name.startswith(("xsd:", "rdfs:")) else range_name
            )
            lines.append(
                f"ex:{property_name} rdfs:domain {domain_term} ; rdfs:range {range_term} ."
            )
        lines.append("")
        lines.append("ex:DelayState a rdfs:Class .")
        lines.extend(f"ex:{state} a ex:DelayState ." for state in ontology_candidate.states)
        return "\n".join(lines) + "\n"

    @staticmethod
    def render_shapes(ontology_candidate: OntologyCandidate) -> str:
        classes = set(ontology_candidate.classes)
        lines = [
            "@prefix ex: <urn:aifde:supplier-delay:> .",
            "@prefix sh: <http://www.w3.org/ns/shacl#> .",
            "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
            "",
        ]
        if "PurchaseOrder" in classes:
            lines.extend(
            [
                "ex:PurchaseOrderShape a sh:NodeShape ;",
                "    sh:targetClass ex:PurchaseOrder ;",
                '    sh:property [ sh:path ex:purchaseOrderId ; sh:minCount 1 ; sh:datatype xsd:string ; sh:message "PurchaseOrder requires purchaseOrderId." ] ;',
                '    sh:property [ sh:path ex:promisedDeliveryDate ; sh:minCount 1 ; sh:datatype xsd:date ; sh:message "PurchaseOrder requires promisedDeliveryDate." ] ;',
                '    sh:property [ sh:path ex:hasSupplier ; sh:minCount 1 ; sh:class ex:Supplier ; sh:message "PurchaseOrder requires a Supplier." ] ;',
                '    sh:property [ sh:path ex:hasLine ; sh:minCount 1 ; sh:class ex:PurchaseOrderLine ; sh:message "PurchaseOrder requires at least one line." ] ;',
                '    sh:property [ sh:path ex:delayState ; sh:minCount 1 ; sh:in ( ex:Unknown ex:OnTime ex:AtRisk ex:Delayed ) ; sh:message "PurchaseOrder delayState is not a governed state." ] .',
            ]
            )
        if "Supplier" in classes:
            lines.extend(
            [
                "ex:SupplierShape a sh:NodeShape ;",
                "    sh:targetClass ex:Supplier ;",
                '    sh:property [ sh:path ex:supplierId ; sh:minCount 1 ; sh:datatype xsd:string ; sh:message "Supplier requires supplierId." ] .',
            ]
            )
        if "PurchaseOrderLine" in classes:
            lines.extend(
            [
                "ex:PurchaseOrderLineShape a sh:NodeShape ;",
                "    sh:targetClass ex:PurchaseOrderLine ;",
                '    sh:property [ sh:path ex:lineId ; sh:minCount 1 ; sh:datatype xsd:string ; sh:message "PurchaseOrderLine requires lineId." ] ;',
                '    sh:property [ sh:path ex:sku ; sh:minCount 1 ; sh:datatype xsd:string ; sh:message "PurchaseOrderLine requires sku." ] ;',
                '    sh:property [ sh:path ex:quantity ; sh:minCount 1 ; sh:datatype xsd:decimal ; sh:message "PurchaseOrderLine requires quantity." ] ;',
                '    sh:property [ sh:path ex:forPurchaseOrder ; sh:minCount 1 ; sh:class ex:PurchaseOrder ; sh:message "PurchaseOrderLine must link to a PurchaseOrder." ] .',
            ]
            )
        if "PromisedDelivery" in classes:
            lines.extend(
            [
                "ex:PromisedDeliveryShape a sh:NodeShape ;",
                "    sh:targetClass ex:PromisedDelivery ;",
                '    sh:property [ sh:path ex:promisedDate ; sh:minCount 1 ; sh:datatype xsd:date ; sh:message "PromisedDelivery requires promisedDate." ] ;',
                '    sh:property [ sh:path ex:forPurchaseOrder ; sh:minCount 1 ; sh:class ex:PurchaseOrder ; sh:message "PromisedDelivery must link to a PurchaseOrder." ] .',
            ]
            )
        if "PromisedDateRevision" in classes:
            lines.extend(
            [
                "ex:PromisedDateRevisionShape a sh:NodeShape ;",
                "    sh:targetClass ex:PromisedDateRevision ;",
                '    sh:property [ sh:path ex:revisionDate ; sh:minCount 1 ; sh:datatype xsd:date ; sh:message "PromisedDateRevision requires revisionDate." ] ;',
                '    sh:property [ sh:path ex:forPurchaseOrder ; sh:minCount 1 ; sh:class ex:PurchaseOrder ; sh:message "PromisedDateRevision must link to a PurchaseOrder." ] .',
            ]
            )
        if "DeliveryEvent" in classes:
            lines.extend(
            [
                "ex:DeliveryEventShape a sh:NodeShape ;",
                "    sh:targetClass ex:DeliveryEvent ;",
                '    sh:property [ sh:path ex:eventTime ; sh:minCount 1 ; sh:datatype xsd:date ; sh:message "DeliveryEvent requires eventTime." ] ;',
                '    sh:property [ sh:path ex:actualDeliveryDate ; sh:minCount 1 ; sh:datatype xsd:date ; sh:message "DeliveryEvent requires actualDeliveryDate." ] ;',
                '    sh:property [ sh:path ex:forPurchaseOrder ; sh:minCount 1 ; sh:class ex:PurchaseOrder ; sh:message "DeliveryEvent must link to a PurchaseOrder." ] .',
            ]
            )
        if "DeliveryException" in classes:
            lines.extend(
            [
                "ex:DeliveryExceptionShape a sh:NodeShape ;",
                "    sh:targetClass ex:DeliveryException ;",
                '    sh:property [ sh:path ex:affects ; sh:minCount 1 ; sh:class ex:PurchaseOrder ; sh:message "DeliveryException must affect a PurchaseOrder." ] ;',
                '    sh:property [ sh:path ex:exceptionState ; sh:minCount 1 ; sh:in ( ex:Unknown ex:OnTime ex:AtRisk ex:Delayed ) ; sh:message "DeliveryException state is not governed." ] .',
            ]
            )
        return "\n".join(lines) + "\n"

    def validate(self, result: CompileResult) -> CompileValidation:
        if not isinstance(result, CompileResult):
            raise TypeError("result must be a CompileResult")
        violations: list[str] = []
        if not _ArtifactManifestAuthority.verify(
            result.artifact_manifest_id, result.artifact_hashes
        ):
            violations.append("artifact manifest is missing or does not match compiler-issued hashes")
        if not result.proposal_evidence_refs:
            violations.append("compile result requires proposal evidence refs")
        known_evidence = set(result.proposal_evidence_refs)
        known_mappings = {item.mapping_id for item in result.mapping_specs}
        if len(known_mappings) != len(result.mapping_specs):
            violations.append("mapping ids must be unique")
        for mapping in result.mapping_specs:
            try:
                self._validate_mapping_spec(mapping, _EXPECTED_SOURCE_PATHS)
            except ValueError as exc:
                violations.append(str(exc))
        field_names = {
            "supplier_id",
            "promised_delivery_date",
            "actual_delivery_date",
            "delay_state",
            "delay_days",
        }
        seen: set[str] = set()
        for row in result.canonical_rows:
            po_id = str(row.get("purchase_order_id", ""))
            if not po_id:
                violations.append("canonical row requires purchase_order_id")
            if po_id in seen:
                violations.append(f"duplicate purchase_order_id {po_id!r}")
            seen.add(po_id)
            if row.get("target_grain") != TARGET_GRAIN:
                violations.append("canonical row target grain must be purchase_order")
            if not row.get("supplier_id"):
                violations.append(f"canonical row {po_id!r} requires supplier_id")
            if not row.get("promised_delivery_date"):
                violations.append(f"canonical row {po_id!r} requires promised_delivery_date")
            if not row.get("evidence_refs"):
                violations.append(f"canonical row {po_id!r} requires evidence_refs")
            elif not set(row["evidence_refs"]).issubset(known_evidence):
                violations.append(f"canonical row {po_id!r} references unknown evidence")
            if row.get("mapping_ids") and not set(row["mapping_ids"]).issubset(known_mappings):
                violations.append(f"canonical row {po_id!r} references unknown mappings")
            field_provenance = row.get("field_provenance")
            if not isinstance(field_provenance, Mapping):
                violations.append(f"canonical row {po_id!r} requires field provenance")
                field_provenance = {}
            for field_name, provenance in field_provenance.items():
                if field_name not in field_names:
                    violations.append(
                        f"canonical row {po_id!r} contains unknown field provenance {field_name!r}"
                    )
                    continue
                if not isinstance(provenance, FieldValueProvenance):
                    violations.append(
                        f"field provenance for {po_id!r}/{field_name!r} has invalid contract"
                    )
                    continue
                if provenance.field_name != field_name:
                    violations.append(
                        f"field provenance field name mismatch for {po_id!r}/{field_name!r}"
                    )
                if field_name not in row:
                    violations.append(
                        f"field provenance for {po_id!r}/{field_name!r} has no canonical value"
                    )
                elif _jsonable(provenance.value) != _jsonable(row[field_name]):
                    violations.append(
                        f"field provenance value mismatch for {po_id!r}/{field_name!r}"
                    )
                if not set(provenance.evidence_refs).issubset(known_evidence):
                    violations.append(
                        f"field provenance for {po_id!r}/{field_name!r} references unknown evidence"
                    )
                if not set(provenance.mapping_ids).issubset(known_mappings):
                    violations.append(
                        f"field provenance for {po_id!r}/{field_name!r} references unknown mappings"
                    )
                location_refs = {item.evidence_id for item in provenance.source_locations}
                if not set(provenance.evidence_refs).issubset(location_refs):
                    violations.append(
                        f"field provenance for {po_id!r}/{field_name!r} is not evidence closed"
                    )
            for required_field in ("supplier_id", "promised_delivery_date"):
                if required_field not in field_provenance:
                    violations.append(
                        f"canonical row {po_id!r} requires field provenance for {required_field}"
                    )
            if "actual_delivery_date" in row and "actual_delivery_date" not in field_provenance:
                violations.append(
                    f"canonical row {po_id!r} actual_delivery_date lacks field provenance"
                )
            if "actual_delivery_date" in field_provenance:
                if "promised_delivery_date" not in field_provenance:
                    violations.append(
                        f"canonical row {po_id!r} actual delivery requires promised date provenance"
                    )
                else:
                    promised = _date_as_datetime(
                        str(field_provenance["promised_delivery_date"].value),
                        "promised_delivery_date",
                    )
                    actual = _date_as_datetime(
                        str(field_provenance["actual_delivery_date"].value),
                        "actual_delivery_date",
                    )
                    expected_delay = max(0, (actual.date() - promised.date()).days)
                    expected_state = "Delayed" if expected_delay > 0 else "OnTime"
                    if row.get("delay_days") != expected_delay:
                        violations.append(f"canonical row {po_id!r} delay_days is not derived from dates")
                    if row.get("delay_state") != expected_state:
                        violations.append(f"canonical row {po_id!r} delay_state is not derived from dates")
            elif row.get("delay_state") != "Unknown":
                violations.append(f"canonical row {po_id!r} without actual date must be Unknown")
            if row.get("delay_state") not in _ALLOWED_DELAY_STATES:
                violations.append(
                    f"canonical row {po_id!r} delay_state {row.get('delay_state')!r} is not governed"
                )
            if "delay_state" not in field_provenance:
                violations.append(f"canonical row {po_id!r} requires derived delay_state provenance")
            elif _jsonable(field_provenance["delay_state"].value) != _jsonable(row.get("delay_state")):
                violations.append(f"canonical row {po_id!r} delay_state provenance is not closed")
            if row.get("delay_days") is not None:
                if "delay_days" not in field_provenance:
                    violations.append(f"canonical row {po_id!r} requires derived delay_days provenance")
                elif _jsonable(field_provenance["delay_days"].value) != _jsonable(row.get("delay_days")):
                    violations.append(f"canonical row {po_id!r} delay_days provenance is not closed")
            try:
                event_time = str(row.get("event_time", ""))
                if not event_time or len(event_time) < 10:
                    raise ValueError
                datetime.fromisoformat(event_time)
                promised = str(row.get("promised_delivery_date", ""))
                if event_time[:10] != promised[:10]:
                    violations.append(f"canonical row {po_id!r} event_time disagrees with promised date")
            except ValueError:
                violations.append(f"canonical row {po_id!r} event_time must be an ISO date or datetime")
            try:
                observed = _parse_datetime(row.get("observed_at"), "observed_at")
                available = _parse_datetime(row.get("available_at"), "available_at")
                if observed > available:
                    violations.append(f"canonical row {po_id!r} available_at precedes observed_at")
                if field_provenance:
                    expected_observed = max(item.observed_at for item in field_provenance.values())
                    expected_available = max(item.available_at for item in field_provenance.values())
                    if observed != expected_observed:
                        violations.append(f"canonical row {po_id!r} observed_at is not field-level aggregate")
                    if available != expected_available:
                        violations.append(f"canonical row {po_id!r} available_at is not field-level aggregate")
            except ValueError as exc:
                violations.append(str(exc))
        row_ids = {str(row.get("purchase_order_id")) for row in result.canonical_rows}
        provenance_by_id = {str(item.get("target_id")): item for item in result.provenance_rows}
        if len(provenance_by_id) != len(result.provenance_rows):
            violations.append("provenance target ids must be unique")
        mapping_row_counts = {mapping_id: 0 for mapping_id in known_mappings}
        for target_id in sorted(row_ids):
            provenance = provenance_by_id.get(target_id)
            if provenance is None or not provenance.get("evidence_refs"):
                violations.append(f"missing provenance for target {target_id!r}")
                continue
            row = next(item for item in result.canonical_rows if str(item.get("purchase_order_id")) == target_id)
            if set(provenance.get("evidence_refs", ())) != set(row.get("evidence_refs", ())):
                violations.append(f"provenance evidence does not match row {target_id!r}")
            if set(provenance.get("mapping_ids", ())) != set(row.get("mapping_ids", ())):
                violations.append(f"provenance mappings do not match row {target_id!r}")
            if not set(provenance.get("evidence_refs", ())).issubset(known_evidence):
                violations.append(f"provenance for {target_id!r} references unknown evidence")
            if not set(provenance.get("mapping_ids", ())).issubset(known_mappings):
                violations.append(f"provenance for {target_id!r} references unknown mappings")
            for mapping_id in provenance.get("mapping_ids", ()):
                if mapping_id in mapping_row_counts:
                    mapping_row_counts[mapping_id] += 1
        for row in result.canonical_rows:
            if not row.get("mapping_ids"):
                violations.append(
                    f"canonical row {row.get('purchase_order_id', '')!r} requires mapping_ids"
                )
            if row.get("actual_delivery_date"):
                try:
                    datetime.fromisoformat(str(row["actual_delivery_date"]))
                except ValueError:
                    violations.append(
                        f"canonical row {row.get('purchase_order_id', '')!r} actual_delivery_date must be an ISO date"
                    )
        seen_lines: set[str] = set()
        for line in result.canonical_line_rows or []:
            line_id = str(line.get("line_id", ""))
            po_id = str(line.get("purchase_order_id", ""))
            if not line_id:
                violations.append("canonical line row requires line_id")
            if line_id in seen_lines:
                violations.append(f"duplicate line_id {line_id!r}")
            seen_lines.add(line_id)
            if po_id not in row_ids:
                violations.append(f"canonical line {line_id!r} references unknown purchase order")
            if line.get("target_grain") != "purchase_order_line":
                violations.append(f"canonical line {line_id!r} target grain must be purchase_order_line")
            for required in ("sku", "quantity"):
                if line.get(required) in (None, ""):
                    violations.append(f"canonical line {line_id!r} requires {required}")
            line_fields = line.get("field_provenance")
            if not isinstance(line_fields, Mapping):
                violations.append(f"canonical line {line_id!r} requires field provenance")
                line_fields = {}
            for field_name, provenance in line_fields.items():
                if not isinstance(provenance, FieldValueProvenance):
                    violations.append(f"canonical line {line_id!r}/{field_name!r} provenance is invalid")
                    continue
                if field_name not in line or _jsonable(provenance.value) != _jsonable(line[field_name]):
                    violations.append(f"canonical line {line_id!r}/{field_name!r} value is not evidence closed")
                if not set(provenance.evidence_refs).issubset(known_evidence):
                    violations.append(f"canonical line {line_id!r}/{field_name!r} references unknown evidence")
                if not set(provenance.mapping_ids).issubset(known_mappings):
                    violations.append(f"canonical line {line_id!r}/{field_name!r} references unknown mappings")
        for mapping_id, count in mapping_row_counts.items():
            if count == 0:
                violations.append(f"mapping {mapping_id!r} produced no canonical row")
        expected_hashes = {
            "ontology": _hash_text(result.ontology_turtle),
            "shapes": _hash_text(result.shapes_turtle),
            "mappings": _hash_json([self._mapping_dict(item) for item in result.mapping_specs]),
            "canonical_product": _hash_json(
                {
                    "orders": result.canonical_rows,
                    "lines": result.canonical_line_rows or [],
                    "revisions": result.canonical_revision_rows or [],
                }
            ),
            "provenance": _hash_json(result.provenance_rows),
            "canonical_rdf": _hash_text(result.data_turtle),
        }
        for artifact_id, expected in expected_hashes.items():
            if result.artifact_hashes.get(artifact_id) != expected:
                violations.append(f"artifact hash mismatch for {artifact_id}")
        violations = list(dict.fromkeys(violations))
        if violations:
            raise ValueError("compiler validation failed: " + "; ".join(violations))
        if not result.canonical_rows:
            raise ValueError("compiler validation failed: canonical product is empty")
        semantic_report = _rdfs_shape_validation(result.data_turtle, result.shapes_turtle)
        if not semantic_report.passed:
            raise ValueError("SHACL validation failed: " + "; ".join(semantic_report.violations))
        return CompileValidation(
            passed=True,
            warnings=tuple(semantic_report.warnings),
            evidence_refs=tuple(
                dict.fromkeys(
                    (*result.ontology_candidate.evidence_refs, *semantic_report.evidence_refs)
                )
            ),
        )

    def _load_fragments(
        self, proposal: CandidateProposal, source_registry: SourceRegistry
    ) -> dict[str, EvidenceFragment]:
        requested = set(proposal.evidence_refs)
        fragments = {
            item.evidence_id: item
            for item in source_registry.list_fragments()
            if item.evidence_id in requested
        }
        if requested != set(fragments):
            missing = sorted(requested - set(fragments))
            raise ValueError("proposal references unavailable evidence: " + ", ".join(missing))
        return fragments

    @staticmethod
    def _validate_proposal_evidence_closure(
        proposal: CandidateProposal, fragments: Mapping[str, EvidenceFragment]
    ) -> None:
        proposal_refs = set(proposal.evidence_refs)
        if set(fragments) != proposal_refs:
            raise ValueError("compiler evidence snapshot is not closed over proposal evidence")
        children = (
            *proposal.terms,
            *proposal.entities,
            *proposal.assertions,
            *proposal.mappings,
        )
        for child in children:
            refs = set(getattr(child, "source_evidence_refs", ())) | set(
                getattr(child, "evidence_refs", ())
            )
            if not refs.issubset(proposal_refs):
                raise ValueError("proposal child references evidence outside proposal closure")
        if any(
            item.status in {"confirmed", "probable_match"}
            and not item.candidate_id
            for item in proposal.entity_matches
        ):
            raise ValueError("resolved entity match requires candidate identity")

    def _mapping_spec(
        self,
        candidate: MappingCandidate,
        fragments: Mapping[str, EvidenceFragment],
        proposal_evidence_refs: Sequence[str],
        version: str,
    ) -> MappingSpec:
        refs = tuple(candidate.source_evidence_refs)
        if not set(refs).issubset(set(proposal_evidence_refs)):
            raise ValueError(
                f"mapping {candidate.mapping_id} references evidence outside proposal evidence"
            )
        if not set(refs).issubset(fragments):
            raise ValueError(f"mapping {candidate.mapping_id} references unavailable evidence")
        first = fragments[refs[0]]
        return MappingSpec(
            mapping_id=candidate.mapping_id,
            source_field_path=candidate.source_field_path,
            target_product=candidate.target_product,
            target_grain=candidate.target_grain,
            target_field=candidate.target_field,
            transform_expression=candidate.transform_expression,
            identity_rule=candidate.identity_rule,
            time_semantics=candidate.time_semantics,
            null_policy=candidate.null_policy,
            lineage_refs=refs,
            security_policy=f"source-policy:{first.source_asset_id}",
            version=version,
        )

    @staticmethod
    def _extract_mapping_value(order: Mapping[str, Any], mapping: MappingSpec) -> str:
        path_to_field = {
            "$.purchase_orders[*].supplier": "supplier",
            "$.purchase_orders[*].promised_date": "promised_date",
        }
        source_field = path_to_field.get(mapping.source_field_path)
        if source_field is None:
            raise ValueError(f"source field path {mapping.source_field_path!r} is not executable")
        expected_target = {
            "supplier": "supplier_id",
            "promised_date": "promised_delivery_date",
        }[source_field]
        if mapping.target_field != expected_target:
            raise ValueError(
                f"mapping {mapping.mapping_id!r} maps {source_field!r} to invalid target field "
                f"{mapping.target_field!r}"
            )
        if mapping.transform_expression not in {"identity", "trim"}:
            raise ValueError(f"unsupported transform expression {mapping.transform_expression!r}")
        value = order.get(source_field)
        if value is None:
            if mapping.null_policy == "reject":
                raise ValueError(f"mapping {mapping.mapping_id!r} rejects null {source_field!r}")
            return ""
        normalized = str(value).strip() if mapping.transform_expression == "trim" else str(value)
        return _nonblank(normalized, source_field)

    def _materialize_rows(
        self,
        proposal: CandidateProposal,
        fragments: Mapping[str, EvidenceFragment],
        mapping_specs: Sequence[MappingSpec],
        version: str,
    ) -> tuple[
        list[dict[str, Any]],
        list[dict[str, Any]],
        list[dict[str, Any]],
        list[dict[str, Any]],
    ]:
        del version
        rows_by_id: dict[str, dict[str, Any]] = {}
        line_rows_by_id: dict[str, dict[str, Any]] = {}
        revision_rows_by_id: dict[str, dict[str, Any]] = {}
        mapping_by_ref: dict[str, list[MappingSpec]] = {}
        for mapping in mapping_specs:
            for ref in mapping.lineage_refs:
                mapping_by_ref.setdefault(ref, []).append(mapping)
        entity_map = {
            item.candidate_id: item.canonical_entity_id
            for item in proposal.entity_matches
            if item.canonical_entity_id and item.status in {"confirmed", "probable_match"}
        }
        entity_matches = {
            item.candidate_id: item for item in proposal.entity_matches
        }
        for ref, fragment in sorted(fragments.items()):
            if not fragment.locator.startswith("$.purchase_orders["):
                continue
            try:
                payload = json.loads(fragment.content)
            except json.JSONDecodeError as exc:
                raise ValueError("purchase-order evidence is not canonical JSON") from exc
            if not isinstance(payload, dict):
                raise ValueError("purchase-order evidence must be an object")
            po_id = _nonblank(str(payload.get("po_id", "")), "po_id")
            supplier_name = _nonblank(str(payload.get("supplier", "")), "supplier")
            promised = _nonblank(str(payload.get("promised_date", "")), "promised_date")
            candidate_supplier_id = "supplier:" + "".join(
                char.lower() if char.isalnum() else " " for char in supplier_name
            ).replace(" ", "")
            supplier_id = entity_map.get(candidate_supplier_id, candidate_supplier_id)
            supplier_match = entity_matches.get(candidate_supplier_id)
            supplier_resolution = self._resolution_payload(
                candidate_supplier_id, supplier_match, supplier_id
            )
            mapping_ids = [item.mapping_id for item in mapping_by_ref.get(ref, [])]
            mapped_values = {
                item.target_field: self._extract_mapping_value(payload, item)
                for item in mapping_by_ref.get(ref, [])
            }
            supplier_value = mapped_values.get("supplier_id", supplier_name)
            promised_value = mapped_values.get("promised_delivery_date", promised)
            row = rows_by_id.setdefault(
                po_id,
                {
                    "purchase_order_id": po_id,
                    "supplier_id": entity_map.get(
                        "supplier:" + "".join(
                            char.lower() if char.isalnum() else " "
                            for char in supplier_value
                        ).replace(" ", ""),
                        supplier_id,
                    ),
                    "promised_delivery_date": promised_value,
                    "event_time": promised_value,
                    "observed_at": _iso(fragment.observed_at),
                    "available_at": _iso(fragment.available_at),
                    "target_grain": TARGET_GRAIN,
                    "evidence_refs": [],
                    "mapping_ids": [],
                    "field_provenance": {},
                    "supplier_resolution": supplier_resolution,
                },
            )
            row["evidence_refs"] = list(dict.fromkeys([*row["evidence_refs"], ref]))
            row["mapping_ids"] = list(dict.fromkeys([*row["mapping_ids"], *mapping_ids]))
            source_locations = (self._field_location(fragment),)
            if "supplier_id" in mapped_values:
                supplier_candidate = "supplier:" + "".join(
                    char.lower() if char.isalnum() else " "
                    for char in mapped_values["supplier_id"]
                ).replace(" ", "")
                row["supplier_id"] = entity_map.get(supplier_candidate, supplier_id)
                row["field_provenance"]["supplier_id"] = FieldValueProvenance(
                    field_name="supplier_id",
                    value=row["supplier_id"],
                    evidence_refs=(ref,),
                    mapping_ids=tuple(
                        item.mapping_id
                        for item in mapping_by_ref.get(ref, [])
                        if item.target_field == "supplier_id"
                    ),
                    source_locations=source_locations,
                    observed_at=fragment.observed_at,
                    available_at=fragment.available_at,
                )
            if "promised_delivery_date" in mapped_values:
                promised_value = mapped_values["promised_delivery_date"]
                row["promised_delivery_date"] = promised_value
                row["event_time"] = promised_value
                row["field_provenance"]["promised_delivery_date"] = FieldValueProvenance(
                    field_name="promised_delivery_date",
                    value=promised_value,
                    evidence_refs=(ref,),
                    mapping_ids=tuple(
                        item.mapping_id
                        for item in mapping_by_ref.get(ref, [])
                        if item.target_field == "promised_delivery_date"
                    ),
                    source_locations=source_locations,
                    event_time=_date_as_datetime(promised_value, "promised_delivery_date"),
                    observed_at=fragment.observed_at,
                    available_at=fragment.available_at,
                    valid_from=_date_as_datetime(promised_value, "promised_delivery_date"),
                )
            items = payload.get("items", [])
            if items is not None and not isinstance(items, list):
                raise ValueError(f"canonical row {po_id!r} items must be a list")
            for index, item in enumerate(items):
                if not isinstance(item, Mapping):
                    raise ValueError(f"canonical row {po_id!r} items must contain objects")
                line_id = f"{po_id}:line:{index + 1}"
                sku = _nonblank(str(item.get("sku", "")), "sku")
                quantity = item.get("quantity")
                if not isinstance(quantity, (int, float)) or isinstance(quantity, bool):
                    raise ValueError(f"canonical line {line_id!r} quantity must be numeric")
                line_location = (self._field_location(fragment),)
                line_rows_by_id.setdefault(
                    line_id,
                    {
                        "line_id": line_id,
                        "purchase_order_id": po_id,
                        "sku": sku,
                        "quantity": quantity,
                        "observed_at": _iso(fragment.observed_at),
                        "available_at": _iso(fragment.available_at),
                        "target_grain": "purchase_order_line",
                        "evidence_refs": [ref],
                        "mapping_ids": list(mapping_ids),
                        "field_provenance": {
                            "line_id": FieldValueProvenance(
                                field_name="line_id",
                                value=line_id,
                                evidence_refs=(ref,),
                                mapping_ids=tuple(mapping_ids),
                                source_locations=line_location,
                                observed_at=fragment.observed_at,
                                available_at=fragment.available_at,
                            ),
                            "sku": FieldValueProvenance(
                                field_name="sku",
                                value=sku,
                                evidence_refs=(ref,),
                                mapping_ids=tuple(mapping_ids),
                                source_locations=line_location,
                                observed_at=fragment.observed_at,
                                available_at=fragment.available_at,
                            ),
                            "quantity": FieldValueProvenance(
                                field_name="quantity",
                                value=quantity,
                                evidence_refs=(ref,),
                                mapping_ids=tuple(mapping_ids),
                                source_locations=line_location,
                                observed_at=fragment.observed_at,
                                available_at=fragment.available_at,
                            ),
                        },
                    },
                )
            if _parse_datetime(fragment.observed_at, "observed_at") > _parse_datetime(fragment.available_at, "available_at"):
                raise ValueError(f"canonical row {po_id!r} available_at precedes observed_at")
        rows = [rows_by_id[key] for key in sorted(rows_by_id)]
        # Only an explicitly evidenced actual-delivery fact may add an actual
        # date.  The provider's assumption remains an open question.
        rows_by_id = {row["purchase_order_id"]: row for row in rows}
        for assertion in proposal.assertions:
            if (
                assertion.assertion_type != "fact"
                or assertion.predicate != "actualDeliveryDate"
                or not assertion.subject.startswith("purchase-order:")
            ):
                continue
            target_id = assertion.subject.split(":", 1)[1]
            row = rows_by_id.get(target_id)
            if row is None:
                continue
            actual_value = _nonblank(str(assertion.value), "actualDeliveryDate")
            assertion_fragments = [fragments[ref] for ref in assertion.evidence_refs]
            if not assertion_fragments:
                raise ValueError("actual delivery fact requires evidence")
            row["actual_delivery_date"] = actual_value
            row["field_provenance"]["actual_delivery_date"] = FieldValueProvenance(
                field_name="actual_delivery_date",
                value=actual_value,
                evidence_refs=tuple(assertion.evidence_refs),
                mapping_ids=(),
                source_locations=tuple(
                    self._field_location(fragment) for fragment in assertion_fragments
                ),
                event_time=next(
                    (
                        fragment.event_time
                        for fragment in assertion_fragments
                        if fragment.event_time is not None
                    ),
                    _date_as_datetime(actual_value, "actual_delivery_date"),
                ),
                observed_at=max(fragment.observed_at for fragment in assertion_fragments),
                available_at=max(fragment.available_at for fragment in assertion_fragments),
                valid_from=_date_as_datetime(actual_value, "actual_delivery_date"),
            )
            row["evidence_refs"] = list(
                dict.fromkeys([*row["evidence_refs"], *assertion.evidence_refs])
            )
        rows = [rows_by_id[key] for key in sorted(rows_by_id)]
        # Inference assertions remain open questions until a domain owner
        # confirms their target.  They are deliberately not fanned out to
        # every purchase order for the supplier; doing so would turn an
        # ambiguous semantic suggestion into a false production fact.
        for row in rows:
            field_provenance = row["field_provenance"]
            row["observed_at"] = _iso(
                max(item.observed_at for item in field_provenance.values())
            )
            row["available_at"] = _iso(
                max(item.available_at for item in field_provenance.values())
            )
            row["delay_state"] = "Unknown"
            if "actual_delivery_date" in field_provenance:
                promised = _date_as_datetime(
                    str(field_provenance["promised_delivery_date"].value),
                    "promised_delivery_date",
                )
                actual = _date_as_datetime(
                    str(field_provenance["actual_delivery_date"].value),
                    "actual_delivery_date",
                )
                row["delay_days"] = max(0, (actual.date() - promised.date()).days)
                row["delay_state"] = "Delayed" if row["delay_days"] > 0 else "OnTime"
            state_sources = [field_provenance["promised_delivery_date"]]
            if "actual_delivery_date" in field_provenance:
                state_sources.append(field_provenance["actual_delivery_date"])
            state_evidence = tuple(
                dict.fromkeys(ref for item in state_sources for ref in item.evidence_refs)
            )
            state_mappings = tuple(
                dict.fromkeys(mapping for item in state_sources for mapping in item.mapping_ids)
            )
            state_locations = tuple(
                dict.fromkeys(
                    location
                    for item in state_sources
                    for location in item.source_locations
                )
            )
            state_available_at = max(item.available_at for item in state_sources)
            state_observed_at = max(item.observed_at for item in state_sources)
            row["field_provenance"]["delay_state"] = FieldValueProvenance(
                field_name="delay_state",
                value=row["delay_state"],
                evidence_refs=state_evidence,
                mapping_ids=state_mappings,
                source_locations=state_locations,
                observed_at=state_observed_at,
                available_at=state_available_at,
            )
            if "actual_delivery_date" in field_provenance:
                row["field_provenance"]["delay_days"] = FieldValueProvenance(
                    field_name="delay_days",
                    value=row["delay_days"],
                    evidence_refs=state_evidence,
                    mapping_ids=state_mappings,
                    source_locations=state_locations,
                    observed_at=state_observed_at,
                    available_at=state_available_at,
                )
        line_rows = [line_rows_by_id[key] for key in sorted(line_rows_by_id)]
        for line in line_rows:
            line_fields = line["field_provenance"]
            line["observed_at"] = _iso(max(item.observed_at for item in line_fields.values()))
            line["available_at"] = _iso(max(item.available_at for item in line_fields.values()))
        provenance_rows = [
            {
                "target_id": row["purchase_order_id"],
                "target_kind": "PurchaseOrder",
                "evidence_refs": list(row["evidence_refs"]),
                "source_locations": [
                    {
                        "evidence_id": item.evidence_id,
                        "source_asset_id": item.source_asset_id,
                        "source_version": item.source_version,
                        "snapshot_id": item.snapshot_id,
                        "locator": item.locator,
                        "observed_at": _iso(item.observed_at),
                        "available_at": _iso(item.available_at),
                        "event_time": _iso(item.event_time) if item.event_time else None,
                    }
                    for ref in row["evidence_refs"]
                    for item in [fragments[ref]]
                ],
                "mapping_ids": list(row["mapping_ids"]),
            "field_provenance": {
                    key: _jsonable(value) for key, value in row["field_provenance"].items()
                },
                "supplier_resolution": _jsonable(row["supplier_resolution"]),
            }
            for row in rows
        ]
        return rows, provenance_rows, line_rows, [
            revision_rows_by_id[key] for key in sorted(revision_rows_by_id)
        ]

    @staticmethod
    def _field_location(fragment: EvidenceFragment) -> FieldEvidenceLocation:
        return FieldEvidenceLocation(
            evidence_id=fragment.evidence_id,
            source_asset_id=fragment.source_asset_id,
            source_version=fragment.source_version,
            snapshot_id=fragment.snapshot_id,
            locator=fragment.locator,
            observed_at=fragment.observed_at,
            available_at=fragment.available_at,
            event_time=fragment.event_time,
        )

    @staticmethod
    def _resolution_payload(
        candidate_id: str,
        match: Any,
        fallback_canonical_id: str,
    ) -> dict[str, Any]:
        if match is None:
            return {
                "candidate_id": candidate_id,
                "canonical_entity_id": fallback_canonical_id,
                "status": "unresolved",
                "score": 0.0,
                "threshold": 1.0,
                "matching_fields": [],
                "algorithm_version": "unknown",
                "conflict_refs": [],
            }
        return {
            "candidate_id": match.candidate_id,
            "canonical_entity_id": match.canonical_entity_id,
            "status": match.status,
            "score": match.score,
            "threshold": match.threshold,
            "matching_fields": list(match.matching_fields),
            "algorithm_version": match.algorithm_version,
            "conflict_refs": list(match.conflict_refs),
        }

    @staticmethod
    def _ontology_candidate(
        proposal: CandidateProposal,
        mapping_specs: Sequence[MappingSpec],
        version: str,
    ) -> OntologyCandidate:
        return OntologyCandidate(
            candidate_id=f"ontology-candidate:{version}",
            version=version,
            classes=(
                "Supplier",
                "PurchaseOrder",
                "PurchaseOrderLine",
                "PromisedDelivery",
                "PromisedDateRevision",
                "DeliveryEvent",
                "DeliveryException",
            ),
            properties=(
                "supplierId",
                "purchaseOrderId",
                "lineId",
                "sku",
                "quantity",
                "promisedDeliveryDate",
                "promisedDate",
                "actualDeliveryDate",
                "delayState",
                "exceptionState",
                "delayDays",
                "eventTime",
                "forPurchaseOrder",
                "hasSupplier",
                "hasLine",
                "hasPromisedDelivery",
                "hasDateRevision",
                "hasDeliveryEvent",
                "hasException",
                "affects",
            ),
            relationships=(
                ("PurchaseOrder", "hasSupplier", "Supplier"),
                ("PurchaseOrder", "hasLine", "PurchaseOrderLine"),
                ("PurchaseOrder", "hasPromisedDelivery", "PromisedDelivery"),
                ("PurchaseOrder", "hasDateRevision", "PromisedDateRevision"),
                ("PurchaseOrder", "hasDeliveryEvent", "DeliveryEvent"),
                ("PurchaseOrderLine", "forPurchaseOrder", "PurchaseOrder"),
                ("DeliveryEvent", "forPurchaseOrder", "PurchaseOrder"),
                ("DeliveryException", "affects", "PurchaseOrder"),
            ),
            states=("OnTime", "AtRisk", "Delayed", "Unknown"),
            events=("DeliveryEvent", "PromisedDateRevision"),
            identity_keys=(
                ("Supplier", ("supplierId",)),
                ("PurchaseOrder", ("purchaseOrderId",)),
            ),
            temporal_semantics=(
                ("promisedDeliveryDate", "valid_time"),
                ("eventTime", "event_time"),
                ("observed_at", "observed_time"),
                ("available_at", "available_time"),
            ),
            access_policies=(("Supplier", "policy:procurement"), ("PurchaseOrder", "policy:procurement")),
            mapping_spec_refs=tuple(item.mapping_id for item in mapping_specs),
            evidence_refs=tuple(proposal.evidence_refs),
            open_questions=tuple(
                item.assertion_id
                for item in proposal.assertions
                if item.assertion_type in {"assumption", "inference"}
            ),
            conflicts=tuple(
                conflict
                for item in proposal.entity_matches
                for conflict in item.conflict_refs
            ),
        )

    @staticmethod
    def _mapping_dict(mapping: MappingSpec) -> dict[str, Any]:
        return {
            "mapping_id": mapping.mapping_id,
            "source_field_path": mapping.source_field_path,
            "target_product": mapping.target_product,
            "target_grain": mapping.target_grain,
            "target_field": mapping.target_field,
            "transform_expression": mapping.transform_expression,
            "identity_rule": mapping.identity_rule,
            "time_semantics": mapping.time_semantics,
            "null_policy": mapping.null_policy,
            "lineage_refs": mapping.lineage_refs,
            "security_policy": mapping.security_policy,
            "version": mapping.version,
        }

    @staticmethod
    def _validate_mapping_spec(mapping: MappingSpec, source_field_paths: Iterable[str]) -> None:
        if mapping.target_product != "purchase_order":
            raise ValueError("mapping target product must be purchase_order")
        if mapping.target_grain != TARGET_GRAIN:
            raise ValueError("mapping target grain must be purchase_order")
        if not mapping.lineage_refs:
            raise ValueError(f"mapping {mapping.mapping_id} requires lineage refs")
        if mapping.source_field_path not in set(source_field_paths):
            raise ValueError(f"source field path {mapping.source_field_path!r} is not resolvable")
        if mapping.target_field not in {"supplier_id", "promised_delivery_date"}:
            raise ValueError(f"mapping target field {mapping.target_field!r} is not supported")
        expected_target = {
            "$.purchase_orders[*].supplier": "supplier_id",
            "$.purchase_orders[*].promised_date": "promised_delivery_date",
        }[mapping.source_field_path]
        if mapping.target_field != expected_target:
            raise ValueError(
                f"mapping {mapping.mapping_id!r} target field does not match source field path"
            )
        if mapping.transform_expression not in {"identity", "trim"}:
            raise ValueError(f"unsupported transform expression {mapping.transform_expression!r}")
        if mapping.time_semantics not in {"observed_at/available_at", "valid_time"}:
            raise ValueError(f"unsupported time semantics {mapping.time_semantics!r}")


__all__ = [
    "CompileResult",
    "CompileValidation",
    "MappingCompiler",
    "MappingSpec",
    "OntologyCandidate",
]
