# S7：人工审核与发布阶段设计

## 1. 阶段定位

S7 把前面生成的候选、映射、数据产品和约束汇总为可审批的 release candidate。它是人类业务责任、独立验证和 Gate Engine 的汇合点；AI-FDE 不得自批准或自发布。

## 2. 目标与范围

形成完整的 Ontology Diff、Mapping Diff、Shape Diff、Data Quality Report、Provenance Coverage Report、Security Review、GateRun 汇总、Approval 和 rollback manifest，发布新版本或阻断。

## 3. 输入与输出

输入：S2–S6 的候选和报告、上一发布版本、变更影响分析、审批人身份、发布策略和回滚目标。

输出：包含 release id、ontology/data/mapping/shape artifact hashes、data product refs、gate run ids、approval ids、dependency versions、rollback target 和 released_at 的 `OntologyReleasePackage`。

## 4. 审核流程

1. `DRAFT → VALIDATING`：确定性验证输入 hash 和版本。
2. `VALIDATING → CHALLENGING`：独立 Challenger 检查反例、未来泄漏、权限和悬空关系。
3. `CHALLENGING → DOMAIN_REVIEW`：提交领域 owner 审核对象、定义、状态、异常和动作语义。
4. `DOMAIN_REVIEW → APPROVED`：所有必需 gate 当前且通过。
5. `APPROVED → RELEASE_CANDIDATE`：Release Owner 检查依赖、回滚和权限。
6. `RELEASE_CANDIDATE → RELEASED`：只有非 Builder 的授权 actor 执行发布。

## 5. 硬门禁

`reality.consistency`、`evidence.coverage`、`semantic.integrity`、`data.quality`、`executable.readiness`、`adversarial.challenge`、`release.governance` 必须通过；软门禁只能由有 owner、原因、补救措施和过期时间的 waiver 处理。高影响实体 unresolved、缺失证据、未来时间泄漏、权限无法传播不可 waiver。

## 6. 回滚与失效

发布包必须保存 artifact hashes、GateRun、Approval、依赖版本和 rollback target。回滚是追加新版本，不删除历史；底层 artifact 或 gate definition 变化时重新使旧结果 stale，并阻断继续发布。

## 7. 验收标准

- Builder actor 无法批准或发布自己的 StageRun。
- 缺任一硬门禁、证据覆盖、SHACL、数据产品或审批时，发布被阻断。
- 发布包可验证当前 artifact hash、GateRun fingerprint 和 approval。
- 回滚生成新版本并保留审计轨迹。
- 发布后的 Ontology、数据产品和 provenance 能被下游 Agent 只读消费。

## 8. 下游接口

P1 从 `OntologyReleasePackage`、发布的 DataProductVersion、Evidence Index、Access Policy 读取事实；任何领域 Agent 不得绕过 S7 直接读取未登记候选或改变发布状态。
