# AI-FDE Shipyard 分阶段设计文档索引

本目录把 Shipyard 的构建阶段拆成可以独立评审、独立实施和独立验收的阶段文档。每份文档都规定同一组边界：目标、前置条件、输入、输出、核心工作、数据契约、门禁、失败处理、验收标准和后续接口。文档中的“生产”指客户侧交付系统的目标能力，不指 Agent 在 Shipyard 内直接承担客户生产运行。

## 总体路线

```text
需求/业务决策
    ↓
证据驱动 Ontology Builder
    ├─ S0 数据源登记
    ├─ S1 解析与证据切片
    ├─ S2 术语与实体候选
    ├─ S3 实体解析与冲突处理
    ├─ S4 业务语义候选
    ├─ S5 Ontology 与映射编译
    ├─ S6 数据产品构建与验证
    └─ S7 人工审核与发布
    ↓
领域 Agent 团队
    ├─ P1 单领域、单任务图
    ├─ P2 专业 Agent 分工
    ├─ P3 并发、冲突与成本控制
    └─ P4 交付系统领域团队
```

## A. 证据驱动 Ontology Builder

设计总纲：[证据驱动 Ontology Builder 设计](../specs/2026-08-13-evidence-driven-ontology-builder-design.md)

| 阶段 | 独立设计文档 | 核心交付物 |
|---|---|---|
| S0 | [数据源登记](evidence-driven-ontology-builder/S0-source-registration.md) | SourceAsset、权限、连接器和源版本 |
| S1 | [解析与证据切片](evidence-driven-ontology-builder/S1-evidence-capture.md) | SourceSnapshot、EvidenceFragment、抽取报告 |
| S2 | [术语与实体候选](evidence-driven-ontology-builder/S2-semantic-candidates.md) | TermCandidate、EntityCandidate、初始语义候选 |
| S3 | [实体解析与冲突处理](evidence-driven-ontology-builder/S3-entity-resolution.md) | EntityMatch、冲突集、人工复核队列 |
| S4 | [业务语义候选](evidence-driven-ontology-builder/S4-semantic-ontology-candidates.md) | Fact、Definition、Rule、Inference、Assumption |
| S5 | [Ontology 与映射编译](evidence-driven-ontology-builder/S5-ontology-mapping-compiler.md) | OntologyCandidate、MappingSpec、RDFS/SHACL |
| S6 | [数据产品构建与验证](evidence-driven-ontology-builder/S6-data-product-validation.md) | Canonical Product、Provenance、质量报告 |
| S7 | [人工审核与发布](evidence-driven-ontology-builder/S7-review-release.md) | GateRun、Approval、OntologyReleasePackage |

## B. 领域 Agent 团队

设计总纲：[领域 Agent 团队设计](../specs/2026-08-13-domain-agent-team-design.md)

| 阶段 | 独立设计文档 | 核心交付物 |
|---|---|---|
| P1 | [单领域、单任务图](domain-agent-team/P1-single-domain-task-graph.md) | TaskContract、Artifact Workspace、基本编排 |
| P2 | [专业 Agent 分工](domain-agent-team/P2-specialist-agent-roles.md) | 专业角色、输入输出契约、交接协议 |
| P3 | [并发、冲突与成本控制](domain-agent-team/P3-concurrency-conflict-cost.md) | DAG 调度、锁、挑战、重试和预算 |
| P4 | [交付系统领域团队](domain-agent-team/P4-production-domain-team.md) | 供应商延误端到端构建、沙箱验证、Action 契约和反馈运营 |

## 阶段通用门禁

每个阶段至少通过以下门禁后才能向下游交付：

1. `contract.compliance`：输入输出符合阶段契约，版本和上下文指纹一致。
2. `evidence.coverage`：关键声明、映射和模型结论都能回放到允许的来源证据。
3. `semantic.integrity`：Ontology/RDFS/SHACL 与候选语义一致。
4. `data.quality`：粒度、主键、时间、空值、重复和质量规则通过。
5. `temporal.safety`：不把未来可用字段带入当前计算，明确 observed/available/event/valid time。
6. `adversarial.challenge`：独立 Challenger 已检查反例、冲突、越权、泄漏和失败路径。
7. `business.acceptance`：领域负责人确认业务定义、动作和例外路径。
8. `release.governance`：版本、审批、权限、回滚和发布责任完整。

AI 只能生成候选和解释，不能自行把候选标成已批准、已发布或已执行。
