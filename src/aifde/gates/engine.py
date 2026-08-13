"""Version-aware gates and the sole, audited stage-transition state machine."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

from aifde.domain.artifacts import canonical_json_bytes
from aifde.domain.gates import GateResult
from aifde.domain.stages import StageRun, StageState
from aifde.gates.definitions import BUILT_IN_GATE_DEFINITIONS, GateDefinition
from aifde.gates.validators import ValidationContext, ValidationResult


class GateRun(BaseModel):
    """One validator result with its complete, comparable input provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    gate_run_id: str
    stage_run_id: str
    gate_id: str
    result: GateResult
    definition_version: str
    validator_version: str
    definition_fingerprint: str
    artifact_hashes: dict[str, str]
    evidence_snapshot_id: str
    evidence_snapshot_hash: str
    configuration: dict[str, JsonValue]
    configuration_hash: str
    input_snapshot_hash: str
    evidence_refs: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    violations: list[str] = Field(default_factory=list)
    created_at: datetime
    stale: bool = False


class GateWaiver(BaseModel):
    """A complete, temporary exception for exactly one soft gate."""

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
    """An immutable audit record of one successful guarded transition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    transition_id: str
    stage_run_id: str
    from_state: StageState
    to_state: StageState
    actor: str
    gate_run_ids: list[str]
    created_at: datetime


class TransitionBlocked(RuntimeError):
    """Raised when GateEngine rejects an attempted state transition."""


_APPROVAL_GATES = frozenset(
    {
        "reality.consistency",
        "evidence.coverage",
        "semantic.integrity",
        "data.quality",
        "executable.readiness",
        "adversarial.challenge",
        "business.exception_coverage",
    }
)
_RELEASE_GATES = _APPROVAL_GATES | {"release.governance"}
_REQUIRED_GATES_BY_TARGET: dict[StageState, frozenset[str]] = {
    StageState.APPROVED: _APPROVAL_GATES,
    StageState.RELEASE_CANDIDATE: _RELEASE_GATES,
    StageState.RELEASED: _RELEASE_GATES,
}
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
    """Record trusted validator snapshots and govern every state mutation."""

    def __init__(self) -> None:
        self._definitions = {
            definition.gate_id: _copy_model(definition)
            for definition in BUILT_IN_GATE_DEFINITIONS
        }
        self._stage_runs: dict[str, StageRun] = {}
        self._builder_actors: dict[str, str] = {}
        self._validation_contexts: dict[str, ValidationContext] = {}
        self._gate_runs: dict[str, list[GateRun]] = {}
        self._waivers: dict[str, list[GateWaiver]] = {}
        self._transitions: list[StageTransition] = []

    def register_definition(self, definition: GateDefinition) -> GateDefinition:
        """Replace a gate policy and invalidate its previous results when changed."""
        stored = _copy_model(definition)
        prior = self._definitions.get(stored.gate_id)
        self._definitions[stored.gate_id] = stored
        if prior is not None and prior.definition_fingerprint != stored.definition_fingerprint:
            self._mark_gate_stale(stored.gate_id)
        return _copy_model(stored)

    def get_definition(self, gate_id: str) -> GateDefinition:
        """Return a defensive copy of one versioned policy definition."""
        try:
            return _copy_model(self._definitions[gate_id])
        except KeyError as exc:
            raise KeyError(f"unknown gate definition: {gate_id}") from exc

    def register_stage_run(
        self,
        stage_run: StageRun,
        *,
        builder_actor: str,
        validation_context: ValidationContext,
    ) -> StageRun:
        """Register the stage and its authoritative validation input snapshot."""
        if not isinstance(stage_run, StageRun):
            raise TypeError("stage_run must be a StageRun")
        builder_actor = _canonicalize_identity(builder_actor, "builder_actor")
        if stage_run.stage_run_id in self._stage_runs:
            raise ValueError("stage run is already registered")
        self._validate_context_for_stage(stage_run, validation_context)
        self._stage_runs[stage_run.stage_run_id] = _copy_model(stage_run)
        self._builder_actors[stage_run.stage_run_id] = builder_actor
        self._validation_contexts[stage_run.stage_run_id] = _copy_model(validation_context)
        self._gate_runs[stage_run.stage_run_id] = []
        self._waivers[stage_run.stage_run_id] = []
        return self.get_stage_run(stage_run.stage_run_id)

    def get_stage_run(self, stage_run_id: str) -> StageRun:
        """Return a defensive copy of the current stage state."""
        try:
            return _copy_model(self._stage_runs[stage_run_id])
        except KeyError as exc:
            raise KeyError(f"unknown stage run: {stage_run_id}") from exc

    def list_stage_runs(self, project_id: str | None = None) -> list[StageRun]:
        """Return defensive copies of registered stage runs for release services."""
        runs = [
            run
            for run in self._stage_runs.values()
            if project_id is None or run.project_id == project_id
        ]
        return [_copy_model(run) for run in runs]

    def list_gate_runs(self, stage_run_id: str) -> list[GateRun]:
        """Return every immutable gate snapshot recorded for one stage run."""
        self.get_stage_run(stage_run_id)
        return [_copy_model(run) for run in self._gate_runs[stage_run_id]]

    def get_gate_run(self, stage_run_id: str, gate_run_id: str) -> GateRun:
        """Return one gate snapshot without exposing the engine's mutable store."""
        for gate_run in self.list_gate_runs(stage_run_id):
            if gate_run.gate_run_id == gate_run_id:
                return gate_run
        raise KeyError(f"unknown gate run: {gate_run_id}")

    def register_result(
        self,
        stage_run_id: str,
        *,
        gate_id: str,
        result: ValidationResult,
        context: ValidationContext,
        gate_result: GateResult | None = None,
    ) -> GateRun:
        """Store a result only when it exactly matches the registered input snapshot."""
        self.get_stage_run(stage_run_id)
        definition = self._get_stored_definition(gate_id)
        if not isinstance(result, ValidationResult):
            raise TypeError("result must be a ValidationResult")
        if not isinstance(context, ValidationContext):
            raise TypeError("context must be a ValidationContext")
        self._validate_context_for_stage(self._stage_runs[stage_run_id], context)
        expected_context = self._validation_contexts.get(stage_run_id)
        if expected_context is not None and _context_payload(context) != _context_payload(expected_context):
            raise ValueError("validation context does not match the registered input snapshot")
        if result.validator_version != definition.validator_version:
            raise ValueError("result validator_version does not match gate definition")
        if set(result.input_hashes) != set(context.artifact_ids):
            raise ValueError("input_hashes must exactly cover validation context artifact_ids")
        if context.evidence_snapshot_id not in result.evidence_refs:
            raise ValueError("result must reference the validation evidence snapshot")
        resolved_gate_result = _resolve_gate_result(result, gate_result)
        gate_run = GateRun(
            gate_run_id=str(uuid4()),
            stage_run_id=stage_run_id,
            gate_id=gate_id,
            result=resolved_gate_result,
            definition_version=definition.version,
            validator_version=result.validator_version,
            definition_fingerprint=definition.definition_fingerprint,
            artifact_hashes=deepcopy(result.input_hashes),
            evidence_snapshot_id=context.evidence_snapshot_id,
            evidence_snapshot_hash=context.evidence_snapshot_hash,
            configuration=deepcopy(context.configuration),
            configuration_hash=context.configuration_hash,
            input_snapshot_hash=_snapshot_hash(context, result.input_hashes),
            evidence_refs=deepcopy(result.evidence_refs),
            warnings=deepcopy(result.warnings),
            violations=deepcopy(result.violations),
            created_at=_utc_now(),
        )
        self._gate_runs[stage_run_id].append(gate_run)
        return _copy_model(gate_run)

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
        """Record an owned, remediated, time-bounded exception for a soft failure."""
        self.get_stage_run(stage_run_id)
        definition = self._get_stored_definition(gate_id)
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
        return _copy_model(waiver)

    def evaluate(self, stage_run_id: str) -> GateSummary:
        """Summarize only observed gate results; transition policy adds required gates."""
        self.get_stage_run(stage_run_id)
        now = _utc_now()
        hard_failures: list[str] = []
        soft_failures: list[str] = []
        pending_approvals: list[str] = []
        valid_until: datetime | None = None
        for gate_run in self._latest_gate_runs(stage_run_id).values():
            if gate_run.result is GateResult.PASSED and self._is_current(gate_run):
                continue
            definition = self._get_stored_definition(gate_run.gate_id)
            if not self._is_current(gate_run):
                hard_failures.append(gate_run.gate_id)
                continue
            if gate_run.result in {GateResult.PENDING, GateResult.BLOCKED}:
                if definition.severity == "hard":
                    hard_failures.append(gate_run.gate_id)
                else:
                    soft_failures.append(gate_run.gate_id)
                    pending_approvals.append(gate_run.gate_id)
                continue
            if definition.severity == "hard":
                hard_failures.append(gate_run.gate_id)
                continue
            soft_failures.append(gate_run.gate_id)
            waiver = self._active_waiver(stage_run_id, gate_run.gate_id, now)
            if waiver is None:
                pending_approvals.append(gate_run.gate_id)
            else:
                valid_until = waiver.expires_at if valid_until is None else min(valid_until, waiver.expires_at)
        return GateSummary(
            hard_failures=hard_failures,
            soft_failures=soft_failures,
            pending_approvals=pending_approvals,
            valid_until=valid_until,
        )

    def can_transition(self, stage_run_id: str, target: StageState) -> TransitionDecision:
        """Apply the explicit target policy to current gate results."""
        if not isinstance(target, StageState):
            raise TypeError("target must be a StageState")
        stage_run = self.get_stage_run(stage_run_id)
        if target not in _ALLOWED_TRANSITIONS[stage_run.state]:
            return TransitionDecision(
                allowed=False,
                reason=f"transition from {stage_run.state.value} to {target.value} is not allowed",
            )
        summary = self.evaluate(stage_run_id)
        latest = self._latest_gate_runs(stage_run_id)
        required = _REQUIRED_GATES_BY_TARGET.get(target, frozenset())
        missing = sorted(required - set(latest))
        stale_or_failed = summary.hard_failures + summary.pending_approvals
        blocking_gate_ids = _unique([*missing, *stale_or_failed])
        if blocking_gate_ids:
            return TransitionDecision(
                allowed=False,
                blocking_gate_ids=blocking_gate_ids,
                warnings=summary.soft_failures,
                reason="required gates are missing, stale, failed, or awaiting waiver",
            )
        return TransitionDecision(
            allowed=True,
            warnings=summary.soft_failures,
            reason="all gates required by the target policy are current and acceptable",
        )

    def transition(
        self, stage_run_id: str, target: StageState, actor: str
    ) -> StageTransition:
        """Perform the only validated and audited state mutation."""
        if not isinstance(target, StageState):
            raise TypeError("target must be a StageState")
        actor = _canonicalize_identity(actor, "actor")
        if target in {
            StageState.APPROVED,
            StageState.RELEASE_CANDIDATE,
            StageState.RELEASED,
        } and actor == self._builder_actors[stage_run_id]:
            raise PermissionError("builder cannot approve or release their own stage")
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
        payload = before.model_dump(mode="python")
        payload["state"] = target
        self._stage_runs[stage_run_id] = StageRun.model_validate(payload)
        self._transitions.append(transition)
        return _copy_model(transition)

    def list_transitions(self, stage_run_id: str) -> list[StageTransition]:
        """Return defensive copies of the audited transition history for one run."""
        self.get_stage_run(stage_run_id)
        return [
            _copy_model(transition)
            for transition in self._transitions
            if transition.stage_run_id == stage_run_id
        ]

    def invalidate_for_artifact_change(self, artifact_id: str, new_hash: str) -> int:
        """Stale every result that used an older hash for a registered stage artifact."""
        _require_identity(artifact_id, "artifact_id")
        _require_identity(new_hash, "new_hash")
        return self._invalidate(
            lambda run: artifact_id in run.artifact_hashes
            and run.artifact_hashes[artifact_id] != new_hash
        )

    def invalidate_for_evidence_snapshot_change(
        self,
        evidence_snapshot_id: str,
        new_snapshot_id: str,
        new_snapshot_hash: str | None = None,
    ) -> int:
        """Stale results when an evidence snapshot id or its content hash changes."""
        _require_identity(evidence_snapshot_id, "evidence_snapshot_id")
        _require_identity(new_snapshot_id, "new_snapshot_id")
        if evidence_snapshot_id == new_snapshot_id and new_snapshot_hash is None:
            raise ValueError("new_snapshot_hash is required when reusing an evidence snapshot id")
        if new_snapshot_hash is not None:
            _require_identity(new_snapshot_hash, "new_snapshot_hash")
        return self._invalidate(
            lambda run: run.evidence_snapshot_id == evidence_snapshot_id
            and (
                run.evidence_snapshot_id != new_snapshot_id
                or (new_snapshot_hash is not None and run.evidence_snapshot_hash != new_snapshot_hash)
            )
        )

    def invalidate_for_configuration_change(
        self, stage_run_id: str, configuration: dict[str, JsonValue]
    ) -> int:
        """Stale a stage's gate results when its canonical validator configuration changes."""
        self.get_stage_run(stage_run_id)
        new_hash = sha256(canonical_json_bytes(configuration)).hexdigest()
        return self._invalidate(
            lambda run: run.stage_run_id == stage_run_id and run.configuration_hash != new_hash
        )

    def _validate_context_for_stage(
        self, stage_run: StageRun, context: ValidationContext
    ) -> None:
        if not isinstance(context, ValidationContext):
            raise TypeError("validation_context must be a ValidationContext")
        if context.stage_run_id != stage_run.stage_run_id:
            raise ValueError("validation context belongs to a different stage run")
        expected_artifacts = stage_run.input_artifact_ids + stage_run.output_artifact_ids
        if set(context.artifact_ids) != set(expected_artifacts) or len(context.artifact_ids) != len(expected_artifacts):
            raise ValueError("validation context artifact_ids must exactly cover stage artifacts")
        if context.evidence_snapshot_id not in stage_run.evidence_refs:
            raise ValueError("validation context evidence snapshot must be referenced by the stage")

    def _get_stored_definition(self, gate_id: str) -> GateDefinition:
        try:
            return self._definitions[gate_id]
        except KeyError as exc:
            raise KeyError(f"unknown gate definition: {gate_id}") from exc

    def _latest_gate_runs(self, stage_run_id: str) -> dict[str, GateRun]:
        latest: dict[str, GateRun] = {}
        for gate_run in self._gate_runs[stage_run_id]:
            latest[gate_run.gate_id] = gate_run
        return latest

    def _active_waiver(self, stage_run_id: str, gate_id: str, now: datetime) -> GateWaiver | None:
        active = [
            waiver
            for waiver in self._waivers[stage_run_id]
            if waiver.gate_id == gate_id and waiver.is_active(now)
        ]
        return max(active, key=lambda waiver: waiver.expires_at, default=None)

    def _is_current(self, gate_run: GateRun) -> bool:
        definition = self._get_stored_definition(gate_run.gate_id)
        return (
            not gate_run.stale
            and gate_run.definition_version == definition.version
            and gate_run.validator_version == definition.validator_version
            and gate_run.definition_fingerprint == definition.definition_fingerprint
        )

    def _mark_gate_stale(self, gate_id: str) -> None:
        self._replace_gate_runs(lambda run: run.gate_id == gate_id)

    def _invalidate(self, predicate: Callable[[GateRun], bool]) -> int:
        changed = 0
        for runs in self._gate_runs.values():
            changed += sum(not run.stale and predicate(run) for run in runs)
        self._replace_gate_runs(predicate)
        return changed

    def _replace_gate_runs(self, predicate: Callable[[GateRun], bool]) -> None:
        for stage_run_id, runs in self._gate_runs.items():
            self._gate_runs[stage_run_id] = [
                _copy_model(run, stale=True) if not run.stale and predicate(run) else run
                for run in runs
            ]


def _context_payload(context: ValidationContext) -> dict[str, Any]:
    return context.model_dump(mode="python")


def _snapshot_hash(context: ValidationContext, artifact_hashes: dict[str, str]) -> str:
    payload = {
        "artifact_hashes": artifact_hashes,
        "evidence_snapshot_id": context.evidence_snapshot_id,
        "evidence_snapshot_hash": context.evidence_snapshot_hash,
        "configuration_hash": context.configuration_hash,
    }
    return sha256(canonical_json_bytes(payload)).hexdigest()


def _copy_model(model: BaseModel, **updates: Any) -> Any:
    """Revalidate a deep copy, avoiding Pydantic's unvalidated model_copy updates."""
    payload = deepcopy(model.model_dump(mode="python"))
    payload.update(updates)
    return type(model).model_validate(payload)


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _canonicalize_identity(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty identity")
    return value.strip()


def _require_identity(value: str, name: str) -> None:
    _canonicalize_identity(value, name)


def _resolve_gate_result(
    result: ValidationResult, gate_result: GateResult | None
) -> GateResult:
    """Resolve an explicit lifecycle result while preserving the boolean API."""
    resolved = gate_result or (GateResult.PASSED if result.passed else GateResult.FAILED)
    if not isinstance(resolved, GateResult):
        raise TypeError("gate_result must be a GateResult")
    if resolved is GateResult.PASSED and not result.passed:
        raise ValueError("a PASSED gate result must have passed=True")
    if resolved is not GateResult.PASSED and result.passed:
        raise ValueError("a non-PASSED gate result must have passed=False")
    return resolved


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
