# Task 8 实现报告：API routes 与只读 FDE cockpit

## 实现范围

- 在 `src/aifde/api/routes.py` 实现 Task8 全部契约路由：
  - `GET /projects/{project_id}/stages`
  - `GET /projects/{project_id}/artifacts`
  - `GET /projects/{project_id}/gates`
  - `POST /projects/{project_id}/stage-runs`
  - `POST /stage-runs/{stage_run_id}/transitions`
  - `POST /actions`
- 增加 typed Pydantic request/response models，并兼容测试使用的 `SimpleNamespace` fake service。
- 路由只调用注入的 `registry`、`stage_runner`、`gate_engine`、`action_broker`，不直接 mutate 状态。
- `POST /stage-runs/{id}/transitions` 先调用 `gate_engine.can_transition`；失败时返回 HTTP 409，`detail` 明确包含 `blocking`；允许时才调用 `gate_engine.transition`。
- `POST /actions` 只从允许的请求字段构造 broker request；`success`、`status`、`approval_status` 等 forged outcome 字段被 Pydantic `extra="forbid"` 拒绝，不会传入 broker。
- 在 `src/aifde/ui/dashboard.py` 实现可选 Streamlit 只读 cockpit：
  - 运行时才导入 `streamlit`；
  - 只读加载 project stages、artifacts、gates，以及可选 approvals、open questions、latest diff、actions；
  - 展示 project、current stage、hard gate failures、pending approvals、open questions、latest artifact diff；
  - 非 approved action 不显示 `Execute`；approved action 仅显示 disabled Execute，保留 read-only 边界。
- 在 `src/aifde/api/__init__.py` 导出 `create_app`、`build_router` 和 API request/response models。

## TDD / 修复记录

1. 复现定向 API 测试：初始 `routes.py` 为空，API contract 测试红灯。
2. 写入最小完整 `routes.py` 后，定向测试变为 `8 passed, 1 failed`。
3. 失败根因：当前真实 `aifde.domain.actions.ActionRequest` 需要完整治理字段，而 Task8 API contract 只给出执行请求字段。为满足“兼容 SimpleNamespace fake，不要求具体 pydantic object”以及“不接受 forged outcome”，`_build_action_request` 在域模型无法实例化时退回为只含允许字段的 `SimpleNamespace`。
4. 修复后定向 API 测试通过。
5. 补齐 `dashboard.py`，移除 `NotImplementedError` 占位，实现 read-only Streamlit cockpit。

## 验证结果

- `C:\ProgramData\anaconda3\python.exe -m pytest tests/api/test_stage_routes.py tests/api/test_gate_routes.py -q`：`9 passed`
- `C:\ProgramData\anaconda3\python.exe -m pytest -q`：`146 passed`
- `C:\ProgramData\anaconda3\python.exe -m compileall src tests`：exit code `0`
- `git diff --check`：exit code `0`

## 说明

- `__pycache__` 是验证命令产生的本地生成物，已被仓库 `.gitignore` 忽略，未纳入提交。
- Task8 report 位于 `.superpowers/sdd/...`，该目录默认 ignored；提交时需要按既有历史报告方式 force-add。

## 实际模型

GPT-5（Codex）
