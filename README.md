# AI-FDE Shipyard

本仓库的唯一主线是：构建一个能够持续产出、评测、发布和升级客户业务决策系统的 AI-FDE Shipyard。

这里的比喻关系是：

```text
AI-FDE Shipyard（船坞）
  → 构建、验证、评测、打包和交付
客户业务决策系统（轮船）
  → 在客户环境中持续接收数据、预测、决策并执行经授权的业务动作
```

Shipyard 可以在沙箱和历史回放中运行目标系统的副本，用来证明其语义、数据、模型、决策、工作流和治理质量；它不承担客户生产环境中的持续预测、决策或业务动作执行。

当前仓库已经具备 Shipyard 所需的一组 Python 工程内核，并把 `supplier-delay` 与 `software-delivery` 作为可运行的领域样板：

- SourceConnector、EvidenceFragment、数据产品和字段级 provenance；
- RDFS/SHACL Ontology IR 编译与 release gate；
- point-in-time Feature/Label/Prediction/Decision 沙箱运行时；
- Model Registry、时间评估、确定性优化和受治理 Action 模拟；
- 领域 Agent、追加式 Artifact Workspace、DAG、预算和 stale 门禁；
- audit、metrics、readiness 和跨领域端到端验收。

这些运行时模块是 Shipyard 用来构建和评测“轮船”的参考内核，不代表 AI-FDE 自己就是客户生产运行时。

设计主线从 [AI-FDE Shipyard Workbench 设计](docs/superpowers/specs/2026-08-15-ai-fde-shipyard-workbench-design.md) 开始。Workbench 是当前人机协作界面；Linear、客户生产运行时和复杂多租户部署均属于后续边界，不是当前核心构建目标。

## Local Web Runtime

当前 L0 版本提供浏览器优先的本地 Shipyard Workbench。它是构建、评测、门禁和发布候选控制面，不是客户生产预测或决策运行时。

在仓库根目录执行：

~~~powershell
python -m pip install -e ".[web]"
Set-Location workbench
npm ci
npm run build
Set-Location ..
shipyard init . --owner alice
shipyard web --project .
~~~

默认地址是 http://127.0.0.1:3080。.shipyard/ 是本地状态目录，Workbench 的 workbench/dist/ 是构建生成物，两者都不会进入版本控制。如果 Workbench 资源不存在，先在 workbench 目录运行 npm run build。

现有 scripts/shipyard_seed.py 只初始化演示数据库，不启动 Web。Local Web 不连接客户系统，也不执行生产 Action；headless、团队内网、Docker 和客户侧运行时属于后续部署边界。

从测试开始：

```powershell
pytest -q
python -m compileall -q src tests
```

Shipyard 内核的能力边界和交付验收见：[AI-FDE Shipyard 内核验收说明](docs/production-ai-fde-acceptance.md)；文档入口见：[docs/README.md](docs/README.md)。

本项目中的本地文件连接器、SQLite、JSONL Action adapter 和 deterministic solver 是可替换的构建/评测边界，不等同于已经接入真实 ERP/Jira 或获得客户生产动作授权。
