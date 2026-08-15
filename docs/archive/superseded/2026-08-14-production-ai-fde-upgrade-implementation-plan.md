# Production AI-FDE Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将当前固定供应商延误 Builder 升级为具备真实生产工程边界的、可跨领域复用的 AI-FDE：能够从企业来源构建可审计 Ontology，运行 point-in-time 计算、预测和决策，经过门禁后通过受保护连接器执行动作，并由领域 Agent 团队协作交付。

**Architecture:** 核心平台只持有领域无关的契约、证据、Ontology IR、计算运行时、门禁、Artifact Workspace 和 Action Broker。每个业务域通过 `DomainPack` 提供词汇、对象、映射、特征、模型、决策和动作策略。Agent 只读授权版本并提交带证据的候选 Artifact；编译器、验证器、人工审批和运行时拥有发布及执行权。

**Tech Stack:** Python 3.11+、Pydantic 2、Polars、RDFLib、SHACL/pySHACL、scikit-learn、SQLite（本地审计）及可替换的 PostgreSQL/S3/队列/模型注册表/企业连接器适配器。

## Global Constraints

- 所有可发布事实、特征、预测、决策和动作必须绑定来源、版本、as-of 时间和数据血缘。
- `available_at > as_of_time` 的字段不得进入历史特征或预测输入。
- Agent 只能提出候选 Artifact；不能直接批准、发布、修改门禁状态或执行生产动作。
- 高影响实体只有 `confirmed` 才能进入生产计算；冲突必须显式阻断或进入人工复核。
- RDFS/SHACL 负责语义结构约束；特征、模型、优化和动作由独立运行时执行，并把结果作为带血缘的 Ontology 计算对象登记。
- 所有外部系统写入必须通过 Action Broker、策略、审批、幂等键、dry-run、回执和对账边界。
- 不允许用“接口存在”、单元测试或固定 fixture 代替跨领域端到端验收。
- 现有 supplier-delay 代码必须迁移为 Domain Pack；核心平台新增第二个 software-delivery Domain Pack 作为通用性验收。

---

### Task 1: Domain Pack 与 Ontology IR 平台内核

**Files:**
- Create: `src/aifde/platform/__init__.py`
- Create: `src/aifde/platform/domain_pack.py`
- Create: `src/aifde/platform/ontology_ir.py`
- Create: `src/aifde/platform/registries.py`
- Create: `tests/platform/test_domain_pack.py`
- Create: `tests/platform/test_ontology_ir.py`

**Interfaces:**
- `DomainPack(pack_id, version, domain, vocabulary, ontology, mappings, computation, decisions, actions, acceptance_suite)`。
- `DomainPackRegistry.register(pack)`, `get(pack_id, version=None)`, `list()`。
- `OntologyIR` 包含 `ClassIR`、`PropertyIR`、`RelationshipIR`、`EventIR`、`StateIR`、`MetricIR`，每项都保存 `evidence_refs`、`version` 和 `status`。
- `OntologyIRCompiler.compile(ir) -> OntologyArtifacts`，输出 RDFS、SHACL、数据 schema 和稳定 hash。

- [ ] **Step 1: Write the failing tests**：验证未知字段拒绝、Domain Pack 版本唯一、IR 中没有 evidence 的发布候选不能成为 release、同一 IR 重复编译 hash 稳定。
- [ ] **Step 2: Run tests to verify failure**：`pytest tests/platform/test_domain_pack.py tests/platform/test_ontology_ir.py -q`，预期因模块不存在失败。
- [ ] **Step 3: Implement contracts and registry**：使用 Pydantic frozen models；所有 nested collection 使用 tuple；registry 拒绝覆盖已有 `(pack_id, version)`。
- [ ] **Step 4: Implement deterministic IR compiler**：使用 RDFLib 生成 typed class/property/domain/range 和 SHACL；编译输出通过现有 `ShaclValidator`；将原有 supplier-delay 的 schema 能力迁入 adapter，而不是复制固定业务逻辑。
- [ ] **Step 5: Run focused tests**：`pytest tests/platform/test_domain_pack.py tests/platform/test_ontology_ir.py -q`，预期全部通过。
- [ ] **Step 6: Run regression**：`pytest -q`。
- [ ] **Step 7: Commit**：`git add src/aifde/platform tests/platform && git commit -m "feat: add domain pack ontology ir kernel"`。

### Task 2: 通用 SourceConnector 与证据抽取层

**Files:**
- Create: `src/aifde/ingestion/__init__.py`
- Create: `src/aifde/ingestion/connectors.py`
- Create: `src/aifde/ingestion/extractors.py`
- Create: `src/aifde/ingestion/quality.py`
- Modify: `src/aifde/builder/sources.py`
- Create: `tests/ingestion/test_connectors.py`
- Create: `tests/ingestion/test_extractors.py`

**Interfaces:**
- `SourceConnector.describe() -> SourceDescriptor`。
- `SourceConnector.capture(request) -> SourceSnapshot`。
- 内置 `LocalFileConnector` 支持 JSON、CSV、Markdown、纯文本；`ConnectorRegistry` 负责按 source type 路由。
- `EvidenceExtractor.extract(snapshot) -> ExtractionReport`，输出带 JSONPath/行号/页码/表格定位的 `EvidenceFragment`。
- `DataQualityEngine.run(product, contract) -> QualityReport`。

- [ ] **Step 1: Add failing tests**：验证 JSON/CSV/Markdown 都能生成可重放 fragment，未知格式显式失败，snapshot hash、locator 和 extractor version 被保留。
- [ ] **Step 2: Run focused tests**：`pytest tests/ingestion -q`，预期失败。
- [ ] **Step 3: Implement connector boundary**：复用现有 `SourceAsset`、`SourceSnapshot`、`EvidenceFragment`，禁止 connector 直接生成业务事实。
- [ ] **Step 4: Implement deterministic extractors**：JSON 使用 JSONPath，CSV 使用行列定位，Markdown/文本使用行区间；保留原文和归一化文本。
- [ ] **Step 5: Implement quality checks**：增加 schema fingerprint、required field、duplicate key、null、temporal order 和 freshness 检查。
- [ ] **Step 6: Run focused and regression tests**。
- [ ] **Step 7: Commit**：`git add src/aifde/ingestion src/aifde/builder/sources.py tests/ingestion && git commit -m "feat: add connector and evidence extraction layer"`。

### Task 3: 领域候选生成、LLM 适配和人工语义审核

**Files:**
- Create: `src/aifde/semantic/provider.py`
- Create: `src/aifde/semantic/review.py`
- Modify: `src/aifde/builder/semantic.py`
- Create: `tests/semantic/test_provider_contract.py`
- Create: `tests/semantic/test_review_queue.py`

**Interfaces:**
- `SemanticProvider.propose(context, evidence) -> CandidateProposal`。
- `StructuredLLMProvider` 只负责生成 Pydantic candidate，禁止直接写 registry。
- `ReviewQueue.submit(candidate)`, `approve(review_id, actor)`, `reject(review_id, actor)`。
- `EntityResolutionPolicy` 为每类实体定义确认阈值、冲突处理和人工升级规则。

- [ ] **Step 1: Write failing tests**：无 evidence 的 LLM 输出拒绝；模型注入的 external key 无来源时拒绝；人工批准前不能生成 release-eligible assertion；审核记录可追溯。
- [ ] **Step 2: Implement deterministic provider adapter**：将当前 `DeterministicCandidateProvider` 改为实现通用接口。
- [ ] **Step 3: Implement structured LLM adapter**：提供可插拔 transport，不绑定某个厂商；输入仅含授权 Evidence，输出必须经过 schema 和 evidence closure 验证。
- [ ] **Step 4: Implement review queue**：审核状态转换由 Gate/Policy 控制，候选和审核不能覆盖写入。
- [ ] **Step 5: Add supplier-delay and software-delivery providers**。
- [ ] **Step 6: Run tests and regression**。
- [ ] **Step 7: Commit**：`git add src/aifde/semantic src/aifde/builder/semantic.py tests/semantic && git commit -m "feat: add governed semantic provider and review queue"`。

### Task 4: 将两个示例迁移为 Domain Pack 并移除核心硬编码

**Files:**
- Create: `src/aifde/domains/supplier_delay.py`
- Create: `src/aifde/domains/software_delivery.py`
- Modify: `src/aifde/builder/flow.py`
- Modify: `src/aifde/builder/compiler.py`
- Modify: `src/software_delivery_demo/builder_demo.py`
- Create: `tests/domains/test_domain_pack_runs.py`

- [ ] **Step 1: Add failing cross-domain tests**：Builder 接收 `pack_id`，两个 Domain Pack 均可编译；核心 compiler 不再读取 supplier-specific paths；错误 Domain Pack 明确阻断。
- [ ] **Step 2: Implement domain adapters**：把对象、mapping、RDFS/SHACL 和 acceptance fixture 移入 Domain Pack。
- [ ] **Step 3: Refactor Builder**：`BuilderRunConfig` 使用 `domain_pack_id` 与 connector request；compiler 只消费 `OntologyIR` 和 mapping contract。
- [ ] **Step 4: Preserve existing supplier-delay behavior**：字段级 provenance、as-of、冲突阻断、SQLite release 全部保持。
- [ ] **Step 5: Wire software-delivery pack**：将现有 data product、feature、model、decision 定义挂到统一 pack interface。
- [ ] **Step 6: Run cross-domain acceptance**：`pytest tests/domains -q && pytest -q`。
- [ ] **Step 7: Commit**：`git add src/aifde/domains src/aifde/builder src/software_delivery_demo tests/domains && git commit -m "refactor: move business logic into domain packs"`。

### Task 5: 可计算 Ontology Runtime

**Files:**
- Create: `src/aifde/runtime/__init__.py`
- Create: `src/aifde/runtime/features.py`
- Create: `src/aifde/runtime/labels.py`
- Create: `src/aifde/runtime/predictions.py`
- Create: `src/aifde/runtime/decisions.py`
- Create: `tests/runtime/test_point_in_time_runtime.py`

- [ ] **Step 1: Write failing tests**：未来字段不能进入 FeatureSnapshot；feature/label snapshot 必须引用同一 release；缺失策略、窗口和 as-of 不能省略；prediction 必须保留 model version 和 feature snapshot。
- [ ] **Step 2: Implement feature runtime**：从 canonical data product 执行 point-in-time join、窗口聚合、缺失策略和 lineage closure。
- [ ] **Step 3: Implement label runtime**：分离 feature_as_of 和 label_as_of，阻止标签泄漏，支持 delayed outcome。
- [ ] **Step 4: Implement prediction runtime**：调用 ModelAdapter，输出概率/区间/解释/不确定性和 artifact hash。
- [ ] **Step 5: Implement decision runtime**：调用 DecisionAdapter，输出候选方案、约束、目标、可行性证明和解释。
- [ ] **Step 6: Integrate `ComputationChainValidator`**：运行时产物必须可进入现有链校验和 Gate Engine。
- [ ] **Step 7: Run tests and regression**。
- [ ] **Step 8: Commit**：`git add src/aifde/runtime tests/runtime && git commit -m "feat: add point-in-time ontology computation runtime"`。

### Task 6: 模型注册、训练、评估和在线预测适配

**Files:**
- Create: `src/aifde/ml/registry.py`
- Create: `src/aifde/ml/adapters.py`
- Create: `src/aifde/ml/evaluation.py`
- Modify: `src/software_delivery_demo/models.py`
- Create: `tests/ml/test_model_registry.py`
- Create: `tests/ml/test_temporal_evaluation.py`

- [ ] **Step 1: Add failing tests**：模型必须绑定 feature definition、training snapshot、code version；时间切分必须可重放；模型弱于 baseline 不得 release；模型 artifact hash 篡改可检测。
- [ ] **Step 2: Implement `ModelRegistry`**：支持 register、promote、rollback、get、verify；模型状态 append-only。
- [ ] **Step 3: Implement `ModelAdapter`**：统一 `fit/evaluate/predict/explain`，保留离线和在线输入 schema。
- [ ] **Step 4: Implement temporal evaluation**：MAE/AUC/coverage/calibration、分组指标和 drift baseline。
- [ ] **Step 5: Connect supplier-delay predictor**：使用历史订单/交付事件生成 delay probability 和 expected delay days。
- [ ] **Step 6: Run model acceptance**：至少使用时间切分数据、baseline 对比、回放和 artifact verification。
- [ ] **Step 7: Commit**：`git add src/aifde/ml src/software_delivery_demo/models.py tests/ml && git commit -m "feat: add governed model registry and temporal evaluation"`。

### Task 7: 决策优化运行时

**Files:**
- Create: `src/aifde/optimization/__init__.py`
- Create: `src/aifde/optimization/contracts.py`
- Create: `src/aifde/optimization/solvers.py`
- Create: `tests/optimization/test_decision_solver.py`

- [ ] **Step 1: Write failing tests**：缺少 objective/variable/hard constraint 的方案拒绝；不可行方案不得进入 approval；同一预测和 release 可重放相同候选排序。
- [ ] **Step 2: Implement problem contracts**：变量、目标、硬/软约束、候选方案和 optimization certificate 都要绑定 Ontology release、prediction refs 和 evidence。
- [ ] **Step 3: Implement deterministic solver adapter**：提供可用的枚举/线性候选 solver，允许后续 OR-Tools/商业求解器适配；不把 LLM 作为求解器。
- [ ] **Step 4: Add supplier-delay interventions**：催交、加急运输、拆单、切换供应商，计算成本/风险/交付影响。
- [ ] **Step 5: Add software-delivery decision adapter**：迁移现有 candidate plan 和 feasibility checks。
- [ ] **Step 6: Run tests and regression**。
- [ ] **Step 7: Commit**：`git add src/aifde/optimization tests/optimization && git commit -m "feat: add governed decision optimization runtime"`。

### Task 8: 真实 Action Adapter、回执、对账和工作台

**Files:**
- Create: `src/aifde/actions/adapters.py`
- Create: `src/aifde/actions/reconciliation.py`
- Modify: `src/aifde/tools/actions.py`
- Modify: `src/aifde/api/routes.py`
- Modify: `src/aifde/ui/dashboard.py`
- Create: `tests/actions/test_adapter_boundary.py`
- Create: `tests/actions/test_reconciliation.py`

- [ ] **Step 1: Add failing tests**：未经批准的真实 adapter 调用拒绝；dry-run 不产生写入；幂等重试不重复写入；外部回执与 ActionOutcome 可对账；失败进入 remediation。
- [ ] **Step 2: Implement adapter protocol**：统一 `validate/dry_run/execute/reconcile/rollback`；保留 Mock adapter 作为测试实现。
- [ ] **Step 3: Implement local production-like adapter**：提供 file/http webhook adapter，具备签名、超时、幂等和回执；真实 ERP/Jira 通过同一 protocol 接入，不伪造外部系统。
- [ ] **Step 4: Extend broker**：将 `GovernedActionRequest` 接入 policy、approval、chain validation 和 adapter registry。
- [ ] **Step 5: Extend cockpit**：显示证据、预测、方案、审批、dry-run、回执和对账状态。
- [ ] **Step 6: Run action acceptance and regression**。
- [ ] **Step 7: Commit**：`git add src/aifde/actions src/aifde/tools/actions.py src/aifde/api src/aifde/ui tests/actions && git commit -m "feat: add governed action adapters and reconciliation"`。

### Task 9: 领域 Agent 团队、Artifact Workspace 和 DAG 编排

**Files:**
- Create: `src/aifde/agents/workspace.py`
- Create: `src/aifde/agents/roles.py`
- Create: `src/aifde/agents/graph.py`
- Create: `src/aifde/agents/budget.py`
- Modify: `src/aifde/orchestration/runner.py`
- Modify: `src/aifde/orchestration/agents.py`
- Create: `tests/agents/test_domain_team.py`
- Create: `tests/agents/test_agent_budget_and_conflicts.py`

- [ ] **Step 1: Add failing tests**：Agent 只能读取授权 workspace；两个 Agent 不能覆盖同一 Artifact；预算耗尽安全停止；Challenger 与 Builder 使用独立上下文；上游 release 变化会使下游 stale。
- [ ] **Step 2: Implement append-only Artifact Workspace**：Artifact version、lock、dependency hash、review status 和 diff 可恢复。
- [ ] **Step 3: Implement typed roles**：Decision Analyst、Workflow Analyst、Ontology Engineer、Data Product Engineer、Model Engineer、Decision Agent、Challenger、Release Agent。
- [ ] **Step 4: Implement DAG scheduler**：显式 dependencies、并发上限、重试、模型路由、token/wall-time budget 和 cancellation。
- [ ] **Step 5: Implement provider routing**：规则/小模型/强模型按任务契约路由；LLM 不能取得写入和执行 capability。
- [ ] **Step 6: Implement supplier-delay domain team**：从已发布 Ontology 开始，生成 feature、prediction、decision、action proposal 和 feedback plan。
- [ ] **Step 7: Run agent quality tests**：证据覆盖、反例发现、冲突、预算、门禁绕过和断点恢复。
- [ ] **Step 8: Commit**：`git add src/aifde/agents src/aifde/orchestration tests/agents && git commit -m "feat: add governed domain agent team orchestration"`。

### Task 10: 生产持久化、观测性、部署和双领域端到端验收

**Files:**
- Create: `src/aifde/observability/metrics.py`
- Create: `src/aifde/observability/audit.py`
- Create: `src/aifde/deployment/health.py`
- Modify: `src/aifde/builder/persistence.py`
- Create: `tests/e2e/test_production_two_domain_flow.py`
- Create: `docs/production-ai-fde-acceptance.md`
- Modify: `README.md`

- [ ] **Step 1: Add failing end-to-end tests**：两个 Domain Pack 都能完成 source→evidence→ontology→data product→feature→prediction→decision→approved action→feedback；任意关键 hash/权限/时间/审批错误必须阻断。
- [ ] **Step 2: Implement metrics and audit events**：记录 ingestion、agent、gate、model、decision、action 和 feedback 指标，审计事件不可覆盖。
- [ ] **Step 3: Implement health/readiness checks**：依赖版本、数据库、connector、model registry、queue 和 policy 状态可检查。
- [ ] **Step 4: Extend persistence boundary**：保留 SQLite 本地实现，增加 PostgreSQL/object-store protocol 和 migration/version checks。
- [ ] **Step 5: Run full acceptance**：`pytest -q`、`python -m compileall -q src tests`、两领域端到端命令和 tamper/replay tests。
- [ ] **Step 6: Write acceptance report**：明确已验证能力、部署前置条件、未接入的客户系统和可观测指标；不得把 local adapter 宣称为 ERP 集成。
- [ ] **Step 7: Commit**：`git add src/aifde/observability src/aifde/deployment src/aifde/builder/persistence.py tests/e2e docs/production-ai-fde-acceptance.md README.md && git commit -m "feat: add production acceptance and observability"`。

## Completion Audit

- [ ] `supplier-delay` 和 `software-delivery` 都通过完整端到端流程。
- [ ] 至少一个真实的预测模型和一个真实的确定性优化器进入统一运行时。
- [ ] Action adapter 有 dry-run、审批、幂等、回执和对账测试。
- [ ] Agent 团队通过 workspace、DAG、预算、挑战者和断点恢复测试。
- [ ] 所有发布产物可追溯到 Source Snapshot、Ontology Release、Feature Snapshot、Model/Decision version 和 Action Outcome。
- [ ] 失败、冲突、未来数据、篡改、权限越权和预算耗尽均不能静默成功。
- [ ] 全量测试、编译检查、端到端验收和生产边界文档均通过。

