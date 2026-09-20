# 生产级 Ontology Builder 验收标准

本文件把“能生成 RDF”与“可以进入生产计算闭环”区分开。当前仓库的 Builder 只有在下列门禁全部通过时，才会创建 release package。

## 1. 事实和数据产品

- 每个规范化字段都必须有 `FieldValueProvenance`：值、证据片段、源位置、event/observed/available/valid 时间、映射 ID。
- `available_at` 是 as-of 可见性的硬上界。`materialize_as_of(t)` 不得把未来已知事实带入历史快照。
- 行级 `observed_at/available_at` 只能是字段级时间的保守聚合，不能覆盖字段事实。
- canonical product 必须有稳定哈希，订单行使用独立粒度和字段血缘。

## 2. 实体和语义

- 高影响实体只有 `confirmed` 才能进入 released 数据；带冲突的 `probable_match` 和 unresolved 必须阻断或降级为 review-only。
- 领域对象至少应区分描述对象、事件、异常、状态和派生量；供应商延误示例包含 `PurchaseOrderLine`、`PromisedDelivery`、`DeliveryEvent`、`DeliveryException` 和 `delayDays`。
- RDFS 输出必须声明关系的 `domain/range`，日期/数值输出必须带 XSD datatype。
- SHACL 必须覆盖存在性、datatype、class、枚举和必要的 cardinality；pySHACL 不可用时，确定性本地子集仍必须执行这些约束。

## 3. 计算闭环

计算对象不能只是附加 JSON 字段，必须使用 `aifde.ontology.computation` 中的契约：

```text
FeatureDefinition → FeatureSnapshot → PredictionArtifact
                                  → DecisionCandidate
                                  → GovernedActionRequest
                                  → ActionOutcomeLink → FeedbackLink
```

每个环节都必须绑定：

- ontology release ID 和 ontology version；
- data product / feature snapshot；
- as-of 时间和模型/特征定义版本；
- 证据与数据血缘；
- 决策到预测、动作到决策、反馈到动作的引用关系。

动作先通过 `ComputationChainValidator`，再进入已有的 Action Broker、审批和幂等执行边界。模型或 Agent 不能自行改变审批状态。

## 4. 持久化和恢复

`SQLiteBuilderRegistry` 追加保存 source snapshot、compile result、字段级血缘和 release manifest。重启后必须：

1. 重新读取并验证 payload hash；
2. 验证 release manifest 引用的 artifact hash 存在于已持久化 compile result；
3. 拒绝相同版本覆盖和孤立 release；
4. 保留不同 ontology/compile 版本的字段血缘记录。

## 5. 当前边界

该示例已经具备可审计的生产工程骨架，但真实生产化仍需替换 source adapter、权限/密钥系统、模型注册表、外部 action connector、监控告警和灾备存储。没有这些部署级组件，不应宣称已经接入真实 ERP 或具备自动执行现实业务动作的能力。

## 6. 验收命令

```powershell
pytest -q
python -m compileall -q src tests
```

至少还应检查：事件发生前的 PO-001 快照不包含 actual delivery，事件资料可用后才出现 `Delayed/delayDays=6`；冲突实体必须为 blocked；重启 SQLite 后 provenance/release hash 校验通过。
