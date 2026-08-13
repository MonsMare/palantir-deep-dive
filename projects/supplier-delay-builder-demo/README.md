# Supplier-delay evidence-driven Ontology Builder

这是一个可重复运行的最小 Palantir-like Builder 场景。它把两类真实工作
资料组织成带版本和时间语义的证据快照：ERP 采购订单 JSON，以及采购运营
Markdown 记录。

```powershell
pytest tests/builder/test_builder_flow.py -q
```

流程会依次执行：

1. 注册 source asset，捕获不可变 snapshot；
2. 按 JSONPath 和行号切片 evidence fragment；
3. 生成带 evidence/context binding 的语义候选；
4. 解析同一供应商的两个名称表示，并保留匹配证据；
5. 编译 purchase-order 数据产品、RDFS 候选、SHACL shapes 和 provenance；
6. 通过 GateEngine 记录八类门禁结果；
7. 经 domain owner 批准后生成 release package，再由 GateEngine 转为 released。

示例数据包含三个采购订单、`Acme Industrial` 与 `Acme Industries` 两种
供应商表示、承诺日期变更、实际到货事件，以及“事件发生后一天才可用”的
运营记录。`canonical_rows` 和 `provenance_rows` 展示了每条产品记录的证据
和映射血缘。

也可以运行故障路径：

```python
run_supplier_delay_builder_demo(
    Path("projects/supplier-delay-builder-demo"),
    force_supplier_conflict=True,
)
```

该路径将高影响供应商合并标记为 unresolved，`adversarial.challenge` 门禁
失败，阶段进入 `blocked`，不会生成 release package。Builder 不能作为自己
的审批人。
