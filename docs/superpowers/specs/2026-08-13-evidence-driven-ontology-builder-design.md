# 证据驱动的 Ontology Builder 设计

状态：设计稿，待评审
适用阶段：AI-FDE 下一阶段
上游：业务立项、需求提炼、工作流观察、原始资料接入
下游：领域 Agent 团队、分析/预测/决策工程、业务应用交付
核心原则：AI 生成候选，证据约束语义，门禁控制发布，人类承担业务确认

## 1. 文档目的

本文定义“证据驱动的 Ontology Builder”阶段的生产级目标、架构、对象、流程、接口、门禁和验收标准。

本阶段解决的问题不是“把表字段转换成 RDF”，而是：

> 把企业分散、重复、冲突、带有时间和权限边界的资料，编译成可追溯、可验证、可回滚、可供计算和 Agent 使用的业务 Ontology 与数据映射。

本阶段的最终产物不是一份 TTL 文件，而是一组可发布的工程 Artifact：

- 证据登记与不可变证据快照；
- 术语、实体、关系和状态候选；
- 实体对齐和冲突决议；
- Ontology 模型及 SHACL 约束；
- 源数据到标准数据产品的映射规范；
- 时间语义、数据血缘和权限策略；
- 可执行的数据产品管道；
- 验证报告、人工审核记录和发布包。

## 2. 能力目标与边界

### 2.1 本阶段要达到的能力

完成本阶段后，系统应能在限定的企业数据域内：

1. 登记文件、表格、数据库、API 和事件流等数据源；
2. 保留原始内容、位置、版本、采集时间、访问范围和哈希；
3. 将非结构化内容拆解为可引用的证据片段；
4. 发现候选业务对象、属性、关系、状态、事件和业务术语；
5. 对跨系统实体进行确定性和概率性对齐；
6. 将业务语义候选映射为 Ontology 类、属性、关系和状态模型；
7. 生成源字段到标准数据产品和 Ontology 对象的映射；
8. 显式表达 valid time、event time、observed time、available time；
9. 为每条关键语义声明绑定证据和责任人；
10. 运行结构、语义、数据、权限和可执行性校验；
11. 通过人工评审、版本发布和回滚，将候选模型变成受控版本；
12. 为后续预测、决策和领域 Agent 提供稳定输入。

### 2.2 明确不自动化的事项

以下事项不能仅由模型输出直接决定：

- 业务对象的最终定义；
- 冲突来源的最终权威级别；
- 敏感字段的访问范围；
- 高风险状态的业务含义；
- 生产系统的写入权限；
- 关键业务规则的最终解释；
- Ontology 发布和生产 Action 的最终批准。

AI 可以提出候选、解释依据、列出冲突和生成 Diff；Domain Owner 或数据责任人必须对业务语义和权限做确认。

## 3. 生产级定义

“生产级 Ontology Builder”必须同时满足以下条件：

| 维度 | 生产级要求 |
|---|---|
| 可复现 | 相同源快照、配置、模型版本和提示版本能够重建同一候选结果 |
| 可追溯 | 每个关键类、属性、关系、映射和约束均可追溯到证据片段 |
| 可解释 | 能说明为什么合并两个实体、为什么选择某个字段、为什么拒绝某个映射 |
| 可验证 | 生成的模型和数据管道可由确定性校验、SHACL、SQL/代码测试验证 |
| 可治理 | 版本、审批、权限、责任人、失效条件和回滚关系完整 |
| 可演进 | 源 schema、术语、业务规则和 Ontology 变化可计算影响范围 |
| 可运行 | 映射能生成并执行数据产品，不只是静态设计文档 |
| 可降级 | 证据不足、冲突未解决或抽取不稳定时，系统必须阻断或降级 |

## 4. 总体架构

~~~mermaid
flowchart LR
    A["企业资料与数据源"] --> B["Source Registry"]
    B --> C["Evidence Capture"]
    C --> D["Evidence Store"]
    D --> E["Extraction and Normalization"]
    E --> F["Term and Entity Resolution"]
    F --> G["Semantic Candidate Builder"]
    G --> H["Ontology and Mapping Compiler"]
    H --> I["Data Product Runtime"]
    H --> J["RDFS/SHACL Validator"]
    I --> K["Data Quality and Temporal Validator"]
    D --> L["Provenance and Access Policy"]
    J --> M["Gate Engine"]
    K --> M
    L --> M
    M --> N["Human Review Workbench"]
    N --> O["Ontology Release Package"]
    O --> P["Domain Agent Workspace"]
~~~

架构分为五个边界：

1. **证据边界**：原始资料不可被 Agent 覆盖，只能生成新版本或派生片段。
2. **语义边界**：候选语义与已批准语义必须区分。
3. **计算边界**：Ontology 描述、数据管道、模型和决策函数分离。
4. **治理边界**：Gate Engine 控制从候选到发布的状态转换。
5. **执行边界**：本阶段默认不直接向生产业务系统写入数据。

## 5. 核心对象

### 5.1 SourceAsset

表示一个外部资料或数据源。

必要字段：

~~~text
source_asset_id
source_type              # pdf, docx, xlsx, csv, database, api, event_stream
source_uri
owner
authority_level
classification
schema_fingerprint
content_hash
captured_at
observed_at
access_policy_id
connector_version
~~~

SourceAsset 是事实来源登记，不等同于业务对象。源文件的更新必须生成新的版本或新的快照。

### 5.2 EvidenceFragment

表示可引用的最小证据单元。

必要字段：

~~~text
evidence_fragment_id
source_asset_id
source_version
location                # 页码、段落、表名、行号、列名、JSONPath
content
content_hash
event_time
observed_time
available_time
extraction_method
extractor_version
confidence
access_policy_id
~~~

证据片段必须能回到原文或原始记录。只保留向量检索结果而不保留原文位置，不满足生产级追溯要求。

### 5.3 TermCandidate

表示术语、缩写、同义词和业务定义候选。

必要字段：

~~~text
term_id
surface_forms
canonical_label
domain
definition_candidate
source_evidence_refs
conflicting_definitions
status                  # proposed, accepted, rejected, deprecated
review_owner
~~~

### 5.4 EntityCandidate

表示从资料中发现的业务实体候选。

必要字段：

~~~text
candidate_id
entity_type_candidate
source_keys
display_values
identity_features
matched_source_assets
resolution_status       # unresolved, probable_match, confirmed, rejected
resolution_method
resolution_score
evidence_refs
conflict_refs
~~~

### 5.5 SemanticAssertion

表示一条关于业务世界的语义声明。

示例：

~~~text
subject_candidate: supplier:001
predicate: promisedDeliveryDate
object_candidate: date:2026-09-10
assertion_type: fact | definition | rule | assumption
valid_time
observed_time
available_time
evidence_refs
responsible_reviewer
status
~~~

fact、definition、rule 和 assumption 必须区分，不能把模型推断直接写成业务事实。

### 5.6 MappingSpec

表示源数据到标准数据产品或 Ontology 属性的映射。

必要字段：

~~~text
mapping_id
source_asset_id
source_field_path
target_product
target_grain
target_field
transform_expression
identity_rule
time_semantics
null_policy
quality_expectations
lineage_refs
security_policy
version
~~~

### 5.7 OntologyCandidate

表示待评审的 Ontology 版本。

必要字段：

~~~text
ontology_candidate_id
version
classes
properties
relationships
states
events
identity_keys
temporal_semantics
access_policies
shape_document_ref
mapping_spec_refs
evidence_refs
open_questions
conflicts
generated_by
~~~

### 5.8 OntologyReleasePackage

表示已经通过发布门禁的版本。

必要字段：

~~~text
release_id
ontology_version
ontology_artifact_hash
shape_artifact_hash
mapping_artifact_hash
data_product_artifact_refs
gate_run_ids
approval_ids
dependency_versions
rollback_target
released_at
~~~

## 6. 端到端工作流

### 6.1 阶段 S0：登记数据源

目标：建立来源边界和权威性，不让 Agent 直接从未登记的文件推理。

必要功能：

- 连接器注册；
- source owner 和 authority level；
- 数据分类和访问策略；
- schema/content fingerprint；
- 增量同步和幂等；
- 采集失败、权限失败和版本变化记录。

输出：

- SourceAsset；
- SourceSnapshot；
- AccessPolicy；
- IngestionRun。

硬门禁：

- 来源可追溯；
- 权限已登记；
- 采集快照有哈希；
- 连接器版本可记录。

### 6.2 阶段 S1：解析与证据切片

目标：把文档、表格和事件变成带位置的 EvidenceFragment。

必要功能：

- PDF、Word、Excel、CSV、JSON、数据库记录解析；
- OCR 和表格结构识别；
- 页码、行号、列名、单元格、JSONPath 定位；
- 文档段落、表头、表格行和事件记录的边界识别；
- 原文片段和归一化文本同时保留；
- 解析失败和低置信片段显式标记。

输出：

- EvidenceFragment；
- ExtractionReport；
- ParserWarning。

硬门禁：

- 每个片段可回源；
- 解析失败率在域配置阈值内；
- 关键字段没有无位置来源；
- OCR 或抽取版本可追溯。

### 6.3 阶段 S2：术语归一与实体候选

目标：从证据中发现业务术语、对象候选和同义表达。

必要功能：

- 术语抽取；
- 缩写、别名、语言变体归一；
- 字段名、文档标题、表头和业务词典联合；
- 候选对象类型发现；
- 业务事件和状态词识别；
- 候选证据引用；
- 不确定表达保留为候选，不强制归类。

AI 的职责：

- 抽取候选；
- 生成同义词；
- 解释候选依据；
- 指出术语冲突。

确定性组件的职责：

- 标准化；
- 去重；
- 候选格式验证；
- 证据引用完整性检查。

### 6.4 阶段 S3：实体解析与冲突处理

目标：判断不同来源中的记录是否代表同一个业务实体。

解析顺序：

1. 精确业务主键匹配；
2. 受信任的外部 ID 映射；
3. 规范化名称、地址、税号、合同号等确定性组合；
4. 概率匹配；
5. LLM 只提供候选解释，不直接合并；
6. 低置信或高风险合并进入人工审核。

每个匹配结果必须保存：

- 使用的字段；
- 匹配算法和版本；
- 分数；
- 阈值；
- 冲突字段；
- 反例；
- 负责审核人。

对于供应商、客户、员工、物料等高影响主数据，默认采用“宁可不合并，不错误合并”的策略。

### 6.5 阶段 S4：业务语义候选

目标：把实体候选和事实候选组织为业务模型。

生成内容：

- 类候选；
- 属性候选；
- 关系候选；
- 状态机候选；
- 事件候选；
- 身份键候选；
- 时间字段候选；
- 权限边界候选；
- 业务规则候选；
- 与决策、预测和 Action 的连接候选。

候选必须标记：

~~~text
事实：来源直接支持
定义：领域人员定义
规则：可执行业务约束
假设：尚未确认
推断：由模型或统计得到
~~~

### 6.6 阶段 S5：Ontology 与映射编译

目标：将语义候选编译成可验证、可执行的工程产物。

编译器至少生成：

1. RDFS/OWL 或等价语义文档；
2. SHACL shapes；
3. canonical data product schema；
4. source-to-product mapping；
5. object projection；
6. event/state reconstruction；
7. provenance links；
8. access policy bindings；
9. validation tests；
10. impact analysis metadata。

编译过程不允许直接覆盖已发布版本。每次编译生成新版本和 Diff。

### 6.7 阶段 S6：数据产品构建与验证

目标：验证 Ontology 不是静态图，而是能从源数据稳定重建对象和事件。

必要检查：

- 主键唯一；
- 外键可解析；
- 目标粒度稳定；
- 时间顺序正确；
- event time 与 observed time 分离；
- 可用延迟符合声明；
- 状态可由事件重建；
- 依赖图无非法环；
- 空值和默认值符合契约；
- 源变更可以触发影响分析；
- 敏感字段没有越权传播。

### 6.8 阶段 S7：人工审核与发布

人工审核至少覆盖：

- 关键类和业务键；
- 高影响实体合并；
- 状态和事件定义；
- 来源冲突；
- 权限策略；
- 关键映射；
- 生产影响范围；
- 回滚版本。

发布前必须形成：

- Ontology Diff；
- Mapping Diff；
- Shape Diff；
- Data Quality Report；
- Provenance Coverage Report；
- Security Review；
- GateRun 汇总；
- Approval 记录。

## 7. 映射编译器设计

### 7.1 映射层次

~~~text
Source Asset
    ↓
Raw Landing
    ↓
Conformed Product
    ↓
Semantic Projection
    ↓
Ontology Object / Event
    ↓
Metric / Feature / Prediction / CandidatePlan
~~~

每一层都应有独立的 schema、版本、数据质量规则和血缘。

### 7.2 映射规则的最小结构

~~~yaml
mapping_id: supplier.promised_date.v1
source:
  asset: procurement_erp.purchase_order_line
  field: promised_delivery_date
target:
  product: purchase_order_line
  grain: one row per purchase order line version
  field: promised_delivery_at
transform:
  expression: parse_datetime(value, timezone="Asia/Shanghai")
identity:
  key: [purchase_order_id, line_id, version]
time:
  valid_time: promised_delivery_at
  observed_time: ingestion_time
  available_time: ingestion_time + 1 day
quality:
  not_null: true
  must_be_after: order_created_at
lineage:
  evidence_required: true
security:
  classification: internal
~~~

### 7.3 编译器验证

编译器必须在生成运行代码前验证：

- 目标字段存在；
- 变换表达式可以执行；
- 目标粒度可唯一识别；
- 时间字段有明确语义；
- null policy 已定义；
- 证据和血缘不为空；
- 安全标签不会丢失；
- 产物版本依赖可解析；
- 生成的 SHACL 与数据产品 schema 一致。

## 8. 时间、血缘和权限

### 8.1 四种时间必须分开

| 时间 | 含义 |
|---|---|
| valid_time | 事实在业务世界中生效的时间 |
| event_time | 业务事件发生的时间 |
| observed_time | 平台观察到该记录的时间 |
| available_time | 该记录允许进入计算的时间 |

预测和回放只能使用 available_time <= as_of_time 的资料。

### 8.2 血缘最小闭环

~~~text
Prediction
→ FeatureSnapshot
→ DataProductVersion
→ MappingSpec
→ EvidenceFragment
→ SourceAsset
~~~

任意一层无法回溯，预测或业务结论只能标记为不可发布。

### 8.3 权限传播

权限不能只放在 UI 层。必须沿以下路径传播：

~~~text
SourceAsset
→ EvidenceFragment
→ MappingSpec
→ DataProduct Field
→ Ontology Property
→ Function / Prediction
→ Application View
→ Action Parameter
~~~

计算结果不能默认比输入更开放。跨权限域的聚合需要显式策略和审计记录。

## 9. 门禁设计

| 门禁 | 类型 | 检查内容 | 失败处理 |
|---|---|---|---|
| G0 source.integrity | 硬 | 来源、版本、哈希、权限、连接器 | 阻断采集结果 |
| G1 evidence.coverage | 硬 | 关键字段和语义是否有可回源证据 | 标记缺证据并阻断 |
| G2 extraction.quality | 硬 | 解析完整性、位置、低置信片段 | 重解析或人工处理 |
| G3 identity.resolution | 硬 | 主键、实体合并、冲突和阈值 | 不合并或进入审核 |
| G4 semantic.integrity | 硬 | 类、关系、状态、业务键和 SHACL | 阻断 Ontology 候选 |
| G5 mapping.executable | 硬 | 映射可执行、粒度稳定、变换可重放 | 返回映射修复任务 |
| G6 data.temporal | 硬 | 时间边界、延迟、事件重建、泄漏 | 阻断数据产品 |
| G7 access.propagation | 硬 | 权限标签和跨域传播 | 阻断发布 |
| G8 domain.acceptance | 软/人工 | 业务语义、冲突、规则和影响 | 审批、拒绝或补充证据 |
| G9 release.governance | 硬 | 版本、Diff、审批、回滚、监控 | 不得发布 |

GateRun 必须绑定：

- Artifact hash；
- Evidence snapshot；
- validator version；
- configuration hash；
- violations；
- remediation；
- 执行者；
- 时间；
- 失效条件。

## 10. AI、人和确定性系统的职责边界

| 工作 | AI 候选 | 确定性系统 | 人 |
|---|---|---|---|
| 文档分块 | 可以 | 校验位置和格式 | 处理异常 |
| 术语抽取 | 可以 | 词典、去重、版本 | 确认定义 |
| 实体匹配 | 可以提出候选 | 执行规则和分数 | 审核高影响合并 |
| 类/关系发现 | 可以提出候选 | 检查引用和结构 | 批准业务含义 |
| SHACL 生成 | 可以生成草稿 | 运行验证 | 选择关键约束 |
| 字段映射 | 可以生成表达式 | 编译、执行、测试 | 确认权威来源 |
| 权限建议 | 可以发现风险 | 强制执行策略 | 授权 |
| 发布 | 不可独立发布 | Gate Engine 控制 | Domain/Release Owner 批准 |

## 11. 场景：供应商延误预测的建模过程

### 11.1 原始资料

~~~text
ERP 采购订单
供应商交付 Excel
合同 PDF
物流事件 API
催交邮件
收货系统
~~~

### 11.2 证据驱动的构建

1. 登记各来源的权威级别和访问范围；
2. 从合同中抽取“承诺交付日”的定义和例外；
3. 从 ERP 中抽取订单、订单行和供应商键；
4. 从物流事件中抽取发运、到达和异常事件；
5. 对齐 ERP 供应商编码、门户编码和合同名称；
6. 将“承诺日期”“预计日期”“实际到货日期”建成不同属性；
7. 将催交邮件作为 SupplierCommunicationEvent，而不是直接修改订单状态；
8. 生成 PurchaseOrderLine、Supplier、Shipment、DeliveryEvent；
9. 生成 SHACL、映射和数据质量规则；
10. 回放历史数据，确认状态和事件能够重建；
11. 经采购负责人确认后发布 Ontology 版本；
12. 下游模型才可以构建“观察时点可用”的延误特征。

### 11.3 为什么必须先做本阶段

如果没有本阶段，模型可能把：

- 实际到货日期当成预测输入；
- 邮件中的临时预计日期当成正式承诺；
- 供应商延误和运输延误混为一个标签；
- 同一个供应商拆成多个实体；
- 已经发生的结果泄漏进训练特征。

这种情况下，模型指标可能很好，但业务结论没有可信度。

## 12. 失败模式与降级策略

| 失败模式 | 不能做的事 | 必须做的事 |
|---|---|---|
| 来源无权限 | 猜测或复制内容 | 阻断并请求授权 |
| OCR 低质量 | 当作可靠事实 | 标记低置信并人工复核 |
| 主数据冲突 | 自动强制合并 | 保留候选和冲突 |
| 定义冲突 | 选择模型偏好的解释 | 提交 Domain Review |
| 时间不明 | 默认使用当前时间 | 标记时间未知并阻断预测 |
| 映射不可执行 | 只保留自然语言说明 | 返回可编译错误 |
| 权限无法传播 | 删除标签继续发布 | 阻断发布 |
| schema 变化 | 静默适配 | 生成影响分析和新版本 |
| 证据不足 | 用 LLM 常识补齐 | 标记假设并阻断关键结论 |

## 13. 实施路线

### P1：受控证据基础

必要功能：

- 本地文件、CSV、Excel、PDF、JSON 接入；
- SourceAsset 和 EvidenceFragment；
- 原文位置和哈希；
- 基本术语抽取；
- 证据检索；
- Evidence Coverage Gate。

验收结果：任何候选字段都能返回来源位置和快照版本。

### P2：实体与语义候选

必要功能：

- 术语词典；
- 确定性实体匹配；
- 概率匹配候选；
- 冲突面板；
- 类/关系/状态候选；
- 人工确认和拒绝；
- Candidate Ontology 版本。

验收结果：高影响实体不会被静默错误合并。

### P3：映射编译与数据产品

必要功能：

- MappingSpec；
- canonical schema；
- 代码/SQL 编译；
- 数据质量规则；
- 时间语义；
- 血缘和权限传播；
- SHACL 与运行时验证。

验收结果：从固定源快照可重建同一数据产品和 Ontology 投影。

### P4：生产连接器和运营

必要功能：

- 数据库、API、消息流连接器；
- 增量同步；
- schema drift；
- 调度、重试、死信；
- 运行监控；
- 版本发布和回滚；
- 多租户和密钥管理。

验收结果：源变更可被发现、隔离、评估并安全发布。

## 14. 设计验收清单

| 验收问题 | 检测方法 | 通过标准 |
|---|---|---|
| 每个关键语义是否可回源？ | 随机抽取类、属性、关系和映射，跳转原文位置 | 100% 有 EvidenceFragment 和 SourceAsset |
| 是否区分事实、定义、规则、假设？ | 检查 SemanticAssertion 类型和发布规则 | 未确认内容不得进入已发布事实 |
| 实体合并是否可解释？ | 重放匹配，查看字段、算法、阈值和冲突 | 每次合并都有可复现理由 |
| 是否存在错误时间泄漏？ | 用历史 as_of 回放并扫描 available_time | 未来资料不得进入数据产品和特征 |
| 映射是否真的可执行？ | 在隔离环境运行编译结果 | 目标 schema、粒度、质量检查全部通过 |
| 权限是否传播到底层结果？ | 用不同身份读取 Source、Ontology、View、Action | 越权访问被拒绝并有审计 |
| 源 schema 变化是否安全？ | 修改字段、类型、粒度后运行影响分析 | 生成新版本并阻断不兼容发布 |
| 人工审核是否有实际作用？ | 尝试绕过 ReviewTask 发布 | 没有批准不能进入 release |
| 发布是否可回滚？ | 发布新版本后回滚并重建投影 | 旧版本和依赖结果可恢复 |
| 同一输入是否可重建？ | 固定快照、配置和模型版本重跑 | 结构和内容哈希一致 |

## 15. 与当前 AI-FDE 原型的关系

当前仓库已经具备可复用基础：

- aifde.ontology.rdf：RDF 文档、哈希和安全复制；
- aifde.tools.validation：SHACL/验证适配；
- aifde.gates.engine：GateRun 和阶段状态控制；
- aifde.domain.artifacts：版本化 Artifact；
- software_delivery_demo.data_products：数据产品和质量检查；
- software_delivery_demo.features：时间安全特征和泄漏检查；
- software_delivery_demo.pipeline：端到端门禁示例。

仍需新增的生产能力：

- Source Registry 和 Connector SDK；
- Evidence Store 和带位置的证据索引；
- Term/Entity Resolution 服务；
- Semantic Candidate Builder；
- Mapping Compiler；
- Temporal/Provenance/Access Policy 运行时；
- Ontology Review Workbench；
- Ontology Release Manager；
- 连接器、schema drift 和运行监控。

本设计完成后，下一步应单独生成实施计划，按 P1 到 P4 将每个组件拆成测试优先的工程任务。
