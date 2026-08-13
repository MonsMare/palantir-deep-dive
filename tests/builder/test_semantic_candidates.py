from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from aifde.builder.contracts import EvidenceFragment, SourceAsset
from aifde.builder.semantic import (
    BuilderContext,
    CandidateProposal,
    DeterministicCandidateProvider,
    EntityCandidate,
    EntityResolver,
    SemanticAssertion,
    SemanticCandidateBuilder,
)
from aifde.builder.sources import SourceRegistry


FIXTURES = Path(__file__).parent / "fixtures"


def dt(hour: int) -> datetime:
    return datetime(2026, 8, 13, hour, tzinfo=timezone.utc)


def supplier_fragments() -> list[EvidenceFragment]:
    registry = SourceRegistry()
    json_asset = registry.register(
        SourceAsset.register(
            "erp-purchase-orders",
            "fixture://supplier_purchase_orders.json",
            "json",
            "procurement",
            5,
            "internal",
            "policy:procurement",
            "purchase-order-v1",
            {"format": "json"},
        )
    )
    notes_asset = registry.register(
        SourceAsset.register(
            "procurement-notes",
            "fixture://supplier_notes.md",
            "markdown",
            "procurement",
            3,
            "internal",
            "policy:procurement",
            "notes-v1",
            {"format": "markdown"},
        )
    )
    json_snapshot = registry.capture(
        json_asset.source_asset_id,
        "2026-08-13",
        (FIXTURES / "supplier_purchase_orders.json").read_bytes(),
        dt(9),
        dt(10),
        "raw-v1",
    )
    notes_snapshot = registry.capture(
        notes_asset.source_asset_id,
        "2026-08-13",
        (FIXTURES / "supplier_notes.md").read_bytes(),
        dt(11),
        dt(12),
        "raw-v1",
    )
    po_content = json.dumps(
        {
            "po_id": "PO-001",
            "supplier": "Acme Industrial",
            "promised_date": "2026-09-01",
            "items": [{"sku": "VALVE-100", "quantity": 20}],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return [
        registry.slice(json_snapshot.snapshot_id, "$.purchase_orders[0]", po_content),
        registry.slice(
            notes_snapshot.snapshot_id,
            "line:3-4",
            "- Acme Industries is the display-name variant for Acme Industrial.\n"
            "- Acme Industries promised date changed to 2026-09-05.",
        ),
    ]


@pytest.fixture
def context() -> BuilderContext:
    return BuilderContext(
        project_id="supplier-ontology",
        domain="procurement",
        ontology_version="v1",
        known_terms=("supplier", "purchase order", "promised date", "delay date"),
    )


@pytest.fixture
def proposal(context: BuilderContext) -> CandidateProposal:
    return SemanticCandidateBuilder(DeterministicCandidateProvider()).build(
        supplier_fragments(), context
    )


def test_candidate_proposal_keeps_fact_definition_and_assumption_distinct(
    proposal: CandidateProposal,
):
    assert {item.assertion_type for item in proposal.assertions} == {
        "fact",
        "definition",
        "assumption",
        "inference",
    }
    assert all(
        item.evidence_refs
        for item in proposal.assertions
        if item.assertion_type == "fact"
    )
    assert any(item.reviewer_owner for item in proposal.assertions if item.assertion_type == "definition")


def test_supplier_alias_is_probable_match_but_conflict_stays_open(
    proposal: CandidateProposal,
):
    match = next(item for item in proposal.entity_matches if item.candidate_id == "supplier:acme-east")

    assert match.canonical_entity_id == "supplier:acme"
    assert match.score >= match.threshold
    assert match.status == "probable_match"
    assert match.matching_fields
    assert match.algorithm_version
    assert match.conflict_refs


def test_source_name_without_external_key_stays_probable_match(proposal: CandidateProposal):
    candidate = next(item for item in proposal.entities if item.candidate_id == "supplier:acmeindustrial")
    match = next(item for item in proposal.entity_matches if item.candidate_id == candidate.candidate_id)

    assert candidate.external_key is None
    assert match.canonical_entity_id == "supplier:acme"
    assert match.status == "probable_match"


def test_date_revision_without_purchase_order_link_is_inference_on_existing_alias(
    proposal: CandidateProposal,
):
    revision = next(
        item for item in proposal.assertions if item.predicate == "promisedDateRevision"
    )

    assert revision.assertion_type == "inference"
    assert revision.subject == "supplier:acme-east"


def test_candidate_proposal_carries_context_version_and_unreleased_assumption(
    proposal: CandidateProposal, context: BuilderContext
):
    assert proposal.proposal_version
    assert proposal.context_digest == context.digest
    assert all(
        item.candidate_version == proposal.proposal_version
        and item.context_digest == context.digest
        for item in (*proposal.assertions, *proposal.mappings)
    )
    assumptions = [item for item in proposal.assertions if item.assertion_type == "assumption"]
    assert assumptions
    assert all(item.release_status == "unreleased" for item in assumptions)


def test_assumption_cannot_be_marked_release_eligible():
    with pytest.raises(ValueError, match="unreleased"):
        SemanticAssertion(
            assertion_id="assumption:delivery",
            assertion_type="assumption",
            subject="purchase-order:PO-001",
            predicate="actualDeliveryDate",
            value="unknown",
            release_status="eligible",
        )


def test_candidate_provider_cannot_self_approve(context: BuilderContext):
    class SelfApprovingProvider:
        def propose(self, fragments: list[EvidenceFragment], context: BuilderContext) -> CandidateProposal:
            del fragments, context
            return CandidateProposal(release_eligibility="eligible")

    with pytest.raises(ValueError, match="self-approve"):
        SemanticCandidateBuilder(SelfApprovingProvider()).build(supplier_fragments(), context)


def test_provider_never_promotes_unanchored_inference(proposal: CandidateProposal):
    for assertion in proposal.assertions:
        if assertion.assertion_type in {"fact", "definition", "rule"}:
            assert assertion.evidence_refs


def test_missing_evidence_fact_is_rejected(context: BuilderContext):
    class InvalidProvider:
        def propose(self, fragments: list[EvidenceFragment], context: BuilderContext) -> CandidateProposal:
            return CandidateProposal(
                terms=(),
                entities=(),
                entity_matches=(),
                assertions=(
                    SemanticAssertion(
                        assertion_id="fact:unanchored",
                        assertion_type="fact",
                        subject="supplier",
                        predicate="name",
                        value="Unanchored Supplier",
                    ),
                ),
                mappings=(),
                warnings=(),
                evidence_refs=(),
            )

    with pytest.raises(ValueError, match="evidence"):
        SemanticCandidateBuilder(InvalidProvider()).build(supplier_fragments(), context)


def test_evidence_must_semantically_support_fact(context: BuilderContext):
    fragments = supplier_fragments()

    class InvalidProvider:
        def propose(self, fragments: list[EvidenceFragment], context: BuilderContext) -> CandidateProposal:
            del context
            ref = fragments[0].evidence_id
            return CandidateProposal(
                assertions=(
                    SemanticAssertion(
                        assertion_id="fact:unsupported",
                        assertion_type="fact",
                        subject="supplier:northstar",
                        predicate="name",
                        value="Northstar Components",
                        evidence_refs=(ref,),
                    ),
                ),
                evidence_refs=(ref,),
            )

    with pytest.raises(ValueError, match="does not support"):
        SemanticCandidateBuilder(InvalidProvider()).build(fragments, context)


def test_assumption_does_not_enter_fact_evidence_set(proposal: CandidateProposal):
    assumptions = [item for item in proposal.assertions if item.assertion_type == "assumption"]
    assert assumptions
    assert all(not item.evidence_refs for item in assumptions)
    assert all(
        item.assertion_id not in proposal.evidence_refs
        for item in assumptions
    )


def test_deterministic_provider_has_stable_ids_and_hashes(context: BuilderContext):
    provider = DeterministicCandidateProvider()
    first = SemanticCandidateBuilder(provider).build(supplier_fragments(), context)
    second = SemanticCandidateBuilder(provider).build(supplier_fragments(), context)

    assert first == second
    assert first.model_dump_json() == second.model_dump_json()
    assert [item.candidate_id for item in first.entities] == [
        item.candidate_id for item in second.entities
    ]


def test_exact_entity_key_or_name_precedes_alias():
    resolver = EntityResolver(
        canonical_entities={"supplier:acme": {"name": "Acme Industrial", "external_key": "ACME-001"}}
    )
    candidates = [
        EntityCandidate(
            candidate_id="supplier:exact",
            entity_type="supplier",
            name="Acme Industrial",
            external_key="ACME-001",
        )
    ]

    match = resolver.resolve(candidates, strategy_version="entity-resolver-v1")[0]

    assert match.canonical_entity_id == "supplier:acme"
    assert match.status == "confirmed"
    assert match.score == 1.0


def test_contracts_are_frozen_and_assertion_types_are_typed():
    assertion = SemanticAssertion(
        assertion_id="assumption:delivery",
        assertion_type="assumption",
        subject="purchase order",
        predicate="actual_delivery_date",
        value="unknown",
    )

    with pytest.raises((ValidationError, TypeError)):
        assertion.value = "changed"


def test_nested_assertion_values_are_immutable():
    assertion = SemanticAssertion(
        assertion_id="fact:delivery:metadata",
        assertion_type="fact",
        subject="purchase-order:PO-001",
        predicate="metadata",
        value={"signals": ["late", "supplier"]},
        evidence_refs=("evidence:test",),
    )

    with pytest.raises(TypeError, match="immutable"):
        assertion.value["signals"].append("unverified")
