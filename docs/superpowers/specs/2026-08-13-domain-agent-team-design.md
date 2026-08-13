# 领域 Agent 团队设计

状态：设计稿，待评审
适用阶段：证据驱动 Ontology Builder 之后
上游：已批准的 Ontology、数据产品、证据索引、权限策略
下游：分析/预测/决策模型、业务应用、受控 Action 和反馈运营
核心原则：专业分工、Artifact 交接、独立挑战、确定性验证、人类批准

## 1. 文档目的

本文定义“领域 Agent 团队”阶段如何把多个专业 Agent 组织成一个可审计、可复现、可恢复的工程团队。

本阶段不是简单部署多个聊天机器人，而是建立：

> 面向一个业务领域的 Agent 工程组织：每个 Agent 拥有明确职责、输入输出契约、工具权限和质量标准，通过共享 Artifact Workspace 协作，由 Gate Engine 控制阶段晋级，由人类承担业务和发布责任。

本阶段默认消费《证据驱动的 Ontology Builder》发布的：

- OntologyReleasePackage；
- DataProductRelease；
- EvidenceIndex；
- AccessPolicy；
- ProvenanceGraph；
- GateRun 和 Approval。

如果上游 Ontology 仍处于候选状态，领域 Agent 只能提出设计建议，不得使用其结果驱动生产预测或 Action。

## 2. 能力目标与边界

### 2.1 本阶段要达到的能力

系统应能让多个领域 Agent 协作完成：

1. 从业务决策问题创建任务契约；
2. 读取已授权的证据、Ontology 和数据产品；
3. 将复杂目标拆为有依赖关系的专业任务；
4. 调度不同 Agent 生成结构化工程 Artifact；
5. 让 Agent 之间通过明确接口交接，而不是通过隐式聊天记忆协作；
6. 让 Challenger 独立寻找证据缺失、语义错误、数据泄漏和流程风险；
7. 让 Deterministic Verifier 运行代码、规则、SHACL、质量和回放测试；
8. 在输入、提示、工具、模型和配置变化时重新验证；
9. 对冲突、失败、超时和低置信结果进行升级；
10. 让 Domain Owner 审核业务含义，让 Release Owner 批准发布；
11. 将已批准产物交给应用和 Action 层；
12. 将实际结果和用户反馈回写为后续评估输入。

### 2.2 Agent 不能拥有的权力

任何 Agent 默认不能：

- 自行批准自己的产物；
- 绕过 Gate Engine 改变阶段状态；
- 修改原始证据；
- 直接覆盖已发布 Ontology；
- 删除冲突、失败和反馈记录；
- 将推断写成事实；
- 直接执行生产 Action；
- 通过伪造上下文获得更高权限；
- 通过拆分任务绕过人工批准。

## 3. Agent 团队角色

### 3.1 Orchestrator Agent

职责：

- 接收业务目标；
- 识别当前生命周期阶段；
- 创建 TaskContract；
- 分解任务和依赖；
- 调度专业 Agent；
- 汇总 GateRun；
- 处理重试、暂停和升级；
- 不生产业务结论，不拥有发布权限。

### 3.2 Decision Analyst Agent

职责：

- 澄清要解决的业务决策；
- 定义用户、触发条件、输入、决策、动作和结果；
- 区分目标、约束、指标和不可接受结果；
- 生成 DecisionContract；
- 标记未解决问题和需要访谈的对象。

### 3.3 Workflow Analyst Agent

职责：

- 还原真实工作流；
- 识别正常路径、异常路径、绕过路径和人工判断；
- 建立角色、事件、状态和动作顺序；
- 发现制度流程与实际流程的差异；
- 生成 WorkflowObservation 和 ExceptionPath。

### 3.4 Ontology Engineer Agent

职责：

- 消费已发布 Ontology 和上游语义候选；
- 提议类、属性、关系、状态和事件变化；
- 建立预测、决策和 Action 与业务对象的连接；
- 生成 Ontology Diff、SHACL Diff 和影响分析；
- 不直接发布 Ontology。

### 3.5 Data Product Engineer Agent

职责：

- 选择或创建数据产品；
- 生成映射、粒度、质量规则和时间语义；
- 检查主键、外键、延迟、空值、重复和状态重建；
- 生成数据产品版本和运行报告；
- 不绕过数据质量门禁。

### 3.6 Feature and Model Engineer Agent

职责：

- 定义标签、特征和观察时点；
- 检查数据泄漏；
- 建立基线和候选模型；
- 执行时间切分、回放、校准和分组评估；
- 生成 ModelEvaluation 和 PredictionArtifact；
- 模型不满足策略时自动回退到基线或阻断。

### 3.7 Decision and Optimization Agent

职责：

- 把业务目标、预测和约束编译为 DecisionProblem；
- 生成多个候选方案；
- 检查硬约束和软约束；
- 解释目标贡献、资源变化、风险和假设；
- 不把不可行方案伪装成推荐方案。

### 3.8 Application Agent

职责：

- 将已批准的对象、预测和方案嵌入用户工作流；
- 生成 API、视图、审批面板和解释组件；
- 确保业务用户能看到证据、门禁和不确定性；
- 不在 UI 层绕过后端权限和 Action Broker。

### 3.9 Challenger Agent

职责：

- 使用独立上下文和工具读取输入；
- 检查每条关键声明的证据；
- 检查反例、异常、冲突、泄漏、权限和失败路径；
- 检查 Agent 是否满足 TaskContract；
- 生成 ChallengeReport 和修复任务。

Challenger 不应复用 Builder 的隐藏中间状态作为唯一检查依据。

### 3.10 Deterministic Verifier

职责：

- 执行代码、SQL、SHACL、数据质量、回放和权限测试；
- 计算输入、配置、Artifact 和证据哈希；
- 返回机器可判定的 ValidationResult；
- 不通过自然语言“解释”替代测试。

### 3.11 Domain Owner

职责：

- 确认业务定义、状态、规则、指标和异常路径；
- 审核关键 Ontology 和决策语义；
- 处理跨部门定义冲突；
- 对业务可接受性负责。

### 3.12 Release Owner

职责：

- 审核发布范围、权限、回滚和监控；
- 确认所有硬门禁通过；
- 批准进入发布候选和生产；
- 对生产 Action 的授权边界负责。

## 4. 共享 Artifact Workspace

### 4.1 设计原则

Agent 之间不共享不可见的聊天上下文作为事实来源，而共享版本化工作空间。

~~~mermaid
flowchart LR
    A["TaskContract"] --> B["Artifact Workspace"]
    B --> C["Builder Agent"]
    C --> D["Draft Artifact"]
    D --> E["Challenger Agent"]
    D --> F["Deterministic Verifier"]
    E --> G["ChallengeReport"]
    F --> H["ValidationResult"]
    G --> I["Remediation Task"]
    H --> J["GateRun"]
    I --> C
    J --> K["Domain Review"]
    K --> L["Release Candidate"]
    L --> M["Release Owner"]
    M --> N["Published Artifact"]
~~~

### 4.2 Workspace 必须支持

- Artifact 版本；
- 内容哈希；
- 输入依赖；
- 证据引用；
- Diff；
- 状态；
- owner；
- GateRun；
- ChallengeReport；
- ValidationResult；
- Approval；
- Feedback；
- 锁和并发控制；
- 回滚；
- 失效传播。

### 4.3 只读事实与可变候选分离

~~~text
Raw Evidence                  不可变
Published Ontology             受控版本
Draft Ontology                 可创建新版本，不可覆盖发布版
Model Evaluation               不可篡改
Prediction                     按快照生成
Candidate Plan                 可比较、可拒绝
Action Request                 只允许经审批提交
Feedback                       追加写入
~~~

## 5. 任务契约

每个 Agent 任务必须使用结构化 TaskContract：

~~~yaml
task_id: supplier-delay-feature-design-001
objective: Define point-in-time features for supplier delay prediction
stage_id: model.training
actor_role: feature-model-engineer
allowed_evidence:
  - evidence-snapshot-2026-08-13
  - ontology-release-supplier-1.2.0
  - data-product-po-line-3.1.0
required_input_artifacts:
  - ontology-release-supplier-1.2.0
  - data-product-po-line-3.1.0
required_output_kinds:
  - FeatureCatalog
  - LeakageReport
forbidden_assumptions:
  - actual receipt date is available before observation time
acceptance_tests:
  - every feature has grain, window, lag, lineage, and version
  - no future-derived field enters the feature frame
  - labels are constructed from future outcomes only
escalation_conditions:
  - source date semantics conflict
  - no sufficient label history
  - permission policy cannot be propagated
budget:
  max_model_calls: 20
  max_wall_time_minutes: 30
~~~

任务契约的作用是把 Agent 的自由生成变成受约束的工程任务。

## 6. Agent 交接协议

### 6.1 标准交接结构

每个 Agent 必须返回：

~~~text
task_id
status
input_artifact_refs
output_artifact_refs
evidence_refs
claims
assumptions
open_questions
warnings
validation_requests
recommended_next_tasks
model_id
prompt_version
tool_call_refs
cost_and_latency
~~~

### 6.2 交接规则

- 下游只能读取 TaskContract 授权的输入；
- 下游不能依赖未登记的聊天上下文；
- 缺少必需 Artifact 时任务进入 blocked；
- 输出必须满足 schema；
- 每条关键 Claim 必须有 EvidenceRef 或明确标为推断；
- 变更必须通过新 Artifact 和 Diff；
- Agent 不能直接把 draft 标记为 approved。

## 7. 编排运行时

### 7.1 状态机

~~~text
CREATED
  ↓
PLANNED
  ↓
RUNNING
  ↓
WAITING_FOR_INPUT
  ↓
CHALLENGING
  ↓
VALIDATING
  ↓
DOMAIN_REVIEW
  ↓
APPROVED
  ↓
RELEASE_CANDIDATE
  ↓
RELEASED
~~~

失败路径：

~~~text
RUNNING / CHALLENGING / VALIDATING
  → REMEDIATION
  → RETRY
  → BLOCKED
~~~

### 7.2 调度策略

Orchestrator 必须依据以下条件调度：

- 阶段；
- 依赖是否满足；
- 输入 Artifact 版本；
- Agent 能力标签；
- 工具权限；
- 数据敏感级别；
- 成本预算；
- 延迟预算；
- 是否需要人工；
- 是否存在同一 Artifact 锁。

不能仅根据自然语言相似度选择 Agent。

### 7.3 并发与锁

同一 Artifact 的写入必须具备：

- 版本乐观锁；
- 父版本 hash；
- 变更范围；
- 冲突检测；
- 合并或人工仲裁策略。

不同 Artifact 的独立任务可以并发，但存在语义依赖的任务必须按 DAG 顺序执行。

## 8. 质量控制与门禁

### 8.1 Agent 自检不是质量门禁

Agent 的自评只能作为输入，不能作为最终通过条件。正式门禁必须由独立 Challenger、Verifier 或人执行。

### 8.2 通用 Agent 门禁

| 门禁 | 检查内容 | 责任组件 |
|---|---|---|
| contract.compliance | 输出是否满足任务契约 | Deterministic Verifier |
| evidence.coverage | Claim 是否有授权证据 | Challenger |
| artifact.schema | 输出结构和字段是否合法 | Schema Validator |
| semantic.integrity | 语义是否符合 Ontology | SHACL/Semantic Validator |
| data.quality | 数据产品质量和粒度 | Data Validator |
| temporal.safety | 时间边界和泄漏 | Temporal Validator |
| adversarial.challenge | 异常、反例、冲突和绕过路径 | Challenger |
| business.acceptance | 业务语义和实际可用性 | Domain Owner |
| release.governance | 版本、权限、回滚、监控 | Release Owner |

### 8.3 Agent 输出质量评分

评分只能用于路由、排名和运营，不能替代硬门禁。建议记录：

- 证据覆盖率；
- 任务契约满足率；
- 确定性测试通过率；
- Challenger 发现率；
- 重试率；
- 人工修改率；
- 采纳率；
- 事实错误率；
- 平均成本和延迟；
- 业务结果贡献。

## 9. 领域 Agent 的真实协作流程

### 9.1 场景：供应商延误预测

#### 第一步：业务目标进入团队

用户提出：

> 找出未来 14 天可能延误的供应商订单，并推荐催交、替代供应商或调整生产计划的方案。

Orchestrator 创建：

- DecisionContract；
- UseCase；
- TaskGraph；
- 风险等级；
- 所需输入和验收标准。

#### 第二步：Decision Analyst 明确决策

定义：

~~~text
用户：采购经理、计划经理
触发：订单进入未来 14 天交付窗口
输入：订单、供应商、承诺日期、物流事件、产能影响
预测：订单延误概率和预期延误天数
动作：催交、替代供应商、调整生产计划、升级处理
目标：减少生产中断和加急成本
~~~

#### 第三步：Workflow Analyst 观察真实路径

不仅记录系统流程，还记录：

- 采购员如何处理延期邮件；
- 哪些订单会被人工标记为“重点关注”；
- 供应商承诺变化后谁修改日期；
- 哪些异常会绕过系统；
- 哪些情况下采购经理不会执行模型建议。

输出进入 WorkflowObservation 和 ExceptionPath。

#### 第四步：Ontology Engineer 评估模型变化

确认已有 Ontology 是否包含：

~~~text
Supplier
PurchaseOrder
PurchaseOrderLine
Shipment
DeliveryEvent
SupplierCommunicationEvent
ProductionOrder
AlternativeSupplier
~~~

若缺少 SupplierCommunicationEvent，Ontology Agent 只能提出 Diff，不能直接发布。

#### 第五步：Data Product Engineer 建立数据产品

生成：

- purchase_order_line_product；
- supplier_delivery_event_product；
- supplier_communication_product；
- production_impact_product。

验证：

- 订单行主键；
- 供应商身份；
- 承诺日期语义；
- 事件时间和可用时间；
- 数据延迟；
- 重复和撤销；
- 权限传播。

#### 第六步：Feature/Model Engineer 构建预测

特征示例：

- 供应商过去 90 天延误率；
- 当前订单承诺日期变化次数；
- 物流事件停滞时长；
- 供应商未完成订单数量；
- 订单行关键物料等级；
- 可替代供应商数量；
- 生产订单受影响程度。

模型 Agent 必须同时产出：

- FeatureCatalog；
- LabelDefinition；
- LeakageReport；
- BaselineEvaluation；
- ModelEvaluation；
- PredictionArtifact。

#### 第七步：Decision Agent 生成方案

候选方案：

1. 发送催交；
2. 提升催交等级；
3. 切换替代供应商；
4. 调整生产顺序；
5. 接受风险并继续观察。

每个方案必须计算：

- 预计交付影响；
- 额外成本；
- 供应商和生产约束；
- 权限和审批要求；
- 方案可行性；
- 解释和证据。

#### 第八步：Challenger 独立挑战

Challenger 重点检查：

- 是否使用了实际到货日期等未来字段；
- 是否把“预计到货”当成事实；
- 是否把运输延误归因给供应商；
- 是否遗漏被人工关闭的订单；
- 是否对新供应商产生错误高风险；
- 是否把不可替代订单推荐为可替代；
- 是否让某采购角色看到越权信息。

#### 第九步：人类审核和应用交付

采购负责人审核：

- 供应商身份和延误定义；
- 风险解释；
- 方案成本；
- 例外路径；
- 是否愿意在日常工作中使用该建议。

Application Agent 将结果嵌入采购工作台，而不是单独提供聊天窗口。

#### 第十步：Action 和反馈

用户选择“发起催交”后：

~~~text
用户选择方案
→ ActionRequest
→ 权限和审批
→ Action Broker
→ 外部回执
→ ActionOutcome
→ Feedback
→ 真实到货结果
→ 模型评估
~~~

没有审批时，Agent 只能创建待处理请求，不能执行生产写入。

## 10. 失败、重试和升级

### 10.1 可自动重试

- 网络临时失败；
- 解析服务超时；
- 无状态工具调用失败；
- 确定性任务的瞬时资源不足。

重试必须记录：

- 原始 call；
- 重试次数；
- 输入 hash；
- 工具版本；
- 错误类型；
- 最终结果。

### 10.2 不应自动重试

- 业务语义冲突；
- 权限拒绝；
- 高风险实体合并不确定；
- 证据不足；
- 预测标签不存在；
- 方案不可行；
- 人工拒绝；
- 发布门禁失败。

这些情况必须创建 RemediationTask 或 HumanReviewTask。

### 10.3 升级条件

以下条件应自动升级：

- 同一问题两次修复仍失败；
- 两个 Agent 的关键结论冲突；
- 关键字段无权威来源；
- 影响生产 Action；
- 预测置信度低于阈值；
- 新版本会改变已发布对象语义；
- 权限策略无法判断；
- 业务目标之间没有可行解。

## 11. 成本、延迟和模型路由

Agent 团队不是无限调用模型。运行时必须管理：

- 每任务模型调用预算；
- Token 和费用；
- 最大墙钟时间；
- 并发数；
- 上下文长度；
- 失败重试预算；
- 结果缓存；
- 低风险任务的小模型路由；
- 高影响语义任务的强模型路由；
- 需要人工的任务及时暂停。

建议路由：

| 任务 | 默认路由 |
|---|---|
| 文档分类、简单字段抽取 | 小模型/规则 |
| 术语和实体候选 | 中等模型 + 确定性匹配 |
| 复杂语义冲突 | 强模型 + 人工审核 |
| 结构化映射生成 | 强模型生成 + 编译器验证 |
| 数据质量和泄漏 | 确定性执行 |
| 方案优化 | Solver/规则引擎 |
| 生产 Action | Policy + 人工审批 |

## 12. 安全与权限

Agent 权限必须由平台根据可信身份和任务上下文签发，不能相信 Agent 自己提交的：

- actor；
- role；
- project；
- stage；
- approval；
- capability。

工具分级：

| 能力 | 默认角色 |
|---|---|
| Read | 所有受授权 Agent |
| Propose | Builder 和专业 Agent |
| Validate | Challenger、Verifier |
| Approve | Domain Owner |
| Execute | Release Owner，且必须有保护性批准记录 |

所有工具调用必须记录：

- call_id；
- actor；
- project；
- stage；
- tool；
- 输入哈希；
- 输出 Artifact；
- PolicyDecision；
- 开始和结束时间；
- 错误和重试。

## 13. 生产运行监控

必须监控四类指标：

### 13.1 工程健康

- 任务成功率；
- 门禁失败率；
- 重试率；
- 平均等待时间；
- Artifact 冲突率；
- 队列积压；
- 连接器失败率。

### 13.2 Agent 质量

- 证据覆盖率；
- 错误 Claim 数；
- Challenger 发现率；
- 人工修改率；
- 任务重开率；
- 采纳率；
- Agent 间冲突率。

### 13.3 模型和决策

- 基线和模型 MAE；
- 校准；
- 分组公平性；
- 数据漂移；
- 特征缺失率；
- 推荐采纳率；
- 方案实际结果差异。

### 13.4 业务结果

- 延误减少；
- 成本变化；
- 人工处理时间；
- 例外处理率；
- 用户工作流覆盖率；
- Action 成功率；
- 误报和漏报造成的损失。

## 14. 实施路线

### P1：单领域、单任务图

必要功能：

- TaskContract；
- Artifact Workspace；
- Orchestrator；
- 一个 Builder；
- 一个 Challenger；
- Deterministic Verifier；
- Gate Engine 交接；
- 人工 ReviewTask。

验收：可完成一个需求变更或供应商延误用例，所有中间产物可追踪。

### P2：专业 Agent 分工

必要功能：

- Decision Analyst；
- Workflow Analyst；
- Ontology Engineer；
- Data Product Engineer；
- Model Engineer；
- Decision Agent；
- 标准交接协议；
- 依赖 DAG；
- 重试、阻断、升级。

验收：Agent 不依赖聊天隐式记忆，换一个 Agent 实例仍能从 Workspace 继续工作。

### P3：并发、冲突和成本控制

必要功能：

- Artifact 乐观锁；
- 并发任务；
- 冲突仲裁；
- 模型路由；
- 调用预算；
- 缓存；
- 运行追踪；
- 失败恢复。

验收：同时处理多个独立子任务时，结果不互相覆盖；预算耗尽会安全暂停。

### P4：生产领域团队

必要功能：

- 多租户；
- 长期领域记忆；
- 真实连接器；
- 真实 Action；
- 生产监控；
- 模型和 Ontology 演进；
- 业务结果评估；
- 回滚和事故处理。

验收：可以在真实业务系统中持续运行，且任何结果和动作均能回溯到证据、模型、策略和批准人。

## 15. 设计验收清单

| 验收问题 | 检测方法 | 通过标准 |
|---|---|---|
| Agent 是否只能使用授权输入？ | 给 Agent 注入未授权证据并检查工具调用 | 访问被拒绝并留下审计 |
| Agent 能否绕过 Gate Engine？ | 直接提交 approved/released 状态 | 状态变更被阻断 |
| Builder 能否批准自己？ | 用 Builder 身份执行审批 | 被拒绝 |
| Agent 之间是否依赖隐式上下文？ | 清空聊天历史，仅保留 Workspace | 任务仍可继续 |
| 关键 Claim 是否有证据？ | 随机检查输出 Claim | 无证据只能标为假设或阻断 |
| Challenger 是否独立？ | 使用不同上下文和工具重跑 | 能发现 Builder 未声明的问题 |
| 数据变化是否会使旧结果失效？ | 修改输入 Artifact 或证据快照 | 相关 GateRun 和下游结果标记 stale |
| 任务失败是否会安全停机？ | 模拟权限、超时、冲突和预算耗尽 | 进入 remediation/blocked，不静默成功 |
| 多 Agent 并发是否安全？ | 让两个 Agent 修改同一 Artifact | 冲突被检测，不丢失变更 |
| 生产 Action 是否受保护？ | 无批准执行 Action | 被拒绝；有批准才允许执行 |
| 反馈是否进入评估？ | 执行 Action 并回写真实结果 | 可关联到原预测和方案 |
| 是否能解释选择的方案？ | 查看 CandidatePlan | 有目标、约束、证据、假设和差异 |

## 16. 与证据驱动 Ontology Builder 的衔接

本阶段不重复实现证据抽取和基础 Ontology 编译，而是消费其发布包：

~~~text
Evidence-driven Ontology Builder
    ↓ OntologyReleasePackage
    ↓ DataProductRelease
    ↓ EvidenceIndex / AccessPolicy / ProvenanceGraph
Domain Agent Team
    ↓ Feature / Model / Decision / Application Artifacts
    ↓ GateRun / Approval
    ↓ Release / Action / Feedback
~~~

衔接规则：

1. Agent 只能读取已批准版本，不能读取未授权草稿；
2. Ontology 变化必须通过新版本和影响分析；
3. Agent 产物必须引用 Ontology 和数据产品版本；
4. 上游版本失效时，下游模型、方案和应用门禁必须重新验证；
5. Agent 团队不能自行修复上游语义后直接发布；
6. 语义问题回流 Ontology Builder，业务问题升级 Domain Owner。

## 17. 与当前 AI-FDE 原型的关系

当前原型已经提供：

- TaskContract、AgentContext、AgentProposal 和 ChallengeReport；
- FakeBuilder、FakeChallenger 的权限化工具调用；
- Artifact、GateRun、StageRun 和状态机；
- Action Broker、审批和幂等；
- Feedback 追加记录；
- 端到端门禁测试。

仍需新增：

- 真实 LLM Agent Provider；
- 专业 Agent 实现；
- Artifact Workspace 的持久化交接和锁；
- Orchestrator DAG 和任务队列；
- Agent 能力注册和模型路由；
- Challenger/Verifier 独立运行环境；
- 多 Agent 冲突仲裁；
- 运行成本和质量评估；
- 领域长期记忆；
- 生产连接器和 Action 适配器。

## 18. 设计结论

领域 Agent 团队的核心不是 Agent 数量，而是四个约束同时成立：

~~~text
专业分工
× Artifact 交接
× 独立验证
× 人类负责制
~~~

缺少任意一个条件，系统都容易退化为：

- 多个 Agent 互相转述；
- 没有证据的语义拼接；
- 共享错误结论；
- 无法定位责任；
- 无法回滚；
- 无法安全执行。

因此，领域 Agent 团队必须建立在证据驱动 Ontology Builder 之上，并以 Gate Engine、Artifact Workspace 和真实反馈作为运行闭环。
