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
    )
    return EvidenceDrivenOntologyBuilder().run(config)


__all__ = ["run_supplier_delay_builder_demo"]
