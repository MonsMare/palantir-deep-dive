# Task 7 实现报告：RDF 与 SHACL 验证工具

## 实现范围

- 增加 `OntologyDocument`：RDF 文本加载、图语义哈希、ontology version/source refs 元数据和序列化。
- 增加 `ShapeLoader`：SHACL NodeShape/property 约束加载、稳定 shapes hash 和可读约束对象。
- 增加 `ShaclValidator` 与 `ValidationResult`：返回 `passed`、`violations`、`warnings`、`data_hash`、`shapes_hash`、`validator_version`、`evidence_refs` 和可读 `message`。
- 增加 `SemanticValidationTool`：声明 `Capability.VALIDATE`，只能由 `ToolGateway` invocation token 调用，并返回结构化 `ToolResult`。
- 增加 `register_semantic_gate` 集成：将 SHACL 结果登记为现有 GateEngine 的 `semantic.integrity` hard gate；失败结果会出现在 blocking gates 中并阻断 Ontology stage transition。
- 增加 Requirement 缺 owner、valid Requirement、SHACL message/violation 可读性、哈希稳定性、输入图不变性、Gateway 能力边界和 hard gate 阻断测试。

## TDD 记录

1. 先创建 `tests/fixtures/software_delivery_shapes.ttl` 与 `tests/gates/test_shacl_validator.py`。
2. 首次运行按要求失败：测试收集阶段因现有 domain gate API 只有 `GateResult` 而测试草稿引用了不存在的 `GateSeverity/GateStatus`。
3. 修正测试以匹配现有 `ToolContext`、`ToolGateway`、`GateEngine` 契约后，骨架阶段得到 6 个 `NotImplementedError` 红灯。
4. 修复两个 Turtle fixture 的类型语句为 `aifde:req-1 a aifde:Requirement ;` 后进入实现迭代。

## 修复轮次：fail-closed 与防御不可变性

- 在 `tests/gates/test_shacl_validator.py` 先新增 3 个回归测试：
  - fallback Turtle parser 必须拒绝缺少 `@prefix` 终止点的 malformed input。
  - `ShapeLoader` 必须拒绝未实现的 SHACL 谓词，例如 `sh:maxCount`、`sh:datatype`，不得把 unsupported-only shape 当成空约束通过。
  - `ValidationResult` 的 `violations`、`warnings`、`evidence_refs` 不允许 `append`、`assign`、`pop` 等嵌套 mutation，且 `model_dump(mode="json")` 仍输出 JSON-compatible list。
- RED 验证：`C:\ProgramData\anaconda3\python.exe -m pytest tests/gates/test_shacl_validator.py -q` 得到 `3 failed, 6 passed`，三个新增测试均按预期失败。
- GREEN 实现：
  - `src/aifde/ontology/rdf.py`：fallback parser 的 prefix directive 现在强制消费终止 `.`，缺失时抛出可读 `RDFParseError`。
  - `src/aifde/ontology/shapes.py`：加载 NodeShape/property shape 时先扫描 unsupported `sh:*` 谓词并 fail closed；property constraint 缺少已实现 enforcing predicate 时抛出 `ShapeParseError`。
  - `src/aifde/tools/validation.py`：`ValidationResult` 使用 list-compatible 只读字符串列表，保留现有等值比较和 JSON 序列化行为，同时阻止嵌套 mutation。
- 维持既有行为：SHACL valid/invalid、hard gate 阻断、Gateway `VALIDATE` 能力边界、warning/message 可读性均由原有测试继续覆盖。

## 依赖与运行模式

本次实际解释器为 `C:\ProgramData\anaconda3\python.exe`，环境探测结果为：

- `rdflib=False`
- `pyshacl=False`

实现对 RDFLib/pySHACL 使用可选适配：依赖存在时优先使用 RDFLib 和真实 pySHACL；当前环境缺少两者时使用受限、确定性的本地 Turtle/SHACL 基数约束子集，并在 `warnings` 与 `message` 中明确提示需安装 `pyshacl` 才能获得完整 SHACL 语义。没有访问真实外部系统。

## 验证结果

- `C:\ProgramData\anaconda3\python.exe -m pytest tests/gates/test_shacl_validator.py -q`：`9 passed`
- `C:\ProgramData\anaconda3\python.exe -m pytest -q`：`137 passed`
- `C:\ProgramData\anaconda3\python.exe -m compileall src tests`：exit code `0`
- `git diff --check`：exit code `0`（仅 Git for Windows 的 LF/CRLF 提示，无 whitespace error）

## 实际模型

GPT-5（Codex）。
