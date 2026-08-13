# 软件研发需求对齐、需求追加与工期预测 Ontology 样板项目设计规格

> 文档状态：设计草案，等待审阅
> 日期：2026-08-11
> 项目类型：本地/私有、模拟数据、模拟 Action 的 Palantir-like 垂直样板
> 依赖平台：AI FDE Builder

## 0. 执行摘要

本项目用于体验一套完整的 Palantir-like 工程流程，业务方向是：

> 解决软件工程开发中的需求对齐、需求追加影响分析、工期预测和迭代计划调整问题。

项目不是做一个需求聊天机器人，也不是简单把 Jira 数据做成报表，而是形成以下闭环：

    需求资料与变更请求
    → 角色、目标、范围和验收条件对齐
    → Requirement、ChangeRequest、WorkItem、Dependency 等 Ontology 对象
    → 数据产品与历史快照
    → 需求变更影响分析
    → 工期预测
    → Sprint 重排和候选计划
    → 用户审批
    → 模拟 Action 更新 Backlog/Sprint
    → 实际完成结果与用户反馈
    → 预测、规则和模型改进

项目将同时验证：

- Ontology 是否从流程镜像扩展为可计算模型；
- 数据产品能否支持时间正确的预测；
- 预测是否能进入计划决策；
- 候选计划是否满足资源和依赖约束；
- 用户是否愿意在工作流中使用；
- AI FDE 的门禁是否能阻止表面化交付。

## 1. 项目目标与非目标

### 1.1 项目目标

#### G1：需求对齐

让项目团队能够回答：

- 需求是谁提出的；
- 需求解决什么业务问题；
- 影响哪些模块、任务和依赖；
- 谁需要确认；
- 验收条件是否明确；
- 当前版本是否应该接收。

#### G2：需求追加分析

当新增或变更需求进入系统时，识别：

- 影响的 Requirement；
- 影响的 Module；
- 影响的 WorkItem；
- 新增工作量；
- 关键路径变化；
- 资源冲突；
- 版本延期风险；
- 需要谁审批。

#### G3：工期预测

在某个历史观察时点，只使用当时可获得的数据，预测：

- WorkItem 的完成天数；
- Sprint 的完成率；
- 需求是否会超过承诺日期；
- 需求追加造成的延期概率；
- P50/P80 完成日期；
- 主要风险因素。

#### G4：计划决策

给出可比较的候选方案：

- 接收追加需求并延期；
- 接收追加需求并减少低优先级任务；
- 增加人员或外部资源；
- 拆分需求并延后部分范围；
- 保持当前计划并拒绝追加需求。

#### G5：完整反馈

记录：

- 用户接受、拒绝或修改了什么；
- 实际执行了什么；
- Action 是否成功；
- 实际完成时间；
- 预测误差；
- 推荐方案是否改善结果。

### 1.2 非目标

项目初版不实现：

- 连接真实 Jira、GitHub、GitLab 或企业项目管理系统；
- 自动修改真实 Backlog；
- 自动向真实团队发送通知；
- 自动评价个人绩效；
- 根据预测结果自动惩罚或排名团队；
- 在数据不足时强行生成生产级预测模型；
- 解决所有软件工程管理问题。

所有外部动作使用 Mock Action。

## 2. 业务决策契约

### 2.1 核心决策

项目围绕以下决策：

> 项目经理或产品负责人收到一个新增或变更需求后，基于当前项目状态、团队容量、历史交付表现、依赖关系和需求风险，判断是否接收、拆分、延期、增配资源或拒绝该需求。

### 2.2 决策输入

- 需求目标和范围；
- 验收条件；
- 优先级；
- 关联模块；
- 关联任务；
- 依赖关系；
- 团队和人员容量；
- 当前 Sprint 剩余容量；
- 历史任务周期；
- 当前阻塞情况；
- 需求变更次数；
- 测试和评审队列；
- 目标承诺日期；
- 组织审批规则。

### 2.3 候选动作

- 接收需求；
- 请求澄清；
- 拆分需求；
- 延后低优先级任务；
- 调整 Sprint；
- 增加资源；
- 调整承诺日期；
- 升级审批；
- 拒绝追加需求。

### 2.4 结果指标

- 需求按期完成率；
- 需求完成时间误差；
- Sprint 承诺完成率；
- 追加需求导致的延期天数；
- 需求返工率；
- 阻塞时间；
- 需求澄清耗时；
- 用户决策耗时；
- 计划变更次数；
- 预测方案采纳率。

## 3. 用户和责任角色

| 角色 | 任务 | 权限 |
|---|---|---|
| 产品负责人 | 定义需求目标和验收条件 | 提交、修改、确认需求 |
| 项目经理 | 评估影响、工期和计划 | 生成方案、审批计划 |
| 技术负责人 | 确认技术依赖和拆分 | 确认模块、依赖和估算 |
| 开发负责人 | 提供执行状态和阻塞信息 | 更新 WorkItem 状态 |
| 测试负责人 | 确认验收和测试容量 | 更新测试状态 |
| 资源负责人 | 确认人员和容量 | 审批资源调整 |
| AI FDE | 构建和维护系统 | 生成候选产物，不拥有业务语义最终批准权 |
| 领域 Owner | 审核模型语义和业务结果 | 批准阶段和重要动作 |

## 4. 需求和工作流生命周期

### 4.1 Requirement 生命周期

    proposed
    → clarifying
    → aligned
    → approved
    → decomposed
    → planned
    → in_progress
    → completed
    → accepted

异常状态：

    rejected
    cancelled
    superseded
    blocked

### 4.2 ChangeRequest 生命周期

    submitted
    → impact_analysis
    → waiting_for_clarification
    → plan_proposed
    → waiting_for_approval
    → accepted
    → scheduled
    → implemented
    → verified

异常状态：

    rejected
    cancelled
    expired

### 4.3 WorkItem 生命周期

    backlog
    → ready
    → in_progress
    → in_review
    → in_test
    → blocked
    → done

每一次状态变化必须记录事件，不允许只覆盖当前状态。

### 4.4 关键业务事件

- RequirementSubmitted；
- RequirementClarified；
- RequirementApproved；
- RequirementChanged；
- RequirementSplit；
- WorkItemCreated；
- WorkItemStarted；
- WorkItemBlocked；
- WorkItemUnblocked；
- WorkItemReviewed；
- WorkItemCompleted；
- SprintStarted；
- SprintCapacityChanged；
- DependencyAdded；
- DependencyResolved；
- EstimateChanged；
- PlanApproved；
- PlanRejected；
- ActionExecuted；
- ActualOutcomeObserved。

## 5. Ontology 设计

### 5.1 核心对象

| 对象 | 说明 | 关键属性 |
|---|---|---|
| Project | 项目或产品 | project_id、name、start_date、target_date、status |
| Requirement | 业务需求 | requirement_id、title、goal、priority、status、owner |
| RequirementVersion | 需求版本 | version_id、content、created_at、created_by、change_reason |
| ChangeRequest | 追加或变更请求 | change_id、reason、requested_at、urgency、status |
| AcceptanceCriterion | 验收条件 | criterion_id、description、verification_method、status |
| Stakeholder | 相关人员 | stakeholder_id、role、team、approval_scope |
| Module | 系统模块 | module_id、name、owner、risk_level |
| WorkItem | 可执行工作项 | work_item_id、type、estimate_hours、status、assignee |
| Dependency | 任务或模块依赖 | dependency_id、predecessor、successor、type、status |
| Sprint | 迭代周期 | sprint_id、start_date、end_date、capacity_hours、status |
| Team | 团队 | team_id、name、capacity、skills |
| Person | 人员 | person_id、team_id、role、availability |
| CapacitySnapshot | 容量快照 | snapshot_time、available_hours、allocated_hours |
| BlockerEvent | 阻塞事件 | blocker_id、started_at、resolved_at、reason |
| Estimate | 工期估算 | estimate_id、work_item、hours、method、created_at |
| DeliveryPrediction | 工期预测 | prediction_id、target、as_of_time、p50、p80、model_version |
| DeliveryRisk | 交付风险 | risk_id、probability、severity、reason_codes、expires_at |
| CandidatePlan | 候选计划 | plan_id、objective_value、constraints、assumptions |
| PlanChange | 计划变更 | plan_change_id、change_type、before、after、reason |
| ActionRequest | Action 请求 | action_id、type、parameters、approval、status |
| ActionOutcome | Action 回执 | outcome_id、success、external_ref、executed_at |
| Feedback | 用户或现实反馈 | feedback_id、type、value、created_at、source |

### 5.2 核心关系

- Project hasRequirement Requirement；
- Requirement hasVersion RequirementVersion；
- Requirement hasCriterion AcceptanceCriterion；
- Requirement requestedBy Stakeholder；
- ChangeRequest changes Requirement；
- ChangeRequest affects Module；
- ChangeRequest affects WorkItem；
- Requirement decomposedInto WorkItem；
- WorkItem belongsTo Module；
- WorkItem assignedTo Person；
- Person memberOf Team；
- WorkItem dependsOn WorkItem；
- WorkItem plannedIn Sprint；
- WorkItem hasEstimate Estimate；
- WorkItem hasPrediction DeliveryPrediction；
- DeliveryRisk affects WorkItem；
- CandidatePlan changes Sprint；
- CandidatePlan addresses ChangeRequest；
- CandidatePlan usesPrediction DeliveryPrediction；
- CandidatePlan subjectTo Dependency；
- CandidatePlan executedBy ActionRequest；
- ActionRequest produces ActionOutcome；
- ActionOutcome generates Feedback。

### 5.3 对象粒度

必须明确：

- Requirement：一个可被业务确认的需求单元；
- ChangeRequest：一次新增或变更请求；
- WorkItem：一个可由团队执行、估算和完成的工作单元；
- Sprint：一个有明确开始和结束时间的迭代；
- BlockerEvent：一次连续阻塞区间；
- Estimate：某个观察时点产生的一次估算；
- DeliveryPrediction：某个观察时点产生的一次预测。

不能把 Requirement、WorkItem 和 ChangeRequest 混为同一个对象。

### 5.4 状态与事实分离

当前状态是派生视图，状态事件才是事实。

例如：

- WorkItem.status = in_progress 是当前视图；
- WorkItemStarted 是事实事件；
- WorkItemBlocked 是事实事件；
- WorkItemCompleted 是事实事件。

这样才能重建任意历史时点的项目状态。

### 5.5 RDFS/SHACL 语义职责

RDFS/OWL 描述：

- 对象类别；
- 继承关系；
- 属性；
- 关系；
- 领域和范围。

SHACL 校验：

- Requirement 必须有业务目标、Owner 和状态；
- ChangeRequest 必须关联一个 Requirement 或新增范围；
- WorkItem 必须属于 Module；
- DeliveryPrediction 必须有 as_of_time、模型版本和特征快照；
- CandidatePlan 必须有关联的目标、变量和约束；
- ActionRequest 必须有权限和审批条件。

计算逻辑不放入 RDFS，而由 SQL、Python、机器学习和 Solver 执行。

## 6. 模拟数据源

### 6.1 需求资料源

字段：

- requirement_id；
- title；
- description；
- requester；
- business_goal；
- priority；
- acceptance_text；
- created_at；
- updated_at；
- source_document；
- version。

### 6.2 需求变更源

字段：

- change_id；
- requirement_id；
- requested_by；
- requested_at；
- change_reason；
- added_scope；
- removed_scope；
- urgency；
- approval_status。

### 6.3 工作项源

字段：

- work_item_id；
- requirement_id；
- module_id；
- type；
- estimate_hours；
- assignee；
- team_id；
- committed_date；
- actual_start_at；
- actual_complete_at；
- status；
- priority。

### 6.4 状态事件源

字段：

- event_id；
- entity_type；
- entity_id；
- event_type；
- event_time；
- observed_time；
- actor；
- reason；
- source_system。

### 6.5 依赖源

字段：

- dependency_id；
- predecessor_id；
- successor_id；
- dependency_type；
- created_at；
- resolved_at；
- status；
- confidence；
- source。

### 6.6 团队容量源

字段：

- team_id；
- person_id；
- snapshot_time；
- available_hours；
- allocated_hours；
- leave_hours；
- skill_tags；
- sprint_id。

### 6.7 评审、测试和阻塞源

字段：

- review_id；
- work_item_id；
- submitted_at；
- approved_at；
- review_rounds；
- test_started_at；
- test_completed_at；
- blocker_started_at；
- blocker_resolved_at；
- blocker_reason。

### 6.8 用户反馈源

字段：

- feedback_id；
- artifact_id；
- user_id；
- feedback_type；
- accepted；
- modified；
- rejection_reason；
- created_at。

## 7. 数据产品设计

### 7.1 需求事实数据产品

粒度：一行一个需求版本。

输出：

- 当前需求版本；
- 需求目标；
- 验收条件；
- 需求 Owner；
- 变更历史；
- 证据链接；
- 质量结果。

### 7.2 需求变更事件数据产品

粒度：一行一个变更事件。

输出：

- 变更请求；
- 发生时间；
- 变更前后范围；
- 影响对象；
- 审批状态；
- 证据。

### 7.3 工作项生命周期数据产品

粒度：一行一个 WorkItem 的状态区间或状态事件。

输出：

- 状态进入时间；
- 状态退出时间；
- 每个状态的停留时长；
- 阻塞时长；
- 评审时长；
- 测试时长；
- 实际完成时间。

### 7.4 计划和容量数据产品

粒度：

- 一行一个 Sprint 容量快照；
- 一行一个团队分配；
- 一行一个计划版本。

输出：

- 剩余容量；
- 已分配容量；
- 需求优先级；
- 任务依赖；
- 计划版本；
- 资源变化。

### 7.5 数据管道分层

| 层 | 内容 |
|---|---|
| Raw | 原始需求、变更、任务、事件和容量记录 |
| Staged | 类型、日期、枚举和字段标准化 |
| Conformed | Requirement、WorkItem、Person、Team、Sprint 身份统一 |
| Enriched | 依赖、周期、阻塞、变更影响和历史指标 |
| Ontology Projection | 对象、关系、事件、状态和预测投影 |
| Serving | 应用查询、特征快照和回放数据 |

### 7.6 数据质量门禁

必须检查：

- requirement_id 是否唯一；
- work_item_id 是否唯一；
- event_time 是否早于 observed_time 或符合迟到规则；
- actual_complete_at 是否晚于 actual_start_at；
- ChangeRequest 是否关联有效 Requirement；
- WorkItem 是否关联有效 Module；
- Dependency 是否形成非法环；
- Sprint 日期是否有效；
- Capacity 是否出现负值；
- 状态事件是否可以重建当前状态。

## 8. 分析模型

分析层用于理解历史和当前状态，不直接声称预测未来。

### 8.1 需求对齐指标

- 需求澄清耗时；
- 验收条件完整率；
- 需求版本变更次数；
- 需求被拒绝或返工次数；
- 需求从提出到批准的周期；
- 角色之间的意见冲突数；
- 需求和 WorkItem 的覆盖率。

### 8.2 需求追加指标

- 每个 Sprint 的追加数量；
- 追加工作量；
- 追加导致的计划变更次数；
- 追加需求的平均澄清时间；
- 追加需求导致的延期天数；
- 被拆分或拒绝的比例。

### 8.3 交付过程指标

- Lead Time；
- Cycle Time；
- 阻塞时长；
- 评审轮次；
- 测试时长；
- 返工次数；
- Sprint 完成率；
- 估算误差；
- 依赖等待时间；
- 团队吞吐量。

### 8.4 当前状态视图

对每个 Sprint 形成一个历史快照：

- 当前未完成 WorkItem；
- 剩余容量；
- 已消耗容量；
- 关键路径；
- 阻塞任务；
- 追加需求；
- 预测完成日期；
- 当前风险。

## 9. 工期预测模型

### 9.1 预测问题一：WorkItem 完成时长

实体：WorkItem。

观察时点：任务进入 ready 或 in_progress 的时间。

目标：

- remaining_duration_days；
- probability_late；
- p50_completion_date；
- p80_completion_date。

标签：

    actual_complete_at - as_of_time

只对最终完成的任务生成完整标签；取消任务、重新打开任务和缺少结束时间的任务分别处理，不能混在一起。

### 9.2 预测问题二：需求是否延期

实体：Requirement 或 Sprint。

观察时点：需求批准、计划进入 Sprint 或出现 ChangeRequest 的时点。

目标：

- 是否超过承诺日期；
- 延期天数；
- 需求完成率；
- Sprint 承诺完成率。

标签必须基于未来实际结果，不能使用观察时点之后才出现的状态字段。

### 9.3 可计算特征

| 特征 | 粒度 | 时间窗口 | 计算逻辑 | 业务含义 |
|---|---|---|---|---|
| 历史团队中位 Cycle Time | Team | 最近 5 个 Sprint | 完成任务周期中位数 | 团队基线 |
| 需求变更次数 | Requirement | 观察时点前 | ChangeRequest 数量 | 范围稳定性 |
| 变更累计工作量 | Requirement | 观察时点前 | 追加估算小时数 | 范围膨胀 |
| 未完成依赖数量 | WorkItem | 观察时点 | 未完成前置任务数 | 依赖风险 |
| 依赖图中心性 | WorkItem | 当前快照 | 依赖图计算 | 关键路径风险 |
| 历史阻塞比例 | Team/Person | 最近 30 天 | 阻塞时间/工作时间 | 流程风险 |
| 当前评审队列 | Team | 观察时点 | 未完成评审数量 | 评审瓶颈 |
| 验收条件完整度 | Requirement | 观察时点 | 已确认条件/应有条件 | 需求清晰度 |
| 资源剩余容量 | Team/Sprint | 当前 Sprint | 可用减已分配 | 资源余量 |
| 任务估算偏差 | Person/Team | 最近 N 个任务 | 实际/估算比例 | 估算校准 |
| 优先级 | WorkItem | 当前快照 | 业务优先级编码 | 排序依据 |
| 任务类型 | WorkItem | 当前快照 | feature、bug、test 等 | 类型差异 |

每个特征必须保存：

- 实体；
- 粒度；
- 计算逻辑；
- 时间窗口；
- 观察时点；
- 可用延迟；
- 缺失处理；
- 版本；
- 数据血缘；
- 数据泄漏规则。

### 9.4 数据泄漏规则

禁止使用：

- actual_complete_at；
- 观察时点后的 status；
- 观察时点后的 blocker；
- 观察时点后的 review 结果；
- 未来 Sprint 的容量；
- 未来才创建的 ChangeRequest；
- 真实完成日期派生的任何字段。

允许使用：

- 观察时点之前的变更；
- 观察时点之前的历史周期；
- 当前已知容量；
- 当前已知依赖；
- 当前已确认的验收条件；
- 当前已存在的阻塞。

### 9.5 基线和候选模型

第一版必须先建立基线：

- 团队历史中位数；
- 按任务类型的历史中位数；
- 估算小时乘以团队校准系数；
- Monte Carlo 采样的简单计划模型。

候选模型：

- 线性回归；
- Random Forest；
- Gradient Boosting；
- Quantile Regression；
- 生存分析或时间到事件模型。

模型不是越复杂越好。只有在时间正确的回放中优于基线，才允许进入候选发布。

### 9.6 模型评估

至少评估：

- MAE；
- RMSE；
- P50 预测误差；
- P80 覆盖率；
- 延期分类的 Precision、Recall 和 F1；
- 概率校准；
- 不同团队、任务类型和优先级的分组表现；
- 时间漂移；
- 与人工估算的比较。

如果数据量不足，应交付：

- 历史基线；
- 分析指标；
- 风险规则；
- 数据采集建议；

而不是伪造 ML 预测能力。

## 10. 决策与优化模型

### 10.1 决策问题

目标是在需求变更进入后，选择一套满足资源、依赖、期限和优先级约束的计划。

### 10.2 决策变量

- 是否接收 ChangeRequest；
- 是否拆分 Requirement；
- 是否延后低优先级 WorkItem；
- 是否调整 WorkItem 所属 Sprint；
- 是否增加资源；
- 是否调整承诺日期；
- 是否升级审批。

### 10.3 目标函数

建议最小化：

    延期成本
    + 未完成高优先级需求损失
    + 资源增加成本
    + 计划变更成本
    + 需求拆分损失
    + 用户等待成本

目标函数必须将每一项转为可解释的业务量或相对权重。

### 10.4 硬约束

- WorkItem 依赖关系不能违反；
- 人员和团队容量不能超出；
- 任务必须具备所需技能；
- Sprint 日期不能冲突；
- 已批准的不可变任务不能随意移除；
- 关键验收和测试任务必须保留；
- Action 的审批权限必须满足；
- 不能安排已取消的需求。

### 10.5 候选方案

至少生成：

1. 维持当前计划，拒绝追加需求；
2. 接收需求，延后低优先级任务；
3. 接收需求，拆分范围；
4. 接收需求，增加资源；
5. 接收需求，调整承诺日期。

每个方案必须展示：

- 目标函数值；
- 变更内容；
- 受影响的需求和任务；
- 关键路径；
- 资源余量；
- 预测完成日期；
- 约束松弛；
- 不可行原因；
- 用户需要批准的内容。

## 11. 用户应用设计

### 11.1 需求收件箱

展示：

- 新需求；
- 追加需求；
- 待澄清需求；
- 高风险需求；
- 等待审批需求。

操作：

- 请求澄清；
- 关联已有需求；
- 标记重复；
- 启动影响分析；
- 转入评估。

### 11.2 需求详情页

展示：

- 需求目标；
- 需求版本；
- 验收条件；
- Stakeholder；
- 关联模块；
- 关联 WorkItem；
- 依赖图；
- 证据；
- 历史变更；
- AI 生成的未决问题。

### 11.3 变更影响分析页

展示：

- 变更前后范围；
- 受影响对象；
- 新增工作量；
- 关键路径；
- 依赖风险；
- 预测延期概率；
- 预测依据；
- 数据质量；
- Challenger 发现的问题。

### 11.4 工期预测页

展示：

- P50 和 P80 完成时间；
- 当前承诺日期；
- 历史基线；
- 影响最大的特征；
- 类似历史任务；
- 置信度；
- 不确定性；
- 预测时点；
- 模型和特征版本。

### 11.5 方案比较页

展示：

- 不同候选计划；
- 成本；
- 延期；
- 资源使用；
- 高优先级需求完成率；
- 依赖约束；
- 方案差异；
- 用户可修改的参数。

### 11.6 回放实验室

支持：

- 选择历史时点；
- 注入一个 ChangeRequest；
- 修改容量；
- 修改优先级；
- 重新运行预测；
- 重新生成候选计划；
- 模拟审批和 Action；
- 与真实结果对照。

## 12. 模拟 Action

初版不连接真实系统，提供以下 Mock Action：

| Action | 作用 | 回执 |
|---|---|---|
| CreateChangeRequest | 创建需求变更 | change_id、status |
| RequestClarification | 请求补充信息 | question_id、recipient |
| ApproveRequirement | 批准需求 | approval_id、approved_at |
| ReplanSprint | 写入模拟 Sprint 计划 | plan_id、affected_items |
| ReassignWorkItem | 模拟调整负责人 | old_owner、new_owner |
| AdjustCommitmentDate | 模拟调整承诺日期 | old_date、new_date |
| EscalateRisk | 创建风险升级 | risk_id、approver |
| RejectChangeRequest | 拒绝变更 | reason、rejected_at |

每个 Action 必须具备：

- 参数 Schema；
- 权限；
- 审批条件；
- 幂等键；
- 模拟执行；
- 成功和失败回执；
- 审计；
- Feedback 关联。

## 13. 模拟数据生成

### 13.1 初始规模

建议第一版生成：

- 3 个 Team；
- 12 名 Person；
- 5 个 Module；
- 8 个 Sprint；
- 80 个 Requirement；
- 160 个 WorkItem；
- 40 个 ChangeRequest；
- 600 条状态事件；
- 100 条 Dependency；
- 200 条 BlockerEvent；
- 80 条容量快照；
- 100 条用户反馈。

规模可以通过配置调整。

### 13.2 生成原则

模拟数据不能是互相独立的随机表，必须有因果和时间关系：

- ChangeRequest 会增加 WorkItem 或估算；
- 依赖未完成会增加等待时间；
- 验收条件缺失会增加澄清时间；
- 评审轮次增加会延长完成周期；
- 容量不足会增加排队时间；
- 阻塞事件会影响实际完成时间；
- 需求稳定性会影响返工概率；
- 高优先级任务会改变计划排序。

### 13.3 隐藏真值

数据生成器可以保留隐藏真值，用于评估：

- 真实延期原因；
- 真实工作量；
- 真实依赖影响；
- 真实完成时间；
- 真实计划成本。

隐藏真值不能进入预测特征，只能用于离线评估。

## 14. 项目门禁流程

### 阶段 0：项目立项

必须有：

- 业务目标；
- 用户；
- 决策；
- 结果指标；
- 项目 Owner；
- 模拟范围。

### 阶段 1：需求对齐

必须有：

- 需求案例；
- 追加案例；
- 被拒绝或修改案例；
- 角色和责任；
- 验收条件；
- 未决问题；
- 证据位置。

### 阶段 2：Ontology

必须有：

- 对象和关系；
- 对象粒度；
- 生命周期；
- 状态事件；
- 权限；
- 源字段映射；
- SHACL 校验。

### 阶段 3：数据产品

必须有：

- Raw、Staged、Conformed 和 Serving 层；
- 主键和粒度；
- 时间字段；
- 数据质量；
- 血缘；
- 回放快照；
- 缺失和冲突策略。

### 阶段 4：预测

必须有：

- 预测实体；
- 观察时点；
- 标签；
- 预测窗口；
- 特征版本；
- 泄漏检查；
- 基线；
- 时间切分；
- 评估报告。

### 阶段 5：决策

必须有：

- 目标函数；
- 决策变量；
- 硬约束；
- 候选方案；
- 方案可行性；
- 约束解释；
- 用户审批。

### 阶段 6：业务应用

必须有：

- 需求收件箱；
- 影响分析；
- 工期预测；
- 方案比较；
- 证据查看；
- 审批；
- Mock Action；
- ActionOutcome。

### 阶段 7：反馈

必须有：

- 实际完成结果；
- 用户采纳或拒绝；
- Action 成功或失败；
- 预测误差；
- ROI 或基线比较；
- 改进任务。

## 15. 反例和验收场景

| 场景 | 需要验证 |
|---|---|
| 正常需求进入 Sprint | 基本需求到计划闭环 |
| 需求追加 | 影响分析和工期变化 |
| 需求描述不完整 | 系统请求澄清，不自行补全 |
| 两个 Stakeholder 说法冲突 | 生成冲突，不静默合并 |
| 重复需求 | 识别相似需求并请求确认 |
| 跨模块依赖 | 影响传播和关键路径 |
| 容量不足 | 生成不可行或延期方案 |
| 需求取消 | 生命周期和计划回滚 |
| 任务被阻塞 | 预测更新和风险升级 |
| 观察时点后才出现的数据 | 泄漏门禁阻断 |
| Action 失败 | 重试、补偿和人工处理 |
| 无历史标签 | 降级到基线和数据采集 |
| 用户拒绝推荐 | 记录原因并进入反馈 |
| 用户修改推荐参数 | 重新计算并记录覆盖 |

## 16. 项目成功标准

### 16.1 工程成功

- 一个需求可以从资料进入 Ontology；
- 一个追加需求可以生成影响分析；
- 一个历史时点可以回放；
- 工期预测可以回到特征、数据和证据；
- 候选计划可以通过约束验证；
- 用户可以审批和执行 Mock Action；
- Action 结果可以回写。

### 16.2 质量成功

- 所有硬门禁可执行；
- 所有关键 Claim 有证据；
- 数据泄漏测试可以捕获故意注入的泄漏字段；
- 依赖环测试可以被阻断；
- 无标签时不会生成伪预测；
- 不可行方案不会被展示为可执行；
- 任何发布都可以回滚。

### 16.3 业务成功

在模拟任务集上，与简单人工基线相比：

- 需求影响识别召回率提高；
- 需求澄清时间下降；
- 工期预测误差不高于基线；
- P80 覆盖率达到预设目标；
- 计划方案满足硬约束；
- 用户能够理解预测和推荐依据；
- 用户反馈可以改变后续模型或规则。

具体阈值在生成模拟数据和基线运行后确定，不预先伪造一个看似精确的指标。

## 17. 实施阶段

### M0：样板数据和领域对象

- 生成模拟源数据；
- 建立事件时间语义；
- 建立核心对象；
- 建立 RDFS/SHACL；
- 通过 Ontology 门禁。

### M1：需求对齐应用

- 需求收件箱；
- 需求详情；
- 证据浏览；
- 需求版本和变更；
- 澄清与审批 Mock Action。

### M2：数据产品和分析

- 生命周期数据产品；
- 需求追加指标；
- Sprint 和容量指标；
- 历史快照；
- 数据质量门禁。

### M3：工期预测

- 特征定义；
- 标签生成；
- 时间切分；
- 基线；
- 候选模型；
- 回放实验室；
- 预测解释。

### M4：决策和计划重排

- 目标函数；
- 约束；
- 候选计划；
- 方案比较；
- ReplanSprint Mock Action；
- 反馈回写。

### M5：完整 AI FDE 流程

- 让 AI FDE 从项目章程开始；
- 自动生成阶段产物；
- 触发 Challenger；
- 运行全部门禁；
- 生成交付包；
- 记录完整 StageRun。

## 18. 设计中的明确降级规则

- 没有稳定 Requirement ID：不能建立需求级预测；
- 没有 ChangeRequest 时间：不能预测追加影响；
- 没有 WorkItem 完成事件：不能构造完整工期标签；
- 没有当前容量：不能进行可信的资源优化；
- 没有历史基线：只能提供规则和数据采集建议；
- 预测效果不优于基线：保留基线，不发布 ML 模型；
- 方案违反硬约束：返回不可行原因，不显示为推荐；
- 用户拒绝率持续升高：暂停自动推荐，进入复盘。

## 19. 开放问题

1. 第一版预测粒度先做 WorkItem、Requirement 还是同时支持 Sprint；
2. 是否将 Git Commit、Pull Request 和 CI 事件作为第二阶段数据源；
3. 需求相似度是否使用 Embedding，还是先使用规则和关键词；
4. 是否需要引入真实 Jira 导出数据作为后续验证；
5. 模拟数据是否需要提供可视化生成器；
6. 业务基线由历史中位数还是人工排期作为第一基线；
7. Action 反馈是否需要模拟外部系统延迟和失败；
8. 是否将用户的手工改计划行为作为模型训练标签。

## 20. 设计结论

这个样板项目的核心不是预测一个日期，而是将以下五个层次连接起来：

    描述层
    Requirement、WorkItem、Dependency、Sprint、Person、Team

    分析层
    变更率、周期、阻塞、容量、依赖和需求清晰度

    预测层
    完成时长、延期概率、P50/P80 完成日期

    决策层
    接收、拆分、延期、增配资源、调整 Sprint 或拒绝

    行动反馈层
    审批、计划变更、实际完成、用户覆盖和预测误差

最终验收不是“生成了一个项目管理 Agent”，而是：

    一个需求追加进入系统
    → 系统能解释影响
    → 能给出时间正确的预测
    → 能生成满足约束的候选计划
    → 用户能审批和修改
    → Mock Action 能改变计划
    → 实际结果能回写
    → 门禁、模型和规则能据此改进
