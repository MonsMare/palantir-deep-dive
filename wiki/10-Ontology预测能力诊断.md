# Ontology 为什么只是业务镜像：预测能力缺口诊断

## 1. 核心判断

你的原方法并不是 Ontology 建模错误，而是把 Ontology 的职责扩大成了预测系统本身。

Ontology 主要解决的是：

> 业务世界里有什么对象、对象如何关联、对象当前处于什么状态、谁可以对它做什么。

预测系统还需要解决另一组问题：

> 在某个历史时点上，我们知道什么？之后发生了什么？哪些先行信号能预测结果？预测多久以后？预测错了代价是什么？采取动作后结果如何？

Palantir 官方把 Ontology 描述为组织的运营层，包含对象、属性、链接等语义元素，以及动作、函数和动态安全等动力元素；它是 AI 和应用运行的上下文与执行平面，但不是自动产生预测能力的算法本身。[Ontology 总览](https://www.palantir.com/docs/foundry/ontology/overview)

## 2. 四种模型要分开

| 模型类型 | 核心问题 | 典型产物 | 你的原模型可能缺少的内容 |
|---|---|---|---|
| 描述模型 | 世界里有什么？ | 对象、属性、链接、当前状态 | 通常已经具备 |
| 分析模型 | 发生了什么？为什么？ | 指标、聚合、根因分析、仪表盘 | 可能部分具备 |
| 预测模型 | 将来会发生什么？什么时候发生？ | 标签、特征、训练模型、评分 | 常常缺失 |
| 决策/优化模型 | 应该采取什么行动？ | 目标函数、约束、方案、动作 | 通常缺失 |

因此，流程镜像只能回答：

```text
供应商 A 当前有订单 100 个
其中 20 个处于运输中
有 3 个订单已经逾期
```

但预测需要回答：

```text
以 2026-08-10 12:00 为信息截点，
供应商 A 的订单 123 在未来 7 天内延误超过 3 天的概率是多少？
如果延误，预计损失是多少？
现在采取改派供应商、加急运输或调整库存，哪个方案的风险/成本最低？
```

## 3. 你的模型没有产生预测能力的八个根因

### 3.1 只有当前状态，没有时间快照

供应商延误预测必须使用“当时可见的信息”预测“之后发生的结果”。如果只保留订单当前状态，无法知道过去某个时点的订单状态、承诺日期、运输状态和供应商行为。

必须区分至少四种时间：

- `event_time`：事件实际发生时间；
- `valid_time`：事实对业务有效的时间；
- `observed_time`：平台观察到该事实的时间；
- `as_of_time`：模型做预测时允许使用信息的截止时间。

如果模型训练使用了 `as_of_time` 之后才出现的数据，就发生未来信息泄漏。

### 3.2 只有对象，没有预测标签

Ontology 中有 `Supplier`、`Order`、`Shipment`，并不等于有监督学习目标。

供应商延误需要定义标签，例如：

```text
label = 1
当订单实际交付时间 > 承诺交付时间 + 3 天
```

还必须明确：

- 预测时点是什么；
- 预测窗口是 3 天、7 天还是 30 天；
- 只预测未交付订单，还是所有订单；
- 取消订单、部分交付、人工改期如何标记；
- 结果何时才算已知；
- 延误概率与成本如何关联。

### 3.3 只有结果，没有先行信号

“订单已经延误”是结果，不是可用于提前预警的特征。

可能的先行信号包括：

- 供应商历史准时率和波动率；
- 承诺日期变更次数；
- 订单确认延迟；
- 发货通知延迟；
- 运输节点停滞时间；
- 质检不合格率；
- 供应商所在地区天气/港口/罢工事件；
- 同类产品的历史缺料率；
- 当前产能、库存和在途数量；
- 采购人员最近的人工备注或异常说明。

这些信号需要在数据产品层中形成稳定、带时间截面的特征，而不是在前端临时拼接。

### 3.4 只有关联关系，没有可计算特征

`Supplier -> supplies -> Order` 是语义关系，但模型需要可计算的特征，例如：

```text
supplier_on_time_rate_90d
supplier_delay_mean_180d
supplier_delay_p95_180d
order_confirmation_lag_hours
days_to_promised_delivery
shipment_last_event_age_hours
supplier_open_order_count
supplier_capacity_utilization
```

Ontology 可以承载这些属性，但必须由数据管道或函数按明确逻辑计算出来。

### 3.5 没有模型生命周期

预测能力不是“把模型文件挂在 Supplier 对象上”。至少需要：

```text
训练数据
→ 时间切分
→ 特征生成
→ 模型提交
→ 离线评估
→ 业务切片评估
→ 发布
→ 批量/实时部署
→ 线上监控
→ 重新训练
```

Foundry 的 Modeling Objective、模型提交、评估、发布和部署正是为此设计的。[模型目标](https://www.palantir.com/docs/zh/foundry/model-integration/objectives)

### 3.6 没有把概率转成决策阈值

模型输出 `0.72` 还不是业务动作。必须结合：

- 延误损失；
- 误报成本；
- 漏报成本；
- 供应商切换成本；
- 加急运输成本；
- 库存缓冲成本；
- 用户处理能力；
- 客户服务等级。

例如，当延误概率超过 0.6 时告警，不一定正确。对于高价值订单，可能 0.25 就需要人工审查；对于低价值订单，可能 0.85 才值得干预。

### 3.7 没有动作与反馈

如果用户只能看到“高风险”，不能：

- 重新分配订单；
- 发起供应商确认；
- 加急运输；
- 调整安全库存；
- 记录人工判断；
- 关闭或升级告警；

那么系统只是分析看板，不是运营系统。

更重要的是，用户的判断和最终结果必须写回数据层，否则系统不会获得新的标签和反馈。

### 3.8 没有评估“预测是否带来业务收益”

预测模型不仅要测 AUC、F1 或 MAE，还要测：

- 提前预警时间；
- 真实延误捕获率；
- 每百个订单的告警数量；
- 告警采纳率；
- 人工确认耗时；
- 避免的延误损失；
- 加急成本；
- 误报造成的操作浪费。

## 4. 供应商延误预警的完整工程

### 4.1 先定义预测契约

```text
预测对象：未完成的订单
预测时点：每天 06:00 和订单状态发生变化时
预测窗口：未来 7 天
预测结果：延误超过 3 天的概率
标签形成：实际收货时间相对承诺收货时间
业务动作：调查、加急、改派、调整库存、升级
评价指标：召回率、提前量、单位告警成本、避免损失
```

### 4.2 设计对象

```text
Supplier
Contract
PurchaseOrder
PurchaseOrderLine
Shipment
Receipt
SupplierEvent
DelayRisk
MitigationAction
```

### 4.3 设计时间化数据产品

至少生成四类数据集：

1. `order_event_history`：订单状态、承诺日期、变更和观察时间。
2. `shipment_event_history`：发货、运输、到港、清关、签收事件。
3. `supplier_performance_history`：供应商按时间窗口聚合的表现。
4. `delay_training_examples`：在每个预测时点生成特征快照和未来结果标签。

训练样本的关键形式是：

```text
(entity_id, as_of_time, feature_snapshot, label_at_future_horizon)
```

### 4.4 训练和评估

不能随机打乱全部历史数据后切分训练集和测试集。应按时间切分，避免未来分布泄漏。

至少做以下切片：

- 供应商类型；
- 地区；
- 产品类别；
- 订单价值；
- 运输方式；
- 新供应商/老供应商；
- 旺季/淡季；
- 数据完整/数据缺失。

### 4.5 将模型接入 Ontology

模型输出可以映射为：

```text
PurchaseOrder.delay_probability
PurchaseOrder.expected_delay_days
PurchaseOrder.risk_level
DelayRisk.reason_codes
DelayRisk.evidence_links
```

随后通过 Function、Action 或 Automate 生成和处理 `DelayRisk`。

### 4.6 进入用户工作流

```text
风险订单收件箱
→ 查看订单、供应商、运输和证据
→ AI 解释风险来源
→ 推荐加急/改派/库存动作
→ 用户批准或拒绝
→ 写回动作和理由
→ 记录最终交付结果
```

### 4.7 建立反馈闭环

最终结果用于：

- 更新模型标签；
- 评估预测是否提前且准确；
- 分析哪类告警没有被采纳；
- 分析人工覆盖原因；
- 调整告警阈值和动作策略；
- 判断模型是否值得继续自动化。

## 5. AI FDE 的开放性与替代方案

### 5.1 AI FDE 是否开源？

截至 2026-08-10，Palantir 官方公开的是 AI FDE 的产品文档和平台能力说明，没有提供 AI FDE 的源代码仓库或可自托管发行版。因此，更准确的表述是：

> AI FDE 是 Palantir Foundry/AIP 内的闭源平台能力；公开文档无法证明其内部实现开源。

官方文档显示，AI FDE 需要在 Foundry 中启用 AIP，推荐启用 Global Branching，并通过权限、上下文、工具、分支、预览和 CI 完成闭环。[AI FDE 官方文档](https://www.palantir.com/docs/foundry/ai-fde/overview)

### 5.2 AI FDE 的能力拆解

AI FDE 并不是一个普通聊天机器人，而是以下组件的组合：

```text
LLM
+ Foundry 专用工具
+ Foundry 上下文管理
+ 权限和身份
+ 数据/代码/Ontology API
+ 分支和 PR
+ 构建、预览、CI
+ 结果反馈循环
+ 审计记录
```

### 5.3 可替代的开源组合

没有一个开源项目能完整复制 AI FDE，因为 AI FDE 的壁垒来自它和 Foundry 数据、Ontology、权限及开发工具的深度集成。

可以自己组合：

| AI FDE 能力 | 开源/公开替代组合 |
|---|---|
| Agent 编排 | OpenAI Agents SDK、LangGraph、PydanticAI |
| 工具协议 | MCP、函数工具、内部 REST/gRPC API |
| Ontology API | 自建类型系统、GraphQL、REST、SQL/Cypher、OSDK 风格 SDK |
| 数据管道操作 | Git、dbt、Dagster/Airflow、Python、Spark、Great Expectations |
| 分支和审查 | Git branch、Pull Request、CI/CD |
| 文档抽取 | OCR、布局 OCR、VLM、结构化 JSON schema、人工复核 |
| 观测与评估 | OpenTelemetry、Langfuse、Phoenix、Promptfoo、自建评估集 |
| 权限 | OIDC/SAML、RBAC/ABAC、行列权限、策略引擎 |

OpenAI Agents SDK 提供 Agent、工具、guardrails、handoff 和 session 等编排能力；LangGraph 更适合有状态、长流程、检查点和多角色图；PydanticAI 更适合类型安全、结构化输出和工具约束。[OpenAI Agents SDK](https://github.com/openai/openai-agents-js) [LangGraph](https://reference.langchain.com/python/langgraph/overview) [PydanticAI](https://pydantic.dev/docs/ai/core-concepts/agent/)

推荐不要寻找“开源 Palantir”，而是复刻 AI FDE 的工程结构：

```text
受控上下文
→ 受限工具
→ 读取/写入业务 API
→ 分支执行
→ 测试/预览/CI
→ 人工审查
→ 合并和发布
```

## 6. 设计审查清单

| 质疑问题 | 检测方法 | 合格标准 |
|---|---|---|
| Ontology 是否只是当前状态镜像？ | 检查是否存在历史事件、时间快照和状态变迁 | 可回答某个过去时点看到了什么 |
| 是否有明确预测标签？ | 查看标签定义、形成时间、缺失和取消规则 | 标签有业务定义且可重复生成 |
| 是否存在未来信息泄漏？ | 用 `as_of_time` 重建训练样本 | 特征只能来自预测时点之前 |
| 关系是否转成特征？ | 检查管道和模型输入 | 关键关系能产生可计算特征 |
| 预测是否能改变业务？ | 跟踪预测输出是否连接 Action | 预测有阈值、动作和人工处理路径 |
| 模型是否可运营？ | 查找评估、发布、部署、监控和回滚 | 具备完整模型生命周期 |
| 是否形成反馈？ | 检查动作结果和后续标签 | 用户决策和真实结果可回写 |
| AI 是否获得过宽权限？ | 审查工具清单、上下文和角色 | 最小权限、动作白名单、可审计 |
