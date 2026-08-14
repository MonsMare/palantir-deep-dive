# Production AI-FDE 增强验收说明

本文档描述当前仓库已经实现并验证的生产工程边界。它定义的是一套可替换的 Palantir-like 工程内核，不声称已经连接客户的 ERP、Jira、身份系统或真实生产队列。

## 1. 当前闭环

```text
SourceConnector
  → SourceSnapshot / EvidenceFragment
  → Domain Pack / Semantic Candidate
  → Ontology IR
  → Data Product / Field Provenance
  → Gate Engine / Release Manifest
  → Point-in-time FeatureSnapshot
  → Model Registry / PredictionArtifact
  → DecisionRuntime / OptimizationCertificate
  → GovernedActionBroker
  → External Receipt / Reconciliation
  → FeedbackLink / Audit / Metrics
```

核心原则是：每一个可计算产物都必须带 ontology release、版本、as-of 时间、输入快照、证据或 lineage；Agent 只能提交 candidate，不能直接批准、发布或执行外部动作。

## 2. 已完成的能力层

### P0：平台内核

- `DomainPack` 把领域词汇、Ontology IR、映射、计算、决策和动作策略封装为可注册版本。
- `OntologyIRCompiler` 生成 RDFS、SHACL、数据 schema 和稳定 hash。
- Registry 拒绝同一 `(pack_id, version)` 覆盖写入。

### P1：证据与语义

- `LocalFileConnector` 支持 JSON、CSV、Markdown、纯文本快照；连接器只产生 snapshot，不直接产生业务事实。
- `EvidenceExtractor` 保留 JSONPath、行号和文本区间等可重放定位。
- `DataQualityEngine` 检查 schema、必填字段、重复键、空值、时间顺序和 freshness。
- `StructuredLLMProvider` 只能在授权证据 payload 上生成 Pydantic 候选；未知证据引用、非法结构和伪造 release eligibility 会被拒绝。
- `ReviewQueue` 记录候选 hash、审查者、决策和终态，候选不会直接写入 release registry。

### P2：可计算 Ontology Runtime

- `FeatureRuntime` 按 `available_at <= as_of_time` 做 point-in-time materialization，显式执行缺失策略和 availability lag。
- `LabelRuntime` 将未来结果与特征快照分开，防止训练标签泄漏到推理输入。
- `PredictionRuntime` 绑定 model id/version、feature snapshot 和 lineage。
- `DecisionRuntime` 只排序可行候选，保留 prediction refs、约束状态和决策 lineage。

### P3：模型治理

- `ModelArtifact` 绑定 feature definition、training snapshot、代码版本、artifact hash 和评估报告。
- `ModelRegistry` 以 immutable identity 注册，支持 promote、rollback、verify；篡改 artifact 会被发现。
- `TemporalEvaluator` 使用时间切分，要求模型优于 baseline、通过 leakage 检查并覆盖有效时间窗口。
- `TabularModelAdapter` 是可替换的真实模型适配边界；当前示例使用 scikit-learn，而不是把 LLM 当作数值求解器。

### P4：决策优化与动作

- `OptimizationProblem` 明确变量、目标、硬/软约束、预测 refs 和 evidence refs。
- `DeterministicEnumerator` 产生可重放的 candidate plans 和 `OptimizationCertificate`；后续可替换 OR-Tools 或商业 solver。
- `GovernedActionBroker` 要求 approved + validation passed + matching dry-run，再执行 adapter。
- `JsonlFileActionAdapter` 只作为本地 production-like connector；它不是 ERP/Jira 集成。
- `execute_with_chain` 在 adapter 写入前调用 `ComputationChainValidator`，核验 feature → prediction → decision → action 的同一 release、版本、as-of 和引用闭包。
- Action 以 action id 幂等；外部回执和 `ReconciliationRecord` 不匹配时进入 remediation，而不是返回静默成功。

### 领域 Agent 团队

- 角色已类型化：Decision Analyst、Workflow Analyst、Ontology Engineer、Data Product Engineer、Model Engineer、Decision Agent、Challenger、Release Agent。
- `ArtifactWorkspace` 是追加式工作区；Agent 拿到的是只读 allowlist view，系统 scheduler 才拥有 commit token。
- 同一 artifact id 的并发提交产生 conflict，不会覆盖已有版本。
- 上游 revision 会向依赖 artifact 传播 stale；stale input 会在 provider 调用前阻断下游节点。
- `AgentGraph` 显式声明 DAG、重试次数、模型路由和 token budget；预算耗尽、取消、失败都会安全阻断下游节点。
- Challenger 拥有独立 invocation context；模型 route 永远没有 write capability。

## 3. 观测、持久化与运行检查

- `MetricsRegistry` 记录 ingestion、feature、prediction、decision、action、feedback 等指标。
- `AppendOnlyAuditLog` 使用 payload hash + predecessor hash + chain hash 检测篡改。
- `ReadinessChecker` 对 persistence、model registry、connector、queue、policy 等依赖 fail-closed。
- `SQLiteBuilderRegistry` 追加保存 source snapshot、compile result、release manifest、field provenance 和 audit events，并支持重启后的 hash replay。

## 4. 已验证的验收路径

当前测试覆盖两条同构领域链路：

1. `supplier-delay`：采购订单、供应商、交付事件和延误风险。
2. `software-delivery`：需求、优先级和交付计划，不依赖 supplier-specific key 或路径。

两条链路都验证：

- source → evidence → ontology release → canonical data product；
- point-in-time feature snapshot；
- prediction artifact；
- feasible decision candidate；
- approved action request；
- dry-run → file adapter receipt → reconciliation；
- action outcome → feedback link；
- computation-chain validation、audit 和 metrics。

建议验收命令：

```powershell
pytest -q
python -m compileall -q src tests
git diff --check
```

重点测试目录：

```powershell
pytest tests/agents tests/actions tests/observability tests/e2e -q
```

## 5. 仍然不能宣称的能力

当前实现已经是生产工程形状，但还不是客户生产环境的完整部署包。正式上线前必须替换或补齐：

- 企业级 SourceConnector、凭据管理、PII/数据分级和网络隔离；
- PostgreSQL/object store/消息队列等高可用持久化；
- 真正的模型注册服务、模型监控、漂移检测和 rollback runbook；
- OR-Tools/商业求解器适配与大规模问题分解；
- ERP、Jira、邮件、审批系统等真实 Action adapter 的签名、超时、重试、回执和补偿；
- 分布式 Agent worker、租户隔离、限流、SLO、告警和人工升级机制；
- 领域专家对 Ontology、特征、模型、约束和动作策略的业务验收。

因此，`JsonlFileActionAdapter`、deterministic provider、本地 SQLite 和 enumerator 只能证明边界契约与可回放性，不能被当作已经接入客户系统或已经具备自动生产决策授权。

## 6. 推荐上线顺序

1. 先用一个高价值决策建立 Domain Pack、证据闭包和人工 review queue。
2. 在 shadow mode 运行 feature/prediction/decision，只记录不执行。
3. 用历史回放、时间切分和 baseline 证明预测价值。
4. 将优化结果先作为候选方案交给业务 owner，保留 dry-run 和 reconciliation。
5. 只为低风险、可逆动作接入真实 adapter，并设置 kill switch。
6. 观察反馈、误报、漏报、执行失败和业务 KPI 后，再复制到第二个部门。

