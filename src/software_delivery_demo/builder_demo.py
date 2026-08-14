"""Operator-facing supplier-delay example for the evidence-driven Builder."""

from __future__ import annotations

from pathlib import Path

from aifde.builder.flow import (
    BuilderRunConfig,
    BuilderRunResult,
    EvidenceDrivenOntologyBuilder,
)


def run_supplier_delay_builder_demo(
    project_root: Path,
    *,
    force_supplier_conflict: bool = False,
    approval_actor: str = "domain-owner-1",
    persistence_path: str | None = None,
) -> BuilderRunResult:
    """Run the clean or intentionally blocked simulated procurement case."""

    project_root = Path(project_root)
    fixture_root = project_root / "fixtures"
    config = BuilderRunConfig(
        project_id="supplier-delay-builder-demo",
        domain="procurement",
        ontology_version="0.1.0",
        actor_id="builder-1",
        source_paths=(
            str(fixture_root / "purchase_orders.json"),
            str(fixture_root / "supplier_notes.md"),
        ),
        approval_actor=approval_actor,
        force_supplier_conflict=force_supplier_conflict,
        persistence_path=persistence_path,
    )
    return EvidenceDrivenOntologyBuilder().run(config)


def run_software_delivery_ontology_builder_demo(
    source_path: Path,
    *,
    project_id: str = "software-delivery-builder-demo",
    ontology_version: str = "0.1.0",
    approval_actor: str = "domain-owner-1",
    persistence_path: str | None = None,
) -> BuilderRunResult:
    """Run the pack-driven Builder against a JSON requirements source.

    The existing software-delivery demo owns a wider set of Parquet data
    products and model workflows.  This entry point intentionally accepts a
    single normalized JSON source for the ontology ingestion boundary; its
    pack can later add Parquet connectors without changing the Builder API.
    """

    source_path = Path(source_path)
    config = BuilderRunConfig(
        project_id=project_id,
        domain="software-delivery",
        domain_pack_id="software-delivery",
        ontology_version=ontology_version,
        actor_id="builder-1",
        source_paths=(str(source_path),),
        approval_actor=approval_actor,
        persistence_path=persistence_path,
    )
    return EvidenceDrivenOntologyBuilder().run(config)


__all__ = [
    "run_software_delivery_ontology_builder_demo",
    "run_supplier_delay_builder_demo",
]
