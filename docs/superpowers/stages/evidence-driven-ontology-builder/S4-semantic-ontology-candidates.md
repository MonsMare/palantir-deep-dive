# S4：业务语义候选阶段设计

## 1. 阶段定位

S4 把候选术语、实体、关系和证据组织成可讨论的业务语义声明。它是从“发现文本”到“定义业务世界”的边界，但仍然只生成候选，不发布事实。

## 2. 五种声明类型

| 类型 | 含义 | 发布条件 |
|---|---|---|
| `fact` | 来源直接支持的业务事实 | 证据存在、语义支撑、领域确认 |
| `definition` | 业务对象/指标/状态的定义 | reviewer owner、证据或规范依据、领域确认 |
| `rule` | 可执行的业务规则 | executable expression、测试和 owner |
| `inference` | 基于证据的推断 | 证据、推断方法、默认 unreleased |
| `assumption` | 尚未证实的假设/未知 | 永远不能直接进入 released fact |

## 3. 输入与输出

输入：S2 术语候选、S3 实体匹配、EvidenceFragment、领域上下文、既有 Ontology 和决策目标。

输出：`SemanticAssertion`、关系候选、状态/事件候选、开放问题、冲突清单和候选 proposal。

每条非 assumption 声明必须有 evidence refs，且声明证据必须属于 proposal 顶层依赖闭包并语义支撑 subject/predicate/value；推断不能引用不存在的 subject candidate。

## 4. 工作流程

1. 将候选实体、术语和证据装配为 subject/predicate/value。
2. 识别对象关系：订单—供应商、订单—交付事件、订单—异常。
3. 识别状态和事件：OnTime、AtRisk、Delayed、PromisedDateRevision、DeliveryEvent。
4. 将业务定义与来源事实分开；将推断和假设分开。
5. 生成规则候选，例如 `actual_delivery_date > promised_delivery_date`。
6. 为每条声明生成 explanation、evidence refs、reviewer owner、版本和 context digest。
7. 输出 open questions，不用默认值伪造缺失业务语义。

## 5. 关键技术原理

- RDFS/OWL 负责描述类、属性、关系和继承；声明的 epistemic status 需要额外的 assertion/claim 层。
- `actual_delivery_date` 未知不能变成“未延误”；它必须保持 assumption/unknown。
- 未关联 PO 的“供应商日期修改”只能是 source-specific inference，不能写成已确认供应商事实。
- 规则是可执行约束，不是自然语言提示；规则要有测试和版本。

## 6. 门禁与失败处理

硬门禁：非 assumption 声明有证据、证据语义支持、subject candidate 存在、定义有 owner、rule 有 executable expression、inference/assumption 不能 eligible、proposal 和子对象版本一致。

失败时：声明降级为 unresolved/open question；冲突进入 S3/S7；无法判断的语义不由 LLM 猜测。

## 7. 验收标准

- 可区分 fact/definition/rule/inference/assumption。
- 证据引用不仅“存在”，还要支持具体声明。
- 版本、context digest、evidence closure 和 release status 可审计。
- 下游编译器可从声明生成 Ontology、映射和质量检查，而不是从聊天记录猜语义。

## 8. 下游接口

S5 消费经过 Builder 校验的 `CandidateProposal`；S6 使用 rule、temporal semantics 和 evidence refs 生成数据产品质量检查；S7 将 open questions、assumptions、conflicts 转为审批项。
