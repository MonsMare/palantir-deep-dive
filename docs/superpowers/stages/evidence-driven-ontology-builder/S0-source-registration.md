# S0：数据源登记阶段设计

## 1. 阶段定位

S0 是证据驱动 Ontology Builder 的入口。它解决“系统到底在相信什么来源、谁对来源负责、来源何时可用、谁可以看”的问题。未经登记的文件、聊天内容或模型输出不得成为后续 Ontology 的事实依据。

## 2. 目标与范围

目标是把 ERP、数据库、API、事件流、PDF、Word、Excel、CSV、邮件导出和业务词典登记为可审计的 `SourceAsset`，并绑定 owner、authority、classification、access policy、schema/content fingerprint 和 connector version。

本阶段不做语义推断、不合并实体、不发布 Ontology、不训练模型。

## 3. 输入与输出

输入：连接器配置、源 URI、数据分类、业务 owner、访问策略、预计刷新频率、源系统版本和采集方式。

输出：

- `SourceAsset`：稳定的来源身份，不等于业务实体。
- `AccessPolicyBinding`：来源的读取范围、脱敏规则和角色限制。
- `ConnectorRegistration`：连接器类型、版本、能力和失败策略。
- `SourceRegistrationReport`：登记结果、缺失字段和风险。

最小 `SourceAsset` 字段：

```yaml
source_asset_id: erp-purchase-orders
source_type: json|csv|database|api|event_stream|pdf|docx|xlsx
source_uri: fixture://supplier_purchase_orders.json
owner: procurement-data-owner
authority_level: 5
classification: internal
access_policy_id: policy:procurement
schema_fingerprint: purchase-order-v1
connector_version: fixture-connector-v1
metadata:
  refresh: daily
```

## 4. 工作流程

1. `discover`：列出候选来源和连接方式。
2. `classify`：确定来源类型、敏感级别、权威等级和数据责任人。
3. `fingerprint`：计算 schema/content fingerprint，记录字段变化基线。
4. `authorize`：绑定最小访问策略，验证执行身份能读取但不能写回生产。
5. `register`：生成不可复用的 source asset identity，写入 append-only registry。
6. `test-connection`：运行读取、版本、权限、重复采集和故障测试。
7. `handoff`：把登记报告交给 S1；没有通过的来源只能进入 blocked 队列。

## 5. 不可变性与时间原则

SourceAsset 的身份和 authority 一旦登记不能静默修改。owner、classification、policy 或 schema 变化必须生成新版本或新登记记录。S0 要区分 `captured_at`、`observed_at`、`available_at` 和 `connector_version`；后续预测只能使用已到 `available_at` 的数据。

## 6. 门禁与失败处理

硬门禁：来源身份非空、URI 可追溯、owner 存在、authority 已赋值、classification 和访问策略存在、fingerprint 可计算、连接器版本可记录、读取测试通过。

失败时：权限失败进入 `blocked`；fingerprint 不稳定进入人工复核；来源 owner 不明确不得由 Agent 猜测；来源内容包含聊天/模型输出标记时只能登记为非权威辅助资料，不能进入事实链。

## 7. 验收标准

- 同一 `(source_asset_id, version)` 的内容或 lineage 字段变化会被拒绝覆盖。
- 未登记来源不能创建 EvidenceFragment。
- 读取权限与写权限分离，S0 不授予生产写入能力。
- 任意后续证据都能回到 SourceAsset、source version 和 connector version。
- 重新运行登记可以产生相同 fingerprint 和相同登记结果。

## 8. 下游接口

S1 只接受登记成功的 `SourceAsset`，通过 `capture(asset_id, version, content, observed_at, available_at, extraction_version)` 创建 `SourceSnapshot`。S0 的 policy 和 classification 必须随快照传递到证据、映射、Ontology 属性和 Agent 工具调用。
