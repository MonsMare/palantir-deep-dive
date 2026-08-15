# Task 3 Report: Identity and Shipyard Application Service

## 红灯

```text
$ pytest tests/shipyard/test_service.py -q
ERROR collecting tests/shipyard/test_service.py
ModuleNotFoundError: No module named 'aifde.shipyard.identity'
1 error
```

## 绿灯

```text
$ pytest tests/shipyard/test_service.py -q
...............                                                          [100%]
15 passed in 2.44s
```

## 聚焦与回归

```text
$ pytest tests/shipyard/test_service.py tests/shipyard/test_contracts.py tests/shipyard/test_store.py tests/task tests/gates tests/api/test_sqlite_registry_routes.py -q
........................................................................ [ 64%]
........................................                                 [100%]
112 passed in 4.44s
```

```text
$ pytest tests/api -q
.......................                                                  [100%]
23 passed in 1.89s
```

全仓回归：

```text
$ pytest -q --tb=no
385 passed, 14 failed, 13 errors in 33.28s
```

基线全量结果为 `370 passed, 14 failed, 13 errors`。新增 Task 3 测试带来的 15 个通过测试已计入当前结果；失败/错误数量和既有失败集合未增加。

## 实现与自审

- `Principal` 只接受非空 subject、`human`/`agent`/`system` 三种 kind 和显式 roles；`FakeIdentityProvider` 只查显式绑定，不按 subject 前缀推断权限，也不采信 request context 中的 actor/kind/roles。
- Service 是新增状态写入入口：每个写操作都通过 `registry.transaction()`，状态记录和 `AuditEvent` 在同一事务中追加；审计构造失败会连同状态一起回滚。
- human 负责 workspace、decision case、Proposal 决策和 Release Candidate；agent 只能提交 `AgentProposal`；system 只能记录 Gate Review。Proposal 的 producer 始终绑定到 Principal，不采信输入中的 actor/authority。
- Agent Proposal 提交不推进 workspace revision；接受/拒绝/退回均追加同一 proposal 的新 revision。base revision 过期时追加 `status="stale"` revision 和审计事件后提交，再抛出 `StaleRevisionError`。
- Release eligibility 校验 requested Artifact 的 workspace/project 归属和 registry 返回的最新版本；校验 requested Gate Review 的 workspace、同 gate 的 current/latest、`passed`、`stale is False`、当前 Artifact hash 和 required gate 覆盖。manifest 对 Artifact ID、Gate Review ID 和 Artifact hash 做确定性排序。
- 没有修改 Task 4 API、bootstrap 或主工作区；Task 1/Task 2 合同与 SQLite 代码保持未修改。

## 提交

- 实现与测试提交：`9c42505` (`feat: add governed Shipyard application service`)

## 遗留疑问 / concerns

- 全仓仍有既有 builder/SHACL 相关 14 failures，以及 builder SQLite 初始化相关 13 errors；这些在 Task 3 之前的基线中已存在，本次未触碰相关代码。
- 本任务未扩展 API，后续 Task 4 仍需把认证上下文解析和 Service 错误映射接入 HTTP 边界。

## Fix round 1

本轮只处理 reviewer 标记的两个 Important；M-1 空 Gate 错误文字和 M-2 Gate revision/created_at 分配顺序按要求延后。

### 红灯

先新增未绑定/mismatched Principal、显式 provider 必填和稳定 manifest digest 测试：

```text
$ pytest tests/shipyard/test_service.py -q
.FF............F.                                                        [100%]
3 failed, 14 passed
```

失败分别证明：Service 仍默认创建 FakeIdentityProvider、未绑定/roles 不匹配 Principal 仍可写入，以及 manifest 尚无 `manifest_digest`。

### 绿灯

修复后：

```text
$ pytest tests/shipyard/test_service.py -q
.................                                                        [100%]
17 passed in 3.13s
```

### Fix round 1 回归

```text
$ pytest tests/shipyard/test_service.py tests/task tests/gates -q
........................................................................ [ 74%]
.........................                                                [100%]
97 passed in 3.26s
```

```text
$ pytest tests/shipyard/test_contracts.py tests/shipyard/test_store.py tests/api/test_sqlite_registry_routes.py -q
.................                                                        [100%]
17 passed in 2.04s
```

```text
$ pytest tests/api -q
.......................                                                  [100%]
23 passed in 2.24s
```

### Fix round 1 自审

- I-1：`ShipyardApplicationService` 现在拒绝 `identity_provider=None`，也拒绝没有 `verify(principal)` 能力的 provider；`IdentityProvider.verify` 返回 canonical Principal，`FakeIdentityProvider.verify` 按 subject、kind、roles 与显式 binding 精确匹配。所有 Service kind 检查都先经过实例 provider 验证，因此未绑定、kind 不匹配或 roles 不匹配的 Principal 不能写入。
- I-2：Service 对排序后的 `artifact_hashes` 和 `gate_run_ids` 组成 canonical JSON，计算并保存 `manifest["manifest_digest"]`；调用者不能提供或覆盖该值。既有 `manifest["artifact_hashes"]` 映射保留，Registry 会随完整 ReleaseCandidate payload 持久化 digest。
- 新测试创建两个不同 candidate ID/content hash、输入顺序不同的候选，确认 `manifest_digest` 相同且等于 canonical SHA-256；Task 1 合同、Task 2 Registry、SQLite schema 与 API 均未修改。
- 未实现 Task 4，未处理 reviewer 指定的两个 Minor。

### Fix round 1 提交

- 实现与测试提交：`3970719` (`fix: enforce Shipyard identity and manifest digest`)
