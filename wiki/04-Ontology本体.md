# Ontology 本体：从数据层到可操作的数字孪生

## 1. Ontology 的真正含义

Ontology 是企业运营世界的语义和执行层，不是简单的数据字典，也不是把数据库表换成圆圈。它把数据源和模型映射为对象类型、属性、链接、对象集、动作和函数，并把安全策略、业务规则和应用工作流连接起来。

一个有用的类比是：

| 传统数据概念 | Ontology 概念 | 工程意义 |
|---|---|---|
| Dataset | Object type | 对数据资产的业务语义封装 |
| Row | Object | 某个真实实体/事件的实例 |
| Column | Property | 可解释的对象属性 |
| Join | Link type | 具名、可导航、有基数的业务关系 |
| Query result | Object set | 静态或动态的对象集合 |
| Update statement | Action type | 受权限、规则和审计控制的业务事务 |
| Server-side code | Function | 可从对象上下文读、计算、调用和编辑 |

## 2. 建模步骤

### 2.1 先识别核心对象

核心对象对应源系统中稳定、可追溯的业务实体或事件，例如飞机、订单、生产线、航班、员工、告警。为每个对象确定主键、来源粒度、生命周期和权限边界。

### 2.2 再识别派生对象

派生对象由多个核心对象或数据资产计算得到，例如航线、风险事件、供应缺口、客户旅程。派生对象应有明确的构造逻辑和刷新策略，避免让每个应用都重复计算。

### 2.3 识别用例编辑对象

用例编辑对象承载运营过程中产生的事实，例如工单、评论、分派、审批、附件、计划和人工标注。它们是闭环的关键：系统不只观察世界，也记录人和 AI 如何改变世界。

### 2.4 建立链接和基数

链接不是无名的 join，而是关系契约。说明关系的方向、名称、主键、基数、有效期、来源和权限，确保用户可以沿对象关系导航和执行工作流。

### 2.5 建立状态与动作

对象生命周期应显式表达，例如 `New -> Assigned -> In progress -> Resolved -> Escalated`。每个转移对应动作类型，并定义参数、前置条件、权限、对象编辑、通知、Webhook、撤销或取消策略。

## 3. Ontology 的“语义面”和“动力面”

- **语义面：**对象、属性、链接、对象集、共享属性、接口，回答“世界中有什么以及它们如何关联”。
- **动力面：**动作、函数、Logic、自动化、动态权限，回答“可以对世界做什么以及什么条件下可以做”。
- **治理面：**对象/属性级权限、标记、目的、审计和血缘，回答“谁可以看到、调用和改变什么”。

这三个面合在一起，才足以支撑人和 Agent 的可信决策。

## 4. 后端原理

Ontology 后端负责元数据、对象数据、对象集查询、搜索/聚合、动作写入、索引和用户编辑汇聚。对象后端把源数据与用户驱动的编辑合并到对象存储和索引中；动作服务负责条件、权限、日志和事务协调；数据漏斗保持批处理/流式数据和用户编辑的一致性。

Object Storage V2 将索引与查询分离以支持横向扩展，并支持增量索引、流式输入、较大规模批量编辑和更细粒度的对象/属性权限。工程上要理解：Ontology 不是只在应用查询时动态拼表，而是一个拥有查询、索引、编辑和权限服务的运营数据平面。

## 5. Ontology 设计验收

- 每个对象类型都能回答“它在业务世界中是什么”，而不是“它来自哪个表”。
- 核心对象、派生对象、编辑对象明确区分。
- 关系有名称、方向、基数和生命周期。
- 属性具有来源、刷新、计算、敏感级别和使用目的。
- 关键动作是统一契约，多个应用不会各自实现一份互相冲突的写逻辑。
- 对象、链接、动作、函数和 Agent 使用同一权限模型。
- 能把一个完整业务任务画成：对象 → 上下文 → 推荐/分析 → 动作 → 新事实。

## 6. 与 AI 的关系

LLM 本身只提供语言推理能力，Ontology 提供可检索的企业上下文、可调用的函数和工具、可执行的动作、可检查的权限和可记录的结果。AI 因此不是“在旁边聊天”，而是在同一受治理语义层上参与企业决策和行动。

## 7. 相关官方页面

- [Ontology 核心概念](https://www.palantir.com/docs/zh/foundry/ontology/core-concepts)
- [对象类型](https://www.palantir.com/docs/zh/foundry/ontology/object-types-overview)
- [链接类型](https://www.palantir.com/docs/zh/foundry/ontology/link-types-overview)
- [动作类型](https://www.palantir.com/docs/zh/foundry/ontology/action-types/overview)
- [Ontology 上的函数](https://www.palantir.com/docs/zh/foundry/ontology/functions/overview)
- [AIP Logic](https://www.palantir.com/docs/zh/foundry/ontology/logic/overview)
- [对象后端](https://www.palantir.com/docs/zh/foundry/ontology/object-backend/overview)
- [对象权限](https://www.palantir.com/docs/zh/foundry/ontology/object-permissioning/overview)
- [对象编辑](https://www.palantir.com/docs/zh/foundry/ontology/object-edits/overview)
