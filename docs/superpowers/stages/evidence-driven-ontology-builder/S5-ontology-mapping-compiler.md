# S5：Ontology 与映射编译阶段设计

## 1. 阶段定位

S5 把业务语义候选编译为可验证、可执行、可版本化的工程 artifact。它的产物不只是 TTL，而是 Ontology candidate、source-to-product mapping、RDFS/SHACL、时间语义、权限绑定和依赖 hash。

## 2. 目标与范围

对采购订单场景生成 Supplier、PurchaseOrder、DeliveryEvent、DeliveryException 等类；生成 identity、promised/actual date、delay state、hasSupplier 等属性和关系；把源 JSON/文档映射到 purchase_order canonical product。

编译器不覆盖已发布版本，不授予写生产权限，不把 unresolved/assumption 直接编译成 released fact。

## 3. 输入与输出

输入：经 S4 校验的 CandidateProposal、SourceRegistry、目标 Ontology version、数据产品 schema、访问策略。

输出：`OntologyCandidate`、`MappingSpec`、`ontology.ttl`、`shapes.ttl`、artifact hashes 和 compiler version。OntologyCandidate 必须包含 classes、properties、relationships、states、events、identity keys、temporal semantics、access policies、evidence refs、open questions 和 conflicts。

## 4. 编译流程

```text
CandidateProposal
  → mapping spec validation
  → source path resolution
  → canonical product schema
  → object/event/state projection
  → RDFS/Turtle rendering
  → SHACL rendering
  → deterministic validation
  → artifact hashes and diff
```

## 5. MappingSpec 最小结构

```yaml
mapping_id: mapping:PO-001:promised-date
source_field_path: $.purchase_orders[*].promised_date
target_product: purchase_order
target_grain: purchase_order
target_field: promised_delivery_date
transform_expression: parse_date(value)
identity_rule: purchase order external key
time_semantics: valid_time
null_policy: preserve
lineage_refs: [evidence:<sha256>]
security_policy: source-policy:erp-purchase-orders
version: 0.1.0
```

## 6. 编译验证

必须在生成可执行映射前验证：target product/grain、source path、主键唯一性、时间字段、null policy、lineage refs、security policy、RDFS 语法和 SHACL shape。非法 grain、未来 available time、缺失 source path 或空 lineage 必须硬失败。

## 7. 门禁与失败处理

`contract.compliance`、`semantic.integrity`、`executable.readiness` 和 `evidence.coverage` 是本阶段硬门禁。编译器失败时不生成可发布 artifact；只能保留带错误报告的 draft。已发布版本只能通过新版本和 diff 变更，不能原地覆盖。

## 8. 验收标准

- 同一输入、版本和编译器产生稳定 artifact hashes。
- Ontology Turtle 包含核心 classes/properties/relationships，SHACL 能被加载。
- 每个 canonical row 有 identity、grain、时间和 evidence refs。
- Ontology candidate 中的 assumption/inference/open questions 不被隐藏。
- 不覆盖已发布 Ontology，版本 diff 可计算。

## 9. 下游接口

S6 执行 MappingSpec 生成 Data Product；S7 审核 Ontology/Mapping/Shape/Data Diff。P1 领域 Agent 只能通过 artifact workspace 读取 S5 产物，不能直接修改编译结果。
