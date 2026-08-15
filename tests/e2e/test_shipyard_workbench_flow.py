"""End-to-end human/Agent review flow for the Shipyard Workbench."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from aifde.domain.artifacts import canonical_json_bytes
from aifde.registry.sqlite import SQLiteRegistry
from aifde.shipyard.identity import FakeIdentityProvider, Principal
from aifde.shipyard.service import ShipyardApplicationService

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


def agent_principal() -> Principal:
    return Principal(subject="agent-1", kind="agent", roles=frozenset({"builder"}))


def test_workbench_review_loop_audits_human_return_and_release_manifest(
    tmp_path: Path,
) -> None:
    registry, service = build_shipyard_test_runtime(tmp_path)
    try:
        workspace = seed_software_delivery_workspace(
            service, PROJECT_ROOT, "alice"
        )
        decision_case = service.create_decision_case(
            workspace.workspace_id,
            {
                "case_id": "case:software-delivery:forecast",
                "name": "预测软件需求交付风险",
                "objective": "在需求变更时预测工期并选择可行的交付方案",
                "decision_owner": "alice",
                "users": ["delivery-lead"],
                "trigger": "需求发生追加或变更",
                "inputs": ["requirements", "work-items", "dependencies", "capacity"],
                "actions": ["review forecast", "select candidate plan"],
                "constraints": ["no dependency order violation", "no capacity over-allocation"],
                "kpis": ["p80 delivery coverage", "late-risk recall"],
                "baseline": "manual status meeting",
                "success_definition": "A feasible plan is selected before commitment",
                "failure_definition": "A plan is selected without explaining delay risk",
            },
            human_principal("alice"),
        )
        artifacts = seed_software_delivery_artifacts(
            service, workspace.workspace_id, "alice"
        )
        artifact_ids = [artifact.artifact_id for artifact in artifacts]

        before_review = service.get_workspace_snapshot(workspace.workspace_id)
        assert before_review["decision_cases"] == [decision_case]
        assert [artifact.artifact_id for artifact in before_review["artifacts"]] == artifact_ids
        assert before_review["gate_reviews"] == []

        proposal = service.submit_agent_proposal(
            workspace.workspace_id,
            {
                "proposal_id": "proposal:software-delivery:forecast-v1",
                "task_packet_id": "task:requirements-alignment:1",
                "proposed_changes": {
                    "kind": "DecisionContract",
                    "change": "add delivery risk review before commitment",
                },
                "affected_artifact_ids": artifact_ids[:2],
                "evidence_refs": ["source:software-delivery-demo/decisions/problem.yaml"],
                "validation_results": [{"validator": "proposal.schema", "passed": True}],
                "confidence": 0.86,
                "risks": ["historical data may underrepresent exceptional work"],
                "open_questions": ["who owns the final commitment decision"],
            },
            agent_principal(),
        )
        returned = service.decide_proposal(
            proposal.proposal_id,
            "return",
            human_principal("alice"),
        )
        assert returned.status == "returned"

        initial_reviews = run_workbench_gate_snapshot(
            service,
            workspace.workspace_id,
            artifact_ids,
        )
        passed_reviews = [
            service.record_gate_review(
                review.model_copy(
                    update={
                        "gate_run_id": f"{review.gate_id}:passed:1",
                        "status": "passed",
                        "stale": False,
                    }
                ),
                system_principal(),
            )
            for review in initial_reviews
        ]
        candidate = service.create_release_candidate(
            workspace.workspace_id,
            artifact_ids,
            [review.gate_run_id for review in passed_reviews],
            human_principal("alice"),
        )

        snapshot = service.get_workspace_snapshot(workspace.workspace_id)
        audit_types = [event.event_type for event in snapshot["audit_events"]]
        assert "workspace.created" in audit_types
        assert "decision_case.created" in audit_types
        assert "proposal.submitted" in audit_types
        assert "proposal.returned" in audit_types
        assert audit_types.count("gate_review.recorded") == len(passed_reviews)
        assert "release_candidate.created" in audit_types
        assert snapshot["release_candidates"] == [candidate]
        assert candidate.manifest["artifact_hashes"] == {
            artifact.artifact_id: artifact.content_hash for artifact in artifacts
        }

        manifest_payload = {
            "artifact_hashes": {
                artifact.artifact_id: artifact.content_hash
                for artifact in sorted(artifacts, key=lambda item: item.artifact_id)
            },
            "gate_run_ids": sorted(review.gate_run_id for review in passed_reviews),
        }
        expected_manifest_digest = sha256(
            canonical_json_bytes(manifest_payload)
        ).hexdigest()
        assert candidate.manifest["manifest_digest"] == expected_manifest_digest
    finally:
        registry.close()
