from __future__ import annotations

import pytest
from pydantic import ValidationError

from aifde.platform.domain_pack import DomainPack, DomainPackRegistry
from aifde.platform.ontology_ir import ClassIR, OntologyIR


def _ontology(*, evidence: tuple[str, ...] = ("evidence:ontology",)) -> OntologyIR:
    return OntologyIR(
        ontology_id="procurement-ontology",
        version="1.0.0",
        namespace="urn:aifde:procurement:",
        classes=(
            ClassIR(
                name="PurchaseOrder",
                label="Purchase order",
                evidence_refs=evidence,
                version="1.0.0",
            ),
        ),
        evidence_refs=evidence,
    )


def _pack(**updates: object) -> DomainPack:
    values: dict[str, object] = {
        "pack_id": "procurement",
        "version": "1.0.0",
        "domain": "procurement",
        "vocabulary": {"purchase_order": "PurchaseOrder"},
        "ontology": _ontology(),
        "mappings": (),
        "computation": {"features": ()},
        "decisions": {"problems": ()},
        "actions": {"policies": ()},
        "acceptance_suite": {"required_tests": ("ontology-shapes",)},
    }
    values.update(updates)
    return DomainPack.model_validate(values)


def test_domain_pack_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="unexpected"):
        _pack(unexpected="must not be silently accepted")


def test_domain_pack_registry_rejects_conflicting_version() -> None:
    registry = DomainPackRegistry()
    original = _pack()
    registry.register(original)

    registry.register(original.model_copy(deep=True))
    with pytest.raises(ValueError, match="immutable"):
        registry.register(original.model_copy(update={"domain": "wrong-domain"}))

    assert registry.get("procurement", "1.0.0") == original
    assert registry.list() == [original]


def test_domain_pack_registry_requires_existing_version_for_lookup() -> None:
    registry = DomainPackRegistry([_pack()])

    with pytest.raises(KeyError, match="procurement@2.0.0"):
        registry.get("procurement", "2.0.0")
