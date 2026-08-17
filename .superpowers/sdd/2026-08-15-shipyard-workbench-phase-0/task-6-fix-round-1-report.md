# Task 6 Fix Round 1 修复报告

## 基线与提交

- 审查基线：Task 6 实现 `e493f43`；审查报告 `adfa11e` 仅作为只读输入。
- 实现提交：`43a59b9 fix: bind Shipyard gates to verified artifact provenance`。
- 追加身份修复提交：`13f839e fix: require gate-runner role for Gate Review writes`。
- 本报告单独作为后续文档提交；没有修改 progress ledger。

## 本轮修复结论

审查报告中的 I-1 和 I-2 已修复。现在 software-delivery Gate Snapshot 不再只是把 Registry 的 hash map 附加到独立 pipeline 结果，而是先建立并验证一个由已注册 Artifact 和固定源码资产共同组成的 deterministic input/source snapshot；Release Candidate 生成时由 Application Service 再次计算并验证同一组输入。

### I-1：Artifact/source/evaluator 输入绑定

- 新增 `src/aifde/shipyard/provenance.py`，对每个输入 Artifact 固定记录 Artifact 内容 hash、版本、source path、source SHA、source evidence，并计算 `source_snapshot_id/hash` 和 `input_snapshot_hash`。
- source preflight 会读取 `projects/software-delivery-demo` 中与六类 typed Artifact 对应的实际文件，检查路径不能逃逸、文件存在、注册 source SHA、source reference/evidence、YAML/Turtle 解析内容及 Artifact content hash 是否一致。
- `run_workbench_gate_snapshot` 始终使用 evaluator-owned 的固定 source root。调用方传入另一个 `project_root` 只会形成 blocked/stale 违规，不能切换 pipeline 的实际输入；请求缺少已注册 Artifact 时也会形成 blocked/stale。若全部请求都没有任何已注册 Artifact，则因 `GateReviewSnapshot` 的非空 hash 不变量而 fail closed，抛出明确的 `RecordNotFoundError`，不伪造空输入快照。
- 只有 source preflight 没有违规时才运行 sandbox pipeline；pipeline blocked/unavailable 不会被改写成 passed。Gate evidence 同时包含 Artifact/source/input snapshot 引用和 pipeline runner 引用。
- Service 在 release 前重新读取当前 Artifact 和固定 source root；源文件、内容、版本、hash 或 evidence 发生变化都会阻断 release。

### I-2：Gate freshness、真实性和 release eligibility

- `GateReviewSnapshot` 现在支持 Artifact versions、source snapshot id/hash、input snapshot hash 和 Gate definition fingerprint；API/Workbench 类型同步扩展，旧字段仍可解析。
- Snapshot 从当前 `GateEngine` 读取 validator version、severity 和 definition fingerprint，不再由调用方选择这些值。
- 对完整的新 provenance `passed` review，`record_gate_review` 通过 Application Service 校验当前 Artifact hash/version、source/input snapshot、当前 validator/fingerprint、非空且绑定当前 input 的 evidence、sandbox runner evidence、`stale` 和 `violations`。software-delivery review 必须覆盖六类 seed Artifact。
- 为保持 Task 1–5 的接口兼容，缺省旧形状的 Gate Review 仍可作为历史/阻断审计记录写入；但 `create_release_candidate` 对所有项目都执行严格复核，旧 validator、缺少 definition fingerprint、空 evidence、缺少当前 Artifact versions/source/input hash、过期 source/evidence、stale 或 blocked review 均不能成为 ready Candidate。
- software-delivery release 还要求 required gates 全部覆盖、Gate Review 是最新记录、Artifact 集合正好是六类 seed Artifact，并且 `gate_run_id` 与当前 input snapshot 的确定性 evaluator run 绑定；伪造 gate run id 会被阻断。
- 人类仍是 Candidate 创建者，Gate Review 写入仍要求经过 `IdentityProvider.verify()` 的 system gate-runner；bootstrap/CLI 没有绕过 Registry 直接写入。

## 测试驱动与验证记录

### TDD RED

在本轮实现前先运行了新增缺失 Artifact 测试：

```powershell
pytest tests/shipyard/test_software_delivery_slice.py::test_missing_registered_artifact_produces_blocked_stale_snapshot -q
```

结果为预期的 `1 failed`：旧实现对缺失 Artifact 直接抛出 `RecordNotFoundError`，没有生成部分输入的 blocked/stale snapshot。早先新增 I-1/I-2 回归用例也按预期暴露了缺少 provenance 字段、旧 validator/空 evidence 可放行和 source mismatch 未阻断的问题。

### 最终 Python 验证

```text
pytest tests/shipyard/test_software_delivery_slice.py tests/e2e/test_shipyard_workbench_flow.py -q
11 passed（追加 gate-runner role 修复后的专项组合验证为 12 passed）

pytest tests/shipyard tests/api tests/gates -q
119 passed

pytest tests/shipyard tests/api tests/gates tests/e2e -q
120 passed, 2 failed
```

最后一个命令中的 2 个失败均是起始 clean branch 已存在、且本轮未修改的 builder persistence 问题：

- `tests/e2e/test_production_two_domain_flow.py::test_supplier_delay_completes_production_chain`
- `tests/e2e/test_production_two_domain_flow.py::test_software_delivery_completes_same_chain_without_supplier_keys`

两者都在 `builder_registry.append_source_snapshot()` 处因 SQLite 缺少 `builder_source_snapshots` 表而报 `sqlite3.OperationalError`。这与本 Task 6 provenance/Shipyard 代码无关，按要求未复制或修复。

其他检查：

```text
python -m py_compile <本轮修改的 Python 源码及测试>
passed

git diff --check
passed

cd workbench; npm test -- --run
13 passed

cd workbench; npm run build
passed（tsc --noEmit + Vite production build）

python scripts/shipyard_seed.py --database <fresh nested temp path> --owner alice
exit 0；父目录和本地 SQLite 创建成功；6 Artifacts、2 Gate Reviews；无外部连接、无生产 Action
```

CLI 所用的独立 `python` 环境缺少 Polars，因此真实输出是两个 `blocked` Gate Review；这正是安全阻断行为，不是把缺少评测依赖伪装为通过。focused pytest 环境具备 demo evaluator 依赖，真实 deterministic passing fixture 完成了 candidate E2E。

## Deferred / 未扩大范围

- M-1：seed 的跨步骤原子性/可恢复性仍 deferred；同一数据库重复 seed 仍遵守 append-only 约束并失败，不会覆盖已有记录。
- M-2：demo pipeline 的 `fixtures/generated` 和本地 mock Action 副作用仍 deferred；文档和代码继续明确它是 sandbox/mock，不是客户生产 Action。
- 旧的缺省 GateReview 记录为兼容 Task 1–5 保留可审计写入能力；后续可在持久化 schema 中增加受治理 evaluator run/attestation，把所有 Gate Review 记录入口进一步收敛为不可伪造的 runner 产物。本轮已保证这类旧记录不能获得 release eligibility。
- 本轮没有实现完整 ML Evaluation Lab、生产 connector、Docker 部署、客户 runtime 或 Linear 集成。
