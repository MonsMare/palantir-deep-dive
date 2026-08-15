"""Governed deterministic evaluator for the software-delivery Shipyard slice."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

import yaml

from aifde.domain.artifacts import Artifact, canonical_json_bytes
from aifde.gates.engine import GateEngine
from aifde.shipyard.contracts import GateReviewSnapshot
from aifde.shipyard.provenance import (
    ArtifactInputSnapshot,
    SOFTWARE_DELIVERY_ARTIFACT_IDS,
    SOFTWARE_DELIVERY_ARTIFACT_ORDER,
    SOFTWARE_DELIVERY_ARTIFACT_SPECS,
    build_artifact_input_snapshot,
)


_RELEASE_GOVERNANCE_STAGES = frozenset(
    {
        "requirements.alignment",
        "ontology.design",
        "data_product.build",
        "prediction.validation",
        "decision.optimization",
        "application.acceptance",
    }
)


@dataclass(frozen=True, slots=True)
class SandboxPipelineReport:
    """Local sandbox result used as an additional, never substitutive check."""

    stage_states: dict[str, str]
    evidence_refs: list[str]


@dataclass(frozen=True, slots=True)
class ArtifactEvaluation:
    """Semantic result for the exact registered Artifact set."""

    input_snapshot: ArtifactInputSnapshot
    artifact_digests: dict[str, str]
    semantic_results: dict[str, str]
    evidence_refs: list[str]
    violations: list[str]


@dataclass(frozen=True, slots=True)
class GovernedEvaluation:
    """Complete evaluator output used to derive immutable Gate snapshots."""

    artifact_evaluation: ArtifactEvaluation
    stage_states: dict[str, str]
    evidence_refs: list[str]
    violations: list[str]


def run_software_delivery_evaluator(
    artifacts: Sequence[Artifact],
    *,
    source_root: Path,
    extra_violations: Sequence[str] = (),
) -> GovernedEvaluation:
    """Evaluate registered Artifact semantics before running the sandbox pipeline."""

    artifact_evaluation = evaluate_registered_artifacts(
        artifacts,
        source_root=source_root,
    )
    violations = sorted(
        set([*artifact_evaluation.violations, *extra_violations])
    )
    report = SandboxPipelineReport(
        stage_states={},
        evidence_refs=["pipeline:software-delivery:artifact-evaluator:v1"],
    )
    if not violations:
        report = run_sandbox_pipeline(source_root)
        if not report.stage_states:
            violations.append(
                "sandbox pipeline produced no stage states; evaluator outcome is unverifiable"
            )
    evidence_refs = sorted(
        {
            "evaluator:software-delivery:artifact-semantics:v1",
            "pipeline:software-delivery:software-delivery-demo:sandbox:v1",
            *artifact_evaluation.input_snapshot.evidence_refs,
            *artifact_evaluation.evidence_refs,
            *report.evidence_refs,
        }
    )
    return GovernedEvaluation(
        artifact_evaluation=artifact_evaluation,
        stage_states=report.stage_states,
        evidence_refs=evidence_refs,
        violations=violations,
    )


def evaluate_registered_artifacts(
    artifacts: Sequence[Artifact],
    *,
    source_root: Path,
) -> ArtifactEvaluation:
    """Read and semantically validate every registered Artifact and its source."""

    input_snapshot = build_artifact_input_snapshot(
        artifacts,
        source_root=source_root,
    )
    by_id = {artifact.artifact_id: artifact for artifact in artifacts}
    violations = list(input_snapshot.violations)
    provided_ids = set(by_id)
    missing_ids = sorted(SOFTWARE_DELIVERY_ARTIFACT_IDS - provided_ids)
    extra_ids = sorted(provided_ids - SOFTWARE_DELIVERY_ARTIFACT_IDS)
    if missing_ids:
        violations.append(
            "artifact evaluator missing registered Artifact(s): "
            + ", ".join(missing_ids)
        )
    if extra_ids:
        violations.append(
            "artifact evaluator received unexpected Artifact(s): "
            + ", ".join(extra_ids)
        )
    if provided_ids != SOFTWARE_DELIVERY_ARTIFACT_IDS:
        violations.append(
            "artifact evaluator must consume all six software-delivery Artifacts"
        )

    artifact_digests: dict[str, str] = {}
    semantic_results: dict[str, str] = {}
    evidence_refs: set[str] = {
        "evaluator:software-delivery:artifact-semantics:v1"
    }
    for artifact_id in SOFTWARE_DELIVERY_ARTIFACT_ORDER:
        artifact = by_id.get(artifact_id)
        if artifact is None:
            semantic_violations = ["registered Artifact is missing"]
            semantic_status = "blocked"
            document: Any = None
            source_sha256 = ""
        else:
            semantic_violations, document, source_sha256 = _validate_artifact_semantics(
                artifact,
                source_root=source_root,
            )
            semantic_status = "passed" if not semantic_violations else "blocked"
        if semantic_violations:
            violations.extend(
                f"Artifact {artifact_id} semantic validation: {violation}"
                for violation in semantic_violations
            )
        semantic_results[artifact_id] = semantic_status
        digest_payload = {
            "artifact_id": artifact_id,
            "kind": artifact.kind if artifact is not None else "<missing>",
            "version": artifact.version if artifact is not None else "<missing>",
            "content_hash": artifact.content_hash if artifact is not None else "<missing>",
            "registered_content": artifact.content if artifact is not None else None,
            "source_path": SOFTWARE_DELIVERY_ARTIFACT_SPECS[artifact_id].relative_path,
            "source_sha256": source_sha256,
            "semantic_status": semantic_status,
            "semantic_violations": semantic_violations,
            "document": document,
        }
        digest = sha256(canonical_json_bytes(digest_payload)).hexdigest()
        artifact_digests[artifact_id] = digest
        evidence_refs.add(f"artifact-evaluator:{artifact_id}:{digest}")

    return ArtifactEvaluation(
        input_snapshot=input_snapshot,
        artifact_digests=artifact_digests,
        semantic_results=semantic_results,
        evidence_refs=sorted(evidence_refs),
        violations=sorted(set(violations)),
    )


def build_software_delivery_gate_reviews(
    workspace_id: str,
    required_gate_ids: Sequence[str],
    artifacts: Sequence[Artifact],
    *,
    source_root: Path,
    extra_violations: Sequence[str] = (),
) -> list[GateReviewSnapshot]:
    """Derive Gate snapshots from the governed evaluator output."""

    evaluation = run_software_delivery_evaluator(
        artifacts,
        source_root=source_root,
        extra_violations=extra_violations,
    )
    engine = GateEngine()
    reviews: list[GateReviewSnapshot] = []
    for gate_id in sorted(required_gate_ids):
        definition = engine.get_definition(gate_id)
        if evaluation.violations:
            status = "blocked"
            violations = list(evaluation.violations)
        else:
            status, violations = _gate_status(gate_id, evaluation.stage_states)
        violations = sorted(set(violations))
        stale = bool(evaluation.violations)
        gate_run_id = (
            f"snapshot:{workspace_id}:{gate_id}:"
            f"{evaluation.artifact_evaluation.input_snapshot.input_snapshot_hash[:16]}"
        )
        snapshot_values = {
            "gate_run_id": gate_run_id,
            "revision": 1,
            "workspace_id": workspace_id,
            "gate_id": gate_id,
            "severity": definition.severity,
            "status": status,
            "artifact_hashes": evaluation.artifact_evaluation.input_snapshot.artifact_hashes,
            "artifact_versions": evaluation.artifact_evaluation.input_snapshot.artifact_versions,
            "source_snapshot_id": evaluation.artifact_evaluation.input_snapshot.source_snapshot_id,
            "source_snapshot_hash": evaluation.artifact_evaluation.input_snapshot.source_snapshot_hash,
            "input_snapshot_hash": evaluation.artifact_evaluation.input_snapshot.input_snapshot_hash,
            "validator_version": definition.validator_version,
            "definition_fingerprint": definition.definition_fingerprint,
            "violations": violations,
            "warnings": [],
            "evidence_refs": evaluation.evidence_refs,
            "stale": stale,
        }
        snapshot_values["outcome_attestation"] = build_gate_outcome_attestation(
            **snapshot_values,
            stage_states=evaluation.stage_states,
        )
        reviews.append(
            GateReviewSnapshot(
                **snapshot_values,
                created_at=_gate_snapshot_created_at(),
            )
        )
    return reviews


def build_gate_outcome_attestation(
    *,
    gate_run_id: str,
    revision: int,
    workspace_id: str,
    gate_id: str,
    severity: str,
    status: str,
    artifact_hashes: Mapping[str, str],
    artifact_versions: Mapping[str, str],
    source_snapshot_id: str,
    source_snapshot_hash: str,
    input_snapshot_hash: str,
    validator_version: str,
    definition_fingerprint: str,
    violations: Sequence[str],
    warnings: Sequence[str],
    evidence_refs: Sequence[str],
    stale: bool,
    stage_states: Mapping[str, str],
) -> str:
    """Hash the complete evaluator outcome, including final status/violations."""

    payload = {
        "gate_run_id": gate_run_id,
        "revision": revision,
        "workspace_id": workspace_id,
        "gate_id": gate_id,
        "severity": severity,
        "status": status,
        "artifact_hashes": dict(artifact_hashes),
        "artifact_versions": dict(artifact_versions),
        "source_snapshot_id": source_snapshot_id,
        "source_snapshot_hash": source_snapshot_hash,
        "input_snapshot_hash": input_snapshot_hash,
        "validator_version": validator_version,
        "definition_fingerprint": definition_fingerprint,
        "violations": sorted(violations),
        "warnings": sorted(warnings),
        "evidence_refs": sorted(evidence_refs),
        "stale": stale,
        "stage_states": dict(stage_states),
    }
    return sha256(canonical_json_bytes(payload)).hexdigest()


def run_sandbox_pipeline(project_root: Path) -> SandboxPipelineReport:
    """Run the existing local pipeline as a supplementary sandbox check."""

    try:
        from software_delivery_demo.pipeline import run_demo_pipeline
    except ModuleNotFoundError as exc:
        if exc.name not in {"polars", "sklearn", "rdflib", "pyshacl"}:
            raise
        return SandboxPipelineReport(
            stage_states={},
            evidence_refs=[
                "pipeline:software-delivery:sandbox-unavailable:v1",
                f"pipeline:software-delivery:missing-dependency:{exc.name}",
            ],
        )
    report = run_demo_pipeline(project_root)
    return SandboxPipelineReport(
        stage_states=report.stage_states,
        evidence_refs=report.evidence_refs,
    )


def _validate_artifact_semantics(
    artifact: Artifact,
    *,
    source_root: Path,
) -> tuple[list[str], Any, str]:
    spec = SOFTWARE_DELIVERY_ARTIFACT_SPECS.get(artifact.artifact_id)
    if spec is None:
        return ["Artifact ID is not in the fixed software-delivery mapping"], None, ""
    violations: list[str] = []
    content = artifact.content
    if not isinstance(content, Mapping):
        return ["content must be a document envelope"], None, ""
    if content.get("format") != spec.format:
        violations.append(
            f"expected content format {spec.format}, got {content.get('format', '<missing>')}"
        )
    document = content.get("document")
    source_file = (source_root / spec.relative_path).resolve()
    source_sha256 = ""
    source_document: Any = None
    if not _is_within(source_file, source_root.resolve()):
        violations.append("expected source path escapes source root")
    elif not source_file.is_file():
        violations.append("expected source file is missing")
    else:
        raw_bytes = source_file.read_bytes()
        source_sha256 = sha256(raw_bytes).hexdigest()
        try:
            source_document = _parse_document(raw_bytes, spec.format)
        except (UnicodeDecodeError, ValueError, yaml.YAMLError) as exc:
            violations.append(f"source document cannot be parsed: {exc}")
    if source_document is not None and document != source_document:
        violations.append("registered canonical content differs from expected source document")
    violations.extend(_semantic_document_violations(spec.key, document))
    return violations, document, source_sha256


def _semantic_document_violations(key: str, document: Any) -> list[str]:
    if key == "ontology-model":
        if not isinstance(document, str) or not document.strip():
            return ["ontology document must be non-empty Turtle text"]
        required_fragments = (
            "@prefix ex: <urn:software-delivery:>",
            "ex:ontology a ex:Ontology",
            "ex:Class",
        )
        return [
            f"ontology Turtle is missing required semantic fragment: {fragment}"
            for fragment in required_fragments
            if fragment not in document
        ]
    spec = next(
        spec
        for spec in SOFTWARE_DELIVERY_ARTIFACT_SPECS.values()
        if spec.key == key
    )
    if not isinstance(document, Mapping) or not document:
        return ["document must be a non-empty YAML mapping"]
    missing = sorted(set(spec.required_keys) - set(document))
    violations = ["missing required keys: " + ", ".join(missing)] if missing else []
    if key == "project-charter":
        for field in (
            "seed",
            "teams",
            "people",
            "modules",
            "sprints",
            "requirements",
            "work_items",
            "change_requests",
            "start_date",
            "sprint_length_days",
            "ingestion_delay_days",
        ):
            value = document.get(field)
            if value in (None, "") or (
                isinstance(value, (int, float)) and value < 0
            ):
                violations.append(f"{field} must be a non-negative configured value")
    elif key == "decision-contract":
        for field in ("variables", "objective_terms", "hard_constraints"):
            if not isinstance(document.get(field), list) or not document[field]:
                violations.append(f"{field} must be a non-empty list")
    elif key == "data-product":
        if not isinstance(document.get("products"), Mapping) or not document["products"]:
            violations.append("products must be a non-empty mapping")
        if not isinstance(document.get("quality_rules"), list) or not document["quality_rules"]:
            violations.append("quality_rules must be a non-empty list")
    elif key == "feature-catalog":
        features = document.get("features")
        if not isinstance(features, list) or not features:
            violations.append("features must be a non-empty list")
        else:
            required_feature_keys = {
                "feature_id",
                "entity_type",
                "grain",
                "window",
                "as_of_time",
                "availability_lag",
                "missing_policy",
                "version",
                "lineage",
                "leakage_policy",
            }
            for index, feature in enumerate(features):
                if not isinstance(feature, Mapping):
                    violations.append(f"features[{index}] must be a mapping")
                    continue
                missing_feature_keys = sorted(required_feature_keys - set(feature))
                if missing_feature_keys:
                    violations.append(
                        f"features[{index}] missing required keys: "
                        + ", ".join(missing_feature_keys)
                    )
    elif key == "model-policy":
        policy = document.get("release_policy")
        if not isinstance(policy, Mapping) or not policy:
            violations.append("release_policy must be a non-empty mapping")
        else:
            required_policy_keys = {
                "baseline_mae_must_not_be_worse",
                "p80_coverage_minimum",
                "leakage_required",
                "temporal_windows_minimum",
                "fallback_model",
            }
            missing_policy_keys = sorted(required_policy_keys - set(policy))
            if missing_policy_keys:
                violations.append(
                    "release_policy missing required keys: "
                    + ", ".join(missing_policy_keys)
                )
    return violations


def _parse_document(raw_bytes: bytes, format_name: str) -> Any:
    text = raw_bytes.decode("utf-8")
    if format_name == "turtle":
        return text
    if format_name == "yaml":
        document = yaml.safe_load(text)
        return {} if document is None else document
    raise ValueError(f"unsupported document format: {format_name}")


def _is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _gate_status(
    gate_id: str,
    stage_states: Mapping[str, str],
) -> tuple[str, list[str]]:
    if gate_id == "semantic.integrity":
        stage_id = "ontology.design"
        passed = stage_states.get(stage_id) in {"approved", "passed"}
        return (
            "passed" if passed else "blocked",
            [] if passed else [f"sandbox pipeline stage blocked: {stage_id}"],
        )
    if gate_id == "release.governance":
        blocked = sorted(
            stage_id
            for stage_id in _RELEASE_GOVERNANCE_STAGES
            if stage_states.get(stage_id) not in {"approved", "passed"}
        )
        return (
            "passed" if not blocked else "blocked",
            [] if not blocked else [
                "sandbox pipeline stages blocked: " + ", ".join(blocked)
            ],
        )
    raise ValueError(f"software-delivery gate adapter does not define {gate_id}")


def _gate_snapshot_created_at():
    from datetime import datetime, timezone

    return datetime(2026, 8, 15, 0, 5, tzinfo=timezone.utc)


__all__ = [
    "ArtifactEvaluation",
    "GovernedEvaluation",
    "SandboxPipelineReport",
    "build_gate_outcome_attestation",
    "build_software_delivery_gate_reviews",
    "evaluate_registered_artifacts",
    "run_sandbox_pipeline",
    "run_software_delivery_evaluator",
]
