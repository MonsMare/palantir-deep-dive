from __future__ import annotations

from aifde.agents.graph import AgentExecutionOutput, AgentGraph, AgentNode
from aifde.agents.roles import AgentRole
from aifde.agents.workspace import ArtifactCandidate
from aifde.orchestration.runner import StageRunner


def test_stage_runner_can_delegate_to_governed_domain_team() -> None:
    runner = StageRunner.for_testing(project_id="project-1")
    graph = AgentGraph(
        [
            AgentNode(
                node_id="ontology",
                role=AgentRole.ONTOLOGY_ENGINEER,
                task_kind="ontology.design",
                output_kind="OntologyModel",
            )
        ]
    )

    def execute(node: AgentNode, _context: object) -> AgentExecutionOutput:
        return AgentExecutionOutput(
            candidate=ArtifactCandidate(
                artifact_id="ontology:runner",
                project_id="project-1",
                kind=node.output_kind or "OntologyModel",
                owner="ontology-engineer",
                content={"classes": ["PurchaseOrder"]},
                evidence_refs=["evidence-1"],
                producer_role=node.role,
            ),
            token_usage=1,
        )

    summary, workspace = runner.run_domain_team(graph, execute)

    assert summary.status == "succeeded"
    assert workspace.latest("ontology:runner").status == "candidate"
