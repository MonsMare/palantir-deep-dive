"""Evidence-bound semantic candidates for the ontology builder.

This module deliberately stops at typed candidates.  It does not publish
business facts or silently merge source identities.  Deterministic extraction
is used by the local demo, while ``CandidateProvider`` keeps the boundary
replaceable for a future LLM proposal adapter.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from hashlib import sha256
import json
import re
from typing import Any, Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .contracts import EvidenceFragment


AssertionType = Literal["fact", "definition", "rule", "assumption", "inference"]
CandidateStatus = Literal["proposed", "accepted", "rejected", "deprecated"]
MatchStatus = Literal["confirmed", "probable_match", "unresolved", "rejected"]


def _nonblank(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must not be empty")
    return value.strip()


def _stable_id(prefix: str, *parts: str) -> str:
    payload = "\x00".join(parts).encode("utf-8")
    return f"{prefix}:{sha256(payload).hexdigest()[:16]}"


def _normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


class BuilderContext(BaseModel):
    """Immutable context that constrains one candidate-building run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: str
    domain: str
    ontology_version: str
    known_terms: tuple[str, ...] = ()

    @field_validator("project_id", "domain", "ontology_version")
    @classmethod
    def validate_identity(cls, value: str, info: Any) -> str:
        return _nonblank(value, info.field_name)

    @field_validator("known_terms")
    @classmethod
    def validate_terms(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(_nonblank(item, "known_terms item") for item in value)


class TermCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    term_id: str
    surface_forms: tuple[str, ...]
    canonical_label: str
    definition_candidate: str | None = None
    source_evidence_refs: tuple[str, ...] = ()
    conflicting_definitions: tuple[str, ...] = ()
    status: CandidateStatus = "proposed"

    @field_validator("term_id", "canonical_label")
    @classmethod
    def validate_identity(cls, value: str, info: Any) -> str:
        return _nonblank(value, info.field_name)

    @field_validator("surface_forms")
    @classmethod
    def validate_surface_forms(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or any(not item.strip() for item in value):
            raise ValueError("surface_forms must contain non-empty values")
        return tuple(dict.fromkeys(item.strip() for item in value))


class EntityCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str
    entity_type: str
    name: str
    external_key: str | None = None
    source_evidence_refs: tuple[str, ...] = ()
    identity_features: tuple[str, ...] = ()
    conflict_refs: tuple[str, ...] = ()
    resolution_status: Literal["unresolved", "probable_match", "confirmed", "rejected"] = "unresolved"

    @field_validator("candidate_id", "entity_type", "name")
    @classmethod
    def validate_identity(cls, value: str, info: Any) -> str:
        return _nonblank(value, info.field_name)


class EntityMatch(BaseModel):
    """A replayable identity-resolution decision, not an implicit merge."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str
    canonical_entity_id: str | None = None
    score: float = Field(ge=0.0, le=1.0)
    threshold: float = Field(ge=0.0, le=1.0)
    matching_fields: tuple[str, ...] = ()
    algorithm_version: str
    conflict_refs: tuple[str, ...] = ()
    status: MatchStatus = "unresolved"

    @field_validator("candidate_id", "algorithm_version")
    @classmethod
    def validate_identity(cls, value: str, info: Any) -> str:
        return _nonblank(value, info.field_name)

    @model_validator(mode="after")
    def validate_match_state(self) -> Self:
        if self.status in {"confirmed", "probable_match"} and not self.canonical_entity_id:
            raise ValueError("resolved matches require canonical_entity_id")
        if self.status == "probable_match" and self.score < self.threshold:
            raise ValueError("probable_match score must meet threshold")
        return self


class SemanticAssertion(BaseModel):
    """A typed semantic claim with explicit epistemic status."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    assertion_id: str
    assertion_type: AssertionType
    subject: str
    predicate: str
    value: Any
    evidence_refs: tuple[str, ...] = ()
    reviewer_owner: str | None = None
    expression: str | None = None

    @field_validator("assertion_id", "subject", "predicate")
    @classmethod
    def validate_identity(cls, value: str, info: Any) -> str:
        return _nonblank(value, info.field_name)

    @model_validator(mode="after")
    def validate_epistemic_fields(self) -> Self:
        if self.assertion_type == "definition" and not self.reviewer_owner:
            raise ValueError("definition assertions require reviewer_owner")
        if self.assertion_type == "rule" and not self.expression:
            raise ValueError("rule assertions require executable expression")
        return self


class MappingCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mapping_id: str
    source_evidence_refs: tuple[str, ...]
    source_field_path: str
    target_product: str
    target_grain: str
    target_field: str
    transform_expression: str = "identity"
    identity_rule: str
    time_semantics: str
    null_policy: str = "preserve"

    @field_validator(
        "mapping_id",
        "source_field_path",
        "target_product",
        "target_grain",
        "target_field",
        "identity_rule",
        "time_semantics",
        "null_policy",
    )
    @classmethod
    def validate_text(cls, value: str, info: Any) -> str:
        return _nonblank(value, info.field_name)

    @field_validator("source_evidence_refs")
    @classmethod
    def validate_evidence(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or any(not item.strip() for item in value):
            raise ValueError("mapping candidates require source evidence")
        return tuple(dict.fromkeys(value))


class CandidateProposal(BaseModel):
    """The complete mutable proposal produced before review and compilation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    terms: tuple[TermCandidate, ...] = ()
    entities: tuple[EntityCandidate, ...] = ()
    entity_matches: tuple[EntityMatch, ...] = ()
    assertions: tuple[SemanticAssertion, ...] = ()
    mappings: tuple[MappingCandidate, ...] = ()
    warnings: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()

    @field_validator("warnings")
    @classmethod
    def normalize_warnings(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(item.strip() for item in value if item.strip()))


class CandidateProvider(Protocol):
    def propose(
        self, fragments: list[EvidenceFragment], context: BuilderContext
    ) -> CandidateProposal:
        """Propose typed candidates without publishing them."""


class DeterministicCandidateProvider:
    """Extract a small procurement vocabulary from the local fixture format."""

    canonical_entities: Mapping[str, Mapping[str, str]] = {
        "supplier:acme": {"name": "Acme Industrial", "external_key": "ACME-001"},
        "supplier:northstar": {
            "name": "Northstar Components",
            "external_key": "NORTHSTAR-001",
        },
    }
    aliases: Mapping[str, str] = {"acmeindustries": "supplier:acme"}

    def propose(
        self, fragments: list[EvidenceFragment], context: BuilderContext
    ) -> CandidateProposal:
        del context
        ordered = sorted(fragments, key=lambda item: item.evidence_id)
        evidence_refs = tuple(dict.fromkeys(item.evidence_id for item in ordered))
        terms: dict[str, TermCandidate] = {}
        entities: dict[str, EntityCandidate] = {}
        assertions: dict[str, SemanticAssertion] = {}
        mappings: dict[str, MappingCandidate] = {}
        warnings: list[str] = []
        first_ref = evidence_refs[0] if evidence_refs else ""

        for fragment in ordered:
            content = fragment.content
            if fragment.locator.startswith("$"):
                self._extract_purchase_order(
                    content,
                    fragment,
                    terms,
                    entities,
                    assertions,
                    mappings,
                )
            elif fragment.locator.startswith("line:"):
                self._extract_note(
                    content,
                    fragment,
                    entities,
                    assertions,
                    terms,
                )
            else:
                warnings.append(f"unsupported semantic locator: {fragment.locator}")

        definition_id = "definition:delivery-delay"
        assertions[definition_id] = SemanticAssertion(
            assertion_id=definition_id,
            assertion_type="definition",
            subject="DeliveryEvent",
            predicate="delayRule",
            value="actual_delivery_date > promised_delivery_date",
            evidence_refs=(first_ref,) if first_ref else (),
            reviewer_owner="procurement-owner",
        )
        assumption_id = "assumption:actual-delivery-date"
        assertions[assumption_id] = SemanticAssertion(
            assertion_id=assumption_id,
            assertion_type="assumption",
            subject="purchase-order:PO-001",
            predicate="actualDeliveryDate",
            value="unknown",
        )
        return CandidateProposal(
            terms=tuple(sorted(terms.values(), key=lambda item: item.term_id)),
            entities=tuple(sorted(entities.values(), key=lambda item: item.candidate_id)),
            assertions=tuple(sorted(assertions.values(), key=lambda item: item.assertion_id)),
            mappings=tuple(sorted(mappings.values(), key=lambda item: item.mapping_id)),
            warnings=tuple(sorted(set(warnings))),
            evidence_refs=evidence_refs,
        )

    def _extract_purchase_order(
        self,
        content: str,
        fragment: EvidenceFragment,
        terms: dict[str, TermCandidate],
        entities: dict[str, EntityCandidate],
        assertions: dict[str, SemanticAssertion],
        mappings: dict[str, MappingCandidate],
    ) -> None:
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError("purchase-order evidence is not canonical JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("purchase-order evidence must be an object")
        po_id = _nonblank(str(payload.get("po_id", "")), "po_id")
        supplier_name = _nonblank(str(payload.get("supplier", "")), "supplier")
        promised_date = _nonblank(str(payload.get("promised_date", "")), "promised_date")
        po_ref = fragment.evidence_id
        supplier_id = self._canonical_supplier_id(supplier_name)
        supplier_candidate_id = f"supplier:{_normalize_name(supplier_name)}"
        entities[supplier_candidate_id] = EntityCandidate(
            candidate_id=supplier_candidate_id,
            entity_type="supplier",
            name=supplier_name,
            external_key=self._external_key(supplier_id),
            source_evidence_refs=(po_ref,),
        )
        po_candidate_id = f"purchase-order:{po_id}"
        entities[po_candidate_id] = EntityCandidate(
            candidate_id=po_candidate_id,
            entity_type="purchase_order",
            name=po_id,
            external_key=po_id,
            source_evidence_refs=(po_ref,),
        )
        terms["term:supplier"] = TermCandidate(
            term_id="term:supplier",
            surface_forms=("supplier",),
            canonical_label="Supplier",
            definition_candidate="A party responsible for fulfilling a purchase order.",
            source_evidence_refs=(po_ref,),
        )
        terms["term:purchase-order"] = TermCandidate(
            term_id="term:purchase-order",
            surface_forms=("purchase order", "PO"),
            canonical_label="PurchaseOrder",
            definition_candidate="A commercial request with a promised delivery date.",
            source_evidence_refs=(po_ref,),
        )
        assertions[f"fact:{po_id}:supplier"] = SemanticAssertion(
            assertion_id=f"fact:{po_id}:supplier",
            assertion_type="fact",
            subject=po_candidate_id,
            predicate="supplier",
            value=supplier_candidate_id,
            evidence_refs=(po_ref,),
        )
        assertions[f"fact:{po_id}:promised-date"] = SemanticAssertion(
            assertion_id=f"fact:{po_id}:promised-date",
            assertion_type="fact",
            subject=po_candidate_id,
            predicate="promisedDeliveryDate",
            value=promised_date,
            evidence_refs=(po_ref,),
        )
        mappings[f"mapping:{po_id}:supplier"] = MappingCandidate(
            mapping_id=f"mapping:{po_id}:supplier",
            source_evidence_refs=(po_ref,),
            source_field_path=f"$.purchase_orders[*].supplier",
            target_product="purchase_order",
            target_grain="purchase_order",
            target_field="supplier_id",
            identity_rule="supplier canonical entity resolution",
            time_semantics="observed_at/available_at",
        )
        mappings[f"mapping:{po_id}:promised-date"] = MappingCandidate(
            mapping_id=f"mapping:{po_id}:promised-date",
            source_evidence_refs=(po_ref,),
            source_field_path="$.purchase_orders[*].promised_date",
            target_product="purchase_order",
            target_grain="purchase_order",
            target_field="promised_delivery_date",
            identity_rule="purchase order external key",
            time_semantics="valid_time",
        )

    def _extract_note(
        self,
        content: str,
        fragment: EvidenceFragment,
        entities: dict[str, EntityCandidate],
        assertions: dict[str, SemanticAssertion],
        terms: dict[str, TermCandidate],
    ) -> None:
        ref = fragment.evidence_id
        variant = re.search(
            r"(?P<alias>[A-Za-z ]+) is the display-name variant for (?P<canonical>[A-Za-z ]+)\.",
            content,
        )
        if variant:
            alias = variant.group("alias").strip()
            canonical = variant.group("canonical").strip()
            alias_id = self._alias_candidate_id(alias)
            entities[alias_id] = EntityCandidate(
                candidate_id=alias_id,
                entity_type="supplier",
                name=alias,
                source_evidence_refs=(ref,),
                conflict_refs=(f"conflict:{alias_id}:display-name",),
            )
            assertions[f"fact:{alias_id}:alias"] = SemanticAssertion(
                assertion_id=f"fact:{alias_id}:alias",
                assertion_type="fact",
                subject=alias_id,
                predicate="displayNameVariantOf",
                value=f"supplier:{_normalize_name(canonical)}",
                evidence_refs=(ref,),
            )
            terms["term:display-name-variant"] = TermCandidate(
                term_id="term:display-name-variant",
                surface_forms=("display-name variant",),
                canonical_label="DisplayNameVariant",
                definition_candidate="A source-specific name that may refer to an existing entity.",
                source_evidence_refs=(ref,),
            )
        date_change = re.search(
            r"(?P<alias>[A-Za-z ]+) promised date changed to (?P<date>\d{4}-\d{2}-\d{2})\.",
            content,
        )
        if date_change:
            alias_id = f"supplier:{_normalize_name(date_change.group('alias'))}"
            assertions[f"fact:{alias_id}:promised-date-revision"] = SemanticAssertion(
                assertion_id=f"fact:{alias_id}:promised-date-revision",
                assertion_type="fact",
                subject=alias_id,
                predicate="promisedDateRevision",
                value=date_change.group("date"),
                evidence_refs=(ref,),
            )
        actual = re.search(
            r"(?:actual|delivered|delivery) date(?: was| is|:)?\s*(\d{4}-\d{2}-\d{2})",
            content,
            re.IGNORECASE,
        )
        if actual:
            assertions["fact:PO-001:actual-date"] = SemanticAssertion(
                assertion_id="fact:PO-001:actual-date",
                assertion_type="fact",
                subject="purchase-order:PO-001",
                predicate="actualDeliveryDate",
                value=actual.group(1),
                evidence_refs=(ref,),
            )

    def _canonical_supplier_id(self, name: str) -> str:
        normalized = _normalize_name(name)
        if normalized in self.aliases:
            return self.aliases[normalized]
        for entity_id, value in self.canonical_entities.items():
            if _normalize_name(value["name"]) == normalized:
                return entity_id
        return f"supplier:{normalized}"

    def _alias_candidate_id(self, name: str) -> str:
        normalized = _normalize_name(name)
        canonical_id = self.aliases.get(normalized)
        if canonical_id == "supplier:acme":
            return "supplier:acme-east"
        return f"supplier:{normalized}"

    def _external_key(self, entity_id: str) -> str | None:
        data = self.canonical_entities.get(entity_id)
        return None if data is None else data.get("external_key")


class EntityResolver:
    """Resolve identities conservatively and preserve ambiguous matches."""

    def __init__(
        self,
        canonical_entities: Mapping[str, Mapping[str, str]] | None = None,
        aliases: Mapping[str, str] | None = None,
    ) -> None:
        self._canonical_entities = dict(canonical_entities or DeterministicCandidateProvider.canonical_entities)
        self._aliases = {
            _normalize_name(key): value
            for key, value in (aliases or DeterministicCandidateProvider.aliases).items()
        }

    def resolve(self, candidates: list[EntityCandidate], strategy_version: str) -> list[EntityMatch]:
        strategy_version = _nonblank(strategy_version, "strategy_version")
        results: list[EntityMatch] = []
        for candidate in candidates:
            exact = self._exact_match(candidate)
            if exact is not None:
                results.append(
                    EntityMatch(
                        candidate_id=candidate.candidate_id,
                        canonical_entity_id=exact,
                        score=1.0,
                        threshold=1.0,
                        matching_fields=("external_key",) if candidate.external_key else ("name",),
                        algorithm_version=strategy_version,
                        status="confirmed",
                    )
                )
                continue
            alias_target = self._aliases.get(_normalize_name(candidate.name))
            if alias_target is not None:
                results.append(
                    EntityMatch(
                        candidate_id=candidate.candidate_id,
                        canonical_entity_id=alias_target,
                        score=0.9,
                        threshold=0.8,
                        matching_fields=("alias", "name"),
                        algorithm_version=strategy_version,
                        conflict_refs=tuple(
                            dict.fromkeys(
                                (*candidate.conflict_refs, f"conflict:{candidate.candidate_id}:alias")
                            )
                        ),
                        status="probable_match",
                    )
                )
                continue
            results.append(
                EntityMatch(
                    candidate_id=candidate.candidate_id,
                    score=0.0,
                    threshold=0.8,
                    matching_fields=(),
                    algorithm_version=strategy_version,
                    conflict_refs=candidate.conflict_refs,
                    status="unresolved",
                )
            )
        return results

    def _exact_match(self, candidate: EntityCandidate) -> str | None:
        if candidate.external_key:
            for entity_id, data in self._canonical_entities.items():
                if data.get("external_key") == candidate.external_key:
                    return entity_id
        normalized = _normalize_name(candidate.name)
        for entity_id, data in self._canonical_entities.items():
            if _normalize_name(data.get("name", "")) == normalized:
                return entity_id
        return None


class SemanticCandidateBuilder:
    """Run a provider and enforce evidence/epistemic invariants."""

    def __init__(
        self,
        provider: CandidateProvider,
        resolver: EntityResolver | None = None,
        strategy_version: str = "entity-resolver-v1",
    ) -> None:
        self._provider = provider
        provider_entities = getattr(provider, "canonical_entities", None)
        provider_aliases = getattr(provider, "aliases", None)
        self._resolver = resolver or EntityResolver(provider_entities, provider_aliases)
        self._strategy_version = _nonblank(strategy_version, "strategy_version")

    def build(
        self, fragments: list[EvidenceFragment], context: BuilderContext
    ) -> CandidateProposal:
        proposal = self._provider.propose(list(fragments), context)
        evidence_refs = {item.evidence_id for item in fragments}
        self._validate_assertions(proposal.assertions, evidence_refs)
        self._validate_evidence_refs(proposal, evidence_refs)
        matches = tuple(
            self._resolver.resolve(list(proposal.entities), self._strategy_version)
        )
        return CandidateProposal(
            terms=proposal.terms,
            entities=proposal.entities,
            entity_matches=matches,
            assertions=proposal.assertions,
            mappings=proposal.mappings,
            warnings=proposal.warnings,
            evidence_refs=proposal.evidence_refs,
        )

    @staticmethod
    def _validate_assertions(
        assertions: Sequence[SemanticAssertion], evidence_refs: set[str]
    ) -> None:
        for assertion in assertions:
            refs = set(assertion.evidence_refs)
            if assertion.assertion_type in {"fact", "definition", "rule"} and not refs:
                raise ValueError(
                    f"{assertion.assertion_type} assertion {assertion.assertion_id} requires evidence"
                )
            if not refs.issubset(evidence_refs):
                raise ValueError(f"assertion {assertion.assertion_id} references unknown evidence")

    @staticmethod
    def _validate_evidence_refs(
        proposal: CandidateProposal, evidence_refs: set[str]
    ) -> None:
        if not set(proposal.evidence_refs).issubset(evidence_refs):
            raise ValueError("proposal references unknown evidence")
        for mapping in proposal.mappings:
            if not set(mapping.source_evidence_refs).issubset(evidence_refs):
                raise ValueError(f"mapping {mapping.mapping_id} references unknown evidence")


__all__ = [
    "BuilderContext",
    "CandidateProposal",
    "CandidateProvider",
    "DeterministicCandidateProvider",
    "EntityCandidate",
    "EntityMatch",
    "EntityResolver",
    "MappingCandidate",
    "SemanticAssertion",
    "SemanticCandidateBuilder",
    "TermCandidate",
]
