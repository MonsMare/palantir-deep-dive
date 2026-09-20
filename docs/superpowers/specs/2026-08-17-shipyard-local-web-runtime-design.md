# Shipyard Local Web Runtime 设计

日期：2026-08-17
状态：设计草案，已获准起草，待用户审阅
范围：AI-FDE Shipyard 的本地 Web 运行与部署方式，不包含客户生产运行时的实现

## 1. 执行摘要

AI-FDE Shipyard 的定位是“建造业务决策系统的船坞”，而不是客户侧持续预测、推荐和执行动作的“轮船”本身。

本设计确定一个 Local Web Runtime 作为 Shipyard Workbench 的第一部署形态：

~~~text
浏览器
  → Shipyard Workbench
  → Shipyard API / Application Service
  → Agent Run / Evaluator / Gate / Release
  → DecisionSystemRelease
  → 交付到客户环境的业务决策系统
~~~

用户通过浏览器进入本机或内网中的 Workbench，围绕 Workspace、Decision Case、Evidence、Ontology、Data Product、Model、Decision、Evaluation、Gate 和 Release Candidate 工作。Agent 的工作结果只能以提案、证据和验证记录进入系统；只有 Application Service 可以改变项目状态、接受提案、记录门禁结果和创建发布候选。

本方案借鉴 DeepSeek Harness 的“本地进程 + Web UI + 工作区 + 受控工具/审批”交互形态，但不复刻其内部实现。DeepSeek Harness 官方文档说明其 Web UI 可在本地启动，默认使用 127.0.0.1:3080，并以 workspace 作为 Agent 的文件操作边界；其架构也把模型适配器、工具、持久化、沙箱、审批策略、设置和凭据等能力组织成可组合的插件树。相关事实以官方仓库、用户指南和架构文档为准：

- [DeepSeek Harness 官方仓库](https://github.com/deepseek-ai/deepseek-harness)
- [DeepSeek Harness Web UI 指南](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/user/guide/index.md)
- [DeepSeek Harness 架构说明](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/architecture.md)

Shipyard 的关键差异是：它的中心不是通用编码 Agent，而是面向业务决策系统交付的证据链、Ontology、数据产品、评测、门禁和发布包。

## 2. 背景与问题

当前仓库已经具备若干可复用的 Shipyard 内核：

- Shipyard Application Service；
- Workspace、Decision Case、Artifact、Proposal、Gate Review、Audit 和 Release Candidate 的领域对象；
- SQLite Registry；
- Ontology、数据产品、特征、模型和决策构建模块；
- Gate Engine、Evaluation 和 Release Dock 的部分能力；
- React Workbench 前端；
- FastAPI 应用工厂；
- 本地 seed 脚本和软件交付示例。

但是，这些能力还缺少一个清晰的部署组合根（composition root）。当前用户需要理解多个服务、脚本和目录才能进入 Workbench；前端、API、运行编排、文件工作区、数据库、模型端点和沙箱之间也没有统一的启动契约。

因此需要一个部署设计来解决以下问题：

1. 用户能否通过一条命令启动完整的本地 Workbench？
2. 浏览器交互如何复用现有 Application Service，而不是绕过领域内核？
3. Agent 运行失败、进程重启、模型不可用或门禁不通过时，如何保持可审计和可恢复？
4. 本地部署如何演进到团队内网、客户现场和无浏览器 CI，而不重写核心业务逻辑？
5. 如何保证“本地 Web 便利性”不会变成任意插件、任意网络访问或任意生产动作的安全后门？

## 3. 设计目标

### 3.1 第一优先级目标

- 提供一个本地浏览器入口，让用户可以查看和操作完整的 Shipyard 构建生命周期；
- 使用现有 Application Service 作为所有状态变更的唯一授权入口；
- 支持 Workspace 选择、项目阶段、Artifact、Agent Run、Gate Review、Audit 和 Release Candidate 的统一视图；
- 让 Agent 以异步 Run 的方式执行，并能展示日志、提案、证据、变更和验证结果；
- 让用户在同一界面中完成“查看证据 → 审阅提案 → 运行门禁 → 生成发布候选”的闭环；
- 本地默认离线友好，模型端点和外部连接由显式配置开启；
- 同一套领域服务可以被 Web、CLI、CI 和未来的团队部署复用；
- 为后续 Docker、PostgreSQL、对象存储、消息队列、身份系统和客户现场连接器预留清晰边界。

### 3.2 第二优先级目标

- 支持本地项目目录与 Shipyard Registry 之间的稳定映射；
- 支持进程重启后的 Run、事件和 Artifact 状态恢复；
- 支持插件能力白名单、版本、哈希和兼容性检查；
- 支持 headless profile，使 CI 可以无浏览器地执行同一套构建和评测；
- 支持把交付包导出为可部署、可审计、可回滚的 DecisionSystemRelease。

## 4. 非目标与边界

第一版 Local Web Runtime 不实现以下能力：

- 客户生产环境中的实时预测、决策或业务动作执行；
- 将 Agent 直接连接到客户 ERP、财务系统、生产队列或审批系统；
- 通过自然语言对话直接跳过 Gate 或改变发布状态；
- Linear 作为核心人机交互入口；
- 面向多租户 SaaS 的完整计费、组织和跨客户隔离；
- 不受限制的任意 shell、任意网络访问和任意插件安装；
- 第一版就完成高可用集群、分布式调度和跨地域容灾；
- 用 Docker 代替领域内核的部署设计。Docker 只是一种交付载体，不是安全或质量边界；
- 用聊天记录代替 Artifact、Evidence、Evaluation 和 Audit；
- 把 Shipyard 自身的 Agent 当作客户侧业务决策 Agent。

### 4.1 构建面与运行时分离

~~~text
Shipyard 构建面
  负责：发现、建模、接入、评测、门禁、打包、升级

客户业务决策运行时
  负责：接收业务数据、计算特征、预测、生成候选动作、请求授权、执行动作、回写反馈
~~~

两者通过版本化的 DecisionSystemRelease、运行配置和 Feedback Contract 连接。Shipyard 可以在沙箱或回放环境中模拟运行时，但不能因为模拟成功就宣称已经具备客户生产运行时能力。

## 5. 核心设计原则

### 5.1 Workbench 优先，聊天作为侧边能力

主界面必须围绕项目阶段和工程产物组织。聊天面板只负责解释当前上下文、发起受控提案、展示 Agent 运行和帮助用户定位证据，不能成为唯一的项目状态入口。

### 5.2 产物优先，而不是对话优先

每次 Agent Run 至少产生以下结构化结果：

- Run 身份、输入快照和执行配置；
- Proposal 或明确的 blocked 状态；
- 使用的 Artifact 和 Evidence；
- 变更摘要；
- 验证器、评测结果和违规项；
- 待人类决定的问题；
- 输出的版本和内容哈希；
- 审计事件。

自然语言解释可以作为可读层，但不能替代上述结构化记录。

### 5.3 Application Service 是唯一写入边界

前端、Agent、Worker、插件和 CLI 都不能直接修改项目状态。它们只能调用领域服务提交命令或 Proposal，由 Application Service 进行：

- Principal 解析；
- Workspace 授权；
- 当前版本检查；
- 并发和冲突检查；
- Gate 前置条件检查；
- 内容和血缘校验；
- 审计事件追加；
- 状态迁移。

### 5.4 Gate 是事实门槛，不是流程装饰

一个阶段完成不等于某个 Agent Run 成功。只有绑定到当前输入版本、验证器版本、Evidence 和 Artifact 内容的 Gate Review 通过，项目才允许进入下一阶段或生成 Release Candidate。

### 5.5 默认安全，显式扩权

本地默认只绑定 127.0.0.1，网络访问默认关闭，工作区外文件默认不可见，生产 Action 永不由 Shipyard Agent 直接执行。任何跨出默认边界的能力都必须由配置、权限、日志和用户确认共同打开。

### 5.6 先做垂直闭环，再扩展平台能力

第一条可交付链路应当是：

~~~text
创建 Workspace
  → 导入证据
  → 生成 Ontology / Data Product / Model / Decision 提案
  → 运行 Evaluator
  → Gate Review
  → 生成 Release Candidate
  → 导出 DecisionSystemRelease
~~~

只有这条链路可运行、可恢复、可审计后，才扩展更多 Agent、插件和部署模式。

## 6. 总体架构

### 6.1 逻辑架构

~~~mermaid
flowchart LR
    USER[领域专家 / FDE / 模型工程师 / 发布负责人]
    BROWSER[浏览器]
    WEB[Shipyard Web Workbench]
    API[Shipyard API Gateway]
    APP[Shipyard Application Service]
    ORCH[Run Orchestrator]
    WORKER[Agent Worker / Builder Worker]
    SANDBOX[Sandbox / Connector Boundary]
    REG[Registry]
    STORE[Artifact Store]
    EVAL[Evaluator]
    GATE[Gate Engine]
    REL[Release Dock]
    PKG[DecisionSystemRelease]
    MODEL[Model Gateway]
    AUDIT[Audit Event Log]

    USER --> BROWSER
    BROWSER --> WEB
    WEB --> API
    API --> APP
    APP --> REG
    APP --> STORE
    APP --> ORCH
    ORCH --> WORKER
    WORKER --> SANDBOX
    WORKER --> MODEL
    WORKER --> STORE
    WORKER --> APP
    APP --> EVAL
    EVAL --> GATE
    GATE --> APP
    APP --> REL
    REL --> PKG
    APP --> AUDIT
    REG --> EVAL
    STORE --> EVAL
~~~

### 6.2 关键边界

| 边界 | 允许的责任 | 不允许的责任 |
| --- | --- | --- |
| 浏览器 → API | 展示、发起命令、订阅运行状态、提交人类评审 | 直接写数据库、直接执行 shell |
| API → Application Service | 身份、参数和请求转换 | 在路由中复制领域规则 |
| Application Service → Registry | 经过授权的状态持久化 | 接受 Agent 自报的 passed、approved 或 release-ready |
| Orchestrator → Worker | 分配 Run、限制资源、收集结果 | 直接改变发布状态 |
| Worker → Sandbox | 读取允许的工作区、运行受限工具、生成证据 | 任意读取宿主机、任意出网、执行客户生产动作 |
| Evaluator → Gate | 基于真实输入重建结果、输出验证事实 | 只信任调用方携带的状态 |
| Release Dock → Release | 打包已通过门禁的版本 | 绕过 Gate 生成可交付版本 |
| Model Gateway → Agent | 提供模型推理 | 直接修改业务状态或发布状态 |

## 7. 部署形态

### 7.1 Local Profile：第一实现目标

Local Profile 运行在个人开发机或 FDE 工作站上：

~~~text
浏览器
  → 本地 Web 静态资源
  → 本地 FastAPI
  → 本地 Application Service
  → 本地 SQLite / 文件 Artifact Store
  → 本地 Worker / Sandbox
  → 可选的远程或本地模型端点
~~~

默认约束：

- API 绑定 127.0.0.1；
- 仅加载显式指定的 ProjectWorkspace；
- SQLite 数据库位于项目的 .shipyard 目录；
- Artifact 采用本地内容寻址目录；
- 外部连接器和网络工具关闭；
- 模型调用必须在配置中显式声明；
- 没有生产 Action 能力；
- 关闭窗口或重启进程后，已经持久化的事件、Artifact 和 Run 状态仍然保留。

Local Profile 的价值是低部署成本、适合单人 FDE 和本地数据，且不需要先搭建团队级基础设施。

### 7.2 Headless / CI Profile：无浏览器验证

Headless Profile 不启动 Web UI，使用相同的 Application Service、Evaluator、Gate Engine 和 Release Dock：

~~~text
CI / CLI
  → 命令或构建配置
  → Application Service
  → Builder / Evaluator / Gate
  → Release Candidate / 报告 / 退出码
~~~

Headless Profile 必须与 Local Profile 共享：

- Artifact 类型和版本规则；
- Gate 定义和验证器；
- 运行输入快照；
- Release Manifest；
- 审计事件结构；
- 失败和 blocked 语义。

这样可以避免“浏览器里看起来通过，但 CI 无法复现”的双重标准。

### 7.3 Team / On-Prem Profile：团队内网与客户现场

Team / On-Prem Profile 是本地 Web 形态的服务化扩展：

~~~text
浏览器
  → Reverse Proxy / TLS / Identity Provider
  → Web Static Server
  → Shipyard API
  → Run Orchestrator / Worker Pool
  → PostgreSQL
  → MinIO / S3-compatible Artifact Store
  → Redis / NATS 等可选队列
  → 内网模型网关和连接器
~~~

与 Local Profile 的主要变化：

- SQLite 替换为 PostgreSQL；
- 本地目录替换为对象存储；
- 单进程 Worker 替换为可恢复的 Worker Pool；
- Local Identity 替换为 OIDC、LDAP 或客户身份系统；
- 127.0.0.1 绑定替换为内网地址，但必须经过 TLS 和身份认证；
- Workspace owner-only 扩展为组织、项目、角色和资源级权限；
- 所有外部连接器都要求客户侧网络策略和审计批准。

这一形态属于后续部署阶段，不应为了第一版本地 Workbench 而提前引入所有分布式组件。

### 7.4 Hybrid Profile：构建面与客户侧连接器分离

当客户数据不能离开客户网络时，采用混合边界：

~~~text
FDE / 中央 Workbench
  → 构建计划、规则、模型包、评测协议
  → 客户侧 Connector Gateway
  → 客户数据抽取、特征计算、回放和结果摘要
  → 脱敏 Evidence / Metrics / Feedback 回传
~~~

客户侧连接器可以读取客户系统，但不能因此获得中央 Workbench 的全部权限。中央 Workbench 接收的是经过协议约束的快照、指标和证据，而不是默认接收所有原始数据。

## 8. Workbench 功能结构

### 8.1 项目总览

用户进入一个 Workspace 后首先看到：

- 项目目标和 Decision Case；
- 当前构建阶段；
- 阶段前置条件；
- 最近一次 Run；
- 当前阻断项；
- Gate 通过、失败和 stale 状态；
- 最近变更和待人类决定的问题；
- 当前可导出的 Release Candidate。

总览页不展示“Agent 已完成”这样的单一进度，而展示“哪些事实已经验证、哪些事实仍然缺失”。

### 8.2 阶段时间线

时间线对应 Shipyard 的工程生命周期：

~~~text
立项
  → 需求与决策发现
  → 证据整理
  → Ontology 建模
  → 数据产品构建
  → 分析 / 预测 / 决策模型
  → 应用和工作流
  → 回放与评测
  → Gate Review
  → Release Candidate
  → 交付与反馈协议
~~~

每个阶段至少显示：

- 输入 Artifact；
- 输出 Artifact；
- 当前版本；
- 责任角色；
- 依赖；
- Gate；
- 证据；
- 阻断原因；
- 可执行命令。

### 8.3 Artifact Explorer

Artifact Explorer 是 Workbench 的核心区域之一，用于按类型和血缘查看：

- Evidence Snapshot；
- Decision Contract；
- Ontology Candidate；
- Ontology Mapping；
- Data Product；
- Feature Definition；
- Label Definition；
- Model；
- Optimization Contract；
- Application；
- Evaluation Report；
- Release Manifest。

Artifact 页面必须同时显示内容和治理信息：

- 版本与内容哈希；
- 父版本和依赖；
- 来源和 Evidence 引用；
- 生产者；
- 最近一次验证；
- 验证器版本；
- 受哪些 Gate 约束；
- 是否 stale；
- 哪些下游产物会受影响。

### 8.4 Evidence 与数据产品视图

用户需要能够从一个对象或计算字段反向追踪：

~~~text
Release
  → Decision
  → Prediction / Optimization
  → Feature
  → Data Product
  → Source Snapshot
  → Evidence Fragment / 原始文件位置
~~~

数据产品视图重点展示：

- 数据粒度；
- 主键；
- 事件时间和可用时间；
- 延迟；
- 缺失处理；
- 去重规则；
- 质量检查；
- 字段血缘；
- 访问权限；
- 版本；
- 最近刷新；
- point-in-time 评测是否通过。

### 8.5 Gate Review

Gate 页面不只是一个“通过/不通过”按钮，而是一个审阅工作区：

- Gate 定义；
- 必需 Artifact；
- 当前输入快照；
- 验证器和定义指纹；
- 违规项；
- 证据；
- 运行日志；
- stale 原因；
- 上次通过版本；
- 当前版本与上次版本的差异；
- 人类评审意见；
- 接受、退回、拒绝和重新运行命令。

人类可以批准的是“由系统重建并绑定输入的验证事实”，而不是 Agent 自报的结论。

### 8.6 Run Console

Run Console 用于观察 Agent Run、Builder Run、Evaluation Run 和 Gate Run：

- Run 状态；
- 阶段和子任务；
- 输入版本；
- 输出 Proposal；
- 消耗的模型和工具；
- 日志和证据；
- 资源使用；
- 失败原因；
- 重试、取消和重新运行；
- 运行后产生的 Artifact。

日志可以实时流式展示，但必须在服务端追加后才成为审计事实。浏览器断开不能导致 Run 被悄悄丢失。

### 8.7 Release Dock

Release Dock 只允许从已通过必要 Gate 的 Artifact 集合创建候选发布包。它展示：

- Release Manifest；
- Ontology 版本；
- 数据产品版本；
- 模型和特征版本；
- 决策/优化合同；
- 应用和工作流配置；
- 评测报告；
- 安全与回滚配置；
- 依赖和兼容性；
- 未解决风险；
- 客户侧部署要求；
- 反馈协议。

第一版 Release Dock 只导出发布包，不把包自动部署到客户生产环境。

### 8.8 Assistant Sidecar

Assistant Sidecar 是上下文 Agent 入口，必须绑定当前 Workspace、Artifact、Run 或 Gate：

- “解释这个 Gate 为什么 blocked”；
- “从当前 Evidence 提出可能缺失的供应商延误特征”；
- “比较两个 Ontology 版本的语义变化”；
- “为当前 Data Product 生成字段血缘审查提案”；
- “运行一个只读的历史回放评测”；
- “根据当前失败项生成修复 Proposal”。

Sidecar 的输出应当进入 Proposal 或 Run，而不是仅停留在聊天记录中。对于改变状态的操作，Sidecar 只能生成命令预览或 Proposal，用户需要在结构化界面中确认。

## 9. 交互模型

### 9.1 三类交互

Workbench 中的交互分为三类：

| 交互类型 | 例子 | 是否改变系统事实 |
| --- | --- | --- |
| 查询 | 查看 Artifact、血缘、Gate、日志、差异 | 否 |
| 运行 | 启动 Builder、Evaluator、回放或 Gate | 创建可追踪 Run，可能产生候选产物 |
| 决定 | 接受 Proposal、退回修改、批准 Gate、创建 Release Candidate | 是，必须由 Application Service 授权并审计 |

自然语言输入属于“提出意图”的方式，不属于第四种绕过治理的状态类型。

### 9.2 Proposal 生命周期

~~~text
Draft
  → Submitted
  → Validating
  → NeedsHumanReview
  → Accepted / Rejected / Returned
  → Applied
~~~

任何 Proposal 都绑定：

- 提案者身份；
- Agent Profile；
- 输入 Artifact 版本；
- 证据引用；
- 预期变更；
- 预期验证器；
- 冲突基线；
- 提交时间；
- 内容哈希。

如果输入 Artifact 在审阅期间发生变化，Proposal 必须自动变为 stale，不能静默应用到新版本。

### 9.3 人类操作成本控制

为了降低人类操作成本，Workbench 应该优先提供：

- 批量查看同一 Gate 的所有阻断项；
- 一键跳转到证据原文；
- 变更影响图；
- “为什么不能发布”解释；
- 只展示需要人类决定的问题；
- 相同类型 Proposal 的批量比较；
- 失败 Run 的可重放入口；
- 从失败项生成修复 Run；
- 结构化表单和自然语言辅助并存。

降低操作成本不能通过减少证据或取消 Gate 实现，而应通过更好的聚合、排序、差异和上下文实现。

## 10. 本地启动与项目布局

以下命令是本设计建议的启动契约，标记为 proposed；在实现计划批准前不表示当前仓库已经提供这些命令。

### 10.1 建议命令

~~~text
shipyard init <project-directory>
shipyard web --profile local --host 127.0.0.1 --port 3080
shipyard run --profile headless --workspace <workspace-id> --stage <stage>
shipyard evaluate --workspace <workspace-id> --gate <gate-id>
shipyard export-release --workspace <workspace-id> --output <release-directory>
~~~

启动成功后：

1. 检查配置和数据库迁移；
2. 创建或加载本地 Registry；
3. 创建或加载 Artifact Store；
4. 初始化本地身份上下文；
5. 启动 API；
6. 启动本地 Run Orchestrator；
7. 注册允许的 Worker、Evaluator 和插件；
8. 托管或引用 Workbench 静态资源；
9. 输出本地 URL；
10. 可选地打开默认浏览器。

端口冲突、数据库锁、无效配置或迁移失败必须显式报错，不能悄悄绑定到一个用户未知的外部地址。

### 10.2 建议项目目录

~~~text
.shipyard/
  config.yaml
  schema-version
  shipyard.db
  artifacts/
    sha256/
  evidence/
  workspaces/
  runs/
  logs/
  releases/
  plugins/
  cache/
  secrets/
~~~

建议：

- shipyard.db 只保存结构化索引、状态和审计事件；
- 大型 Artifact、Evidence 和 Run 输出使用内容寻址文件；
- secrets 目录不进入 Git，并且应在实现阶段进一步接入操作系统凭据存储；
- 项目源码和客户原始数据不应因为启动 Workbench 而自动复制到另一处；
- 配置中只保存引用和策略，不把 API key 写入前端静态资源。

### 10.3 当前 seed 脚本的定位

现有 scripts/shipyard_seed.py 继续作为演示和测试数据初始化工具。它不是最终的 Web 启动器，也不承担：

- 启动前端；
- 启动 API；
- 管理 Worker 生命周期；
- 处理用户登录；
- 连接客户系统；
- 执行生产 Action。

后续实现应将“数据 seed”和“运行时启动”分成两个明确命令。

## 11. 配置模型

配置必须区分公开运行配置、受保护凭据和项目内容。

### 11.1 建议配置结构

~~~yaml
schema_version: 1

profile: local

server:
  host: 127.0.0.1
  port: 3080
  open_browser: true

storage:
  registry: sqlite
  database_path: .shipyard/shipyard.db
  artifact_store: filesystem
  artifact_path: .shipyard/artifacts

workspace:
  root: .
  allowed_roots:
    - .

orchestrator:
  mode: in_process
  max_parallel_runs: 2
  default_timeout_seconds: 1800

sandbox:
  filesystem: workspace_only
  network: deny
  production_actions: deny
  max_process_seconds: 900

model_gateway:
  provider: openai_compatible
  base_url_env: SHIPYARD_MODEL_BASE_URL
  api_key_env: SHIPYARD_MODEL_API_KEY
  default_model: configured-by-user

plugins:
  trusted_directories:
    - .shipyard/plugins
  allow:
    - core.builder
    - core.evaluator
    - core.release

auth:
  mode: local_owner
~~~

实际配置字段应在实现计划阶段结合现有 Python API、前端环境变量和测试约束细化。特别是 model_gateway 的 key 不能由浏览器直接读取。

### 11.2 配置校验

启动阶段必须验证：

- profile 是否存在；
- host 是否为允许值；
- storage 路径是否在用户明确的项目范围内；
- plugin 是否在可信目录且哈希匹配；
- sandbox 策略是否与 profile 兼容；
- model endpoint 是否可选且凭据未泄漏；
- 数据库 schema 是否需要迁移；
- 当前配置是否允许外部网络或生产 Action。

## 12. 一次完整的本地构建流程

### 12.1 启动阶段

~~~text
用户执行 shipyard web
  → 读取 profile
  → 创建 RuntimeContext
  → 加载 Registry / Artifact Store
  → 启动 Application Service
  → 加载插件和能力白名单
  → 启动 Orchestrator
  → 挂载 Web UI
~~~

RuntimeContext 是部署组合根，不应让每个路由、Agent 或插件自行创建数据库、模型客户端和文件根目录。

### 12.2 用户建立工作区

~~~text
用户选择项目目录
  → Workbench 检查目录边界
  → 创建或加载 ProjectWorkspace
  → 通过 Application Service 写入 owner 和配置
  → 追加 WorkspaceCreated 审计事件
~~~

工作区选择不能仅由前端传一个路径字符串决定。服务端必须解析真实路径、检查允许根目录并生成稳定的 Workspace 身份。

### 12.3 Agent 生成提案

~~~text
用户选择阶段和目标
  → Workbench 提交 StartRun
  → Application Service 创建 Run
  → Orchestrator 固化输入 Artifact 版本
  → Worker 在 Sandbox 中执行
  → Worker 产生 Proposal / Evidence / Validation
  → Application Service 持久化结果
  → Workbench 展示待审阅项
~~~

Agent 的输入必须包括当前上下文快照，而不是读取一个不断变化的工作区后自行决定基线。这样可以在重放和审计时准确知道 Agent 当时看到了什么。

### 12.4 人类审阅和应用

~~~text
用户打开 Proposal
  → 查看变化、证据、验证和影响范围
  → 接受 / 退回 / 拒绝
  → Application Service 再次检查基线版本和权限
  → 通过后写入 Artifact 新版本
  → 追加 ProposalAccepted / ArtifactCreated 事件
  → 触发相关下游 Gate stale
~~~

被接受的 Proposal 也不自动意味着 Gate 通过。Artifact 变化后必须重新运行受影响的验证器。

### 12.5 评测、门禁和发布

~~~text
用户启动 Evaluation
  → 读取绑定输入快照
  → 生成 Evaluation Run
  → Evaluator 重建特征、标签、预测或决策结果
  → Gate Engine 计算事实
  → Gate Review 绑定证据、输入哈希和验证器指纹
  → 所需 Gate 全部通过
  → Release Dock 组装 Release Manifest
  → 导出 DecisionSystemRelease
~~~

如果输入、验证器、Evidence 或 Artifact 发生变化，旧 Gate Review 应变为 stale，并阻止新的 Release Candidate 复用旧结果。

## 13. 事件和持久化模型

### 13.1 需要持久化的事实

至少持久化以下对象：

- Workspace；
- Decision Case；
- Artifact；
- Evidence；
- Proposal；
- Agent Run；
- Evaluation Run；
- Gate Review；
- Release Candidate；
- Audit Event；
- Plugin Manifest；
- Model Endpoint 配置的非敏感部分；
- Feedback Contract 和交付版本。

### 13.2 事件原则

关键生命周期采用追加式事件记录：

~~~text
WorkspaceCreated
ArtifactRegistered
ProposalSubmitted
RunStarted
RunProgressRecorded
RunCompleted
RunFailed
ProposalAccepted
ProposalReturned
GateRunCreated
GateReviewRecorded
GateReviewStaled
ReleaseCandidateCreated
ReleaseExported
~~~

事件应包含：

- event_id；
- event_type；
- aggregate_type；
- aggregate_id；
- aggregate_version；
- actor；
- timestamp；
- input_hash；
- payload；
- correlation_id；
- causation_id。

第一版可以继续使用 SQLite 的关系表和 JSON 字段，但事件和审计字段必须保持可查询、可导出和可重放。后续切换 PostgreSQL 或消息队列时，不应改变领域对象的语义。

### 13.3 Run 恢复

进程异常退出后，启动器应扫描未结束 Run：

- 没有 Worker 心跳但已超过超时：标记为 failed 或 stale；
- 有可重放输入且没有副作用：允许 retry；
- 已生成部分 Artifact：保留为临时或候选状态，不能自动提升为正式版本；
- 已进入人类审阅：恢复为原状态；
- 处于未知状态：默认 blocked，要求显式重新运行。

## 14. Agent、插件和能力治理

### 14.1 Agent 不是超级用户

Agent Profile 至少包括：

- profile_id；
- 角色；
- 可读取的 Artifact 类型；
- 可调用的工具；
- 可写出的 Proposal 类型；
- 模型配置；
- 最大 token、时间和并行额度；
- 是否允许网络；
- 是否允许执行代码；
- 必需的验证器；
- 允许的 Workspace 根目录。

Agent 不能拥有：

- 直接审批自身 Proposal 的权限；
- 修改 Gate definition 的权限；
- 直接创建 Release Candidate 的权限；
- 直接调用客户生产 Action 的权限；
- 绕过 Application Service 的数据库凭据。

### 14.2 插件契约

插件可以扩展：

- Source Connector；
- Evidence Extractor；
- Ontology Builder；
- Data Product Builder；
- Model Adapter；
- Evaluator；
- Gate；
- Release Exporter；
- Workbench 面板。

插件注册信息至少包括：

- plugin_id；
- version；
- api_version；
- content_hash；
- owner；
- capabilities；
- required_permissions；
- input/output artifact kinds；
- deterministic 或 nondeterministic 标记；
- 可用 profile；
- 兼容性范围。

插件加载前必须检查：

- 来源目录是否可信；
- 哈希是否匹配；
- API 版本是否兼容；
- 所需 capability 是否在 profile 白名单内；
- 是否需要用户确认；
- 是否允许访问工作区外文件或网络。

### 14.3 模型网关

所有模型调用通过 Model Gateway：

- Agent 不直接管理 provider secret；
- Gateway 记录模型、参数、版本和调用关联 ID；
- 支持远程 OpenAI-compatible endpoint、客户内网模型或本地模型；
- 可以设置脱敏、限额、超时和重试；
- 模型返回不直接成为领域事实，必须经过结构化解析和验证；
- 对同一输入需要可复现时，保存请求摘要、模型版本和响应哈希；
- 不可用或超时的模型只能产生 pending/blocked，不得产生“默认通过”。

## 15. 安全模型

### 15.1 网络边界

Local Profile：

- 默认仅绑定 127.0.0.1；
- 不默认接受局域网访问；
- 不默认允许 Agent 出网；
- 模型端点若在远端，必须由配置显式打开；
- 外部连接器要单独声明并记录。

Team / On-Prem Profile：

- 经过反向代理和 TLS；
- 接入客户身份系统；
- 按网络区划分 API、Worker、数据库、对象存储和连接器；
- 对外发出的请求和返回的摘要都要有审计；
- 客户侧数据最小化传输。

### 15.2 文件系统边界

- 工作区外路径默认拒绝；
- 符号链接解析后仍必须落在允许根目录；
- 临时目录和 Artifact Store 分离；
- 删除和覆盖操作默认禁止或需要用户确认；
- 文件上传要限制类型、大小和解压路径；
- 浏览器只能通过 API 访问文件，不能自行读取本地任意路径。

### 15.3 高风险能力

以下能力必须在第一版保持 deny：

- 修改客户生产系统；
- 发送外部通知；
- 删除客户数据；
- 部署客户运行时；
- 更改身份和权限；
- 任意安装插件；
- 任意执行宿主机命令。

未来若开放，必须通过独立的 Action Gateway、审批、幂等键、回滚协议和客户侧授权，不应直接把能力加到 Workbench Agent 上。

## 16. 失败与降级策略

| 故障 | 必须发生的结果 | 不允许的结果 |
| --- | --- | --- |
| Web UI 断开 | Run 继续或明确进入可恢复状态，用户重新连接后可查看 | Run 消失、状态只存在浏览器 |
| API 重启 | 从 Registry 恢复已持久化事实 | 把未确认的临时结果当正式结果 |
| Worker 崩溃 | Run failed/stale，关联 Proposal 不可直接应用 | 自动宣称完成 |
| 模型端点不可用 | Run pending/blocked，保留原因和输入 | 生成伪造预测或默认通过 |
| Evaluator 失败 | Gate blocked，保留日志和输入快照 | 复制上次 passed |
| Artifact 被修改 | 受影响 Gate stale | 继续复用旧 Gate |
| 数据库锁或写入失败 | 返回明确错误，不产生部分状态 | 前端显示成功但服务端未落盘 |
| 端口冲突 | 启动失败并提示处理方式 | 静默暴露到未知地址 |
| 插件哈希变化 | 插件拒绝加载或进入人工确认 | 无提示地运行新代码 |
| 文件超出工作区 | 读取/写入拒绝并审计 | 自动扩大根目录 |

系统采用 fail closed：无法验证时阻断发布，不以“看起来合理”代替验证事实。

## 17. 质量与验收标准

### 17.1 Local Web 启动验收

1. 执行初始化命令可以创建最小 .shipyard 目录；
2. 执行 Web 启动命令后，浏览器可以访问 Workbench；
3. 默认只监听 127.0.0.1；
4. API 和 Web UI 使用同一 profile 和 Workspace；
5. 无效配置、端口冲突、数据库迁移失败会阻止启动；
6. 启动日志不包含 API key、凭据或客户原始敏感数据。

### 17.2 业务闭环验收

1. 用户可以创建或加载 Workspace；
2. 用户可以查看 Decision Case、Artifact、Evidence、Run、Gate 和 Release；
3. Agent Run 通过 Application Service 创建；
4. Agent 不能直接写入正式 Artifact 或 Gate Review；
5. Proposal 可以被接受、退回和拒绝；
6. 输入版本变化会使 Proposal 或 Gate 变为 stale；
7. Evaluator 失败时不能创建 release-ready Candidate；
8. Release Dock 只能组装已满足前置 Gate 的 Artifact 集合；
9. 导出的 Release Manifest 可以被重新读取和校验；
10. 所有关键决定都能在 Audit 中找到 actor、时间、输入和结果。

### 17.3 可恢复性验收

1. 浏览器刷新不影响 Run；
2. API 重启后仍能看到已持久化的 Run 和事件；
3. Worker 失败后不会产生正式发布；
4. 重试使用明确的输入快照；
5. 取消、超时和失败状态有一致的语义；
6. 相同输入和配置的 headless 评测可以生成同结构的结果。

### 17.4 安全验收

1. Agent 不能读取工作区外文件；
2. 网络 deny profile 中无法访问任意外部地址；
3. 浏览器无法获取模型密钥；
4. 未授权用户无法访问其他 Workspace；
5. 插件未经白名单和兼容性检查不能加载；
6. 不存在生产 Action 入口；
7. 关键写操作均有审计事件。

### 17.5 前端与后端测试

至少覆盖：

- API contract tests；
- Application Service authorization tests；
- Registry persistence and migration tests；
- Run lifecycle tests；
- evaluator/gate stale tests；
- release eligibility tests；
- sandbox boundary tests；
- plugin manifest tests；
- Web UI integration tests；
- browser-level end-to-end tests；
- headless 与 local 结果一致性测试。

## 18. 分阶段实现路线

### L0：Local Web Composition Root

目标：让用户能一条命令启动本地 Workbench。

范围：

- RuntimeContext；
- local profile 配置；
- shipyard init；
- shipyard web；
- FastAPI 与静态 Web 资源组合；
- 本地身份；
- SQLite Registry；
- 文件 Artifact Store；
- 只读和基础写入 API；
- 端口、迁移和配置错误处理。

不在 L0 解决：

- 分布式 Worker；
- 完整插件市场；
- 生产 Action；
- 多用户权限；
- PostgreSQL 和 MinIO。

### L1：可恢复 Run 与受限 Sandbox

目标：让 Agent 和 Evaluator 在 Web 中可靠运行。

范围：

- Run Orchestrator；
- Worker 生命周期；
- 心跳、超时、取消和重试；
- Run 日志和事件流；
- Sandbox 工作区边界；
- 模型网关；
- Proposal 结构化展示；
- 失败恢复。

### L2：Gate、Release 和 Headless 一致性

目标：让浏览器流程、CLI 和 CI 共享同一套质量事实。

范围：

- Gate Review 页面；
- Evaluation Run 页面；
- Release Dock；
- headless profile；
- Release Manifest 校验；
- 复现和审计导出；
- 受影响 Gate 自动 stale。

### L3：插件和团队内网部署

目标：让多个构建角色能够在内网协同。

范围：

- plugin manifest 与 capability manager；
- PostgreSQL adapter；
- MinIO/S3 adapter；
- Worker Pool；
- Redis/NATS 等队列适配；
- OIDC/LDAP；
- 组织和项目级 ACL；
- Docker Compose 与 On-Prem 部署包；
- TLS 和反向代理。

### L4：客户侧交付与混合连接器

目标：把已经验证的 Release 安全地交付到客户环境。

范围：

- DecisionSystemRelease 安装器；
- 客户侧 Runtime 与 Shipyard 的协议；
- Connector Gateway；
- Feedback Contract；
- 运行时回放和指标回传；
- 升级、回滚和兼容性检查；
- 独立的 Action Gateway。

L4 不是 Local Web Runtime 的必要前置条件，但必须在 L0 的边界设计中预留 Release Manifest、Feedback Contract 和 connector capability。

## 19. 方案比较与选择

### 方案 A：浏览器 + 本地服务

组成：

~~~text
浏览器 → 本地 Web/API → Shipyard 内核
~~~

优点：

- 用户不需要理解前端构建和多个服务；
- 本地部署和客户现场部署的心智模型一致；
- 可以复用现有 React Workbench 和 FastAPI；
- 浏览器天然适合 Artifact、表格、血缘、Gate 和差异视图；
- CLI、CI 和浏览器可以共享 Application Service。

代价：

- 需要设计本地身份、浏览器到本地 API 的安全边界；
- 需要处理进程生命周期和版本升级；
- 默认不是天然的多人协作系统。

选择：推荐，作为第一部署形态。

### 方案 B：桌面壳层（Tauri / Electron）

优点：

- 可以更强地控制本地文件和进程；
- 可以提供系统级启动、托盘和离线体验。

代价：

- 增加桌面打包、升级、签名和跨平台维护成本；
- 容易把 Workbench 设计成单机应用，削弱后续内网部署的连续性；
- Web UI 与桌面权限边界仍然需要额外设计。

选择：不是第一版；未来可以作为 Local Profile 的可选包装。

### 方案 C：服务优先的内网部署

优点：

- 多人协作、身份和资源管理更自然；
- 更容易接入 PostgreSQL、对象存储和 Worker Pool。

代价：

- 部署成本高；
- 本地数据、客户现场和开发者体验更复杂；
- 会把第一版问题过早扩大为平台运维问题。

选择：作为 L3，不作为第一版默认形态。

## 20. 关键决策

本设计做出以下决策：

1. Shipyard Workbench 采用浏览器优先的人机交互；
2. Local Web Runtime 是第一部署形态；
3. AI-FDE 构建面与客户生产运行时严格分离；
4. Workbench 是主要控制面，Chat 是上下文侧边能力；
5. Application Service 是唯一写入边界；
6. Agent 只能提交 Proposal 和验证结果，不能直接审批、发布或执行客户动作；
7. Local Profile 默认绑定 127.0.0.1，网络和生产能力默认关闭；
8. SQLite、文件 Artifact Store 和进程内 Orchestrator 先用于单机闭环；
9. Team / On-Prem 通过 profile 替换存储、身份和 Worker，而不是重写领域内核；
10. Headless / CI 与 Web 共享同一套 Artifact、Gate、Evaluation 和 Release 语义；
11. Linear 不进入本版本核心；
12. Docker 是后续部署适配方式，不是本地 Web 设计的前置依赖。

## 21. 延后决策

以下事项不阻塞 L0，但在进入对应阶段前必须形成单独设计：

- 团队成员、组织、项目和资源级 ACL；
- OIDC、LDAP 和客户身份系统的具体适配；
- PostgreSQL 迁移和并发策略；
- 对象存储生命周期和加密；
- 消息队列的至少一次/至多一次语义；
- 插件签名和私有插件仓库；
- 客户侧 Connector Gateway 的协议；
- DecisionSystemRelease 的安装、升级和回滚格式；
- 运行时 Action Gateway 的审批和幂等设计；
- 多租户 SaaS 形态。

这些事项不能通过在 L0 中增加模糊的待办占位符来替代；它们应在进入 L3/L4 前成为可验证的协议和验收标准。

## 22. 成功定义

本设计成功的标志不是“浏览器能打开一个聊天框”，而是：

~~~text
一个 FDE 可以在本地启动 Shipyard
  → 选择项目工作区
  → 让 Agent 处理结构化构建任务
  → 审阅证据、产物、差异和验证结果
  → 运行 Gate 和评测
  → 处理阻断项
  → 导出可追溯的 DecisionSystemRelease
  → 在没有客户生产权限的前提下完成交付准备
~~~

如果用户重启电脑、刷新浏览器、替换模型端点或切换到 headless profile，已经形成的工程事实仍然能够被读取、重放、审计和继续构建。这才是 Local Web Runtime 对 Shipyard 的核心价值。
