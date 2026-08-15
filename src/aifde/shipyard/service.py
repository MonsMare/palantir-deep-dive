"""Governed application writes for the Shipyard Workbench."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Literal
from uuid import uuid4

from aifde.domain.artifacts import Artifact, canonical_json_bytes
from aifde.registry.sqlite import SQLiteRegistry
from aifde.shipyard.contracts import (
    AgentProposal,
    AuditEvent,
    DecisionCase,
    GateReviewSnapshot,
    ProjectWorkspace,
    ReleaseCandidate,
)
from aifde.shipyard.identity import (
    IdentityProvider,
    Principal,
    UnauthorizedError,
)


ZERO_HASH = "0" * 64
ProposalDecision = Literal["accept", "reject", "return"]


class StaleRevisionError(RuntimeError):
    """A proposal was based on a workspace revision that is no longer current."""


class ReleaseBlockedError(RuntimeError):
    """The requested release references an ineligible artifact or gate snapshot."""


class RecordNotFoundError(LookupError):
    """A Workbench record or required project-scoped record does not exist."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _model_values(value: Any, expected_type: type[Any], record_name: str) -> dict[str, Any]:
    if isinstance(value, expected_type):
        return value.model_dump(mode="python")
    if isinstance(value, Mapping):
        return dict(value)
    raise TypeError(f"{record_name} must be a {expected_type.__name__} or mapping")


def _ids(value: Iterable[str], field_name: str) -> list[str]:
    if isinstance(value, str):
        raise TypeError(f"{field_name} must be a sequence of strings")
    try:
        values = list(value)
    except TypeError as exc:
        raise TypeError(f"{field_name} must be a sequence of strings") from exc
    if any(not isinstance(item, str) or not item.strip() for item in values):
        raise ValueError(f"{field_name} must contain non-blank strings")
    return list(dict.fromkeys(item.strip() for item in values))


class ShipyardApplicationService:
    """The only application-level state mutation boundary for Workbench."""

    def __init__(
        self,
        registry: SQLiteRegistry,
        identity_provider: IdentityProvider | None = None,
        required_gate_ids: frozenset[str] | None = None,
    ) -> None:
        if identity_provider is None:
            raise ValueError("identity_provider must be supplied explicitly")
        if required_gate_ids is None:
            raise ValueError("required_gate_ids must be supplied explicitly")
        normalized_gate_ids = frozenset(required_gate_ids)
        if not normalized_gate_ids or any(
            not isinstance(gate_id, str) or not gate_id.strip()
            for gate_id in normalized_gate_ids
        ):
            raise ValueError("required_gate_ids must contain non-blank gate IDs")
        if not hasattr(registry, "transaction"):
            raise TypeError("registry must provide transaction()")
        if not callable(getattr(identity_provider, "verify", None)):
            raise TypeError("identity_provider must implement verify(principal)")
        self.registry = registry
        self.identity_provider = identity_provider
        self.required_gate_ids = normalized_gate_ids

    def _principal(self, principal: Principal) -> Principal:
        if not isinstance(principal, Principal):
            raise UnauthorizedError("operation requires a trusted Principal")
        canonical = self.identity_provider.verify(principal)
        if not isinstance(canonical, Principal):
            raise UnauthorizedError("identity provider returned an invalid Principal")
        return canonical

    def _require_kind(
        self, principal: Principal, *allowed_kinds: Literal["human", "agent", "system"]
    ) -> Principal:
        principal = self._principal(principal)
        if principal.kind not in allowed_kinds:
            allowed = ", ".join(allowed_kinds)
            raise UnauthorizedError(
                f"principal kind {principal.kind!r} is not authorized; required {allowed}"
            )
        return principal

    @staticmethod
    def _workspace(store: Any, workspace_id: str) -> ProjectWorkspace:
        try:
            return store.get_workspace(workspace_id)
        except KeyError as exc:
            raise RecordNotFoundError(f"workspace not found: {workspace_id}") from exc

    @staticmethod
    def _proposal(store: Any, proposal_id: str) -> AgentProposal:
        try:
            return store.get_proposal(proposal_id)
        except KeyError as exc:
            raise RecordNotFoundError(f"proposal not found: {proposal_id}") from exc

    @staticmethod
    def _decision_case(store: Any, case_id: str) -> DecisionCase:
        try:
            return store.get_decision_case(case_id)
        except KeyError as exc:
            raise RecordNotFoundError(f"decision case not found: {case_id}") from exc

    def get_workspace(self, workspace_id: str) -> ProjectWorkspace:
        """Return the current workspace projection without exposing its store."""

        return self._workspace(self.registry.shipyard, workspace_id)

    def list_workspaces(self) -> list[ProjectWorkspace]:
        """Return one current projection per workspace in stable identity order."""

        history = self.registry.shipyard.list_workspaces()
        latest: dict[str, ProjectWorkspace] = {}
        for workspace in history:
            current = latest.get(workspace.workspace_id)
            if current is None or workspace.revision > current.revision:
                latest[workspace.workspace_id] = workspace
        return [latest[workspace_id] for workspace_id in sorted(latest)]

    def list_decision_cases(self, workspace_id: str) -> list[DecisionCase]:
        """Return decision cases for an existing workspace."""

        self.get_workspace(workspace_id)
        return self.registry.shipyard.list_decision_cases(workspace_id)

    @staticmethod
    def _append_workspace_revision(
        store: Any,
        workspace: ProjectWorkspace,
        **updates: Any,
    ) -> ProjectWorkspace:
        values = workspace.model_dump(mode="python")
        values.update(updates)
        values["revision"] = workspace.revision + 1
        values["updated_at"] = _utc_now()
        updated = ProjectWorkspace.model_validate(values)
        store.put_workspace(updated)
        return updated

    @staticmethod
    def _append_audit(
        store: Any,
        workspace_id: str,
        event_type: str,
        principal: Principal,
        payload: Mapping[str, Any],
    ) -> AuditEvent:
        events = store.list_audit_events(workspace_id)
        predecessor_hash = events[-1].event_hash if events else ZERO_HASH
        event = AuditEvent.build(
            workspace_id=workspace_id,
            event_type=event_type,
            actor=principal.subject,
            actor_kind=principal.kind,
            payload=dict(payload),
            predecessor_hash=predecessor_hash,
        )
        return store.append_audit_event(event)

    def _write(self, operation: Any) -> Any:
        transaction = self.registry.transaction()
        try:
            result = operation(transaction)
            transaction.commit()
            return result
        except BaseException:
            transaction.rollback()
            raise

    def create_workspace(
        self, workspace_input: Mapping[str, Any] | ProjectWorkspace, principal: Principal
    ) -> ProjectWorkspace:
        principal = self._require_kind(principal, "human")
        values = _model_values(workspace_input, ProjectWorkspace, "workspace")
        for field_name in (
            "revision",
            "decision_case_ids",
            "artifact_ids",
            "proposal_ids",
            "gate_review_ids",
            "release_candidate_ids",
            "created_at",
            "updated_at",
            "owner",
            "status",
        ):
            values.pop(field_name, None)
        values.update(
            {
                "owner": principal.subject,
                "status": "active",
                "revision": 1,
                "decision_case_ids": [],
                "artifact_ids": [],
                "proposal_ids": [],
                "gate_review_ids": [],
                "release_candidate_ids": [],
            }
        )
        workspace = ProjectWorkspace.model_validate(values)

        def operation(transaction: Any) -> ProjectWorkspace:
            store = transaction.shipyard
            store.put_workspace(workspace)
            self._append_audit(
                store,
                workspace.workspace_id,
                "workspace.created",
                principal,
                {
                    "workspace_id": workspace.workspace_id,
                    "project_id": workspace.project_id,
                    "revision": workspace.revision,
                },
            )
            return workspace

        return self._write(operation)

    def create_decision_case(
        self,
        workspace_id: str,
        decision_case_input: Mapping[str, Any] | DecisionCase,
        principal: Principal,
    ) -> DecisionCase:
        principal = self._require_kind(principal, "human")
        values = _model_values(decision_case_input, DecisionCase, "decision case")
        supplied_workspace_id = values.get("workspace_id")
        if supplied_workspace_id is not None and supplied_workspace_id != workspace_id:
            raise UnauthorizedError("decision case does not belong to the requested workspace")
        values["workspace_id"] = workspace_id
        decision_case = DecisionCase.model_validate(values)

        def operation(transaction: Any) -> DecisionCase:
            store = transaction.shipyard
            workspace = self._workspace(store, workspace_id)
            store.put_decision_case(decision_case)
            self._append_workspace_revision(
                store,
                workspace,
                decision_case_ids=[*workspace.decision_case_ids, decision_case.case_id],
            )
            self._append_audit(
                store,
                workspace_id,
                "decision_case.created",
                principal,
                {"case_id": decision_case.case_id, "revision": workspace.revision + 1},
            )
            return decision_case

        return self._write(operation)

    def register_artifact(
        self, workspace_id: str, artifact: Artifact, principal: Principal
    ) -> Artifact:
        principal = self._require_kind(principal, "human", "system")
        if not isinstance(artifact, Artifact):
            raise TypeError("artifact must be an Artifact")

        def operation(transaction: Any) -> Artifact:
            store = transaction.shipyard
            workspace = self._workspace(store, workspace_id)
            if artifact.project_id != workspace.project_id:
                raise UnauthorizedError("artifact does not belong to the workspace project")
            saved = transaction.artifacts.put(artifact)
            artifact_ids = list(workspace.artifact_ids)
            if saved.artifact_id not in artifact_ids:
                artifact_ids.append(saved.artifact_id)
            self._append_workspace_revision(
                store,
                workspace,
                artifact_ids=artifact_ids,
            )
            self._append_audit(
                store,
                workspace_id,
                "artifact.registered",
                principal,
                {
                    "artifact_id": saved.artifact_id,
                    "version": saved.version,
                    "content_hash": saved.content_hash,
                    "revision": workspace.revision + 1,
                },
            )
            return saved

        return self._write(operation)

    def submit_agent_proposal(
        self,
        workspace_id: str,
        proposal_input: Mapping[str, Any] | AgentProposal,
        principal: Principal,
    ) -> AgentProposal:
        principal = self._require_kind(principal, "agent")
        values = _model_values(proposal_input, AgentProposal, "proposal")
        supplied_workspace_id = values.get("workspace_id")
        if supplied_workspace_id is not None and supplied_workspace_id != workspace_id:
            raise UnauthorizedError("proposal does not belong to the requested workspace")
        supplied_kind = values.get("producer_kind")
        if supplied_kind is not None and supplied_kind != "agent":
            raise UnauthorizedError("an Agent Proposal cannot claim human authority")

        def operation(transaction: Any) -> AgentProposal:
            store = transaction.shipyard
            workspace = self._workspace(store, workspace_id)
            values_for_record = dict(values)
            for field_name in (
                "revision",
                "status",
                "created_at",
                "content_hash",
                "producer",
                "producer_kind",
                "workspace_id",
            ):
                values_for_record.pop(field_name, None)
            values_for_record.update(
                {
                    "workspace_id": workspace_id,
                    "producer": principal.subject,
                    "producer_kind": "agent",
                    "revision": 1,
                    "status": "proposed",
                    "base_revision": values.get("base_revision", workspace.revision),
                }
            )
            proposal = AgentProposal.model_validate(values_for_record)
            store.put_proposal(proposal)
            self._append_audit(
                store,
                workspace_id,
                "proposal.submitted",
                principal,
                {
                    "proposal_id": proposal.proposal_id,
                    "revision": proposal.revision,
                    "base_revision": proposal.base_revision,
                },
            )
            return proposal

        return self._write(operation)

    def decide_proposal(
        self,
        proposal_id: str,
        decision: ProposalDecision,
        principal: Principal,
    ) -> AgentProposal:
        principal = self._require_kind(principal, "human")
        if decision not in {"accept", "reject", "return"}:
            raise ValueError("decision must be accept, reject, or return")
        status_by_decision = {
            "accept": "accepted",
            "reject": "rejected",
            "return": "returned",
        }

        stale_error: StaleRevisionError | None = None

        def operation(transaction: Any) -> AgentProposal:
            nonlocal stale_error
            store = transaction.shipyard
            proposal = self._proposal(store, proposal_id)
            workspace = self._workspace(store, proposal.workspace_id)
            if proposal.status != "proposed":
                raise UnauthorizedError(
                    f"proposal {proposal_id} is not awaiting a human decision"
                )
            if proposal.base_revision != workspace.revision:
                stale = proposal.model_copy(
                    update={
                        "revision": proposal.revision + 1,
                        "status": "stale",
                        "created_at": _utc_now(),
                    }
                )
                store.put_proposal(stale)
                self._append_audit(
                    store,
                    workspace.workspace_id,
                    "proposal.stale",
                    principal,
                    {
                        "proposal_id": proposal.proposal_id,
                        "revision": stale.revision,
                        "base_revision": proposal.base_revision,
                        "current_workspace_revision": workspace.revision,
                    },
                )
                stale_error = StaleRevisionError(
                    f"proposal {proposal_id} is stale: base revision "
                    f"{proposal.base_revision}, current workspace revision {workspace.revision}"
                )
                return stale

            decided = proposal.model_copy(
                update={
                    "revision": proposal.revision + 1,
                    "status": status_by_decision[decision],
                    "created_at": _utc_now(),
                }
            )
            store.put_proposal(decided)
            self._append_workspace_revision(store, workspace)
            self._append_audit(
                store,
                workspace.workspace_id,
                f"proposal.{decision}d" if decision != "return" else "proposal.returned",
                principal,
                {
                    "proposal_id": proposal.proposal_id,
                    "revision": decided.revision,
                    "status": decided.status,
                    "workspace_revision": workspace.revision + 1,
                },
            )
            return decided

        result = self._write(operation)
        if stale_error is not None:
            raise stale_error
        return result

    def record_gate_review(
        self, gate_review: GateReviewSnapshot, principal: Principal
    ) -> GateReviewSnapshot:
        principal = self._require_kind(principal, "system")
        if not isinstance(gate_review, GateReviewSnapshot):
            raise TypeError("gate_review must be a GateReviewSnapshot")

        def operation(transaction: Any) -> GateReviewSnapshot:
            store = transaction.shipyard
            workspace = self._workspace(store, gate_review.workspace_id)
            for artifact_id in gate_review.artifact_hashes:
                if artifact_id not in workspace.artifact_ids:
                    raise RecordNotFoundError(
                        f"gate review references Artifact outside workspace: {artifact_id}"
                    )
            store.put_gate_review(gate_review)
            gate_review_ids = [*workspace.gate_review_ids, gate_review.gate_run_id]
            self._append_workspace_revision(
                store,
                workspace,
                gate_review_ids=gate_review_ids,
            )
            self._append_audit(
                store,
                workspace.workspace_id,
                "gate_review.recorded",
                principal,
                {
                    "gate_run_id": gate_review.gate_run_id,
                    "gate_id": gate_review.gate_id,
                    "status": gate_review.status,
                    "stale": gate_review.stale,
                    "revision": workspace.revision + 1,
                },
            )
            return gate_review

        return self._write(operation)

    def create_release_candidate(
        self,
        workspace_id: str,
        artifact_ids: Sequence[str],
        gate_run_ids: Sequence[str],
        principal: Principal,
    ) -> ReleaseCandidate:
        principal = self._require_kind(principal, "human")
        try:
            requested_artifact_ids = _ids(artifact_ids, "artifact_ids")
            requested_gate_run_ids = _ids(gate_run_ids, "gate_run_ids")
        except (TypeError, ValueError) as exc:
            raise ReleaseBlockedError(str(exc)) from exc
        if not requested_artifact_ids:
            raise ReleaseBlockedError("release requires at least one Artifact")
        if not requested_gate_run_ids:
            raise ReleaseBlockedError("release requires at least one Gate Review")

        def operation(transaction: Any) -> ReleaseCandidate:
            store = transaction.shipyard
            workspace = self._workspace(store, workspace_id)
            artifacts: dict[str, Artifact] = {}
            for artifact_id in requested_artifact_ids:
                if artifact_id not in workspace.artifact_ids:
                    raise ReleaseBlockedError(
                        f"Artifact {artifact_id} does not belong to workspace {workspace_id}"
                    )
                try:
                    artifact = transaction.artifacts.get(
                        workspace.project_id, artifact_id
                    )
                except KeyError as exc:
                    raise ReleaseBlockedError(
                        f"Artifact {artifact_id} is not available in workspace {workspace_id}"
                    ) from exc
                if artifact.project_id != workspace.project_id:
                    raise ReleaseBlockedError(
                        f"Artifact {artifact_id} does not belong to workspace {workspace_id}"
                    )
                artifacts[artifact_id] = artifact

            reviews = store.list_gate_reviews()
            by_run_id = {review.gate_run_id: review for review in reviews}
            requested_reviews: list[GateReviewSnapshot] = []
            for gate_run_id in requested_gate_run_ids:
                review = by_run_id.get(gate_run_id)
                if review is None:
                    raise ReleaseBlockedError(f"missing Gate Review: {gate_run_id}")
                if review.workspace_id != workspace_id:
                    raise ReleaseBlockedError(
                        f"Gate Review {gate_run_id} does not belong to workspace {workspace_id}"
                    )
                requested_reviews.append(review)

            latest_by_gate: dict[str, tuple[int, datetime, int, GateReviewSnapshot]] = {}
            for index, review in enumerate(reviews):
                if review.workspace_id != workspace_id:
                    continue
                key = (review.revision, review.created_at, index, review)
                current = latest_by_gate.get(review.gate_id)
                if current is None or key[:3] > current[:3]:
                    latest_by_gate[review.gate_id] = key

            for review in requested_reviews:
                latest = latest_by_gate.get(review.gate_id)
                if latest is None or latest[3].gate_run_id != review.gate_run_id:
                    raise ReleaseBlockedError(
                        f"Gate Review {review.gate_run_id} is not the current/latest review "
                        f"for gate {review.gate_id}"
                    )
                if review.status != "passed":
                    raise ReleaseBlockedError(
                        f"Gate Review {review.gate_run_id} is not passed"
                    )
                if review.stale:
                    raise ReleaseBlockedError(
                        f"Gate Review {review.gate_run_id} is stale"
                    )
                expected_hashes = {
                    artifact_id: artifacts[artifact_id].content_hash
                    for artifact_id in requested_artifact_ids
                }
                if review.artifact_hashes != expected_hashes:
                    raise ReleaseBlockedError(
                        f"Gate Review {review.gate_run_id} does not reference current Artifact hashes"
                    )

            reviewed_gate_ids = {review.gate_id for review in requested_reviews}
            missing_gate_ids = sorted(self.required_gate_ids - reviewed_gate_ids)
            if missing_gate_ids:
                raise ReleaseBlockedError(
                    "missing required gate: " + ", ".join(missing_gate_ids)
                )

            ordered_artifact_ids = sorted(requested_artifact_ids)
            ordered_gate_run_ids = sorted(requested_gate_run_ids)
            manifest_payload = {
                "artifact_hashes": {
                    artifact_id: artifacts[artifact_id].content_hash
                    for artifact_id in ordered_artifact_ids
                },
                "gate_run_ids": ordered_gate_run_ids,
            }
            manifest = {
                **manifest_payload,
                "manifest_digest": sha256(
                    canonical_json_bytes(manifest_payload)
                ).hexdigest(),
            }
            candidate = ReleaseCandidate(
                candidate_id=f"candidate:{uuid4()}",
                workspace_id=workspace_id,
                artifact_ids=ordered_artifact_ids,
                gate_run_ids=ordered_gate_run_ids,
                manifest=manifest,
                status="ready",
                created_by=principal.subject,
            )
            store.put_release_candidate(candidate)
            self._append_workspace_revision(
                store,
                workspace,
                release_candidate_ids=[
                    *workspace.release_candidate_ids,
                    candidate.candidate_id,
                ],
            )
            self._append_audit(
                store,
                workspace_id,
                "release_candidate.created",
                principal,
                {
                    "candidate_id": candidate.candidate_id,
                    "artifact_ids": ordered_artifact_ids,
                    "gate_run_ids": ordered_gate_run_ids,
                    "revision": workspace.revision + 1,
                },
            )
            return candidate

        return self._write(operation)

    def get_workspace_snapshot(self, workspace_id: str) -> dict[str, object]:
        store = self.registry.shipyard
        workspace = self._workspace(store, workspace_id)
        artifacts: list[Artifact] = []
        for artifact_id in workspace.artifact_ids:
            try:
                artifacts.append(self.registry.artifacts.get(workspace.project_id, artifact_id))
            except KeyError as exc:
                raise RecordNotFoundError(
                    f"Artifact not found for workspace {workspace_id}: {artifact_id}"
                ) from exc
        decision_cases = store.list_decision_cases(workspace_id)
        proposals = store.list_proposals(workspace_id)
        gate_reviews = store.list_gate_reviews(workspace_id)
        release_candidates: list[ReleaseCandidate] = []
        for candidate_id in workspace.release_candidate_ids:
            try:
                release_candidates.append(store.get_release_candidate(candidate_id))
            except KeyError as exc:
                raise RecordNotFoundError(
                    f"Release Candidate not found for workspace {workspace_id}: {candidate_id}"
                ) from exc
        audit_events = store.list_audit_events(workspace_id)
        return {
            "workspace": workspace,
            "decision_cases": decision_cases,
            "artifacts": artifacts,
            "proposals": proposals,
            "gate_reviews": gate_reviews,
            "release_candidates": release_candidates,
            "audit_events": audit_events,
        }


__all__ = [
    "RecordNotFoundError",
    "ReleaseBlockedError",
    "ShipyardApplicationService",
    "StaleRevisionError",
    "UnauthorizedError",
]
