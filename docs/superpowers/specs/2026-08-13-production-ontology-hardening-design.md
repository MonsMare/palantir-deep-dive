# Shipyard 生产级 Ontology 产出能力改造设计

归属：AI-FDE Shipyard 的构建质量内核，不是客户生产运行时设计。

## 目标

把当前可运行的证据驱动 Builder 从“能够生成并发布结构化候选”提升为“能够生成具备字段级时间安全、实体治理、业务语义约束和计算闭环契约的可交付 Ontology Release Package”。

这里的“生产级”限定为 Shipyard 构建质量：对同一组输入能够稳定重建，所有事实和计算结果可追溯，未来数据不能进入历史快照，高影响实体不确定时不能发布，RDF/SHACL 与数据产品可执行，预测/决策/Action 能绑定已发布的 Ontology 版本。真实 ERP/API 连接器和客户运行时仍通过交付适配器接入，不在本次模拟项目中伪造。

## 现状缺陷

1. 证据血缘只到行级，`actual_delivery_date` 的 `available_at` 没有传播到字段和 as-of 数据产品，可能发生数据泄漏。
2. 有冲突的 `probable_match` 可以通过挑战门禁并进入发布数据。
3. Ontology 候选声明了状态和事件，但没有完整生成订单行、承诺修订、交付异常和派生状态实例。
4. RDFS 属性缺少稳定的 domain/range/datatype，SHACL 主要检查字段存在，不能检查类型、关系和业务状态。
5. Feature、Prediction、Decision、Action、Feedback 尚未共享同一个 Ontology release、数据产品版本和时间/血缘契约。

## 设计原则

### 1. 字段级时间安全

每个规范化字段必须携带独立的值、证据、event time、observed time、available time、valid time 和来源版本。行级时间是所有可见字段时间的保守聚合，不能覆盖字段级时间。

`materialize_as_of(as_of_time)` 只返回 `available_at <= as_of_time` 的字段；被隐藏的字段不能出现在值、特征或证据引用中。

### 2. 不确定实体默认不进入生产计算

`confirmed` 才能进入 released prediction/decision 数据；带冲突的 `probable_match`、`unresolved` 和 `rejected` 必须阻断生产发布或降级为 review-only 数据集。

### 3. 描述、事实、推断和派生计算分层

RDFS 描述类型和关系；Evidence/Assertion 描述事实的认识状态；SHACL 检查结构；规则编译器生成状态、异常和派生字段；Feature/Prediction/Decision 不伪装成事实。

### 4. 计算结果必须绑定发布版本

FeatureSnapshot、Prediction、DecisionCandidate、ActionRequest、ActionOutcome 和 Feedback 都必须引用 Ontology release、数据产品版本、计算版本和 as-of/available 时间。

## 目标架构

```text
SourceSnapshot / EvidenceFragment
        ↓
FieldValueProvenance
        ↓
Canonical Product + as-of materialization
        ↓
Typed RDFS + SHACL + derived states/events
        ↓
OntologyReleasePackage
        ↓
FeatureSnapshot → Prediction → DecisionCandidate
                                      ↓
                              approved ActionRequest
                                      ↓
                                ActionOutcome
                                      ↓
                                  Feedback
```

## P0 交付

- 新增字段级 `FieldValueProvenance`。
- canonical row 和 provenance row 同时保存字段级血缘。
- 增加 `CompileResult.materialize_as_of`，未来字段不可见。
- 时间门禁检查每个字段的可用时间、事件时间、观察时间和行级聚合一致性。
- 高影响实体的 `probable_match + conflict_refs` 阻断 `adversarial.challenge`。
- 演示数据改为用来源明确的 external key 解决正常路径；保留冲突路径验证阻断。

## P1 交付

- 增加 `PurchaseOrderLine`、`PromisedDelivery`、`PromisedDateRevision`、`DeliveryEvent`、`DeliveryException`。
- 生成 `OnTime`、`Delayed`、`Unknown` 和 `delayDays` 的实例或派生字段。
- RDFS 输出明确的 domain、range 和 XSD datatype。
- SHACL 支持 datatype、class、maxCount、pattern 等约束；编译器补充跨字段业务规则。
- 订单行、交付事件、异常和证据均保持可追溯。

## P2 交付

- 建立通用计算契约：`FeatureDefinition`、`FeatureSnapshot`、`LabelDefinition`、`PredictionArtifact`、`DecisionCandidate`、`GovernedActionRequest`、`ActionOutcomeLink`、`FeedbackLink`。
- 计算对象必须引用 Ontology release、数据产品版本、模型/决策版本、as-of 时间和血缘。
- Feature materializer 只能从 as-of 数据产品生成输入；Prediction 不能引用未来字段。
- DecisionCandidate 必须引用预测和约束；Action 必须引用已批准决策并通过现有 Action Broker；Feedback 必须能回连 Action/Prediction。

## 验收标准

1. 在事件发生日之前 materialize 的 PO-001 不包含实际到货日期和 Delayed 状态；事件资料 available 后才出现。
2. 任意字段的 `available_at` 晚于 as-of 时，特征构建硬失败或隐藏该字段，不能静默使用。
3. 带冲突的高影响 probable match 无法进入 released。
4. PO-001 能生成 `Delayed` 和 `delayDays = 6`，没有实际日期的订单为 `Unknown`。
5. RDF 日期为 `xsd:date`，关系具备 domain/range，SHACL 能拦截类型、关系和状态错误。
6. 计算对象缺少 release/version/as-of/lineage 任一项时构造失败。
7. 未批准的 Action 无法执行；ActionOutcome 和 Feedback 具备回链。
8. 全量回归测试、P0/P1/P2 专项测试和编译检查全部通过。
