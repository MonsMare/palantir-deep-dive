# 软件交付 Ontology Demo

这是一个完全本地、确定性、只使用 Mock Action 的 Palantir-like 工程样例。
它把需求、变更、工作项、事件、数据产品、RDFS/SHACL、本体快照、时间安全特征、预测、候选计划、Action 和 Feedback 串成一条可回放链路。

## 快速开始

```powershell
$env:PYTHONPATH = "src"
python -m software_delivery_demo.cli_demo generate
python -m pytest tests/demo -q
```

运行完整管线并查看 Gate Engine 记录：

```powershell
python -m software_delivery_demo.cli_demo pipeline
python -m software_delivery_demo.cli_demo scenarios
```

## 复现实验

- `build_data_products` 和 `run_quality_checks`：检查数据粒度、主外键、事件区间和依赖环。
- `project_objects_to_graph` 和 `validate_domain_graph`：运行 RDF/SHACL 语义门禁。
- `build_project_snapshot`、`build_features`、`build_labels`：按 `as_of_time` 重建历史视图，禁止未来字段进入特征。
- `BaselineModel` 与 `DeliveryModel`：先建立中位数基线，再用时间对齐标签训练候选模型。
- `build_candidate_plans`：枚举可行计划，容量不足时只返回不可行并带原因的候选。
- `run_gate_scenarios`：复现缺少需求负责人、冲突描述、未来完成字段泄漏、依赖环、负容量、无标签历史、容量超载、无审批 Action、重复 Action 和用户拒绝。

## API/UI

`software_delivery_demo.app.create_demo_app` 提供只读需求、需求详情、变更影响、工期预测、计划审批、Mock Action 执行和 Feedback 查询接口。
`software_delivery_demo.ui` 提供 Streamlit 视图的数据契约和渲染适配器；Streamlit 是可选依赖，未安装时核心测试仍可运行。

所有状态晋级都由平台 `aifde.gates.engine.GateEngine` 执行并留下 GateRun；所有 Action 都经过平台 `ActionBroker`，不会写入真实项目管理系统。
