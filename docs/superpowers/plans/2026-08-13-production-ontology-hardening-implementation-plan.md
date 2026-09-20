# 生产级 Ontology 产出能力改造 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按 P0、P1、P2 检查项把证据驱动 Builder 升级为可生成时间安全、语义强约束、可计算且可治理的生产级 Ontology 发布包。

**Architecture:** 在现有 `aifde.builder` 上增加字段级血缘和 as-of 数据产品，在编译器中生成类型化 RDF、SHACL 和业务派生状态，在独立计算契约层连接 Feature、Prediction、Decision、Action 和 Feedback。现有 GateEngine 继续是唯一状态变更入口，AI 仍只能产生候选。

**Tech Stack:** Python 3.11+, Pydantic v2, RDFLib, pySHACL, Polars, SQLite registry, pytest。

## Global Constraints

- 任何字段的值必须可追溯到 EvidenceFragment；字段级 `available_at` 是 as-of 可见性的唯一上界。
- 高影响实体只有 `confirmed` 才能进入 released prediction/decision 数据；带冲突的 `probable_match` 必须阻断发布。
- RDFS、SHACL、数据产品、特征和计算对象都必须版本化并可复现。
- AI/heuristic 只能生成候选；不得自批准事实、实体合并、发布或执行 Action。
- 每个生产函数先写失败测试，再写最小实现；每个阶段结束运行 focused tests 和回归测试。

---

### Task 1: P0 字段级时间血缘与 as-of 数据产品

**Files:**
- Modify: `src/aifde/builder/contracts.py`
- Modify: `src/aifde/builder/compiler.py`
- Modify: `tests/builder/test_compiler.py`
- Create: `tests/builder/test_production_hardening.py`

**Interfaces:**
- `FieldValueProvenance`
- `CompileResult.materialize_as_of(as_of_time: datetime) -> list[dict[str, Any]]`
- `MappingCompiler.validate` must verify field-level provenance closure and temporal safety.

- [ ] **Step 1: Write failing tests** for field-level actual-delivery availability and as-of filtering.
- [ ] **Step 2: Run `pytest tests/builder/test_production_hardening.py -q` and confirm failure because field provenance/as-of API is absent.**
- [ ] **Step 3: Implement immutable `FieldValueProvenance` and populate every canonical field.**
- [ ] **Step 4: Implement as-of materialization and temporal validation.**
- [ ] **Step 5: Run focused compiler tests and commit `feat: enforce field level temporal provenance`.**

### Task 2: P0 高影响实体发布门禁

**Files:**
- Modify: `src/aifde/builder/gates.py`
- Modify: `src/software_delivery_demo/builder_demo.py`
- Modify: `projects/supplier-delay-builder-demo/fixtures/purchase_orders.json`
- Modify: `projects/supplier-delay-builder-demo/fixtures/supplier_notes.md`
- Modify: `tests/builder/test_builder_flow.py`
- Modify: `tests/builder/test_semantic_candidates.py`

**Interfaces:**
- `BuilderGateRunner.evaluate` must treat conflict-bearing `probable_match` as a hard adversarial failure.
- Normal demo data must carry source-explicit supplier keys; ambiguous fixtures must remain blocked.

- [ ] **Step 1: Add a failing probable-match conflict gate test.**
- [ ] **Step 2: Run the focused test and confirm the current gate incorrectly passes.**
- [ ] **Step 3: Implement the hard-gate rule and expose resolution status in canonical data.**
- [ ] **Step 4: Make the clean fixture explicitly resolvable and retain a forced conflict path.**
- [ ] **Step 5: Run Builder tests and commit `fix: block ambiguous production identities`.**

### Task 3: P1 领域语义、事件状态和派生对象

**Files:**
- Modify: `src/aifde/builder/semantic.py`
- Modify: `src/aifde/builder/compiler.py`
- Modify: `src/aifde/ontology/shapes.py`
- Modify: `src/aifde/tools/validation.py`
- Modify: `src/aifde/ontology/rdf.py`
- Modify: `tests/builder/test_compiler.py`
- Modify: `tests/gates/test_shacl_validator.py`
- Create: `tests/builder/test_domain_semantics.py`

**Interfaces:**
- `OntologyCandidate` includes order-line, promise/revision, delivery event and exception classes.
- Canonical product includes `delay_state`, `delay_days`, `canonical_line_rows`, and typed temporal fields.
- `MappingCompiler.render_turtle` and `render_shapes` generate typed RDFS/SHACL.

- [ ] **Step 1: Add failing tests for `Delayed`, `Unknown`, order lines, typed dates, relation constraints and invalid states.**
- [ ] **Step 2: Run focused tests and confirm current artifact lacks these semantics.**
- [ ] **Step 3: Implement semantic projection and derived state calculation.**
- [ ] **Step 4: Extend the deterministic SHACL subset and use pySHACL when available.**
- [ ] **Step 5: Run P1 tests and commit `feat: compile production domain semantics`.**

### Task 4: P2 计算 Ontology 契约

**Files:**
- Create: `src/aifde/ontology/computation.py`
- Modify: `src/aifde/ontology/__init__.py`
- Modify: `src/aifde/domain/actions.py`
- Modify: `src/aifde/domain/feedback.py`
- Modify: `src/aifde/tools/actions.py`
- Create: `tests/ontology/test_computation_contracts.py`
- Modify: `tests/unit/test_action_broker.py`

**Interfaces:**
- `FeatureDefinition`, `FeatureSnapshot`, `LabelDefinition`, `PredictionArtifact`, `DecisionCandidate`, `GovernedActionRequest`, `ActionOutcomeLink`, `FeedbackLink`.
- `FeatureMaterializer.materialize(compile_result, feature_definition, as_of_time)`.
- `validate_computation_lineage(...)`.

- [ ] **Step 1: Add failing tests for missing release/version/as-of/lineage and future-field use.**
- [ ] **Step 2: Run focused tests and confirm the contracts are absent.**
- [ ] **Step 3: Implement immutable computation contracts and as-of feature materialization.**
- [ ] **Step 4: Link predictions, decisions, governed Actions and feedback to released artifacts.**
- [ ] **Step 5: Verify Action Broker refuses unapproved or unlinked governed actions; commit `feat: add ontology computation contracts`.**

### Task 5: 持久化发布/血缘接口与文档

**Files:**
- Create: `src/aifde/builder/persistence.py`
- Modify: `src/aifde/registry/sqlite.py`
- Create: `tests/builder/test_persistence.py`
- Modify: `projects/supplier-delay-builder-demo/README.md`
- Create: `docs/production-ontology-acceptance.md`

**Interfaces:**
- `BuilderRegistry` protocol for append-only source snapshots, field provenance and release manifests.
- `SQLiteBuilderRegistry` with immutable inserts and hash verification.

- [ ] **Step 1: Add failing persistence/restart tests.**
- [ ] **Step 2: Implement append-only SQLite persistence without changing existing registry contracts.**
- [ ] **Step 3: Persist release manifest and verify hashes after reopening the database.**
- [ ] **Step 4: Document production readiness boundaries and operational acceptance.**
- [ ] **Step 5: Run all tests, compileall, and commit `feat: persist production ontology provenance`.**

### Task 6: 全量验证与完成审计

- [ ] Run `pytest tests/builder tests/ontology tests/gates tests/unit -q`.
- [ ] Run `pytest -q`.
- [ ] Run `python -m compileall -q src tests`.
- [ ] Run deterministic demo before and after actual-event availability and inspect RDF/SHACL artifacts.
- [ ] Verify no P0/P1/P2 acceptance item remains untested.
- [ ] Only after fresh evidence, mark the active goal complete.
