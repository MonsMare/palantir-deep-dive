from __future__ import annotations

from typing import Any

from aifde.agents.graph import AgentExecutionOutput, AgentGraph, AgentNode, DomainAgentTeam
from aifde.agents.roles import AgentRole
from aifde.agents.workspace import ArtifactCandidate, ArtifactWorkspace, WorkspaceConflictError


def _candidate(node: AgentNode, *, artifact_id: str | None = None) -> ArtifactCandidate:
    return ArtifactCandidate(
        artifact_id=artifact_id or f"{node.role.value}:artifact",
        project_id="project-1",
        kind=node.output_kind or "AgentNote",
        version="1.0.0",
        owner=f"{node.role.value}-agent",
        content={"node_id": node.node_id, "supported": True},
        evidence_refs=["evidence:1"],
        producer_role=node.role,
    )


class _Executor:
    def __init__(self) -> None:
        self.contexts: dict[str, Any] = {}

    def execute(self, node: AgentNode, context: Any) -> AgentExecutionOutput:
        self.contexts[node.node_id] = context
        return AgentExecutionOutput(candidate=_candidate(node), token_usage=1)


def test_domain_team_runs_explicit_dag_and_keeps_agent_contexts_independent() -> None:
    workspace = ArtifactWorkspace(project_id="project-1")
    executor = _Executor()
    team = DomainAgentTeam(workspace=workspace, max_parallelism=2)

    summary = team.run(AgentGraph.default_supplier_delay(), executor)

    assert summary.status == "succeeded"
    assert summary.completed_node_ids == (
        "decision-analyst",
        "workflow-analyst",
        "ontology-engineer",
        "data-product-engineer",
        "model-engineer",
        "decision-agent",
        "challenger",
        "release-agent",
    )
    assert executor.contexts["ontology-engineer"].model_route.tier.value == "large"
    assert (
        executor.contexts["challenger"].independent_context_id
        != executor.contexts["ontology-engineer"].independent_context_id
    )
    assert workspace.latest("ontology-engineer:artifact").status == "candidate"


def test_workspace_commit_is_append_only_and_conflicts_do_not_overwrite() -> None:
    workspace = ArtifactWorkspace(project_id="project-1")
    committer = workspace.system_committer()
    candidate = ArtifactCandidate(
        artifact_id="ontology:1",
        project_id="project-1",
        kind="OntologyModel",
        version="1.0.0",
        owner="ontology-engineer",
        content={"classes": ["PurchaseOrder"]},
        evidence_refs=["evidence:1"],
        producer_role=AgentRole.ONTOLOGY_ENGINEER,
    )

    first = committer.commit(candidate)
    assert first.status == "candidate"
    try:
        committer.commit(candidate)
    except WorkspaceConflictError:
        pass
    else:
        raise AssertionError("a second write must not overwrite an existing artifact")
    assert workspace.latest("ontology:1").content == {"classes": ["PurchaseOrder"]}
    assert len(workspace.history("ontology:1")) == 1


def test_upstream_revision_marks_dependent_artifacts_stale() -> None:
    workspace = ArtifactWorkspace(project_id="project-1")
    committer = workspace.system_committer()
    source = ArtifactCandidate(
        artifact_id="source:1",
        project_id="project-1",
        kind="SourceSnapshot",
        version="1.0.0",
        owner="data-product-engineer",
        content={"rows": 1},
        evidence_refs=["evidence:1"],
        producer_role=AgentRole.DATA_PRODUCT_ENGINEER,
    )
    committer.commit(source)
    feature = ArtifactCandidate(
        artifact_id="feature:1",
        project_id="project-1",
        kind="FeatureDefinition",
        version="1.0.0",
        owner="model-engineer",
        content={"expression": "rows"},
        depends_on=["source:1"],
        evidence_refs=["evidence:1"],
        producer_role=AgentRole.MODEL_ENGINEER,
    )
    committer.commit(feature)

    revised = source.model_copy(update={"version": "1.1.0", "content": {"rows": 2}})
    committer.revise(revised, parent_version="1.0.0")

    assert workspace.latest("feature:1").status == "stale"
    assert workspace.latest("feature:1").dependency_hash != workspace.dependency_hash(["source:1"])
