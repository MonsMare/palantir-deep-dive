"""HTTP contract tests for the stage and stage-run routes."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from aifde.api.app import create_app
from aifde.domain.stages import StageRun, StageState
from aifde.orchestration.contracts import TaskContract
from aifde.orchestration.runner import StageRunner


pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


class FakeRegistry:
    """Minimal registry surface used by the route contract tests."""

    def __init__(self) -> None:
        self.projects = {"p1": SimpleNamespace(project_id="p1")}
        self.stages = {
            "p1": [
                SimpleNamespace(
                    stage_id="decision.contract",
                    state="domain_review",
                    blocking_gate_ids=["semantic.integrity"],
                    pending_approval_ids=["approval-1"],
                    latest_run_id="run-1",
                )
            ]
        }

    def get_project(self, project_id: str) -> SimpleNamespace:
        try:
            return self.projects[project_id]
        except KeyError as exc:
            raise KeyError(project_id) from exc

    def list_stages(self, project_id: str) -> list[SimpleNamespace]:
        self.get_project(project_id)
        return self.stages[project_id]


class FakeGateEngine:
    def can_transition(self, stage_run_id: str, target: str) -> SimpleNamespace:
        return SimpleNamespace(
            allowed=target != "approved",
            blocking_gate_ids=[] if target != "approved" else ["semantic.integrity"],
        )

    def transition(self, stage_run_id: str, target: str, actor: str) -> SimpleNamespace:
        return SimpleNamespace(
            stage_run_id=stage_run_id,
            from_state="domain_review",
            to_state=target,
            actor=actor,
            gate_run_ids=[],
        )


class FakeStageRunner:
    def create_stage_run(self, project_id: str, stage_id: str, actor: str) -> SimpleNamespace:
        return SimpleNamespace(
            stage_run_id="run-created",
            project_id=project_id,
            stage_id=stage_id,
            state="queued",
        )


@pytest.fixture
def client() -> TestClient:
    app = create_app(
        registry=FakeRegistry(),
        gate_engine=FakeGateEngine(),
        stage_runner=FakeStageRunner(),
        action_broker=SimpleNamespace(),
    )
    return TestClient(app)


def test_project_stage_list_returns_gate_status(client: TestClient) -> None:
    response = client.get("/projects/p1/stages")

    assert response.status_code == 200
    assert response.json()[0]["stage_id"] == "decision.contract"
    assert "blocking_gate_ids" in response.json()[0]
    assert response.json()[0]["pending_approval_ids"] == ["approval-1"]


def test_unknown_project_returns_not_found(client: TestClient) -> None:
    response = client.get("/projects/missing/stages")

    assert response.status_code == 404


def test_stage_run_route_delegates_to_stage_runner(client: TestClient) -> None:
    response = client.post(
        "/projects/p1/stage-runs",
        json={"stage_id": "decision.contract", "actor": "builder"},
    )

    assert response.status_code == 200
    assert response.json()["stage_run_id"] == "run-created"
    assert response.json()["project_id"] == "p1"


def test_real_stage_runner_route_adapts_to_formal_run_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = StageRunner.for_testing(project_id="p1")
    observed: list[TaskContract] = []

    def formal_run(contract: TaskContract) -> StageRun:
        observed.append(contract)
        return StageRun(
            stage_run_id="run-adapted",
            project_id="p1",
            stage_id=contract.stage_id,
            state=StageState.DRAFT,
        )

    monkeypatch.setattr(runner, "run", formal_run)
    app = create_app(
        registry=FakeRegistry(),
        gate_engine=FakeGateEngine(),
        stage_runner=runner,
        action_broker=SimpleNamespace(),
    )

    response = TestClient(app).post(
        "/projects/p1/stage-runs",
        json={"stage_id": "decision.contract", "actor": "builder"},
    )

    assert response.status_code == 200
    assert response.json()["stage_run_id"] == "run-adapted"
    assert len(observed) == 1
    contract = observed[0]
    assert isinstance(contract, TaskContract)
    assert contract.actor == "builder"
    assert contract.objective
    assert contract.allowed_evidence
    assert contract.required_output
    assert runner.stage_runs == {}


def test_transition_route_returns_409_on_hard_gate_failure(client: TestClient) -> None:
    response = client.post(
        "/stage-runs/run-1/transitions",
        json={"target": "approved", "actor": "builder"},
        headers={"X-Actor-ID": "builder"},
    )

    assert response.status_code == 409
    assert "blocking" in response.json()["detail"].lower()


def test_transition_route_rejects_missing_trusted_actor_header(client: TestClient) -> None:
    response = client.post(
        "/stage-runs/run-1/transitions",
        json={"target": "domain_review", "actor": "domain-owner-1"},
    )

    assert response.status_code == 403


def test_transition_route_rejects_actor_header_mismatch(client: TestClient) -> None:
    response = client.post(
        "/stage-runs/run-1/transitions",
        json={"target": "domain_review", "actor": "domain-owner-1"},
        headers={"X-Actor-ID": "release-owner-1"},
    )

    assert response.status_code == 403


def test_transition_route_rejects_unknown_trusted_actor(client: TestClient) -> None:
    response = client.post(
        "/stage-runs/run-1/transitions",
        json={"target": "domain_review", "actor": "attacker"},
        headers={"X-Actor-ID": "attacker"},
    )

    assert response.status_code == 403


def test_transition_route_accepts_actor_from_trusted_directory(client: TestClient) -> None:
    response = client.post(
        "/stage-runs/run-1/transitions",
        json={"target": "domain_review", "actor": "domain-owner-1"},
        headers={"X-Actor-ID": "domain-owner-1"},
    )

    assert response.status_code == 200
    assert response.json()["actor"] == "domain-owner-1"
