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


@dataclass(frozen=True)
class BuilderRunConfig:
    project_id: str
    domain: str
    ontology_version: str
    actor_id: str
    source_paths: tuple[str, ...]
    approval_actor: str
    force_supplier_conflict: bool = False


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


class EvidenceDrivenOntologyBuilder:
    """Coordinate source capture, candidate building, compilation and gates."""

    def __init__(
        self,
        *,
        provider: CandidateProvider | None = None,
        compiler: MappingCompiler | None = None,
        policy: PolicyEngine | None = None,
    ) -> None:
        self.policy = policy or PolicyEngine()
        self.provider = provider or DeterministicCandidateProvider()
        self.compiler = compiler or MappingCompiler()

    def run(self, config: BuilderRunConfig) -> BuilderRunResult:
        self._validate_config(config)
        run_id = f"ontology-builder:{uuid4()}"
        registry, fragments, snapshots = self._capture_sources(config)
        context = BuilderContext(
            project_id=config.project_id,
            domain=config.domain,
            ontology_version=config.ontology_version,
            known_terms=("supplier", "purchase order", "promised date", "delivery event"),
        )
        proposal = SemanticCandidateBuilder(self.provider).build(fragments, context)
        compile_result = self.compiler.compile(
            proposal, registry, version=config.ontology_version
        )
        gate_engine = GateEngine()
        gate_runner = BuilderGateRunner(gate_engine, policy=self.policy)
        gate_report = gate_runner.evaluate(
            proposal,
            compile_result,
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
            return BuilderRunResult(
                run_id=run_id,
                state=StageState.BLOCKED.value,
                proposal=proposal,
                compile_result=compile_result,
                gate_report=gate_report,
                release_package=None,
                blocking_reasons=gate_report.blocking_reasons,
                builder_actor=config.actor_id,
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
        )
        package = gate_runner.release(draft_result, config.approval_actor)
        gate_engine.transition(run_id, StageState.RELEASED, actor=config.approval_actor)
        draft_result.state = StageState.RELEASED.value
        draft_result.release_package = package
        return draft_result

    def _capture_sources(
        self, config: BuilderRunConfig
    ) -> tuple[SourceRegistry, list[Any], tuple[SourceSnapshot, SourceSnapshot]]:
        if len(config.source_paths) != 2:
            raise ValueError("supplier-delay Builder requires exactly two source paths")
        root = Path(config.source_paths[0]).parent.parent
        json_path = Path(config.source_paths[0])
        notes_path = Path(config.source_paths[1])
        if not json_path.exists() or not notes_path.exists():
            raise FileNotFoundError("Builder source path does not exist")
        registry = SourceRegistry()
        json_asset = registry.register(
            SourceAsset.register(
                "erp-purchase-orders",
                f"file://{json_path.as_posix()}",
                "json",
                "procurement",
                5,
                "internal",
                "policy:procurement",
                "purchase-order-v1",
                {"format": "json", "project_root": str(root)},
            )
        )
        notes_asset = registry.register(
            SourceAsset.register(
                "procurement-notes",
                f"file://{notes_path.as_posix()}",
                "markdown",
                "procurement",
                3,
                "internal",
                "policy:procurement",
                "notes-v1",
                {"format": "markdown", "project_root": str(root)},
            )
        )
        json_snapshot = registry.capture(
            json_asset.source_asset_id,
            "2026-08-13",
            json_path.read_bytes(),
            datetime(2026, 8, 13, 9, tzinfo=timezone.utc),
            datetime(2026, 8, 13, 10, tzinfo=timezone.utc),
            "raw-v1",
        )
        notes_snapshot = registry.capture(
            notes_asset.source_asset_id,
            "2026-09-08",
            notes_path.read_bytes(),
            datetime(2026, 9, 7, 12, tzinfo=timezone.utc),
            datetime(2026, 9, 8, 12, tzinfo=timezone.utc),
            "raw-v1",
        )
        document = json.loads(json_path.read_text(encoding="utf-8"))
        orders = document.get("purchase_orders", [])
        fragments = [
            registry.slice(
                json_snapshot.snapshot_id,
                f"$.purchase_orders[{index}]",
                json.dumps(order, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            )
            for index, order in enumerate(orders)
        ]
        fragments.append(
            registry.slice(
                notes_snapshot.snapshot_id,
                "line:3-5",
                "\n".join(notes_path.read_text(encoding="utf-8").splitlines()[2:5]),
                event_time=datetime(2026, 9, 7, 12, tzinfo=timezone.utc),
            )
        )
        return registry, fragments, (json_snapshot, notes_snapshot)

    def _register_stage(
        self,
        engine: GateEngine,
        *,
        run_id: str,
        config: BuilderRunConfig,
        proposal: CandidateProposal,
        compile_result: CompileResult,
        snapshots: tuple[SourceSnapshot, SourceSnapshot],
    ) -> tuple[StageRun, ValidationContext, dict[str, str]]:
        input_ids = [f"{run_id}:source:json", f"{run_id}:source:notes"]
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
            evidence_refs=[snapshots[0].snapshot_id, snapshots[1].snapshot_id],
        )
        snapshot_hash = sha256(
            (snapshots[0].content_hash + snapshots[1].content_hash).encode("utf-8")
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
            input_ids[0]: snapshots[0].content_hash,
            input_ids[1]: snapshots[1].content_hash,
            **{
                artifact_id: compile_result.artifact_hashes[key]
                for artifact_id, key in zip(output_ids, output_keys, strict=True)
            },
        }
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
        for field in ("project_id", "domain", "ontology_version", "actor_id", "approval_actor"):
            if not getattr(config, field).strip():
                raise ValueError(f"{field} must not be empty")
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
