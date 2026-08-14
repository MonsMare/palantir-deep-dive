import pytest
from pydantic import ValidationError

from aifde.task.contracts import TaskContract


def _contract(**overrides):
    values = {
        "task_id": "linear:LAC-1",
        "project_id": "demo",
        "domain_pack": "software_delivery",
        "task_kind": "forecast",
        "objective": "预测工期",
        "decision_owner": "owner-1",
        "required_outputs": ("ForecastReport",),
        "acceptance": ("每个结论引用证据",),
    }
    values.update(overrides)
    return TaskContract(**values)


@pytest.mark.parametrize("decision_owner", [""])
def test_contract_requires_decision_owner(decision_owner):
    with pytest.raises(ValidationError):
        _contract(decision_owner=decision_owner)


@pytest.mark.parametrize("acceptance", [()])
def test_contract_requires_acceptance(acceptance):
    with pytest.raises(ValidationError):
        _contract(acceptance=acceptance)


def test_contract_normalizes_duplicate_refs_and_defaults_fix_rounds():
    contract = _contract(
        evidence_refs=("evidence-1", "evidence-1"),
    )
    assert contract.evidence_refs == ("evidence-1",)
    assert contract.max_fix_rounds == 3
