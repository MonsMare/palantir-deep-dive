"""Optional Streamlit read-only cockpit for the AI FDE project."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, Callable, Mapping
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


JsonDict = dict[str, Any]
FetchJson = Callable[[str], Any]


@dataclass(frozen=True)
class CockpitSnapshot:
    """Read-only API data rendered by the project cockpit."""

    project_id: str
    stages: list[JsonDict] = field(default_factory=list)
    artifacts: list[JsonDict] = field(default_factory=list)
    gates: list[JsonDict] = field(default_factory=list)
    approvals: list[JsonDict] = field(default_factory=list)
    open_questions: list[JsonDict] = field(default_factory=list)
    latest_diff: str | None = None
    actions: list[JsonDict] = field(default_factory=list)
    dry_runs: list[JsonDict] = field(default_factory=list)
    reconciliations: list[JsonDict] = field(default_factory=list)

    @property
    def current_stage(self) -> JsonDict | None:
        """Return the stage most likely to need attention."""

        if not self.stages:
            return None
        for stage in self.stages:
            state = str(stage.get("state", "")).lower()
            if state not in {"approved", "released"}:
                return stage
        return self.stages[-1]

    @property
    def hard_gate_failures(self) -> list[JsonDict]:
        """Return failed hard gates without mutating the source payload."""

        return [
            gate
            for gate in self.gates
            if str(gate.get("severity", "")).lower() == "hard"
            and str(gate.get("status", "")).lower() in {"failed", "blocked"}
        ]


def load_project_cockpit(
    project_id: str,
    *,
    api_base_url: str = "http://localhost:8000",
    fetch_json: FetchJson | None = None,
) -> CockpitSnapshot:
    """Load a project cockpit snapshot through read-only API endpoints."""

    if not isinstance(project_id, str) or not project_id.strip():
        raise ValueError("project_id must be a non-empty string")
    project_id = project_id.strip()
    fetch = fetch_json or _http_get_json(api_base_url)
    encoded = quote(project_id, safe="")

    stages = _as_list(fetch(f"/projects/{encoded}/stages"))
    artifacts = _as_list(fetch(f"/projects/{encoded}/artifacts"))
    gates = _as_list(fetch(f"/projects/{encoded}/gates"))
    approvals = _optional_list(fetch, f"/projects/{encoded}/approvals")
    open_questions = _optional_list(fetch, f"/projects/{encoded}/open-questions")
    latest_diff = _optional_text(fetch, f"/projects/{encoded}/latest-diff")
    actions = _optional_list(fetch, f"/projects/{encoded}/actions")
    dry_runs = _optional_list(fetch, f"/projects/{encoded}/action-dry-runs")
    reconciliations = _optional_list(fetch, f"/projects/{encoded}/reconciliations")

    if latest_diff is None and artifacts:
        latest_artifact = artifacts[-1]
        latest_diff = _string_or_none(
            latest_artifact.get("diff")
            or latest_artifact.get("latest_diff")
            or latest_artifact.get("content_diff")
        )

    return CockpitSnapshot(
        project_id=project_id,
        stages=stages,
        artifacts=artifacts,
        gates=gates,
        approvals=approvals,
        open_questions=open_questions,
        latest_diff=latest_diff,
        actions=actions,
        dry_runs=dry_runs,
        reconciliations=reconciliations,
    )


def render_dashboard(
    project_id: str = "p1",
    *,
    api_base_url: str = "http://localhost:8000",
    fetch_json: FetchJson | None = None,
) -> CockpitSnapshot:
    """Render the read-only project cockpit with optional Streamlit."""

    try:
        import streamlit as st
    except ImportError as exc:  # pragma: no cover - Streamlit is optional
        raise RuntimeError(
            "Streamlit is required for the cockpit; install the optional UI dependency"
        ) from exc

    snapshot = load_project_cockpit(
        project_id,
        api_base_url=api_base_url,
        fetch_json=fetch_json,
    )

    st.title("AI FDE Project Cockpit")
    st.caption("Read-only gate, approval, question, and artifact review surface.")

    st.subheader("Project")
    st.write({"project_id": snapshot.project_id})

    st.subheader("Current stage")
    if snapshot.current_stage is None:
        st.info("No stages are registered for this project.")
    else:
        st.json(snapshot.current_stage)

    st.subheader("Hard gate failures")
    if snapshot.hard_gate_failures:
        st.table(snapshot.hard_gate_failures)
    else:
        st.success("No failed hard gates.")

    st.subheader("Pending approvals")
    pending_approval_ids = _pending_approval_ids(snapshot)
    if snapshot.approvals:
        st.table(snapshot.approvals)
    elif pending_approval_ids:
        st.write(pending_approval_ids)
    else:
        st.info("No pending approvals.")

    st.subheader("Open questions")
    if snapshot.open_questions:
        st.table(snapshot.open_questions)
    else:
        st.info("No open questions.")

    st.subheader("Latest artifact diff")
    if snapshot.latest_diff:
        st.code(snapshot.latest_diff, language="diff")
    elif snapshot.artifacts:
        st.json(snapshot.artifacts[-1])
    else:
        st.info("No artifacts are available yet.")

    st.subheader("Actions")
    _render_actions_read_only(st, snapshot.actions)

    st.subheader("Dry-run receipts")
    if snapshot.dry_runs:
        st.table(snapshot.dry_runs)
    else:
        st.info("No dry-run receipts are available.")

    st.subheader("Reconciliation")
    if snapshot.reconciliations:
        st.table(snapshot.reconciliations)
    else:
        st.info("No reconciliation records are available.")

    return snapshot


def _render_actions_read_only(st: Any, actions: list[JsonDict]) -> None:
    """Render actions without exposing Execute for non-approved records."""

    if not actions:
        st.info("No actions available.")
        return

    for action in actions:
        approval_status = str(action.get("approval_status", "")).lower()
        label = str(action.get("action_id") or action.get("action_type") or "action")
        with st.expander(label):
            st.json(action)
            if approval_status == "approved":
                st.caption("Approved action; execution remains mediated by the API boundary.")
                st.button(
                    "Execute",
                    disabled=True,
                    help="Disabled in the read-only cockpit. Use the approved Action API boundary.",
                )
            else:
                st.caption("Action is not approved; Execute is intentionally hidden.")


def _http_get_json(api_base_url: str) -> FetchJson:
    base = api_base_url.rstrip("/")

    def fetch(path: str) -> Any:
        request = Request(f"{base}{path}", method="GET")
        try:
            with urlopen(request, timeout=10) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            if exc.code == 404:
                raise KeyError(path) from exc
            raise
        if not body.strip():
            return None
        return json.loads(body)

    return fetch


def _optional_list(fetch: FetchJson, path: str) -> list[JsonDict]:
    try:
        return _as_list(fetch(path))
    except KeyError:
        return []
    except HTTPError as exc:
        if exc.code == 404:
            return []
        raise


def _optional_text(fetch: FetchJson, path: str) -> str | None:
    try:
        value = fetch(path)
    except KeyError:
        return None
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    if isinstance(value, Mapping):
        return _string_or_none(
            value.get("diff")
            or value.get("latest_diff")
            or value.get("content")
            or value.get("text")
        )
    return _string_or_none(value)


def _as_list(value: Any) -> list[JsonDict]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise TypeError("expected API response to be a list")
    return [dict(item) if isinstance(item, Mapping) else {"value": item} for item in value]


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text.strip() else None


def _pending_approval_ids(snapshot: CockpitSnapshot) -> list[str]:
    ids: list[str] = []
    for stage in snapshot.stages:
        for approval_id in stage.get("pending_approval_ids", []) or []:
            ids.append(str(approval_id))
    return ids


__all__ = ["CockpitSnapshot", "load_project_cockpit", "render_dashboard"]
