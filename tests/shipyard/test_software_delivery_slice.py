"""Integration contract for the software-delivery Shipyard vertical slice."""

from __future__ import annotations

from pathlib import Path

import pytest

from aifde.registry.sqlite import SQLiteRegistry
from aifde.shipyard.identity import FakeIdentityProvider, Principal
from aifde.shipyard.service import ReleaseBlockedError, ShipyardApplicationService

from aifde.shipyard.bootstrap import (
    run_workbench_gate_snapshot,
    seed_software_delivery_artifacts,
    seed_software_delivery_workspace,
)


PROJECT_ROOT = Path(__file__).parents[2] / "projects" / "software-delivery-demo"
REQUIRED_GATE_IDS = frozenset({"semantic.integrity", "release.governance"})


def build_shipyard_test_runtime(tmp_path: Path) -> tuple[SQLiteRegistry, ShipyardApplicationService]:
    registry = SQLiteRegistry(tmp_path / "shipyard.db")
    identity = FakeIdentityProvider()
    identity.bind("alice", "human", {"workspace-owner", "release-owner"})
    identity.bind("agent-1", "agent", {"builder"})
    identity.bind("gate-runner", "system", {"gate-runner"})
    service = ShipyardApplicationService(
        registry,
        identity_provider=identity,
        required_gate_ids=REQUIRED_GATE_IDS,
    )
    return registry, service


def human_principal(subject: str) -> Principal:
    return Principal(
        subject=subject,
        kind="human",
        roles=frozenset({"workspace-owner", "release-owner"}),
    )


def system_principal() -> Principal:
    return Principal(
        subject="gate-runner",
        kind="system",
        roles=frozenset({"gate-runner"}),
    )


def test_software_delivery_workbench_blocks_then_allows_release(tmp_path: Path) -> None:
    registry, service = build_shipyard_test_runtime(tmp_path)
    try:
        workspace = seed_software_delivery_workspace(
            service, PROJECT_ROOT, "alice"
        )
        artifacts = seed_software_delivery_artifacts(
            service, workspace.workspace_id, "alice"
        )
        artifact_ids = [artifact.artifact_id for artifact in artifacts]

        with pytest.raises(ReleaseBlockedError):
            service.create_release_candidate(
                workspace.workspace_id,
                artifact_ids,
                [],
                human_principal("alice"),
            )

        initial_reviews = run_workbench_gate_snapshot(
            service,
            workspace.workspace_id,
            artifact_ids,
        )
        assert {review.gate_id for review in initial_reviews} == service.required_gate_ids
        assert all(review.artifact_hashes == {
            artifact.artifact_id: artifact.content_hash for artifact in artifacts
        } for review in initial_reviews)
        assert all(review.validator_version for review in initial_reviews)
        assert all(review.evidence_refs for review in initial_reviews)
        assert all(review.stale is False for review in initial_reviews)

        passed_reviews = []
        for review in initial_reviews:
            passed = review.model_copy(
                update={
                    "gate_run_id": f"{review.gate_id}:passed:1",
                    "status": "passed",
                    "stale": False,
                }
            )
            passed_reviews.append(
                service.record_gate_review(passed, system_principal())
            )

        candidate = service.create_release_candidate(
            workspace.workspace_id,
            artifact_ids,
            [review.gate_run_id for review in passed_reviews],
            human_principal("alice"),
        )
        assert candidate.status == "ready"
        assert candidate.manifest["artifact_hashes"] == {
            artifact.artifact_id: artifact.content_hash for artifact in artifacts
        }
        assert candidate.manifest["gate_run_ids"] == sorted(
            review.gate_run_id for review in passed_reviews
        )
    finally:
        registry.close()


def test_seed_registers_deterministic_typed_artifacts_with_lineage(tmp_path: Path) -> None:
    registry, service = build_shipyard_test_runtime(tmp_path)
    try:
        workspace = seed_software_delivery_workspace(
            service, PROJECT_ROOT, "alice"
        )
        artifacts = seed_software_delivery_artifacts(
            service, workspace.workspace_id, "alice"
        )

        assert [artifact.kind for artifact in artifacts] == [
            "ProjectCharter",
            "DecisionContract",
            "OntologyModel",
            "DataProduct",
            "FeatureCatalog",
            "ModelPolicy",
        ]
        assert [artifact.version for artifact in artifacts] == ["1.0.0"] * 6
        assert [artifact.producer for artifact in artifacts] == ["shipyard-seed"] * 6
        assert all(artifact.evidence_refs for artifact in artifacts)
        assert all(artifact.content_hash for artifact in artifacts)
        assert artifacts[1].depends_on == [artifacts[0].artifact_id]
        assert artifacts[2].depends_on == [artifacts[1].artifact_id]
        assert artifacts[-1].depends_on == [artifacts[-2].artifact_id]

        snapshot = service.get_workspace_snapshot(workspace.workspace_id)
        assert [artifact.artifact_id for artifact in snapshot["artifacts"]] == [
            artifact.artifact_id for artifact in artifacts
        ]
        assert [event.event_type for event in snapshot["audit_events"]].count(
            "artifact.registered"
        ) == len(artifacts)
    finally:
        registry.close()
