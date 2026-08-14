import pytest

from aifde.task.lifecycle import LifecycleTransitionError, TaskLifecycle, TaskStatus


def test_review_gate_pass_enters_human_approval():
    assert TaskLifecycle.transition(TaskStatus.REVIEWING, "gates_pass") == TaskStatus.AWAITING_HUMAN


def test_agent_cannot_directly_complete_a_task():
    with pytest.raises(LifecycleTransitionError):
        TaskLifecycle.transition(TaskStatus.REVIEWING, "agent_done")
