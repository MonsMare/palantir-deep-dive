# AI-FDE 生产 Docker 环境设计

状态：已批准，待实施

日期：2026-08-14

## 1. 文档定位

本文档定义当前 AI-FDE 从“可测试 Python 内核”进入“单机生产型 Docker Compose 部署”的目标架构、运行边界、数据持久化策略、容器安全约束和验收标准。

本文档只解决生产运行底座，不改变 Ontology、数据产品、模型、决策和 Agent 门禁的业务语义。业务执行仍由现有 Domain Pack、Gate Engine、Artifact Workspace 和 DomainAgentTeam 负责。

本阶段的生产定义是：

- 在一台装有 Docker Desktop 或 Docker Engine 的机器上可恢复运行；
- API、异步 Worker、Linear Bridge 可以独立重启；
- 任务、工件、证据、审计和队列状态不会因为容器重启而丢失；
- 支持真实 Linear 和本地 Fake Linear 两种模式；
- 支持从离线测试逐步切换到真实外部系统；
- 具备健康检查、日志、幂等、备份和故障升级能力。

这不是高可用集群设计，也不是 Kubernetes、Kafka 或 Temporal 的迁移设计。多机高可用属于后续阶段。

## 2. 已确认的架构裁决

### 2.1 核心依赖

生产 Compose 采用：

- PostgreSQL：业务注册表、任务生命周期、事件 Inbox/Outbox、门禁、审批、审计索引；
- Redis Streams：异步任务和事件分发；
- MinIO：证据原文、数据产品快照、Agent 工件、评审报告和运行文件；
- Python API：对外 HTTP API 和项目工作台接口；
- Python Worker：执行 Agent DAG、门禁、模型和受治理 Action；
- Linear Bridge：连接 Linear，负责工单同步、人机评论、状态投影和人工升级；
- Migration Job：启动前执行数据库迁移；
- Evaluator Profile：只在验收和回归时启动。

SQLite 和本地文件系统继续保留为：

- 单元测试；
- 离线 Builder；
- 无外部依赖的开发环境；
- Fake Adapter 的最小运行模式。

SQLite 不作为多 Worker 生产事实源。

### 2.2 事实源分层

| 内容 | 权威来源 |
|---|---|
| 工单标题、描述、评论和人类可见状态 | Linear 的外部协作记录 |
| 任务合同版本、内部生命周期、运行状态 | PostgreSQL |
| Artifact、Evidence、Gate、Approval 的业务元数据 | PostgreSQL |
| 二进制证据和大文件 | MinIO |
| 待执行任务和事件分发 | Redis Streams |
| 执行日志和评论引用 | PostgreSQL 索引 + MinIO 原文 |
| Agent 候选工件 | Artifact Workspace，落盘到 PostgreSQL/MinIO |
| 最终发布与 Action 权限 | AI-FDE Gate Engine 和 Policy Gateway |

Linear 是人机控制面和外部协作投影，不是内部 Gate、Artifact 或审计链的唯一事实源。

## 3. 目标拓扑

~~~mermaid
flowchart LR
    H["人类 / Linear UI"] <--> L["linear-bridge"]
    L --> P[("PostgreSQL")]
    L --> R[("Redis Streams")]
    A["aifde-api"] --> P
    A --> R
    R --> W["aifde-worker"]
    W --> P
    W --> M[("MinIO")]
    W --> G["Gate Engine / Policy Gateway"]
    W --> T["DomainAgentTeam"]
    T --> O["Ontology / Data Product / Model / Decision"]
    W --> X["受治理 Action Adapter"]
    X --> P
    W --> R
    R --> L
~~~

所有业务容器加入同一个 Compose 内部网络。PostgreSQL、Redis 和 MinIO 默认不暴露到宿主机公网；只有 API、必要的健康端口和开发调试端口显式映射。

## 4. Compose 服务规格

### 4.1 aifde-api

职责：

- 提供现有项目、阶段、Artifact、Gate、Action 和健康接口；
- 连接 PostgreSQL、Redis、MinIO；
- 对外只提供经过 Pydantic 校验的领域 API；
- 不直接执行长时间 Agent 任务；
- 对长任务只创建任务记录并写入 Redis Streams。

运行约束：

- 非 root 用户；
- 只读镜像层；
- /tmp 使用 tmpfs；
- 运行时配置来自环境变量或 Docker secrets；
- /health/live 只检查进程存活；
- /health/ready 检查 PostgreSQL、Redis、MinIO、迁移版本和策略加载。

### 4.2 aifde-worker

职责：

- 消费 AgentRun、GateRun、ModelEvaluation 和 ActionReconciliation 任务；
- 调用 DomainAgentTeam；
- 维护预算、租约、重试和幂等；
- 将结果写入 Artifact Workspace、PostgreSQL、MinIO 和 Outbox；
- 不直接调用 Linear GraphQL。

运行约束：

- 每个任务生成独立运行目录；
- 不挂载 Docker socket；
- 每个任务有 run_id、idempotency_key、lease_owner 和 lease_expiry；
- 消费失败进入重试或 Dead Letter Stream；
- 达到重试上限时写入人工升级事件。

### 4.3 aifde-linear-bridge

职责：

- 使用 RealLinearAdapter 或 FakeLinearAdapter；
- 通过 webhook 和增量轮询发现工单变化；
- 解析并验证 aifde.task.v1；
- 将工单转换为内部 TaskContract；
- 通过 Outbox 发布 Linear 状态和评论；
- 不绕过内部生命周期和 Gate Engine；
- 将评审、失败、超时和人工升级结果投影回 Linear。

Bridge 需要支持 per-issue 错误隔离：单个工单异常不能中断整轮同步。

### 4.4 postgres

职责：

- 保存 AI-FDE 业务事实和执行事实；
- 开启 pg_isready 健康检查；
- 使用 named volume 保存数据；
- 默认只在内部网络监听；
- 启动时先运行迁移 Job。

### 4.5 redis

职责：

- 使用 Streams 和 Consumer Group 做任务分发；
- 开启 AOF；
- 使用 named volume 保存未确认消息和恢复信息；
- Redis 中的数据不是最终业务事实；
- 业务处理成功后才确认消息。

### 4.6 minio

职责：

- 保存原始证据、数据产品快照、模型包、评审报告和长日志；
- 用 bucket policy 区分证据、工件、运行文件和备份；
- 通过对象 ETag/内容哈希校验完整性；
- 生产凭证只能从环境或 secrets 注入。

### 4.7 migrate

启动顺序：

1. 等待 PostgreSQL healthy；
2. 执行版本化迁移；
3. 写入当前 schema version；
4. 成功退出；
5. API、Worker 和 Bridge 才允许进入 ready。

## 5. PostgreSQL 持久化边界

现有 Registry Protocol 继续作为抽象边界。需要新增 PostgreSQL 实现，但不删除 SQLite 实现。

逻辑表分组：

### 5.1 领域注册表

- projects
- artifacts
- artifact_versions
- evidence
- evidence_locations
- gate_definitions
- gate_runs
- approvals
- model_packages
- decision_runs
- action_requests
- action_outcomes
- reconciliation_records

### 5.2 Agent 执行表

- task_contracts
- task_contract_versions
- agent_runs
- agent_node_runs
- agent_leases
- agent_budgets
- agent_findings
- workspace_commits
- feedback_records

### 5.3 Linear 集成表

- linear_issues
- linear_issue_snapshots
- linear_events_inbox
- linear_comments
- linear_state_projections
- linear_commands
- linear_cursors

### 5.4 Outbox 和审计

- outbox_events
- outbox_delivery_attempts
- audit_events
- audit_chain_heads
- dead_letter_events

关键约束：

- Artifact 和 Evidence 采用追加式版本；
- 外部事件按 provider + external_event_id 唯一；
- TaskContract 按 linear_issue_id + contract_version 唯一；
- AgentRun 按 idempotency_key 唯一；
- Action 由 action_id 唯一，重试不能产生第二个外部动作；
- Outbox 与业务写入在同一个 PostgreSQL 事务内提交。

## 6. Redis Streams 契约

初始 Stream：

- aifde.task.dispatch
- aifde.gate.run
- aifde.action.reconcile
- aifde.linear.outbox
- aifde.dead-letter

消息统一信封：

~~~json
{
  "event_id": "event:uuid",
  "event_type": "agent.run.requested",
  "schema_version": 1,
  "occurred_at": "2026-08-14T00:00:00Z",
  "project_id": "project-1",
  "task_id": "linear-task-1",
  "run_id": "agent-run-1",
  "idempotency_key": "task-1:contract-v2:graph-v1",
  "attempt": 1,
  "payload_ref": "postgres://task_contracts/task-1"
}
~~~

消费规则：

1. 读取消息；
2. 检查事件是否已处理；
3. 获取任务租约；
4. 执行业务操作；
5. 在 PostgreSQL 写入结果和 Outbox；
6. 事务成功后 ACK；
7. 异常时不 ACK，等待重试；
8. 达到上限后移动到 Dead Letter Stream 并升级人工。

## 7. MinIO 对象命名

对象路径必须可通过业务标识反查：

~~~text
evidence/{project_id}/{evidence_id}/{content_hash}/original
artifacts/{project_id}/{artifact_id}/{version}/payload.json
models/{project_id}/{model_id}/{version}/package.tar
runs/{project_id}/{run_id}/logs/{sequence}.jsonl
reviews/{project_id}/{run_id}/review-{round}.json
exports/{project_id}/{export_id}/manifest.json
~~~

数据库保存对象 URI、内容哈希、大小、媒体类型、创建时间、分类和保留策略。没有数据库元数据的孤立对象由清理 Job 标记，不能直接删除。

## 8. 配置和密钥

必须提供：

- AIFDE_ENV=dev|test|prod
- AIFDE_STORAGE=sqlite|postgres
- DATABASE_URL
- REDIS_URL
- MINIO_ENDPOINT
- MINIO_ACCESS_KEY
- MINIO_SECRET_KEY
- MINIO_BUCKET_PREFIX
- LINEAR_MODE=real|fake
- LINEAR_API_KEY（real 模式）
- LINEAR_TEAM_ID
- LINEAR_WEBHOOK_SECRET（webhook 模式）
- MODEL_PROVIDER
- MODEL_API_KEY
- AIFDE_MAX_AGENT_PARALLELISM
- AIFDE_MAX_FIX_ROUNDS
- AIFDE_TASK_TIMEOUT_SECONDS

密钥规则：

- .env.example 只保存变量名和示例占位符；
- .env、生产 secrets 和 token 不进入 Git；
- Agent 评论只引用证据和工件 URI，不写入原始敏感数据；
- API 日志对 token、Authorization、连接串和敏感字段脱敏；
- 容器镜像中不得出现 Linear、模型或数据库凭证。

## 9. 容器安全

- 所有业务镜像使用固定基础镜像版本；
- 使用非 root 用户；
- 只读根文件系统，必要的写入通过 named volume 或 tmpfs；
- 不使用 privileged；
- 不挂载 Docker socket；
- Agent 工作目录按任务隔离；
- 生产 Action Adapter 与调试工具分开挂载；
- 默认禁止容器之间直接访问不属于自身职责的端口；
- 高风险 Worker 可使用独立 Compose profile；
- 容器内命令必须经过任务权限和 Tool Gateway 检查。

## 10. 启动、升级和恢复

### 10.1 启动

~~~text
docker compose config
docker compose up -d postgres redis minio
docker compose run --rm migrate
docker compose up -d aifde-api aifde-worker aifde-linear-bridge
docker compose ps
~~~

### 10.2 升级

1. 构建不可变镜像；
2. 运行离线 schema 检查；
3. 备份 PostgreSQL 和 MinIO manifest；
4. 执行迁移；
5. 滚动重启 API、Worker、Bridge；
6. 执行健康检查和 Fake Linear E2E；
7. 检查未确认消息、Dead Letter 和 Outbox 延迟。

### 10.3 恢复

- PostgreSQL：从 pg_dump 或备份卷恢复；
- MinIO：按 manifest 校验对象哈希；
- Redis：从 AOF 恢复未确认任务；
- Bridge：从 PostgreSQL cursor 和 Inbox 去重继续；
- Worker：租约过期后重新领取；
- 所有外部 Action：先查 Action/Reconciliation，再决定是否重试。

## 11. 可观测性

统一结构化事件字段：

- timestamp
- service
- environment
- event_id
- project_id
- task_id
- run_id
- issue_identifier
- actor
- component
- status
- duration_ms
- attempt
- error_code
- artifact_refs
- evidence_refs

最低指标：

- API 请求数量、延迟、错误率；
- readiness 失败次数；
- Redis 消费延迟、未确认消息数和 Dead Letter 数；
- Worker 运行数量、成功率、超时、预算消耗；
- Gate 通过/阻断数量；
- Linear 同步延迟、Webhook 重试和投影冲突；
- Outbox 未投递数量；
- Action reconciliation matched/remediation 数量。

## 12. Fake/Real 双模式验收

Fake 模式必须能够不访问外部 Linear API 完成：

1. 创建一个规范 Task；
2. Bridge 领取任务；
3. Worker 执行 Agent DAG；
4. 确定性检查；
5. Challenger 评审；
6. 产生 minor、major 和 blocker 三种结果；
7. 返工和最大轮次升级；
8. 人工批准并关闭；
9. Bridge 重启后继续；
10. 重复事件不产生重复工件和重复 Action。

Real 模式只替换 Adapter 和凭证，不改变 Task Lifecycle、Worker、Gate 和 Agent Graph。

## 13. 生产验收标准

- [ ] docker compose config 无错误；
- [ ] 全新机器可以构建所有必需镜像；
- [ ] migrate 成功且版本可查询；
- [ ] API live/ready 行为符合约定；
- [ ] PostgreSQL、Redis、MinIO healthcheck 全绿；
- [ ] Fake Linear E2E 全链路通过；
- [ ] API、Worker、Bridge 单独重启后状态可恢复；
- [ ] Redis 重复投递不会重复提交；
- [ ] PostgreSQL 和 MinIO 备份恢复通过哈希校验；
- [ ] 真实 Linear Adapter 的 GraphQL 合同测试通过；
- [ ] pytest -q、compileall、git diff --check 通过；
- [ ] 没有 secret、Docker socket 或 root 运行违规；
- [ ] 所有生产 Action 都可追溯到 Task、Approval、Artifact、Evidence 和 Reconciliation。

## 14. 分阶段实施边界

### M0：可构建的 Compose 骨架

- Dockerfile、Compose、.env.example；
- API、Worker、Bridge、PostgreSQL、Redis、MinIO；
- healthcheck、migration、named volumes；
- Fake Linear 最小模式。

### M1：生产持久化

- PostgreSQL Registry；
- Task、AgentRun、Inbox、Outbox 和 Audit 持久化；
- Redis Streams Consumer Group；
- Worker lease、retry、idempotency。

### M2：外部集成和运行保障

- Real Linear Adapter；
- MinIO evidence/artifact storage；
- 备份、恢复和清理；
- metrics、structured logs、dead letter 运维接口。

### M3：高风险 Action 和扩展

- Action reconciliation 持久化；
- 细粒度网络和工具隔离；
- 多 Worker 并发；
- 为未来 Kubernetes/Temporal 迁移保留协议边界。

## 15. 明确不在本阶段实现

- Kubernetes 部署；
- 多机高可用；
- Kafka 集群；
- Temporal 工作流迁移；
- 自动化生产发布；
- Agent 自主获得 Linear 管理权限；
- 使用 Linear 评论保存原始客户敏感数据；
- 没有审批的高风险 Action。
