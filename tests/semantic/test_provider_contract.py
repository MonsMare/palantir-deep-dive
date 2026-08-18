from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any

import pytest

from aifde.builder.contracts import EvidenceFragment, SourceAsset, SourceSnapshot
from aifde.builder.semantic import BuilderContext, CandidateProposal
from aifde.semantic.provider import StructuredLLMProvider


UTC = timezone.utc


def _fragment() -> EvidenceFragment:
    asset = SourceAsset.register(
        "asset:notes",
        "fixture://notes.md",
        "markdown",
        "procurement",
        3,
        "internal",
        "policy:procurement",
        "notes-v1",
        {"format": "markdown"},
    )
    snapshot = SourceSnapshot.capture(
        asset,
        "v1",
        b"Supplier ACME is delayed.",
        datetime(2026, 8, 14, 9, tzinfo=UTC),
        datetime(2026, 8, 14, 10, tzinfo=UTC),
        "raw-v1",
    )
    return EvidenceFragment.from_snapshot(snapshot, "line:1", "Supplier ACME is delayed.")


class FakeTransport:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls: list[dict[str, Any]] = []

    def complete(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return self.payload


def _context() -> BuilderContext:
    return BuilderContext(
        project_id="semantic-test",
        domain="procurement",
        ontology_version="1.0.0",
        known_terms=("supplier", "delivery"),
    )


def test_structured_provider_only_accepts_evidence_bound_output() -> None:
    fragment = _fragment()
    transport = FakeTransport(
        {
            "evidence_refs": [fragment.evidence_id],
            "release_eligibility": "review_required",
            "proposal_version": "semantic-candidate-v1",
        }
    )
    provider = StructuredLLMProvider(
        transport=transport,
        provider_id="test-llm",
        model_id="test-model",
        prompt_version="prompt-v1",
    )

    proposal = provider.propose(_context(), [fragment])

    assert isinstance(proposal, CandidateProposal)
    assert proposal.evidence_refs == (fragment.evidence_id,)
    assert provider.last_invocation is not None
    assert transport.calls[0]["evidence"][0]["evidence_id"] == fragment.evidence_id
    assert "Supplier ACME" in transport.calls[0]["evidence"][0]["content"]


def test_structured_provider_rejects_unknown_evidence_reference() -> None:
    fragment = _fragment()
    transport = FakeTransport(
        {
            "evidence_refs": ["evidence:not-authorized"],
            "release_eligibility": "review_required",
        }
    )
    provider = StructuredLLMProvider(
        transport=transport,
        provider_id="test-llm",
        model_id="test-model",
        prompt_version="prompt-v1",
    )

    with pytest.raises(ValueError, match="outside authorized evidence"):
        provider.propose(_context(), [fragment])


def test_structured_provider_rejects_self_approved_output() -> None:
    fragment = _fragment()
    transport = FakeTransport(
        {
            "evidence_refs": [fragment.evidence_id],
            "release_eligibility": "eligible",
        }
    )
    provider = StructuredLLMProvider(
        transport=transport,
        provider_id="test-llm",
        model_id="test-model",
        prompt_version="prompt-v1",
    )

    with pytest.raises(ValueError, match="self-approve"):
        provider.propose(_context(), [fragment])


def test_structured_provider_rejects_malformed_structured_output() -> None:
    fragment = _fragment()
    transport = FakeTransport(
        {
            "evidence_refs": [fragment.evidence_id],
            "release_eligibility": "review_required",
            "unexpected": "must fail closed",
        }
    )
    provider = StructuredLLMProvider(
        transport=transport,
        provider_id="test-llm",
        model_id="test-model",
        prompt_version="prompt-v1",
    )

    with pytest.raises(ValueError, match="structured candidate"):
        provider.propose(_context(), [fragment])

