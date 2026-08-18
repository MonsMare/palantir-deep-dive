# S6：数据产品构建与验证阶段设计

## 1. 阶段定位

S6 证明 Ontology 不是业务流程的静态镜像，而是能从源数据稳定重建对象、事件、状态和可计算字段的数据产品。它是后续预测、决策和 Agent 使用 Ontology 的基础。

## 2. 目标与范围

构建 canonical product、object projection、event/state reconstruction、provenance product、quality report 和 lineage graph。处理多文档重复、字段重叠、时间错位、缺失、撤销、迟到数据和权限传播。

## 3. 输入与输出

输入：S5 MappingSpec、SourceSnapshot/EvidenceFragment、OntologyCandidate、SHACL shapes、质量规则、时间语义和 access policy。

输出：`CanonicalProduct`、`ProvenanceProduct`、`QualityReport`、`TemporalReport` 和 `DataProductVersion`。

## 4. 工作流程

1. 读取 SourceSnapshot，执行 source path 和 transform。
2. 以目标 grain 聚合，生成 canonical identity。
3. 做实体外键解析，并保留 unresolved，不默认丢弃。
4. 分离 valid/event/observed/available time。
5. 生成对象、关系、事件和状态投影。
6. 为每行写入 evidence refs、source locations、mapping ids。
7. 执行 data quality、SHACL、temporal safety 和权限传播检查。
8. 生成版本化产品与 diff，失败则阻断 S7。

## 5. 关键验证规则

- 目标粒度稳定：一个 purchase order 不应被无理由复制成多个对象。
- 主键/外键可解析；重复和冲突必须可见。
- `observed_at <= available_at`；预测 as-of 时只能使用 `available_at <= as_of_time`。
- event time 不等于 available time；迟到记录不能改变历史可见性。
- actual delivery 等未来结果只能作为 label/回溯事实，不能进入过去的 feature snapshot。
- 每条产品记录都有血缘闭环：product → mapping → evidence → snapshot → source asset。
- classification 和 access policy 从源到字段、属性、预测和 action 传递。

## 6. 门禁与失败处理

硬门禁：schema、grain、identity、temporal、provenance、SHACL、权限和可重建性通过。数据质量低于阈值或 source drift 未审查时 blocked；可自动修复的格式问题必须记录修复版本，不能静默修复。

## 7. 验收标准

- 用同一 source snapshot 重跑获得相同 product hash。
- 每个 canonical row 和 ontology object 都能追溯到 evidence。
- 删除一个来源片段的反事实测试能够暴露受影响对象和映射。
- 未来字段进入 feature frame 的测试失败。
- 质量报告可解释“哪些对象缺失、为什么缺失、影响哪些下游模型/决策”。

## 8. 下游接口

S7 消费 DataProductVersion、QualityReport、TemporalReport、ProvenanceCoverage；模型工程和领域 Agent 只能读取发布版本或明确标记的候选版本。
