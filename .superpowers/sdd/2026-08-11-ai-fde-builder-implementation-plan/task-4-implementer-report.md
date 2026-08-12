# Task 4 修复收尾报告：Capability Policy 与 Tool Gateway

## 实际模型

- 用户偏好：`gpt-5.6-luna + max + priority`
- 本轮实际可用模型：Codex / GPT-5（当前会话没有可调用的 `gpt-5.6-luna` 或 service-tier 切换接口）

## 范围

只修改 Task 4 指定文件：

- `src/aifde/policy/capabilities.py`
- `src/aifde/policy/gateway.py`
- `src/aifde/tools/protocol.py`
- `tests/unit/test_tool_gateway.py`
- `.superpowers/sdd/2026-08-11-ai-fde-builder-implementation-plan/task-4-implementer-report.md`

未修改计划、ledger 或 Task 5+ 文件。

## 已关闭的审查问题

1. 未知/前缀 actor 默认拒绝：移除 actor_id 前缀推断，改为显式 `ActorBinding` / `ActorRole` 可信目录；`builder-unknown`、`release-owner-attacker`、大小写/空白变体均拒绝。
2. Policy snapshot 与更新 API：默认权限与 actor mapping 使用 immutable snapshot；`ToolGateway` 初始化时复制 policy；新增 `with_actor_role()` / `with_actor_capabilities()` 显式更新 API，返回新 policy，不影响已注册 Gateway。
3. Execute 可信边界：新增 `ApprovedActionRecord` 与 `ApprovalVerifier`；Execute 只允许可信 Release Owner 对受保护记录中的 approved + validation passed + mock Action 执行；approval actor 必须是可信 Domain Owner 且不能是 requester。payload 只能做一致性校验，不能自证 approval。
4. Tool 不能绕过 Gateway：注册时安装 Gateway-issued opaque invocation token guard；直接 `Tool.call(context, payload)` 无 token 时拒绝且不写 Gateway audit。
5. Tool 注册严格验证与 snapshot：`tool_id` canonical lookup；`required_capabilities` 必须非空且元素都是 `Capability`；`allowed_stage_ids` 必须非空、非空白、属于已知 stage registry；注册后外部修改 tool metadata/handler 不影响已注册 Gateway。
6. Context 隔离与不可变：`ToolContext` frozen，artifact IDs 为 tuple；Gateway 使用独立 audit snapshot 与 tool snapshot；tool 即使用低层 mutation 改写收到的 context，也不能改写 caller context 或 audit 身份字段。
7. Result defensive copy 与重新验证：`ToolResult` frozen，artifact/evidence/payload 使用递归不可变容器；Gateway 覆盖可信 audit_id，并对 nested payload 做 JSON-compatible 校验；invalid result 会写 `invalid_result` audit。
8. Escalation 防护：`with_capability()` / `model_copy()` 只构造 capability 请求；非 capability 字段 copy 会丢失 trusted binding；assignment 与低层 mutation escalation 均拒绝。
9. 一致拒绝策略：deny、unknown tool、tool exception、invalid result、invalid payload、execute approval denial 均 fail-closed；调用阶段 denial 均有 audit。

## 测试覆盖

`tests/unit/test_tool_gateway.py` 扩展到 44 个 focused tests，覆盖：

- unknown role-shaped actor
- fake approval / fake approver
- missing/unvalidated Action record
- Tool metadata 与 handler mutation
- direct Tool.call bypass
- empty / blank / unknown / case-mismatched stage
- empty / invalid / string capability declaration
- context model_copy / assignment / low-level mutation escalation
- isolated context 与 immutable result
- unknown tool、tool exception、invalid nested result audit
- policy explicit update API snapshot

## 验证结果

本轮新测试使用 TDD 补齐：先观察到 handler snapshot 与 explicit policy update API 测试失败，再实现修复并重跑通过。

- `python -m pytest tests/unit/test_tool_gateway.py -q` → `44 passed`
- `python -m pytest -q` → `109 passed`
- `python -m compileall -q src tests` → exit 0
- `git diff --check` → exit 0

## 风险与边界

- Task 4 只提供受保护的 approved mock Action 执行授权边界，不实现 Task 5 Action Broker、持久化 approval store 或真实外部执行。
- actor / role 目录现在是显式可信映射；接入真实身份系统时应通过 `PolicyEngine` 的显式 binding/update API 构造新 snapshot。
- audit 当前保存在 Gateway 进程内存中；持久化审计存储属于后续任务范围。
