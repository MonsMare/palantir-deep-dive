# Palantir-like 工程公式：从业务世界到可执行决策系统

> 这份文档给出一套可以自行实现的 Palantir-like 工程公式。它不是 Palantir 未公开的内部源码或交付手册，而是基于 Palantir Foundry/AIP 公开文档、公开产品概念和工程推理整理出的可执行方法论。凡是官方文档没有明确披露的内部实现，本文都按“推荐的等价工程实现”表达，不把推理误写成 Palantir 的事实。

## 1. 最准确的工程公式

### 1.1 系统构造公式

$$
\text{Palantir-like 系统}
=
\text{业务决策契约}
\times
\text{业务世界 Ontology}
\times
\text{可信数据产品}
\times
\text{分析与特征计算}
\times
\text{预测模型}
\times
\text{决策/优化模型}
\times
\text{函数与 Agent 编排}
\times
\text{应用与用户工作流}
\times
\text{Action 执行与系统写回}
\times
\text{反馈、评估与治理}
$$

这里的“乘法”不是数学乘法，而是一个质量门槛：任一项为零，整体就只能成为报表、聊天机器人或流程镜像，而不是能够持续改变业务结果的运营系统。

### 1.2 业务价值公式

$$
\text{业务价值}
=
\text{决策价值}
\times
\text{数据可信度}
\times
\text{语义一致性}
\times
\text{预测有效性}
\times
\text{方案可行性}
\times
\text{用户采纳率}
\times
\text{动作执行成功率}
\times
\text{反馈闭环完整度}
$$

这个公式解释了为什么“模型准确率不错”仍然可能没有业务收益：

- 没有高价值决策，预测只是信息；
- 没有可靠标签和时间切面，预测会泄漏或漂移；
- 没有可执行约束，推荐方案不能落地；
- 没有用户在工作流中采纳，系统无法改变行为；
- 没有 Action 和结果回写，系统无法知道自己是否有效。

### 1.3 运行时闭环

真实业务事件
→ 数据产品
→ Ontology 对象、事件和状态
→ 指标与特征
→ 预测
→ 决策/优化方案
→ 用户解释、审批或拒绝
→ Action 与外部系统写回
→ 实际结果
→ 评估、再训练、策略改进和权限审计

因此，Palantir-like 系统的核心不是“Ontology 加大模型”，而是把业务决策变成一个有输入、有时间、有证据、有约束、有动作、有反馈的可运营闭环。

## 2. 先纠正一个常见理解

“描述模型 → 接大模型 → 做聊天机器人”缺失了三个决定业务价值的层：

1. 预测目标：系统到底要提前预测哪一个可观测事件；
2. 决策目标：预测后应该在什么约束下选择什么动作；
3. 执行反馈：动作是否被执行、是否成功、结果是否优于基线。

推荐的工程顺序是：

找到高价值业务决策
→ 定义用户、输入、判断、动作和结果
→ 建对象、事件、状态、时间和权限
→ 建可信数据产品
→ 建历史指标和可复现快照
→ 定义预测目标、标签、特征和时间切面
→ 训练、验证和发布预测模型
→ 定义目标函数、决策变量、约束和候选方案
→ 封装为函数、应用或 Agent 工具
→ 嵌入现有工作流
→ 执行 Action 并写回
→ 用结果评估、迭代和复制

这与 Palantir 公开的用例生命周期和开发排序思想一致，但本文把它进一步展开成了可自行实施的工程协议。参考：[Foundry Ontology 概览](https://www.palantir.com/docs/foundry/ontology/overview)、[Sequencing development](https://www.palantir.com/docs/zh/foundry/use-case-life-cycle/sequencing-development)。

## 3. 十个必须同时存在的组件

### 3.1 业务决策契约

业务决策契约是一个用例的最小闭环规格。它在建模前回答：

- 谁在什么场景下做什么决策；
- 决策时能看到什么输入；
- 决策窗口有多长；
- 可选动作是什么；
- 哪些动作需要审批；
- 成功和失败如何定义；
- 结果何时可观测；
- 用什么基线衡量增量价值。

以供应商延误为例：

~~~yaml
use_case: supplier_delay_mitigation
decision_owner: 采购经理
trigger: 订单在承诺交期前 14 天仍存在履约风险
decision: 是否催交、改派供应商、调整生产计划或使用安全库存
prediction_target: 未来 7 天内是否延误超过 3 天
decision_horizon: 当前时点到承诺交期
allowed_actions:
  - no_action
  - request_expedite
  - reallocate_supplier
  - adjust_production_plan
  - consume_safety_stock
hard_constraints:
  - 供应商产能
  - 物料替代关系
  - 最小订货量
  - 生产工序前置关系
  - 预算和审批权限
success_metric:
  - 缺料停线小时
  - 加急成本
  - 订单准时率
  - 总供应链成本
feedback_sources:
  - 实际到货时间
  - 用户采纳或拒绝
  - Action 执行结果
  - 生产是否因缺料受影响
~~~

没有决策契约，Ontology 很容易扩张成“所有业务对象的百科全书”，而不是解决一项具体任务。

### 3.2 业务世界 Ontology

Ontology 负责描述系统正在操作的业务世界：

- 对象：Supplier、PurchaseOrder、Shipment、Material、ProductionOrder；
- 关系：供应商承接订单、订单包含物料、订单关联运输、物料供给生产需求；
- 属性：承诺日期、数量、状态、成本、地点；
- 事件：确认、发运、改期、到货、取消、审批；
- 状态：已确认、在途、高风险、已延误、已解决；
- 时间：事件发生时间、生效时间、观测时间、预测时点；
- 权限：谁可查看、修改、审批和执行；
- 证据：对象值来自哪条记录、哪份文件、哪个源系统。

Ontology 的职责是提供共同语义和可操作对象，而不是承载所有模型权重、训练缓存和优化算法。Palantir 对象类型、属性、链接和动作类型的公开概念可参考：[Ontology core concepts](https://www.palantir.com/docs/foundry/ontology/core-concepts)。

### 3.3 可信数据产品

数据产品不是简单的 ETL 脚本，而是面向一个稳定业务语义输出的数据资产。每个数据产品至少要有：

- 输入源清单和源系统所有者；
- 原始层、标准化层、业务整合层、增强层和服务层；
- 主键、业务键、身份解析和去重规则；
- 字段定义、单位、枚举和时间含义；
- 数据质量期望、阈值、异常处理和隔离区；
- 运行频率、时延、重跑策略和服务等级；
- 数据血缘、版本、证据和责任人；
- 下游使用者、影响范围和变更兼容策略；
- 访问控制、敏感字段处理和审计记录。

推荐的层次：

| 层 | 作用 | 典型产物 |
| --- | --- | --- |
| Raw | 保留源数据事实，支持追溯 | 文件、API 响应、CDC、原始文本 |
| Staged | 类型、编码、列名和基础时间统一 | 标准化表、解析结果 |
| Conformed | 解决身份、粒度和跨源冲突 | Supplier、Order、Shipment 主表 |
| Enriched | 加入业务派生字段和外部信息 | 交期偏差、风险信号、地理距离 |
| Ontology projection | 映射到对象、关系、事件和状态 | 对象类型、链接、对象集 |
| Serving | 为应用、模型和报表提供稳定接口 | 特征表、指标表、API、快照 |

Palantir 的 Data Lineage、数据质量和数据期望思想，工程上可对应到数据契约、质量门禁和血缘图。参考：[Define data expectations](https://www.palantir.com/docs/foundry/maintaining-pipelines/define-data-expectations)。

### 3.4 分析与特征计算

分析层回答“过去发生了什么、为什么发生、目前处于什么状态”；特征层把业务事件转换成在某个观察时点真正可用的数值或类别输入。

特征不是一个字段名，而是一份可复现的计算契约：

~~~yaml
feature_id: supplier_30d_late_rate
entity_type: Supplier
grain: supplier_id
calculation: late_shipments / shipments_with_observed_outcome
observation_window: rolling_30d
as_of_time: prediction_request_time
availability_lag: 1d
missing_policy: missing_if_denominator_zero
version: v3
lineage:
  - shipment_events
  - purchase_orders
leakage_policy:
  exclude_records_after_as_of_time: true
  exclude_outcome_fields: true
~~~

这些栏目的必要性：

| 栏目 | 必要性 |
| --- | --- |
| 实体 | 确定特征属于谁，避免把供应商级数据错误拼到订单级 |
| 粒度 | 确定一行代表什么，防止重复计数和错误聚合 |
| 计算逻辑 | 让训练、离线评估和在线服务得到同一含义 |
| 时间窗口 | 表达近期行为、季节性和衰减，避免把不同阶段混为一谈 |
| 观察时点 | 固定“当时能知道什么”，形成时间旅行边界 |
| 数据可用延迟 | 模拟真实系统的到数时间，避免把尚未到达的数据用于预测 |
| 缺失处理 | 区分未知、没有发生和不适用，避免默认填零制造假信号 |
| 版本 | 让模型知道它依赖哪套定义，支持回滚和影响分析 |
| 数据血缘 | 能定位错误来源、解释预测、完成审计 |
| 数据泄漏规则 | 防止使用结果发生后的字段，保证离线指标可信 |

### 3.5 预测模型

预测模型回答“如果现在不改变什么，未来可能发生什么”。它必须显式定义：

- 预测对象和粒度；
- 标签事件、标签时间和观察窗口；
- 预测时点与未来窗口；
- 特征集和可用延迟；
- 训练样本生成规则；
- 评估切分策略；
- 概率校准、阈值和成本敏感性；
- 模型版本、输入版本和输出解释；
- 线上监控、漂移和再训练触发器。

供应商用例的一个预测问题：

~~~yaml
prediction_problem: supplier_late_over_3d_within_7d
entity: PurchaseOrder
label: actual_delivery_time > promised_delivery_time + 3d
prediction_time: every_daily_snapshot
horizon: 7d
features:
  - supplier_30d_late_rate
  - order_confirmation_delay
  - shipment_missing_scan_days
  - route_disruption_score
  - material_criticality
output:
  probability: late_probability
  risk_band: low_medium_high
  explanation: evidence_and_contributing_features
~~~

预测结果可进入 Ontology 成为派生对象，例如 DelayPrediction：

- linked_order；
- predicted_at；
- horizon_end；
- probability；
- risk_band；
- model_version；
- feature_snapshot_version；
- evidence_links；
- expires_at。

但模型权重、训练日志和大规模张量通常保留在模型仓库或对象存储中；Ontology 保存可治理、可解释、可关联和可供下游使用的模型产物。

Palantir 公开文档强调模型集成、模型目标和通过函数调用模型；参考：[Model objectives](https://www.palantir.com/docs/zh/foundry/model-integration/objectives)、[Functions on models](https://www.palantir.com/docs/foundry/functions/functions-on-models)。

### 3.6 决策/优化模型

决策模型回答“在预测和约束已知时，现在应该比较哪些方案”。它与预测模型不同：

- 预测模型估计未来状态或概率；
- 决策模型在目标函数和约束下选择行动；
- 推荐结果必须说明假设、代价、风险和不可行原因；
- 能执行的候选方案要经过权限、审批和外部系统校验。

供应商延误的决策问题：

~~~yaml
decision_problem: supplier_delay_mitigation_v1
objective:
  minimize:
    - shortage_cost
    - expedite_cost
    - production_delay_cost
    - supplier_switch_cost
variables:
  expedite_quantity: nonnegative
  reallocated_quantity: nonnegative
  safety_stock_consumption: nonnegative
constraints:
  - reallocated_quantity <= alternate_supplier_capacity
  - production_requirement must be satisfied
  - minimum_order_quantity
  - budget_limit
  - material_substitution_allowed
inputs:
  - DelayPrediction
  - InventoryPosition
  - SupplierCapacity
  - ProductionRequirement
outputs:
  - CandidatePlan
  - objective_value
  - constraint_slack
  - infeasibility_reasons
~~~

CandidatePlan 可以是：

- 不动作；
- 催交若干数量；
- 将部分数量改派至备用供应商；
- 消耗安全库存；
- 调整生产批次或排产顺序。

决策模型的效果不是“推荐听起来合理”，而是把预测风险转换为可比较的成本、服务水平和资源影响，并保证候选方案在硬约束内可执行。

### 3.7 Functions 与 Agent 编排

一个可治理的运行时通常分为两类：

- Function：确定性、可测试、带类型和权限边界的业务函数，例如计算风险、生成候选方案、创建催交请求；
- Agent：理解用户意图、选择工具、组织上下文、解释结果、请求澄清和编排多个函数。

Agent 不应直接绕过权限或直接写生产系统。推荐链路：

用户问题
→ Agent 识别意图
→ 检查用户权限和对象范围
→ 读取 Ontology 对象及证据
→ 调用分析/预测/优化函数
→ 生成解释和候选方案
→ 用户确认或审批
→ 调用 Action
→ Action Runtime 写回外部系统
→ 记录完整审计和结果

### 3.8 应用与用户工作流

应用不是模型的展示壳，而是把“查看、判断、审批、执行、复盘”安排在用户已有工作节奏中的工作台。

供应商风险工作台至少需要：

- 今日需要处理的风险订单；
- 风险排序和预测置信度；
- 关键证据时间线；
- 预测与历史基线比较；
- 候选方案、目标函数和约束解释；
- 用户可编辑参数；
- 审批、拒绝、转派和备注；
- Action 状态和失败重试；
- 结果复盘和反馈入口。

应用设计的验收问题不是“用户能否看到预测”，而是“用户是否能在原来处理一张订单的时间内完成更好的决策”。

### 3.9 Action、外部系统写回和事实闭环

Action 是系统改变现实的边界。一个 Action 需要定义：

- 作用对象；
- 参数及其类型；
- 调用者权限；
- 审批条件；
- 幂等键；
- 外部系统目标；
- 成功、失败、超时和部分成功；
- 回写事件；
- 撤销或补偿方式；
- 审计信息。

例如 RequestExpedite：

~~~yaml
action: request_expedite
target: PurchaseOrder
parameters:
  quantity: integer
  requested_date: date
  reason: text
authorization:
  - procurement_manager
approval:
  required_when: expedite_cost > approval_threshold
external_system: ERP_or_supplier_portal
idempotency_key: order_id + requested_date + quantity
writeback_events:
  - expedite_requested
  - expedite_confirmed
  - expedite_rejected
  - actual_delivery_observed
~~~

Palantir 的 Action Type 和 Action 应用概念可参考：[Action types](https://www.palantir.com/docs/foundry/action-types/overview)。

### 3.10 反馈、评估和治理

必须同时记录三种反馈：

- 世界反馈：实际到货、实际成本、是否缺料、是否停线；
- 用户反馈：采纳、拒绝、修改、忽略以及拒绝原因；
- 系统反馈：数据延迟、函数失败、Action 失败、模型漂移和策略版本。

这三类反馈分别用于：

- 计算预测标签和校准模型；
- 判断推荐是否可用、是否改变用户行为；
- 发现数据产品、应用和运行时的可靠性问题。

## 4. 五个维度不是五座孤岛

“描述、分析、预测、决策、行动反馈”可以作为五个张力维度理解，但它们必须通过共享契约连接：

| 共享契约 | 描述模型 | 分析 | 预测 | 决策 | Action/反馈 |
| --- | --- | --- | --- | --- | --- |
| 身份 | 对象和关系主键 | 聚合实体 | 样本实体 | 决策对象 | 作用对象 |
| 时间 | 事件、生效和状态时间 | 截止快照 | 观察时点和预测窗口 | 方案有效期 | 执行和结果时间 |
| 输入输出 | 属性、事件 | 指标 | 特征和预测 | 变量、约束和候选方案 | 参数和结果 |
| 版本 | Ontology 版本 | 指标版本 | 模型和特征版本 | 优化器和策略版本 | Action 版本 |
| 权限 | 对象可见性 | 聚合可见性 | 输出可见性 | 推荐和审批权限 | 执行权限 |
| 反馈 | 新事件和新状态 | 结果指标 | 标签和漂移 | 方案效果 | 成功、失败和拒绝 |

如果这张表没有落到接口、表结构、对象属性、权限规则和审计记录中，五个维度就只是概念分层。

## 5. RDFS 能不能承载分析、预测和决策

### 5.1 正确答案

RDFS 可以描述这三类模型的语义关系，但不能单独实现它们的计算能力。

RDFS 适合表达：

- 什么是 FeatureDefinition、PredictionProblem、DecisionProblem；
- 某个特征作用于什么实体；
- 某个预测问题使用什么特征；
- 某个决策问题使用什么预测；
- 某个候选方案对应什么 Action；
- 哪个产物由哪个版本生成。

RDFS 不适合单独表达和执行：

- 大规模窗口聚合；
- 特征物化和低延迟查询；
- 机器学习训练和推理；
- 概率校准；
- 线性/整数规划、约束求解；
- 事务、审批、重试和外部系统写回。

因此正确做法是“RDFS/OWL 描述语义 + SHACL 做结构约束 + SQL/Python/Spark 做数据计算 + ML Runtime 做预测 + Solver 做优化 + Policy/Action Runtime 做治理和执行”。

### 5.2 最小 RDF 语义层示例

~~~turtle
ex:PurchaseOrder a rdfs:Class .
ex:Supplier a rdfs:Class .
ex:DelayPrediction a rdfs:Class .
ex:FeatureDefinition a rdfs:Class .
ex:PredictionProblem a rdfs:Class .
ex:DecisionProblem a rdfs:Class .
ex:CandidatePlan a rdfs:Class .
ex:ActionOutcome a rdfs:Class .

ex:linkedOrder a rdf:Property ;
  rdfs:domain ex:DelayPrediction ;
  rdfs:range ex:PurchaseOrder .

ex:usesFeature a rdf:Property ;
  rdfs:domain ex:PredictionProblem ;
  rdfs:range ex:FeatureDefinition .

ex:usesPrediction a rdf:Property ;
  rdfs:domain ex:DecisionProblem ;
  rdfs:range ex:PredictionProblem .

ex:producesPlan a rdf:Property ;
  rdfs:domain ex:DecisionProblem ;
  rdfs:range ex:CandidatePlan .

ex:implementsAction a rdf:Property ;
  rdfs:domain ex:CandidatePlan ;
  rdfs:range ex:ActionOutcome .

ex:calculationSpec a rdf:Property .
ex:observationWindow a rdf:Property .
ex:availabilityLag a rdf:Property .
ex:leakagePolicy a rdf:Property .
ex:modelVersion a rdf:Property .
ex:objectiveSpec a rdf:Property .
ex:constraintSpec a rdf:Property .
~~~

RDF 只负责把产物放进可发现、可链接、可治理的语义网络。具体计算由外部可版本化实现完成，例如：

- FeatureDefinition → SQL/Python/Spark 计算作业；
- MetricDefinition → 指标物化表或查询服务；
- PredictionProblem → 训练数据生成器和模型服务；
- DecisionProblem → 优化器、规则引擎或仿真器；
- CandidatePlan → 函数输出和用户可审查对象；
- ActionOutcome → 事务服务、消息总线和外部系统回执。

## 6. 供应商延误的完整链路

~~~mermaid
flowchart LR
  A["ERP 订单、供应商回执、物流扫描、库存和生产计划"] --> B["数据产品：订单履约与运输事件"]
  B --> C["Ontology：Supplier、PurchaseOrder、Shipment、InventoryPosition"]
  C --> D["分析：交期偏差、扫描缺口、供应商历史表现"]
  D --> E["特征快照：按订单和观察时点冻结"]
  E --> F["预测：未来 7 天延误概率"]
  F --> G["决策/优化：目标函数、变量和硬约束"]
  G --> H["CandidatePlan：不动作、催交、改派、用库存、调排产"]
  H --> I["应用：证据、解释、成本、风险和审批"]
  I --> J["Action：ERP 催交、改派或排产调整"]
  J --> K["执行回执和实际到货事件"]
  K --> L["标签、用户反馈、ROI、模型和策略评估"]
  L --> D
  L --> F
  L --> G
~~~

其中每一步的“作用”不同：

| 节点 | 做什么 | 为什么必要 |
| --- | --- | --- |
| 数据产品 | 从多个源恢复订单、事件和时间 | 没有稳定事实就没有可复现样本 |
| Ontology | 统一对象、关系、状态和权限 | 让人、模型、应用使用同一业务语义 |
| 分析 | 计算历史基线和当前信号 | 为预测和解释建立业务上下文 |
| 特征快照 | 冻结当时可用的输入 | 防止未来信息泄漏 |
| 预测 | 输出未来事件概率和证据 | 把被动查询变成提前干预 |
| 决策/优化 | 比较可行动作的成本与效果 | 把风险转为行动选择 |
| 应用 | 让负责人审查、修改和审批 | 把模型嵌入工作流 |
| Action | 真正修改订单、计划或库存 | 产生现实业务影响 |
| 反馈 | 回收结果和人机交互 | 形成标签、ROI 和持续改进 |

## 7. 面向散乱文件和数据的数据产品方法

Palantir-like 数据工程的关键不是让一个 LLM 直接读完所有文件，而是建立“证据可追溯的逐层收敛管道”。

### 7.1 源盘点和文档分区

先建立 SourceInventory：

- 来源系统、文件夹、表、接口和责任人；
- 内容类型、敏感级别、更新频率和可信级别；
- 主体对象和可能覆盖的业务事件；
- 文档版本、有效期、语言和解析难度；
- 与其他来源的重叠、冲突和补充关系。

把原始文件不可变保存，并为每个文件记录哈希、采集时间、来源路径和解析器版本。

### 7.2 解析、切分和证据保留

将文件转换为带位置信息的结构化片段：

- 文本、表格、图片、附件分别处理；
- 保存页码、段落、表格行列、文件版本和字符区间；
- 抽取实体、事件、日期、数量、单位、条件和责任人；
- 把抽取结果与原文证据绑定，而不是只保存一个最终值；
- 对低置信度或冲突字段进入人工核验队列。

LLM 可用于候选抽取、字段映射和冲突解释，但不应替代确定性校验、身份解析和人工裁决。

### 7.3 标准化、身份解析和时间归一

对散乱资料做：

- 单位、币种、时区、日期格式和枚举统一；
- 供应商、订单、物料、地点的别名映射；
- 主键与业务键分离；
- 一对多、多对一和合并拆分关系显式保存；
- 区分事件发生时间、文件记录时间、生效时间和入库时间；
- 迟到数据采用回补、重算和版本化策略。

### 7.4 冲突和重叠处理

每个字段要有来源优先级和冲突规则：

- 业务权威系统优先于非权威附件；
- 最新有效版本优先于旧版本；
- 确认事件优先于预测事件；
- 结构化回执优先于自由文本推断；
- 不同来源只表达不同语义时，不强行覆盖，保留多值和证据；
- 无法裁决时生成 DataIssue，而不是静默选择一个值。

### 7.5 质量门禁和隔离区

建立可量化的 DataExpectation：

- 主键唯一率；
- 必填字段完整率；
- 日期顺序合法率；
- 订单与供应商关联率；
- 事件去重率；
- 到数延迟；
- 分区新鲜度；
- 解析置信度；
- 与上游总量的对账差异。

失败记录进入 quarantine；下游可以选择阻断、降级或继续但标注风险。每个质量结果要能反查到源文件、转换步骤和责任人。

### 7.6 输出数据产品而不是一次性结果

数据产品要公开稳定接口：

- 业务实体表；
- 事件表；
- 当前状态表；
- 历史快照表；
- 指标和特征表；
- 证据表；
- 数据质量结果；
- 血缘和版本元数据。

这样，Ontology、分析、预测和应用消费同一份可解释产物，而不是各自重新清洗一遍。

## 8. 从项目启动到交付的工程节奏

### 阶段 0：立项和价值假设

客户通常提出：

- 降低成本、库存、停机或加急费用；
- 提高准时交付、产能、良率或服务水平；
- 缩短计划、审核、响应和调查时间；
- 让管理者获得跨系统的可见性；
- 把专家经验标准化；
- 在突发事件中更快比较和执行方案。

交付物不是“做一个 AI 平台”，而是一份带基线、决策人、时间窗口和价值指标的用例契约。

### 阶段 1：需求提炼和现场观察

以真实决策事件为单位采集：

- 触发事件；
- 决策者和参与者；
- 当时可见的输入；
- 输入来自哪个系统或文件；
- 判断规则、例外和经验；
- 候选动作和审批链；
- 动作结果和结果可见时间；
- 用户会如何解释一次成功或失败。

方法包括访谈、跟班观察、历史案例回放、屏幕/表单走查、异常事件复盘和样本文件核对。与原团队的摩擦处理方式：

- 让业务专家拥有语义和例外裁决权；
- 让技术团队负责可复现实现和质量证据；
- 用真实案例共同标注，而不是争论抽象模型；
- 先做只读辅助和并行运行，再逐步开放 Action；
- 记录拒绝理由和人工覆盖，不把专家行为当作“噪声”。

### 阶段 2：方案设计和全量模型

不要试图一次性画出全企业本体。先从一个高价值决策建立“最小闭环”，再用相邻决策扩展。

建模顺序：

1. 画决策流程和事件时间线；
2. 列出决策所需对象、关系、事件、状态和权限；
3. 建立对象身份与源字段映射；
4. 标注当前值、历史值、预测值和方案值；
5. 标注谁可看、谁可改、谁可审批；
6. 将异常、手工覆盖和证据作为一等元素；
7. 为每个对象和事件绑定数据血缘；
8. 为每个预测、方案和 Action 绑定版本。

AI 可以加速：

- 从文档和表结构生成候选实体、属性和关系；
- 对字段做语义匹配、单位识别和枚举归一；
- 从流程文本抽取事件、角色、条件和动作；
- 自动发现同义对象、重复字段和潜在主键；
- 根据历史日志提出状态机和异常路径；
- 生成候选 FeatureDefinition、测试样本和映射草案；
- 从 Ontology 查询生成应用骨架、函数接口和测试用例。

AI 只能生成候选，不能自动决定权威语义、权限、标签真值或生产 Action 逻辑；这些必须经过业务专家和数据所有者确认。

### 阶段 3：数据接入和数据产品

优先接入能闭合一个决策的最小数据集：

- 事实源；
- 事件源；
- 结果/标签源；
- 约束源；
- 权限和组织源。

先保证可追溯、可重跑、可对账，再扩展来源。每新增一个字段都要回答：它服务哪个决策、由谁负责、是否可在观察时点获得、错误时怎么办。

### 阶段 4：Ontology 建模

先建可执行对象，不追求全量属性：

- 对象类型和唯一标识；
- 关系和反向导航；
- 当前状态与状态变更事件；
- 证据和数据血缘；
- 权限；
- 与指标、特征、预测和候选方案的关联；
- 可以改变世界的 Action。

### 阶段 5：分析、预测和决策

按顺序交付：

- 历史基线和指标；
- 时间切分的特征快照；
- 可解释预测；
- 成本和约束明确的候选方案；
- 离线回放；
- 与人工基线比较；
- 小范围影子运行；
- 受控 Action。

### 阶段 6：应用嵌入、运营和复制

通过工作台、任务队列、审批、通知和外部系统集成进入日常流程。上线后监控：

- 数据质量和新鲜度；
- 预测性能和漂移；
- 方案采纳率和人工覆盖率；
- Action 成功率；
- 实际业务指标；
- 权限异常和审计事件。

稳定后再复制到相邻部门，同时复用对象、数据产品、特征、函数、权限模板和评估框架。

## 9. 组件连接关系

| 组件 | 输入 | 输出 | 连接对象 |
| --- | --- | --- | --- |
| 数据连接 | 数据库、API、文件、消息和文档 | 原始数据集、证据片段 | 数据产品 |
| 数据产品 | 原始数据和转换规则 | 标准表、事件、质量、血缘 | Ontology、分析、模型 |
| Ontology | 数据产品和业务语义 | 对象、关系、状态、权限 | 应用、函数、Agent |
| 分析 | 对象、事件和快照 | 指标、聚合、解释 | 特征、应用 |
| 特征 | 历史事件和观察时点 | 可复现特征快照 | 预测模型 |
| 预测 | 特征快照和模型版本 | 概率、类别、解释、风险对象 | 决策模型、应用 |
| 决策/优化 | 预测、资源、成本和约束 | 候选方案、目标值、不可行原因 | 应用、Action |
| Function | Ontology 对象和模型 | 类型化业务计算 | Agent、应用、Action |
| Agent | 用户意图和权限上下文 | 工具调用、解释和编排 | Function、应用 |
| Action | 用户确认、权限和参数 | 外部写回、回执、审计 | 反馈和标签 |
| 反馈评估 | 实际结果、用户行为和运行日志 | 标签、ROI、漂移、改进任务 | 数据产品、模型、策略 |

Palantir 的 Object Views、Functions、Actions 等公开概念可参考：[Object Views](https://www.palantir.com/docs/foundry/object-views/overview)、[Functions on models](https://www.palantir.com/docs/foundry/functions/functions-on-models)、[Action types](https://www.palantir.com/docs/foundry/action-types/overview)。

## 10. 最小可用 Palantir-like 实现

如果不复制 Palantir 的全部平台，建议先实现一个垂直用例：

1. PostgreSQL 或对象存储保存 Raw、Conformed、Feature、Prediction、Plan 和 Feedback；
2. dbt、Dagster 或 Airflow 负责可重跑数据管道；
3. Great Expectations 或 Soda 负责质量门禁；
4. OpenLineage 或自建元数据表保存血缘；
5. RDF4J、Jena 或 PostgreSQL 关系表承载 Ontology 语义；
6. SHACL 校验对象和模型元数据；
7. Python、Polars、DuckDB 或 Spark 计算指标和特征；
8. MLflow 管理模型版本、指标和部署；
9. FastAPI 或函数运行时提供预测和决策接口；
10. OR-Tools、Pyomo 或商用 Solver 执行优化；
11. OPA 或自建 Policy Service 做权限和审批条件；
12. React/Next.js 或 Retool 构建风险工作台；
13. Temporal、消息队列或工作流引擎管理 Action、重试和回执；
14. OpenTelemetry、Prometheus 和审计库记录运行质量。

最低验收标准：

- 一个真实决策能从源数据走到候选方案；
- 每个预测都能回到特征快照、模型版本和证据；
- 每个候选方案都能展示目标函数、约束和不可行原因；
- 用户可以确认、拒绝、修改并完成审批；
- Action 有幂等、回执、失败重试和审计；
- 实际结果能生成预测标签和业务 ROI；
- 数据、模型、Ontology、策略和 Action 都可版本化回滚。

## 11. 最终判断

最准确的 Palantir-like 工程公式不是：

Ontology + 大模型 + 聊天机器人

而是：

业务决策契约
+ 业务世界语义
+ 可追溯数据产品
+ 时间正确的分析与特征
+ 对未来的预测
+ 受约束的决策/优化
+ 可治理的函数和 Agent
+ 嵌入工作流的应用
+ 有权限、有审批、有回执的 Action
+ 真实结果、用户反馈和持续评估

用一句话概括：

> Ontology 让系统知道“世界里有什么、它们如何关联、谁能做什么”；数据产品保证系统知道的事实可信且可追溯；分析让系统理解过去；预测让系统推断未来；决策/优化让系统比较可行选择；应用和 Agent 让用户愿意使用；Action 让系统改变现实；反馈让系统知道改变是否有效。

与本项目其他研究资料的关系：

- [Palantir 文档研究索引](README.md)
- [AI-FDE Shipyard Workbench 设计](../docs/superpowers/specs/2026-08-15-ai-fde-shipyard-workbench-design.md)
- [Shipyard 文档入口](../docs/README.md)
