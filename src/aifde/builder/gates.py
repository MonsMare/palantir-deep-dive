"""Builder-specific gate evaluation and release packaging.

The evaluator computes deterministic facts; ``GateEngine`` remains the only
component allowed to mutate stage state.  This split is intentional: a Builder
can propose a gate outcome, but it cannot turn that outcome into approval or a
release without the audited transition service.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from aifde.domain.stages import StageState
from aifde.gates.engine import GateEngine
from aifde.policy.capabilities import ActorRole, PolicyEngine

from .compiler import CompileResult, MappingCompiler
from .semantic import CandidateProposal


_GATE_ORDER = (
    "reality.consistency",
    "evidence.coverage",
    "semantic.integrity",
    "data.quality",
    "executable.readiness",
    "adversarial.challenge",
    "business.exception_coverage",
    "release.governance",
)


@dataclass(frozen=True)
class BuilderGateReport:
    """The deterministic gate posture for one Builder candidate."""

    statuses: tuple[tuple[str, bool], ...]
    hard_failures: tuple[str, ...] = ()
    soft_failures: tuple[str, ...] = ()
    blocking_reasons: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()

    @property
    def all_hard_gates_passed(self) -> bool:
        return not self.hard_failures

    @property
    def all_required_gates_passed(self) -> bool:
        """Whether hard gates pass and no soft gate awaits a waiver."""

        return not self.hard_failures and not self.soft_failures

    @property
    def status_by_gate(self) -> dict[str, bool]:
        return dict(self.statuses)


@dataclass(frozen=True)
class OntologyReleasePackage:
    """Content-addressed manifest for the simulated ontology release."""

    release_id: str
    ontology_version: str
    ontology_artifact_hash: str
    shape_artifact_hash: str
    mapping_artifact_hash: str
    canonical_product_artifact_hash: str
    provenance_artifact_hash: str
    canonical_rdf_artifact_hash: str
    gate_run_ids: tuple[str, ...]
    approval_ids: tuple[str, ...]
    dependency_versions: tuple[tuple[str, str], ...]
    source_evidence_refs: tuple[str, ...]
    rollback_target: str | None
    released_at: datetime


class BuilderGateRunner:
    """Evaluate Builder invariants and build a package after approval."""

    def __init__(self, gate_engine: GateEngine, *, policy: PolicyEngine | None = None) -> None:
        if not isinstance(gate_engine, GateEngine):
            raise TypeError("gate_engine must be a GateEngine")
        self._gate_engine = gate_engine
        self._policy = policy or PolicyEngine()

    def evaluate(
        self,
        proposal: CandidateProposal,
        compile_result: CompileResult,
        *,
        compiler: Any | None = None,
        force_supplier_conflict: bool = False,
    ) -> BuilderGateReport:
        if not isinstance(proposal, CandidateProposal):
            raise TypeError("proposal must be a CandidateProposal")
        if not isinstance(compile_result, CompileResult):
            raise TypeError("compile_result must be a CompileResult")

        try:
            compiler_is_valid = (compiler or MappingCompiler()).validate(compile_result).passed
        except (TypeError, ValueError):
            compiler_is_valid = False
        statuses: dict[str, bool] = {
            "reality.consistency": bool(proposal.evidence_refs and compile_result.canonical_rows),
            "evidence.coverage": self._evidence_is_closed(proposal, compile_result),
            "semantic.integrity": compiler_is_valid,
            "data.quality": self._data_is_temporally_safe(compile_result),
            "executable.readiness": self._mapping_is_executable(compile_result),
            "adversarial.challenge": True,
            "business.exception_coverage": self._business_exception_coverage(
                proposal, compile_result
            ),
            "release.governance": True,
        }
        reasons: list[str] = []
        used_supplier_ids = {
            str(row.get("supplier_resolution", {}).get("candidate_id"))
            for row in compile_result.canonical_rows
            if isinstance(row.get("supplier_resolution"), dict)
            and row.get("supplier_resolution", {}).get("candidate_id")
        }
        matches_by_candidate = {
            item.candidate_id: item for item in proposal.entity_matches
        }
        blocked_supplier_matches = []
        if compile_result.domain_pack_id != "supplier-delay":
            used_supplier_ids = set()
        for candidate_id in sorted(used_supplier_ids):
            match = matches_by_candidate.get(candidate_id)
            if match is None:
                blocked_supplier_matches.append(f"{candidate_id}:missing-match")
                continue
            if match.status == "unresolved":
                blocked_supplier_matches.append(f"{candidate_id}:unresolved")
            elif match.status == "probable_match" and match.conflict_refs:
                blocked_supplier_matches.append(f"{candidate_id}:probable-match-conflict")
        if force_supplier_conflict:
            blocked_supplier_matches.append("supplier:forced-conflict:unresolved")
        if blocked_supplier_matches:
            statuses["adversarial.challenge"] = False
            reasons.append(
                "entity conflict: non-confirmed high-impact supplier resolution(s): "
                + ", ".join(sorted(set(blocked_supplier_matches)))
            )

        for gate_id, passed in statuses.items():
            if passed:
                continue
            definition = self._gate_engine.get_definition(gate_id)
            if definition.severity == "hard":
                reasons.append(f"{gate_id} failed") if gate_id not in {
                    "adversarial.challenge"
                } else None

        hard_failures = tuple(
            gate_id
            for gate_id, passed in statuses.items()
            if not passed and self._gate_engine.get_definition(gate_id).severity == "hard"
        )
        soft_failures = tuple(
            gate_id
            for gate_id, passed in statuses.items()
            if not passed and self._gate_engine.get_definition(gate_id).severity == "soft"
        )
        return BuilderGateReport(
            statuses=tuple((gate_id, statuses[gate_id]) for gate_id in _GATE_ORDER),
            hard_failures=hard_failures,
            soft_failures=soft_failures,
            blocking_reasons=tuple(dict.fromkeys(reasons)),
            evidence_refs=tuple(
                dict.fromkeys(
                    (*proposal.evidence_refs, *compile_result.validation_report.evidence_refs)
                )
            ),
        )

    def release(self, result: Any, approval_actor: str) -> OntologyReleasePackage:
        """Create a package only for a governed release-candidate state."""

        if not isinstance(approval_actor, str) or not approval_actor.strip():
            raise ValueError("approval_actor must be a non-empty identity")
        if getattr(result, "builder_actor", None) == approval_actor:
            raise PermissionError("Builder actor cannot approve or release its own run")
        role = self._policy.role_for(approval_actor)
        if role not in {ActorRole.DOMAIN_OWNER.value, ActorRole.RELEASE_OWNER.value}:
            raise PermissionError("approval_actor must be a trusted domain or release owner")
        if getattr(result, "state", None) != StageState.RELEASE_CANDIDATE.value:
            raise ValueError("release package requires a release_candidate Builder run")
        report = result.gate_report
        if not report.all_required_gates_passed:
            raise PermissionError("Builder gates have not passed or a soft gate awaits waiver")
        compile_result = result.compile_result
        stage_run_id = result.run_id
        stage_run = self._gate_engine.get_stage_run(stage_run_id)
        if stage_run.state is not StageState.RELEASE_CANDIDATE:
            raise ValueError("GateEngine stage is not release_candidate")
        decision = self._gate_engine.can_transition(stage_run_id, StageState.RELEASED)
        if not decision.allowed:
            raise PermissionError(
                "GateEngine refused release: "
                + ", ".join(decision.blocking_gate_ids or [decision.reason])
            )
        gate_runs = self._gate_engine.list_gate_runs(stage_run_id)
        transitions = self._gate_engine.list_transitions(stage_run_id)
        hashes = compile_result.artifact_hashes
        return OntologyReleasePackage(
            release_id=f"ontology-release:{uuid4()}",
            ontology_version=compile_result.ontology_candidate.version,
            ontology_artifact_hash=hashes["ontology"],
            shape_artifact_hash=hashes["shapes"],
            mapping_artifact_hash=hashes["mappings"],
            canonical_product_artifact_hash=hashes["canonical_product"],
            provenance_artifact_hash=hashes["provenance"],
            canonical_rdf_artifact_hash=hashes["canonical_rdf"],
            gate_run_ids=tuple(item.gate_run_id for item in gate_runs),
            approval_ids=tuple(
                item.transition_id
                for item in transitions
                if item.to_state
                in {StageState.APPROVED, StageState.RELEASE_CANDIDATE}
            ),
            dependency_versions=(
                ("builder", "evidence-driven-builder-v1"),
                ("compiler", compile_result.validation_report.compiler_version),
                ("gate-policy", "built-in-gates-1.0.0"),
            ),
            source_evidence_refs=tuple(report.evidence_refs),
            rollback_target=None,
            released_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _evidence_is_closed(proposal: CandidateProposal, result: CompileResult) -> bool:
        known = set(proposal.evidence_refs)
        if not known or len(result.canonical_rows) != len(result.provenance_rows):
            return False
        provenance_by_id = {
            str(item.get("target_id")): item for item in result.provenance_rows
        }
        return all(
            str(row.get(result.primary_key_field)) in provenance_by_id
            and set(row.get("evidence_refs", ())).issubset(known)
            and set(
                provenance_by_id[str(row.get(result.primary_key_field))].get(
                    "evidence_refs", ()
                )
            )
            == set(row.get("evidence_refs", ()))
            for row in result.canonical_rows
        )

    @staticmethod
    def _data_is_temporally_safe(result: CompileResult) -> bool:
        for row in result.canonical_rows:
            if any(row.get(field) in (None, "") for field in result.required_fields):
                return False
            if row.get("observed_at", "") > row.get("available_at", ""):
                return False
        return bool(result.canonical_rows)

    @staticmethod
    def _mapping_is_executable(result: CompileResult) -> bool:
        mapping_ids = {item.mapping_id for item in result.mapping_specs}
        return bool(mapping_ids) and all(
            set(row.get("mapping_ids", ())).issubset(mapping_ids)
            and row.get("mapping_ids")
            for row in result.canonical_rows
        )

    @staticmethod
    def _business_exception_coverage(
        proposal: CandidateProposal, result: CompileResult
    ) -> bool:
        if result.domain_pack_id != "supplier-delay":
            return result.business_exception_coverage
        return any(
            item.assertion_type == "fact" and item.predicate == "actualDeliveryDate"
            for item in proposal.assertions
        )


__all__ = ["BuilderGateReport", "BuilderGateRunner", "OntologyReleasePackage"]
