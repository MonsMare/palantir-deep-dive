"""Runtime boundaries for versioned domain packs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from aifde.builder.contracts import EvidenceFragment, SourceSnapshot
from aifde.builder.semantic import CandidateProvider
from aifde.builder.sources import SourceRegistry
from aifde.platform.domain_pack import DomainPack


@dataclass(frozen=True)
class DomainCapture:
    """Immutable output of one domain-owned source capture stage."""

    registry: SourceRegistry
    fragments: tuple[EvidenceFragment, ...]
    snapshots: tuple[SourceSnapshot, ...]


class DomainCompiler(Protocol):
    """Compiler contract consumed by the platform Builder."""

    def compile(self, proposal, source_registry: SourceRegistry, version: str):
        """Compile a bound candidate into a traceable CompileResult."""

    def validate(self, result):
        """Re-validate a CompileResult without mutating it."""


class DomainAdapter(Protocol):
    """Domain-specific edge of an otherwise domain-neutral Builder."""

    pack: DomainPack

    @property
    def provider(self) -> CandidateProvider:
        """Return a candidate-only semantic provider."""

    @property
    def compiler(self) -> DomainCompiler:
        """Return a compiler configured by this pack."""

    def capture(self, source_paths: Sequence[str]) -> DomainCapture:
        """Capture and extract evidence without publishing business facts."""


__all__ = ["DomainAdapter", "DomainCapture", "DomainCompiler"]
