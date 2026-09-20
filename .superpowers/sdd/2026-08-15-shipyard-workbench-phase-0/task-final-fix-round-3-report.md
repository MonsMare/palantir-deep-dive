# Task Final Review Fix Round 3 报告

日期：2026-08-15

本轮实现基线为 `e50e83d`，只读审查报告为 `b5a4e06`。本轮只处理唯一 Important I-1：Workspace 资源级授权缺失；final review 中的 M-1～M-6 均未作为本轮实现目标。

## 结论

I-1 已关闭。Phase 0 现在采用 owner-only human workspace policy，并在 Service 和 API 两层执行：

- 已验证 human 只能列出和读取自己拥有的 Workspace；Bob 对 Alice Workspace 的 detail、decision cases、snapshot 返回 403，Bob 的 workspace list 只返回自己的 owner workspaces；
- `create_decision_case`、`register_artifact`、`decide_proposal` 在 Service 事务内读取实际 Workspace/Proposal owner，要求 principal subject 等于 `workspace.owner` 且具备 `workspace-owner` role；
- `create_release_candidate` 在 Service 事务内要求实际 owner 且具备 `release-owner` role；Bob 不能代表 Alice 创建 ready Candidate；
- Artifact 的 `project_id`、`owner` 和 workspace membership 也在 Service 内校验；Agent Proposal 的 `affected_artifact_ids` 必须属于目标 Workspace，避免跨 workspace 引用；
- API 的 `GET /workspaces`、`GET /workspaces/{id}`、`GET /decision-cases`、`GET /snapshot` 均把已验证 Principal 传入 Service，不再丢弃 principal；
- Agent 只有 `agent + builder` 身份才能提交 Proposal，不能审批、登记 Artifact 或创建 Release Candidate；system 只有 `system + gate-runner` 身份才能记录 Gate Review，不获得 human owner 权限；
- bootstrap/evaluator 使用明确的 `_get_workspace_internal` 和 `_get_workspace_snapshot_internal` 读取 helper，公开 Service read 方法不再提供无 Principal 绕过；
- Workspace owner 仍由 `create_workspace` 使用已验证 Principal 强制写入，未从 request body 读取 actor/owner 作为授权依据。成员 ACL 延后处理。

## 实现提交

- `157eef2` — `fix: enforce workspace owner authorization`

本轮报告单独作为后续 commit 提交。

## 回归测试

新增 Service 回归覆盖：

- Alice 创建 Workspace 后，Bob 的 read、Decision Case、Artifact、Proposal decision、Release Candidate 均被拒绝；
- owner 缺少 `workspace-owner` role 时只能读取，不能写 Decision Case；
- Agent 缺少 `builder` role 不能提交 Proposal；
- Agent Proposal 不能引用目标 Workspace 之外的 Artifact；
- Alice 仍可完成原有完整 Workbench flow，system gate-runner 仍可记录 Gate Review。

新增 API 回归覆盖：

- Bob 的 owner-filtered list、detail、decision-case list、snapshot 和 Decision Case write；
- Bob 对 Alice Proposal 的 decision 和 Release Candidate；
- Alice 创建、Agent 提案、system Gate Review 的既有路径不回归。

错误映射保持既有规则：未认证为 401，已认证但无 workspace 权限为 403，不存在 workspace/proposal 为 404，release/gate 业务阻断为 409。

## 验证结果

在 `157eef2` 提交前后，定向验证结果如下：

| 命令 | 结果 |
| --- | --- |
| `pytest tests/shipyard tests/api tests/gates tests/e2e -q` | 130 passed, 2 failed；两项均为既有 `builder_source_snapshots` 缺表基线失败 |
| `pytest tests/shipyard/test_service.py::test_workspace_owner_policy_blocks_cross_workspace_human_access tests/api/test_shipyard_routes.py::test_workspace_owner_policy_blocks_cross_workspace_reads_and_writes -q` | 2 passed |
| `npm test -- --run` | 13 passed |
| `npm run build` | `tsc --noEmit` 和 Vite production build 通过 |
| `python scripts/shipyard_seed.py --database .tmp\\final-review-fix-round3-cli\\nested\\shipyard.db --owner alice` | exit 0；父目录自动创建；六 Artifact、两 Gate Review；当前环境为 blocked/stale；`external_connections=[]`、`production_actions_executed=false` |
| changed-file `python -m py_compile ...` | 通过 |
| `git diff --check` | 通过 |

两个未解决的基线失败为：

- `tests/e2e/test_production_two_domain_flow.py::test_supplier_delay_completes_production_chain`
- `tests/e2e/test_production_two_domain_flow.py::test_software_delivery_completes_same_chain_without_supplier_keys`

错误均为 `sqlite3.OperationalError: no such table: builder_source_snapshots`，本轮未修改 builder persistence 路径。

## Final review 的 deferred observations

- M-1：bootstrap seed 仍不是跨步骤原子事务；后续增加 seed-run/preflight 或原子 bootstrap transaction。
- M-2：sandbox evaluator 可能产生本地 fixture/mock Action 副作用；后续隔离 evaluation workspace 并显式 dry-run contract。
- M-3：evaluator attestation 已包含 revision，但 Service 字段比较尚未单独比较 revision；后续补齐 revision/timestamp policy。
- M-4：Artifact 语义失败时 evidence 仍可能包含未实际执行的 sandbox pipeline reference；后续区分 skipped/blocked evidence。
- M-5：Workbench 尚未完整展示 source/input snapshot、validator/fingerprint、Artifact versions 和 outcome attestation；后续补充只读 provenance UI。
- M-6：前端 readiness 判定弱于后端 authoritative release policy；后续由后端提供 readiness projection 或复用同一严格判断。

本轮没有连接 Linear、客户系统或外部服务，没有执行生产 Action，也没有修改 progress ledger。
