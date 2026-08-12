# Task 3 修复实现报告：Gate Engine 与阶段状态机

## 范围

- 只修改 Task 3 范围内的 `src/aifde/gates/`、`tests/gates/`，以及本实现报告。
- 未实现后续 Tool / Action / Orchestration，也未修改计划、ledger 或其他任务文件。

## 已关闭的 5 个审查问题

1. Required gate policy
   - `APPROVED` 必须具备七个 approval gates 的 current acceptable 结果。
   - `RELEASE_CANDIDATE` / `RELEASED` 额外要求 `release.governance`。
   - missing、partial、pending waiver、stale、hard failed 都进入 `blocking_gate_ids`，空结果不再放行。

2. 输入快照闭合
   - `ValidationContext.artifact_ids` 必须与 StageRun input + output artifacts 一一覆盖。
   - `ValidationResult.input_hashes` 必须与 context artifacts 一一覆盖且非空。
   - GateRun 记录 artifact hashes、evidence snapshot id/hash、configuration、configuration hash、input snapshot hash。
   - 新增 configuration invalidation；definition / validator version、artifact、evidence 变化都会使旧 GateRun stale。
   - `evidence_snapshot_hash` 为可选字段，用于增强快照绑定，同时保持 brief 中原有 `ValidationContext` 接口兼容。

3. 防御性 copy / 嵌套可变对象隔离
   - definition、stage run、GateRun、waiver、transition 对外返回均经重新验证的深拷贝。
   - 外部对返回对象的 nested dict/list 做 `clear()` / mutation 不会修改内部审计与 invalidation 状态。

4. 身份与 typed state 边界
   - `builder_actor` 必填非空。
   - `actor` 必填非空。
   - `can_transition` / `transition` 运行时拒绝非 `StageState` target。
   - 内部 StageRun state 更新通过 `StageRun.model_validate`，避免未经验证的 `model_copy(update=...)`。

5. 未越界
   - 未添加 Tool Gateway、ActionBroker、orchestration 或持久化 repository 的后续任务实现。

## 测试与验证

- `pytest tests/gates/test_gate_engine.py tests/gates/test_gate_invalidation.py -q`
  - `15 passed in 0.20s`
- `pytest -q`
  - `56 passed in 1.85s`
- `python -m compileall -q src tests`
  - exit 0，无输出
- `git diff --check`
  - exit 0；仅 Git 报告工作区文件未来可能 LF→CRLF 的提示，无 whitespace error

## 风险 / 后续集成边界

- GateRun、waiver、transition 仍为 GateEngine 内存存储；后续 SQLite repository contract 应由对应任务接入，避免越界修改 Task 2。
- `register_stage_run` 现在强制 `builder_actor`，但 `validation_context` 保持可选；如果调用方在注册时不提供 context，则必须在 `register_result` 时提供完整闭合 context。
- Release governance gate 只在 release candidate / released target policy 中强制；实际 validator 执行调度仍属于后续 orchestration 范围。
