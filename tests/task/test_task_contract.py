import pytest
from pydantic import ValidationError

from aifde.task.contracts import TaskContract


def test_contract_requires_decision_owner_and_acceptance():
    with pytest.raises(ValidationError):
        TaskContract(
            task_id="linear:LAC-1",
            project_id="demo",
            domain_pack="software_delivery",
            task_kind="forecast",
            objective="预测工期",
            decision_owner="",
            required_outputs=("ForecastReport",),
            acceptance=(),
        )


def test_contract_normalizes_duplicate_refs_and_defaults_fix_rounds():
    contract = TaskContract(
        task_id="linear:LAC-1",
        project_id="demo",
        domain_pack="software_delivery",
        task_kind="forecast",
        objective="预测工期",
        decision_owner="owner-1",
        required_outputs=("ForecastReport",),
        acceptance=("每个结论引用证据",),
        evidence_refs=("evidence-1", "evidence-1"),
    )
    assert contract.evidence_refs == ("evidence-1",)
    assert contract.max_fix_rounds == 3
