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

## Fix round 1：review Important findings

### 改动

1. `Artifact.created_at` 改为非空 UTC `default_factory`；`Artifact.build` 即使不传时间也会写入 UTC 时间戳，显式 naive 时间仍被拒绝。对旧 SQLite 行缺失时间字段的兼容策略是让 Pydantic 生成非空 UTC 兼容时间，并通过 `__pydantic_fields_set__` 区分 legacy synthesized time，比较旧记录时不把无法由旧 schema 恢复的时间当作差异；新合同本身不再接受 `None`。
2. `AgentProposal`、`GateReviewSnapshot`、`ReleaseCandidate` 增加派生且可重验证的 `content_hash`；Gate Review 和 Release Candidate 增加 `revision >= 1`。Release Candidate 的 `manifest` 现在必须非空，并且必须包含 `artifact_hashes`、`content_hash` 或 `manifest_hash` 之一，其中 hash 会按 SHA-256 校验；`model_copy` 会丢弃旧派生 hash 后重新计算，序列化后的正确 hash 可再次验证，伪造 hash 会拒绝。
3. `AuditEvent.event_hash` 的 canonical 输入现在包含规范化后的 `event_id`、UTC `created_at`、workspace/event/actor 元数据、payload 和 `predecessor_hash`；篡改 event ID 或时间戳都会造成验证失败。

### Fix round 1 红灯命令/输出

命令：

```powershell
pytest tests/shipyard/test_contracts.py tests/unit/test_domain_contracts.py -q
```

结果：退出码 `1`，新增行为测试按预期暴露 4 个失败、40 个通过：

```text
.....FF......FF.............................                             [100%]
4 failed, 40 passed in 0.55s
```

失败分别对应 Gate `revision` 为额外字段、Audit event ID 未被 hash 覆盖、Artifact 新建时间为 `None`、legacy Artifact 兼容时间为 `None`。

### Fix round 1 绿灯命令/输出

命令：

```powershell
pytest tests/shipyard/test_contracts.py tests/unit/test_domain_contracts.py -q
```

结果：

```text
............................................                             [100%]
44 passed in 0.51s
```

### Fix round 1 回归命令/输出

命令：

```powershell
pytest tests/unit/test_sqlite_registry.py tests/gates/test_bypass_paths.py tests/api/test_sqlite_registry_routes.py -q
```

结果：

```text
...........                                                              [100%]
11 passed in 2.12s
```

辅助验证：`python -m py_compile src/aifde/shipyard/contracts.py src/aifde/shipyard/__init__.py src/aifde/domain/artifacts.py` 退出码 `0`；`git diff --check` 退出码 `0`。

### Fix round 1 自审

- 新建 Artifact 和显式 `Artifact.build` 均得到非空、timezone-aware、UTC 时间；旧 SQLite 缺失字段只走明确的 legacy synthesized-time 兼容路径。
- Proposal/Gate/Release 的 hash 均由合同字段派生，`model_dump` 后可通过 `model_validate` 重验证；Gate/Release revision 受 `ge=1` 约束。
- Release manifest 非空且必须含有合法 hash 引用；已有 `artifact_hashes` 形式保持兼容。
- Audit hash 覆盖 `event_id` 与 `created_at`，payload、前继 hash 和 actor/workspace 元数据仍在 canonical 输入内。
- 只修改了 Task 1 列出的源文件和测试文件，并追加本报告；没有实现 Task 2 Registry/Service。

### Fix round 1 提交 SHA

`8cc524a`（`fix: harden Shipyard Workbench Task 1 contracts`）。

### Fix round 1 遗留疑问

- SQLite schema/repository 仍按 Task 2 边界未修改；本轮只保证旧 SQLite 读入不产生 `None` 且既有 Artifact 回归保持通过。新 hash/revision 字段的持久化列和追加式 Registry 行为仍由 Task 2 实现。
- 本轮无阻塞项。

## Fix round 2：manifest 多 hash 组合校验

### 改动

- `ReleaseCandidate.validate_manifest` 现在先枚举 `artifact_hashes`、`content_hash`、`manifest_hash` 三个保留 hash 字段；缺少全部保留字段仍拒绝，同时出现多个保留字段时明确拒绝，避免 `if/elif` 只校验第一个字段。
- 单一保留字段的既有行为保持不变：`artifact_hashes` 逐项校验 SHA-256，`content_hash` 和 `manifest_hash` 校验 SHA-256；多字段组合统一抛出 `manifest must contain exactly one reserved hash field`。
- 新增组合回归测试，覆盖合法 `artifact_hashes` 与非法 `content_hash` 同时出现的探针场景，并断言该歧义组合被明确拒绝。

### Fix round 2 TDD 红灯命令/输出

命令：

```powershell
pytest tests/shipyard/test_contracts.py tests/unit/test_domain_contracts.py -q
```

结果：退出码 `1`；新增测试按预期暴露旧实现的短路缺口：

```text
......F......................................                            [100%]
1 failed, 44 passed in 0.49s
```

失败为 `test_release_candidate_rejects_ambiguous_manifest_hash_fields` 的 `DID NOT RAISE ValidationError`。

### Fix round 2 绿灯命令/输出

命令：

```powershell
pytest tests/shipyard/test_contracts.py tests/unit/test_domain_contracts.py -q
```

结果：

```text
.............................................                            [100%]
45 passed in 0.37s
```

### Fix round 2 回归命令/输出

命令：

```powershell
pytest tests/unit/test_sqlite_registry.py tests/gates/test_bypass_paths.py tests/api/test_sqlite_registry_routes.py -q
```

结果：

```text
...........                                                              [100%]
11 passed in 2.92s
```

辅助验证：`python -m py_compile src/aifde/shipyard/contracts.py tests/shipyard/test_contracts.py` 退出码 `0`；`git diff --check` 退出码 `0`；暂存区仅包含 `src/aifde/shipyard/contracts.py` 与 `tests/shipyard/test_contracts.py`。

### Fix round 2 自审

- 三个保留 hash 字段在分派到具体 SHA-256 校验前统一计数；组合场景不会再因 `if/elif` 顺序而绕过后续字段，且拒绝消息明确表达“恰好一个”。
- 单一 `artifact_hashes`、`content_hash`、`manifest_hash` 路径仍分别经过原有结构/格式校验；manifest 非空和未知字段约束未放宽。
- 既有 Artifact 非空 UTC 时间、身份/时间校验、内容哈希、Gate/Audit hash、`model_copy` 兼容测试均包含在 45 个聚焦测试中；Task 1 回归 11 个测试全部通过。
- 本轮只修改 Task 1 范围内的合同与测试文件，未实现 Task 2 Registry/Service，也未触碰 SQLite schema/repository。

### Fix round 2 提交 SHA

`a2833d1`（`fix: reject ambiguous manifest hash combinations`）。

### Fix round 2 遗留疑问

- 无本轮阻塞项；SQLite 新字段持久化和追加式 Registry 行为仍按既定范围留给 Task 2。
