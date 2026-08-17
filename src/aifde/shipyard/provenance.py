"""Deterministic input and source provenance for Workbench gate runs."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from aifde.domain.artifacts import Artifact, canonical_json_bytes, content_hash_for


@dataclass(frozen=True, slots=True)
class SoftwareDeliveryArtifactSpec:
    """Evaluator-owned source and semantic contract for one seed Artifact."""

    key: str
    relative_path: str
    kind: str
    format: str
    required_keys: tuple[str, ...] = ()


SOFTWARE_DELIVERY_ARTIFACT_ORDER = (
    "artifact:software-delivery-demo:project-charter",
    "artifact:software-delivery-demo:decision-contract",
    "artifact:software-delivery-demo:ontology-model",
    "artifact:software-delivery-demo:data-product",
    "artifact:software-delivery-demo:feature-catalog",
    "artifact:software-delivery-demo:model-policy",
)

SOFTWARE_DELIVERY_ARTIFACT_SPECS: Mapping[str, SoftwareDeliveryArtifactSpec] = {
    SOFTWARE_DELIVERY_ARTIFACT_ORDER[0]: SoftwareDeliveryArtifactSpec(
        key="project-charter",
        relative_path="config/project.yaml",
        kind="ProjectCharter",
        format="yaml",
        required_keys=(
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
        ),
    ),
    SOFTWARE_DELIVERY_ARTIFACT_ORDER[1]: SoftwareDeliveryArtifactSpec(
        key="decision-contract",
        relative_path="decisions/problem.yaml",
        kind="DecisionContract",
        format="yaml",
        required_keys=("variables", "objective_terms", "hard_constraints"),
    ),
    SOFTWARE_DELIVERY_ARTIFACT_ORDER[2]: SoftwareDeliveryArtifactSpec(
        key="ontology-model",
        relative_path="ontology/domain.ttl",
        kind="OntologyModel",
        format="turtle",
    ),
    SOFTWARE_DELIVERY_ARTIFACT_ORDER[3]: SoftwareDeliveryArtifactSpec(
        key="data-product",
        relative_path="data_products/contracts.yaml",
        kind="DataProduct",
        format="yaml",
        required_keys=("products", "quality_rules"),
    ),
    SOFTWARE_DELIVERY_ARTIFACT_ORDER[4]: SoftwareDeliveryArtifactSpec(
        key="feature-catalog",
        relative_path="features/definitions.yaml",
        kind="FeatureCatalog",
        format="yaml",
        required_keys=("features",),
    ),
    SOFTWARE_DELIVERY_ARTIFACT_ORDER[5]: SoftwareDeliveryArtifactSpec(
        key="model-policy",
        relative_path="models/model_policy.yaml",
        kind="ModelPolicy",
        format="yaml",
        required_keys=("release_policy",),
    ),
}

SOFTWARE_DELIVERY_ARTIFACT_IDS = frozenset(SOFTWARE_DELIVERY_ARTIFACT_SPECS)


@dataclass(frozen=True, slots=True)
class ArtifactInputSnapshot:
    """The exact Artifact/source set consumed by one evaluator run."""

    artifact_hashes: dict[str, str]
    artifact_versions: dict[str, str]
    source_snapshot_id: str
    source_snapshot_hash: str
    input_snapshot_hash: str
    evidence_refs: list[str]
    violations: list[str]

    @property
    def stale(self) -> bool:
        return bool(self.violations)


def build_artifact_input_snapshot(
    artifacts: Sequence[Artifact],
    *,
    source_root: Path | None = None,
) -> ArtifactInputSnapshot:
    """Hash registered Artifact content and, when configured, its source files.

    ``source_root`` is an evaluator-owned path, never a path supplied by a
    Workbench caller.  When an Artifact carries seed source metadata, its raw
    source bytes and parsed content must match the registered Artifact.  This
    makes source tampering or a source-directory switch a blocking condition
    before the sandbox evaluator is invoked.
    """

    if not artifacts:
        raise ValueError("at least one Artifact is required for an input snapshot")
    ordered = sorted(artifacts, key=lambda artifact: artifact.artifact_id)
    project_ids = {artifact.project_id for artifact in ordered}
    if len(project_ids) != 1:
        raise ValueError("all input Artifacts must belong to one project")
    normalized_root = source_root.resolve() if source_root is not None else None
    records: list[dict[str, Any]] = []
    artifact_hashes: dict[str, str] = {}
    artifact_versions: dict[str, str] = {}
    evidence_refs: set[str] = set()
    violations: list[str] = []

    for artifact in ordered:
        artifact_hashes[artifact.artifact_id] = artifact.content_hash
        artifact_versions[artifact.artifact_id] = artifact.version
        evidence_refs.update(artifact.evidence_refs)
        metadata = artifact.metadata if isinstance(artifact.metadata, dict) else {}
        source_path_value = metadata.get("source_path")
        declared_source_sha = metadata.get("source_sha256")
        declared_source_path = (
            str(source_path_value).strip() if source_path_value else ""
        )
        declared_source_sha = (
            str(declared_source_sha).strip() if declared_source_sha else ""
        )
        fixed_spec = (
            SOFTWARE_DELIVERY_ARTIFACT_SPECS.get(artifact.artifact_id)
            if artifact.project_id == "software-delivery-demo"
            else None
        )
        source_path = fixed_spec.relative_path if fixed_spec else declared_source_path
        observed_source_sha = declared_source_sha or artifact.content_hash
        record: dict[str, Any] = {
            "artifact_id": artifact.artifact_id,
            "version": artifact.version,
            "content_hash": artifact.content_hash,
            "source_path": source_path,
            "declared_source_path": declared_source_path,
            "source_sha256": observed_source_sha,
            "evidence_refs": sorted(set(artifact.evidence_refs)),
        }

        if fixed_spec is not None:
            if declared_source_path != fixed_spec.relative_path:
                violations.append(
                    f"Artifact {artifact.artifact_id} expected source mapping is "
                    f"{fixed_spec.relative_path}, got {declared_source_path or '<missing>'}"
                )
            if artifact.kind != fixed_spec.kind:
                violations.append(
                    f"Artifact {artifact.artifact_id} expected kind {fixed_spec.kind}, "
                    f"got {artifact.kind}"
                )

        if normalized_root is not None:
            if not source_path or not declared_source_sha:
                violations.append(
                    f"Artifact {artifact.artifact_id} is missing source metadata"
                )
            else:
                source_file = (normalized_root / source_path).resolve()
                if not _is_within(source_file, normalized_root):
                    violations.append(
                        f"Artifact {artifact.artifact_id} source path escapes source root"
                    )
                elif not source_file.is_file():
                    violations.append(
                        f"Artifact {artifact.artifact_id} source file is missing: {source_path}"
                    )
                else:
                    raw_bytes = source_file.read_bytes()
                    observed_source_sha = sha256(raw_bytes).hexdigest()
                    record["source_sha256"] = observed_source_sha
                    if observed_source_sha != declared_source_sha:
                        violations.append(
                            f"Artifact {artifact.artifact_id} source SHA does not match registered source"
                        )
                    violations.extend(
                        _content_consistency_violations(
                            artifact,
                            raw_bytes,
                            source_path,
                            expected_format=fixed_spec.format if fixed_spec else None,
                        )
                    )

        records.append(record)

    source_payload = {
        "project_id": next(iter(project_ids)),
        "artifacts": records,
    }
    source_snapshot_hash = sha256(canonical_json_bytes(source_payload)).hexdigest()
    source_snapshot_id = (
        f"source-snapshot:{next(iter(project_ids))}:{source_snapshot_hash[:16]}"
    )
    input_payload = {
        "artifact_hashes": artifact_hashes,
        "artifact_versions": artifact_versions,
        "source_snapshot_id": source_snapshot_id,
        "source_snapshot_hash": source_snapshot_hash,
    }
    input_snapshot_hash = sha256(canonical_json_bytes(input_payload)).hexdigest()
    evidence_refs.update(
        {
            source_snapshot_id,
            f"source-snapshot-hash:{source_snapshot_hash}",
            f"input-snapshot:{input_snapshot_hash}",
        }
    )
    return ArtifactInputSnapshot(
        artifact_hashes=artifact_hashes,
        artifact_versions=artifact_versions,
        source_snapshot_id=source_snapshot_id,
        source_snapshot_hash=source_snapshot_hash,
        input_snapshot_hash=input_snapshot_hash,
        evidence_refs=sorted(evidence_refs),
        violations=sorted(set(violations)),
    )


def _is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _content_consistency_violations(
    artifact: Artifact,
    raw_bytes: bytes,
    source_path: str,
    *,
    expected_format: str | None = None,
) -> list[str]:
    content = artifact.content
    if not isinstance(content, dict):
        return [f"Artifact {artifact.artifact_id} content is not a source document envelope"]
    source_ref = content.get("source_ref")
    content_format = content.get("format")
    if not isinstance(source_ref, str) or not source_ref.strip():
        return [f"Artifact {artifact.artifact_id} source reference is missing"]
    expected_source_ref = f"source:{artifact.project_id}/{source_path}"
    violations: list[str] = []
    if expected_format is not None and content_format != expected_format:
        violations.append(
            f"Artifact {artifact.artifact_id} expected format {expected_format}, "
            f"got {content_format or '<missing>'}"
        )
    if source_ref != expected_source_ref:
        violations.append(
            f"Artifact {artifact.artifact_id} source reference does not match source path"
        )
    if source_ref not in artifact.evidence_refs:
        violations.append(
            f"Artifact {artifact.artifact_id} source reference is not in evidence_refs"
        )
    parse_format = expected_format or content_format
    try:
        if parse_format == "turtle":
            document: Any = raw_bytes.decode("utf-8")
        elif parse_format == "yaml":
            document = yaml.safe_load(raw_bytes.decode("utf-8"))
            document = {} if document is None else document
        else:
            raise ValueError(f"unsupported source format: {parse_format}")
    except (UnicodeDecodeError, ValueError, yaml.YAMLError) as exc:
        violations.append(
            f"Artifact {artifact.artifact_id} source document cannot be parsed: {exc}"
        )
        return violations
    expected_content = {
        "source_ref": expected_source_ref,
        "format": content_format,
        "document": document,
    }
    if content != expected_content or artifact.content_hash != content_hash_for(expected_content):
        violations.append(
            f"Artifact {artifact.artifact_id} content hash does not match source content"
        )
    return violations


__all__ = [
    "ArtifactInputSnapshot",
    "SoftwareDeliveryArtifactSpec",
    "SOFTWARE_DELIVERY_ARTIFACT_ORDER",
    "SOFTWARE_DELIVERY_ARTIFACT_IDS",
    "SOFTWARE_DELIVERY_ARTIFACT_SPECS",
    "build_artifact_input_snapshot",
]
