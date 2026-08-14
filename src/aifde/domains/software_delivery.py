"""Software-delivery Domain Pack and generic JSON mapping adapter."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from aifde.builder.compiler import (
    CompileResult,
    CompileValidation,
    MappingSpec,
    OntologyCandidate,
    _ArtifactManifestAuthority,
    _hash_json,
    _hash_text,
    _jsonable,
)
from aifde.builder.contracts import (
    EvidenceFragment,
    FieldEvidenceLocation,
    FieldValueProvenance,
)
from aifde.builder.semantic import (
    BuilderContext,
    CandidateProposal,
    CandidateProvider,
    EntityCandidate,
    MappingCandidate,
    SemanticAssertion,
    SemanticCandidateBuilder,
    TermCandidate,
)
from aifde.builder.sources import SourceRegistry
from aifde.ingestion.connectors import CaptureRequest, LocalFileConnector
from aifde.ingestion.extractors import EvidenceExtractor
from aifde.platform.domain_pack import DomainPack
from aifde.platform.ontology_ir import (
    ClassIR,
    EventIR,
    MetricIR,
    OntologyIR,
    OntologyIRCompiler,
    PropertyIR,
    RelationshipIR,
    StateIR,
)

from .base import DomainCapture


_PACK_EVIDENCE = "domain-pack:software-delivery@1.0.0"


def _leaf(path: str) -> str:
    value = path.rsplit(".", 1)[-1].replace("[*]", "")
    if not value:
        raise ValueError(f"mapping source path has no field leaf: {path}")
    return value


def _compact(value: str) -> str:
    return "".join(char.lower() for char in value if char.isalnum())


def _software_ontology() -> OntologyIR:
    classes = tuple(
        ClassIR(name=name, label=name, evidence_refs=(_PACK_EVIDENCE,), version="1.0.0", status="accepted")
        for name in (
            "Requirement",
            "WorkItem",
            "ChangeRequest",
            "Sprint",
            "Person",
            "Team",
            "DeliveryEvent",
        )
    )
    properties = tuple(
        PropertyIR(
            name=name,
            label=name,
            domain=domain,
            value_type=value_type,
            min_count=min_count,
            evidence_refs=(_PACK_EVIDENCE,),
            version="1.0.0",
            status="accepted",
        )
        for name, domain, value_type, min_count in (
            ("requirementId", "Requirement", "string", 1),
            ("title", "Requirement", "string", 1),
            ("priority", "Requirement", "integer", 0),
            ("workItemId", "WorkItem", "string", 1),
            ("status", "WorkItem", "string", 0),
            ("estimateHours", "WorkItem", "number", 0),
            ("requestedAt", "ChangeRequest", "datetime", 1),
            ("committedDate", "WorkItem", "date", 0),
            ("eventTime", "DeliveryEvent", "datetime", 1),
        )
    )
    relationships = tuple(
        RelationshipIR(
            name=name,
            label=name,
            source=source,
            target=target,
            min_count=min_count,
            evidence_refs=(_PACK_EVIDENCE,),
            version="1.0.0",
            status="accepted",
        )
        for name, source, target, min_count in (
            ("hasWorkItem", "Requirement", "WorkItem", 0),
            ("hasChangeRequest", "Requirement", "ChangeRequest", 0),
            ("belongsToSprint", "WorkItem", "Sprint", 0),
            ("assignedToTeam", "WorkItem", "Team", 0),
            ("ownedBy", "Requirement", "Person", 0),
            ("observedBy", "WorkItem", "DeliveryEvent", 0),
        )
    )
    return OntologyIR(
        ontology_id="software-delivery",
        version="1.0.0",
        namespace="urn:aifde:software-delivery:",
        classes=classes,
        properties=properties,
        relationships=relationships,
        events=(
            EventIR(
                name="WorkItemObserved",
                label="Work Item Observed",
                subject="WorkItem",
                event_time_field="eventTime",
                evidence_refs=(_PACK_EVIDENCE,),
                version="1.0.0",
                status="accepted",
            ),
        ),
        states=(
            StateIR(
                name="WorkItemState",
                label="Work Item State",
                subject="WorkItem",
                values=("backlog", "in_progress", "done", "blocked"),
                evidence_refs=(_PACK_EVIDENCE,),
                version="1.0.0",
                status="accepted",
            ),
        ),
        metrics=(
            MetricIR(
                name="deliveryLeadTime",
                label="Delivery Lead Time",
                subject="WorkItem",
                expression="actual_complete_at - actual_start_at",
                time_grain="work_item",
                evidence_refs=(_PACK_EVIDENCE,),
                version="1.0.0",
                status="accepted",
            ),
        ),
        evidence_refs=(_PACK_EVIDENCE,),
        status="accepted",
    )


def _software_pack() -> DomainPack:
    return DomainPack(
        pack_id="software-delivery",
        version="1.0.0",
        domain="software-delivery",
        vocabulary={
            "requirement": "Requirement",
            "work item": "WorkItem",
            "change request": "ChangeRequest",
            "sprint": "Sprint",
            "delivery event": "DeliveryEvent",
        },
        ontology=_software_ontology(),
        mappings=(
            {
                "mapping_id": "software.requirement.id",
                "source_field_path": "$.requirements[*].requirement_id",
                "target_product": "requirement",
                "target_grain": "requirement",
                "target_field": "requirement_id",
                "identity_rule": "requirement external key",
                "time_semantics": "observed_at/available_at",
            },
            {
                "mapping_id": "software.requirement.title",
                "source_field_path": "$.requirements[*].title",
                "target_product": "requirement",
                "target_grain": "requirement",
                "target_field": "title",
                "identity_rule": "requirement external key",
                "time_semantics": "observed_at/available_at",
            },
            {
                "mapping_id": "software.requirement.priority",
                "source_field_path": "$.requirements[*].priority",
                "target_product": "requirement",
                "target_grain": "requirement",
                "target_field": "priority",
                "identity_rule": "requirement external key",
                "time_semantics": "observed_at/available_at",
            },
        ),
        computation={
            "feature_grain": "work_item",
            "prediction_target": "schedule_slip_days",
        },
        decisions={"candidate_plan": "sprint_assignment"},
        actions={"default_adapter": "mock-workflow-webhook"},
        acceptance_suite={
            "primary_key": "requirement_id",
            "target_product": "requirement",
            "target_grain": "requirement",
            "required_fields": ("requirement_id", "title"),
            "business_exception_predicates": ("change_requested",),
        },
    )


class GenericJsonCandidateProvider:
    """Evidence-bound candidate provider driven only by pack mappings."""

    def __init__(self, pack: DomainPack) -> None:
        self._pack = pack

    def propose(
        self, fragments: list[EvidenceFragment], context: BuilderContext
    ) -> CandidateProposal:
        ordered = tuple(sorted(fragments, key=lambda item: item.evidence_id))
        evidence_refs = tuple(item.evidence_id for item in ordered)
        primary_key = str(self._pack.acceptance_suite["primary_key"])
        target_product = str(self._pack.acceptance_suite["target_product"])
        terms = tuple(
            TermCandidate(
                term_id=f"term:{item.name}",
                surface_forms=(item.label,),
                canonical_label=item.name,
                definition_candidate=f"A {item.label} in the {self._pack.domain} domain.",
                source_evidence_refs=tuple(
                    fragment.evidence_id
                    for fragment in ordered
                    if _compact(item.name) in _compact(fragment.content)
                ),
            )
            for item in self._pack.ontology.classes
            if any(_compact(item.name) in _compact(fragment.content) for fragment in ordered)
        )
        entities: list[EntityCandidate] = []
        assertions: list[SemanticAssertion] = []
        records: list[tuple[dict[str, Any], EvidenceFragment]] = []
        for fragment in ordered:
            try:
                payload = json.loads(fragment.content)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            records.append((payload, fragment))
            entity_value = payload.get(primary_key)
            if entity_value in (None, ""):
                continue
            entity_id = f"{target_product}:{entity_value}"
            entities.append(
                EntityCandidate(
                    candidate_id=entity_id,
                    entity_type=target_product,
                    name=str(entity_value),
                    external_key=str(entity_value),
                    source_evidence_refs=(fragment.evidence_id,),
                )
            )
            for mapping in self._pack.mappings:
                field_name = _leaf(str(mapping["source_field_path"]))
                if field_name not in payload:
                    continue
                assertions.append(
                    SemanticAssertion(
                        assertion_id=f"fact:{entity_id}:{mapping['target_field']}",
                        assertion_type="fact",
                        subject=entity_id,
                        predicate=str(mapping["target_field"]),
                        value=payload[field_name],
                        evidence_refs=(fragment.evidence_id,),
                    )
                )
        mappings: list[MappingCandidate] = []
        for mapping in self._pack.mappings:
            path = str(mapping["source_field_path"])
            field_name = _leaf(path)
            refs = tuple(
                fragment.evidence_id
                for payload, fragment in records
                if field_name in payload
            )
            if not refs:
                continue
            mappings.append(
                MappingCandidate(
                    mapping_id=str(mapping["mapping_id"]),
                    source_evidence_refs=refs,
                    source_field_path=path,
                    target_product=str(mapping["target_product"]),
                    target_grain=str(mapping["target_grain"]),
                    target_field=str(mapping["target_field"]),
                    transform_expression=str(mapping.get("transform_expression", "identity")),
                    identity_rule=str(mapping["identity_rule"]),
                    time_semantics=str(mapping["time_semantics"]),
                    null_policy=str(mapping.get("null_policy", "preserve")),
                )
            )
        warnings = () if records else ("no JSON records matched the Domain Pack",)
        proposal = CandidateProposal(
            terms=terms,
            entities=tuple(entities),
            assertions=tuple(assertions),
            mappings=tuple(mappings),
            warnings=warnings,
            evidence_refs=evidence_refs,
            proposal_version="semantic-candidate-v1",
        )
        return proposal.model_copy(
            update={
                "context_digest": context.digest,
                "terms": tuple(
                    item.model_copy(
                        update={
                            "candidate_version": proposal.proposal_version,
                            "context_digest": context.digest,
                        }
                    )
                    for item in proposal.terms
                ),
                "entities": tuple(
                    item.model_copy(
                        update={
                            "candidate_version": proposal.proposal_version,
                            "context_digest": context.digest,
                        }
                    )
                    for item in proposal.entities
                ),
                "assertions": tuple(
                    item.model_copy(
                        update={
                            "candidate_version": proposal.proposal_version,
                            "context_digest": context.digest,
                        }
                    )
                    for item in proposal.assertions
                ),
                "mappings": tuple(
                    item.model_copy(
                        update={
                            "candidate_version": proposal.proposal_version,
                            "context_digest": context.digest,
                        }
                    )
                    for item in proposal.mappings
                ),
            }
        )


class JsonDomainCompiler:
    """Compile arbitrary pack-defined record mappings into a data product."""

    compiler_version = "domain-pack-json-compiler-v1"

    def __init__(self, pack: DomainPack) -> None:
        self._pack = pack
        self._primary_key = str(pack.acceptance_suite["primary_key"])
        self._target_product = str(pack.acceptance_suite["target_product"])
        self._target_grain = str(pack.acceptance_suite["target_grain"])
        self._required_fields = tuple(pack.acceptance_suite.get("required_fields", ()))

    def compile(
        self,
        proposal: CandidateProposal,
        source_registry: SourceRegistry,
        version: str,
    ) -> CompileResult:
        if not isinstance(proposal, CandidateProposal):
            raise TypeError("proposal must be a CandidateProposal")
        if not proposal.mappings:
            raise ValueError("proposal requires executable mappings before compilation")
        fragments = {
            fragment.evidence_id: fragment
            for fragment in (
                source_registry.get_fragment(ref) for ref in proposal.evidence_refs
            )
        }
        mapping_specs = tuple(
            MappingSpec(
                mapping_id=item.mapping_id,
                source_field_path=item.source_field_path,
                target_product=item.target_product,
                target_grain=item.target_grain,
                target_field=item.target_field,
                transform_expression=item.transform_expression,
                identity_rule=item.identity_rule,
                time_semantics=item.time_semantics,
                null_policy=item.null_policy,
                lineage_refs=item.source_evidence_refs,
                security_policy=f"policy:{self._pack.pack_id}",
                version=version,
            )
            for item in proposal.mappings
        )
        rows_by_id: dict[str, dict[str, Any]] = {}
        for fragment in fragments.values():
            try:
                payload = json.loads(fragment.content)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            primary = payload.get(self._primary_key)
            if primary in (None, ""):
                continue
            target_id = str(primary)
            if target_id in rows_by_id:
                raise ValueError(f"duplicate {self._primary_key} {target_id!r}")
            row: dict[str, Any] = {
                self._primary_key: primary,
                "entity_id": target_id,
                "target_product": self._target_product,
                "target_grain": self._target_grain,
                "observed_at": fragment.observed_at.isoformat(),
                "available_at": fragment.available_at.isoformat(),
                "event_time": (
                    fragment.event_time.isoformat()
                    if fragment.event_time is not None
                    else fragment.observed_at.isoformat()
                ),
                "evidence_refs": [fragment.evidence_id],
                "mapping_ids": [],
                "field_provenance": {},
            }
            for mapping in mapping_specs:
                field_name = _leaf(mapping.source_field_path)
                if field_name not in payload:
                    continue
                value = payload[field_name]
                if mapping.transform_expression == "trim" and isinstance(value, str):
                    value = value.strip()
                row[mapping.target_field] = value
                row["mapping_ids"].append(mapping.mapping_id)
                location = FieldEvidenceLocation(
                    evidence_id=fragment.evidence_id,
                    source_asset_id=fragment.source_asset_id,
                    source_version=fragment.source_version,
                    snapshot_id=fragment.snapshot_id,
                    locator=fragment.locator,
                    observed_at=fragment.observed_at,
                    available_at=fragment.available_at,
                    event_time=fragment.event_time,
                )
                row["field_provenance"][mapping.target_field] = FieldValueProvenance(
                    field_name=mapping.target_field,
                    value=value,
                    evidence_refs=(fragment.evidence_id,),
                    mapping_ids=(mapping.mapping_id,),
                    source_locations=(location,),
                    observed_at=fragment.observed_at,
                    available_at=fragment.available_at,
                    event_time=fragment.event_time,
                )
            rows_by_id[target_id] = row
        canonical_rows = [rows_by_id[key] for key in sorted(rows_by_id)]
        provenance_rows = [
            {
                "target_id": row["entity_id"],
                "target_kind": self._target_product,
                "evidence_refs": list(row["evidence_refs"]),
                "mapping_ids": list(row["mapping_ids"]),
                "field_provenance": {
                    key: _jsonable(value)
                    for key, value in row["field_provenance"].items()
                },
                "source_locations": [
                    _jsonable(location)
                    for provenance in row["field_provenance"].values()
                    for location in provenance.source_locations
                ],
            }
            for row in canonical_rows
        ]
        ontology = self._bound_ontology(proposal, version)
        ontology_artifacts = OntologyIRCompiler().compile(ontology)
        data_turtle = self._render_data(canonical_rows)
        ontology_candidate = OntologyCandidate(
            candidate_id=f"ontology-candidate:{self._pack.pack_id}:{version}",
            version=version,
            classes=tuple(item.name for item in ontology.classes),
            properties=tuple(item.name for item in ontology.properties),
            relationships=tuple(
                (item.source, item.name, item.target) for item in ontology.relationships
            ),
            states=tuple(value for item in ontology.states for value in item.values),
            events=tuple(item.name for item in ontology.events),
            identity_keys=((self._target_product, (self._primary_key,)),),
            temporal_semantics=(("observed_at", "observed_time"), ("available_at", "available_time")),
            access_policies=((self._target_product, f"policy:{self._pack.pack_id}"),),
            mapping_spec_refs=tuple(item.mapping_id for item in mapping_specs),
            evidence_refs=tuple(proposal.evidence_refs),
        )
        hashes = {
            "ontology": ontology_artifacts.ontology_hash,
            "shapes": ontology_artifacts.shapes_hash,
            "mappings": _hash_json([self._mapping_dict(item) for item in mapping_specs]),
            "canonical_product": _hash_json(canonical_rows),
            "provenance": _hash_json(provenance_rows),
            "canonical_rdf": _hash_text(data_turtle),
        }
        result = CompileResult(
            ontology_candidate=ontology_candidate,
            mapping_specs=mapping_specs,
            canonical_rows=canonical_rows,
            provenance_rows=provenance_rows,
            validation_report=CompileValidation(
                passed=False,
                evidence_refs=tuple(proposal.evidence_refs),
                compiler_version=self.compiler_version,
            ),
            artifact_hashes=hashes,
            ontology_turtle=ontology_artifacts.ontology_text,
            shapes_turtle=ontology_artifacts.shapes_text,
            data_turtle=data_turtle,
            proposal_evidence_refs=tuple(proposal.evidence_refs),
            source_field_paths=tuple(item.source_field_path for item in mapping_specs),
            canonical_line_rows=[],
            canonical_revision_rows=[],
            domain_pack_id=self._pack.pack_id,
            primary_key_field=self._primary_key,
            target_product=self._target_product,
            target_grain=self._target_grain,
            required_fields=self._required_fields,
            business_exception_coverage=True,
        )
        result.artifact_manifest_id = _ArtifactManifestAuthority.issue(result.artifact_hashes)
        result.validation_report = self.validate(result)
        return result

    def validate(self, result: CompileResult) -> CompileValidation:
        violations: list[str] = []
        if not _ArtifactManifestAuthority.verify(result.artifact_manifest_id, result.artifact_hashes):
            violations.append("artifact manifest is missing or does not match compiler-issued hashes")
        if result.domain_pack_id != self._pack.pack_id:
            violations.append("compile result domain pack does not match compiler")
        known_evidence = set(result.proposal_evidence_refs)
        known_mappings = {item.mapping_id for item in result.mapping_specs}
        if not known_evidence:
            violations.append("compile result requires proposal evidence refs")
        for mapping in result.mapping_specs:
            if mapping.target_product != self._target_product:
                violations.append(f"mapping {mapping.mapping_id} target product is not governed")
            if mapping.target_grain != self._target_grain:
                violations.append(f"mapping {mapping.mapping_id} target grain is not governed")
            if not set(mapping.lineage_refs).issubset(known_evidence):
                violations.append(f"mapping {mapping.mapping_id} references unknown evidence")
        seen: set[str] = set()
        for row in result.canonical_rows:
            target_id = str(row.get(self._primary_key, ""))
            if not target_id:
                violations.append(f"canonical row requires {self._primary_key}")
            if target_id in seen:
                violations.append(f"duplicate {self._primary_key} {target_id!r}")
            seen.add(target_id)
            if row.get("target_product") != self._target_product:
                violations.append(f"canonical row {target_id!r} target product is not governed")
            if row.get("target_grain") != self._target_grain:
                violations.append(f"canonical row {target_id!r} target grain is not governed")
            for field_name in self._required_fields:
                if row.get(field_name) in (None, ""):
                    violations.append(f"canonical row {target_id!r} requires {field_name}")
            if not set(row.get("evidence_refs", ())).issubset(known_evidence):
                violations.append(f"canonical row {target_id!r} references unknown evidence")
            if not set(row.get("mapping_ids", ())).issubset(known_mappings):
                violations.append(f"canonical row {target_id!r} references unknown mappings")
            fields = row.get("field_provenance")
            if not isinstance(fields, Mapping):
                violations.append(f"canonical row {target_id!r} requires field provenance")
                continue
            for field_name, provenance in fields.items():
                if not isinstance(provenance, FieldValueProvenance):
                    violations.append(f"field provenance for {target_id!r}/{field_name!r} is invalid")
                    continue
                if field_name not in row or _jsonable(provenance.value) != _jsonable(row[field_name]):
                    violations.append(f"field provenance for {target_id!r}/{field_name!r} is not closed")
                if not set(provenance.evidence_refs).issubset(known_evidence):
                    violations.append(f"field provenance for {target_id!r}/{field_name!r} references unknown evidence")
                if not set(provenance.mapping_ids).issubset(known_mappings):
                    violations.append(f"field provenance for {target_id!r}/{field_name!r} references unknown mappings")
            try:
                observed = datetime.fromisoformat(str(row["observed_at"]))
                available = datetime.fromisoformat(str(row["available_at"]))
                if observed > available:
                    violations.append(f"canonical row {target_id!r} available_at precedes observed_at")
            except (KeyError, ValueError):
                violations.append(f"canonical row {target_id!r} requires valid temporal metadata")
        expected_hashes = {
            "ontology": _hash_text(result.ontology_turtle),
            "shapes": _hash_text(result.shapes_turtle),
            "mappings": _hash_json([self._mapping_dict(item) for item in result.mapping_specs]),
            "canonical_product": _hash_json(result.canonical_rows),
            "provenance": _hash_json(result.provenance_rows),
            "canonical_rdf": _hash_text(result.data_turtle),
        }
        if expected_hashes != result.artifact_hashes:
            violations.append("artifact hashes do not match compiled content")
        return CompileValidation(
            passed=not violations,
            violations=tuple(dict.fromkeys(violations)),
            evidence_refs=tuple(result.proposal_evidence_refs),
            compiler_version=self.compiler_version,
        )

    def _bound_ontology(self, proposal: CandidateProposal, version: str) -> OntologyIR:
        refs = tuple(proposal.evidence_refs)
        declarations = {
            "classes": tuple(
                item.model_copy(update={"evidence_refs": refs, "version": version, "status": "accepted"})
                for item in self._pack.ontology.classes
            ),
            "properties": tuple(
                item.model_copy(update={"evidence_refs": refs, "version": version, "status": "accepted"})
                for item in self._pack.ontology.properties
            ),
            "relationships": tuple(
                item.model_copy(update={"evidence_refs": refs, "version": version, "status": "accepted"})
                for item in self._pack.ontology.relationships
            ),
            "events": tuple(
                item.model_copy(update={"evidence_refs": refs, "version": version, "status": "accepted"})
                for item in self._pack.ontology.events
            ),
            "states": tuple(
                item.model_copy(update={"evidence_refs": refs, "version": version, "status": "accepted"})
                for item in self._pack.ontology.states
            ),
            "metrics": tuple(
                item.model_copy(update={"evidence_refs": refs, "version": version, "status": "accepted"})
                for item in self._pack.ontology.metrics
            ),
        }
        return self._pack.ontology.model_copy(
            update={
                **declarations,
                "version": version,
                "evidence_refs": refs,
                "status": "accepted",
            }
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

    def _render_data(self, rows: Sequence[Mapping[str, Any]]) -> str:
        lines = [f"@prefix ex: <{self._pack.ontology.namespace}> .", ""]
        for row in rows:
            target_id = str(row[self._primary_key]).replace('"', '\\"')
            predicate_values = [
                f'ex:entityId "{target_id}"',
                f'ex:targetProduct "{self._target_product}"',
            ]
            for field_name in sorted(self._required_fields):
                if field_name in row:
                    value = str(row[field_name]).replace('"', '\\"')
                    predicate_values.append(f'ex:{field_name} "{value}"')
            lines.append(
                f"ex:record-{target_id} a ex:{self._target_product.title().replace('_', '')} ;\n    "
                + " ;\n    ".join(predicate_values)
                + " ."
            )
        return "\n".join(lines) + "\n"


class SoftwareDeliveryDomain:
    """Domain Pack adapter for requirements and delivery alignment."""

    def __init__(self) -> None:
        self.pack = _software_pack()
        self._provider = GenericJsonCandidateProvider(self.pack)
        self._compiler = JsonDomainCompiler(self.pack)

    @property
    def provider(self) -> CandidateProvider:
        return self._provider

    @property
    def compiler(self) -> JsonDomainCompiler:
        return self._compiler

    def capture(self, source_paths: Sequence[str]) -> DomainCapture:
        if not source_paths:
            raise ValueError("software-delivery Domain Pack requires at least one source path")
        registry = SourceRegistry()
        fragments: list[EvidenceFragment] = []
        snapshots = []
        for index, source_path in enumerate(source_paths):
            path = Path(source_path)
            if not path.exists():
                raise FileNotFoundError(f"software-delivery source path does not exist: {path}")
            connector = LocalFileConnector.from_path(
                path,
                owner="software-delivery-ingestion",
                authority_level=3,
                classification="internal",
                access_policy_id="policy:software-delivery",
                registry=registry,
            )
            snapshot = connector.capture(
                CaptureRequest(
                    version=f"source-{index + 1}",
                    observed_at=datetime(2026, 8, 14, 9, tzinfo=timezone.utc),
                    available_at=datetime(2026, 8, 14, 10, tzinfo=timezone.utc),
                    extraction_version="local-file-v1",
                )
            )
            report = EvidenceExtractor().extract(snapshot)
            # The extractor is pure and returns fragments; register the same
            # immutable identities in the source registry so later compiler
            # stages can replay them by evidence ID.
            fragments.extend(
                registry.slice(
                    fragment.snapshot_id,
                    fragment.locator,
                    fragment.content,
                    normalized_content=fragment.normalized_content,
                    extraction_method=fragment.extraction_method,
                    event_time=fragment.event_time,
                    confidence=fragment.confidence,
                )
                for fragment in report.fragments
            )
            snapshots.append(snapshot)
        return DomainCapture(
            registry=registry,
            fragments=tuple(fragments),
            snapshots=tuple(snapshots),
        )


__all__ = ["GenericJsonCandidateProvider", "JsonDomainCompiler", "SoftwareDeliveryDomain"]
