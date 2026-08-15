"""Create a local software-delivery Shipyard Workbench seed database."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPOSITORY_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from aifde.registry.sqlite import SQLiteRegistry  # noqa: E402
from aifde.shipyard.bootstrap import (  # noqa: E402
    PROJECT_ID,
    run_workbench_gate_snapshot,
    seed_software_delivery_artifacts,
    seed_software_delivery_workspace,
)
from aifde.shipyard.identity import FakeIdentityProvider, Principal  # noqa: E402
from aifde.shipyard.service import ShipyardApplicationService  # noqa: E402


REQUIRED_GATE_IDS = frozenset({"semantic.integrity", "release.governance"})


def _decision_case_input(owner: str) -> dict[str, object]:
    return {
        "case_id": "case:software-delivery:forecast",
        "name": "预测软件需求交付风险",
        "objective": "在需求变更时预测工期并选择可行的交付方案",
        "decision_owner": owner,
        "users": ["delivery-lead"],
        "trigger": "需求发生追加或变更",
        "inputs": ["requirements", "work-items", "dependencies", "capacity"],
        "actions": ["review forecast", "select candidate plan"],
        "constraints": ["no dependency order violation", "no capacity over-allocation"],
        "kpis": ["p80 delivery coverage", "late-risk recall"],
        "baseline": "manual status meeting",
        "success_definition": "A feasible plan is selected before commitment",
        "failure_definition": "A plan is selected without explaining delay risk",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Seed a local Shipyard Workbench software-delivery database"
    )
    parser.add_argument("--database", required=True, type=Path, help="SQLite database path")
    parser.add_argument("--owner", required=True, help="Bound human owner subject")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    database = args.database.expanduser().resolve()
    database.parent.mkdir(parents=True, exist_ok=True)
    project_root = REPOSITORY_ROOT / "projects" / PROJECT_ID

    identity = FakeIdentityProvider()
    identity.bind(args.owner, "human", {"workspace-owner", "release-owner"})
    identity.bind("gate-runner", "system", {"gate-runner"})
    service = ShipyardApplicationService(
        SQLiteRegistry(database),
        identity_provider=identity,
        required_gate_ids=REQUIRED_GATE_IDS,
    )
    try:
        human = Principal(
            subject=args.owner,
            kind="human",
            roles=frozenset({"workspace-owner", "release-owner"}),
        )
        gate_runner = Principal(
            subject="gate-runner",
            kind="system",
            roles=frozenset({"gate-runner"}),
        )
        workspace = seed_software_delivery_workspace(service, project_root, args.owner)
        decision_case = service.create_decision_case(
            workspace.workspace_id,
            _decision_case_input(args.owner),
            human,
        )
        artifacts = seed_software_delivery_artifacts(
            service, workspace.workspace_id, args.owner
        )
        snapshots = run_workbench_gate_snapshot(
            service,
            workspace.workspace_id,
            [artifact.artifact_id for artifact in artifacts],
            project_root=project_root,
        )
        recorded_reviews = [
            service.record_gate_review(review, gate_runner) for review in snapshots
        ]
        result = {
            "database": str(database),
            "workspace_id": workspace.workspace_id,
            "decision_case_id": decision_case.case_id,
            "artifact_ids": [artifact.artifact_id for artifact in artifacts],
            "gate_reviews": [
                {
                    "gate_run_id": review.gate_run_id,
                    "gate_id": review.gate_id,
                    "status": review.status,
                    "stale": review.stale,
                }
                for review in recorded_reviews
            ],
            "external_connections": [],
            "production_actions_executed": False,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    finally:
        service.registry.close()


if __name__ == "__main__":
    raise SystemExit(main())
