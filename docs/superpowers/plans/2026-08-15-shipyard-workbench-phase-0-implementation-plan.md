# AI-FDE Shipyard Workbench Phase 0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现第一条可运行的 Shipyard Workbench 垂直切片：人类创建项目和业务决策，查看版本化 Artifact 与 Gate Review，审查 Agent Proposal，并在 Gate 未通过时被阻止创建 Release Candidate。

**Architecture:** 在现有 `aifde` Python 内核之上增加 `aifde.shipyard` 应用层。`SQLiteRegistry` 保存 Workbench 对象和追加式审计；`ShipyardApplicationService` 是唯一状态写入边界；FastAPI 提供 Workbench API；React/TypeScript Workbench 只通过 API 读取和提交人类命令。现有 Builder、Ontology、Gate 和领域代码作为沙箱构建内核被调用，不把客户生产运行时放入 Shipyard。

**Tech Stack:** Python 3.11+、Pydantic v2、SQLite、FastAPI、pytest；React 18、TypeScript、Vite、TanStack Query、Vitest、Testing Library；本阶段不引入 Linear、PostgreSQL、消息队列或客户生产连接器。

## Global Constraints

- Shipyard 只负责构建、评测和交付；客户生产运行时是 `DecisionSystemRelease` 的交付物，不是本阶段的服务进程。
- Agent 只能提交 `AgentProposal`，不能直接修改 Workspace、审批 Proposal、改变 Gate 状态或创建可发布的 Release Candidate。
- 所有状态写入必须通过 `ShipyardApplicationService`；Registry 只提供持久化，不承载业务授权。
- 人类身份来自 API 认证上下文；请求体不得声明 `actor`、`authority` 或 `approval`，本地 FakeAuth 只能显式配置用于测试和开发。
- Artifact、Proposal、Gate Review、Release Candidate 和审计事件必须带 workspace/project 归属、版本或 revision、时间和内容哈希。
- Release Candidate 只能引用当前 Artifact 版本和 `passed`、非 stale 的 Gate Review；任何 `failed`、`blocked`、`pending` 或缺失 Gate 都必须拒绝。
- 兼容现有 `Artifact`、`SQLiteRegistry`、`GateEngine` 和 API 测试；不得为了 Workbench 重写现有领域内核。
- 当前工作区已有未提交用户改动；实施时只触碰本计划列出的文件，不使用 `git add -A`、reset 或 checkout 覆盖它们。
- 每个任务遵循 TDD：先写一个会正确失败的测试，再写最小实现，再运行任务测试和回归测试。

---

### Task 1: 建立 Shipyard Workbench 领域合同

**Files:**

- Create: `src/aifde/shipyard/__init__.py`
- Create: `src/aifde/shipyard/contracts.py`
- Modify: `src/aifde/domain/artifacts.py`
- Test: `tests/shipyard/test_contracts.py`
- Test: `tests/unit/test_domain_contracts.py`

**Interfaces:**

- `ProjectWorkspace(workspace_id, project_id, name, domain_pack, owner, status, current_phase, revision, decision_case_ids, artifact_ids, proposal_ids, gate_review_ids, release_candidate_ids, created_at, updated_at)`。
- `DecisionCase(case_id, workspace_id, name, objective, decision_owner, users, trigger, inputs, actions, constraints, kpis, baseline, success_definition, failure_definition, status)`。
- `AgentProposal(proposal_id, revision, workspace_id, task_packet_id, producer, producer_kind, proposed_changes, affected_artifact_ids, evidence_refs, validation_results, confidence, risks, open_questions, next_step, base_revision, status, created_at)`。
- `GateReviewSnapshot(gate_run_id, workspace_id, gate_id, severity, status, artifact_hashes, validator_version, violations, warnings, evidence_refs, stale, created_at)`。
- `ReleaseCandidate(candidate_id, workspace_id, artifact_ids, gate_run_ids, manifest, status, created_at, created_by)`。
- `AuditEvent(event_id, workspace_id, event_type, actor, actor_kind, payload, created_at, predecessor_hash, event_hash)`。
- `AuditEvent.build(workspace_id, event_type, actor, actor_kind, payload, predecessor_hash)` recomputes the event hash from canonical JSON。
- `Artifact` gains backwards-compatible `parent_artifact_ids`, `producer`, `created_at` and `validation_results` defaults; its existing content hash remains derived only from `content`.

- [ ] **Step 1: Write the failing contract tests**

```python
from aifde.domain.artifacts import Artifact, content_hash_for


def test_decision_case_requires_a_decision_owner_and_action() -> None:
    with pytest.raises(ValidationError):
        DecisionCase(
            case_id="case-1",
            workspace_id="ws-1",
            name="delivery forecast",
            objective="forecast duration",
            decision_owner="",
            users=["pm"],
            trigger="change request arrives",
            inputs=["requirement"],
            actions=[],
            constraints=[],
            kpis=["on_time_rate"],
            baseline="manual review",
            success_definition="fewer surprises",
            failure_definition="silent delay",
        )


def test_agent_proposal_cannot_claim_human_authority() -> None:
    with pytest.raises(ValidationError):
        AgentProposal.model_validate({
            "proposal_id": "proposal-1",
            "workspace_id": "ws-1",
            "task_packet_id": "packet-1",
            "producer": "agent-1",
            "producer_kind": "human",
            "proposed_changes": {"kind": "DecisionContract"},
            "base_revision": 1,
        })


def test_artifact_new_metadata_is_backward_compatible_and_hash_is_stable() -> None:
    artifact = Artifact.build(
        project_id="p1", kind="DecisionContract", content={"objective": "forecast"}, owner="alice"
    )
    assert artifact.parent_artifact_ids == []
    assert artifact.content_hash == content_hash_for(artifact.content)
```

- [ ] **Step 2: Run the focused tests and verify the expected failure**

Run: `pytest tests/shipyard/test_contracts.py tests/unit/test_domain_contracts.py -q`

Expected: collection or validation failures because `aifde.shipyard.contracts` and the new fields do not exist.

- [ ] **Step 3: Implement immutable-enough Pydantic contracts**

Use `ConfigDict(extra="forbid", frozen=True)` for Workbench records. Use `Literal`/enums for statuses, reject blank identities, normalize `created_at` to UTC, and make `AgentProposal.producer_kind` a literal `"agent"`. Build `AuditEvent.event_hash` from canonical JSON of the event payload plus `predecessor_hash`; never accept a caller-supplied hash without recomputing it.

- [ ] **Step 4: Extend `Artifact` without changing its existing public builder contract**

Add only defaulted fields and pass them through `model_copy`, validation, SQLite serialization, and `Artifact.build`. Keep `content_hash` computed from canonical content and reject a forged supplied hash as before.

- [ ] **Step 5: Run focused and regression tests**

Run: `pytest tests/shipyard/test_contracts.py tests/unit/test_domain_contracts.py -q`

Expected: all tests pass, including existing Artifact immutability and content-hash tests.

- [ ] **Step 6: Commit**

```powershell
git add src/aifde/shipyard src/aifde/domain/artifacts.py tests/shipyard/test_contracts.py tests/unit/test_domain_contracts.py
git commit -m "feat: add Shipyard Workbench domain contracts"
```

### Task 2: Add append-only Workbench persistence

**Files:**

- Create: `src/aifde/shipyard/store.py`
- Modify: `src/aifde/registry/protocol.py`
- Modify: `src/aifde/registry/sqlite.py`
- Test: `tests/shipyard/test_store.py`
- Test: `tests/api/test_sqlite_registry_routes.py`

**Interfaces:**

- `ShipyardStore` protocol with `put_workspace`, `get_workspace`, `list_workspaces`, `put_decision_case`, `get_decision_case`, `list_decision_cases`, `put_proposal`, `get_proposal`, `list_proposals`, `put_gate_review`, `list_gate_reviews`, `put_release_candidate`, `get_release_candidate`, `append_audit_event`, and `list_audit_events`.
- `SQLiteRegistry.shipyard` implements the protocol through the same SQLite connection and lock as artifact/evidence repositories.
- `SQLiteRegistry.transaction()` exposes a transaction-scoped Shipyard repository so state and its audit event commit atomically.

- [ ] **Step 1: Write failing persistence tests**

At the top of `tests/shipyard/test_store.py`, define concrete test factories
`build_workspace(workspace_id: str) -> ProjectWorkspace`,
`build_event(workspace_id: str, event_type: str) -> AuditEvent`, and
`build_release_candidate(candidate_id: str) -> ReleaseCandidate` using the
Task 1 constructors and fixed UTC timestamps. These are test-only factories;
the production repository must not generate implicit records.

```python
def test_workspace_and_audit_event_survive_registry_restart(tmp_path: Path) -> None:
    first = SQLiteRegistry(tmp_path / "shipyard.db")
    workspace = build_workspace("ws-1")
    first.shipyard.put_workspace(workspace)
    first.shipyard.append_audit_event(build_event(workspace.workspace_id, "workspace.created"))
    first.close()

    second = SQLiteRegistry(tmp_path / "shipyard.db")
    assert second.shipyard.get_workspace("ws-1").revision == 1
    assert second.shipyard.list_audit_events("ws-1")[0].event_type == "workspace.created"
    second.close()


def test_release_candidate_rejects_duplicate_identity_and_never_overwrites(tmp_path: Path) -> None:
    registry = SQLiteRegistry(tmp_path / "shipyard.db")
    candidate = build_release_candidate("candidate-1")
    registry.shipyard.put_release_candidate(candidate)
    with pytest.raises(ValueError, match="already exists"):
        registry.shipyard.put_release_candidate(candidate)
```

- [ ] **Step 2: Run the focused tests and verify failure**

Run: `pytest tests/shipyard/test_store.py -q`

Expected: failure because the Shipyard tables and repository are absent.

- [ ] **Step 3: Add schema and repository methods**

Add `shipyard_workspaces`, `shipyard_decision_cases`, `shipyard_proposals`, `shipyard_gate_reviews`, `shipyard_release_candidates`, and `shipyard_audit_events` tables. Store canonical JSON payloads, identity keys, content hashes and timestamps. Make `(workspace_id, revision)` the workspace record key and `(proposal_id, revision)` the Proposal record key; `get_*` returns the highest revision and `list_*` can return the full history. Gate Reviews, Release Candidates and audit events use globally unique IDs and are append-only. Every `put_*` operation rejects an existing identity/revision and never overwrites a prior record.

- [ ] **Step 4: Add transaction-scoped writes**

Implement `with registry.transaction() as tx:` support for the Shipyard repository. `ShipyardApplicationService` will use it to write a new revision and its audit event together. Rollback must remove both records when the audit hash or validation fails.

- [ ] **Step 5: Run persistence and API regression tests**

Run: `pytest tests/shipyard/test_store.py tests/api/test_sqlite_registry_routes.py -q`

Expected: all focused tests pass and existing SQLite-backed API tests remain green.

- [ ] **Step 6: Commit**

```powershell
git add src/aifde/shipyard/store.py src/aifde/registry/protocol.py src/aifde/registry/sqlite.py tests/shipyard/test_store.py tests/api/test_sqlite_registry_routes.py
git commit -m "feat: persist Shipyard Workbench records"
```

### Task 3: Implement identity and the Shipyard application service

**Files:**

- Create: `src/aifde/shipyard/identity.py`
- Create: `src/aifde/shipyard/service.py`
- Test: `tests/shipyard/test_service.py`

**Interfaces:**

- `Principal(subject: str, kind: Literal["human", "agent", "system"], roles: frozenset[str])`.
- `IdentityProvider.resolve(request_context: Mapping[str, str]) -> Principal`.
- `FakeIdentityProvider.bind(subject, kind, roles)` for explicit local/test configuration only.
- `UnauthorizedError`, `StaleRevisionError`, `ReleaseBlockedError`, and `RecordNotFoundError` are typed application errors mapped by the API layer.
- `ShipyardApplicationService(..., required_gate_ids: frozenset[str])` receives the required Gate policy explicitly; the software-delivery slice supplies its fixed Gate set rather than hiding it in route code.
- `ShipyardApplicationService.create_workspace(...) -> ProjectWorkspace`.
- `ShipyardApplicationService.create_decision_case(...) -> DecisionCase`.
- `ShipyardApplicationService.register_artifact(workspace_id, artifact, principal) -> Artifact`.
- `ShipyardApplicationService.submit_agent_proposal(...) -> AgentProposal`.
- `ShipyardApplicationService.decide_proposal(proposal_id, decision: Literal["accept", "reject", "return"], principal) -> AgentProposal`.
- `ShipyardApplicationService.record_gate_review(...) -> GateReviewSnapshot`.
- `ShipyardApplicationService.create_release_candidate(...) -> ReleaseCandidate`.
- `ShipyardApplicationService.get_workspace_snapshot(workspace_id) -> dict[str, object]`.

- [ ] **Step 1: Write failing authorization and lifecycle tests**

The test module defines `workspace_input()`, `proposal_input()`,
`human_principal(subject="alice")`, `agent_principal(subject="agent-1")`,
`system_principal()`, and `passed_gate(workspace_id, artifact)` factories.
The `service` fixture creates a temporary `SQLiteRegistry`, a
`FakeIdentityProvider`, and a `ShipyardApplicationService` bound to that
registry. The factories use only the public contracts from Task 1.

```python
def test_agent_proposal_is_recorded_but_does_not_change_workspace_revision(service, agent):
    workspace = service.create_workspace(workspace_input(), human_principal())
    before = workspace.revision
    proposal = service.submit_agent_proposal(workspace.workspace_id, proposal_input(), agent)
    assert proposal.status == "proposed"
    assert service.get_workspace_snapshot(workspace.workspace_id)["workspace"].revision == before


def test_agent_cannot_accept_or_create_release_candidate(service, agent):
    workspace = service.create_workspace(workspace_input(), human_principal())
    with pytest.raises(UnauthorizedError):
        service.decide_proposal("proposal-1", "accept", agent)
    with pytest.raises(UnauthorizedError):
        service.create_release_candidate(workspace.workspace_id, [], [], agent)


def test_release_candidate_requires_current_passed_nonstale_gates(service, human):
    workspace = service.create_workspace(workspace_input(), human)
    artifact = service.register_artifact(
        workspace.workspace_id,
        Artifact.build(
            project_id=workspace.project_id,
            kind="DecisionContract",
            content={"objective": "forecast"},
            owner=human.subject,
            artifact_id="artifact-1",
        ),
        human,
    )
    service.record_gate_review(passed_gate(workspace.workspace_id, artifact), system_principal())
    with pytest.raises(ReleaseBlockedError, match="missing required gate"):
        service.create_release_candidate(workspace.workspace_id, [artifact.artifact_id], [], human)
```

- [ ] **Step 2: Run the focused tests and verify failure**

Run: `pytest tests/shipyard/test_service.py -q`

Expected: import or missing-service failures.

- [ ] **Step 3: Implement the principal boundary**

Reject blank subjects and unknown kinds. `FakeIdentityProvider` must look up a preconfigured subject; it must not infer authority from a name prefix or a request body field. The API request models will not contain actor/authority fields.

- [ ] **Step 4: Implement service methods and policy checks**

All writes go through one service method, a transaction, and an audit event. Human-only operations are `create_workspace`, `create_decision_case`, proposal decision, and Release Candidate creation. Agent-only operation is proposal submission. System-only operation is Gate Review recording. Compare `base_revision` before accepting a Proposal; stale proposals are persisted as a new Proposal revision with `status="stale"` and cannot be accepted. A proposal decision is also a new `(proposal_id, revision)` record, never an in-place update.

- [ ] **Step 5: Implement release eligibility**

Load every requested Artifact and Gate Review. Require exact workspace ownership, latest Artifact version, `status == "passed"`, `stale is False`, and all required gate IDs. Persist a deterministic manifest hash from the ordered Artifact hashes and Gate Review IDs.

- [ ] **Step 6: Run service and regression tests**

Run: `pytest tests/shipyard/test_service.py tests/task tests/gates -q`

Expected: all tests pass; no Agent path can mutate approval/release state.

- [ ] **Step 7: Commit**

```powershell
git add src/aifde/shipyard/identity.py src/aifde/shipyard/service.py tests/shipyard/test_service.py
git commit -m "feat: add governed Shipyard application service"
```

### Task 4: Expose the Workbench application API

**Files:**

- Create: `src/aifde/api/shipyard_routes.py`
- Modify: `src/aifde/api/app.py`
- Modify: `src/aifde/api/__init__.py`
- Test: `tests/api/test_shipyard_routes.py`

**Interfaces:**

- `POST /workspaces` and `GET /workspaces`.
- `GET /workspaces/{workspace_id}`.
- `POST /workspaces/{workspace_id}/decision-cases` and `GET /workspaces/{workspace_id}/decision-cases`.
- `POST /workspaces/{workspace_id}/proposals`.
- `POST /proposals/{proposal_id}/decision` with `decision` only.
- `POST /workspaces/{workspace_id}/gate-reviews` for system/internal evaluation calls.
- `POST /workspaces/{workspace_id}/release-candidates`.
- `GET /workspaces/{workspace_id}/snapshot`.
- `create_app(..., shipyard_service: ShipyardApplicationService | None = None)` remains backwards compatible; when supplied, it includes the Workbench router.

- [ ] **Step 1: Write failing route tests**

```python
def test_create_workspace_uses_authenticated_header_not_request_actor(client):
    response = client.post(
        "/workspaces",
        headers={"X-Shipyard-Identity": "alice"},
        json={"workspace_id": "ws-1", "project_id": "p1", "name": "Delivery", "domain_pack": "software_delivery"},
    )
    assert response.status_code == 201
    assert response.json()["owner"] == "alice"


def test_request_body_actor_is_rejected(client):
    response = client.post(
        "/workspaces",
        headers={"X-Shipyard-Identity": "alice"},
        json={"workspace_id": "ws-1", "project_id": "p1", "name": "Delivery", "domain_pack": "software_delivery", "actor": "attacker"},
    )
    assert response.status_code == 422


def test_release_candidate_route_returns_conflict_when_gate_is_not_passed(client):
    response = client.post(
        "/workspaces/ws-1/release-candidates",
        headers={"X-Shipyard-Identity": "alice"},
        json={"artifact_ids": ["artifact-1"], "gate_run_ids": []},
    )
    assert response.status_code == 409
```

- [ ] **Step 2: Run route tests to verify failure**

Run: `pytest tests/api/test_shipyard_routes.py -q`

Expected: route import or 404 failures because the Workbench router is absent.

- [ ] **Step 3: Add strict request/response models and identity dependency**

Use `extra="forbid"` for all mutating Workbench request models. Resolve `X-Shipyard-Identity` through the configured `IdentityProvider`; missing or unknown identities return 401/403. Never copy an actor value from JSON into a Principal.

- [ ] **Step 4: Add routes that delegate to the service**

The route layer performs HTTP translation only. It must not call the Registry, GateEngine, Action Broker, or Domain Pack directly. Map `UnauthorizedError` to 403, stale revision to 409, release eligibility failures to 409, validation failures to 422, and missing records to 404.

- [ ] **Step 5: Mount the router without breaking the existing API**

Keep the current stage/action routes and tests unchanged. Add the Workbench service as an optional dependency so existing callers can still build the legacy sandbox API while the new Workbench API is explicitly configured.

- [ ] **Step 6: Run API regression tests**

Run: `pytest tests/api tests/shipyard/test_service.py -q`

Expected: all existing and new API tests pass.

- [ ] **Step 7: Commit**

```powershell
git add src/aifde/api/shipyard_routes.py src/aifde/api/app.py src/aifde/api/__init__.py tests/api/test_shipyard_routes.py
git commit -m "feat: expose Shipyard Workbench API"
```

### Task 5: Build the minimal React/TypeScript Workbench

**Files:**

- Create: `workbench/package.json`
- Create: `workbench/package-lock.json`
- Create: `workbench/index.html`
- Create: `workbench/tsconfig.json`
- Create: `workbench/vite.config.ts`
- Create: `workbench/src/main.tsx`
- Create: `workbench/src/App.tsx`
- Create: `workbench/src/api.ts`
- Create: `workbench/src/types.ts`
- Create: `workbench/src/styles.css`
- Test: `workbench/src/App.test.tsx`

**Interfaces:**

- `ShipyardApi.listWorkspaces(): Promise<ProjectWorkspace[]>`.
- `ShipyardApi.getSnapshot(workspaceId): Promise<WorkspaceSnapshot>`.
- `ShipyardApi.createDecisionCase(workspaceId, input): Promise<DecisionCase>`.
- `ShipyardApi.decideProposal(proposalId, decision): Promise<AgentProposal>`.
- `App` renders Project Home, Decision Case summary, Artifact Review, Gate Review, and Release Candidate status from `WorkspaceSnapshot`.
- `WorkspaceSnapshot` contains the latest Workspace revision plus Decision Cases, Artifact summaries, Proposal histories, Gate Review histories, Release Candidates and the audit tail needed by the review screen.

- [ ] **Step 1: Create the failing UI test**

The test module also defines a complete `fakeApiWithBlockedGate` object that
implements the `ShipyardApi` interface with deterministic `Promise.resolve`
responses: one workspace, one decision case named
`软件需求对齐与工期预测`, and one blocked `semantic.integrity` gate. The
object is passed as a prop so the component test does not require a running
backend.

```tsx
it("renders the workspace decision and blocks release when a gate is blocked", async () => {
  render(<App api={fakeApiWithBlockedGate} />);
  expect(await screen.findByText("软件需求对齐与工期预测")).toBeVisible();
  expect(screen.getByText("Release Candidate blocked")).toBeVisible();
  expect(screen.getByText("semantic.integrity")).toBeVisible();
});
```

- [ ] **Step 2: Install the minimal frontend toolchain and run the failing test**

Run: `cd workbench; npm install; npm test -- --run`

Expected: test file or `App` import is absent, so the test fails before implementation.

- [ ] **Step 3: Implement typed API client and query state**

Use `@tanstack/react-query`, `VITE_SHIPYARD_API_URL`, `X-Shipyard-Identity` from a local development setting, and typed response models. Mutations invalidate only the affected workspace snapshot query.

- [ ] **Step 4: Implement the review-first layout**

Build a compact three-pane layout: workspace/phase navigation, artifact and gate lists, and selected detail panel. The UI must show content hashes, versions, evidence references, gate status, stale state and blocking reasons. It must not expose an Agent “approve” control or a production Action control.

- [ ] **Step 5: Implement the blocked-release state**

When any required Gate Review is not passed or is stale, display the blocking gate IDs and disable the Release Candidate action. When all gates pass, show the release action as available but still require the authenticated human API call.

- [ ] **Step 6: Run frontend tests and build**

Run: `cd workbench; npm test -- --run; npm run build`

Expected: Vitest passes and Vite emits a production build under `workbench/dist`.

- [ ] **Step 7: Commit**

```powershell
git add workbench
git commit -m "feat: add Shipyard Workbench review surface"
```

### Task 6: Seed the software-delivery vertical slice and prove the end-to-end review loop

**Files:**

- Create: `src/aifde/shipyard/bootstrap.py`
- Create: `scripts/shipyard_seed.py`
- Modify: `src/software_delivery_demo/app.py`
- Create: `tests/shipyard/test_software_delivery_slice.py`
- Create: `tests/e2e/test_shipyard_workbench_flow.py`
- Modify: `docs/production-ai-fde-acceptance.md`
- Modify: `docs/README.md`

**Interfaces:**

- `seed_software_delivery_workspace(service, project_root, owner) -> ProjectWorkspace`.
- `seed_software_delivery_artifacts(service, workspace_id, owner) -> list[Artifact]`.
- `run_workbench_gate_snapshot(service, workspace_id, artifact_ids) -> list[GateReviewSnapshot]`.
- `scripts/shipyard_seed.py --database PATH --owner USER` creates a local SQLite Workbench workspace without connecting to Linear or customer systems.

- [ ] **Step 1: Write the failing integration test**

The test module defines `build_shipyard_test_runtime(tmp_path)` returning a
temporary registry and service, plus `human_principal(subject)` and
`system_principal()` factories. Bootstrap writes all records through the
service boundary; the registry is passed only as the service's persistence
dependency.

```python
import pytest


def test_software_delivery_workbench_blocks_then_allows_release(tmp_path: Path) -> None:
    registry, service = build_shipyard_test_runtime(tmp_path)
    workspace = seed_software_delivery_workspace(
        service, Path("projects/software-delivery-demo"), "alice"
    )
    artifacts = seed_software_delivery_artifacts(
        service, workspace.workspace_id, "alice"
    )
    with pytest.raises(ReleaseBlockedError, match="missing required gate"):
        service.create_release_candidate(
            workspace.workspace_id,
            [artifact.artifact_id for artifact in artifacts],
            [],
            human_principal("alice"),
        )

    initial_reviews = run_workbench_gate_snapshot(
        service,
        workspace.workspace_id,
        [artifact.artifact_id for artifact in artifacts],
    )
    assert {review.gate_id for review in initial_reviews} == service.required_gate_ids
    passed_reviews = []
    for review in initial_reviews:
        passed = review.model_copy(
            update={
                "gate_run_id": f"{review.gate_id}:passed:1",
                "status": "passed",
                "stale": False,
            }
        )
        passed_reviews.append(
            service.record_gate_review(passed, system_principal())
        )

    candidate = service.create_release_candidate(
        workspace.workspace_id,
        [artifact.artifact_id for artifact in artifacts],
        [review.gate_run_id for review in passed_reviews],
        human_principal("alice"),
    )
    assert candidate.status == "candidate"
    assert candidate.manifest["artifact_hashes"] == {
        artifact.artifact_id: artifact.content_hash for artifact in artifacts
    }
```

The first version of the test must assert the actual exception, then add Gate Review records and assert a `ReleaseCandidate` is created only after all required reviews pass. It must also assert that the resulting manifest references the exact Artifact content hashes.

- [ ] **Step 2: Run the integration test and verify failure**

Run: `pytest tests/shipyard/test_software_delivery_slice.py tests/e2e/test_shipyard_workbench_flow.py -q`

Expected: missing seed/bootstrap functions or missing Workbench records.

- [ ] **Step 3: Build the deterministic seed from existing project assets**

Read `projects/software-delivery-demo/config/project.yaml`, `decisions/problem.yaml`, `ontology/domain.ttl`, `data_products/contracts.yaml`, `features/definitions.yaml`, and `models/model_policy.yaml`. Register them as typed Artifact content with evidence references and `producer="shipyard-seed"`; do not execute an external Action.

- [ ] **Step 4: Adapt existing demo pipeline output into Gate Review snapshots**

Use the existing `software_delivery_demo.pipeline` only in the sandbox. Convert its deterministic stage/gate results into `GateReviewSnapshot` records with validator version, Artifact hashes, evidence references and stale status. Preserve the existing pipeline behavior; this adapter only maps results into Workbench records.

- [ ] **Step 5: Add the local seed command and Workbench snapshot E2E test**

The command creates the parent directory when needed, then creates a local
database, seed workspace, decision case, Artifact list and initial Gate Review.
The E2E test exercises: create workspace → create decision case → see
Artifact/Gate snapshot → submit Agent Proposal → human returns it → record
passed Gate Reviews → create Release Candidate → verify audit events and
manifest hash.

- [ ] **Step 6: Run the complete Phase 0 verification**

Run:

```powershell
pytest tests/shipyard tests/api tests/e2e -q
cd workbench; npm test -- --run; npm run build
cd ..; python scripts/shipyard_seed.py --database .tmp/shipyard.db --owner alice
```

Expected: Python and frontend tests pass, the Workbench build succeeds, and the seed command writes only the local database and no external system.

- [ ] **Step 7: Update the acceptance boundary and commit**

Document that Phase 0 delivers Workbench review and release eligibility, not a customer runtime, full ML evaluation lab, production connectors, Docker deployment or Linear integration.

```powershell
git add src/aifde/shipyard/bootstrap.py scripts/shipyard_seed.py src/software_delivery_demo/app.py tests/shipyard/test_software_delivery_slice.py tests/e2e/test_shipyard_workbench_flow.py docs/production-ai-fde-acceptance.md docs/README.md
git commit -m "feat: prove Shipyard Workbench software delivery slice"
```

## Phase 0 Acceptance Checklist

- [ ] Human identity is resolved outside request bodies and is required for human writes.
- [ ] Agent Proposal can be submitted but cannot approve itself or create a Release Candidate.
- [ ] Artifact versions, hashes, evidence references and validation results are visible in the Workbench snapshot.
- [ ] Gate Review is append-only and stale/failed/pending results block release.
- [ ] Release Candidate manifest is deterministic and references exact Artifact and Gate IDs.
- [ ] The Workbench UI can complete the review flow without Linear.
- [ ] The software-delivery seed and sandbox pipeline do not call a customer system or execute a production Action.
- [ ] Python focused tests, existing API/gate tests, frontend tests and frontend build pass.

## Deliberate Follow-up Plans

This plan intentionally stops after the first reviewable Workbench slice. The following are separate plans so each produces independently testable software:

1. Evaluation Lab: point-in-time feature/label snapshots, temporal model evaluation, replay and baseline comparison.
2. Ontology/Data Product Studio: evidence graph, semantic candidates, mapping compiler, SHACL diff and data-product quality review.
3. Domain Agent Team: Task Packet, Artifact Workspace, DAG orchestration, Challenger and budget/stale controls.
4. Release Dock: installable `DecisionSystemRelease`, deployment manifest, rollback, feedback intake and client-runtime handoff.
5. Docker deployment: PostgreSQL/object storage/queue adapters for Shipyard services only; Linear remains an optional adapter.
