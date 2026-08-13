# P4：生产领域 Agent 团队阶段设计

## 1. 阶段定位

P4 将前面各阶段组合成一个可运营的领域系统。它不是“多个聊天机器人”，而是围绕已发布 Ontology、数据产品、预测、决策和 Action 的受控闭环。

## 2. 输入与输出

输入：S7 `OntologyReleasePackage`、发布的 DataProductVersion、Evidence Index、Access Policy、模型/决策版本和用户业务工作台。

输出：PredictionArtifact、CandidatePlan、ActionRequest、ActionOutcome、Feedback、ActualOutcome、运营指标和下一轮评估任务。

## 3. 端到端场景：供应商延误风险

业务用户提出：“找出未来 14 天可能延误的订单，并推荐催交、替代供应商或生产调整方案。”

系统按以下链路工作：

1. Orchestrator 建立 DecisionContract 和 TaskGraph。
2. Decision Analyst 确认用户、触发条件、风险阈值、可用动作和不可接受后果。
3. Workflow Analyst 识别采购员如何处理承诺变更、邮件、物流停滞和升级。
4. Ontology Engineer 消费 S7 release，若缺少 SupplierCommunicationEvent/Shipment 等对象，只生成 Ontology diff。
5. Data Product Engineer 构建订单行、交付事件、供应商沟通、生产影响数据产品。
6. Feature/Model Engineer 以 as-of time 生成过去 90 天延误率、承诺变更次数、物流停滞、未完成订单、关键物料和可替代供应商等特征，产出 label、leakage report、evaluation 和 PredictionArtifact。
7. Decision/Optimization Agent 将预测导入约束问题，比较催交、替代供应商、调整生产顺序和继续观察方案。
8. Challenger 检查未来泄漏、错误归因、不可替代订单、权限和置信度阈值。
9. Domain Owner 审核业务语义，Release Owner 批准上线；Application Agent 把风险队列、证据、方案和审批入口嵌入采购工作台。
10. 用户批准后创建 ActionRequest，经 Policy/Action Broker 执行；ActionOutcome、实际到货和用户反馈回写 Ontology/data product，进入模型评估与运营。

## 4. 生产 Artifact 链

```text
OntologyReleasePackage
  → DataProductVersion
  → FeatureCatalog + LabelDefinition + LeakageReport
  → ModelEvaluation + PredictionArtifact
  → DecisionProblem + CandidatePlan
  → ActionRequest → ActionOutcome
  → Feedback + ActualOutcome
```

每一层必须保留输入 hash、版本、evidence refs、权限、owner 和 gate run。Prediction 不是事实，CandidatePlan 不是执行结果，ActionRequest 不是 ActionOutcome。

## 5. 用户交互与嵌入

用户不应被迫离开工作系统进入孤立聊天窗口。Application Agent 将风险排序、解释、来源、置信度、候选方案、成本/约束、审批按钮和反馈入口嵌入采购工作台、订单详情、异常队列和日报。聊天只作为解释和查询入口，所有改变现实的动作都走 ActionRequest、审批和 Action Broker。

## 6. 生产质量与运营

监控四类指标：

- 工程：任务成功率、延迟、成本、锁冲突、重试、gate stale。
- Agent：证据覆盖、契约满足、挑战发现率、人工修改率、事实错误率。
- 模型/决策：校准、召回、漂移、方案可行率、约束违反率、拒绝率。
- 业务：延误减少、加急成本、交付稳定性、人工处理时间、用户采纳率。

模型只在评估、漂移和反馈门禁通过后更新；高风险动作默认 human-in-the-loop。

## 7. 门禁

生产 Action 前必须通过 contract、evidence、semantic、data quality、temporal safety、adversarial、business acceptance 和 release governance 门禁。高风险动作必须有人工批准；模型低置信度、权限不足、方案不可行或 Action 执行失败时不得自动升级权限。

## 8. 失败和降级

数据延迟或质量下降时降级到规则/基线；预测置信度低时显示“需人工判断”；优化无可行方案时说明冲突约束；权限不足时拒绝并显示缺少授权，不通过 Agent 猜权限；Action 失败时保留请求与回执，支持幂等重试和人工接管。

## 9. 验收标准

- 用户可以在原业务流程中看到风险、证据、方案和审批入口。
- 任一预测可回放到 feature snapshot、data product、mapping、evidence 和 source。
- 任一方案可解释目标、约束、预测输入、成本和不可行原因。
- 未审批 Action 不会写入生产系统。
- 实际结果和用户反馈能回写并形成下一轮评估样本。
- 领域团队能在数据冲突、模型低置信度、权限不足和 Action 失败时安全降级。

## 10. 下游接口

P4 的输出进入业务运营和反馈评估，不直接替代领域 owner。新领域复制时复用 TaskContract、Artifact Workspace、Gate Engine、Action Broker 和反馈协议，并重新完成本领域语义与权限审核。

## 11. 阶段结论

P4 的完成标志不是 Agent 能回答更多问题，而是它能在受控权限下，把已发布 Ontology 转化为可验证预测、可比较决策和可审计行动，并让行动结果反过来改善数据、模型和业务流程。
