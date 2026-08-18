# Task 6 Fix Round 1 Scoped Re-review

审查基线：`e493f43`
最终 HEAD：`2761b52`
原审查报告：`adfa11e` / `task-6-review.md`
审查包：`review-fix1-e493f43..2761b52.diff`

本次只复核原 I-1/I-2、修复差异及其直接回归；没有修改实现代码，也没有扩大到已明确 deferred 的 M-1 seed 原子性和 M-2 sandbox 副作用。

## Summary

修复确实补上了大量 provenance 防线：固定 evaluator source root、Artifact content hash/version、source SHA、source snapshot/input snapshot、definition fingerprint、evidence 引用和 required six Artifact 集合现在会在 snapshot/record/release 多个边界被重新计算或校验；system Gate Review 还新增了 `gate-runner` role。旧 Gate Review 形状也不能直接获得 release eligibility。

但本轮仍不能宣称 I-1/I-2 完全关闭：

1. 六类 Artifact 的源文件一致性被 hash/preflight 绑定了，但 sandbox evaluator 仍主要运行 synthetic pipeline，未以六个 Artifact 的语义内容作为实际 Gate 计算输入；且 provenance 信任 Artifact 自己声明的 `source_path`，没有固定每个 Artifact ID 到预期资产路径/类型的映射。
2. blocked evaluator 的 Gate Review 仍可被 system gate-runner 通过 `model_copy` 改成 `passed` 并清空 `violations`，因为 Service 校验的是当前声明和确定性 input/gate-run ID，没有校验一个不可伪造的 evaluator outcome/attestation。受控探针已经使该路径生成 `ready` Candidate。

## I-1 disposition

**Partially addressed — not closed。**

### 已确认修复有效的部分

- `src/aifde/shipyard/provenance.py:56-145` 会对当前 Artifact 记录版本、content hash、source path、source SHA、evidence，并生成 `source_snapshot_id/hash` 与 `input_snapshot_hash`。
- `src/aifde/shipyard/bootstrap.py:181-212` 始终使用 evaluator-owned 的 `_asset_root()`；调用方传入不同 `project_root` 会产生 blocked/stale，而不会切换 pipeline root。缺少部分 Artifact 时也会生成 blocked/stale；全部输入缺失时 fail closed 抛出 `RecordNotFoundError`。
- `src/aifde/shipyard/provenance.py:92-145` 对固定 root 下的文件执行 source SHA 和 envelope content hash 一致性检查；`src/aifde/shipyard/service.py:530-560`、`:658-673` 在记录 Gate 和创建 Candidate 时都会重新计算当前输入。
- `tests/shipyard/test_software_delivery_slice.py` 新增并通过了 source mismatch、missing Artifact、source-root switch 和 run ID 绑定测试；错 hash、错版本、过期 source/input snapshot 无法 ready。

### 尚未关闭的残余问题

#### 1. provenance 绑定了文件，却没有让 Gate 语义计算消费六个 Artifact

`run_workbench_gate_snapshot()` 在 preflight 后只调用 `_run_sandbox_pipeline(str(source_root))`。`src/software_delivery_demo/pipeline.py:115-128` 仍从 `project.yaml` 生成 synthetic bundle，并用 `project_objects_to_graph(bundle)` 验证生成图；它没有从已注册的 `OntologyModel` Artifact 编译 Ontology，也没有把 `data_products/contracts.yaml`、`model_policy.yaml` 等 Artifact 内容作为 Gate evaluator 输入。部分 feature/decision 读取还使用当前工作目录的默认路径。

因此当前 input snapshot 能证明“注册的 Artifact 与其声明的 source 文件一致”，但不能证明“本次 semantic/release Gate 计算使用了这些 Artifact 的内容”。一个语义上错误但 hash 与自身 source envelope 一致的 `domain.ttl` 仍可能被 preflight 接受，随后由 synthetic pipeline 得到通过结果。

#### 2. Artifact ID 到预期资产的映射仍可被声明 metadata 改写

`SOFTWARE_DELIVERY_ARTIFACT_IDS` 只约束六个 ID；`build_artifact_input_snapshot()` 使用每个 Artifact 自己的 `metadata["source_path"]` 和 `content["source_ref"]` 作为校验目标，没有验证：

```text
artifact:...:ontology-model -> ontology/domain.ttl
artifact:...:data-product -> data_products/contracts.yaml
...
```

我用受控 deterministic passing evaluator 做了探针：将现有 `ontology-model` 注册为版本 `2.0.0`，但把其 source path/content 改成合法的 `config/project.yaml` envelope；source SHA、input snapshot、evidence、validator/fingerprint 都按当前值生成。当前实现仍记录两个 Gate，并成功生成 `ready` Candidate，输出为：

```text
wrong-source-mapping-ready config/project.yaml ready
```

这说明“固定同一个 source root”已经成立，但“六类 Artifact 必须对应六个预期源资产”尚未成立，属于原 I-1 的 release correctness 残余。

## I-2 disposition

**Partially addressed — not closed。**

### 已确认修复有效的部分

- `src/aifde/shipyard/service.py:485-502` 现在要求经过 `IdentityProvider.verify()` 的 system principal 且具有 `gate-runner` role，并校验 Gate 存在和 severity 与当前定义一致。
- `src/aifde/shipyard/service.py:512-592` 对完整 provenance 的 passed review 校验当前 Artifact hashes/versions、source/input snapshot、validator version、definition fingerprint、非空且绑定当前输入的 evidence、sandbox evidence、stale 和 violations。
- `src/aifde/shipyard/service.py:704-785` 在 Candidate 生成前再次执行上述校验，并验证 required gates、最新 Gate Review、software-delivery 六类 Artifact 集合和确定性 evaluator `gate_run_id`。
- 旧 Task 1–5 Gate Review 形状虽然仍可作为历史/阻断记录写入，但 Candidate 路径无条件要求 provenance 字段、当前 input/source snapshot、evidence、validator/fingerprint，因此旧形状、空 evidence、错误 hash、过期 snapshot、错误 run ID 均不能 ready。API 的新字段是向后兼容的可选解析字段，前端类型同步，`119` 个 Python Shipyard/API/Gate 回归和前端构建均通过。

### 尚未关闭的关键绕过

Service 没有持久化或验证“该 `gate_run_id` 的 evaluator 实际 outcome”。确定性 `gate_run_id` 只绑定 input snapshot，不绑定 outcome。`record_gate_review()` 对 passed review 会拒绝已有 `violations`，但允许 caller 同时修改 `status="passed"`、`stale=False`、`violations=[]`，然后使用同一输入 snapshot/evidence/run ID 记录。

我用受控 evaluator 返回两个 blocked Gate（空 stage states、带 blocked violations），再执行：

```python
review.model_copy(update={
    "status": "passed",
    "stale": False,
    "violations": [],
})
```

两条 review 都被 `record_gate_review()` 接受，随后 `create_release_candidate()` 返回 `ready`，探针输出：

```text
blocked-to-ready ['blocked', 'blocked'] ready
```

这直接违反本轮要求的“pipeline blocked 时 fail-closed，不能改写为 passed”。`tests/shipyard/test_software_delivery_slice.py` 覆盖了 validator、definition fingerprint、空 evidence、stale、source mismatch 和 forged run ID，但没有覆盖“blocked → 清空 violations → passed”的组合；因此当前绿色测试不足以关闭 I-2。

## New findings

### Important

None beyond the residual I-1/I-2 dispositions above。两项残余均属于原审查范围，不另行扩展编号。

### Minor

None。原 M-1、M-2 按要求继续 deferred。

## Tests

在当前 worktree 执行：

- `pytest tests/shipyard/test_software_delivery_slice.py tests/e2e/test_shipyard_workbench_flow.py -q`：`11 passed`。
- `pytest tests/shipyard tests/api tests/gates -q`：`119 passed`。
- `pytest tests/shipyard tests/api tests/gates tests/e2e -q`：`120 passed, 2 failed`；两个失败仍是未修改的既有 `builder_source_snapshots` SQLite 表缺失：
  - `test_supplier_delay_completes_production_chain`
  - `test_software_delivery_completes_same_chain_without_supplier_keys`
- 本轮修改 Python 源码/测试 `py_compile`：通过。
- `git diff --check e493f43..2761b52`：通过。
- `workbench`：`npm test -- --run` 为 `13 passed`；`npm run build`（含 `tsc --noEmit`）通过。
- CLI fresh nested path：exit `0`，创建 6 个 Artifact、2 个 Gate Review 和父目录；当前 CLI Python 缺少 Polars，两个 Gate 为 `blocked`，无外部连接/生产 Action。
- 额外受控探针：blocked review 清空 violations 后可生成 ready；错误 Artifact source mapping 也可生成 ready。两项均为本轮复核新增的行为证据。

## Verdict

**Changes requested**

本轮 provenance、freshness、required gate、system role 和旧形状兼容校验有实质改善，但在修复“Artifact ID 到预期 source asset 的绑定/真实 evaluator 输入”以及“不可将 blocked outcome 改写为 passed”之前，不能批准 Task 6 fix round 1，也不能宣称当前 slice 已具备可信的 release eligibility。
