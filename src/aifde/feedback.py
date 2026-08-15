"""Append-only feedback service for Shipyard release evaluation and upgrades."""

from __future__ import annotations

from copy import deepcopy

from aifde.domain.feedback import Feedback


class FeedbackService:
    """Record user and system outcomes without allowing caller mutation."""

    def __init__(self) -> None:
        self._records: dict[str, Feedback] = {}

    def record(self, feedback: Feedback) -> Feedback:
        """Append one feedback fact; an existing identity can never be replaced."""
        if not isinstance(feedback, Feedback):
            raise TypeError("feedback must be a Feedback")
        _require_identity(feedback.feedback_id, "feedback_id")
        _require_identity(feedback.artifact_id, "artifact_id")
        _require_identity(feedback.feedback_type, "feedback_type")
        _require_identity(feedback.source, "source")
        if feedback.feedback_id in self._records:
            raise ValueError("feedback records are immutable and duplicate identities are rejected")
        stored = Feedback.model_validate(deepcopy(feedback.model_dump(mode="python")))
        self._records[stored.feedback_id] = stored
        return _copy_feedback(stored)

    def list_for_artifact(self, artifact_id: str) -> list[Feedback]:
        """Return feedback facts in deterministic creation order."""
        _require_identity(artifact_id, "artifact_id")
        records = [
            feedback
            for feedback in self._records.values()
            if feedback.artifact_id == artifact_id
        ]
        records.sort(key=lambda item: (item.created_at, item.feedback_id))
        return [_copy_feedback(feedback) for feedback in records]

    def list_all(self) -> list[Feedback]:
        """Return all feedback facts as defensive copies."""
        records = list(self._records.values())
        records.sort(key=lambda item: (item.created_at, item.feedback_id))
        return [_copy_feedback(feedback) for feedback in records]

    @property
    def count(self) -> int:
        """Return the number of immutable feedback facts recorded so far."""
        return len(self._records)


def _copy_feedback(feedback: Feedback) -> Feedback:
    return Feedback.model_validate(deepcopy(feedback.model_dump(mode="python")))


def _require_identity(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty identity")
    if value != value.strip():
        raise ValueError(f"{name} must use a canonical identity")
