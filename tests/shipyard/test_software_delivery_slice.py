"""Integration contract for the software-delivery Shipyard vertical slice."""

from __future__ import annotations

from pathlib import Path

import pytest

from aifde.registry.sqlite import SQLiteRegistry
from aifde.shipyard import evaluator as evaluator_module
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
        assert all(review.status == "passed" for review in initial_reviews)
        assert all(review.artifact_versions == {
            artifact.artifact_id: artifact.version for artifact in artifacts
        } for review in initial_reviews)
        assert all(review.source_snapshot_id for review in initial_reviews)
        assert all(review.source_snapshot_hash for review in initial_reviews)
        assert all(review.input_snapshot_hash for review in initial_reviews)
        assert all(review.definition_fingerprint for review in initial_reviews)
        assert all(review.artifact_hashes == {
            artifact.artifact_id: artifact.content_hash for artifact in artifacts
        } for review in initial_reviews)
        assert all(review.validator_version for review in initial_reviews)
        assert all(review.evidence_refs for review in initial_reviews)
        assert all(review.outcome_attestation for review in initial_reviews)
        assert all(review.stale is False for review in initial_reviews)

        passed_reviews = [
            service.record_gate_review(review, system_principal())
            for review in initial_reviews
        ]

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


@pytest.mark.parametrize(
    ("mutation", "expected_message"),
    [
        ({"validator_version": "obsolete-validator-v0"}, "validator"),
        ({"definition_fingerprint": "0" * 64}, "definition fingerprint"),
        ({"evidence_refs": []}, "evidence"),
        ({"stale": True}, "stale"),
    ],
)
def test_untrusted_gate_claim_cannot_make_release_candidate(
    tmp_path: Path,
    mutation: dict[str, object],
    expected_message: str,
) -> None:
    registry, service = build_shipyard_test_runtime(tmp_path)
    try:
        workspace = seed_software_delivery_workspace(service, PROJECT_ROOT, "alice")
        artifacts = seed_software_delivery_artifacts(
            service, workspace.workspace_id, "alice"
        )
        artifact_ids = [artifact.artifact_id for artifact in artifacts]
        reviews = run_workbench_gate_snapshot(
            service, workspace.workspace_id, artifact_ids
        )
        tampered_reviews = [
            review.model_copy(update=mutation)
            if review.gate_id == sorted(service.required_gate_ids)[0]
            else review
            for review in reviews
        ]
        target_gate_id = sorted(service.required_gate_ids)[0]
        for review in tampered_reviews:
            if review.gate_id == target_gate_id:
                with pytest.raises(ReleaseBlockedError, match=expected_message):
                    service.record_gate_review(review, system_principal())
            else:
                service.record_gate_review(review, system_principal())

        with pytest.raises(ReleaseBlockedError, match="missing Gate Review"):
            service.create_release_candidate(
                workspace.workspace_id,
                artifact_ids,
                [review.gate_run_id for review in tampered_reviews],
                human_principal("alice"),
            )
    finally:
        registry.close()


def test_registered_artifact_source_mismatch_blocks_snapshot_and_release(
    tmp_path: Path,
) -> None:
    registry, service = build_shipyard_test_runtime(tmp_path)
    try:
        workspace = seed_software_delivery_workspace(service, PROJECT_ROOT, "alice")
        artifacts = seed_software_delivery_artifacts(
            service, workspace.workspace_id, "alice"
        )
        tampered = artifacts[2].model_copy(
            update={
                "version": "2.0.0",
                "metadata": {
                    **artifacts[2].metadata,
                    "source_sha256": "0" * 64,
                },
            }
        )
        service.register_artifact(workspace.workspace_id, tampered, human_principal("alice"))
        artifact_ids = [artifact.artifact_id for artifact in artifacts]

        blocked_reviews = run_workbench_gate_snapshot(
            service, workspace.workspace_id, artifact_ids
        )
        assert all(review.status == "blocked" for review in blocked_reviews)
        assert all(review.stale for review in blocked_reviews)
        assert any("source" in violation for review in blocked_reviews for violation in review.violations)

        for review in blocked_reviews:
            service.record_gate_review(review, system_principal())
        promoted_reviews = [
            review.model_copy(
                update={
                    "gate_run_id": f"{review.gate_run_id}:promoted",
                    "status": "passed",
                    "stale": False,
                }
            )
            for review in blocked_reviews
        ]
        for review in promoted_reviews:
            with pytest.raises(ReleaseBlockedError, match="source snapshot"):
                service.record_gate_review(review, system_principal())

        with pytest.raises(ReleaseBlockedError):
            service.create_release_candidate(
                workspace.workspace_id,
                artifact_ids,
                [review.gate_run_id for review in blocked_reviews],
                human_principal("alice"),
            )
    finally:
        registry.close()


def test_fixed_artifact_source_mapping_cannot_be_repointed_to_another_legal_asset(
    tmp_path: Path,
) -> None:
    registry, service = build_shipyard_test_runtime(tmp_path)
    try:
        workspace = seed_software_delivery_workspace(service, PROJECT_ROOT, "alice")
        artifacts = seed_software_delivery_artifacts(
            service, workspace.workspace_id, "alice"
        )
        repointed = artifacts[2].model_copy(
            update={
                "version": "2.0.0",
                "content": artifacts[0].content,
                "evidence_refs": artifacts[0].evidence_refs,
                "metadata": artifacts[0].metadata,
            }
        )
        service.register_artifact(
            workspace.workspace_id,
            repointed,
            human_principal("alice"),
        )

        reviews = run_workbench_gate_snapshot(
            service,
            workspace.workspace_id,
            [artifact.artifact_id for artifact in artifacts],
        )
        assert all(review.status == "blocked" for review in reviews)
        assert all(review.stale for review in reviews)
        assert any(
            "expected source" in violation or "mapping" in violation
            for review in reviews
            for violation in review.violations
        )
    finally:
        registry.close()


def test_artifact_semantic_content_error_blocks_gate_snapshot(
    tmp_path: Path,
) -> None:
    registry, service = build_shipyard_test_runtime(tmp_path)
    try:
        workspace = seed_software_delivery_workspace(service, PROJECT_ROOT, "alice")
        artifacts = seed_software_delivery_artifacts(
            service, workspace.workspace_id, "alice"
        )
        invalid_ontology = artifacts[2].model_copy(
            update={
                "version": "2.0.0",
                "content": {
                    "source_ref": artifacts[2].content["source_ref"],
                    "format": "turtle",
                    "document": "not a Turtle ontology",
                },
            }
        )
        service.register_artifact(
            workspace.workspace_id,
            invalid_ontology,
            human_principal("alice"),
        )

        reviews = run_workbench_gate_snapshot(
            service,
            workspace.workspace_id,
            [artifact.artifact_id for artifact in artifacts],
        )
        assert all(review.status == "blocked" for review in reviews)
        assert all(review.stale for review in reviews)
        assert any(
            "semantic" in violation.lower()
            for review in reviews
            for violation in review.violations
        )
    finally:
        registry.close()


def test_evaluator_evidence_covers_each_registered_artifact(
    tmp_path: Path,
) -> None:
    registry, service = build_shipyard_test_runtime(tmp_path)
    try:
        workspace = seed_software_delivery_workspace(service, PROJECT_ROOT, "alice")
        artifacts = seed_software_delivery_artifacts(
            service, workspace.workspace_id, "alice"
        )
        reviews = run_workbench_gate_snapshot(
            service,
            workspace.workspace_id,
            [artifact.artifact_id for artifact in artifacts],
        )
        assert all(review.status == "passed" for review in reviews)
        for artifact in artifacts:
            prefix = f"artifact-evaluator:{artifact.artifact_id}:"
            assert all(
                any(reference.startswith(prefix) for reference in review.evidence_refs)
                for review in reviews
            )
    finally:
        registry.close()


@pytest.mark.parametrize(
    "mutation",
    [
        {"status": "passed"},
        {"violations": []},
        {"stale": False},
        {"gate_run_id": "forged-gate-run"},
        {"outcome_attestation": "0" * 64},
    ],
)
def test_blocked_evaluator_outcome_cannot_be_rewritten(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: dict[str, object],
) -> None:
    monkeypatch.setattr(
        evaluator_module,
        "run_sandbox_pipeline",
        lambda _root: evaluator_module.SandboxPipelineReport(
            stage_states={},
            evidence_refs=["pipeline:fixture:blocked"],
        ),
    )
    registry, service = build_shipyard_test_runtime(tmp_path)
    try:
        workspace = seed_software_delivery_workspace(service, PROJECT_ROOT, "alice")
        artifacts = seed_software_delivery_artifacts(
            service, workspace.workspace_id, "alice"
        )
        reviews = run_workbench_gate_snapshot(
            service,
            workspace.workspace_id,
            [artifact.artifact_id for artifact in artifacts],
        )
        assert all(review.status == "blocked" for review in reviews)
        target = reviews[0].model_copy(update=mutation)

        with pytest.raises(ReleaseBlockedError, match="attestation"):
            service.record_gate_review(target, system_principal())
    finally:
        registry.close()


def test_gate_review_run_id_must_bind_to_current_evaluator_input(
    tmp_path: Path,
) -> None:
    registry, service = build_shipyard_test_runtime(tmp_path)
    try:
        workspace = seed_software_delivery_workspace(service, PROJECT_ROOT, "alice")
        artifacts = seed_software_delivery_artifacts(
            service, workspace.workspace_id, "alice"
        )
        artifact_ids = [artifact.artifact_id for artifact in artifacts]
        reviews = run_workbench_gate_snapshot(
            service, workspace.workspace_id, artifact_ids
        )
        target_gate_id = sorted(service.required_gate_ids)[0]
        forged_reviews = [
            review.model_copy(update={"gate_run_id": "forged-gate-run"})
            if review.gate_id == target_gate_id
            else review
            for review in reviews
        ]
        for review in forged_reviews:
            if review.gate_id == target_gate_id:
                with pytest.raises(ReleaseBlockedError, match="attestation"):
                    service.record_gate_review(review, system_principal())
            else:
                service.record_gate_review(review, system_principal())
    finally:
        registry.close()


def test_gate_snapshot_cannot_switch_to_another_project_root(tmp_path: Path) -> None:
    registry, service = build_shipyard_test_runtime(tmp_path)
    try:
        workspace = seed_software_delivery_workspace(service, PROJECT_ROOT, "alice")
        artifacts = seed_software_delivery_artifacts(
            service, workspace.workspace_id, "alice"
        )
        reviews = run_workbench_gate_snapshot(
            service,
            workspace.workspace_id,
            [artifact.artifact_id for artifact in artifacts],
            project_root=tmp_path / "different-project-root",
        )
        assert all(review.status == "blocked" for review in reviews)
        assert all(review.stale for review in reviews)
        assert any(
            "source root" in violation
            for review in reviews
            for violation in review.violations
        )
    finally:
        registry.close()


def test_missing_registered_artifact_produces_blocked_stale_snapshot(
    tmp_path: Path,
) -> None:
    registry, service = build_shipyard_test_runtime(tmp_path)
    try:
        workspace = seed_software_delivery_workspace(service, PROJECT_ROOT, "alice")
        artifacts = seed_software_delivery_artifacts(
            service, workspace.workspace_id, "alice"
        )
        artifact_ids = [artifact.artifact_id for artifact in artifacts]
        reviews = run_workbench_gate_snapshot(
            service,
            workspace.workspace_id,
            [*artifact_ids, "artifact:software-delivery-demo:missing"],
        )
        assert all(review.status == "blocked" for review in reviews)
        assert all(review.stale for review in reviews)
        assert any(
            "six seeded Artifacts" in violation
            for review in reviews
            for violation in review.violations
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

        snapshot = service.get_workspace_snapshot(
            workspace.workspace_id, human_principal("alice")
        )
        assert [artifact.artifact_id for artifact in snapshot["artifacts"]] == [
            artifact.artifact_id for artifact in artifacts
        ]
        assert [event.event_type for event in snapshot["audit_events"]].count(
            "artifact.registered"
        ) == len(artifacts)
    finally:
        registry.close()
