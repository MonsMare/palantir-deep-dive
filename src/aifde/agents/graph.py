"""DAG execution for typed domain agents with workspace and budget gates."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from threading import Event
from typing import Any, Callable, Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .budget import BudgetExhausted, BudgetLedger, BudgetSpec
from .roles import AgentRole, ModelRoute, ModelRouter
from .workspace import (
    ArtifactCandidate,
    ArtifactWorkspace,
    WorkspaceAccessError,
    WorkspaceConflictError,
    WorkspaceReadView,
)


class AgentNode(BaseModel):
    """One independently runnable role in the domain delivery graph."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str
    role: AgentRole
    task_kind: str
    depends_on: tuple[str, ...] = Field(default_factory=tuple)
    input_artifact_ids: tuple[str, ...] = Field(default_factory=tuple)
    output_kind: str | None = None
    token_budget: int = 2_000
    max_attempts: int = 1

    @field_validator("node_id", "task_kind")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("agent node identity must not be blank")
        return value.strip()

    @field_validator("depends_on", "input_artifact_ids")
    @classmethod
    def validate_refs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not isinstance(item, str) or not item.strip() for item in value):
            raise ValueError("agent node references must be non-empty strings")
        return tuple(dict.fromkeys(value))

    @field_validator("output_kind")
    @classmethod
    def validate_output_kind(cls, value: str | None) -> str | None:
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ValueError("output_kind must not be blank")
        return value

    @field_validator("token_budget", "max_attempts")
    @classmethod
    def require_positive_int(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("agent node limits must be positive")
        return value


class AgentGraph:
    """Explicit dependency graph; missing nodes and cycles are rejected."""

    def __init__(self, nodes: list[AgentNode] | tuple[AgentNode, ...] = ()) -> None:
        self._nodes: dict[str, AgentNode] = {}
        for node in nodes:
            self.add(node)

    def add(self, node: AgentNode) -> None:
        node = AgentNode.model_validate(node)
        if node.node_id in self._nodes:
            raise ValueError(f"duplicate agent node: {node.node_id}")
        self._nodes[node.node_id] = node

    @property
    def nodes(self) -> tuple[AgentNode, ...]:
        return tuple(self._nodes.values())

    def node(self, node_id: str) -> AgentNode:
        try:
            return self._nodes[node_id]
        except KeyError as exc:
            raise KeyError(f"unknown agent node: {node_id}") from exc

    def validate(self) -> None:
        for node in self._nodes.values():
            missing = [dependency for dependency in node.depends_on if dependency not in self._nodes]
            if missing:
                raise ValueError(f"node {node.node_id} has missing dependencies: {missing}")
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node_id: str) -> None:
            if node_id in visiting:
                raise ValueError(f"agent graph contains a cycle at {node_id}")
            if node_id in visited:
                return
            visiting.add(node_id)
            for dependency in self._nodes[node_id].depends_on:
                visit(dependency)
            visiting.remove(node_id)
            visited.add(node_id)

        for node_id in self._nodes:
            visit(node_id)

    @classmethod
    def default_supplier_delay(cls) -> "AgentGraph":
        """Reference graph for a supplier-delay Ontology delivery."""

        return cls(
            [
                AgentNode(
                    node_id="decision-analyst",
                    role=AgentRole.DECISION_ANALYST,
                    task_kind="decision.contract",
                    output_kind="DecisionContract",
                ),
                AgentNode(
                    node_id="workflow-analyst",
                    role=AgentRole.WORKFLOW_ANALYST,
                    task_kind="workflow.observation",
                    depends_on=("decision-analyst",),
                    output_kind="WorkflowObservation",
                ),
                AgentNode(
                    node_id="ontology-engineer",
                    role=AgentRole.ONTOLOGY_ENGINEER,
                    task_kind="ontology.design",
                    depends_on=("workflow-analyst",),
                    output_kind="OntologyModel",
                ),
                AgentNode(
                    node_id="data-product-engineer",
                    role=AgentRole.DATA_PRODUCT_ENGINEER,
                    task_kind="data.product",
                    depends_on=("ontology-engineer",),
                    output_kind="DataProduct",
                ),
                AgentNode(
                    node_id="model-engineer",
                    role=AgentRole.MODEL_ENGINEER,
                    task_kind="model.training",
                    depends_on=("data-product-engineer",),
                    output_kind="ModelPackage",
                ),
                AgentNode(
                    node_id="decision-agent",
                    role=AgentRole.DECISION_AGENT,
                    task_kind="decision.optimization",
                    depends_on=("model-engineer",),
                    output_kind="OptimizationPlan",
                ),
                AgentNode(
                    node_id="challenger",
                    role=AgentRole.CHALLENGER,
                    task_kind="quality.challenge",
                    depends_on=("decision-agent",),
                    output_kind="ChallengeReport",
                ),
                AgentNode(
                    node_id="release-agent",
                    role=AgentRole.RELEASE_AGENT,
                    task_kind="release.validation",
                    depends_on=("challenger",),
                    output_kind="ReleaseCandidate",
                ),
            ]
        )


class AgentExecutionContext(BaseModel):
    """Read-only invocation context given to one provider call."""

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    run_id: str
    node_id: str
    role: AgentRole
    independent_context_id: str
    workspace: WorkspaceReadView
    model_route: ModelRoute
    input_artifact_ids: tuple[str, ...] = Field(default_factory=tuple)


class AgentExecutionOutput(BaseModel):
    """Typed candidate returned by an agent; never a release or Action."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate: ArtifactCandidate | None = None
    token_usage: int = 0
    findings: tuple[str, ...] = Field(default_factory=tuple)

    @field_validator("token_usage")
    @classmethod
    def require_nonnegative_usage(cls, value: int) -> int:
        if value < 0:
            raise ValueError("token_usage must be non-negative")
        return value


class NodeExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str
    status: Literal[
        "succeeded",
        "failed",
        "blocked",
        "budget_exhausted",
        "cancelled",
        "stale",
    ]
    attempts: int = 0
    artifact_id: str | None = None
    error: str | None = None
    token_usage: int = 0
    context_id: str | None = None


class AgentRunSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    status: Literal["succeeded", "partial_failure", "blocked", "budget_exhausted", "cancelled"]
    node_results: dict[str, NodeExecutionResult]
    completed_node_ids: tuple[str, ...] = Field(default_factory=tuple)


class AgentExecutor(Protocol):
    def execute(
        self, node: AgentNode, context: AgentExecutionContext
    ) -> AgentExecutionOutput: ...


ExecutorLike = AgentExecutor | Callable[[AgentNode, AgentExecutionContext], AgentExecutionOutput]


class DomainAgentTeam:
    """Run Builder/Challenger/Release roles under one guarded runtime."""

    def __init__(
        self,
        *,
        workspace: ArtifactWorkspace,
        budget: BudgetSpec | BudgetLedger | None = None,
        router: ModelRouter | None = None,
        max_parallelism: int = 4,
    ) -> None:
        if max_parallelism <= 0:
            raise ValueError("max_parallelism must be positive")
        self.workspace = workspace
        self.budget = budget if isinstance(budget, BudgetLedger) else BudgetLedger(budget)
        self.router = router or ModelRouter()
        self.max_parallelism = max_parallelism

    def run(
        self,
        graph: AgentGraph,
        executor: ExecutorLike,
        *,
        cancel_event: Event | None = None,
    ) -> AgentRunSummary:
        graph.validate()
        run_id = f"agent-run:{uuid4()}"
        results: dict[str, NodeExecutionResult] = {}
        pending = {node.node_id for node in graph.nodes}
        completed: list[str] = []
        if cancel_event is not None and cancel_event.is_set():
            for node_id in pending:
                results[node_id] = NodeExecutionResult(node_id=node_id, status="cancelled")
            return AgentRunSummary(
                run_id=run_id,
                status="cancelled",
                node_results=results,
                completed_node_ids=(),
            )

        while pending:
            if cancel_event is not None and cancel_event.is_set():
                for node_id in pending:
                    results[node_id] = NodeExecutionResult(node_id=node_id, status="cancelled")
                pending.clear()
                break

            self._mark_unrunnable(graph, pending, results)
            pending.difference_update(results)
            if not pending:
                break
            ready = [
                graph.node(node_id)
                for node_id in pending
                if all(results.get(dependency, NodeExecutionResult(node_id=dependency, status="blocked")).status == "succeeded" for dependency in graph.node(node_id).depends_on)
            ]
            if not ready:
                for node_id in pending:
                    results[node_id] = NodeExecutionResult(
                        node_id=node_id,
                        status="blocked",
                        error="DAG has no runnable node after dependency resolution",
                    )
                pending.clear()
                break
            ready.sort(key=lambda node: node.node_id)
            batch = ready[: self.max_parallelism]
            with ThreadPoolExecutor(max_workers=len(batch)) as pool:
                futures = {
                    pool.submit(self._run_node, run_id, node, executor, cancel_event): node.node_id
                    for node in batch
                }
                for future in as_completed(futures):
                    node_id = futures[future]
                    results[node_id] = future.result()
                    pending.discard(node_id)
                    if results[node_id].status == "succeeded":
                        completed.append(node_id)

        status = self._summary_status(results)
        return AgentRunSummary(
            run_id=run_id,
            status=status,
            node_results=results,
            completed_node_ids=tuple(completed),
        )

    def _run_node(
        self,
        run_id: str,
        node: AgentNode,
        executor: ExecutorLike,
        cancel_event: Event | None,
    ) -> NodeExecutionResult:
        context_id = f"{run_id}:{node.node_id}:{uuid4()}"
        for artifact_id in node.input_artifact_ids:
            try:
                input_artifact = self.workspace.latest(artifact_id)
            except KeyError as exc:
                return NodeExecutionResult(
                    node_id=node.node_id,
                    status="failed",
                    error=str(exc),
                    context_id=context_id,
                )
            if input_artifact.status == "stale":
                return NodeExecutionResult(
                    node_id=node.node_id,
                    status="stale",
                    error=f"input artifact is stale: {artifact_id}",
                    context_id=context_id,
                )
        attempts = 0
        total_tokens = 0
        while attempts < node.max_attempts:
            if cancel_event is not None and cancel_event.is_set():
                return NodeExecutionResult(
                    node_id=node.node_id,
                    status="cancelled",
                    attempts=attempts,
                    context_id=context_id,
                )
            attempts += 1
            try:
                self.budget.reserve(
                    f"{run_id}:{node.node_id}",
                    token_budget=node.token_budget,
                    retry=attempts > 1,
                )
            except BudgetExhausted as exc:
                return NodeExecutionResult(
                    node_id=node.node_id,
                    status="budget_exhausted",
                    attempts=attempts - 1,
                    error=str(exc),
                    context_id=context_id,
                )

            reservation_open = True
            output: AgentExecutionOutput | None = None
            try:
                allowed = node.input_artifact_ids or self.workspace.artifact_ids()
                context = AgentExecutionContext(
                    run_id=run_id,
                    node_id=node.node_id,
                    role=node.role,
                    independent_context_id=context_id,
                    workspace=self.workspace.authorized_view(
                        actor_id=f"{node.role.value}:{node.node_id}",
                        role=node.role,
                        allowed_artifact_ids=tuple(allowed),
                    ),
                    model_route=self.router.route(node.role, node.task_kind),
                    input_artifact_ids=tuple(node.input_artifact_ids),
                )
                output = self._invoke(executor, node, context)
                total_tokens += output.token_usage
                self.budget.complete(
                    f"{run_id}:{node.node_id}", token_usage=output.token_usage
                )
                reservation_open = False
                artifact_id: str | None = None
                if output.candidate is not None:
                    self._validate_output(node, output.candidate)
                    artifact = self.workspace.system_committer().commit(output.candidate)
                    artifact_id = artifact.artifact_id
                return NodeExecutionResult(
                    node_id=node.node_id,
                    status="succeeded",
                    attempts=attempts,
                    artifact_id=artifact_id,
                    token_usage=total_tokens,
                    context_id=context_id,
                )
            except BudgetExhausted as exc:
                if reservation_open:
                    self.budget.cancel(f"{run_id}:{node.node_id}")
                return NodeExecutionResult(
                    node_id=node.node_id,
                    status="budget_exhausted",
                    attempts=attempts,
                    error=str(exc),
                    token_usage=total_tokens,
                    context_id=context_id,
                )
            except (ValueError, KeyError, PermissionError, WorkspaceAccessError, WorkspaceConflictError) as exc:
                if reservation_open:
                    self.budget.complete(
                        f"{run_id}:{node.node_id}",
                        token_usage=output.token_usage if output is not None else 0,
                    )
                if attempts >= node.max_attempts:
                    return NodeExecutionResult(
                        node_id=node.node_id,
                        status="failed",
                        attempts=attempts,
                        error=str(exc),
                        token_usage=total_tokens,
                        context_id=context_id,
                )
            except Exception as exc:  # pragma: no cover - defensive boundary
                if reservation_open:
                    self.budget.complete(
                        f"{run_id}:{node.node_id}",
                        token_usage=output.token_usage if output is not None else 0,
                    )
                if attempts >= node.max_attempts:
                    return NodeExecutionResult(
                        node_id=node.node_id,
                        status="failed",
                        attempts=attempts,
                        error=f"unexpected agent error: {exc}",
                        token_usage=total_tokens,
                        context_id=context_id,
                    )
        return NodeExecutionResult(
            node_id=node.node_id,
            status="failed",
            attempts=attempts,
            error="agent attempts exhausted",
            token_usage=total_tokens,
            context_id=context_id,
        )

    @staticmethod
    def _invoke(
        executor: ExecutorLike,
        node: AgentNode,
        context: AgentExecutionContext,
    ) -> AgentExecutionOutput:
        output = (
            executor.execute(node, context)
            if hasattr(executor, "execute")
            else executor(node, context)  # type: ignore[misc]
        )
        return AgentExecutionOutput.model_validate(output)

    def _validate_output(self, node: AgentNode, candidate: ArtifactCandidate) -> None:
        if candidate.producer_role != node.role:
            raise PermissionError(
                f"candidate producer role {candidate.producer_role.value} does not match node {node.role.value}"
            )
        if node.output_kind is not None and candidate.kind != node.output_kind:
            raise ValueError(
                f"node {node.node_id} must produce {node.output_kind}, got {candidate.kind}"
            )
        if not candidate.evidence_refs:
            raise ValueError("agent candidate must include evidence references")

    @staticmethod
    def _mark_unrunnable(
        graph: AgentGraph,
        pending: set[str],
        results: dict[str, NodeExecutionResult],
    ) -> None:
        for node_id in tuple(pending):
            node = graph.node(node_id)
            dependency_results = [results.get(dependency) for dependency in node.depends_on]
            if any(
                result is not None
                and result.status
                in {"failed", "blocked", "budget_exhausted", "cancelled", "stale"}
                for result in dependency_results
            ):
                results[node_id] = NodeExecutionResult(
                    node_id=node_id,
                    status="blocked",
                    error="upstream agent node did not produce an approved candidate",
                )

    @staticmethod
    def _summary_status(
        results: dict[str, NodeExecutionResult],
    ) -> Literal["succeeded", "partial_failure", "blocked", "budget_exhausted", "cancelled"]:
        statuses = {result.status for result in results.values()}
        if statuses and statuses <= {"cancelled"}:
            return "cancelled"
        if "budget_exhausted" in statuses:
            return "budget_exhausted"
        if statuses and statuses <= {"blocked", "stale"}:
            return "blocked"
        if "failed" in statuses or "blocked" in statuses or "stale" in statuses:
            return "partial_failure"
        return "succeeded"


__all__ = [
    "AgentExecutionContext",
    "AgentExecutionOutput",
    "AgentGraph",
    "AgentNode",
    "AgentRunSummary",
    "DomainAgentTeam",
    "NodeExecutionResult",
]
