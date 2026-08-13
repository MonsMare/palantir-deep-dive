# Task 8 修复实现报告

## 修复范围

本轮只收敛 Task 8 的 API 与真实编排服务集成缺口，未进入 Task 9 或 sample 项目。

## 根因

1. `/actions` 路由原先在无法构造完整治理型 `ActionRequest` 时回退为 `SimpleNamespace`。这会把请求绕过领域模型的 Pydantic 校验，并把一个不满足真实 `ActionBroker` 类型与治理契约的对象送入执行边界。结果是 fake broker 测试可以通过，但真实 broker 无法安全执行。
2. API 的 stage-run 创建路径依赖 `StageRunner.create_stage_run`，而此前真实 `StageRunner` 只暴露 `run(TaskContract)`，导致路由与真实服务接口不一致。`TaskContract` 和 `StageRun` 也缺少创建者 actor 的追踪字段，无法完整保留审计上下文。

## 修复内容

- `/actions` 使用嵌套且完整的 `ActionRequest` 作为请求边界，移除 `SimpleNamespace` fallback；不完整请求由 API 返回 422。
- API 请求模型继续禁止额外字段，调用方不能伪造 outcome 或 approval 字段；保护记录、审批一致性和实际授权仍由 `ActionBroker` 负责。
- 修正 action outcome 响应对嵌套 request 中 `action_id` 的读取路径。
- 为 `TaskContract` 与 `StageRun` 增加可选 actor 追踪字段，保持既有调用兼容并保留执行主体。
- 补充 API 回归测试，覆盖伪造 approval/outcome 字段、缺失治理字段以及真实 broker 拒绝不一致审批声明的边界。

## 验证证据

以下结果由独立验证轮次确认，本收尾轮次不重复运行测试：

- focused pytest：26 passed
- `compileall`：通过
- `git diff --check`：通过

## 变更文件

- `src/aifde/api/routes.py`
- `src/aifde/domain/stages.py`
- `src/aifde/orchestration/contracts.py`
- `tests/api/test_gate_routes.py`
- 本报告文件
