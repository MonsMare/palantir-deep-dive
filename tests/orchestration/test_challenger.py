"""Red tests for the independent challenger adapter."""

from __future__ import annotations

from aifde.orchestration.agents import FakeChallenger
from aifde.orchestration.contracts import AgentContext, TaskContract


def test_challenger_reports_claim_without_support():
    contract = TaskContract(
        task_id="task-claim-1",
        objective="Review a claim",
        stage_id="decision.contract",
        allowed_evidence=["evidence-1"],
        required_output=["DecisionContract"],
        forbidden_assumptions=[],
        acceptance_tests=["critical claims cite evidence"],
        escalation_conditions=[],
    )
    challenger = FakeChallenger.for_testing(
        raw_evidence={"evidence-1": {"text": "source text"}},
        artifacts={
            "artifact-1": {
                "claims": [{"text": "unsupported claim", "evidence_refs": []}]
            }
        },
    )
    context = AgentContext(
        project_id="project-1",
        stage_id="decision.contract",
        evidence_snapshot_id="snapshot-1",
        artifact_ids=["artifact-1"],
        tool_gateway=challenger.tool_gateway,
    )

    report = challenger.run(contract, context)

    assert report.result == "failed"
    assert report.findings[0].code == "CLAIM_WITHOUT_SUPPORT"
    assert report.required_remediation


def test_challenger_reports_forbidden_assumption_and_missing_acceptance_test():
    contract = TaskContract(
        task_id="task-challenge-1",
        objective="Review a decision",
        stage_id="decision.contract",
        allowed_evidence=["evidence-1"],
        required_output=["DecisionContract"],
        forbidden_assumptions=["unverified market size"],
        acceptance_tests=["must validate pricing"],
        escalation_conditions=[],
    )
    challenger = FakeChallenger.for_testing(
        raw_evidence={"evidence-1": {"text": "source text"}},
        artifacts={
            "artifact-1": {
                "assumptions": ["unverified market size"],
                "acceptance_tests": [],
                "claims": [],
            }
        },
    )
    context = AgentContext(
        project_id="project-1",
        stage_id="decision.contract",
        evidence_snapshot_id="snapshot-1",
        artifact_ids=["artifact-1"],
        tool_gateway=challenger.tool_gateway,
    )

    report = challenger.run(contract, context)

    finding_codes = {finding.code for finding in report.findings}
    assert "FORBIDDEN_ASSUMPTION" in finding_codes
    assert "MISSING_ACCEPTANCE_TEST" in finding_codes
