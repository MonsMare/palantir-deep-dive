"""Persistence boundary for immutable Shipyard Workbench records."""

from __future__ import annotations

from typing import Protocol

from aifde.shipyard.contracts import (
    AgentProposal,
    AuditEvent,
    DecisionCase,
    GateReviewSnapshot,
    ProjectWorkspace,
    ReleaseCandidate,
)


class ShipyardStore(Protocol):
    """Persist and retrieve append-only Workbench contract records."""

    def put_workspace(self, workspace: ProjectWorkspace) -> ProjectWorkspace:
        """Append a workspace revision without replacing an existing revision."""

    def get_workspace(self, workspace_id: str) -> ProjectWorkspace:
        """Return the highest persisted workspace revision."""

    def list_workspaces(self, workspace_id: str | None = None) -> list[ProjectWorkspace]:
        """Return workspace history, optionally restricted to one workspace."""

    def put_decision_case(self, decision_case: DecisionCase) -> DecisionCase:
        """Append a decision case and reject a duplicate case identity."""

    def get_decision_case(self, case_id: str) -> DecisionCase:
        """Return one decision case by identity."""

    def list_decision_cases(self, workspace_id: str | None = None) -> list[DecisionCase]:
        """Return decision cases, optionally restricted to one workspace."""

    def put_proposal(self, proposal: AgentProposal) -> AgentProposal:
        """Append a proposal revision without replacing an existing revision."""

    def get_proposal(self, proposal_id: str) -> AgentProposal:
        """Return the highest persisted proposal revision."""

    def list_proposals(self, workspace_id: str | None = None) -> list[AgentProposal]:
        """Return proposal history, optionally restricted to one workspace."""

    def put_gate_review(self, gate_review: GateReviewSnapshot) -> GateReviewSnapshot:
        """Append a gate review with its globally unique gate-run identity."""

    def list_gate_reviews(self, workspace_id: str | None = None) -> list[GateReviewSnapshot]:
        """Return gate reviews, optionally restricted to one workspace."""

    def put_release_candidate(self, candidate: ReleaseCandidate) -> ReleaseCandidate:
        """Append a release candidate with its globally unique identity."""

    def get_release_candidate(self, candidate_id: str) -> ReleaseCandidate:
        """Return one release candidate by identity."""

    def append_audit_event(self, event: AuditEvent) -> AuditEvent:
        """Append a validated, hash-linked audit event."""

    def list_audit_events(self, workspace_id: str | None = None) -> list[AuditEvent]:
        """Return audit events in append/creation order, optionally by workspace."""


__all__ = ["ShipyardStore"]
