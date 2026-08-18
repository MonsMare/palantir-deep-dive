from __future__ import annotations

import pytest

from aifde.builder.semantic import CandidateProposal
from aifde.semantic.review import ReviewQueue


def _proposal() -> CandidateProposal:
    return CandidateProposal(
        evidence_refs=("evidence:1",),
        release_eligibility="review_required",
    )


def test_review_queue_is_append_only_and_approval_does_not_promote_candidate() -> None:
    queue = ReviewQueue()
    proposal = _proposal()

    task = queue.submit(proposal, owner="domain-owner")
    decision = queue.approve(task.review_id, actor="domain-owner")

    assert decision.status == "approved"
    assert decision.candidate_hash == task.candidate_hash
    assert proposal.release_eligibility == "review_required"
    with pytest.raises(ValueError, match="terminal"):
        queue.reject(task.review_id, actor="domain-owner", reason="late rejection")


def test_review_queue_rejects_empty_reviewer_and_reason() -> None:
    queue = ReviewQueue()
    task = queue.submit(_proposal(), owner="domain-owner")

    with pytest.raises(ValueError, match="actor"):
        queue.approve(task.review_id, actor=" ")
    with pytest.raises(ValueError, match="reason"):
        queue.reject(task.review_id, actor="domain-owner", reason=" ")


def test_review_queue_requires_matching_candidate_for_approved_access() -> None:
    queue = ReviewQueue()
    task = queue.submit(_proposal(), owner="domain-owner")
    queue.approve(task.review_id, actor="domain-owner")

    with pytest.raises(ValueError, match="candidate hash"):
        queue.require_approved(task.review_id, CandidateProposal(evidence_refs=("evidence:2",)))

