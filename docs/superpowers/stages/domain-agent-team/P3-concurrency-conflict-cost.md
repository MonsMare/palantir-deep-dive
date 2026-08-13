# P3：并发、冲突与成本控制阶段设计

## 1. 阶段定位

P3 解决 Agent 团队规模扩大后最容易出现的工程问题：并发写冲突、循环重试、上下文漂移、质量门禁被绕过、成本不可控和模型输出不可复现。

## 2. 调度模型

输入是 P2 的角色契约、任务 DAG、artifact 版本/哈希、权限上下文、质量门禁、
成本与延迟预算。输出是可重放的调度计划、锁与版本记录、冲突报告、重试/升级
记录、预算消耗和最终交接状态；被拒绝或超预算的任务必须留下审计记录。

Orchestrator 根据 TaskContract、阶段、输入 artifact version、能力标签、工具权限、风险等级、成本预算和延迟预算构建 DAG。无依赖任务可并行；有语义依赖的任务必须按 DAG 顺序执行。

## 3. 输入与输出

本阶段输入是 P2 的角色契约、任务 DAG、artifact 版本/哈希、权限上下文、质量门禁、
成本与延迟预算；输出是可重放的调度计划、锁与版本记录、冲突报告、重试/升级记录、
预算消耗和最终交接状态。被拒绝或超预算的任务必须留下审计记录。

## 4. Artifact 并发控制

每个写入必须携带：artifact id、parent hash、版本、变更范围、锁 token、输入 hash 和输出 hash。冲突检测包含同一 artifact、同一语义字段、同一 Ontology 类/属性和同一数据产品 schema。冲突不能由最后写入者覆盖；应重试合并或创建人工仲裁任务。

## 5. 重试与升级

可重试：网络临时失败、解析服务超时、无状态工具失败、确定性资源不足。不可自动重试：业务定义冲突、权限拒绝、证据不足、高影响实体 unresolved、预测标签不存在、发布 gate 失败和人工拒绝。

重复失败、Agent 结论冲突、输入版本过期、权限无法传播或影响生产 Action 时，升级 Domain Owner/Release Owner。

## 6. 成本与模型路由

每个 TaskContract 规定最大 model calls、token、wall time、并发数和重试预算。简单分类/字段抽取走规则或小模型；复杂语义冲突走强模型；优化使用确定性 solver/rule engine；生产 Action 需要 policy + 人工批准。缓存必须绑定 prompt/model/tool/input/artifact hashes，不能用旧结果冒充新版本。

## 7. Challenger 与 Verifier

Challenger 使用独立上下文、独立调用链或反例生成策略；Verifier 运行确定性测试。二者不能只复述 Builder 的自评。挑战结果必须产生 ChallengeReport，包含被挑战 claim、输入 hash、反例、严重性和 remediation。

## 8. 门禁

并发写、输入版本、预算、挑战和审计是硬门禁；预算耗尽必须 blocked，不得无限循环。

## 9. 验收标准

- 并发修改同一 artifact 时至少一个写入被拒绝或进入显式 merge。
- 输入版本变化会使依赖任务和旧 gate stale。
- Challenger 能发现未来字段泄漏、悬空实体、缺证据和越权。
- 所有调用可按 model/prompt/tool/input hash 重放。

## 10. 下游接口

P4 以 P3 的调度、锁、预算、审计和升级机制承载生产领域团队；不能为了低延迟关闭硬门禁。
