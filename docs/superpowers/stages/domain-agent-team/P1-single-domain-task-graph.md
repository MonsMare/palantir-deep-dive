# P1：单领域、单任务图阶段设计

## 1. 阶段定位

P1 是领域 Agent 团队的最小可用形态：只服务一个领域、一个业务决策和一条受控任务图。目标不是让多个 Agent 自由聊天，而是让每个 Agent 围绕版本化 Artifact 交接工作。

## 2. 适用场景

首个场景采用“未来 14 天供应商订单延误风险与跟进行动”：输出风险排序、证据、建议动作和待审批 ActionRequest，不直接写生产系统。

## 3. 前置输入与输出

前置输入必须来自 S7 发布包：Ontology、Canonical Data Product、Evidence Index、Access Policy 和 gate manifest。

输出：`TaskContract`、`TaskGraph`、`Artifact Workspace` 中的 draft artifacts、ChallengeReport、ValidationResult、HumanReviewTask 和最终 ActionRequest。

最小任务契约：

```yaml
task_id: supplier-delay-001
objective: identify orders at risk in the next 14 days
stage_id: model.inference
allowed_input_artifacts: [ontology-release, purchase-order-product]
required_output_kinds: [RiskAssessment, Recommendation]
forbidden_assumptions: [actual_delivery_date_available_at_prediction_time]
acceptance_tests: [every claim has evidence or is marked inference]
escalation_conditions: [source conflict, missing label, permission failure]
budget: {max_model_calls: 20, max_wall_time_minutes: 30}
```

## 4. 工作流程

1. Orchestrator 接收业务目标，建立目标、范围、风险等级和验收条件。
2. 读取已发布 Ontology 和数据产品，生成 DAG：决策澄清 → 工作流观察 → 特征/模型 → 方案 → 挑战 → 验证 → 人审。
3. 每个节点读取授权 artifact，产生新版本 draft，不修改输入事实。
4. Challenger 和 Deterministic Verifier 独立消费 draft。
5. 通过 Gate Engine 后进入 Domain Owner review；未通过进入 remediation。

## 5. 质量边界

Agent 的自评只能作为 telemetry，不能成为 gate。聊天上下文不是事实源；Agent 必须引用 workspace artifact、evidence refs 和 tool call refs。Orchestrator 不生产业务结论、不持有发布权限。

## 6. 门禁

必须通过 contract、evidence、schema、temporal、semantic、adversarial 和 business acceptance 门禁。缺少实际到货标签时只能输出数据缺口任务，不能声称完成预测训练。

## 7. 验收标准

- 完整 happy path 能从 TaskContract 走到 Domain Review。
- 缺少标签、证据或权限时进入 blocked/remediation。
- Agent 不能修改输入事实、发布状态或生产 Action。

## 8. 下游接口

P2 在 P1 的 TaskContract、Artifact Workspace、状态机和交接格式上增加专业角色；P4 在同一边界上接入 Action Broker 和反馈。
