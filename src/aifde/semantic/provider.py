"""Evidence-authorized semantic provider adapters.

The provider is deliberately a proposal boundary.  An LLM may suggest typed
terms, entities, assertions, and mappings, but it cannot introduce evidence
outside the current run or mark its own result as releasable.  The transport
is kept deliberately small so a local fake, an OpenAI-compatible endpoint, or
an enterprise model gateway can be plugged in without changing the builder
contracts.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from aifde.builder.contracts import EvidenceFragment
from aifde.builder.semantic import (
    BuilderContext,
    CandidateProposal,
    CandidateProvider,
)


class LLMTransport(Protocol):
    """Minimal structured-completion boundary for a model gateway."""

    def complete(self, **kwargs: Any) -> Mapping[str, Any] | BaseModel:
        """Return a JSON object or a validated Pydantic response."""


class SemanticProvider(Protocol):
    """Context-first interface used by orchestration and review workflows."""

    def propose(
        self, context: BuilderContext, evidence: Sequence[EvidenceFragment]
    ) -> CandidateProposal:
        """Return a non-releasable, evidence-bound candidate proposal."""


class ProviderInvocation(BaseModel):
    """Replay metadata for one model invocation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    invocation_id: str
    provider_id: str
    model_id: str
    prompt_version: str
    input_evidence_refs: tuple[str, ...]
    output_hash: str
    created_at: datetime


def _nonblank(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must not be empty")
    return value.strip()


def _canonical_hash(value: Any) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(payload).hexdigest()


class StructuredLLMProvider:
    """Turn model output into a guarded :class:`CandidateProposal`.

    ``transport.complete`` receives only the authorized evidence excerpts;
    this is an important distinction from merely putting evidence IDs into a
    prompt.  The returned object is parsed with ``extra='forbid'`` contracts,
    then all nested evidence references are checked before the proposal is
    returned to the caller.
    """

    def __init__(
        self,
        transport: LLMTransport,
        provider_id: str,
        model_id: str,
        prompt_version: str,
    ) -> None:
        self._transport = transport
        self._provider_id = _nonblank(provider_id, "provider_id")
        self._model_id = _nonblank(model_id, "model_id")
        self._prompt_version = _nonblank(prompt_version, "prompt_version")
        self._last_invocation: ProviderInvocation | None = None

    @property
    def last_invocation(self) -> ProviderInvocation | None:
        return self._last_invocation

    def propose(
        self, context: BuilderContext, evidence: Sequence[EvidenceFragment]
    ) -> CandidateProposal:
        if not isinstance(context, BuilderContext):
            raise TypeError("context must be a BuilderContext")
        fragments = tuple(evidence)
        if not fragments:
            raise ValueError("semantic provider requires at least one evidence fragment")
        if any(not isinstance(item, EvidenceFragment) for item in fragments):
            raise TypeError("evidence must contain EvidenceFragment values")

        evidence_payload = tuple(
            {
                "evidence_id": item.evidence_id,
                "source_asset_id": item.source_asset_id,
                "source_version": item.source_version,
                "locator": item.locator,
                "content": item.content,
                "normalized_content": item.normalized_content,
                "content_hash": item.content_hash,
                "source_content_hash": item.source_content_hash,
                "observed_at": item.observed_at.isoformat(),
                "available_at": item.available_at.isoformat(),
                "event_time": item.event_time.isoformat() if item.event_time else None,
                "extraction_method": item.extraction_method,
                "extraction_version": item.extraction_version,
                "confidence": item.confidence,
            }
            for item in fragments
        )
        authorized_refs = {item["evidence_id"] for item in evidence_payload}
        response = self._transport.complete(
            system_prompt=self._system_prompt(),
            user_prompt=self._user_prompt(context, evidence_payload),
            response_model=CandidateProposal,
            context=context.model_dump(mode="json"),
            evidence=evidence_payload,
        )
        try:
            proposal = (
                response
                if isinstance(response, CandidateProposal)
                else CandidateProposal.model_validate(response)
            )
        except Exception as exc:  # Pydantic ValidationError is intentionally normalized.
            raise ValueError(f"invalid structured candidate: {exc}") from exc

        referenced = self._candidate_evidence_refs(proposal)
        if not referenced.issubset(authorized_refs):
            unknown = sorted(referenced - authorized_refs)
            raise ValueError(
                "candidate references evidence outside authorized evidence: "
                + ", ".join(unknown)
            )
        if proposal.release_eligibility == "eligible":
            raise ValueError("structured provider cannot self-approve a candidate")
        if referenced and not proposal.evidence_refs:
            raise ValueError("candidate child evidence requires proposal evidence_refs")

        output_hash = _canonical_hash(proposal)
        invocation_id = (
            f"invocation:{self._provider_id}:{self._model_id}:"
            f"{output_hash[:16]}"
        )
        self._last_invocation = ProviderInvocation(
            invocation_id=invocation_id,
            provider_id=self._provider_id,
            model_id=self._model_id,
            prompt_version=self._prompt_version,
            input_evidence_refs=tuple(item["evidence_id"] for item in evidence_payload),
            output_hash=output_hash,
            created_at=datetime.now(timezone.utc),
        )
        return proposal

    def as_candidate_provider(self) -> CandidateProvider:
        """Expose the legacy builder ordering through a safe adapter."""

        return CandidateProviderAdapter(self)

    @staticmethod
    def _candidate_evidence_refs(proposal: CandidateProposal) -> set[str]:
        refs = set(proposal.evidence_refs)
        for item in (*proposal.terms, *proposal.entities, *proposal.mappings):
            refs.update(getattr(item, "source_evidence_refs", ()))
        for item in proposal.assertions:
            refs.update(item.evidence_refs)
        return refs

    def _system_prompt(self) -> str:
        return (
            "Produce only a typed CandidateProposal. Use only the supplied evidence. "
            "Keep unsupported claims out of facts and mappings; mark uncertainty as "
            "warnings, assumptions, or inferences. release_eligibility must remain "
            "review_required or blocked. The model cannot approve or publish output. "
            f"Prompt contract version: {self._prompt_version}."
        )

    @staticmethod
    def _user_prompt(
        context: BuilderContext, evidence: Sequence[Mapping[str, Any]]
    ) -> str:
        return json.dumps(
            {
                "context": context.model_dump(mode="json"),
                "authorized_evidence": list(evidence),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


class CandidateProviderAdapter:
    """Adapt the provider's context-first API to ``CandidateProvider``."""

    def __init__(self, provider: SemanticProvider) -> None:
        self._provider = provider

    def propose(
        self, fragments: list[EvidenceFragment], context: BuilderContext
    ) -> CandidateProposal:
        return self._provider.propose(context, fragments)


__all__ = [
    "CandidateProviderAdapter",
    "LLMTransport",
    "ProviderInvocation",
    "SemanticProvider",
    "StructuredLLMProvider",
]
