# Shipyard Workbench Phase 0 Final Review Fix Round 3

审查基线：`e50e83d`

修复 HEAD：`5ff3864`

上一份全分支审查：`b5a4e06` / `task-final-review.md`

本轮范围：只复核原 Important I-1 Workspace 资源级授权；M-1～M-6 按要求继续 deferred，不作为本轮 blocker。

## I-1 disposition

**Closed.** 本轮修复已把 Phase 0 的访问策略明确为 owner-only human workspace policy，并在 Service、API 和回归测试中贯彻。

- `src/aifde/shipyard/service.py:181-212` 的 `_authorize_workspace` 使用 Registry 中实际读取的 `ProjectWorkspace.owner`，而不是请求体或调用方声明；read 要求 owner，write 要求 owner + `workspace-owner`，release 要求 owner + `release-owner`。
- `get_workspace`、`list_workspaces`、`list_decision_cases` 和 `get_workspace_snapshot` 都需要经过已验证的 human Principal；list 只返回 `owner == principal.subject` 的 workspace。`create_decision_case`、`register_artifact`、`decide_proposal` 和 `create_release_candidate` 在各自 `_write` transaction 的 operation 内重新读取实际 workspace/proposal 并执行 owner/role 校验，避免授权检查与写入状态脱节。证据：`src/aifde/shipyard/service.py:239-275`、`src/aifde/shipyard/service.py:369-443`、`src/aifde/shipyard/service.py:508-588`、`src/aifde/shipyard/service.py:754-800`。
- Artifact 写入现在只接受 human owner，且检查 Artifact `project_id` 与 workspace project 一致、Artifact `owner` 与 workspace owner 一致；Agent Proposal 要求 `agent + builder`，其 `affected_artifact_ids` 必须属于目标 workspace。Proposal decision 按 Proposal 实际归属 workspace 授权。没有发现 Bob 通过跨 workspace Artifact、Proposal 或 Gate 引用进入 Candidate 的路径。
- API 的 `GET /workspaces`、`GET /workspaces/{id}`、`GET /decision-cases` 和 `GET /snapshot` 均把依赖注入解析出的 Principal 传给 Service；list 进行 owner 过滤，跨 workspace detail/read/write 映射为 403，未知记录仍为 404，release/gate 业务阻断仍为 409。证据：`src/aifde/api/shipyard_routes.py:200-328`、`tests/api/test_shipyard_routes.py:430-545`。
- system Gate Review 仍要求 `system + gate-runner`，不被 human owner policy 误伤；agent builder proposal 和 Alice 的完整 Workbench flow 均继续通过。相关路径没有把 system/agent 角色提升为 human owner。
- 无公开的 Service read helper 可以无 Principal 读取：公开的 `get_workspace`/`list_workspaces`/`list_decision_cases`/`get_workspace_snapshot` 都带 Principal。`_get_workspace_internal` 和 `_get_workspace_snapshot_internal` 位于 Service 私有命名空间，仅由 `bootstrap.py` 的受信任 builder-side adapter 使用，未被 API router 暴露；API 不调用 Registry 或这些 helper。

### 受信任内部边界说明

`bootstrap.run_workbench_gate_snapshot` 仍是一个导出的 builder-side Python adapter，签名按 Phase 0 设计不接收 human Principal；它只调用 underscore-prefixed internal snapshot helper，返回未持久化 Gate snapshots，当前调用方是本地 seed CLI/测试而不是 HTTP/API。它依赖同进程 trusted internal module 约定，而不是 Python 强制 capability isolation。如果未来允许不可信插件与 Service 同进程运行，应再将该 adapter 收窄为私有入口或传入内部 capability；在本轮声明的 Phase 0 API/外部边界内，这不是 I-1 的新 release/security bypass。

## New findings

### Critical

None.

### Important

None. 原 I-1 的跨 workspace human 读写与 ready Candidate 路径已关闭；未发现新的权限绕过或 release eligibility 绕过。

### Minor

None new. M-1～M-6（seed 原子性、sandbox 副作用、attestation revision、未实际执行的 sandbox evidence、Workbench provenance 展示、前后端 readiness policy 差异）仍按上一份报告 deferred，本轮未扩大范围。

## Tests

- `pytest tests/shipyard/test_service.py::test_workspace_owner_policy_blocks_cross_workspace_human_access tests/api/test_shipyard_routes.py::test_workspace_owner_policy_blocks_cross_workspace_reads_and_writes -q`：`2 passed`。
- `pytest tests/shipyard/test_software_delivery_slice.py tests/e2e/test_shipyard_workbench_flow.py -q`：`19 passed`。
- `pytest tests/shipyard tests/api tests/gates tests/e2e -q`：`130 passed, 2 failed`；仅两个既有 `tests/e2e/test_production_two_domain_flow.py` 失败，均为未修改的 builder persistence 缺少 `builder_source_snapshots` 表。
- 受影响 Service/API/bootstrap/test Python 文件 `python -m py_compile`：通过。
- `npm test -- --run`：`13 passed`；`npm run build`：TypeScript 检查和 Vite production build 通过。
- `scripts/shipyard_seed.py --database <nested temp path> --owner alice`：exit 0，父目录自动创建，六个 Artifact 和两个 Gate Review 成功生成；当前环境为 passed/stale=false，输出 `external_connections=[]`、`production_actions_executed=false`。
- 受控临时 SQLite 探针：`bob_read=DENIED`、`bob_ready_candidate=DENIED`、`alice_ready_candidate=READY`。这同时验证了 Gate Review 仍可由 gate-runner 记录，以及 owner 的原有 release flow 未被误伤。
- `git diff --check e50e83d..5ff3864`：通过；工作树在写入本报告前无实现改动。

## Verdict

**Approved**

I-1 已关闭。修复后的 owner/role policy 在 Service transaction 内按实际 workspace ownership 执行，API read scope 已传递 Principal，Bob→Alice 的读取、业务写入和 ready Candidate 均被拒绝；Alice、agent builder 和 system gate-runner 的合法路径仍然可用。Phase 0 可以在当前声明的 trusted internal bootstrap boundary 下通过本轮 scoped re-review。
