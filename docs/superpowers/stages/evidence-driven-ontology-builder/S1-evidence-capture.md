# S1：解析与证据切片阶段设计

## 1. 阶段定位

S1 把原始文件或记录变成可定位、可重放、带时间和访问边界的 `EvidenceFragment`。它不回答“这句话是否为业务事实”，只保证“这段内容确实来自哪里”。

## 2. 目标与范围

支持 JSON/CSV/数据库行/API 记录以及 PDF、Word、Excel、Markdown 等文档的解析、OCR、表格识别、段落切片和结构化定位。保留原文、归一化文本、原始 source hash、locator、抽取方法、版本、confidence 和 event time。

不在本阶段做实体合并、事实发布、LLM 自由改写或丢弃原始定位。

## 3. 输入与输出

输入：S0 `SourceAsset`、原始内容、source version、观察/可用时间、解析器和抽取器版本。

输出：`SourceSnapshot`、`EvidenceFragment`、`ExtractionReport` 和 `ParserWarning`。最小证据契约：

```yaml
evidence_id: evidence:<sha256>
snapshot_id: snapshot:<sha256>
source_asset_id: erp-purchase-orders
source_version: 2026-08-13
locator: $.purchase_orders[0] | page:4/table:orders/row:12 | line:3-4
content: ...
normalized_content: ...
content_hash: <sha256>
source_content_hash: <sha256>
observed_at: 2026-08-13T09:00:00Z
available_at: 2026-08-13T10:00:00Z
extraction_method: deterministic-json|mineru|ocr|table-parser
extraction_version: raw-v1
confidence: 0.0-1.0
```

## 4. 工作流程

1. 对 SourceSnapshot 做字节规范化和 SHA-256 内容寻址。
2. 选择与 source type 匹配的确定性解析器；必要时调用 OCR/文档抽取器。
3. 为段落、行、表格行、单元格或 JSONPath 创建 locator。
4. 保存原始 content 与 normalized content；归一化不能替代原文。
5. 计算片段 hash，并验证 locator 能从快照重放出同样内容。
6. 记录 event/observed/available time 和 extraction confidence。
7. 生成 ExtractionReport，只有高质量片段才进入 S2。

## 5. 关键技术原理

- 内容寻址保证同一快照可重建；locator + source hash 保证证据可回放。
- 原文/归一化双存储避免清洗过程改变事实表述。
- `available_at` 是进入特征和预测计算的边界，不能用未来才可用的片段回填过去。
- 解析器失败显式暴露为 warning/block，不用 LLM 猜补缺失文本。

## 6. 门禁与失败处理

硬门禁：快照 hash 与内容一致、locator 可重放、片段 hash 一致、时间带时区且 `observed_at <= available_at`、source lineage 完整、访问策略不丢失。

失败时：无法定位的内容标记 `unusable`；OCR 置信度低于阈值进入复核；重叠片段允许共存但必须保留各自 locator；模型输出或聊天文本不得伪装成原始来源。

## 7. 验收标准

- 修改片段 content、locator、source hash 或 source version 会失败。
- 同一快照重跑抽取产生相同 evidence id。
- 每个下游 assertion、term、entity、mapping 都能引用一个或多个 fragment。
- 采集延迟可在 `observed_at` 与 `available_at` 中重建。
- 解析失败不会静默变成空字符串或模型补全文本。

## 8. 下游接口

S2 读取 `list_fragments(snapshot_id)`，只能拿到已登记且可回放的片段；S4–S7 必须保留 `evidence_id`，不能只保留向量检索结果或聊天消息。
