# Shipyard Workbench Phase 0 整分支 Senior Code Review

审查基线：`382ed31`

审查 HEAD：`e50e83d`

审查范围：完整读取 `final-review-package.diff`、Phase 0 implementation plan、Task brief/progress ledger、当前实现、相关测试和既有审查报告；本次不修改实现代码，不做 checkout/reset。

## Strengths

- Service boundary 基本贯彻到位。API request model 使用 `extra="forbid"`，没有把 `actor`、`authority` 或审批字段作为可信输入；mutating route 通过身份 provider 解析 header，最终由 `ShipyardApplicationService` 再次 `verify`。Agent 只能提交 Proposal；human/system/agent 的操作类型边界和 `gate-runner` 角色均有测试覆盖。主要证据：`src/aifde/shipyard/identity.py:19-107`、`src/aifde/shipyard/service.py:122-181`、`src/aifde/api/shipyard_routes.py:29-184`。
- SQLite 持久化确实是追加式的：canonical JSON、content hash、revision、时间和身份字段会一起落盘；重复 identity/revision 被拒绝，Service 的领域记录和审计事件在同一事务中提交/回滚。重启、重复写入、revision history 和事务回滚测试均通过。主要证据：`src/aifde/registry/sqlite.py:365-405`、`src/aifde/registry/sqlite.py:768-1044`、`tests/shipyard/test_store.py:122-243`。
- 软件交付 evaluator 已从“检查调用方声明”提升为真实的注册 Artifact 评测：从 Registry 读取 canonical content，使用固定六个 Artifact ID 到 source path/kind/format 的映射，校验 source SHA、内容 envelope、YAML/Turtle 语义结构、缺失/额外输入，并将每个 Artifact 的 digest、semantic result 和 evidence 纳入结果。`record_gate_review` 与 `create_release_candidate` 会重新构建同一 evaluator outcome；blocked、stale、旧输入、错误 hash、旧 validator、空/不绑定 evidence 不能生成 ready Candidate。主要证据：`src/aifde/shipyard/provenance.py:111-242`、`src/aifde/shipyard/evaluator.py:66-186`、`src/aifde/shipyard/service.py:527-681`、`src/aifde/shipyard/service.py:688-901`。
- `outcome_attestation` 覆盖了 gate/run/status/stale、violations、Artifact hashes/versions、source/input snapshot、validator/fingerprint、evidence 和 stage states；blocked outcome 的篡改探针和确定性 passing snapshot 的 Candidate 测试均通过。旧 GateReview shape 仍可兼容写入，但不会获得软件交付 Candidate eligibility。
- Release manifest 按排序后的 Artifact hashes 和 Gate run IDs 计算 deterministic digest，E2E 确实覆盖 Agent Proposal → human return → Gate Review → Candidate → audit/manifest hash，而不是只检查 HTTP 200。定向 Python 测试 146 个全部通过。
- Phase 0 文档边界准确：Shipyard 是构建/评测/交付控制面，不是客户 production runtime；CLI 只创建本地 SQLite，不连接 Linear/客户系统，也不执行 production Action。Workbench 有 loading/error/release-disabled 语义，未暴露 Agent approve 或 production Action 控件。

## Issues

### Critical

None found.

### Important

#### I-1 Workspace 资源级授权未实现，已认证的任意 human 可跨 workspace 写入并创建 ready Candidate

- 文件/位置：`src/aifde/shipyard/service.py:316-390`、`src/aifde/shipyard/service.py:443-525`、`src/aifde/shipyard/service.py:688-901`；只读 API 还在 `src/aifde/api/shipyard_routes.py:200-328` 丢弃已解析的 `principal`。
- 证据：`create_decision_case`、`register_artifact`、`decide_proposal` 和 `create_release_candidate` 只调用 `_require_kind(..., "human")`（Artifact 另允许 system），随后按传入 `workspace_id` 读取并写入 workspace；没有检查 `workspace.owner`、workspace membership 或 `workspace-owner`/`release-owner` role。GET routes 认证后直接 `del principal`。
- 可复现探针：在临时 SQLite 中绑定 Alice、Bob 为两个合法 human；Alice 创建 `ws-alice`，Bob 成功创建该 workspace 的 `DecisionCase`。在两个 deterministic passed Gate 已存在时，Bob 进一步成功创建 Candidate，输出为：`cross_workspace_release_candidate=READY`、`workspace_owner=alice`、`candidate_created_by=bob`、`candidate_status=ready`。
- 影响：这不是 blocked→passed 的 evaluator 绕过，后端 Gate eligibility 仍然有效；但它破坏了 workspace owner/角色字段所表达的权限边界，允许一个已认证用户代表另一个 workspace 做业务建模、Proposal 决策和 release-candidate 创建，也能读取其他 workspace 的快照。若 Workbench 后续承载多个客户/项目，这属于跨租户写入风险。
- 修复建议：在 Phase 0 明确二选一并落实其一：
  1. 若当前确实是单租户内部控制面，在设计/acceptance 文档中明确“所有已认证 human 是全局 Workbench operator”，移除/改名会暗示资源授权的 owner roles，并增加共享访问回归测试；或
  2. 增加 Service 级 `authorize_workspace(principal, workspace, action)`，对 create/decision/artifact/proposal decision/release 和所有 read 使用 owner/member/role policy，API 将 principal 传入 read 方法；增加 Alice/Bob 跨 workspace 读写均被拒绝的 API 与 Service 测试。

### Minor

#### M-1（已知 deferred）Bootstrap 不是原子 seed，重复 seed/retry 语义不完整

`src/aifde/shipyard/bootstrap.py:60-137` 逐个调用 Service transaction；第 N 个资产失败时，workspace 和前 N-1 个 Artifact 会保留，确定性的 gate run ID 也使同一数据库重试可能因 duplicate identity 失败。当前没有产生外部副作用或错误放行，但建议后续增加全量 preflight/seed-run 状态或原子 bootstrap transaction。

#### M-2（已知 deferred）Sandbox evaluator 仍可能产生本地文件/mock Action 副作用

`src/aifde/shipyard/evaluator.py:299-318` 调用既有 demo pipeline。当前探针证明没有客户连接和 production Action，但 pipeline 可能写入本地 generated fixture 或执行 mock adapter；建议后续把它隔离到临时 evaluation workspace，并显式提供 dry-run contract。

#### M-3（已知 deferred）Evaluator attestation 有 revision，但 Service 比较字段遗漏 revision

`src/aifde/shipyard/evaluator.py:253-295` 将 `revision` 纳入 attestation，`src/aifde/shipyard/service.py:95-125` 的 `_assert_software_gate_review_matches_evaluator` 却没有把 `revision` 放入 `compared_fields`。这不能把 blocked 改成 passed，因为 status/violations/attestation 仍会失败；但可信 gate-runner 可提交同 outcome 的异常高 revision，影响 latest 选择和审计完整性。后续应将 revision（以及明确的 timestamp policy）纳入重建比较。

#### M-4（已知 deferred）Artifact 语义失败时仍会添加未实际执行的 sandbox evidence

`src/aifde/shipyard/evaluator.py:79-98` 在 semantic/source violation 发生、sandbox 被跳过时仍无条件加入 `pipeline:software-delivery:software-delivery-demo:sandbox:v1`。它不会让 Gate 变成 passed，但 evidence 叙述不完全忠实；应只记录实际执行的 pipeline evidence，并保留 skipped/blocked reason。

#### M-5 Workbench 未展示全部新 provenance/attestation 字段

`workbench/src/types.ts:85-105` 已定义 source/input snapshot、definition fingerprint 和 outcome attestation，但 `workbench/src/App.tsx:646-676` 的 Artifact 卡片只展示 version/owner/producer/content hash/evidence，`workbench/src/App.tsx:730-779` 的 Gate 卡片也未展示 source snapshot hash、input snapshot hash、definition fingerprint、outcome attestation、Artifact versions 或 validation/source metadata。后端仍然正确持久化和校验这些字段，因此不是 release bypass；但人类在 Workbench 中不能完整核对 evaluator provenance。建议补充只读展示和 populated snapshot UI tests。

#### M-6 前端 readiness 判定比后端 release policy 弱，可能先显示可发布再被 API 拒绝

`workbench/src/App.tsx:169-245` 只检查 required gate 的 status、stale 和 Artifact hashes，没有检查当前 Artifact versions、source/input snapshot、validator/fingerprint、evidence 或 outcome attestation；而 `src/aifde/shipyard/service.py:783-858` 会检查这些字段。后端仍 fail closed，但用户可能看到 “All required gates passed” 并点击后得到 409。建议由后端提供 authoritative readiness projection，或让前端复用同一严格 policy；同时统一前后端 required-gate configuration。

## Recommendations

1. 在合并前先解决 I-1：确定 Phase 0 是全局单租户 operator 模式还是 workspace-scoped 模式，并用 Service/API 负例测试把该决定固定下来。
2. 保留当前 evaluator 的“Registry canonical content + fixed source root + deterministic outcome rebuild”结构；后续把 M-3/M-4 的 attestation/evidence 细节修正，避免 provenance 只在安全逻辑正确而在展示层不完整。
3. 将后端 release-readiness 结果作为 Workbench 单一事实来源，补齐 M-5/M-6 的 provenance 展示、空/非法 JSON client error 测试和 release disabled 回归。
4. 后续再处理 M-1/M-2；它们是 seed/评测运行隔离问题，不应通过放宽 Gate 或直接写 Registry 来“修复”。

## Tests / Checks

- `pytest tests/shipyard/test_software_delivery_slice.py tests/e2e/test_shipyard_workbench_flow.py -q`：`19 passed`。
- `pytest tests/shipyard tests/api tests/gates -q`：`127 passed`。
- `npm test -- --run`：`13 passed`。
- `npm run build`：TypeScript 检查和 Vite production build 均成功。
- 受影响 Shipyard/API/evaluator/bootstrap/Registry Python 文件 `py_compile` 成功；`python -m compileall -q src` 成功。
- `scripts/shipyard_seed.py --database <nested temp path> --owner alice`：exit 0，自动创建父目录，注册六个 Artifact 和两个 Gate Review；当前环境结果为 passed，输出明确 `external_connections=[]`、`production_actions_executed=false`。
- 全量 `pytest tests -q`：`423 passed, 14 failed, 13 errors`。失败集中在基线中已存在且本分支未修改的 builder/runtime/platform 路径：production E2E 的 `builder_source_snapshots` 缺表，以及未改动的 `src/aifde/ontology/shapes.py` 在当前环境对 `sh:class`/`sh:datatype` 的既有 SHACL 解析失败；Shipyard/API/Gate/Workbench 定向测试没有对应回归。
- `git diff --check 382ed31..e50e83d` 只报告已有 `task-6-rereview2.md` 的文档 trailing whitespace；本报告不引入该问题。
- 受控权限探针如 I-1 所述；现有 evaluator source-mapping、semantic-content、blocked-attestation、旧 GateReview 和 deterministic Candidate 测试均通过。

## Assessment

**Ready to merge: With fixes**

Phase 0 的核心 Shipyard vertical slice、evaluator 防伪门禁、append-only persistence、Workbench review flow 和声明的外部边界已经达到可审查质量；没有发现 Critical，也没有发现能把 blocked outcome 直接伪装成 passed 的新路径。但在 owner/role 语义未明确且 Service/API 未执行 workspace 资源级授权前，不建议将该分支作为可供多个项目/客户使用的最终 Workbench 合并。解决 I-1 或以文档与回归测试明确“单租户全局 operator”后，可重新评估为 Ready。
