# Task 8 修复轮次实现报告：API 与真实服务集成

## 修复范围

本轮只处理 Task 8 的 API、只读 cockpit 及其必要 orchestration adapter，不引入真实外部 connector，也不修改 Task 4 的 Tool Gateway 或 Task 5 的 ActionBroker 安全边界。

- `POST /actions` 的请求边界改为显式的真实 `ActionRequest` envelope。
  - 删除 `SimpleNamespace` 和裸 `dict` fallback。
  - 缺少治理字段、治理字段非法或额外提交 `success`、`status`、`approval_status`、`outcome_id` 等伪造 outcome/approval 字段时，由 FastAPI/Pydantic 返回 422，且不会调用 broker。
  - 合法请求先通过真实 `ActionRequest` 校验，再交给 `ActionBroker.execute()`；approval、validation、audit、outcome 仍由 broker 及其受保护记录决定，API 不伪造这些事实。
  - broker 的 `PermissionError` 映射为 403，业务 `ValueError` 映射为 409。
- `StageRunner.create_stage_run(project_id, stage_id, actor)` 提供受控 API 适配入口。
  - 校验 project、stage、actor 身份和已知 stage allowlist。
  - 构造包含 `objective`、`allowed_evidence`、`required_output`、acceptance/escalation 条件的 `TaskContract`。
  - 只委托正式 `run(contract)`；不直接创建或写入内部 `StageRun`，状态变化继续经过 GateEngine。
- stage route 在调用适配入口前验证项目存在，并正确映射 unknown、permission、invalid contract；transition route 先走 `can_transition`，hard gate 阻断返回 409。
- dashboard 保持只读：基础 stages/artifacts/gates 请求为必需数据，approvals、open-questions、latest-diff、actions 等可选 API 返回 404 时按空数据处理；approved action 只显示 disabled Execute，非 approved action 隐藏 Execute。

## TDD / 根因复核记录

1. 在现有 API 与 orchestration 测试中先加入真实兼容性回归测试：真实 `ActionRequest`/`ActionBroker` 治理请求、缺治理字段拒绝、伪造字段拒绝，以及真实 `StageRunner` 通过正式 `run(TaskContract)` 的 adapter 测试。
2. 定向测试先红灯：`5 failed, 17 passed`。失败分别复现了真实 `StageRunner` 没有 `create_stage_run`，以及旧 `_build_action_request()` 构造真实模型失败后回退 `SimpleNamespace` 并绕过 broker typed boundary。
3. 生产修复后定向 API/orchestration 测试通过；随后补充 invalid execution mode、approval claim mismatch、无 protected approval 的真实 broker 拒绝和 outcome 不落库测试。
4. 最终定向测试为 `26 passed`，证明 Fake service contract 与真实服务边界同时保持通过。

## 验证结果

以下命令均在当前 worktree、HEAD `2120572` 及本轮报告更新前后按要求复核；最后一次复核结果如下：

```text
C:\ProgramData\anaconda3\python.exe -m pytest tests/api/test_stage_routes.py tests/api/test_gate_routes.py tests/orchestration/test_stage_runner.py -q
26 passed in 0.84s

C:\ProgramData\anaconda3\python.exe -m pytest -q
157 passed in 2.64s

C:\ProgramData\anaconda3\python.exe -m compileall -q src tests
exit code 0

git diff --check
exit code 0
```

## 变更文件

- `src/aifde/api/routes.py`
- `src/aifde/orchestration/runner.py`
- `tests/api/test_gate_routes.py`
- `tests/api/test_stage_routes.py`
- `tests/orchestration/test_stage_runner.py`
- `.superpowers/sdd/2026-08-11-ai-fde-builder-implementation-plan/task-8-implementer-report.md`

## 实际模型

GPT-5（Codex）
