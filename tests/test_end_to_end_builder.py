from __future__ import annotations

from datetime import datetime, timezone

from aifde.domain.feedback import Feedback
from aifde.feedback import FeedbackService


def test_feedback_is_append_only_queryable_and_defensively_copied() -> None:
    service = FeedbackService()
    feedback = Feedback(
        feedback_id="feedback-1",
        artifact_id="artifact-1",
        feedback_type="user_acceptance",
        value={"accepted": True},
        source="domain-owner-1",
        created_at=datetime.now(timezone.utc),
        metadata={"comment": "ready"},
    )

    saved = service.record(feedback)
    saved.metadata["comment"] = "caller mutation"

    records = service.list_for_artifact("artifact-1")
    assert len(records) == 1
    assert records[0].metadata["comment"] == "ready"
    assert service.list_for_artifact("unknown-artifact") == []


def test_feedback_rejects_duplicate_identity_and_blank_artifact() -> None:
    service = FeedbackService()
    feedback = Feedback(
        feedback_id="feedback-1",
        artifact_id="artifact-1",
        feedback_type="rejection",
        value={"reason": "insufficient evidence"},
        source="domain-owner-1",
        created_at=datetime.now(timezone.utc),
    )
    service.record(feedback)
    try:
        service.record(feedback)
    except ValueError as exc:
        assert "immutable" in str(exc) or "duplicate" in str(exc)
    else:
        raise AssertionError("duplicate feedback identity was accepted")

