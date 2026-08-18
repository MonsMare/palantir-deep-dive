# Linear 驱动的人机-Agent 协作设计

状态：已批准，待实施

日期：2026-08-14

## 1. 文档定位

本文档定义 AI-FDE 如何使用 Linear 工单作为人机控制面，把人类的目标、业务语义、反馈和审批，转化为受治理的 Agent 执行任务，并将 Agent 的证据、工件、门禁和异常重新投影回 Linear。

本文档吸收 multi-agents-workbench 中已经验证的实践：

- [task] 工单筛选；
- 常驻 Bridge；
- 增量同步和 per-issue 错误隔离；
- 确定性 checks；
- 实现—评审—返工—批准闭环；
- 原子状态文件；
- 最大修复轮次；
- 失败评论和人工升级；
- 独立 Reviewer；
- 容器化 executor/reviewer。

但本项目采用一个更严格的系统边界：

> AI-FDE 内部生命周期、Gate、Artifact、Audit 和 Action Policy 是执行事实；Linear 是人类协作界面、外部事件入口和状态投影。

因此，Linear Bridge 不直接替代 DomainAgentTeam，也不能绕过内部门禁。

## 2. 目标与非目标

### 2.1 目标

- 让人类只通过 Linear 就能提交、补充、评审和关闭 AI-FDE 任务；
- 让一个工单具备明确目标、证据范围、产物、验收和审批责任；
- 让 Agent 团队按任务合同和类型化工件协作；
- 让每次执行可暂停、重试、返工、升级和恢复；
- 让需求变更、评审意见和人工反馈形成可追踪版本；
- 让 Fake Linear 和真实 Linear 共享同一套生命周期与测试；
- 让工单轨迹可以追溯到 Evidence、Artifact、Gate、Model、Action 和 Feedback。

### 2.2 非目标

- 不把 Linear 当作完整的 Ontology 或 Artifact 数据库；
- 不让 Agent 直接操作 Linear 状态；
- 不允许普通自然语言评论绕过审批；
- 不让多个 Agent 通过无结构聊天共享隐含状态；
- 不让 Agent 自主执行高风险生产 Action；
- 不让工单状态成为唯一的运行事实；
- 不承诺每个自由描述的需求都能自动建模。

## 3. 参与者和责任

| 参与者 | 责任 | 权限边界 |
|---|---|---|
| 业务发起人 | 说明目标、价值和范围 | 创建/修改任务合同 |
| 领域负责人 | 确认业务语义、例外和决策口径 | 批准领域工件 |
| 数据负责人 | 确认数据来源、访问和质量 | 授权证据范围 |
| 审批人 | 批准模型、决策或 Action | 触发高风险状态转移 |
| 运维负责人 | 处理超时、故障和升级 | 重开、暂停或终止任务 |
| Linear Adapter | 同步外部事件和评论 | 不能绕过内部 Gate |
| Lifecycle Controller | 管理内部状态和合法转移 | 唯一的机器状态机 |
| Agent Graph Planner | 选择领域 Agent 图 | 只能提交运行计划 |
| DomainAgentTeam | 生成类型化候选工件 | 不能直接发布或执行 Action |
| Challenger/Reviewer | 独立验证和提出问题 | 不能替代审批人 |

## 4. Task Contract

### 4.1 工单约定

一个受治理工单必须：

- 标题以 [task] 开始，或者被明确标记为 AI-FDE 类型；
- 包含可解析的 aifde.task.v1 区块；
- 指定 domain pack 和 task kind；
- 指定至少一个业务目标和一个验收标准；
- 指定 decision owner；
- 指定输入证据范围或明确声明需要先发现证据；
- 指定期望输出；
- 指定风险等级和人工检查点。

人类可读区块用于业务协作，规范区块用于系统解析。规范区块解析失败时，系统必须停在 needs_info。

### 4.2 推荐合同格式

~~~yaml
aifde_version: 1
task_id: linear:LAC-123
project_id: software-delivery-demo
domain_pack: software_delivery
task_kind: requirement_alignment_and_forecast
objective: 识别需求追加风险并预测当前版本工期
decision:
  owner: product-owner
  action: 是否拆分需求、调整范围或重新排期
scope:
  included: [requirements, work_items, dependencies, change_requests]
  excluded: [production_deployment]
inputs:
  evidence_refs: [requirements-export-v4, change-log-2026-08]
  allowed_sources: [jira-export, meeting-notes]
outputs:
  required: [WorkflowObservation, OntologyModel, DataProduct, ForecastReport]
acceptance:
  - 每个风险结论必须引用证据
  - 预测必须声明观察时点和时间窗口
  - 必须给出可执行的范围调整建议
governance:
  risk_tier: medium
  human_checkpoints: [ontology_boundary, forecast_release]
  max_fix_rounds: 3
  timeout_seconds: 3600
actions:
  allowed: [dry_run]
  production_requires_approval: true
~~~

### 4.3 合同版本

以下任一变化生成新版本：

- 目标、范围或决策定义改变；
- 输入证据集合改变；
- 输出类型改变；
- 验收标准改变；
- 风险等级或审批人改变。

活动中的 AgentRun 绑定一个固定 Contract 版本。新版本发布后，旧运行标记为 stale，不得继续提交结果。

## 5. 内部生命周期

内部状态比 Linear 更细，且由 Lifecycle Controller 唯一维护：

~~~mermaid
stateDiagram-v2
    [*] --> intake
    intake --> needs_info: contract_invalid
    intake --> ready: contract_valid
    needs_info --> intake: human_updates
    ready --> running: dispatch
    running --> checks_failed: executor_or_checks_fail
    running --> reviewing: implementation_done
    checks_failed --> ready: human_reopen
    reviewing --> fix_requested: major_or_blocker
    reviewing --> awaiting_human: gates_pass
    fix_requested --> running: redispatch
    awaiting_human --> approved: authorized_approval
    awaiting_human --> ready: human_revision
    approved --> action_pending: action_requested
    approved --> released: no_action
    action_pending --> released: action_reconciled
    action_pending --> awaiting_human: approval_required
    running --> stale: timeout_or_contract_change
    reviewing --> stale: timeout_or_contract_change
    stale --> ready: human_reopen
    intake --> canceled: human_cancel
    ready --> canceled: human_cancel
    running --> canceled: authorized_cancel
    released --> [*]
    canceled --> [*]
~~~

状态转移要求：

- 每次转移带 event_id、actor、run_id、contract_version 和前置状态；
- 非法转移被拒绝并写入审计；
- 状态写入和 Outbox 事件在同一事务中提交；
- Bridge 重试不能重复转移；
- 人类状态修改先进入 Inbox，经过冲突检查后才转换为内部命令。

## 6. Linear 状态映射

| Linear | 内部状态 | Linear 展示内容 |
|---|---|---|
| Backlog | intake、needs_info | 缺失字段、待补充问题 |
| Todo | ready | 合同通过、等待派发 |
| In Progress | running、fix_requested、checks_failed | 当前节点、进度、失败证据 |
| In Review | reviewing、awaiting_human、approved | Gate、评审、工件和审批项 |
| Done | released，且必须由授权人关闭 | 仅授权人可关闭 |
| Canceled | canceled | 取消原因和操作者 |

特殊规则：

- checks_failed 保持 In Progress，不能伪装成 In Review；
- Agent 不能移动到 Done；
- 人类提前移动到 Done 时，内部状态不自动变成 released；
- Bridge 发布冲突评论，要求授权人通过结构化命令确认；
- 内部状态和 Linear 状态不一致时，先以内部状态重建投影，不静默覆盖人工操作。

## 7. 人类交互协议

### 7.1 结构化命令

只有明确的命令评论才能改变生命周期：

~~~text
/aifde approve run=run-123 scope=ontology
/aifde approve run=run-123 scope=forecast
/aifde revise run=run-123 供应商分类需要增加战略供应商例外
/aifde pause run=run-123
/aifde reopen run=run-123
/aifde cancel run=run-123 reason="业务目标取消"
~~~

命令处理规则：

- 评论作者必须绑定到 Linear 身份和 AI-FDE Policy；
- approve 必须匹配合同中声明的审批角色；
- scope 必须对应待审批工件或 Gate；
- 旧 run、旧 contract 或已关闭任务的命令拒绝执行；
- 命令本身写入 linear_commands 和审计链；
- 命令失败时回写可读原因，不删除原评论。

### 7.2 自然语言反馈

普通评论不直接改变状态，保存为 HumanFeedback：

- 记录作者、时间、评论 ID 和关联 run；
- 通过 Feedback Interpreter 提取候选问题；
- 生成 FeedbackProposal；
- 只有人类确认后才能变成 Contract Patch 或 Fix Request；
- 不允许 Agent 自己把反馈解释为批准。

## 8. 评论和事件格式

评论需要同时满足人类可读和机器可解析：

~~~text
[aifde][agent:ontology-engineer][run:run-123]
event: artifact.proposed
status: pending_review
artifact_refs: ontology-model:v3
evidence_refs: evidence-17,evidence-22
gate_refs: gate-ontology-completeness

本轮产出了需求、工作项和变更请求之间的关系模型。
请领域负责人确认“需求追加”是否应作为独立事件类型。
~~~

发布者前缀：

- [aifde][system]：系统状态、故障、超时和升级；
- [aifde][agent:<role>]：Agent 进度和候选工件；
- [aifde][reviewer:<role>]：独立评审；
- [aifde][gate:<gate-id>]：门禁结果；
- [aifde][human]：人工命令或人工确认。

结构化事件字段：

~~~json
{
  "schema": "aifde.linear.comment.v1",
  "event_id": "linear-comment-event:uuid",
  "issue_id": "linear-issue-id",
  "identifier": "LAC-123",
  "run_id": "agent-run:uuid",
  "contract_version": 2,
  "producer": "ontology-engineer",
  "event_type": "artifact.proposed",
  "severity": "info",
  "artifact_refs": ["ontology-model:v3"],
  "evidence_refs": ["evidence-17", "evidence-22"],
  "gate_refs": ["gate-ontology-completeness"],
  "created_at": "2026-08-14T00:00:00Z"
}
~~~

Linear 评论不是唯一事实源。评论先进入 Inbox，解析、去重、持久化和生命周期处理成功后，再由 Outbox 投影状态和评论。

## 9. Agent 团队组织

Agent 不是平行聊天群，而是由领域任务图约束的候选工件生产者。

### 9.1 控制层

- TaskContractValidator：解析工单、检查目标、验收、角色和权限；
- DomainGraphPlanner：根据 domain pack 和 task kind 选择 AgentGraph；
- LifecycleController：管理状态，不由 LLM 决策；
- ReviewController：编排 checks、Challenger、Gate 和人工审批；
- ActionController：将批准的 ActionProposal 交给 Policy Gateway。

### 9.2 领域执行层

- DecisionAnalyst：明确高价值业务决策、输入、输出和动作；
- WorkflowAnalyst：从证据中提取实际工作流和例外；
- Evidence/Data Agent：发现、抽取、校验和治理数据；
- Ontology Engineer：提交对象、关系、状态、权限和语义约束；
- Data Product Engineer：提交时间、粒度、质量、血缘和可计算特征；
- Model Engineer：提交标签、模型、评估和漂移约束；
- Decision Agent：提交候选方案、约束、目标函数和敏感性分析；
- Challenger：独立读取允许的证据，检查支持关系、泄漏、缺失和验收；
- Release Agent：只做发布前清单，不直接发布高风险内容。

### 9.3 Agent 输出边界

每个 Agent 只能返回候选工件，必须包含：

- producer_role；
- kind；
- version；
- evidence_refs；
- claims；
- assumptions；
- acceptance_tests；
- open_questions；
- warnings；
- depends_on。

Agent 不能：

- 直接改 Linear 状态；
- 直接写生产数据库；
- 直接执行 Action；
- 将自身结果标记为已批准；
- 读取未授权证据；
- 删除上游工件或历史版本。

现有 DomainAgentTeam 继续负责 DAG、并行度、独立上下文、预算、stale 输入和 Workspace 提交。真实模型通过 ModelRouter 和 Provider Adapter 注入，模型型号不写死在生命周期逻辑中。

## 10. 端到端运行流程

### 10.1 任务进入

1. 人类在 Linear 创建 [task] 工单；
2. Real/Fake Adapter 收到 webhook 或轮询发现；
3. Inbox 按外部事件 ID 去重；
4. Contract Validator 解析任务；
5. 失败则评论缺口并进入 needs_info；
6. 成功则创建 Contract 版本和内部 Task；
7. Bridge 投影为 Todo 或保持 Backlog。

### 10.2 Agent 执行

1. Lifecycle Controller 将任务置为 ready；
2. Graph Planner 根据 domain pack 选择 AgentGraph；
3. 创建 AgentRun 和节点运行记录；
4. 通过 Redis Streams 派发；
5. Worker 获取租约；
6. DomainAgentTeam 执行节点；
7. 节点候选写入 Workspace；
8. 写入 Artifact、Evidence、日志和 Outbox；
9. 成功后 Bridge 评论当前节点和工件引用；
10. 失败则保持 In Progress 并写入失败证据。

### 10.3 评审与人工协作

1. 完成确定性 checks；
2. 独立 Challenger 读取原始证据和候选工件；
3. Gate Engine 执行结构、语义、数据和权限门禁；
4. 通过后内部进入 awaiting_human；
5. Linear 进入 In Review；
6. 人类查看工件、证据、Gate、评审和影响分析；
7. 人类批准、修改、暂停或重开；
8. major/blocker 生成 Fix Request；
9. 达到修复轮次上限、预算、超时或风险阈值时人工升级。

### 10.4 发布和反馈

1. 低风险无 Action 工件可在批准后进入 released；
2. 有 Action 的任务先进入 action_pending；
3. Policy Gateway 检查权限、审批和 dry-run；
4. Action Adapter 执行并返回 Receipt；
5. Reconciliation 校验外部结果；
6. 结果和反馈回写 Ontology/Artifact/Feedback；
7. Linear 只展示结果引用和下一步建议。

## 11. Adapter 接口

Real 和 Fake Adapter 必须共享下列抽象：

~~~text
list_events(cursor) -> LinearEventPage
get_issue(issue_id) -> LinearIssue
get_comments(issue_id) -> list[LinearComment]
create_issue(team_id, title, description) -> LinearIssueRef
post_comment(issue_id, body, idempotency_key) -> LinearCommentRef
transition_issue(issue_id, target_state, idempotency_key) -> LinearStateResult
archive_issue(issue_id, idempotency_key) -> ArchiveResult
~~~

Real Adapter 要求：

- GraphQL 分页；
- webhook 签名校验；
- 增量轮询补偿；
- 限流退避；
- 网络超时；
- 外部 ID 去重；
- 失败 Outbox 重试。

Fake Adapter 要求：

- 使用 PostgreSQL 或测试临时存储；
- 支持伪造 webhook、评论、状态变化和重复事件；
- 支持 Bridge 重启；
- 支持直接制造评审失败、人工反馈和冲突；
- 不依赖真实 Linear token。

Bridge、Lifecycle、Worker 和 Gate 不得通过 real/fake 分叉业务逻辑。

## 12. Inbox、Outbox 和幂等

### 12.1 Inbox

所有 Linear 外部事件先写入：

- provider；
- external_event_id；
- issue_id；
- received_at；
- payload_hash；
- payload；
- processing_status；
- error_code。

同一 external_event_id 只允许成功处理一次。

### 12.2 Outbox

所有内部状态变化、评论、Linear 状态投影和升级通知先写入 Outbox，再由 Bridge 投递。Outbox 事件包含：

- outbox_id；
- event_type；
- target；
- issue_id；
- run_id；
- payload；
- idempotency_key；
- attempts；
- next_retry_at；
- delivered_at。

### 12.3 租约和恢复

- 同一 task 同一时刻只有一个有效 Worker lease；
- lease 到期后可重新领取；
- Bridge 使用数据库锁或单实例租约，防止重复派发；
- 进程崩溃后从内部状态和未确认消息恢复；
- 重试只允许重新执行幂等步骤；
- 外部 Action 必须先查 Receipt 和 Reconciliation。

## 13. 评审、门禁和返工

评审结果分为：

- minor：记录后允许批准；
- major：必须生成 Fix Request；
- blocker：阻断发布和 Action；
- question：任务进入 awaiting_human 等待业务回答。

默认最多 3 轮修复。每轮保存：

- review round；
- 输入 Artifact 版本；
- Reviewer 身份和模型路线；
- findings；
- 修复提示；
- 新 Artifact 版本；
- checks 输出；
- Gate 输出。

任何 Agent 自报的“完成”都不能代替：

- 确定性检查；
- 证据引用检查；
- 独立 Challenger；
- Gate Engine；
- 必要的人类审批。

## 14. 人工检查点策略

根据风险等级选择检查点：

### Low

- Contract；
- 最终 Artifact。

### Medium

- Contract；
- Ontology/Data Product 边界；
- 最终预测或决策输出。

### High

- Contract；
- 数据访问；
- Ontology 语义边界；
- 模型评估；
- 决策/Action dry-run；
- 生产 Action；
- 结果 reconciliation。

人工检查点由 Contract 声明，不能由 Agent 临时降低。

## 15. 失败、冲突和升级

以下情况必须升级人工：

- Contract 无法解析；
- 关键证据缺失或冲突；
- 需求版本变化；
- Agent 输出不含证据；
- Gate blocker；
- 连续执行失败；
- 超过最大修复轮次；
- 超过 Token/时间预算；
- Linear 状态与内部状态冲突；
- 外部 Action 结果无法 reconciliation；
- 需要提升数据或工具权限。

升级评论必须包含：

- task/issue；
- run；
- contract version；
- 当前内部状态；
- 失败原因；
- 已尝试次数；
- 相关 Artifact/Evidence/Gate；
- 人类需要做的具体决定。

## 16. 安全和权限

- Linear 用户身份映射到 AI-FDE actor；
- 审批命令校验角色和项目权限；
- Agent 使用独立 Context 和 Tool Gateway；
- Linear 评论不写原始客户敏感数据；
- 评论只写摘要、哈希和引用；
- 生产 Action 需要显式 Policy 和 Approval；
- Bridge 不将 Linear token 暴露给 Worker；
- Worker 不拥有改变 Linear 状态的凭证；
- 所有人工命令和 Agent 事件进入 append-only audit；
- 需求、证据和工件按项目隔离。

## 17. 可观测性和人机协作指标

最低指标：

- 工单从创建到 Contract 通过的时间；
- needs_info 比例；
- 每个 Agent 节点成功率、耗时和预算；
- 每轮评审的 minor/major/blocker 比例；
- 平均修复轮次；
- 人工等待时间；
- 工单状态冲突数量；
- Bridge webhook/轮询延迟；
- 重复事件和幂等命中数量；
- 人工升级比例；
- Artifact/Evidence 引用完整率；
- Action reconciliation 成功率；
- 预测和决策反馈闭环率。

## 18. 验收场景

### 基础闭环

- Fake Linear 创建规范工单；
- Contract 通过；
- 选择 software delivery domain graph；
- Worker 完成节点；
- checks、Challenger 和 Gate 通过；
- Linear 进入 In Review；
- 授权人批准；
- 工单可关闭。

### 需求补充

- 缺少 decision owner；
- Bridge 评论缺口；
- 任务停在 needs_info；
- 人类通过评论补齐；
- 新合同版本重新进入 ready。

### 评审返工

- Reviewer 返回 minor，任务可继续审批；
- Reviewer 返回 major，进入 Fix Request；
- 第二轮通过；
- 所有轮次和工件版本可追溯。

### 失败与升级

- checks 失败保持 In Progress；
- Executor 超时；
- 重复消息；
- Bridge 重启；
- 三轮修复仍失败；
- 最终生成人工升级评论。

### 冲突与安全

- 人类提前移动 Done；
- 未授权人发送 approve；
- Agent 尝试改变状态；
- Agent 访问未授权 Evidence；
- Action 重复投递；
- 需求被修改导致旧 run stale。

### Real Adapter 合同

- GraphQL 分页；
- webhook 签名；
- 评论和状态更新；
- 网络超时和限流；
- Outbox 重试；
- 没有 token 时 Fake 模式不访问外部。

## 19. 实施分解

### L0：领域无关的生命周期内核

- TaskContract 和版本；
- 内部状态机；
- Inbox/Outbox；
- Fake Adapter；
- 结构化评论和命令解析；
- 生命周期单元测试。

### L1：连接现有 AgentTeam

- Task kind 到 DomainAgent Graph 的路由；
- Redis dispatch；
- Worker lease、预算和幂等；
- Artifact、Gate、Audit 结果回写。

### L2：评审闭环

- deterministic checks；
- Challenger；
- Reviewer findings；
- major/blocker 返工；
- 最大轮次和人工升级。

### L3：真实 Linear

- GraphQL Real Adapter；
- webhook + poll；
- 用户身份绑定；
- Linear 状态投影；
- 评论、状态冲突和限流恢复。

### L4：生产运维

- PostgreSQL 持久化；
- MinIO 工件；
- 结构化日志和指标；
- 备份恢复；
- Compose E2E；
- 双领域运行验证。

## 20. 与当前代码的接入边界

预计新增或扩展：

- aifde/task/：TaskContract、版本和生命周期；
- aifde/integrations/linear/：Adapter、Fake/Real、评论和命令；
- aifde/queue/：Redis Streams Publisher/Consumer；
- aifde/runtime/worker.py：AgentRun Worker；
- aifde/persistence/：PostgreSQL Registry、Inbox、Outbox、Audit；
- aifde/review/：checks、Challenger、Review Cycle；
- aifde/api/：任务、运行、审批和健康接口。

复用现有组件：

- DomainAgentTeam；
- AgentGraph；
- ArtifactWorkspace；
- GateEngine；
- PolicyEngine；
- ReadinessChecker；
- AppendOnlyAuditLog；
- MetricsRegistry；
- ActionBroker 和 ReconciliationLedger。

## 21. 明确不在第一版实现

- 让 Agent 直接使用 Linear API；
- 用自然语言评论直接触发生产 Action；
- 多个独立 Agent 自由协商并自动合并冲突；
- 无证据的自动 Ontology 发布；
- 无人批准的高风险外部写入；
- 将 Linear 当作大文件和敏感证据存储；
- 以模型自评替代确定性 Gate 和独立 Challenger。
