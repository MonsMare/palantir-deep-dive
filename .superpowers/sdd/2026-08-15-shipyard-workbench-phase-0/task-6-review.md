# Task 6 独立审查报告

审查范围：实现 commit `1c7900f`、报告 commit `e493f43`，相对于基线 `1e96a60`；审查包为 `review-1c7900f.diff`。本次只新增本报告，没有修改实现代码。

## Summary

Task 6 已经打通本地 SQLite seed、六类 typed Artifact、Workbench Gate snapshot、Agent Proposal 的人类退回、审计和 Release Candidate 结构；Service-only 写入边界和“不连接外部系统”的 CLI 约束也基本成立。

但当前实现还不能把“Gate 通过”解释为“六个已注册项目 Artifact 已被真实验证”：Gate snapshot 的 `artifact_hashes` 只是附加到独立运行的 sandbox pipeline 结果上，pipeline 没有以这六个 Artifact 的内容/版本作为输入。与此同时，Gate 的 `stale`、`validator_version` 和 evidence 真实性主要由 system caller 提供，Release eligibility 没有重新验证 Gate 定义/验证器新鲜度。当前测试还会把 pipeline 返回的 blocked snapshot 直接复制成 passed，因此在缺少 Polars 的环境中仍能生成 ready candidate，掩盖了上述问题。

## Findings

### I-1 — Gate snapshot 没有绑定到六个已注册 Artifact 的真实内容

**Severity：Important；Verdict：Changes requested。**

证据：

- `src/aifde/shipyard/bootstrap.py:156-174` 从 Registry snapshot 读取当前 Artifact hash，随后独立调用 `_run_sandbox_pipeline(pipeline_root)`；没有把 Artifact payload、来源 hash 或版本传给 evaluator，也没有在调用前把 `project_root` 的文件与注册 Artifact 的 `metadata.source_sha256`/content hash 逐一比对。
- `src/software_delivery_demo/pipeline.py:115-128` 的 pipeline 主要从 `config/project.yaml` 生成 synthetic bundle，再用 `project_objects_to_graph(bundle)` 生成 Ontology 并验证；它不是从 `ontology/domain.ttl` Artifact 编译 Ontology。`data_products/contracts.yaml` 和 `models/model_policy.yaml` 也没有作为该 pipeline 的输入契约传入。`features.py`、`decisions.py` 中的部分读取还使用当前进程工作目录的默认路径，而不是注册 Artifact 的内容或 `project_root` 下的快照。
- `src/aifde/shipyard/bootstrap.py:173` 允许传入任意可用目录作为 pipeline root，而 `seed_software_delivery_artifacts()` 使用固定 checkout 的 `_asset_root()` 注册资产；因此可以出现“注册的是 A，评测读取的是 B”的组合。
- `src/aifde/shipyard/bootstrap.py:192` 只把 hash map 写入 `GateReviewSnapshot`，而 `src/aifde/shipyard/service.py:576-583` 的发布检查只能验证 Gate 声明的 hash map 等于当前 Artifact hash，不能证明 Gate 的计算确实使用了这些 Artifact 内容。

影响：

一个损坏、过期或被修改的 `ontology/domain.ttl`、data-product contract、feature definition 或 model policy 仍可能被注册；只要 synthetic pipeline 的其他结果通过，Gate 就会携带这些 Artifact 的 hash 并允许 Candidate。Release manifest 因此只证明“候选引用了这些 hash”，没有证明“这些 hash 对应的内容经过了本次 Gate 验证”。这直接削弱 Phase 0 所宣称的 Artifact/Gate/release eligibility 闭环，也使 evidence 与输入版本不可复现。

建议修复方向：让 evaluator 直接消费 Registry 中的 Artifact 内容，或在运行 pipeline 前对每个 source file 做 source SHA/content hash 一致性检查并将输入 hash 写入验证证据；不一致时必须生成 blocked/stale 结果。`project_root` 也应绑定到同一个 source snapshot/resolver，不能仅凭一个可读目录改变 Gate 的实际输入。

### I-2 — Gate stale/validator/evidence 语义由 caller 自报，且测试把 blocked 结果提升为 passed

**Severity：Important；Verdict：Changes requested。**

证据：

- `src/aifde/shipyard/bootstrap.py:193-198` 对每次 snapshot 固定写入当前 `GateEngine` 的 validator version，但同时无条件写入 `stale=False`；没有依据 Artifact 版本/hash、Gate definition fingerprint、validator version 或 evidence snapshot 计算 stale。
- `src/aifde/shipyard/service.py:459-496` 的 `record_gate_review()` 只要求 system principal，并直接持久化 caller 提供的 `status`、`stale`、`validator_version` 和 `evidence_refs`；没有通过 `GateEngine` 重新验证 Gate 定义、验证器版本、evidence 存在性或结果与 violations 的一致性。
- `src/aifde/shipyard/service.py:561-583` 的 release 校验只检查 latest/current、`status == "passed"`、`stale is False` 和当前 Artifact hash；不检查 validator version 是否仍是当前定义，也不检查 evidence 是否有效。
- 直接探针已复现：以 `semantic.integrity` 为 required gate，提交 `status="passed"`、`validator_version="obsolete-validator-v0"`、空 `evidence_refs`、`stale=False` 的 Gate Review，经绑定 system principal 记录后，`create_release_candidate()` 返回 `status="ready"`。
- `tests/shipyard/test_software_delivery_slice.py:86-97` 和 `tests/e2e/test_shipyard_workbench_flow.py:125-136` 都把 snapshot 复制成 `status="passed"`、`stale=False` 后记录，并没有断言原始 snapshot 的 status 必须是 passed。当前 Python 环境缺少 Polars 时，真实 snapshot 是 blocked，但这两个测试仍然可以生成 ready Candidate。

影响：

Gate 的“通过”在当前边界不是验证事实，而是一个 system caller 可以提交的声明；旧验证器、无证据或无法执行评测的结果可以被标成 passed。尤其是当前环境已经证明 pipeline fallback 会产生 blocked，而测试仍把它变成 passed，导致回归测试不能证明真实 sandbox 通过，也不能保护后续 Gate freshness 改动。

建议修复方向：将 Gate Review 的记录入口收敛为 Gate Engine/受治理 evaluator 的结构化输出，重新验证 required gate、definition/validator fingerprint、Artifact 输入 hash 和 evidence；Artifact 或 Gate policy 变化时自动 stale。Happy-path 测试应使用真实的 deterministic passing evaluator（或明确的、验证过的 gate-runner fixture），同时保留并断言 blocked snapshot 不能被简单改写后放行。

### M-1 — seed 过程不是跨步骤原子操作

`seed_software_delivery_workspace()` 只在创建 Workspace 前检查第一个资产；后续资产由多个独立 Service transaction 顺序注册。若第 3/6 个文件缺失、版本重复或中途异常，数据库会留下 Workspace 和部分 Artifact。CLI 也没有清理或恢复策略；报告已说明同一数据库重复 seed 会因 append-only revision 失败。当前不构成外部 Action 或权限绕过，但建议后续加入 source preflight、单次 bootstrap transaction 或显式 seed run 状态。

### M-2 — sandbox pipeline 具有本地文件和 mock Action 副作用

`software_delivery_demo.pipeline.run_demo_pipeline()` 会写入 `fixtures/generated`，并通过本地 `ActionBroker` 执行 mock `ReplanSprint`。它没有连接客户系统，报告和文档也明确说明不是 production Action，因此不构成本轮 blocker；但 Gate snapshot 接口从调用者视角并非纯评估函数。后续应把生成数据放入隔离的 evaluation workspace，并将 mock Action 明确改为 dry-run/可观测的测试输出。

## Tests/Checks

以下检查均在 `C:\Users\meta\Code\研究中心\palantir-deepdive-gpt\.worktrees\shipyard-workbench-phase-0` 执行：

- `pytest tests/shipyard/test_software_delivery_slice.py tests/e2e/test_shipyard_workbench_flow.py -q`：`3 passed`。
- `pytest tests/shipyard tests/api tests/gates -q`：`110 passed`。
- `pytest tests/e2e -q`：新增 Workbench E2E 通过；另有 `tests/e2e/test_production_two_domain_flow.py` 的 `2 failed`，均为基线分支缺少 `builder_source_snapshots` 表的既有失败。
- `python -m py_compile src/aifde/shipyard/bootstrap.py scripts/shipyard_seed.py tests/shipyard/test_software_delivery_slice.py tests/e2e/test_shipyard_workbench_flow.py`：通过。
- `git diff --check 1e96a60..e493f43`：通过。
- `workbench` 中 `npm test -- --run`：`13 passed`；`npm run build`：Vite production build 通过。
- `python scripts/shipyard_seed.py --database <fresh nested temp path> --owner alice`：exit `0`，创建 6 个 Artifact、2 个 Gate Review 和父目录；当前环境缺少 Polars，两个 Gate 均为 `blocked`，未连接外部系统。
- 静态边界检查显示 `bootstrap.py` 没有直接使用 Registry 写入；CLI 只负责构造本地 `SQLiteRegistry` 并把写入委托给 Service。静态检查也确认 pipeline 的实际输入与六类 Artifact 的内容绑定不完整。
- 额外行为探针确认：旧 `validator_version`、空 evidence、`stale=False` 的 passed Gate Review 当前可以生成 `ready` Candidate。

## Verdict

**Changes requested**

Service-only 写入、显式身份、append-only Registry、本地 seed CLI 和 Workbench/E2E 的结构基础是成立的；但在修复 I-1/I-2 之前，不能把本 Task 6 宣称为“六类项目资产经过真实 Gate 验证后具备 release eligibility”。
