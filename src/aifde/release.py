"""Governed release packages and append-only rollback operations."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from aifde.domain.artifacts import Artifact, semantic_version_key
from aifde.domain.stages import StageState
from aifde.gates.engine import GateEngine, TransitionBlocked
from aifde.policy.capabilities import ActorRole, PolicyEngine


class ReleasePackage(BaseModel):
    """Immutable provenance manifest for one released artifact set."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    package_id: str = Field(default_factory=lambda: str(uuid4()))
    project_id: str
    artifact_ids: list[str]
    artifact_hashes: dict[str, str]
    gate_run_ids: list[str]
    approval_ids: list[str]
    tool_versions: dict[str, str] = Field(default_factory=dict)
    policy_version: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    rollback_manifest: dict[str, dict[str, Any]]

    @property
    def passed_gate_run_ids(self) -> list[str]:
        """Compatibility/readability alias for the release acceptance contract."""
        return list(self.gate_run_ids)

    @field_validator(
        "package_id",
        "project_id",
        "policy_version",
    )
    @classmethod
    def reject_blank_identity(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("release identity must be non-empty")
        if value != value.strip():
            raise ValueError("release identity must be canonical")
        return value

    @field_validator("artifact_ids", "gate_run_ids", "approval_ids")
    @classmethod
    def validate_identity_lists(cls, value: list[str]) -> list[str]:
        if not value or any(not isinstance(item, str) or not item.strip() for item in value):
            raise ValueError("release identity lists must be non-empty")
        if any(item != item.strip() for item in value):
            raise ValueError("release identity lists must be canonical")
        if len(set(value)) != len(value):
            raise ValueError("release identity lists must not contain duplicates")
        return value

    @field_validator("artifact_hashes")
    @classmethod
    def validate_artifact_hashes(cls, value: dict[str, str]) -> dict[str, str]:
        if not value or any(
            len(item) != 64
            or any(char not in "0123456789abcdef" for char in item)
            for item in value.values()
        ):
            raise ValueError("artifact_hashes must contain SHA-256 hashes")
        return value

    @field_validator("created_at")
    @classmethod
    def require_aware_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value


class ReleaseVerification(BaseModel):
    """Result of checking a package against current artifacts and gate facts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    missing_gate_runs: list[str] = Field(default_factory=list)
    missing_approvals: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class RollbackResult(BaseModel):
    """Audit result for a non-destructive rollback append."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    restored_artifact_ids: list[str]
    previous_release_id: str | None = None
    audit_id: str = Field(default_factory=lambda: str(uuid4()))


class ReleaseManager:
    """Build, verify, and rollback releases through the Gate Engine."""

    def __init__(
        self,
        registry: Any,
        gate_engine: GateEngine,
        *,
        policy: PolicyEngine | None = None,
        release_actor: str = "release-owner-1",
        policy_version: str | None = None,
        tool_versions: dict[str, str] | None = None,
    ) -> None:
        if not isinstance(gate_engine, GateEngine):
            raise TypeError("gate_engine must be a GateEngine")
        self._registry = registry
        self._gate_engine = gate_engine
        self._policy = policy or PolicyEngine()
        binding = self._policy.actor_binding(release_actor)
        if binding is None or self._policy.role_for(release_actor) != ActorRole.RELEASE_OWNER.value:
            raise PermissionError("release_actor must be a trusted Release Owner")
        self._release_actor = release_actor
        self._policy_version = policy_version or str(self._policy.policy_version)
        self._tool_versions = dict(tool_versions or {"release-manager": "1.0.0"})
        self._packages: dict[str, ReleasePackage] = {}
        self._latest_by_project: dict[str, str] = {}
        self._rollbacks: dict[str, RollbackResult] = {}

    def build(self, project_id: str, artifact_ids: list[str]) -> ReleasePackage:
        """Release only artifacts covered by a release-candidate GateEngine run."""
        _require_identity(project_id, "project_id")
        normalized_ids = _unique_identities(artifact_ids, "artifact_ids")
        artifacts = [
            self._registry.artifacts.get(project_id, artifact_id)
            for artifact_id in normalized_ids
        ]
        stage_runs = self._stage_runs_for_artifacts(project_id, normalized_ids)
        for stage_run in stage_runs:
            if stage_run.state is not StageState.RELEASE_CANDIDATE:
                raise TransitionBlocked(
                    f"stage run {stage_run.stage_run_id} must be release_candidate before release"
                )
            decision = self._gate_engine.can_transition(
                stage_run.stage_run_id, StageState.RELEASED
            )
            if not decision.allowed:
                raise TransitionBlocked(
                    f"release blocked for {stage_run.stage_run_id}: {decision.reason}"
                )

        rollback_manifest = self._build_rollback_manifest(project_id, artifacts)
        transitions = [
            self._gate_engine.transition(
                stage_run.stage_run_id,
                StageState.RELEASED,
                actor=self._release_actor,
            )
            for stage_run in stage_runs
        ]
        gate_run_ids = _unique(
            gate_run_id
            for transition in transitions
            for gate_run_id in transition.gate_run_ids
        )
        approval_ids = _unique(
            transition.transition_id
            for stage_run in stage_runs
            for transition in self._gate_engine.list_transitions(stage_run.stage_run_id)
            if transition.to_state
            in {
                StageState.APPROVED,
                StageState.RELEASE_CANDIDATE,
                StageState.RELEASED,
            }
        )
        package = ReleasePackage(
            project_id=project_id,
            artifact_ids=normalized_ids,
            artifact_hashes={
                artifact.artifact_id: artifact.content_hash for artifact in artifacts
            },
            gate_run_ids=gate_run_ids,
            approval_ids=approval_ids,
            tool_versions=deepcopy(self._tool_versions),
            policy_version=self._policy_version,
            rollback_manifest=rollback_manifest,
        )
        self._packages[package.package_id] = _copy_package(package)
        self._latest_by_project[project_id] = package.package_id
        return _copy_package(package)

    def verify(self, package_id: str) -> ReleaseVerification:
        """Check that package provenance still matches current governed state."""
        package = self._get_package(package_id)
        missing_gate_runs: list[str] = []
        missing_approvals: list[str] = []
        errors: list[str] = []
        for artifact_id in package.artifact_ids:
            try:
                current = self._registry.artifacts.get(package.project_id, artifact_id)
            except KeyError:
                errors.append(f"missing artifact: {artifact_id}")
                continue
            if current.content_hash != package.artifact_hashes[artifact_id]:
                errors.append(f"artifact hash changed: {artifact_id}")

        for stage_run in self._stage_runs_for_artifacts(package.project_id, package.artifact_ids):
            if stage_run.state is not StageState.RELEASED:
                errors.append(
                    f"release stage is no longer released: {stage_run.stage_run_id}"
                )

        known_gate_runs = {
            gate_run.gate_run_id: gate_run
            for stage_run in self._gate_engine.list_stage_runs(package.project_id)
            for gate_run in self._gate_engine.list_gate_runs(stage_run.stage_run_id)
        }
        for gate_run_id in package.gate_run_ids:
            gate_run = known_gate_runs.get(gate_run_id)
            if gate_run is None:
                missing_gate_runs.append(gate_run_id)
                continue
            definition = self._gate_engine.get_definition(gate_run.gate_id)
            if (
                gate_run.result.value != "passed"
                or gate_run.stale
                or gate_run.definition_version != definition.version
                or gate_run.validator_version != definition.validator_version
                or gate_run.definition_fingerprint != definition.definition_fingerprint
            ):
                errors.append(f"gate run is not current and passed: {gate_run_id}")

        known_approvals = {
            transition.transition_id
            for stage_run in self._gate_engine.list_stage_runs(package.project_id)
            for transition in self._gate_engine.list_transitions(stage_run.stage_run_id)
        }
        missing_approvals.extend(
            approval_id
            for approval_id in package.approval_ids
            if approval_id not in known_approvals
        )
        return ReleaseVerification(
            passed=not missing_gate_runs and not missing_approvals and not errors,
            missing_gate_runs=missing_gate_runs,
            missing_approvals=missing_approvals,
            errors=errors,
        )

    def rollback(self, package_id: str) -> RollbackResult:
        """Append versions containing the prior artifact content; never delete history."""
        if package_id in self._rollbacks:
            return _copy_rollback(self._rollbacks[package_id])
        package = self._get_package(package_id)
        previous: dict[str, Artifact] = {}
        current: dict[str, Artifact] = {}
        for artifact_id in package.artifact_ids:
            versions = self._registry.artifacts.list_versions(package.project_id, artifact_id)
            manifest = package.rollback_manifest[artifact_id]
            previous_version = manifest.get("previous_version")
            if not previous_version:
                raise ValueError(f"no previous artifact version is available for {artifact_id}")
            current[artifact_id] = self._registry.artifacts.get(package.project_id, artifact_id)
            previous[artifact_id] = self._registry.artifacts.get(
                package.project_id, artifact_id, version=str(previous_version)
            )
            if not versions:
                raise KeyError(artifact_id)

        audit_id = str(uuid4())
        stage_runs = self._stage_runs_for_artifacts(package.project_id, package.artifact_ids)
        for stage_run in stage_runs:
            if stage_run.state is not StageState.RELEASED:
                raise TransitionBlocked(
                    f"stage run {stage_run.stage_run_id} is not released and cannot be rolled back"
                )
            self._gate_engine.transition(
                stage_run.stage_run_id,
                StageState.REMEDIATION,
                actor=self._release_actor,
            )
        restored: dict[str, Artifact] = {}
        for artifact_id, prior in previous.items():
            latest = current[artifact_id]
            restored[artifact_id] = Artifact.build(
                artifact_id=latest.artifact_id,
                project_id=latest.project_id,
                kind=prior.kind,
                version=_next_patch(latest.version),
                status="released",
                owner=prior.owner,
                content=deepcopy(prior.content),
                depends_on=deepcopy(prior.depends_on),
                evidence_refs=deepcopy(prior.evidence_refs),
                metadata={
                    **deepcopy(prior.metadata),
                    "rollback_of": package.package_id,
                    "rollback_audit_id": audit_id,
                },
            )
        transaction = self._registry.transaction()
        try:
            for artifact in restored.values():
                transaction.artifacts.put(artifact)
            transaction.commit()
        except BaseException:
            transaction.rollback()
            raise
        for artifact_id, artifact in restored.items():
            self._gate_engine.invalidate_for_artifact_change(
                artifact_id, artifact.content_hash
            )
        restored_ids = list(restored)
        previous_release_id = next(
            (
                str(manifest["previous_release_id"])
                for manifest in package.rollback_manifest.values()
                if manifest.get("previous_release_id")
            ),
            None,
        )
        result = RollbackResult(
            restored_artifact_ids=restored_ids,
            previous_release_id=previous_release_id,
            audit_id=audit_id,
        )
        self._rollbacks[package_id] = _copy_rollback(result)
        return _copy_rollback(result)

    def _stage_runs_for_artifacts(self, project_id: str, artifact_ids: list[str]) -> list[Any]:
        selected: list[Any] = []
        for artifact_id in artifact_ids:
            candidates = [
                stage_run
                for stage_run in self._gate_engine.list_stage_runs(project_id)
                if artifact_id in stage_run.output_artifact_ids
            ]
            if not candidates:
                raise KeyError(f"no governed stage run contains artifact: {artifact_id}")
            candidate = next(
                (
                    stage_run
                    for stage_run in reversed(candidates)
                    if stage_run.state is StageState.RELEASE_CANDIDATE
                ),
                candidates[-1],
            )
            if candidate.stage_run_id not in {run.stage_run_id for run in selected}:
                selected.append(candidate)
        return selected

    def _build_rollback_manifest(
        self, project_id: str, artifacts: list[Artifact]
    ) -> dict[str, dict[str, Any]]:
        previous_release_id = self._latest_by_project.get(project_id)
        manifest: dict[str, dict[str, Any]] = {}
        for artifact in artifacts:
            versions = self._registry.artifacts.list_versions(project_id, artifact.artifact_id)
            prior = versions[-2] if len(versions) >= 2 else None
            manifest[artifact.artifact_id] = {
                "released_version": artifact.version,
                "released_hash": artifact.content_hash,
                "previous_version": None if prior is None else prior.version,
                "previous_hash": None if prior is None else prior.content_hash,
                "previous_release_id": previous_release_id,
            }
        return manifest

    def _get_package(self, package_id: str) -> ReleasePackage:
        _require_identity(package_id, "package_id")
        try:
            return _copy_package(self._packages[package_id])
        except KeyError as exc:
            raise KeyError(f"unknown release package: {package_id}") from exc


def _copy_package(package: ReleasePackage) -> ReleasePackage:
    return ReleasePackage.model_validate(deepcopy(package.model_dump(mode="python")))


def _copy_rollback(result: RollbackResult) -> RollbackResult:
    return RollbackResult.model_validate(deepcopy(result.model_dump(mode="python")))


def _require_identity(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty identity")
    if value != value.strip():
        raise ValueError(f"{name} must use a canonical identity")


def _unique_identities(values: list[str], name: str) -> list[str]:
    if not isinstance(values, list) or not values:
        raise ValueError(f"{name} must be a non-empty list")
    for value in values:
        _require_identity(value, name)
    if len(set(values)) != len(values):
        raise ValueError(f"{name} must not contain duplicates")
    return list(values)


def _unique(values: Any) -> list[str]:
    return list(dict.fromkeys(values))


def _next_patch(version: str) -> str:
    major, minor, patch = semantic_version_key(version)
    return f"{major}.{minor}.{patch + 1}"


__all__ = [
    "ReleaseManager",
    "ReleasePackage",
    "ReleaseVerification",
    "RollbackResult",
]
