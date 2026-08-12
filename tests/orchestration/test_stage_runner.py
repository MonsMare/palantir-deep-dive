"""Red tests for the evidence-bound stage runner."""

from __future__ import annotations

import pytest

from aifde.domain.stages import StageRun, StageState
from aifde.orchestration.contracts import TaskContract
from aifde.orchestration.runner import StageRunner


def test_stage_runner_persists_evidence_bound_builder_output():
    contract = TaskContract(
        task_id="task-decision-1",
        objective="Produce a decision contract",
        stage_id="decision.contract",
        allowed_evidence=["evidence-1"],
        required_output=["DecisionContract"],
        forbidden_assumptions=["unverified market size"],
        acceptance_tests=["critical claims cite evidence"],
        escalation_conditions=["source conflict"],
    )
    runner = StageRunner.for_testing()

    run = runner.run(contract)

    assert run.output_artifact_ids
    assert run.evidence_refs
    assert run.open_questions
    assert run.state in {StageState.CHALLENGING, StageState.REMEDIATION, StageState.BLOCKED}


def test_stage_runner_blocks_contract_without_allowed_evidence():
    contract = TaskContract(
        task_id="task-without-evidence",
        objective="Produce a decision contract",
        stage_id="decision.contract",
        allowed_evidence=[],
        required_output=["DecisionContract"],
        forbidden_assumptions=[],
        acceptance_tests=["critical claims cite evidence"],
        escalation_conditions=[],
    )
    runner = StageRunner.for_testing()

    run = runner.run(contract)

    assert run.state == StageState.BLOCKED
    assert run.blocking_reasons
    assert "evidence" in run.blocking_reasons[0].lower()


def test_stage_runner_delegates_requested_transition_to_gate_engine():
    contract = TaskContract(
        task_id="task-transition-1",
        objective="Produce a decision contract",
        stage_id="decision.contract",
        allowed_evidence=["evidence-1"],
        required_output=["DecisionContract"],
        forbidden_assumptions=[],
        acceptance_tests=["critical claims cite evidence"],
        escalation_conditions=[],
    )
    runner = StageRunner.for_testing()
    run = runner.run(contract)

    transition = runner.request_transition(
        run.stage_run_id, StageState.APPROVED, actor="builder-1"
    )

    assert transition.stage_run_id == run.stage_run_id
    assert transition.to_state != StageState.APPROVED


@pytest.mark.parametrize("method_name", ["run", "challenge", "request_transition"])
def test_stage_runner_api_is_present(method_name: str):
    assert hasattr(StageRunner, method_name)


def test_stage_runner_api_adapter_delegates_to_formal_run(monkeypatch: pytest.MonkeyPatch):
    runner = StageRunner.for_testing(project_id="project-1")
    observed: list[TaskContract] = []

    def formal_run(contract: TaskContract) -> StageRun:
        observed.append(contract)
        return StageRun(
            stage_run_id="api-run-1",
            project_id="project-1",
            stage_id=contract.stage_id,
        )

    monkeypatch.setattr(runner, "run", formal_run)

    run = runner.create_stage_run(
        project_id="project-1", stage_id="decision.contract", actor="builder"
    )

    assert run.stage_run_id == "api-run-1"
    assert len(observed) == 1
    assert observed[0].actor == "builder"
    assert observed[0].objective
    assert observed[0].allowed_evidence
    assert observed[0].required_output
    assert runner.stage_runs == {}


def test_stage_runner_records_api_actor_on_real_run():
    runner = StageRunner.for_testing(project_id="project-1")

    run = runner.create_stage_run(
        project_id="project-1", stage_id="decision.contract", actor="builder"
    )

    assert run.project_id == "project-1"
    assert run.stage_id == "decision.contract"
    assert run.actor == "builder"
