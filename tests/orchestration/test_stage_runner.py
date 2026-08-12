"""Red tests for the evidence-bound stage runner."""

from __future__ import annotations

import pytest

from aifde.domain.stages import StageState
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
