"""Compile semantic candidates into executable, traceable ontology artifacts."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
from typing import Any
from uuid import uuid4

from aifde.tools.validation import ShaclValidator

from .contracts import EvidenceFragment, SourceSnapshot
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


def _nonblank(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must not be empty")
    return value.strip()


def _hash_text(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _hash_json(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return _hash_text(payload)


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
        canonical_rows, provenance_rows = self._materialize_rows(proposal, fragments, mapping_specs, version)
        ontology_candidate = self._ontology_candidate(proposal, mapping_specs, version)
        ontology_turtle = self.render_turtle(ontology_candidate)
        shapes_turtle = self.render_shapes(ontology_candidate)
        data_turtle = self.render_data(canonical_rows)
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
                "canonical_product": _hash_json(canonical_rows),
                "provenance": _hash_json(provenance_rows),
                "canonical_rdf": _hash_text(data_turtle),
            },
            ontology_turtle=ontology_turtle,
            shapes_turtle=shapes_turtle,
            data_turtle=data_turtle,
            proposal_evidence_refs=tuple(proposal.evidence_refs),
            source_field_paths=tuple(sorted({item.source_field_path for item in mapping_specs})),
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
    def render_data(canonical_rows: Sequence[Mapping[str, Any]]) -> str:
        """Render canonical product instances for non-vacuous SHACL validation."""

        lines = [
            "@prefix ex: <urn:aifde:supplier-delay:> .",
            "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
            "",
        ]
        suppliers: set[str] = set()
        for row in canonical_rows:
            po_id = _nonblank(str(row.get("purchase_order_id", "")), "purchase_order_id")
            supplier_id = _nonblank(str(row.get("supplier_id", "")), "supplier_id")
            supplier_slug = _safe_local_name(supplier_id)
            suppliers.add(supplier_slug + "\t" + supplier_id)
            actual_date = row.get("actual_delivery_date")
            event_link = (
                f' ; ex:hasDeliveryEvent ex:event-{_safe_local_name(po_id)}'
                if actual_date
                else ""
            )
            lines.append(
                f'ex:po-{_safe_local_name(po_id)} a ex:PurchaseOrder ; '
                f'ex:purchaseOrderId "{_escape_literal(po_id)}" ; '
                f'ex:promisedDeliveryDate "{_escape_literal(str(row.get("promised_delivery_date", "")))}" ; '
                f'ex:hasSupplier ex:supplier-{supplier_slug}{event_link} .'
            )
            if actual_date:
                lines.append(
                    f'ex:event-{_safe_local_name(po_id)} a ex:DeliveryEvent ; '
                    f'ex:actualDeliveryDate "{_escape_literal(str(actual_date))}" ; '
                    f'ex:eventTime "{_escape_literal(str(actual_date))}" ; '
                    f'ex:forPurchaseOrder ex:po-{_safe_local_name(po_id)} .'
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
            "",
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
        for subject, predicate, obj in ontology_candidate.relationships:
            lines.append(
                f"ex:{subject} ex:{predicate} ex:{obj} ."
                if predicate == "hasSupplier"
                else f"ex:{subject} ex:{predicate} ex:{obj} ."
            )
        lines.append("")
        lines.extend(
            f"ex:{prop} rdfs:domain ex:{domain} ; rdfs:range ex:{range_name} ."
            for prop, domain, range_name in (
                ("hasSupplier", "PurchaseOrder", "Supplier"),
                ("promisedDeliveryDate", "PurchaseOrder", "Date"),
                ("actualDeliveryDate", "DeliveryEvent", "Date"),
                ("delayState", "DeliveryException", "DelayState"),
            )
        )
        return "\n".join(lines) + "\n"

    @staticmethod
    def render_shapes(ontology_candidate: OntologyCandidate) -> str:
        classes = set(ontology_candidate.classes)
        lines = [
            "@prefix ex: <urn:aifde:supplier-delay:> .",
            "@prefix sh: <http://www.w3.org/ns/shacl#> .",
            "",
        ]
        if "PurchaseOrder" in classes:
            lines.extend(
            [
                "ex:PurchaseOrderShape a sh:NodeShape ;",
                "    sh:targetClass ex:PurchaseOrder ;",
                '    sh:property [ sh:path ex:purchaseOrderId ; sh:minCount 1 ; sh:message "PurchaseOrder requires purchaseOrderId." ] ;',
                '    sh:property [ sh:path ex:promisedDeliveryDate ; sh:minCount 1 ; sh:message "PurchaseOrder requires promisedDeliveryDate." ] .',
            ]
            )
        if "Supplier" in classes:
            lines.extend(
            [
                "ex:SupplierShape a sh:NodeShape ;",
                "    sh:targetClass ex:Supplier ;",
                '    sh:property [ sh:path ex:supplierId ; sh:minCount 1 ; sh:message "Supplier requires supplierId." ] .',
            ]
            )
        if "DeliveryEvent" in classes:
            lines.extend(
            [
                "ex:DeliveryEventShape a sh:NodeShape ;",
                "    sh:targetClass ex:DeliveryEvent ;",
                '    sh:property [ sh:path ex:eventTime ; sh:minCount 1 ; sh:message "DeliveryEvent requires eventTime." ] .',
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
        for mapping_id, count in mapping_row_counts.items():
            if count == 0:
                violations.append(f"mapping {mapping_id!r} produced no canonical row")
        expected_hashes = {
            "ontology": _hash_text(result.ontology_turtle),
            "shapes": _hash_text(result.shapes_turtle),
            "mappings": _hash_json([self._mapping_dict(item) for item in result.mapping_specs]),
            "canonical_product": _hash_json(result.canonical_rows),
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
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        del version
        rows_by_id: dict[str, dict[str, Any]] = {}
        mapping_by_ref: dict[str, list[MappingSpec]] = {}
        for mapping in mapping_specs:
            for ref in mapping.lineage_refs:
                mapping_by_ref.setdefault(ref, []).append(mapping)
        entity_map = {
            item.candidate_id: item.canonical_entity_id
            for item in proposal.entity_matches
            if item.canonical_entity_id and item.status in {"confirmed", "probable_match"}
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
                },
            )
            row["evidence_refs"] = list(dict.fromkeys([*row["evidence_refs"], ref]))
            row["mapping_ids"] = list(dict.fromkeys([*row["mapping_ids"], *mapping_ids]))
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
            row["actual_delivery_date"] = _nonblank(str(assertion.value), "actualDeliveryDate")
            row["evidence_refs"] = list(
                dict.fromkeys([*row["evidence_refs"], *assertion.evidence_refs])
            )
        rows = [rows_by_id[key] for key in sorted(rows_by_id)]
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
            }
            for row in rows
        ]
        return rows, provenance_rows

    @staticmethod
    def _ontology_candidate(
        proposal: CandidateProposal,
        mapping_specs: Sequence[MappingSpec],
        version: str,
    ) -> OntologyCandidate:
        return OntologyCandidate(
            candidate_id=f"ontology-candidate:{version}",
            version=version,
            classes=("Supplier", "PurchaseOrder", "DeliveryEvent", "DeliveryException"),
            properties=(
                "supplierId",
                "purchaseOrderId",
                "promisedDeliveryDate",
                "actualDeliveryDate",
                "delayState",
                "eventTime",
                "forPurchaseOrder",
            ),
            relationships=(
                ("PurchaseOrder", "hasSupplier", "Supplier"),
                ("PurchaseOrder", "hasDeliveryEvent", "DeliveryEvent"),
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
