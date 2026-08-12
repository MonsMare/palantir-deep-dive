"""Evidence-bound stage runner."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any
from uuid import uuid4

from aifde.domain.artifacts import Artifact, canonical_json_bytes
from aifde.domain.gates import GateResult
from aifde.domain.stages import StageRun, StageState
from aifde.gates.engine import GateEngine, StageTransition, TransitionBlocked
from aifde.gates.validators import ValidationContext, ValidationResult
from aifde.policy.gateway import ToolGateway

from .agents import FakeBuilder, FakeChallenger
from .contracts import AgentContext, ChallengeReport, TaskContract


class StageRunner:
    """Run one bounded stage through builder, challenger, and gate checks."""

    @classmethod
    def for_testing(
        cls,
        *,
        project_id: str = "project-1",
        raw_evidence: dict[str, Any] | None = None,
        artifacts: dict[str, Any] | None = None,
    ) -> "StageRunner":
        return cls(
            project_id=project_id,
            raw_evidence=raw_evidence,
            artifact_payloads=artifacts,
        )

    def __init__(
        self,
        *,
        project_id: str = "project-1",
        builder: FakeBuilder | None = None,
        challenger: FakeChallenger | None = None,
        gate_engine: GateEngine | None = None,
        raw_evidence: dict[str, Any] | None = None,
        artifact_payloads: dict[str, Any] | None = None,
    ) -> None:
        self.project_id = project_id
        self.raw_evidence: dict[str, Any] = (
            raw_evidence
            if raw_evidence is not None
            else {"evidence-1": {"text": "source text"}}
        )
        self.artifact_payloads: dict[str, Any] = (
            artifact_payloads if artifact_payloads is not None else {}
        )
        self.artifacts: dict[str, Artifact] = {}
        self.builder = builder or FakeBuilder.for_testing()
        self.challenger = challenger or FakeChallenger.for_testing(
            raw_evidence=self.raw_evidence,
            artifacts=self.artifact_payloads,
        )
        self.gate_engine = gate_engine or GateEngine()
        self.stage_runs: dict[str, StageRun] = {}
        self.contracts: dict[str, TaskContract] = {}
        self.artifact_to_run: dict[str, str] = {}
        self.reports: dict[str, ChallengeReport] = {}
        self._sequence = 0
        self.tool_gateway: ToolGateway = self.builder.tool_gateway

    def run(self, contract: TaskContract) -> StageRun:
        contract = TaskContract.model_validate(contract)
        errors = self._contract_errors(contract)
        if errors:
            return self._blocked_contract_run(contract, errors)

        self._ensure_raw_evidence(contract.allowed_evidence)
        stage_run_id = self._next_stage_run_id(contract)
        evidence_snapshot_id = f"{stage_run_id}-evidence-snapshot"
        builder_context = AgentContext(
            project_id=self.project_id,
            stage_id=contract.stage_id,
            evidence_snapshot_id=evidence_snapshot_id,
            artifact_ids=[],
            tool_gateway=self.builder.tool_gateway,
        )
        proposal = self.builder.run(contract, builder_context)
        persisted_artifacts = self._persist_proposal(proposal.artifact_payloads)
        artifact_ids = [artifact.artifact_id for artifact in persisted_artifacts]
        stage_run = StageRun(
            stage_run_id=stage_run_id,
            project_id=self.project_id,
            stage_id=contract.stage_id,
            state=StageState.DRAFT,
            output_artifact_ids=artifact_ids,
            evidence_refs=list(
                dict.fromkeys([evidence_snapshot_id, *proposal.evidence_refs])
            ),
            open_questions=proposal.open_questions,
        )
        gate_context = self._validation_context(stage_run, contract)
        self.gate_engine.register_stage_run(
            stage_run,
            builder_actor=self.builder.actor_id,
            validation_context=gate_context,
        )
        self.contracts[stage_run_id] = contract
        self._persist_stage_run(self.gate_engine.get_stage_run(stage_run_id))
        self._transition(stage_run_id, StageState.VALIDATING, actor=self.builder.actor_id)
        self._transition(
            stage_run_id,
            StageState.CHALLENGING,
            actor=self.challenger.actor_id,
        )
        report = self._challenge_run(contract, stage_run_id, artifact_ids, evidence_snapshot_id)
        self.reports[stage_run_id] = report
        if report.result == "failed":
            self._transition(
                stage_run_id,
                StageState.REMEDIATION,
                actor=self.challenger.actor_id,
            )
            self._register_deterministic_gates(stage_run_id, gate_context, report)
            self._merge_run_fields(
                stage_run_id,
                blocking_reasons=report.required_remediation,
                open_questions=list(
                    dict.fromkeys(
                        [
                            *self.stage_runs[stage_run_id].open_questions,
                            *report.required_remediation,
                        ]
                    )
                ),
            )
        else:
            self._register_deterministic_gates(stage_run_id, gate_context, report)
            self._transition(
                stage_run_id,
                StageState.DOMAIN_REVIEW,
                actor=self.challenger.actor_id,
            )
        return _copy_stage_run(self.stage_runs[stage_run_id])

    def challenge(self, artifact_id: str) -> ChallengeReport:
        if artifact_id not in self.artifact_to_run:
            raise KeyError(f"unknown artifact: {artifact_id}")
        stage_run_id = self.artifact_to_run[artifact_id]
        contract = self.contracts[stage_run_id]
        run = self.stage_runs[stage_run_id]
        report = self._challenge_run(
            contract,
            stage_run_id,
            [artifact_id],
            run.evidence_refs[0],
        )
        self.reports[stage_run_id] = report
        return ChallengeReport.model_validate(report.model_dump(mode="python"))

    def request_transition(
        self,
        stage_run_id: str,
        target: StageState,
        actor: str,
    ) -> StageTransition:
        target = target if isinstance(target, StageState) else StageState(target)
        try:
            transition = self.gate_engine.transition(stage_run_id, target, actor=actor)
        except (PermissionError, TransitionBlocked) as exc:
            self._append_blocking_reason(stage_run_id, str(exc))
            try:
                transition = self.gate_engine.transition(
                    stage_run_id,
                    StageState.BLOCKED,
                    actor=actor,
                )
            except (PermissionError, TransitionBlocked, ValueError):
                current = self.gate_engine.get_stage_run(stage_run_id)
                transition = StageTransition(
                    transition_id=str(uuid4()),
                    stage_run_id=stage_run_id,
                    from_state=current.state,
                    to_state=current.state,
                    actor=actor.strip(),
                    gate_run_ids=[],
                    created_at=datetime.now(timezone.utc),
                )
        self._persist_stage_run(self.gate_engine.get_stage_run(stage_run_id))
        return transition

    def _contract_errors(self, contract: TaskContract) -> list[str]:
        errors: list[str] = []
        if not contract.allowed_evidence:
            errors.append("TaskContract must include allowed evidence before Builder work")
        if not contract.required_output:
            errors.append("TaskContract must name at least one required output")
        return errors

    def _blocked_contract_run(
        self,
        contract: TaskContract,
        blocking_reasons: list[str],
    ) -> StageRun:
        stage_run_id = self._next_stage_run_id(contract)
        snapshot_id = f"{stage_run_id}-contract-validation"
        stage_run = StageRun(
            stage_run_id=stage_run_id,
            project_id=self.project_id,
            stage_id=contract.stage_id,
            state=StageState.DRAFT,
            input_artifact_ids=[f"{stage_run_id}-contract"],
            evidence_refs=[snapshot_id],
            blocking_reasons=blocking_reasons,
        )
        context = ValidationContext(
            stage_run_id=stage_run.stage_run_id,
            artifact_ids=stage_run.input_artifact_ids,
            evidence_snapshot_id=snapshot_id,
            evidence_snapshot_hash=_hash_json({"blocking_reasons": blocking_reasons}),
            configuration={"contract_validation": True},
        )
        self.gate_engine.register_stage_run(
            stage_run,
            builder_actor=self.builder.actor_id,
            validation_context=context,
        )
        self.contracts[stage_run_id] = contract
        transition = self.gate_engine.transition(
            stage_run_id,
            StageState.BLOCKED,
            actor="deterministic-verifier-1",
        )
        self._persist_stage_run(self.gate_engine.get_stage_run(transition.stage_run_id))
        return _copy_stage_run(self.stage_runs[stage_run_id])

    def _challenge_run(
        self,
        contract: TaskContract,
        stage_run_id: str,
        artifact_ids: list[str],
        evidence_snapshot_id: str,
    ) -> ChallengeReport:
        challenge_context = AgentContext(
            project_id=self.project_id,
            stage_id=contract.stage_id,
            evidence_snapshot_id=evidence_snapshot_id,
            artifact_ids=artifact_ids,
            tool_gateway=self.challenger.tool_gateway,
        )
        return self.challenger.run(contract, challenge_context)

    def _persist_proposal(self, artifact_payloads: list[dict[str, Any]]) -> list[Artifact]:
        artifacts: list[Artifact] = []
        for payload in artifact_payloads:
            artifact = Artifact.model_validate(payload)
            self.artifacts[artifact.artifact_id] = artifact
            self.artifact_payloads[artifact.artifact_id] = artifact.model_dump(mode="json")
            self.artifact_payloads[artifact.artifact_id].update(
                artifact.content if isinstance(artifact.content, dict) else {}
            )
            artifacts.append(artifact)
        return artifacts

    def _validation_context(
        self,
        stage_run: StageRun,
        contract: TaskContract,
    ) -> ValidationContext:
        evidence_snapshot_id = stage_run.evidence_refs[0]
        return ValidationContext(
            stage_run_id=stage_run.stage_run_id,
            artifact_ids=stage_run.input_artifact_ids + stage_run.output_artifact_ids,
            evidence_snapshot_id=evidence_snapshot_id,
            evidence_snapshot_hash=self._evidence_snapshot_hash(contract.allowed_evidence),
            configuration={
                "runner": "deterministic-fake",
                "task_id": contract.task_id,
            },
        )

    def _register_deterministic_gates(
        self,
        stage_run_id: str,
        context: ValidationContext,
        report: ChallengeReport,
    ) -> None:
        unsupported_claims = [
            finding
            for finding in report.findings
            if finding.code == "CLAIM_WITHOUT_SUPPORT"
        ]
        self._register_gate(
            stage_run_id,
            context,
            gate_id="evidence.coverage",
            passed=not unsupported_claims,
            violations=[finding.message for finding in unsupported_claims],
        )
        self._register_gate(
            stage_run_id,
            context,
            gate_id="adversarial.challenge",
            passed=report.result == "passed",
            violations=[finding.message for finding in report.findings],
        )

    def _register_gate(
        self,
        stage_run_id: str,
        context: ValidationContext,
        *,
        gate_id: str,
        passed: bool,
        violations: list[str],
    ) -> None:
        result = ValidationResult(
            passed=passed,
            violations=violations,
            warnings=[],
            evidence_refs=[context.evidence_snapshot_id],
            validator_version=self.gate_engine.get_definition(gate_id).validator_version,
            input_hashes={
                artifact_id: self.artifacts[artifact_id].content_hash
                for artifact_id in context.artifact_ids
                if artifact_id in self.artifacts
            },
        )
        self.gate_engine.register_result(
            stage_run_id,
            gate_id=gate_id,
            result=result,
            context=context,
            gate_result=GateResult.PASSED if passed else GateResult.FAILED,
        )

    def _transition(
        self,
        stage_run_id: str,
        target: StageState,
        *,
        actor: str,
    ) -> None:
        self.gate_engine.transition(stage_run_id, target, actor=actor)
        self._persist_stage_run(self.gate_engine.get_stage_run(stage_run_id))

    def _persist_stage_run(self, stage_run: StageRun) -> None:
        current = self.stage_runs.get(stage_run.stage_run_id)
        payload = stage_run.model_dump(mode="python")
        if current is not None:
            if not payload["blocking_reasons"]:
                payload["blocking_reasons"] = current.blocking_reasons
            if not payload["open_questions"]:
                payload["open_questions"] = current.open_questions
        self.stage_runs[stage_run.stage_run_id] = StageRun.model_validate(payload)
        for artifact_id in stage_run.output_artifact_ids:
            self.artifact_to_run[artifact_id] = stage_run.stage_run_id

    def _merge_run_fields(
        self,
        stage_run_id: str,
        *,
        blocking_reasons: list[str] | None = None,
        open_questions: list[str] | None = None,
    ) -> None:
        run = self.stage_runs[stage_run_id]
        payload = run.model_dump(mode="python")
        if blocking_reasons is not None:
            payload["blocking_reasons"] = list(dict.fromkeys(blocking_reasons))
        if open_questions is not None:
            payload["open_questions"] = list(dict.fromkeys(open_questions))
        self.stage_runs[stage_run_id] = StageRun.model_validate(payload)

    def _append_blocking_reason(self, stage_run_id: str, reason: str) -> None:
        if stage_run_id not in self.stage_runs:
            return
        run = self.stage_runs[stage_run_id]
        self._merge_run_fields(
            stage_run_id,
            blocking_reasons=list(dict.fromkeys([*run.blocking_reasons, reason])),
        )

    def _next_stage_run_id(self, contract: TaskContract) -> str:
        self._sequence += 1
        return f"{contract.task_id}-run-{self._sequence}"

    def _ensure_raw_evidence(self, evidence_refs: list[str]) -> None:
        for evidence_id in evidence_refs:
            self.raw_evidence.setdefault(
                evidence_id,
                {"text": f"raw evidence fixture for {evidence_id}"},
            )

    def _evidence_snapshot_hash(self, evidence_refs: list[str]) -> str:
        return _hash_json(
            {
                evidence_id: self.raw_evidence.get(evidence_id)
                for evidence_id in evidence_refs
            }
        )


def _copy_stage_run(stage_run: StageRun) -> StageRun:
    return StageRun.model_validate(deepcopy(stage_run.model_dump(mode="python")))


def _hash_json(value: Any) -> str:
    try:
        return sha256(canonical_json_bytes(value)).hexdigest()
    except ValueError:
        return sha256(str(value).encode("utf-8")).hexdigest()
