# Linear Human-Agent Collaboration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Implement a domain-independent Task Contract and lifecycle kernel that lets humans coordinate governed Agent runs through Real/Fake Linear adapters without making Linear the execution source of truth.

**Architecture:** Build a pure Pydantic task/lifecycle layer first, then add a persistent task store, Linear protocol adapters, and a Bridge that converts Linear events into internal commands and Outbox events. The existing DomainAgentTeam remains the execution kernel; the Bridge never calls a model or external Action directly.

**Tech Stack:** Python 3.11+, Pydantic v2, SQLite for offline persistence, standard-library HTTP transport for the Real Linear adapter, pytest, existing DomainAgentTeam, ArtifactWorkspace, GateEngine, PolicyEngine, Audit and Metrics components.

## Global Constraints

- AI-FDE internal lifecycle, Gate, Artifact, Audit and Action Policy are execution facts; Linear is the human control surface and projection.
- RealLinearAdapter and FakeLinearAdapter must implement the same protocol and must not fork business lifecycle logic.
- Agents may propose typed artifacts only; they cannot change Linear state, approve their own output, or execute production Actions.
- Every task run is bound to one immutable Task Contract version; a contract change makes active runs stale.
- Default maximum fix rounds is 3; checks failure stays In Progress and produces a failure comment.
- Every state transition has an event id, actor, run id, contract version and expected previous state.
- Tests must prove a desired behavior fails before its production implementation is written.
- No Linear token or model credential may appear in tests, comments, logs or committed files.

---

## Task 1: Add the Task Contract and lifecycle state machine

**Files:**
- Create: src/aifde/task/__init__.py
- Create: src/aifde/task/contracts.py
- Create: src/aifde/task/lifecycle.py
- Test: tests/task/test_task_contract.py
- Test: tests/task/test_task_lifecycle.py

**Interfaces:**

- Produces TaskStatus, TaskContract, TaskContractVersion, TaskRecord, TaskEvent, LifecycleTransitionError and TaskLifecycle.
- TaskLifecycle.transition(current: TaskStatus, event: str) -> TaskStatus is pure and deterministic.
- TaskContract exposes task_id, project_id, domain_pack, task_kind, objective, decision_owner, required_outputs, acceptance, evidence_refs, risk_tier, human_checkpoints, max_fix_rounds and timeout_seconds.

- [ ] **Step 1: Write the failing contract tests**

~~~python
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
~~~

- [ ] **Step 2: Run the contract test and verify the expected missing-module failure**

Run: pytest tests/task/test_task_contract.py -q

Expected: collection fails because aifde.task.contracts does not exist.

- [ ] **Step 3: Write the failing lifecycle tests**

~~~python
def test_review_gate_pass_enters_human_approval():
    assert TaskLifecycle.transition(TaskStatus.REVIEWING, "gates_pass") == TaskStatus.AWAITING_HUMAN


def test_agent_cannot_directly_complete_a_task():
    with pytest.raises(LifecycleTransitionError):
        TaskLifecycle.transition(TaskStatus.REVIEWING, "agent_done")
~~~

- [ ] **Step 4: Run the lifecycle test and verify it fails for the missing state machine**

Run: pytest tests/task/test_task_lifecycle.py -q

Expected: collection fails because aifde.task.lifecycle does not exist.

- [ ] **Step 5: Implement the minimal models and transition table**

Use Pydantic frozen models. Define these states:

~~~python
class TaskStatus(str, Enum):
    INTAKE = "intake"
    NEEDS_INFO = "needs_info"
    READY = "ready"
    RUNNING = "running"
    CHECKS_FAILED = "checks_failed"
    REVIEWING = "reviewing"
    FIX_REQUESTED = "fix_requested"
    AWAITING_HUMAN = "awaiting_human"
    APPROVED = "approved"
    ACTION_PENDING = "action_pending"
    RELEASED = "released"
    STALE = "stale"
    CANCELED = "canceled"
~~~

Implement only transitions required by the approved design. Reject unknown events and illegal transitions with LifecycleTransitionError.

- [ ] **Step 6: Run the focused tests and verify they pass**

Run: pytest tests/task/test_task_contract.py tests/task/test_task_lifecycle.py -q

Expected: all focused tests pass.

- [ ] **Step 7: Commit**

~~~text
git add src/aifde/task tests/task
git commit -m "feat: add governed task contract lifecycle"
~~~

## Task 2: Add Task Contract parsing and Linear comment commands

**Files:**
- Create: src/aifde/task/parser.py
- Create: src/aifde/integrations/__init__.py
- Create: src/aifde/integrations/linear/__init__.py
- Create: src/aifde/integrations/linear/comments.py
- Test: tests/task/test_task_parser.py
- Test: tests/integrations/linear/test_comments.py

**Interfaces:**

- parse_task_description(description: str, task_id: str) -> TaskContract
- parse_human_command(body: str) -> HumanCommand | None
- parse_structured_event(body: str) -> LinearCommentEvent | None
- render_event_comment(event: LinearCommentEvent, human_summary: str) -> str

- [ ] **Step 1: Write failing parser and command tests**

~~~python
def test_parser_reads_aifde_task_v1_yaml_block():
    description = """
    业务目标：预测工期
    [aifde_version: 1 YAML block with project_id, domain_pack,
    task_kind, objective, decision.owner, outputs.required and acceptance]
    """
    contract = parse_task_description(description, "linear:LAC-1")
    assert contract.decision_owner == "product-owner"
    assert contract.required_outputs == ("ForecastReport",)


def test_parser_rejects_missing_contract_fields():
    with pytest.raises(TaskContractParseError, match="acceptance"):
        parse_task_description("aifde_version: 1 without acceptance", "linear:LAC-2")


def test_approve_command_requires_run_and_scope():
    command = parse_human_command("/aifde approve run=run-1 scope=ontology")
    assert command.kind == "approve"
    assert command.run_id == "run-1"
    assert command.scope == "ontology"
~~~

- [ ] **Step 2: Run the parser tests and verify they fail**

Run: pytest tests/task/test_task_parser.py tests/integrations/linear/test_comments.py -q

Expected: collection fails because parser and comment modules do not exist.

- [ ] **Step 3: Implement strict parsing**

Extract the first aifde_version 1 YAML fence, reject duplicate blocks, reject unknown top-level contract keys, and map the Chinese acceptance section only as a compatibility fallback. Free-form comments must never become commands.

The command parser must accept approve, revise, pause, reopen and cancel. It must reject missing run, malformed key/value pairs and unknown command names.

- [ ] **Step 4: Implement structured comment rendering**

Render the stable header:

~~~text
[aifde][agent:<producer>][run:<run_id>]
event: <event_type>
status: <status>
artifact_refs: <comma-separated refs>
evidence_refs: <comma-separated refs>
gate_refs: <comma-separated refs>
~~~

Do not include raw evidence content or secrets.

- [ ] **Step 5: Run focused parser tests and verify they pass**

Run: pytest tests/task/test_task_parser.py tests/integrations/linear/test_comments.py -q

Expected: all focused tests pass.

- [ ] **Step 6: Commit**

~~~text
git add src/aifde/task/parser.py src/aifde/integrations tests/task/test_task_parser.py tests/integrations/linear/test_comments.py
git commit -m "feat: parse governed linear task contracts and commands"
~~~

## Task 3: Add an append-only task store with Inbox and Outbox

**Files:**
- Create: src/aifde/task/store.py
- Create: src/aifde/task/sqlite_store.py
- Create: src/aifde/task/events.py
- Test: tests/task/test_task_store.py
- Test: tests/task/test_task_store_idempotency.py

**Interfaces:**

- TaskStore.create_contract(contract: TaskContract) -> TaskRecord
- TaskStore.get(task_id: str) -> TaskRecord
- TaskStore.append_event(event: TaskEvent) -> TaskEvent
- TaskStore.apply_transition(task_id, event_name, actor, expected_state, run_id, contract_version) -> TaskRecord
- TaskStore.put_inbox(provider, external_event_id, payload_hash, payload) -> bool
- TaskStore.enqueue_outbox(event_type, target, task_id, payload, idempotency_key) -> OutboxEvent
- TaskStore.pending_outbox(limit: int) -> list[OutboxEvent]
- TaskStore.mark_outbox_delivered(outbox_id: str) -> None

- [ ] **Step 1: Write failing persistence and idempotency tests**

~~~python
def test_transition_requires_expected_current_state(tmp_path):
    store = SQLiteTaskStore(tmp_path / "tasks.db")
    task = store.create_contract(valid_contract())
    with pytest.raises(TaskStateConflict):
        store.apply_transition(
            task.task_id, "dispatch", actor="bridge",
            expected_state=TaskStatus.RUNNING, run_id=None,
            contract_version=1,
        )


def test_duplicate_inbox_event_is_ignored(tmp_path):
    store = SQLiteTaskStore(tmp_path / "tasks.db")
    assert store.put_inbox("linear", "event-1", "hash-1", {"x": 1}) is True
    assert store.put_inbox("linear", "event-1", "hash-1", {"x": 1}) is False


def test_outbox_idempotency_returns_one_event(tmp_path):
    store = SQLiteTaskStore(tmp_path / "tasks.db")
    first = store.enqueue_outbox("comment", "linear", "task-1", {"body": "ok"}, "key-1")
    second = store.enqueue_outbox("comment", "linear", "task-1", {"body": "ok"}, "key-1")
    assert first.outbox_id == second.outbox_id
~~~

- [ ] **Step 2: Run the store tests and verify they fail**

Run: pytest tests/task/test_task_store.py tests/task/test_task_store_idempotency.py -q

Expected: collection fails because the store module does not exist.

- [ ] **Step 3: Implement the SQLite schema and append-only operations**

Use one SQLite transaction for state change plus its Outbox insertion. Store payloads as canonical JSON and hash the Inbox payload. Make event and outbox insertions idempotent by unique provider/event and idempotency key constraints.

- [ ] **Step 4: Run focused store tests and verify they pass**

Run: pytest tests/task/test_task_store.py tests/task/test_task_store_idempotency.py -q

Expected: all focused tests pass.

- [ ] **Step 5: Commit**

~~~text
git add src/aifde/task tests/task/test_task_store.py tests/task/test_task_store_idempotency.py
git commit -m "feat: add append-only task inbox and outbox store"
~~~

## Task 4: Implement FakeLinearAdapter

**Files:**
- Create: src/aifde/integrations/linear/protocol.py
- Create: src/aifde/integrations/linear/fake.py
- Test: tests/integrations/linear/test_fake_adapter.py

**Interfaces:**

- LinearIssue, LinearComment, LinearEvent, LinearEventPage and LinearStateResult are frozen Pydantic models.
- LinearAdapter.list_events(cursor: str | None) -> LinearEventPage
- LinearAdapter.get_issue(issue_id: str) -> LinearIssue
- LinearAdapter.get_comments(issue_id: str) -> tuple[LinearComment, ...]
- LinearAdapter.post_comment(issue_id: str, body: str, idempotency_key: str) -> LinearComment
- LinearAdapter.transition_issue(issue_id: str, target_state: str, idempotency_key: str) -> LinearStateResult

- [ ] **Step 1: Write failing Fake Adapter tests**

~~~python
def test_fake_adapter_replays_events_and_deduplicates_comments():
    adapter = FakeLinearAdapter()
    issue = adapter.create_issue("[task] Forecast", valid_description())
    first = adapter.post_comment(issue.id, "hello", "comment-key")
    second = adapter.post_comment(issue.id, "hello", "comment-key")
    assert first.id == second.id
    page = adapter.list_events(None)
    assert [event.issue_id for event in page.events] == [issue.id]
~~~

- [ ] **Step 2: Run the test and verify it fails**

Run: pytest tests/integrations/linear/test_fake_adapter.py -q

Expected: collection fails because protocol and fake adapter do not exist.

- [ ] **Step 3: Implement the protocol models and deterministic fake**

The Fake Adapter must support issue creation, comments, state transitions, event cursoring, duplicate comments, human comments and direct state changes used by conflict tests. It must not contain lifecycle decisions.

- [ ] **Step 4: Run the focused test and verify it passes**

Run: pytest tests/integrations/linear/test_fake_adapter.py -q

Expected: all focused tests pass.

- [ ] **Step 5: Commit**

~~~text
git add src/aifde/integrations/linear tests/integrations/linear/test_fake_adapter.py
git commit -m "feat: add fake linear adapter"
~~~

## Task 5: Implement LinearBridge and internal state projection

**Files:**
- Create: src/aifde/integrations/linear/bridge.py
- Test: tests/integrations/linear/test_bridge.py
- Test: tests/integrations/linear/test_bridge_failure_paths.py

**Interfaces:**

- LinearBridge(adapter: LinearAdapter, store: TaskStore, task_dispatcher: Callable)
- LinearBridge.poll_once(cursor: str | None) -> BridgeResult
- LinearBridge.process_issue(issue: LinearIssue) -> IssueProcessResult
- LinearBridge.publish_outbox(limit: int) -> int

- [ ] **Step 1: Write failing Bridge tests**

~~~python
def test_valid_task_creates_contract_and_dispatch_outbox():
    adapter = FakeLinearAdapter()
    issue = adapter.create_issue("[task] Forecast", valid_description())
    store = SQLiteTaskStore(":memory:")
    bridge = LinearBridge(adapter, store, task_dispatcher=record_dispatch)
    result = bridge.poll_once(None)
    assert result.processed == (issue.identifier,)
    task = store.get(f"linear:{issue.identifier}")
    assert task.status == TaskStatus.READY
    assert dispatched == [task.task_id]


def test_invalid_task_stays_needs_info_and_never_dispatches():
    adapter = FakeLinearAdapter()
    issue = adapter.create_issue("[task] Missing", "no contract")
    store = SQLiteTaskStore(":memory:")
    bridge = LinearBridge(adapter, store, task_dispatcher=record_dispatch)
    bridge.poll_once(None)
    assert store.get(f"linear:{issue.identifier}").status == TaskStatus.NEEDS_INFO
    assert dispatched == []
~~~

- [ ] **Step 2: Run Bridge tests and verify they fail**

Run: pytest tests/integrations/linear/test_bridge.py tests/integrations/linear/test_bridge_failure_paths.py -q

Expected: collection fails because LinearBridge does not exist.

- [ ] **Step 3: Implement intake, contract validation and event projection**

Filter [task] issues in Backlog and Todo. Write the external event to Inbox, parse the contract, create or version the task, and enqueue an internal dispatch event only after the contract is valid. Publish missing-field comments through Outbox.

Map internal states to Linear states without changing internal truth. Keep checks failure in In Progress. Make one issue failure isolated from the rest of the poll.

- [ ] **Step 4: Implement review feedback and fix-loop rules**

Interpret structured human approve/revise/pause/reopen/cancel commands only after actor authorization supplied by an injected policy callback. Convert reviewer major/blocker comments to fix_requested and enforce max_fix_rounds. Convert minor-only review to awaiting_human.

- [ ] **Step 5: Run focused Bridge tests and verify they pass**

Run: pytest tests/integrations/linear/test_bridge.py tests/integrations/linear/test_bridge_failure_paths.py -q

Expected: all focused tests pass.

- [ ] **Step 6: Commit**

~~~text
git add src/aifde/integrations/linear tests/integrations/linear/test_bridge.py tests/integrations/linear/test_bridge_failure_paths.py
git commit -m "feat: add linear task lifecycle bridge"
~~~

## Task 6: Connect Task dispatch to DomainAgentTeam

**Files:**
- Create: src/aifde/orchestration/task_dispatch.py
- Modify: src/aifde/orchestration/runner.py
- Test: tests/orchestration/test_task_dispatch.py
- Test: tests/e2e/test_linear_agent_team_flow.py

**Interfaces:**

- DomainTaskDispatcher(stage_runner: StageRunner, graph_selector: Callable)
- DomainTaskDispatcher.dispatch(task: TaskRecord) -> DispatchResult
- graph_selector(domain_pack: str, task_kind: str) -> AgentGraph

- [ ] **Step 1: Write failing dispatch tests**

~~~python
def test_dispatcher_selects_domain_graph_and_calls_domain_team():
    dispatcher = DomainTaskDispatcher(
        stage_runner=fake_stage_runner,
        graph_selector=lambda domain, kind: AgentGraph.default_supplier_delay(),
    )
    result = dispatcher.dispatch(valid_task_record())
    assert result.graph_id == "supplier-delay"
    assert result.status == "requested"
~~~

- [ ] **Step 2: Run the tests and verify they fail**

Run: pytest tests/orchestration/test_task_dispatch.py tests/e2e/test_linear_agent_team_flow.py -q

Expected: collection fails because task_dispatch.py does not exist.

- [ ] **Step 3: Implement the dispatcher as a side-effect-limited adapter**

The dispatcher may create an AgentRun request and invoke the injected StageRunner/DomainAgentTeam boundary. It must not post comments, change Linear state or execute Action. Return run id, graph id and idempotency key for the Bridge/Worker layer.

- [ ] **Step 4: Add one Fake Linear to AgentTeam integration scenario**

Use a deterministic executor and an in-memory ArtifactWorkspace. Assert that a candidate is committed only through DomainAgentTeam, carries evidence refs, and produces an internal run result that the Bridge can project.

- [ ] **Step 5: Run focused orchestration tests and verify they pass**

Run: pytest tests/orchestration/test_task_dispatch.py tests/e2e/test_linear_agent_team_flow.py -q

Expected: all focused tests pass.

- [ ] **Step 6: Commit**

~~~text
git add src/aifde/orchestration tests/orchestration/test_task_dispatch.py tests/e2e/test_linear_agent_team_flow.py
git commit -m "feat: connect linear tasks to governed agent teams"
~~~

## Task 7: Implement RealLinearAdapter and webhook verification

**Files:**
- Create: src/aifde/integrations/linear/real.py
- Create: src/aifde/integrations/linear/transport.py
- Create: src/aifde/integrations/linear/webhook.py
- Test: tests/integrations/linear/test_real_adapter.py
- Test: tests/integrations/linear/test_webhook.py

**Interfaces:**

- GraphQLTransport.post(payload: dict[str, Any]) -> dict[str, Any]
- RealLinearAdapter(transport: GraphQLTransport, api_key: str, team_id: str)
- verify_linear_webhook(raw_body: bytes, signature: str, secret: str) -> bool

- [ ] **Step 1: Write failing transport and webhook tests**

~~~python
def test_real_adapter_sends_linear_key_without_bearer_prefix():
    transport = RecordingTransport({"data": {"issues": {"nodes": []}}})
    adapter = RealLinearAdapter(transport, api_key="secret", team_id="team-1")
    adapter.list_events(None)
    assert transport.headers["Authorization"] == "secret"


def test_webhook_rejects_wrong_signature():
    assert verify_linear_webhook(b"{}", "bad", "secret") is False
~~~

- [ ] **Step 2: Run the tests and verify they fail**

Run: pytest tests/integrations/linear/test_real_adapter.py tests/integrations/linear/test_webhook.py -q

Expected: collection fails because the Real Adapter modules do not exist.

- [ ] **Step 3: Implement GraphQL calls with injected transport**

Support issue pagination, comment creation, state transition, archive and cursor mapping. Use bounded retry for transport errors and raise a typed LinearAdapterError after the final attempt. Never log the API key or raw response payload when it may contain sensitive data.

- [ ] **Step 4: Implement HMAC webhook verification**

Use constant-time comparison. Reject missing, malformed or mismatched signatures. The webhook handler will only enqueue an Inbox event; it will not execute Agent work in the HTTP request.

- [ ] **Step 5: Run focused Real Adapter tests and verify they pass**

Run: pytest tests/integrations/linear/test_real_adapter.py tests/integrations/linear/test_webhook.py -q

Expected: all focused tests pass.

- [ ] **Step 6: Commit**

~~~text
git add src/aifde/integrations/linear tests/integrations/linear/test_real_adapter.py tests/integrations/linear/test_webhook.py
git commit -m "feat: add real linear graphql adapter"
~~~

## Task 8: Add the complete Fake Linear lifecycle acceptance suite

**Files:**
- Create: tests/e2e/test_linear_human_agent_lifecycle.py
- Modify: README.md
- Create: docs/linear-human-agent-operations.md

- [ ] **Step 1: Write the failing scenario table**

The suite must cover:

1. valid task: intake → ready → running → reviewing → awaiting_human → approved;
2. missing contract field: needs_info and no dispatch;
3. checks failure: In Progress and failure comment;
4. minor review: no fix dispatch;
5. major review: fix_requested → running → reviewing;
6. three failed rounds: human escalation;
7. human state conflict: internal state remains authoritative;
8. duplicate webhook/comment: one Inbox event and one Outbox effect;
9. contract edit: old run stale and new contract version ready;
10. unauthorized approve: command rejected and audit event written.

- [ ] **Step 2: Run the new suite and verify it fails**

Run: pytest tests/e2e/test_linear_human_agent_lifecycle.py -q

Expected: failures identify missing lifecycle/Bridge behavior, not import errors.

- [ ] **Step 3: Implement only the missing integration behavior**

Do not loosen tests to accommodate implementation shortcuts. Keep assertions on internal state, Linear projection, comment references, run ids, contract versions and idempotency.

- [ ] **Step 4: Run the complete Linear suite**

Run: pytest tests/task tests/integrations/linear tests/orchestration/test_task_dispatch.py tests/e2e/test_linear_agent_team_flow.py tests/e2e/test_linear_human_agent_lifecycle.py -q

Expected: all Linear collaboration tests pass.

- [ ] **Step 5: Update operational documentation**

Document how a human creates a Task Contract, responds to needs_info, approves a scope, reopens a task and handles escalation. Include Fake Adapter commands and the real environment variable names without real secrets.

- [ ] **Step 6: Commit**

~~~text
git add README.md docs/linear-human-agent-operations.md tests/e2e/test_linear_human_agent_lifecycle.py
git commit -m "docs: add linear human agent lifecycle operations"
~~~

## Final Linear Plan Verification

- [ ] Run pytest tests/task tests/integrations/linear tests/orchestration tests/e2e/test_linear_agent_team_flow.py tests/e2e/test_linear_human_agent_lifecycle.py -q
- [ ] Run python -m compileall -q src tests
- [ ] Run git diff --check
- [ ] Confirm no production code imports a concrete Linear adapter inside DomainAgentTeam
- [ ] Confirm all state changes are represented by TaskEvent and Outbox records
- [ ] Confirm an Agent cannot transition a task to Done or invoke an Action
