# Palantir-like AI-FDE 工程内核

本仓库是一个以证据、Ontology、可计算特征、预测、决策优化和受治理动作闭环为主线的 AI-FDE 研究与验证项目。

当前实现已经把 `supplier-delay` 和 `software-delivery` 做成两个可运行的 Domain Pack，并提供：

- SourceConnector、EvidenceFragment、数据产品和字段级 provenance；
- RDFS/SHACL Ontology IR 编译与 release gate；
- point-in-time Feature/Label/Prediction/Decision runtime；
- Model Registry、时间评估、确定性优化和 Action Broker；
- 领域 Agent 团队、追加式 Artifact Workspace、DAG、预算和 stale 门禁；
- audit、metrics、readiness 和双领域端到端验收。

从测试开始：

```powershell
pytest -q
python -m compileall -q src tests
```

完整的生产边界、验收证据和上线前替换项见：[生产 AI-FDE 增强验收说明](docs/production-ai-fde-acceptance.md)。

本项目中的本地文件连接器、SQLite、JSONL Action adapter 和 deterministic solver 是可替换的工程边界，不等同于已经接入真实 ERP/Jira 或获得客户生产动作授权。
