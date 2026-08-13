# P2：专业 Agent 分工阶段设计

## 1. 阶段定位

P2 把单一 Agent 拆为职责边界清晰的专业角色，降低“一个 Agent 表面上完成所有工作”的风险。角色之间只通过 TaskContract 和 Artifact 交接，不共享未审计的隐式记忆。

## 2. 角色与权限

| 角色 | 负责 | 不能做 |
|---|---|---|
| Orchestrator | 目标澄清、拆任务、调度、汇总 gate | 不能生成业务事实或批准发布 |
| Decision Analyst | 用户、触发、输入、决策、动作、结果 | 不能私自定义数据事实 |
| Workflow Analyst | 观察真实路径、例外和人工判断 | 不能修改已发布 Ontology |
| Ontology Engineer | 类、属性、关系、状态、Ontology diff | 不能发布 |
| Data Product Engineer | 映射、粒度、质量、时间、血缘 | 不能跳过数据门禁 |
| Feature/Model Engineer | label、feature、泄漏、评估、预测 artifact | 不能把 prediction 当 fact |
| Decision/Optimization Agent | 约束、目标、候选方案、可行性 | 不能执行生产 Action |
| Application Agent | 把批准结果嵌入用户工作流 | 不能在 UI 绕过权限 |
| Challenger | 反例、漏洞、泄漏、冲突、越权 | 不能替代领域审批 |
| Deterministic Verifier | 运行代码、SQL、SHACL、数据检查 | 不能用语言解释替代测试 |
| Domain Owner | 确认业务含义和可接受性 | 不能修改审计历史 |
| Release Owner | 批准发布、执行和回滚 | 不能隐藏 gate 失败 |

## 3. 交接协议

每个 Agent 必须返回：task id、status、input artifact refs、output artifact refs、evidence refs、claims、assumptions、open questions、warnings、validation requests、recommended next tasks、model/prompt/tool versions、cost/latency。

关键 claim 没有 evidence ref 或明确 `inference/assumption` 标记时，交接无效。输出状态不能由 Agent 自己从 `draft` 改为 `approved`。

## 4. 供应商延误任务图

Decision Analyst 定义风险决策；Workflow Analyst 还原催交和升级路径；Ontology Engineer 评估缺失对象；Data Product Engineer 建立订单/交付/沟通产品；Feature/Model Engineer 生成 point-in-time feature 和预测；Decision Agent 生成催交/替代供应商/调整计划方案；Challenger 独立反驳；Domain/Release Owner 批准。

## 5. 门禁

为每个角色建立 schema contract、允许工具和禁止工具。一个角色输出缺少 evidence 时被拦截；一个角色试图改变 release status 时被拒绝；跨角色 context digest 不一致时任务进入 blocked。

## 6. 验收标准

- 每个角色有独立输入、输出、工具和权限边界。
- 关键 claim 缺 evidence 或 epistemic status 时交接失败。
- Domain Owner/Release Owner 的审批权不能被专业 Agent 继承。

## 7. 下游接口

P3 为这些角色增加 DAG 并发、artifact lock、冲突合并、重试和成本路由；角色定义本身保持稳定版本化。
