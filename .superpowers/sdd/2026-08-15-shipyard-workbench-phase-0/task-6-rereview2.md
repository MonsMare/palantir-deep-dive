# Task 6 Fix Round 2 Scoped Re-review

审查基线：`2761b52`  
最终 HEAD：`9099f5b`  
上一份 scoped review：`c6c33c6` / `task-6-rereview.md`  
审查范围：`review-fix2-2761b52..9099f5b.diff`

本轮只复核原 I-1/I-2 及其直接回归；没有修改实现代码，没有扩大到已明确 deferred 的 M-1 seed 原子性和 M-2 sandbox 副作用。

## Summary

本轮实现已实质关闭原 I-1/I-2：六个软件交付 Artifact 由 evaluator-owned 的固定 ID→source path/kind/format 映射驱动，evaluator 读取当前 Registry Artifact 的 canonical content 和固定 source asset，执行 YAML/Turtle 解析、内容/hash 一致性及结构语义检查；缺失、额外、错配、内容不一致或未参与完整评测时，Gate 结果保持 blocked/stale。sandbox 只在 Artifact 评测无违规后作为补充检查，缺失可验证 stage state 时 fail closed。

Gate Review 的 `outcome_attestation` 对 canonical evaluator outcome 做 SHA-256，包含 gate/run/status/stale/violations、Artifact/input/source hashes、versions、validator、definition fingerprint、evidence 和 stage states。`record_gate_review` 与 `create_release_candidate` 都会重新读取当前 Artifact、固定 source root 并重建 evaluator outcome；旧 GateReview 形状仍能兼容写入历史记录，但不能获得软件交付 Candidate 的 ready 资格。

## I-1 disposition

**Closed。**

- `src/aifde/shipyard/provenance.py:35-91` 集中定义六个 Artifact 的权威映射；`build_artifact_input_snapshot` 不再以 Artifact 自报的 `metadata.source_path` 或 `content.source_ref` 选择评测输入，只把它们作为必须匹配的声明进行校验。
- `src/aifde/shipyard/evaluator.py:108-188` 要求完整的六类 Artifact 集合，逐个读取注册 canonical content 和固定 source asset；生成 semantic result、digest 和 evidence reference，并把结果/违规传入 Gate snapshot。
- `src/aifde/shipyard/evaluator.py:66-105` 只有在 Artifact 评测无违规时才调用 sandbox；Artifact 违规或 sandbox 无 stage state 都不会生成可通过的结果。
- 受控检查确认合法的其他资产不能重指向 `ontology-model`；无效 Turtle、source root 切换、缺失 Artifact 和额外/未参与 Artifact 都产生 blocked/stale。六个 Artifact 的 evaluator evidence 均出现在合法 snapshot 中。
- 原始 deterministic passing snapshot 可正常被 system gate-runner 记录并生成 ready Candidate；因此修复没有把 fail-closed 改成永远阻断。

## I-2 disposition

**Closed。**

- `src/aifde/shipyard/evaluator.py:253-297` 的 attestation payload 覆盖 gate_run_id、状态、stale、violations、输入/来源快照、Artifact hashes/versions、validator、definition fingerprint、evidence 和 stage states。
- `src/aifde/shipyard/service.py:95-127` 对完整 provenance review 逐字段比对 evaluator 生成的 outcome；`record_gate_review` 在写入前重建 outcome，`create_release_candidate` 在发布资格判定前再次重建并验证。
- 在 sandbox stage state 为空的 blocked evaluator 探针中，分别修改 `status=passed`、清空 `violations`、改 `stale=False`、伪造 `gate_run_id` 或替换 `outcome_attestation`，均被 `record_gate_review` 以 attestation mismatch 拒绝；无法通过清空违规把 blocked 变成 passed。
- 旧 GateReview shape 可以作为兼容历史记录写入，但在软件交付 Candidate 路径会因缺失当前 provenance/evaluator attestation 被阻断；受控旧形状探针得到 `outcome attestation does not match the governed evaluator`，没有 ready Candidate。
- API request model 和 Workbench 类型已同步新增字段；Task 1–5 相关 Shipyard/API/Gate 回归未见失败。

## New findings

### Important

None。原 I-1/I-2 没有残留的 release-bypass 阻塞问题。

### Minor

- **M-3：严格 evaluator 比对遗漏 `revision` 字段。** `build_gate_outcome_attestation` 将 `revision` 纳入 payload，但 `src/aifde/shipyard/service.py:106-122` 的 `compared_fields` 没有直接比较 `revision`。受控探针对合法 passing snapshot 执行 `model_copy(update={"revision": 999})` 后，仍可被记录并生成 `ready` Candidate（输出：`revision-tamper-candidate ready revision 999`）。这不会把 blocked outcome 变成 passed，但会污染 Gate 的 append-only revision/latest 排序，并可能用伪造的高 revision 造成后续 Gate 选择阻断。建议后续将 revision 纳入 strict comparison，或由 Service 统一分配而非接受调用方值。
- **M-4：blocked Artifact evaluation 的 evidence list 包含未实际执行的 sandbox 标识。** `src/aifde/shipyard/evaluator.py:91-98` 无条件加入 `pipeline:software-delivery:software-delivery-demo:sandbox:v1`；当 Artifact 违规导致 sandbox 被跳过时，`stage_states` 为空但 evidence 仍声称 sandbox pipeline。它不会放行 Candidate，但会降低审计证据的事实准确性。建议仅在 `run_sandbox_pipeline` 实际返回后加入该 execution evidence，或区分 pipeline definition 与 execution evidence。

上述两项均不构成本轮 I-1/I-2 的 release-bypass blocker；M-1、M-2 按本轮范围继续 deferred。

## Tests

- `pytest tests/shipyard/test_software_delivery_slice.py tests/e2e/test_shipyard_workbench_flow.py -q`：`19 passed in 76.19s`。
- `pytest tests/shipyard tests/api tests/gates -q`：`119 passed`。
- `pytest tests/shipyard tests/api tests/gates tests/e2e -q`：`120 passed, 2 failed`；失败仍为与本任务无关的既有 `builder_source_snapshots` 表缺失：`test_supplier_delay_completes_production_chain`、`test_software_delivery_completes_same_chain_without_supplier_keys`。
- 定向 `python -m py_compile`（evaluator/provenance/contracts/service/bootstrap/API 及相关测试）：通过。
- `git diff --check 2761b52..9099f5b`：通过。
- Workbench 前端参考本轮修复验证：`npm test -- --run` 为 `13 passed`，`npm run build`（含 `tsc --noEmit`）通过。
- CLI nested database 探针：父目录自动创建，命令 exit 0，只写本地 SQLite；输出 `external_connections=[]`、`production_actions_executed=false`，当前直接 Python 环境缺少可选 pipeline 依赖时 Gate 安全保持 blocked/stale。
- 受控探针：旧 GateReview shape 被 release 阻断；revision 篡改与 producer 篡改分别验证了上述 Minor 边界，但 producer 篡改不改变本轮语义 evaluator 的 release 结论，未列为本轮 blocker。

## Verdict

**Approved**

原 I-1/I-2 已关闭，确定性 passing snapshot 可正常进入 Candidate，blocked/旧形状/错输入不能取得 ready 资格。M-3/M-4 是不影响本轮验收的后续完整性修复项。
