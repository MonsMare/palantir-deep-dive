"""Append-only human review queue for semantic candidates."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from threading import RLock
from typing import Literal

from pydantic import BaseModel, ConfigDict

from aifde.builder.semantic import CandidateProposal


ReviewStatus = Literal["pending", "approved", "rejected"]


def _nonblank(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must not be empty")
    return value.strip()


def candidate_hash(candidate: CandidateProposal) -> str:
    payload = json.dumps(
        candidate.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(payload).hexdigest()


class ReviewTask(BaseModel):
    """Immutable snapshot of a candidate awaiting or receiving review."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    review_id: str
    candidate_hash: str
    candidate: CandidateProposal
    owner: str
    status: ReviewStatus = "pending"
    created_at: datetime
    updated_at: datetime
    decision_actor: str | None = None
    decision_reason: str | None = None


class ReviewDecision(BaseModel):
    """Durable decision receipt without mutating the candidate itself."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    review_id: str
    candidate_hash: str
    status: Literal["approved", "rejected"]
    actor: str
    reason: str | None = None
    decided_at: datetime


class ReviewQueue:
    """Small process-local implementation of an append-only review boundary.

    Production persistence can replace the dictionary, but the transition
    rules intentionally remain the same: one candidate hash per task, one
    terminal decision, and explicit actor/reason metadata.
    """

    def __init__(self) -> None:
        self._records: dict[str, ReviewTask] = {}
        self._lock = RLock()

    def submit(self, candidate: CandidateProposal, owner: str) -> ReviewTask:
        if not isinstance(candidate, CandidateProposal):
            raise TypeError("candidate must be a CandidateProposal")
        owner = _nonblank(owner, "owner")
        if candidate.release_eligibility == "eligible":
            raise ValueError("review queue cannot accept self-approved candidate")
        digest = candidate_hash(candidate)
        review_id = f"review:{digest[:32]}"
        now = datetime.now(timezone.utc)
        task = ReviewTask(
            review_id=review_id,
            candidate_hash=digest,
            candidate=candidate,
            owner=owner,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            existing = self._records.get(review_id)
            if existing is not None:
                if existing.candidate_hash != digest:
                    raise ValueError("review id collision")
                return existing
            self._records[review_id] = task
            return task

    def get(self, review_id: str) -> ReviewTask:
        review_id = _nonblank(review_id, "review_id")
        with self._lock:
            try:
                return self._records[review_id]
            except KeyError as exc:
                raise KeyError(f"unknown review: {review_id}") from exc

    def list(self, status: ReviewStatus | None = None) -> tuple[ReviewTask, ...]:
        with self._lock:
            values = tuple(self._records.values())
        if status is None:
            return values
        return tuple(item for item in values if item.status == status)

    def approve(self, review_id: str, actor: str) -> ReviewDecision:
        actor = _nonblank(actor, "actor")
        return self._decide(review_id, actor, "approved", None)

    def reject(self, review_id: str, actor: str, reason: str) -> ReviewDecision:
        actor = _nonblank(actor, "actor")
        reason = _nonblank(reason, "reason")
        return self._decide(review_id, actor, "rejected", reason)

    def require_approved(
        self, review_id: str, candidate: CandidateProposal
    ) -> CandidateProposal:
        task = self.get(review_id)
        if task.candidate_hash != candidate_hash(candidate):
            raise ValueError("candidate hash does not match review task")
        if task.status != "approved":
            raise ValueError("review is not approved")
        return task.candidate

    def _decide(
        self,
        review_id: str,
        actor: str,
        status: Literal["approved", "rejected"],
        reason: str | None,
    ) -> ReviewDecision:
        with self._lock:
            task = self.get(review_id)
            if task.status != "pending":
                raise ValueError("review is terminal")
            now = datetime.now(timezone.utc)
            self._records[review_id] = task.model_copy(
                update={
                    "status": status,
                    "updated_at": now,
                    "decision_actor": actor,
                    "decision_reason": reason,
                }
            )
            return ReviewDecision(
                review_id=review_id,
                candidate_hash=task.candidate_hash,
                status=status,
                actor=actor,
                reason=reason,
                decided_at=now,
            )


__all__ = ["ReviewDecision", "ReviewQueue", "ReviewStatus", "ReviewTask", "candidate_hash"]
