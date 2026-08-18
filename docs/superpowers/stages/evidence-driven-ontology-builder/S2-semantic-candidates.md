# S2：术语与实体候选阶段设计

## 1. 阶段定位

S2 从证据片段中发现术语、别名、字段语义和实体候选，但不把候选直接当成已批准 Ontology。它建立跨文档组织混乱情况下的候选空间。

## 2. 目标与范围

识别业务词、缩写、同义表达、字段名、对象候选、事件候选和身份特征；输出可解释、可版本化、带证据的 `TermCandidate` 与 `EntityCandidate`。AI 可以做抽取、归一、候选解释和冲突提示；确定性代码负责 schema、证据存在性、版本和不可变性。

## 3. 输入与输出

输入：EvidenceFragment、BuilderContext、领域词典、既有 Ontology 版本和抽取策略版本。

输出：`TermCandidate`、`EntityCandidate` 和 `CandidateProposal`。所有子对象必须与 proposal 的 `proposal_version` 和 `context_digest` 一致；未绑定 Builder 的直接模型只能被视为 draft。

## 4. 工作流程

1. 对内容做语言、大小写、空格、缩写和字段名归一化，但保留原始 surface form。
2. 将文本命中、表头、JSON key、表格列和词典匹配转换为 TermCandidate。
3. 识别供应商、客户、订单、物料、事件和角色等 EntityCandidate。
4. 为每个候选绑定 source evidence refs，并检查片段是否包含名称/术语的语义支持。
5. 对同名异物、同物异名和定义冲突建立 conflict refs。
6. 给候选标注 `proposed`，不写入已发布 Ontology。

## 5. 关键技术原理

- 术语归一不是实体合并：`Acme Industries` 只能先作为别名候选。
- 候选实体与 canonical entity 分开：候选 ID 不等于外部系统主键。
- 证据必须支撑候选本身，不能只引用一个无关文件。
- 顶层 evidence refs 是 proposal 的依赖闭包，子对象不能引用未声明证据。
- Candidate value 使用深度不可变 JSON，防止生成后被调用方悄悄修改。

## 6. 门禁与失败处理

硬门禁：每个 term/entity 有来源证据、引用都可回放、候选版本和 context digest 完整、未知类型不通过、直接构造的 provider 不能自批准。

失败时：证据不足保持 unresolved；同名冲突进入 S3；低置信度候选不能进入事实集合；模型输出只作为 proposal，不具有写权限。

## 7. 验收标准

- `Acme Industrial` 与 `Acme Industries` 可同时存在，不能静默合并。
- 没有证据的 inference、fact、definition、rule 被拒绝；assumption 必须 `unreleased`。
- generic token 不能单独支撑事实。
- source 未显式提供的 external key 不得进入 confirmed match。
- `model_copy` 不能绕过 release status、版本、上下文和深度不可变约束。

## 8. 下游接口

S3 消费 EntityCandidate 和 evidence refs；S4 消费 TermCandidate；S5 只消费经过 `SemanticCandidateBuilder.build` 绑定上下文的 CandidateProposal。
