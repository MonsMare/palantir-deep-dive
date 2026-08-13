"""Repository contracts for immutable artifacts and captured evidence."""

from __future__ import annotations

from typing import Protocol

from aifde.domain.artifacts import Artifact
from aifde.domain.evidence import Evidence


class ArtifactRepository(Protocol):
    """Persist and retrieve append-only artifact versions."""

    def put(self, artifact: Artifact) -> Artifact:
        """Store a new artifact version without changing an existing version."""

    def get(
        self, project_id: str, artifact_id: str, version: str | None = None
    ) -> Artifact:
        """Return a specific version or the latest version when omitted."""

    def list_versions(self, project_id: str, artifact_id: str) -> list[Artifact]:
        """Return all versions in ascending version order."""


class EvidenceRepository(Protocol):
    """Persist captured evidence and its immutable original bytes."""

    def put(self, evidence: Evidence, content: bytes) -> Evidence:
        """Store evidence with a hash computed from its original bytes."""

    def get(self, evidence_id: str) -> Evidence:
        """Return evidence metadata after verifying its stored bytes hash."""

    def read_content(self, evidence_id: str) -> bytes:
        """Return original evidence bytes after verifying their hash."""


class RegistryTransaction(Protocol):
    """An explicit transaction spanning immutable repository writes."""

    artifacts: ArtifactRepository
    evidence: EvidenceRepository

    def commit(self) -> None:
        """Atomically make all writes in this transaction durable."""

    def rollback(self) -> None:
        """Discard all writes in this transaction."""
