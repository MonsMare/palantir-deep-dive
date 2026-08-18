from __future__ import annotations

from threading import Lock

import pytest

from aifde.agents.budget import BudgetSpec
from aifde.agents.graph import AgentExecutionOutput, AgentGraph, AgentNode, DomainAgentTeam
from aifde.agents.roles import AgentRole
from aifde.agents.workspace import ArtifactCandidate, ArtifactWorkspace


def _node(node_id: str, *, depends_on: tuple[str, ...] = (), token_budget: int = 1) -> AgentNode:
    return AgentNode(
        node_id=node_id,
        role=AgentRole.ONTOLOGY_ENGINEER,
        task_kind="ontology.design",
        depends_on=depends_on,
        output_kind="OntologyModel",
        token_budget=token_budget,
    )


def _candidate(node: AgentNode) -> ArtifactCandidate:
    return ArtifactCandidate(
        artifact_id="shared:artifact",
        project_id="project-1",
        kind=node.output_kind or "Artifact",
        owner=node.role.value,
        content={"node": node.node_id},
        evidence_refs=["evidence:1"],
        producer_role=node.role,
    )


def test_parallel_agents_cannot_overwrite_the_same_artifact() -> None:
    graph = AgentGraph(
        [
            _node("builder-a"),
            _node("builder-b"),
        ]
    )
    workspace = ArtifactWorkspace(project_id="project-1")

    def execute(node: AgentNode, _context: object) -> AgentExecutionOutput:
        return AgentExecutionOutput(candidate=_candidate(node), token_usage=1)

    summary = DomainAgentTeam(workspace=workspace, max_parallelism=2).run(graph, execute)

    assert summary.status == "partial_failure"
    assert sum(result.status == "succeeded" for result in summary.node_results.values()) == 1
    assert sum(result.status == "failed" for result in summary.node_results.values()) == 1
    assert len(workspace.history("shared:artifact")) == 1


def test_budget_exhaustion_stops_downstream_nodes_without_running_them() -> None:
    graph = AgentGraph([_node("first", token_budget=6), _node("second", token_budget=6, depends_on=("first",)), _node("third", token_budget=1, depends_on=("second",))])
    workspace = ArtifactWorkspace(project_id="project-1")
    called: list[str] = []
    lock = Lock()

    def execute(node: AgentNode, _context: object) -> AgentExecutionOutput:
        with lock:
            called.append(node.node_id)
        return AgentExecutionOutput(candidate=_candidate(node), token_usage=6)

    summary = DomainAgentTeam(
        workspace=workspace,
        budget=BudgetSpec(max_tokens=6, max_nodes=10),
    ).run(graph, execute)

    assert called == ["first"]
    assert summary.node_results["second"].status == "budget_exhausted"
    assert summary.node_results["third"].status == "blocked"
    assert summary.status == "budget_exhausted"


def test_cancelled_team_does_not_invoke_pending_agent() -> None:
    graph = AgentGraph([_node("first"), _node("second", depends_on=("first",))])
    workspace = ArtifactWorkspace(project_id="project-1")
    called: list[str] = []

    def execute(node: AgentNode, _context: object) -> AgentExecutionOutput:
        called.append(node.node_id)
        return AgentExecutionOutput(candidate=_candidate(node), token_usage=1)

    import threading

    cancel = threading.Event()
    cancel.set()
    summary = DomainAgentTeam(workspace=workspace).run(graph, execute, cancel_event=cancel)

    assert called == []
    assert all(result.status == "cancelled" for result in summary.node_results.values())


def test_stale_input_blocks_agent_before_provider_invocation() -> None:
    workspace = ArtifactWorkspace(project_id="project-1")
    committer = workspace.system_committer()
    source = ArtifactCandidate(
        artifact_id="source:stale",
        project_id="project-1",
        kind="SourceSnapshot",
        owner="data-product-engineer",
        content={"value": 1},
        evidence_refs=["evidence:1"],
        producer_role=AgentRole.DATA_PRODUCT_ENGINEER,
    )
    committer.commit(source)
    dependent = ArtifactCandidate(
        artifact_id="dependent:stale",
        project_id="project-1",
        kind="FeatureDefinition",
        owner="model-engineer",
        content={"value": 1},
        depends_on=["source:stale"],
        evidence_refs=["evidence:1"],
        producer_role=AgentRole.MODEL_ENGINEER,
    )
    committer.commit(dependent)
    committer.revise(source.model_copy(update={"version": "1.1.0", "content": {"value": 2}}), parent_version="1.0.0")

    graph = AgentGraph(
        [
            AgentNode(
                node_id="model",
                role=AgentRole.MODEL_ENGINEER,
                task_kind="model.training",
                input_artifact_ids=("dependent:stale",),
                output_kind="ModelPackage",
            )
        ]
    )
    called: list[str] = []

    def execute(node: AgentNode, _context: object) -> AgentExecutionOutput:
        called.append(node.node_id)
        return AgentExecutionOutput(candidate=_candidate(node), token_usage=1)

    summary = DomainAgentTeam(workspace=workspace).run(graph, execute)

    assert called == []
    assert summary.node_results["model"].status == "stale"
