# AI-FDE Shipyard 内核验收说明

本文档描述当前仓库对 Shipyard 构建能力的验收边界。这里的“生产级”指构建产物可重放、可审计、可评测、可回滚并能形成交付包；不表示本仓库已经成为客户生产环境中的持续预测和决策运行时。

## 1. 系统边界

```text
Shipyard Workbench
  → Shipyard API / Application Service
  → Evidence / Ontology / Data Product / Model / Decision Builder
  → Gate Engine / Evaluation Lab / Release Dock
  → DecisionSystemRelease（交付给客户的轮船）
  → 客户环境中的生产运行时
  → 运行反馈和业务结果回传 Shipyard
```

Shipyard 的职责是构建、验证、评测、打包、交付和升级；客户生产运行时的职责是接收实时或批量数据、产生预测和决策、执行已经授权的业务动作。两者使用发布包和反馈协议连接，不能由同一个 Agent 进程混合承担。

## 2. 当前已具备的构建内核

### 2.1 证据与 Ontology Builder

- `SourceConnector` 将源文件或源记录登记为不可变快照；
- `EvidenceFragment` 保存 JSONPath、行号、文本区间等可重放定位；
- 数据质量检查覆盖 schema、必填字段、重复键、空值、时间顺序和 freshness；
- 语义候选、实体解析、映射和 Ontology IR 均保留来源、版本和候选状态；
- RDFS/SHACL 编译和 Gate Engine 阻止未经验证的候选进入发布包。

### 2.2 数据产品与计算评测

- 数据产品以明确粒度、时间语义、可用延迟、缺失策略和字段血缘构建；
- `FeatureRuntime` 按 `available_at <= as_of_time` 生成 point-in-time 特征；
- `LabelRuntime` 将未来结果与推理输入分离，检查数据泄漏；
- `PredictionArtifact` 绑定模型、特征快照、训练快照和评估结果；
- `DecisionCandidate` 绑定预测、约束、目标和决策血缘；
- 历史回放和时间切分用于证明目标系统是否真的产生预测价值，而不是只生成描述性镜像。

### 2.3 领域 Agent 与治理

- Decision Analyst、Workflow Analyst、Ontology Engineer、Data Product Engineer、Model Engineer、Decision Agent、Challenger 和 Release Agent 以类型化 Artifact 协作；
- Agent 只能提交 Proposal，不能直接批准、发布、改变 Gate 状态或执行客户生产动作；
- Artifact Workspace 追加写入，冲突、stale 输入、预算耗尽和验证失败都会显式阻断；
- Gate、Approval、Audit、版本和输入哈希组成可追溯的构建记录。

### 2.4 目标系统的沙箱验证

`supplier-delay` 和 `software-delivery` 领域包可以在本地沙箱中验证：

```text
source
 → evidence
 → ontology release
 → canonical data product
 → feature / label snapshot
 → prediction artifact
 → feasible decision candidate
 → mock action / dry-run
 → feedback link
 → replay and evaluation
```

其中 JSONL adapter、deterministic solver、SQLite 和模拟数据只用于证明契约、可回放性和门禁行为，不能被描述为已经接入 ERP、Jira 或客户真实生产队列。

## 3. Shipyard 发布门禁

一个 `DecisionSystemRelease` 至少需要通过：

1. 业务决策定义：明确用户、触发、输入、决策、动作和结果指标；
2. 证据完整性：关键业务语义可回到授权来源；
3. Ontology 语义：对象、关系、状态、权限和 SHACL 约束通过；
4. 数据产品：粒度、时间、质量、血缘和权限传播通过；
5. 智能能力：基线、时间评估、泄漏检查、校准和不确定性说明通过；
6. 决策与工作流：候选方案满足硬约束，用户动作和异常路径可解释；
7. 安全与审计：权限、敏感数据、版本、审批、回滚和审计闭环通过；
8. 交付完整性：运行配置、依赖、监控、升级和回滚手册已纳入发布包。

## 4. 当前不能宣称的能力

当前仓库还不能宣称：

- 已实现生产级 Shipyard Workbench 前端；
- 已连接客户的 ERP、Jira、身份系统、消息系统或生产队列；
- 已提供客户生产运行时的高可用、实时服务、租户隔离和 SLO；
- 已具备不经人工批准的高风险业务动作能力；
- 已将 Linear 作为当前核心人机交互入口；
- 仅凭 Ontology 描述层就获得预测或优化能力；
- 本地适配器、固定 fixture 或单元测试可以替代客户领域验收。

## 5. 推荐验收命令

```powershell
pytest -q
python -m compileall -q src tests
git diff --check
```

重点验证：

```powershell
pytest tests/builder tests/ml tests/optimization tests/gates tests/agents tests/e2e -q
```

## 6. 下一步交付顺序

1. 建立 Workbench 项目空间、Decision Case、Artifact Review 和 Gate Review；
2. 将证据驱动 Builder、Ontology Studio、Data Product Studio 和 Evaluation Lab 接入同一套 Workbench 生命周期；
3. 用 `software_delivery` 完成第一条从需求对齐到工期预测的垂直切片；
4. 建立 Release Dock，生成可安装、可回滚、可监控的 `DecisionSystemRelease`；
5. 再补充 PostgreSQL、对象存储、队列和客户侧运行时部署适配器；
6. 最后将 Linear 作为可选同步适配器，而不是替代 Workbench。
