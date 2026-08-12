"""Version-aware gate evaluation and the only stage-transition path."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from aifde.domain.gates import GateResult
from aifde.domain.stages import StageRun, StageState
from aifde.gates.definitions import BUILT_IN_GATE_DEFINITIONS, GateDefinition
from aifde.gates.validators import ValidationContext, ValidationResult


class GateRun(BaseModel):
    """A persisted-in-engine validation attempt and its complete input snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    gate_run_id: str
    stage_run_id: str
    gate_id: str
    result: GateResult
    definition_version: str
    validator_version: str
    artifact_hashes: dict[str, str] = Field(default_factory=dict)
    evidence_snapshot_id: str
    evidence_refs: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    violations: list[str] = Field(default_factory=list)
    created_at: datetime
    stale: bool = False


class GateWaiver(BaseModel):
    """A temporary, owned exception to one soft gate failure."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    waiver_id: str
    stage_run_id: str
    gate_id: str
    owner: str
    reason: str
    remediation: str
    expires_at: datetime
    created_at: datetime

    @field_validator("owner", "reason", "remediation")
    @classmethod
    def reject_blank_required_fields(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value

    def is_active(self, now: datetime) -> bool:
        return self.expires_at > now


class GateSummary(BaseModel):
    """Current gate posture for a stage run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    hard_failures: list[str] = Field(default_factory=list)
    soft_failures: list[str] = Field(default_factory=list)
    pending_approvals: list[str] = Field(default_factory=list)
    valid_until: datetime | None = None


class TransitionDecision(BaseModel):
    """A typed decision made before a stage state can change."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed: bool
    blocking_gate_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    reason: str


class StageTransition(BaseModel):
    """An immutable audit record of a successful guarded state transition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    transition_id: str
    stage_run_id: str
    from_state: StageState
    to_state: StageState
    actor: str
    gate_run_ids: list[str]
    created_at: datetime


class TransitionBlocked(RuntimeError):
    """Raised when callers attempt a state change GateEngine rejected."""


_ALLOWED_TRANSITIONS: dict[StageState, set[StageState]] = {
    StageState.DRAFT: {StageState.VALIDATING, StageState.BLOCKED},
    StageState.VALIDATING: {StageState.CHALLENGING, StageState.REMEDIATION, StageState.BLOCKED},
    StageState.CHALLENGING: {StageState.DOMAIN_REVIEW, StageState.REMEDIATION, StageState.BLOCKED},
    StageState.DOMAIN_REVIEW: {StageState.APPROVED, StageState.REMEDIATION, StageState.BLOCKED},
    StageState.APPROVED: {StageState.RELEASE_CANDIDATE, StageState.REMEDIATION, StageState.BLOCKED},
    StageState.RELEASE_CANDIDATE: {StageState.RELEASED, StageState.REMEDIATION, StageState.BLOCKED},
    StageState.RELEASED: {StageState.REMEDIATION},
    StageState.REMEDIATION: {StageState.VALIDATING, StageState.BLOCKED},
    StageState.BLOCKED: {StageState.REMEDIATION},
}


class GateEngine:
    """Keep gate evidence current and perform all traceable stage transitions."""

    def __init__(self) -> None:
        self._definitions = {
            definition.gate_id: definition for definition in BUILT_IN_GATE_DEFINITIONS
        }
        self._stage_runs: dict[str, StageRun] = {}
        self._builder_actors: dict[str, str | None] = {}
        self._gate_runs: dict[str, list[GateRun]] = {}
        self._waivers: dict[str, list[GateWaiver]] = {}
        self._transitions: list[StageTransition] = []

    def register_definition(self, definition: GateDefinition) -> GateDefinition:
        """Register policy and mark prior results stale if its policy changed."""
        prior = self._definitions.get(definition.gate_id)
        self._definitions[definition.gate_id] = definition
        if prior is not None and (
            prior.version != definition.version
            or prior.validator_version != definition.validator_version
        ):
            self._mark_gate_stale(definition.gate_id)
        return definition

    def get_definition(self, gate_id: str) -> GateDefinition:
        """Return the versioned policy definition for a gate."""
        try:
            return self._definitions[gate_id]
        except KeyError as exc:
            raise KeyError(f"unknown gate definition: {gate_id}") from exc

    def register_stage_run(
        self, stage_run: StageRun, *, builder_actor: str | None = None
    ) -> StageRun:
        """Store a stage run before evaluation or transitions can occur."""
        if stage_run.stage_run_id in self._stage_runs:
            raise ValueError("stage run is already registered")
        self._stage_runs[stage_run.stage_run_id] = stage_run.model_copy(deep=True)
        self._builder_actors[stage_run.stage_run_id] = builder_actor
        self._gate_runs[stage_run.stage_run_id] = []
        self._waivers[stage_run.stage_run_id] = []
        return self.get_stage_run(stage_run.stage_run_id)

    def get_stage_run(self, stage_run_id: str) -> StageRun:
        """Return the current stage state without exposing mutable engine storage."""
        try:
            return self._stage_runs[stage_run_id].model_copy(deep=True)
        except KeyError as exc:
            raise KeyError(f"unknown stage run: {stage_run_id}") from exc

    def register_result(
        self,
        stage_run_id: str,
        *,
        gate_id: str,
        result: ValidationResult,
        context: ValidationContext | None = None,
    ) -> GateRun:
        """Persist one validation result with the exact definition and input versions."""
        stage_run = self.get_stage_run(stage_run_id)
        definition = self.get_definition(gate_id)
        resolved_context = context or ValidationContext(
            stage_run_id=stage_run_id,
            artifact_ids=stage_run.output_artifact_ids or stage_run.input_artifact_ids,
            evidence_snapshot_id=stage_run.evidence_refs[0] if stage_run.evidence_refs else "",
            configuration={},
        )
        if resolved_context.stage_run_id != stage_run_id:
            raise ValueError("validation context belongs to a different stage run")
        if result.validator_version != definition.validator_version:
            raise ValueError("result validator_version does not match gate definition")
        if resolved_context.evidence_snapshot_id not in result.evidence_refs:
            raise ValueError("result must reference the validation evidence snapshot")
        gate_run = GateRun(
            gate_run_id=str(uuid4()),
            stage_run_id=stage_run_id,
            gate_id=gate_id,
            result=GateResult.PASSED if result.passed else GateResult.FAILED,
            definition_version=definition.version,
            validator_version=result.validator_version,
            artifact_hashes=result.input_hashes,
            evidence_snapshot_id=resolved_context.evidence_snapshot_id,
            evidence_refs=result.evidence_refs,
            warnings=result.warnings,
            violations=result.violations,
            created_at=_utc_now(),
        )
        self._gate_runs[stage_run_id].append(gate_run)
        return gate_run

    def add_waiver(
        self,
        stage_run_id: str,
        *,
        gate_id: str,
        owner: str,
        reason: str,
        remediation: str,
        expires_at: datetime,
    ) -> GateWaiver:
        """Record a complete, temporary exception for a failed soft gate."""
        self.get_stage_run(stage_run_id)
        definition = self.get_definition(gate_id)
        if definition.severity != "soft":
            raise ValueError("only soft gates can be waived")
        if expires_at.tzinfo is None:
            raise ValueError("expires_at must be timezone-aware")
        waiver = GateWaiver(
            waiver_id=str(uuid4()),
            stage_run_id=stage_run_id,
            gate_id=gate_id,
            owner=owner,
            reason=reason,
            remediation=remediation,
            expires_at=expires_at,
            created_at=_utc_now(),
        )
        self._waivers[stage_run_id].append(waiver)
        return waiver

    def evaluate(self, stage_run_id: str) -> GateSummary:
        """Summarize the latest result per gate, honoring only active soft waivers."""
        self.get_stage_run(stage_run_id)
        now = _utc_now()
        hard_failures: list[str] = []
        soft_failures: list[str] = []
        pending_approvals: list[str] = []
        warnings: list[str] = []
        valid_until: datetime | None = None
        for gate_run in self._latest_gate_runs(stage_run_id).values():
            if gate_run.result is GateResult.PASSED and not self._is_current(gate_run):
                hard_failures.append(gate_run.gate_id)
                warnings.append(f"{gate_run.gate_id} is stale")
                continue
            if gate_run.result is GateResult.PASSED:
                warnings.extend(gate_run.warnings)
                continue
            definition = self.get_definition(gate_run.gate_id)
            if definition.severity == "hard" or not self._is_current(gate_run):
                hard_failures.append(gate_run.gate_id)
                continue
            soft_failures.append(gate_run.gate_id)
            waiver = self._active_waiver(stage_run_id, gate_run.gate_id, now)
            if waiver is None:
                pending_approvals.append(gate_run.gate_id)
            else:
                valid_until = (
                    waiver.expires_at
                    if valid_until is None
                    else min(valid_until, waiver.expires_at)
                )
        return GateSummary(
            hard_failures=hard_failures,
            soft_failures=soft_failures,
            pending_approvals=pending_approvals,
            valid_until=valid_until,
        )

    def can_transition(self, stage_run_id: str, target: StageState) -> TransitionDecision:
        """Decide whether a typed transition is legal under current gate evidence."""
        stage_run = self.get_stage_run(stage_run_id)
        if target not in _ALLOWED_TRANSITIONS[stage_run.state]:
            return TransitionDecision(
                allowed=False,
                reason=f"transition from {stage_run.state.value} to {target.value} is not allowed",
            )
        summary = self.evaluate(stage_run_id)
        blocking_gate_ids = summary.hard_failures + summary.pending_approvals
        if blocking_gate_ids:
            return TransitionDecision(
                allowed=False,
                blocking_gate_ids=blocking_gate_ids,
                warnings=[*summary.soft_failures, *summary.pending_approvals],
                reason="gates are blocking the transition",
            )
        return TransitionDecision(
            allowed=True,
            warnings=summary.soft_failures,
            reason="all registered gate results are current and acceptable",
        )

    def transition(
        self, stage_run_id: str, target: StageState, actor: str
    ) -> StageTransition:
        """Apply the only allowed state mutation after the gate decision succeeds."""
        if target is StageState.APPROVED and actor == self._builder_actors.get(stage_run_id):
            raise PermissionError("builder cannot approve their own stage")
        decision = self.can_transition(stage_run_id, target)
        if not decision.allowed:
            raise TransitionBlocked(f"transition not allowed: {decision.reason}")
        before = self.get_stage_run(stage_run_id)
        transition = StageTransition(
            transition_id=str(uuid4()),
            stage_run_id=stage_run_id,
            from_state=before.state,
            to_state=target,
            actor=actor,
            gate_run_ids=[run.gate_run_id for run in self._latest_gate_runs(stage_run_id).values()],
            created_at=_utc_now(),
        )
        self._stage_runs[stage_run_id] = before.model_copy(update={"state": target})
        self._transitions.append(transition)
        return transition

    def invalidate_for_artifact_change(self, artifact_id: str, new_hash: str) -> int:
        """Mark every gate result that used an older artifact hash as stale."""
        return self._invalidate(
            lambda run: artifact_id in run.artifact_hashes
            and run.artifact_hashes[artifact_id] != new_hash
        )

    def invalidate_for_evidence_snapshot_change(
        self, evidence_snapshot_id: str, new_snapshot_id: str
    ) -> int:
        """Mark every gate result tied to a replaced evidence snapshot as stale."""
        return self._invalidate(
            lambda run: run.evidence_snapshot_id == evidence_snapshot_id
            and evidence_snapshot_id != new_snapshot_id
        )

    def _latest_gate_runs(self, stage_run_id: str) -> dict[str, GateRun]:
        latest: dict[str, GateRun] = {}
        for gate_run in self._gate_runs[stage_run_id]:
            latest[gate_run.gate_id] = gate_run
        return latest

    def _active_waiver(
        self, stage_run_id: str, gate_id: str, now: datetime
    ) -> GateWaiver | None:
        active = [
            waiver
            for waiver in self._waivers[stage_run_id]
            if waiver.gate_id == gate_id and waiver.is_active(now)
        ]
        return max(active, key=lambda waiver: waiver.expires_at, default=None)

    def _is_current(self, gate_run: GateRun) -> bool:
        definition = self.get_definition(gate_run.gate_id)
        return (
            not gate_run.stale
            and gate_run.definition_version == definition.version
            and gate_run.validator_version == definition.validator_version
        )

    def _mark_gate_stale(self, gate_id: str) -> None:
        for stage_run_id, runs in self._gate_runs.items():
            self._gate_runs[stage_run_id] = [
                run.model_copy(update={"stale": True}) if run.gate_id == gate_id else run
                for run in runs
            ]

    def _invalidate(self, predicate: object) -> int:
        changed = 0
        for stage_run_id, runs in self._gate_runs.items():
            updated_runs: list[GateRun] = []
            for run in runs:
                if not run.stale and callable(predicate) and predicate(run):
                    updated_runs.append(run.model_copy(update={"stale": True}))
                    changed += 1
                else:
                    updated_runs.append(run)
            self._gate_runs[stage_run_id] = updated_runs
        return changed


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
