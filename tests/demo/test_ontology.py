from __future__ import annotations

from software_delivery_demo.ontology import (
    project_objects_to_graph,
    validate_domain_graph,
)


def test_valid_requirement_has_owner_and_goal(bundle) -> None:
    document = project_objects_to_graph(bundle)
    result = validate_domain_graph(document)
    assert result.passed is True


def test_change_request_without_requirement_is_blocked(bundle) -> None:
    document = project_objects_to_graph(bundle)
    change_id = bundle.changes[0, "change_id"]
    requirement_id = bundle.changes[0, "requirement_id"]
    document.remove_link(
        f"ChangeRequest/{change_id}",
        "changes",
        f"Requirement/{requirement_id}",
    )
    result = validate_domain_graph(document)
    assert result.passed is False
    assert "changes" in result.message


def test_prediction_shape_requires_as_of_time(bundle) -> None:
    document = project_objects_to_graph(bundle)
    document.add_type("DeliveryPrediction/pred-001", "DeliveryPrediction")
    result = validate_domain_graph(document)
    assert result.passed is False
    assert "as_of_time" in result.message


def test_ontology_document_hash_changes_when_link_changes(bundle) -> None:
    document = project_objects_to_graph(bundle)
    before = document.data_hash
    document.remove_link(
        f"Requirement/{bundle.requirements[0, 'requirement_id']}",
        "decomposedInto",
        f"WorkItem/{bundle.work_items[0, 'work_item_id']}",
    )
    assert document.data_hash != before
