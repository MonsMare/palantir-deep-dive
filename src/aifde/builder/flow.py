"""End-to-end evidence-driven Ontology Builder orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from aifde.domain.gates import GateResult
from aifde.domain.stages import StageRun, StageState
from aifde.gates.engine import GateEngine
from aifde.gates.validators import ValidationContext, ValidationResult
from aifde.policy.capabilities import ActorRole, PolicyEngine
from aifde.domains import DomainAdapterRegistry

from .compiler import CompileResult, MappingCompiler
from .gates import BuilderGateReport, BuilderGateRunner, OntologyReleasePackage
from .semantic import (
    BuilderContext,
    CandidateProposal,
    CandidateProvider,
    DeterministicCandidateProvider,
    SemanticCandidateBuilder,
)
from .sources import SourceRegistry
from .contracts import SourceAsset, SourceSnapshot
from .persistence import SQLiteBuilderRegistry


@dataclass(frozen=True)
class BuilderRunConfig:
    project_id: str
    domain: str
    ontology_version: str
    actor_id: str
    source_paths: tuple[str, ...]
    approval_actor: str
    force_supplier_conflict: bool = False
    persistence_path: str | None = None
    domain_pack_id: str = "supplier-delay"


@dataclass
class BuilderRunResult:
    run_id: str
    state: str
    proposal: CandidateProposal
    compile_result: CompileResult
    gate_report: BuilderGateReport
    release_package: OntologyReleasePackage | None
    blocking_reasons: tuple[str, ...]
    builder_actor: str
    domain_pack_id: str = "supplier-delay"


class EvidenceDrivenOntologyBuilder:
    """Coordinate source capture, candidate building, compilation and gates."""

    def __init__(
        self,
        *,
        provider: CandidateProvider | None = None,
        compiler: MappingCompiler | None = None,
        policy: PolicyEngine | None = None,
        domain_registry: DomainAdapterRegistry | None = None,
    ) -> None:
        self.policy = policy or PolicyEngine()
        self.provider = provider
        self.compiler = compiler
        self.domain_registry = domain_registry or DomainAdapterRegistry()

    def run(self, config: BuilderRunConfig) -> BuilderRunResult:
        self._validate_config(config)
        adapter = self.domain_registry.get(config.domain_pack_id)
        run_id = f"ontology-builder:{uuid4()}"
        capture = adapter.capture(config.source_paths)
        registry, fragments, snapshots = (
            capture.registry,
            list(capture.fragments),
            capture.snapshots,
        )
        provider = self.provider or adapter.provider
        compiler = self.compiler or adapter.compiler
        builder_registry = (
            SQLiteBuilderRegistry(config.persistence_path)
            if config.persistence_path
            else None
        )
        if builder_registry is not None:
            for snapshot in snapshots:
                builder_registry.append_source_snapshot(snapshot)
        context = BuilderContext(
            project_id=config.project_id,
            domain=config.domain,
            ontology_version=config.ontology_version,
            known_terms=tuple(adapter.pack.vocabulary),
        )
        proposal = SemanticCandidateBuilder(provider).build(fragments, context)
        compile_result = compiler.compile(
            proposal, registry, version=config.ontology_version
        )
        if builder_registry is not None:
            builder_registry.append_compile_result(compile_result)
        gate_engine = GateEngine()
        gate_runner = BuilderGateRunner(gate_engine, policy=self.policy)
        gate_report = gate_runner.evaluate(
            proposal,
            compile_result,
            compiler=compiler,
            force_supplier_conflict=config.force_supplier_conflict,
        )
        stage_run, validation_context, input_hashes = self._register_stage(
            gate_engine,
            run_id=run_id,
            config=config,
            proposal=proposal,
            compile_result=compile_result,
            snapshots=snapshots,
        )
        self._advance_to_domain_review(gate_engine, run_id, config.actor_id)
        if not gate_report.all_required_gates_passed:
            # GateEngine intentionally checks failed results for every target,
            # including BLOCKED.  Enter the terminal stop before recording the
            # failed validator snapshot, then append the snapshot as evidence.
            gate_engine.transition(run_id, StageState.BLOCKED, actor="deterministic-verifier-1")
        self._record_gate_results(
            gate_engine,
            run_id=run_id,
            report=gate_report,
            context=validation_context,
            input_hashes=input_hashes,
        )
        if not gate_report.all_required_gates_passed:
            if builder_registry is not None:
                builder_registry.close()
            return BuilderRunResult(
                run_id=run_id,
                state=StageState.BLOCKED.value,
                proposal=proposal,
                compile_result=compile_result,
                gate_report=gate_report,
                release_package=None,
                blocking_reasons=gate_report.blocking_reasons,
                builder_actor=config.actor_id,
                domain_pack_id=config.domain_pack_id,
            )
        gate_engine.transition(run_id, StageState.APPROVED, actor=config.approval_actor)
        gate_engine.transition(
            run_id, StageState.RELEASE_CANDIDATE, actor=config.approval_actor
        )
        draft_result = BuilderRunResult(
            run_id=run_id,
            state=StageState.RELEASE_CANDIDATE.value,
            proposal=proposal,
            compile_result=compile_result,
            gate_report=gate_report,
            release_package=None,
            blocking_reasons=(),
            builder_actor=config.actor_id,
            domain_pack_id=config.domain_pack_id,
        )
        package = gate_runner.release(draft_result, config.approval_actor)
        gate_engine.transition(run_id, StageState.RELEASED, actor=config.approval_actor)
        if builder_registry is not None:
            builder_registry.append_release_manifest(package)
            builder_registry.close()
        draft_result.state = StageState.RELEASED.value
        draft_result.release_package = package
        return draft_result

    def _register_stage(
        self,
        engine: GateEngine,
        *,
        run_id: str,
        config: BuilderRunConfig,
        proposal: CandidateProposal,
        compile_result: CompileResult,
        snapshots: tuple[SourceSnapshot, ...],
    ) -> tuple[StageRun, ValidationContext, dict[str, str]]:
        if not snapshots:
            raise ValueError("Builder stage requires at least one source snapshot")
        input_ids = [f"{run_id}:source:{index}" for index, _ in enumerate(snapshots)]
        output_keys = ("ontology", "shapes", "mappings", "canonical_product", "provenance")
        output_ids = [f"{run_id}:artifact:{key}" for key in output_keys]
        stage = StageRun(
            stage_run_id=run_id,
            project_id=config.project_id,
            stage_id="ontology.design",
            state=StageState.DRAFT,
            actor=config.actor_id,
            input_artifact_ids=input_ids,
            output_artifact_ids=output_ids,
            evidence_refs=[item.snapshot_id for item in snapshots],
        )
        snapshot_hash = sha256(
            "".join(item.content_hash for item in snapshots).encode("utf-8")
        ).hexdigest()
        context = ValidationContext(
            stage_run_id=run_id,
            artifact_ids=input_ids + output_ids,
            evidence_snapshot_id=snapshots[0].snapshot_id,
            evidence_snapshot_hash=snapshot_hash,
            configuration={
                "builder_version": "evidence-driven-builder-v1",
                "ontology_version": config.ontology_version,
                "proposal_evidence_count": len(proposal.evidence_refs),
            },
        )
        input_hashes = {
            input_id: snapshot.content_hash
            for input_id, snapshot in zip(input_ids, snapshots, strict=True)
        }
        input_hashes.update(
            {
                artifact_id: compile_result.artifact_hashes[key]
                for artifact_id, key in zip(output_ids, output_keys, strict=True)
            }
        )
        engine.register_stage_run(
            stage, builder_actor=config.actor_id, validation_context=context
        )
        return stage, context, input_hashes

    @staticmethod
    def _advance_to_domain_review(engine: GateEngine, run_id: str, actor: str) -> None:
        engine.transition(run_id, StageState.VALIDATING, actor=actor)
        engine.transition(run_id, StageState.CHALLENGING, actor=actor)
        engine.transition(run_id, StageState.DOMAIN_REVIEW, actor=actor)

    @staticmethod
    def _record_gate_results(
        engine: GateEngine,
        *,
        run_id: str,
        report: BuilderGateReport,
        context: ValidationContext,
        input_hashes: dict[str, str],
    ) -> None:
        for gate_id, passed in report.statuses:
            definition = engine.get_definition(gate_id)
            violations = [] if passed else list(report.blocking_reasons) or [f"{gate_id} failed"]
            result = ValidationResult(
                passed=passed,
                violations=violations,
                warnings=[],
                evidence_refs=[context.evidence_snapshot_id, *report.evidence_refs],
                validator_version=definition.validator_version,
                input_hashes=input_hashes,
            )
            engine.register_result(
                run_id,
                gate_id=gate_id,
                result=result,
                context=context,
                gate_result=GateResult.PASSED if passed else GateResult.FAILED,
            )

    def _validate_config(self, config: BuilderRunConfig) -> None:
        if not isinstance(config, BuilderRunConfig):
            raise TypeError("config must be a BuilderRunConfig")
        for field in ("project_id", "domain", "ontology_version", "actor_id", "approval_actor", "domain_pack_id"):
            if not getattr(config, field).strip():
                raise ValueError(f"{field} must not be empty")
        adapter = self.domain_registry.get(config.domain_pack_id)
        if config.domain != adapter.pack.domain:
            raise ValueError(
                f"domain {config.domain!r} does not match Domain Pack {config.domain_pack_id!r}"
            )
        if self.policy.role_for(config.actor_id) != ActorRole.BUILDER.value:
            raise PermissionError("actor_id must be a trusted Builder")
        if config.actor_id == config.approval_actor:
            raise PermissionError("Builder actor cannot approve or release its own run")
        if self.policy.role_for(config.approval_actor) not in {
            ActorRole.DOMAIN_OWNER.value,
            ActorRole.RELEASE_OWNER.value,
        }:
            raise PermissionError("approval_actor must be a trusted domain or release owner")


__all__ = ["BuilderRunConfig", "BuilderRunResult", "EvidenceDrivenOntologyBuilder"]
