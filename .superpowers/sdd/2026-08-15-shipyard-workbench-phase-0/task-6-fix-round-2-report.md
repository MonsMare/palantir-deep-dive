# Task 6 Fix Round 2 实现与验证报告

日期：2026-08-15

本轮以 `2761b52` 作为实现基线，`c6c33c6` rereview 仅作为只读审查报告；未修改 progress ledger。实现目标是关闭 rereview 的 I-1/I-2，不把 AI-FDE 误做成客户生产运行时。

## 结论

I-1 和 I-2 已关闭。软件交付 slice 现在由受治理的 deterministic evaluator 产生 Gate Review：

- 六个固定 Artifact ID 分别绑定固定的 source asset、Artifact kind 和格式；Artifact 自己声明的 `metadata.source_path`、`content.source_ref` 只能被验证，不能改变 evaluator 的输入选择；
- evaluator 从 Registry 读取六个已注册 Artifact 的 canonical content，并读取固定 source asset，执行来源 SHA、content hash、文档解析和类型/结构语义校验；六个 Artifact 缺失、额外、错配、内容不一致、语义错误或未参与评测都会产生 blocked/stale；
- 每个 Artifact 生成 deterministic input digest 和 semantic-result evidence，Gate Review 同时携带 input/source snapshot、Artifact hashes/versions、validator/definition fingerprint、violations、stage states 和 outcome attestation；sandbox pipeline 只是通过 Artifact evaluator 后的补充检查；
- Application Service 在 `record_gate_review` 和 `create_release_candidate` 中重建同一 evaluator outcome，逐字段校验 outcome attestation。修改 status、violations、stale、gate_run_id、输入/来源 hash、evidence 或 validator/fingerprint 的完整 provenance review 不能被记录或取得 release eligibility；
- 没有可验证 sandbox stage state 时 fail closed，不会把 blocked evaluator outcome 复制为 passed；CLI 在此环境下安全生成 blocked/stale Gate Review，不创建 Candidate。

## 主要实现

### 1. Artifact source mapping 与 evaluator

新增 `src/aifde/shipyard/evaluator.py`，并将软件交付六类资产的权威映射集中到 `src/aifde/shipyard/provenance.py`：

| Artifact | 固定 source asset | kind | format |
| --- | --- | --- | --- |
| `project-charter` | `config/project.yaml` | `ProjectCharter` | YAML |
| `decision-contract` | `decisions/problem.yaml` | `DecisionContract` | YAML |
| `ontology-model` | `ontology/domain.ttl` | `OntologyModel` | Turtle |
| `data-product` | `data_products/contracts.yaml` | `DataProduct` | YAML |
| `feature-catalog` | `features/definitions.yaml` | `FeatureCatalog` | YAML |
| `model-policy` | `models/model_policy.yaml` | `ModelPolicy` | YAML |

Ontology source 会用 RDFLib 做 Turtle 语法解析；YAML 会被解析为 mapping/list 并检查各类 required structure，feature catalog 还检查每个 feature 的时间、延迟、缺失、版本、血缘和泄漏字段。语义结果和 digest 都进入 Gate evidence，错误进入 Gate violations。

### 2. Governed outcome attestation

`GateReviewSnapshot.outcome_attestation` 是对以下 canonical payload 的 SHA-256：

`gate_id + gate_run_id + revision + status + stale + violations + Artifact/input/source hashes + validator_version + definition_fingerprint + evidence_refs + stage_states`

旧 GateReview shape 仍可通过兼容 API 写入，但没有完整 provenance 和 evaluator attestation 时不获得软件交付 Candidate eligibility。所有状态写入仍经过 `ShipyardApplicationService`，身份约束和 gate-runner role 保持不变。

### 3. 回归测试

`tests/shipyard/test_software_delivery_slice.py` 新增/更新覆盖：

- 合法的另一项目资产不能重指向 `ontology-model`；
- Ontology semantic content 错误会得到 blocked/stale；
- 六个 Artifact 都必须有 evaluator evidence；
- blocked snapshot 改写 status、violations、stale、gate_run_id 或 outcome attestation 会被拒绝；
- 原始 deterministic passing snapshot 可以记录并创建 Candidate；
- 原有 run-id 绑定测试改为验证 Service 在记录阶段拒绝篡改。

## 验证结果

以下命令均在本 worktree 运行：

| 命令 | 结果 |
| --- | --- |
| `pytest tests/shipyard/test_software_delivery_slice.py tests/e2e/test_shipyard_workbench_flow.py -q` | 18 passed（主修复提交后） |
| 针对最终语义补丁运行 8 项关键 slice/回归测试 | 8 passed |
| `pytest tests/shipyard tests/api tests/gates -q` | 127 passed |
| `pytest tests/shipyard tests/api tests/gates tests/e2e -q` | 128 passed, 2 failed；失败为下述基线问题 |
| `npm test -- --run` | 13 passed |
| `npm run build` | `tsc --noEmit` 和 Vite build 均通过 |
| `python scripts/shipyard_seed.py --database .tmp\\fix-round2-cli-test\\nested\\shipyard.db --owner alice` | exit 0；父目录自动创建；六 Artifact、两 Gate Review；当前环境结果为 blocked/stale；无 external connections、无 production actions |
| changed-file `python -m py_compile ...` | 通过 |
| `git diff --check` | 通过 |

最终指定集合的 2 个失败是起始分支已知且与本任务无关的失败：

- `tests/e2e/test_production_two_domain_flow.py::test_supplier_delay_completes_production_chain`
- `tests/e2e/test_production_two_domain_flow.py::test_software_delivery_completes_same_chain_without_supplier_keys`

两者均在旧的 `EvidenceDrivenOntologyBuilder` persistence 路径报 `sqlite3.OperationalError: no such table: builder_source_snapshots`。本轮未复制或修复该 unrelated builder persistence 变化。一次全量 `python -m compileall -q src tests` 还命中未修改的 `src/aifde/ontology/shapes.py:97` 既有 f-string syntax error；本轮变更文件的定向 `py_compile` 已通过。

## Commits

- 实现主提交：`9e37004` — `fix: govern software delivery artifact evaluation`
- 实现补丁提交：`13d782d` — `fix: attest artifact semantic outcomes`
- 本报告提交：在本文件完成后单独提交。

## Deferred minor

- M-1：seed 的跨步骤写入尚未改为单事务；保持当前 Service-only 写入边界，后续可增加 bootstrap workflow transaction。
- M-2：sandbox pipeline 仍可能生成本地 fixture/mock action 副作用；它只作为 Shipyard sandbox 补充检查，未连接客户系统、Linear 或生产 Action。文档没有将其描述为生产评测或客户运行时。

## 范围自检

本轮只修改 Task 6 evaluator/provenance/service/contracts/API 类型、Workbench slice 测试、Phase 0 文档和本任务计划/报告；没有修改 progress ledger，没有执行客户系统调用，没有执行生产 Action，也没有使用其他模型或子智能体。
