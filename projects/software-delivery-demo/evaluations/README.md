# 评估指南

## 运行

```powershell
$env:PYTHONPATH = "src"
python -m software_delivery_demo.cli_demo generate
python -m pytest tests/demo -q
```

## 重点检查

- 生成器公开表与 `_protected/hidden_truth.parquet` 分离；隐藏真值不参与特征构建。
- 数据产品记录固定粒度、主外键、事件可用时间和依赖无环规则。
- RDF/SHACL 负责对象关系和语义完整性；快照、标签、特征负责时间边界。
- 预测先和 `baseline-median-v1` 比较，再决定是否释放候选模型。
- 决策层只允许可行计划进入批准路径；不可行计划保留约束解释。
- `run_gate_scenarios` 会把每个对抗场景作为 Gate Engine 的独立 stage run 记录，并输出 `blocked` 或 `passed`。

## 业务链路

1. 运行变更影响分析，比较历史事实、工期预测和候选计划。
2. 由领域负责人审批计划，生成 Feedback。
3. 由 Release Owner 执行已审批的 Mock Action。
4. 查询 ActionOutcome 和 Feedback，作为下一轮评估的闭环输入。
