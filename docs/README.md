# AI-FDE Shipyard 文档入口

本目录只保留一条主线：Shipyard 如何与人协作，把业务决策问题构建成可评测、可发布、可交付的客户业务决策系统。

## 当前权威设计

1. [Shipyard Workbench 设计](superpowers/specs/2026-08-15-ai-fde-shipyard-workbench-design.md)：当前产品边界、Workbench 交互、生命周期、Artifact、Gate、Agent 协议和第一条垂直切片。
2. [证据驱动 Ontology Builder 设计](superpowers/specs/2026-08-13-evidence-driven-ontology-builder-design.md)：从散乱资料到证据、语义候选、可执行映射和 Ontology Release 的构建阶段。
3. [生产级 Ontology 产出能力改造](superpowers/specs/2026-08-13-production-ontology-hardening-design.md)：字段级时间安全、实体治理、计算契约和发布质量边界。
4. [领域 Agent 团队设计](superpowers/specs/2026-08-13-domain-agent-team-design.md)：在 Builder 之后如何组织专业 Agent、Challenger、Verifier 和人工审批。
5. [软件研发需求对齐与工期预测样板](superpowers/specs/2026-08-11-software-requirements-alignment-delivery-forecasting-design.md)：第一条用于体验完整 Shipyard 流程的垂直领域。
6. [Shipyard 内核验收说明](production-ai-fde-acceptance.md)：当前实现能证明什么、不能宣称什么、下一步怎样交付 Workbench。

## Phase 0 可运行垂直切片

当前实现已包含软件交付领域的第一条 Workbench review/release-eligibility 链路：

```text
本地项目资产
  → Shipyard seed Workspace / Decision Case / typed Artifact
  → sandbox Gate snapshot
  → system gate-runner 经 Application Service 记录 Gate Review
  → 人类审阅 Agent Proposal 与 Gate evidence
  → required gates 全部通过后生成 Release Candidate manifest
```

可用命令：

```powershell
python scripts/shipyard_seed.py --database .tmp/shipyard.db --owner alice
```

这条命令只初始化本地 SQLite；它不是客户生产 runtime、完整 ML 评测实验室、生产 connector、Docker 部署或 Linear 适配器。若当前 Python 环境缺少 demo pipeline 的可选评测依赖，初始化仍会生成可审计的 blocked Gate Review，而不会错误放行候选发布。

## 研究资料

[Palantir Foundry / Ontology / AIP 工程方法 Wiki](../wiki/README.md) 保留官方文档研究、方法论、工程公式和数据产品研究，作为 Shipyard 的方法来源，不作为当前软件实现规格。

## 文档规则

- Shipyard 是构建和评测平台；客户生产运行时是交付物，不能混写为同一个系统。
- Agent 只能提交候选 Artifact；应用服务、Gate 和人工审批才是状态、发布和权限的写入边界。
- Linear 只能作为未来可选适配器；当前人机协作以 Shipyard Workbench 为准。
- 旧方案和历史实施计划放在 [superseded archive](archive/superseded/README.md)，不作为当前路线依据。
