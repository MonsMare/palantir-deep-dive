# AI FDE Builder 设计规格：受门禁控制的 Palantir-like 工程控制平面

> 文档状态：设计草案，等待审阅
> 日期：2026-08-11
> 适用范围：本地/私有部署、Git 优先、开源组件可组合的自用 MVP
> 设计定位：借鉴 Palantir-like 工程方法，不复刻 Palantir 未公开的内部实现

## 0. 执行摘要

AI FDE Builder 是一套辅助构建业务 AI 系统的工程控制平面。它服务 FDE、数据工程师、Ontology 工程师、模型工程师、应用工程师和业务 Owner，把以下过程变成可审查、可执行、可回滚的工程流水线：

    业务目标与散乱资料
    → 高价值业务决策
    → 真实工作流观察
    → 需求与方案设计
    → 数据源登记与数据产品
    → Ontology 与语义校验
    → 分析、特征、预测与优化
    → 函数、应用与 Action
    → 门禁、评估、交付
    → 运行反馈与持续改进

系统的核心不是增加 Agent 数量，而是把 Agent 的工作限制在任务契约、证据、工程产物、确定性验证和人工审批之内。

最终交付条件：

    Artifact 可发布
    = 任务契约完整
    ∧ 证据链完整
    ∧ 语义验证通过
    ∧ 数据验证通过
    ∧ 可执行验证通过
    ∧ 反例审查通过
    ∧ 领域 Owner 批准
    ∧ Git 变更可追溯
    ∧ 回滚方案存在

## 1. 设计背景与定位

### 1.1 要解决的问题

传统多 Agent 系统容易出现：

- Agent 生成大量自然语言，但没有可运行产物；
- 多个 Agent 互相总结同一份错误资料；
- 需求、Ontology、数据管道和模型之间没有共同契约；
- Agent 把假设写成事实；
- 没有真实案例、异常案例和反例；
- 门禁只是报告中的“已检查”；
- 用户只能通过聊天窗口使用系统；
- Agent 可以绕过审批修改文件或调用外部系统。

AI FDE Builder 需要解决的不是让 Agent 更会说话，而是让未经证明的产物无法进入下一阶段。

### 1.2 系统边界

AI FDE Builder 包含三个相互连接但权限分离的平面：

| 平面 | 职责 |
|---|---|
| 构建控制平面 | 需求、数据产品、Ontology、模型、应用的构建、验证和发布 |
| Ontology 运行平面 | 业务对象、状态、预测、方案、权限和业务查询 |
| 业务应用与反馈平面 | 用户日常工作、审批、Action、回执和结果反馈 |

它不是单一聊天机器人，也不是拥有全部权限的超级 Agent。

### 1.3 设计参考

- [AI FDE 工程结构复刻项目需求与系统设计](2026-08-10-ai-fde-engineering-requirements-design.md)
- [Palantir-like 工程公式](../../../wiki/14-Palantir-like工程公式.md)
- [Ontology-AI 方法论实施计划](2026-08-10-ontology-ai-methodology.md)

## 2. 目标与非目标

### 2.1 产品目标

- 把 FDE 工作拆成有输入、输出、证据、门禁和审批点的阶段；
- 将 Agent 输出固化为可版本化工程产物；
- 对关键 Claim 建立证据追踪；
- 用 RDFS/OWL、SHACL、数据质量和代码运行保证工程可执行；
- 用 Challenger 和反例阻止表面化结论；
- 通过 Git Diff、审批、回滚和审计完成交付；
- 将已构建系统嵌入业务用户的工作流；
- 让实际结果和用户反馈回到后续改进。

### 2.2 非目标

MVP 不承诺：

- 复刻 Palantir Foundry 或 AIP 的全部产品；
- 自动连接所有企业系统；
- 自动决定业务语义；
- 无审批写入生产系统；
- 在没有历史标签时伪造预测能力；
- 用一个 Agent 替代所有工程和业务角色；
- 一开始建设企业级实时总线、多租户和 Kubernetes 平台。

## 3. 设计原则

### P1：决策优先

从“谁在什么场景下做什么决策”开始，不从“有哪些数据”或“使用什么模型”开始。

### P2：Artifact-first

Agent 的工作结果必须是工程产物；聊天记录只能作为运行日志和辅助证据。

### P3：Evidence-first

没有证据的内容只能标记为假设或未知，不能写成业务事实。

### P4：门禁是状态机

门禁不是项目末尾的 QA 清单，而是阶段推进的必要条件。

### P5：构建与运行分离

AI FDE 负责构建和改进系统；业务用户使用已经发布的 Ontology 应用。

### P6：描述、计算、执行分离

| 层 | 技术职责 |
|---|---|
| 语义描述 | RDFS/OWL |
| 结构约束 | SHACL |
| 血缘与时间 | Provenance、时间语义 |
| 数据计算 | SQL、Python、Polars、DuckDB |
| 机器学习 | ML Runtime |
| 决策优化 | 规则引擎、OR-Tools 或其他 Solver |
| 审批与写回 | Workflow、Policy、Action Runtime |

### P7：AI 先提案，系统后执行

Agent 可以读取、分析、生成 Diff 和模拟执行；真实写入和高风险 Action 必须经过策略和审批。

### P8：失败显式化

证据不足、来源冲突、粒度不明、标签缺失或方案不可行时，系统必须阻断或降级，不能静默猜测。

## 4. 核心工程对象

| 对象 | 含义 | 必要字段 |
|---|---|---|
| Project | 业务工程 | project_id、Owner、范围、版本、状态 |
| UseCase | 业务用例 | 用户、决策、触发、动作、结果 |
| Stage | 工程阶段 | 输入、产物、门禁、状态 |
| StageRun | 阶段运行 | Agent、工具、输入、输出、结果 |
| Artifact | 工程产物 | 类型、版本、Owner、依赖、状态 |
| Evidence | 原始证据 | 来源、位置、哈希、采集时间、权限 |
| Claim | 事实或推断 | 类型、内容、证据、负责人、验证状态 |
| GateDefinition | 门禁定义 | 阶段、严重性、验证器、通过条件 |
| GateRun | 门禁运行 | 版本、输入、结果、失败项、时间 |
| ChangeSet | 变更集合 | Diff、影响、审批、回滚 |
| Approval | 人工批准 | 人员、范围、意见、时间 |
| Function | 类型化计算 | 输入、输出、权限、实现 |
| Prediction | 预测产物 | 对象、时点、目标、概率、模型版本 |
| CandidatePlan | 候选方案 | 目标、变量、约束、结果 |
| Action | 业务动作 | 参数、审批、幂等、回执 |
| Feedback | 反馈 | 实际结果、用户行为、系统日志 |

## 5. 总体架构

    业务资料与目标
             ↓
    证据与知识层
             ↓
    Agent 编排层
             ↓
    工程产物层与 Git
          ↙       ↘
    语义校验层   计算运行层
          ↘       ↙
    应用、审批与 Action
             ↓
    结果、反馈与运营
             ↓
    重新进入 Agent 编排层

### 5.1 证据与知识层

职责：

- 登记原始资料；
- 保存不可变文件和哈希；
- 解析文本、表格和结构化记录；
- 保留页码、行号、表格单元格和字符位置；
- 管理实体别名、术语和来源优先级；
- 提供带权限的检索；
- 记录事实、推断、假设和未知。

原始证据不得被 Agent 直接覆盖。

### 5.2 Agent 编排层

职责：

- 判断当前阶段；
- 检查前置产物；
- 生成任务契约；
- 调度 Builder、Challenger 和专业工具；
- 汇总门禁结果；
- 触发人工审批；
- 创建下一阶段任务。

编排 Agent 没有发布权限。

### 5.3 工程产物层

职责：

- 保存结构化工程产物；
- 管理版本、依赖和状态；
- 生成 Git Diff；
- 记录产物关系；
- 支持回滚和影响分析。

### 5.4 语义校验层

职责：

- 运行 RDFS/OWL；
- 运行 SHACL；
- 检查对象、关系、状态和权限；
- 检查数据映射；
- 检查模型、预测和方案关联；
- 保存语义版本。

### 5.5 计算运行层

职责：

- 运行数据管道；
- 构造指标和特征；
- 训练、评估和推理；
- 运行优化和规则引擎；
- 支持历史回放和场景模拟。

### 5.6 应用与 Action 层

职责：

- 展示业务对象；
- 展示证据和解释；
- 允许用户修改参数；
- 生成候选方案；
- 发起审批；
- 执行模拟或真实 Action；
- 接收外部系统回执。

## 6. 工程生命周期与阶段产物

| 阶段 | 目标 | 主要产物 | 关键门禁 |
|---|---|---|---|
| 0. 立项 | 定义目标和范围 | ProjectCharter、ValueHypothesis | 现实业务 |
| 1. 决策筛选 | 找到高价值决策 | DecisionCandidate、DecisionContract | 决策真实性 |
| 2. 工作流观察 | 观察真实工作方式 | WorkflowObservation、ExceptionPath | 案例和异常 |
| 3. 需求提炼 | 形成可执行需求 | FunctionalRequirement、OpenQuestion | 证据覆盖 |
| 4. 方案设计 | 设计对象和交互 | SolutionDesign、ObjectModel | 语义完整 |
| 5. 数据登记 | 盘点数据和权限 | SourceAsset、FieldProfile | 数据源可用 |
| 6. 数据产品 | 建立稳定管道 | DataProduct、Expectation | 质量和血缘 |
| 7. Ontology | 建立业务语义 | OntologyModel、SHACL | 语义门禁 |
| 8. 分析建模 | 形成指标、特征、标签 | Metric、Feature、Label | 时间正确 |
| 9. 预测决策 | 预测和比较方案 | Model、Prediction、DecisionProblem | 回放和约束 |
| 10. 应用交付 | 嵌入用户流程 | Application、Function、Action | 用户验收 |
| 11. 运营反馈 | 观察结果并改进 | Feedback、Evaluation、ChangeRequest | ROI、漂移、审计 |

阶段状态：

    DRAFT
    → VALIDATING
    → CHALLENGING
    → DOMAIN_REVIEW
    → APPROVED
    → RELEASE_CANDIDATE
    → RELEASED

失败状态：

    VALIDATING 或 CHALLENGING 失败
    → REMEDIATION 或 BLOCKED
    → 修复后重新运行

## 7. 门禁控制系统

### 7.1 总原则

- 所有阶段转换必须经过 Gate Engine；
- 所有 Agent 产物先处于 draft 或 proposed；
- Builder 不能批准自己的产物；
- 硬门禁失败时阶段必须阻断；
- 门禁结果绑定产物哈希、输入快照和 Validator 版本；
- 产物、数据、规则或 Validator 变化后旧结果自动失效；
- 软门禁允许有期限的人工豁免；
- 硬门禁不允许被 Agent 静默豁免。

### 7.2 门禁类型

| 编号 | 类型 | 主要检查 |
|---|---|---|
| G0 | 现实业务 | 用户、决策、触发、动作、结果、Owner |
| G1 | 证据 | Claim、来源、位置、时间、相关性、冲突 |
| G2 | 语义 | 类型、粒度、业务键、状态、时间、权限、用途 |
| G3 | 数据 | 主键、完整性、时间、身份、延迟、重复、敏感字段 |
| G4 | 可执行 | 管道、SQL、SHACL、特征、模型、优化、Function、Action |
| G5 | 对抗 | 正常、异常、缺失、冲突、泄漏、权限、失败、参数变化 |
| G6 | 业务验收 | 领域语义、任务完成、推荐采纳、业务基线 |
| G7 | 发布治理 | 审计、版本、回滚、审批、监控、责任人 |

### 7.3 GateDefinition 必要字段

| 字段 | 说明 |
|---|---|
| gate_id | 门禁唯一标识 |
| stage_id | 适用阶段 |
| artifact_kind | 适用产物类型 |
| severity | hard 或 soft |
| validator | 执行器、入口和版本 |
| inputs | 所需输入产物和快照 |
| pass_condition | 通过条件 |
| failure_policy | 阻断、警告或降级 |
| evidence_required | 是否需要证据 |
| human_approval_required | 是否需要人工批准 |
| expiry_policy | 何时失效 |

### 7.4 GateRun 必要字段

| 字段 | 说明 |
|---|---|
| gate_run_id | 运行标识 |
| gate_id | 门禁标识 |
| artifact_id | 被检查产物 |
| artifact_hash | 产物哈希 |
| evidence_snapshot_id | 证据快照 |
| validator_version | 验证器版本 |
| result | passed、failed、blocked、pending |
| failures | 失败编码、严重性、证据和修复 |
| executed_by | 执行者 |
| executed_at | 执行时间 |
| expires_at | 失效时间 |

### 7.5 阶段转换控制

阶段转换必须执行：

    提交转换请求
    → 读取阶段和产物
    → 检查依赖
    → 执行硬门禁
    → 执行 Challenger
    → 检查人工审批
    → 检查权限策略
    → 检查产物哈希
    → 写入 StageTransition
    → 更新阶段状态

任何硬门禁失败，必须返回阻断原因和修复任务。

### 7.6 门禁自身的元测试

平台必须测试：

- API、CLI、Git 和 Agent 是否可以绕过失败门禁；
- 门禁通过后修改产物是否导致结果失效；
- 修改 Validator 版本是否导致旧结果失效；
- 无权用户是否无法批准和执行；
- 相同输入能否得到可复现结果；
- Validator 异常时是否阻止错误放行。

## 8. Agent 体系

### 8.1 核心角色

| 角色 | 责任 | 发布权 |
|---|---|---|
| Orchestrator | 阶段编排、任务分配 | 无 |
| Builder | 生成候选工程产物 | 无 |
| Challenger | 反证、找缺口、找反例 | 无 |
| Deterministic Verifier | 运行代码和规则校验 | 无 |
| Domain Owner | 确认业务语义和结果 | 指定范围 |
| Release Owner | 最终发布 | 受策略控制 |

专业能力包括：

- Decision Analyst；
- Workflow Analyst；
- Data Product Engineer；
- Ontology Engineer；
- Feature Engineer；
- Model Engineer；
- Optimization Engineer；
- Application Engineer；
- Release Engineer。

### 8.2 任务契约

任务契约必须包含：

| 字段 | 内容 |
|---|---|
| task_id | 任务标识 |
| objective | 目标 |
| stage_id | 当前阶段 |
| actor | Agent 或人工角色 |
| allowed_evidence | 允许使用的证据 |
| required_output | 必须产出 |
| forbidden_assumptions | 禁止假设 |
| acceptance_tests | 验收检查 |
| escalation_conditions | 必须升级人工的问题 |

### 8.3 Agent 输出规范

Agent 必须返回：

- 候选结论；
- 证据引用；
- 生成产物；
- 修改 Diff；
- 未决问题；
- 验证结果；
- 风险；
- 下一步。

不能只返回无结构的自然语言报告。

## 9. 工具网关与权限

### 9.1 工具访问级别

| 级别 | 能力 | 示例 |
|---|---|---|
| Read | 只读分析 | 搜索证据、读取对象、数据画像 |
| Propose | 生成 Diff | 修改需求、Ontology、模型配置 |
| Validate | 执行验证 | SHACL、SQL、回放、质量检查 |
| Approve | 人工批准 | 阶段通过、发布候选 |
| Execute | 执行 Action | 写入业务系统、发送通知 |

Agent 默认只有 Read、Propose 和 Validate 权限。

### 9.2 工具调用审计

每次调用必须记录：

- call_id；
- actor；
- project_id；
- stage_id；
- tool_id；
- input_hash；
- output_artifact_id；
- policy_decision；
- 起止时间；
- 错误和重试。

### 9.3 Action Broker

所有 Action 经过：

    用户请求
    → 权限检查
    → 参数 Schema
    → 审批策略
    → 幂等检查
    → 模拟或真实执行
    → 外部回执
    → ActionOutcome
    → Feedback

MVP 默认只允许模拟执行。

## 10. 使用者交互形态

### 10.1 FDE 工程工作台

关注：

- 阶段；
- 产物；
- Diff；
- 证据；
- 门禁；
- Git；
- 交付。

### 10.2 领域专家审查工作台

关注：

- 对象是否真实；
- 状态是否正确；
- 指标是否有意义；
- 方案是否符合业务规则；
- 是否批准阶段转换。

### 10.3 业务运行应用

关注：

- 当前任务；
- 风险；
- 预测；
- 候选方案；
- 审批；
- Action 结果。

### 10.4 Chat 的定位

Chat 负责：

- 查询上下文；
- 启动阶段任务；
- 请求生成候选；
- 解释证据；
- 请求澄清；
- 组织多个工具。

Chat 不是事实源。事实存储在 Artifact、Evidence、Ontology、GateRun、Approval 和 ActionOutcome 中。

### 10.5 项目驾驶舱

必须展示：

- 当前阶段；
- 门禁通过数和失败数；
- 待确认问题；
- 数据质量；
- Ontology 变更；
- 模型评估；
- 用户验收；
- Git 变更；
- 风险和阻塞。

### 10.6 回放实验室

用户可以选择历史时点，使用当时可见数据重新运行：

    业务状态
    → 特征快照
    → 预测
    → 候选方案
    → 用户修改参数
    → 重新优化
    → 模拟 Action

## 11. Palantir-like 三循环嵌入

### 11.1 构建循环

    业务目标
    → 决策契约
    → 工作流
    → 数据产品
    → Ontology
    → 模型
    → 应用
    → 门禁
    → 发布

AI FDE 服务 FDE 和工程团队。

### 11.2 运行循环

    业务事件
    → Ontology 状态变化
    → 分析和预测
    → 候选方案
    → 用户审批
    → Action
    → 外部系统回执

业务人员使用业务应用，不直接操作构建控制台。

### 11.3 学习循环

    实际结果
    → 用户采纳或拒绝
    → Action 成功或失败
    → 预测误差
    → 数据漂移
    → 需求变化
    → 重新进入构建循环

## 12. 工程目录

    ai-fde-builder/
    ├── platform/
    │   ├── schemas/
    │   ├── agents/
    │   ├── tools/
    │   ├── validators/
    │   ├── policies/
    │   ├── gate_engine/
    │   ├── artifact_registry/
    │   └── runtime/
    ├── projects/
    │   └── software-delivery-demo/
    │       ├── charter/
    │       ├── evidence/
    │       ├── requirements/
    │       ├── workflow/
    │       ├── data_products/
    │       ├── ontology/
    │       ├── analytics/
    │       ├── features/
    │       ├── models/
    │       ├── decisions/
    │       ├── applications/
    │       ├── actions/
    │       ├── evaluations/
    │       └── releases/
    ├── tests/
    │   ├── gates/
    │   ├── schemas/
    │   ├── replay/
    │   └── fixtures/
    ├── docs/
    └── pyproject.toml

## 13. 推荐技术栈

| 能力 | MVP 方案 |
|---|---|
| 编排 | Python、Pydantic、自定义 Stage Runner |
| 证据元数据 | SQLite |
| 文件存储 | 本地目录或对象存储兼容层 |
| 查询 | DuckDB、Polars |
| 数据管道 | Python，后续接 Dagster |
| RDF | RDFLib |
| SHACL | pySHACL |
| 血缘 | 自建 Provenance 表 |
| 机器学习 | scikit-learn、XGBoost |
| 模型管理 | MLflow 或本地模型目录 |
| 优化 | OR-Tools |
| API | FastAPI |
| 原型界面 | Streamlit |
| 工作流 | 状态机，后续接 Temporal |
| 测试 | pytest、契约测试、回放测试 |
| 版本控制 | Git |
| LLM | 可替换的 OpenAI-compatible API 或本地模型 |

## 14. 安全与治理

- 原始资料按权限读取；
- 敏感字段默认脱敏；
- Agent 只获得当前任务所需上下文；
- 证据检索记录访问日志；
- 生产凭据不进入 Agent Prompt；
- Action 使用短期、最小权限凭据；
- 所有变更先进入分支；
- 重要产物必须人工审查；
- 发布必须有回滚版本；
- GateRun 不可覆盖，只能生成新结果；
- 规则、模型、Ontology 和 Action 都必须版本化。

## 15. 失败处理

| 失败类型 | 系统行为 |
|---|---|
| 证据缺失 | 标记 unknown，生成调查任务 |
| 来源冲突 | 生成 DataIssue，阻断关键字段 |
| Schema 失败 | 不允许进入下一阶段 |
| SHACL 失败 | 阻断 Ontology 发布 |
| 数据质量失败 | 隔离记录，按策略阻断或降级 |
| 模型无标签 | 转为数据采集和分析任务 |
| 预测效果不足 | 保留基线，不发布预测模型 |
| 优化不可行 | 展示冲突约束，不强行推荐 |
| Action 失败 | 重试、补偿或人工处理 |
| Agent 超时 | 保留 StageRun，允许恢复 |
| 工具异常 | 记录失败，不生成伪造结果 |

## 16. 测试与验收

### 16.1 平台级硬验收

- 失败硬门禁无法被 API、CLI 或 Agent 绕过；
- 修改产物后旧门禁结果自动失效；
- 证据缺失的 Claim 无法升级为 Fact；
- Agent 无法直接执行未授权 Action；
- 所有阶段都能回放；
- 失败任务可以重试；
- 所有变更都有 Git Diff；
- 所有发布都有回滚路径。

### 16.2 质量指标

| 指标 | 目标 |
|---|---|
| 关键 Claim 证据覆盖率 | 100% |
| 硬门禁绕过率 | 0 |
| 关键产物 Schema 通过率 | 100% |
| 门禁结果可复现率 | 100% |
| 失败任务可定位率 | 100% |
| Action 幂等性测试 | 100% |
| 关键场景回放成功率 | 不低于 95% |
| 业务 Owner 审批覆盖率 | 100% |
| 发布产物可回滚率 | 100% |

### 16.3 表面化检测

系统必须定期检测：

- 产物是否只有叙述而没有执行物；
- 对象是否没有来源；
- 关系是否没有业务用途；
- 预测是否没有真实标签；
- 方案是否没有约束；
- 用户是否没有实际使用；
- Agent 是否频繁输出无结论调查报告；
- Challenger 是否总是无条件通过。

## 17. MVP 分阶段

### M0：产物与门禁内核

实现 Artifact Registry、StageRun、GateDefinition、GateRun、Claim/Evidence、Git Diff、Schema 验证和状态机。

### M1：需求与 Ontology 构建

实现决策契约、工作流观察、需求提炼、RDFS、SHACL、对象关系映射和 FDE 工程工作台。

### M2：数据产品与预测

实现模拟数据源、数据质量、历史快照、特征、工期预测和回放实验室。

### M3：决策、应用与模拟 Action

实现方案优化、需求变更工作台、Sprint 重排、审批、Mock Action 和反馈回写。

### M4：运营与复制

实现漂移检测、业务结果评估、反馈驱动变更、用例模板和新项目初始化。

## 18. 开放问题

1. 第一版 LLM 使用远程 API、局域网模型还是完全本地模型；
2. 是否需要多人并行审批；
3. Git 是否作为所有工程产物的唯一版本源；
4. RDF 存储使用 RDFLib 文件、Jena 还是关系数据库；
5. 是否将 Streamlit 作为第一版唯一界面；
6. 样板项目是否只模拟 Action，不连接真实 Jira 或 GitHub；
7. 预测模型是否同时支持任务级和 Sprint 级预测；
8. 是否记录用户每一次手工修改作为训练反馈。

## 19. 设计结论

AI FDE Builder 的本质是：

    工程产物系统
    + 证据系统
    + 门禁系统
    + Agent 编排系统
    + Ontology/计算运行时
    + 用户工作流系统
    + 反馈系统

最重要的不是 Agent，而是：

    状态不可绕过
    证据不可伪造
    验证不可省略
    审批不可隐式
    结果不可丢失

## 20. MVP 实现决策记录

### 20.1 ReleasePackage 与 Gate Engine 的绑定

发布服务不接受调用方提交的“已通过”布尔值、GateRun 列表或审批列表作为权威输入。`ReleaseManager.build(project_id, artifact_ids)` 首先从不可变 Artifact Registry 读取工件，再由 Gate Engine 找到包含这些工件的阶段运行，并要求阶段已经到达 `release_candidate`。随后它再次请求 Gate Engine 判断到 `released` 的转换是否允许，只有通过后才执行唯一的状态转换路径。

ReleasePackage 固化：

- 工件 ID 与发布时的内容哈希；
- 实际参与发布决策的 GateRun ID；
- 阶段转换审计 ID（作为当前 MVP 的 approval ID）；
- 工具版本和策略版本；
- 每个工件的前一版本、前一版本哈希和前一发布包引用。

这样，发布包不是一份“发布说明”，而是可以重新核验的 provenance manifest。

### 20.2 回滚是追加写入，不是删除或覆盖

回滚先把发布阶段通过 Gate Engine 转回 `remediation`，再在 Registry 事务中为每个工件追加一个新的 patch 版本，将内容恢复为清单中的前一版本。历史版本、原发布包、原 GateRun 和回滚审计 ID 均保留。新版本的哈希变化会使依赖旧工件的 GateRun 失效，系统必须重新验证后才能再次发布。

### 20.3 Feedback 是运行事实

`FeedbackService` 只接受类型化 `Feedback`，按 `feedback_id` 追加写入；重复身份拒绝，返回值和查询结果都经过深拷贝，调用者不能通过修改返回对象篡改历史。Feedback 因此可以承接人工采纳、拒绝、Action 结果和实际业务结果，作为后续特征、模型和需求迭代的输入，而不是被埋在聊天记录里。

### 20.4 绕过路径测试

API、CLI 和 `StageRunner` 都只能调用 Gate Engine 的状态转换接口。测试明确覆盖：失败硬门禁不能被直接发布，不能被 CLI 转换，也不能被编排器转成批准状态；HTTP 层还要求可信 Actor 身份。该约束是结构性约束，不依赖 Agent 的自律。
