# Task 1：Shipyard Workbench 领域合同实现报告

## 实现摘要

- 新增 `aifde.shipyard` 包及六个 Workbench Pydantic 领域合同：`ProjectWorkspace`、`DecisionCase`、`AgentProposal`、`GateReviewSnapshot`、`ReleaseCandidate`、`AuditEvent`。
- Workbench 合同统一使用 `extra="forbid"`、`frozen=True`，并通过重验证式 `model_copy` 保持追加式 revision 记录的边界。
- `AgentProposal.producer_kind` 固定为 `"agent"`，合同不包含人类审批/权限字段；Workspace/Proposal 提供正数 `revision` 与 `base_revision`。
- 增加非空身份、状态 Literal、时区感知时间并归一化为 UTC、SHA-256 引用和审计事件哈希校验。
- `AuditEvent.build(...)` 按事件核心字段、canonical JSON payload 与 `predecessor_hash` 计算 `event_hash`，外部伪造哈希会被拒绝。
- 扩展 `Artifact` 的 `parent_artifact_ids`、`producer`、`created_at`、`validation_results` 默认字段；旧 `Artifact.build` 调用、内容哈希和重验证式 `model_copy` 保持兼容。为兼容现有 SQLite 旧字段读写，`created_at` 的遗留默认值为 `None`；显式时间仍校验并归一化为 UTC。

## 修改文件

- `src/aifde/shipyard/__init__.py`
- `src/aifde/shipyard/contracts.py`
- `src/aifde/domain/artifacts.py`
- `tests/shipyard/test_contracts.py`
- `tests/unit/test_domain_contracts.py`
- 本报告：`.superpowers/sdd/2026-08-15-shipyard-workbench-phase-0/task-1-report.md`

未修改 Task 2 及之后的持久化、应用服务、API、UI 文件。

## 红灯命令/输出

命令：

```powershell
pytest tests/shipyard/test_contracts.py tests/unit/test_domain_contracts.py -q
```

结果：退出码 `1`；收集阶段按预期失败：

```text
ModuleNotFoundError: No module named 'aifde.shipyard'
1 error in 0.48s
```

## 绿灯命令/输出

命令：

```powershell
pytest tests/shipyard/test_contracts.py tests/unit/test_domain_contracts.py -q
```

结果：

```text
...........................................                              [100%]
43 passed in 0.29s
```

辅助验证：源码 `py_compile` 通过，`git diff --check` 退出码为 `0`。

## 回归命令/输出

命令：

```powershell
pytest tests/unit/test_sqlite_registry.py tests/gates/test_bypass_paths.py tests/api/test_sqlite_registry_routes.py -q
```

结果：

```text
...........                                                              [100%]
11 passed in 2.67s
```

## 自审结果

- `extra="forbid"` 与 `frozen=True` 已由共享 Workbench 合同基类统一设置；`model_copy(update=...)` 会重新走 Pydantic 校验。
- 身份字段拒绝空白值；`producer_kind` 不能声明为 `human`；Agent Proposal 没有审批、授权或人类 actor 字段。
- Workspace/Proposal 的 `revision`、`base_revision` 均要求从 `1` 开始，支持后续 Registry 的追加式历史语义。
- Workbench 时间字段拒绝 naive datetime，并归一化到 UTC；Artifact 的 legacy `created_at=None` 保持旧 SQLite 回归兼容，显式时间仍有相同校验。
- Gate Artifact hash、Audit predecessor/event hash 均要求合法小写 SHA-256；内容哈希仍只从 `Artifact.content` 计算，新增元数据不会改变 hash。
- 已确认旧 `Artifact.build`、`Artifact.model_copy`、内容 hash forged-input 校验和 SQLite 旧数据回归均通过。
- 已按 brief 的 Task 1 文件边界实现；未运行主控已知无关的 Ontology/Builder 全量失败测试。

## 提交 SHA

实现提交：`97e7eeb`（`feat: add Shipyard Workbench domain contracts`）。

## 遗留疑问

- 当前任务按文件边界没有修改 SQLite schema/repository；因此非默认 Artifact 新元数据的持久化扩展仍属于 Task 2，当前实现只保证旧 SQLite 读写与默认字段兼容。
- 除上述明确留给 Task 2 的持久化边界外，无阻塞项。
