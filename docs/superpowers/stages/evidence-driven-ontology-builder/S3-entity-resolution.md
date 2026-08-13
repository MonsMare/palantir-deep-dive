# S3：实体解析与冲突处理阶段设计

## 1. 阶段定位

S3 判断不同来源记录是否可能指向同一个业务实体，并把“确认”和“可能匹配”严格分开。它解决 Ontology 最危险的错误之一：把两个供应商错误合并后，所有预测、权限和动作都建立在错误身份上。

## 2. 目标与范围

采用可重放的多级匹配：来源显式 external key、强身份字段、规范化名称、显式 alias、概率匹配和人工确认。输出 `EntityMatch`、冲突集、匹配算法版本、阈值、字段、反例和审核任务。

## 3. 输入与输出

输入：S2 EntityCandidate、source evidence、canonical entity registry、alias table、匹配策略和高影响实体清单。

输出：包含 candidate id、canonical id、score、threshold、matching fields、algorithm version、conflict refs、status、candidate version 和 context digest 的 `EntityMatch`。

## 4. 匹配顺序

1. 证据中明确提供且可回放的 external key：可进入 `confirmed`。
2. 多个强 identity feature 一致：通常 `probable_match`，高影响实体需人工确认。
3. 规范化名称一致：`probable_match`，不能凭名称自动 confirmed。
4. 显式 alias table 命中：`probable_match`，必须保留冲突。
5. 模糊相似度低于阈值或字段冲突：`unresolved` 或 `rejected`。

任何由 provider 注入但未出现在 source evidence 的 external key 都必须被拒绝。

## 5. 冲突处理

冲突不是清洗噪声，而是业务状态。每个冲突要记录字段、来源、authority、时间、候选解释、反例和 owner。供应商、客户、员工等高影响对象采用“宁可不合并，不可错误合并”的默认策略。

## 6. 门禁与失败处理

硬门禁：匹配结果有 score/threshold/fields/algorithm version、external key 有证据支持、canonical entity 存在、候选与上下文版本一致、冲突未被隐藏。

失败时：匹配失败保持 unresolved；低分或冲突进入人工队列；不能用别名直接覆盖候选 ID；不能通过 prompt 让 Agent 提升匹配状态。

## 7. 验收标准

- exact external key 且来源显式提供时才可 confirmed。
- 名称匹配和 alias 匹配均保留 probable_match。
- 同一候选在不同策略版本下的结果可重放并可比较。
- 高影响 unresolved match 会阻断 S7 发布。
- 每次合并都能回到 evidence、algorithm version 和 reviewer。

## 8. 下游接口

S4 用 match 结果决定关系候选，但不能把 probable_match 当作事实；S6 将 unresolved/conflict 传播到质量报告；S7 根据高影响冲突门禁决定是否允许发布。
