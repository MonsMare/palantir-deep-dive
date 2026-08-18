"""Deterministic orchestration agents and their test-only gateway tools."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from aifde.agents.graph import AgentExecutionContext, AgentExecutionOutput, AgentNode
from aifde.agents.roles import AgentRole
from aifde.domain.artifacts import Artifact
from aifde.policy.capabilities import Capability, PolicyEngine, ToolContext
from aifde.policy.gateway import ToolGateway
from aifde.tools.protocol import ToolResult

from .contracts import (
    AgentContext,
    AgentProposal,
    ChallengeReport,
    Finding,
    TaskContract,
)


class BuilderAgent(Protocol):
    """Agent that may only propose artifacts."""

    def run(self, contract: TaskContract, context: AgentContext) -> AgentProposal:
        """Return a typed proposal without mutating stage state."""


class ChallengerAgent(Protocol):
    """Agent that independently validates proposed artifacts."""

    def run(self, contract: TaskContract, context: AgentContext) -> ChallengeReport:
        """Return a typed challenge report."""


class RoutedDomainAgentExecutor:
    """Route typed domain roles to isolated provider handlers.

    Handlers return ``AgentExecutionOutput`` and therefore can only submit a
    candidate.  The workspace commit, review, release, and Action boundaries
    remain owned by ``DomainAgentTeam`` and the platform gates.
    """

    def __init__(
        self,
        handlers: Mapping[
            AgentRole | str,
            Callable[[AgentNode, AgentExecutionContext], AgentExecutionOutput],
        ],
    ) -> None:
        self._handlers = {
            role if isinstance(role, AgentRole) else AgentRole(role): handler
            for role, handler in handlers.items()
        }

    def execute(
        self, node: AgentNode, context: AgentExecutionContext
    ) -> AgentExecutionOutput:
        try:
            handler = self._handlers[node.role]
        except KeyError as exc:
            raise PermissionError(f"no provider handler registered for {node.role.value}") from exc
        return AgentExecutionOutput.model_validate(handler(node, context))


@dataclass
class _ProposeArtifactTool:
    tool_id: str = "create_artifact"
    required_capabilities: frozenset[Capability] = frozenset({Capability.PROPOSE})
    allowed_stage_ids: frozenset[str] = PolicyEngine.KNOWN_STAGE_IDS

    def call(self, context: ToolContext, payload: dict[str, Any]) -> ToolResult:
        kind = _required_text(payload, "kind")
        task_id = _required_text(payload, "task_id")
        objective = _required_text(payload, "objective")
        artifact_id = str(payload.get("artifact_id") or _artifact_id(task_id, kind))
        evidence_refs = _strings(payload.get("evidence_refs", []))
        assumptions = _strings(payload.get("assumptions", []))
        acceptance_tests = _strings(payload.get("acceptance_tests", []))
        open_questions = _strings(payload.get("open_questions", []))
        warnings = _strings(payload.get("warnings", []))
        claims = _json_list(payload.get("claims", []))
        content: dict[str, Any] = {
            "objective": objective,
            "claims": claims,
            "assumptions": assumptions,
            "acceptance_tests": acceptance_tests,
            "open_questions": open_questions,
            "warnings": warnings,
        }
        artifact = Artifact.build(
            artifact_id=artifact_id,
            project_id=context.project_id,
            kind=kind,
            owner=context.actor_id,
            content=content,
            evidence_refs=evidence_refs,
            metadata={"task_id": task_id, "stage_id": context.stage_id},
        )
        artifact_payload = artifact.model_dump(mode="json")
        return ToolResult(
            status="proposed",
            artifact_ids=[artifact.artifact_id],
            evidence_refs=evidence_refs,
            payload={
                "artifact": artifact_payload,
                "open_questions": open_questions,
                "assumptions": assumptions,
                "warnings": warnings,
            },
        )


@dataclass
class _ReadEvidenceTool:
    raw_evidence: Mapping[str, Any]
    tool_id: str = "read_evidence"
    required_capabilities: frozenset[Capability] = frozenset({Capability.READ})
    allowed_stage_ids: frozenset[str] = PolicyEngine.KNOWN_STAGE_IDS

    def call(self, _context: ToolContext, payload: dict[str, Any]) -> ToolResult:
        evidence_id = _required_text(payload, "evidence_id")
        if evidence_id not in self.raw_evidence:
            raise KeyError(f"unknown evidence: {evidence_id}")
        return ToolResult(
            status="read",
            evidence_refs=[evidence_id],
            payload={
                "evidence_id": evidence_id,
                "evidence": _jsonable(self.raw_evidence[evidence_id]),
            },
        )


@dataclass
class _ReadArtifactTool:
    artifacts: Mapping[str, Any]
    tool_id: str = "read_artifact"
    required_capabilities: frozenset[Capability] = frozenset({Capability.READ})
    allowed_stage_ids: frozenset[str] = PolicyEngine.KNOWN_STAGE_IDS

    def call(self, _context: ToolContext, payload: dict[str, Any]) -> ToolResult:
        artifact_id = _required_text(payload, "artifact_id")
        if artifact_id not in self.artifacts:
            raise KeyError(f"unknown artifact: {artifact_id}")
        return ToolResult(
            status="read",
            artifact_ids=[artifact_id],
            payload={
                "artifact_id": artifact_id,
                "artifact": _jsonable(self.artifacts[artifact_id]),
            },
        )


class FakeBuilder:
    """A deterministic Builder that can only create typed proposals."""

    actor_id = "builder-1"

    @classmethod
    def for_testing(cls, *, tool_gateway: ToolGateway | None = None) -> FakeBuilder:
        return cls(tool_gateway=tool_gateway)

    def __init__(self, *, tool_gateway: ToolGateway | None = None) -> None:
        self.tool_gateway = tool_gateway or ToolGateway([_ProposeArtifactTool()])

    def run(self, contract: TaskContract, context: AgentContext) -> AgentProposal:
        output_kind = contract.required_output[0] if contract.required_output else "Artifact"
        evidence_refs = list(dict.fromkeys(contract.allowed_evidence))
        open_questions = [
            f"Confirm acceptance evidence for {contract.objective}.",
        ]
        assumptions = list(contract.forbidden_assumptions)
        warnings = [
            f"Forbidden assumption requires remediation: {item}"
            for item in contract.forbidden_assumptions
        ]
        claims = [
            {
                "text": f"{contract.objective} is supported by bounded evidence.",
                "evidence_refs": evidence_refs[:1],
            }
        ]
        builder_context = context.tool_gateway.issue_context(
            actor_id=self.actor_id,
            project_id=context.project_id,
            stage_id=context.stage_id,
            artifact_ids=context.artifact_ids,
            capability=Capability.PROPOSE,
            request_id=f"{contract.task_id}-builder-propose",
        )
        result = context.tool_gateway.call(
            "create_artifact",
            builder_context,
            {
                "task_id": contract.task_id,
                "kind": output_kind,
                "artifact_id": _artifact_id(contract.task_id, output_kind),
                "objective": contract.objective,
                "evidence_refs": evidence_refs,
                "assumptions": assumptions,
                # The fake builder deliberately leaves acceptance tests unmapped
                # so the independent challenger can drive remediation.
                "acceptance_tests": [],
                "open_questions": open_questions,
                "warnings": warnings,
                "claims": claims,
            },
        )
        payload = dict(result.payload)
        return AgentProposal(
            artifact_ids=list(result.artifact_ids),
            evidence_refs=list(result.evidence_refs),
            open_questions=_strings(payload.get("open_questions", open_questions)),
            assumptions=_strings(payload.get("assumptions", assumptions)),
            warnings=_strings(payload.get("warnings", warnings)),
            artifact_payloads=[dict(payload["artifact"])],
        )


class FakeChallenger:
    """Independent deterministic challenger that reads raw evidence itself."""

    actor_id = "challenger-1"

    @classmethod
    def for_testing(
        cls,
        *,
        raw_evidence: Mapping[str, Any] | None = None,
        artifacts: Mapping[str, Any] | None = None,
        tool_gateway: ToolGateway | None = None,
    ) -> FakeChallenger:
        return cls(
            raw_evidence=raw_evidence,
            artifacts=artifacts,
            tool_gateway=tool_gateway,
        )

    def __init__(
        self,
        *,
        raw_evidence: Mapping[str, Any] | None = None,
        artifacts: Mapping[str, Any] | None = None,
        tool_gateway: ToolGateway | None = None,
    ) -> None:
        self.raw_evidence = raw_evidence if raw_evidence is not None else {}
        self.artifacts = artifacts if artifacts is not None else {}
        self.tool_gateway = tool_gateway or ToolGateway(
            [
                _ReadEvidenceTool(self.raw_evidence),
                _ReadArtifactTool(self.artifacts),
            ]
        )

    def run(self, contract: TaskContract, context: AgentContext) -> ChallengeReport:
        read_context = context.tool_gateway.issue_context(
            actor_id=self.actor_id,
            project_id=context.project_id,
            stage_id=context.stage_id,
            artifact_ids=context.artifact_ids,
            capability=Capability.READ,
            request_id=f"{contract.task_id}-challenger-read",
        )
        raw_evidence = self._read_allowed_evidence(
            contract,
            context.tool_gateway,
            read_context,
        )
        findings: list[Finding] = []
        observed_evidence_refs: list[str] = []
        for artifact_id in context.artifact_ids:
            artifact = self._read_artifact(context.tool_gateway, read_context, artifact_id)
            artifact_body = _artifact_body(artifact)
            observed_evidence_refs.extend(_strings(artifact.get("evidence_refs", [])))
            findings.extend(
                _claim_support_findings(
                    artifact_id,
                    artifact_body,
                    allowed_evidence=contract.allowed_evidence,
                    raw_evidence=raw_evidence,
                )
            )
            findings.extend(
                _forbidden_assumption_findings(
                    artifact_id,
                    artifact_body,
                    contract.forbidden_assumptions,
                )
            )
            findings.extend(
                _missing_acceptance_test_findings(
                    artifact_id,
                    artifact_body,
                    contract.acceptance_tests,
                )
            )

        remediation = [_remediation_for(finding) for finding in findings]
        evidence_refs = list(dict.fromkeys([*raw_evidence, *observed_evidence_refs]))
        return ChallengeReport(
            result="failed" if findings else "passed",
            findings=findings,
            evidence_refs=evidence_refs,
            required_remediation=list(dict.fromkeys(remediation)),
        )

    def _read_allowed_evidence(
        self,
        contract: TaskContract,
        gateway: ToolGateway,
        read_context: ToolContext,
    ) -> dict[str, Any]:
        raw_evidence: dict[str, Any] = {}
        for evidence_id in contract.allowed_evidence:
            try:
                result = gateway.call(
                    "read_evidence",
                    read_context,
                    {"evidence_id": evidence_id},
                )
            except KeyError:
                continue
            raw_evidence[evidence_id] = result.payload["evidence"]
        return raw_evidence

    def _read_artifact(
        self,
        gateway: ToolGateway,
        read_context: ToolContext,
        artifact_id: str,
    ) -> dict[str, Any]:
        result = gateway.call(
            "read_artifact",
            read_context,
            {"artifact_id": artifact_id},
        )
        return dict(result.payload["artifact"])


def _claim_support_findings(
    artifact_id: str,
    artifact_body: Mapping[str, Any],
    *,
    allowed_evidence: list[str],
    raw_evidence: Mapping[str, Any],
) -> list[Finding]:
    findings: list[Finding] = []
    allowed = set(allowed_evidence)
    for claim in _json_list(artifact_body.get("claims", [])):
        claim_refs = _strings(claim.get("evidence_refs", []))
        missing_refs = [
            ref for ref in claim_refs if ref not in allowed or ref not in raw_evidence
        ]
        if not claim_refs or missing_refs:
            findings.append(
                Finding(
                    code="CLAIM_WITHOUT_SUPPORT",
                    message=f"Claim lacks raw evidence support: {claim.get('text', '')}",
                    artifact_id=artifact_id,
                    evidence_refs=claim_refs,
                )
            )
    return findings


def _forbidden_assumption_findings(
    artifact_id: str,
    artifact_body: Mapping[str, Any],
    forbidden_assumptions: list[str],
) -> list[Finding]:
    forbidden = {item.casefold(): item for item in forbidden_assumptions}
    assumptions = _strings(artifact_body.get("assumptions", []))
    for claim in _json_list(artifact_body.get("claims", [])):
        if str(claim.get("claim_type", claim.get("type", ""))).casefold() == "assumption":
            text = str(claim.get("text", ""))
            if text:
                assumptions.append(text)
    findings: list[Finding] = []
    for assumption in assumptions:
        if assumption.casefold() in forbidden:
            findings.append(
                Finding(
                    code="FORBIDDEN_ASSUMPTION",
                    message=f"Forbidden assumption present: {assumption}",
                    artifact_id=artifact_id,
                )
            )
    return findings


def _missing_acceptance_test_findings(
    artifact_id: str,
    artifact_body: Mapping[str, Any],
    acceptance_tests: list[str],
) -> list[Finding]:
    present = set(_strings(artifact_body.get("acceptance_tests", [])))
    return [
        Finding(
            code="MISSING_ACCEPTANCE_TEST",
            message=f"Missing acceptance test: {required}",
            artifact_id=artifact_id,
        )
        for required in acceptance_tests
        if required not in present
    ]


def _artifact_body(artifact: Mapping[str, Any]) -> Mapping[str, Any]:
    content = artifact.get("content")
    if isinstance(content, Mapping):
        return content
    return artifact


def _remediation_for(finding: Finding) -> str:
    if finding.code == "CLAIM_WITHOUT_SUPPORT":
        return "Attach allowed raw evidence references to each claim."
    if finding.code == "FORBIDDEN_ASSUMPTION":
        return "Remove or replace forbidden assumptions with cited evidence."
    if finding.code == "MISSING_ACCEPTANCE_TEST":
        return "Map every contract acceptance test into the artifact."
    return f"Resolve {finding.code}."


def _artifact_id(task_id: str, kind: str) -> str:
    return f"{_slug(task_id)}-{_slug(kind)}"


def _slug(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")


def _required_text(payload: Mapping[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raise TypeError("expected an iterable of strings")
    values = list(value)
    if any(not isinstance(item, str) or not item.strip() for item in values):
        raise ValueError("expected non-empty strings")
    return values


def _json_list(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, str):
        raise TypeError("expected a list of mappings")
    items = list(value)
    if any(not isinstance(item, Mapping) for item in items):
        raise TypeError("expected a list of mappings")
    return [dict(item) for item in items]


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return deepcopy(str(value))
