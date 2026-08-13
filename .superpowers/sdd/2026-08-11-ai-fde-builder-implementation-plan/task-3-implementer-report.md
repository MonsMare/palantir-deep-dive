# Task 3 最终修复实现报告：Gate Engine 与阶段状态机

## 范围

- 只修改 `src/aifde/gates/`、`tests/gates/` 与本报告。
- 未实现后续 Tool / Action / Orchestration，也未修改计划、ledger 或 Task 4+ 文件。

## 六项修复

1. **C1-R：required soft gate 状态**
   - `PENDING` / `BLOCKED` 永远进入阻塞路径；active waiver 只豁免 current soft `FAILED`。
   - required gate 的 missing、stale、hard failure、pending/block 状态都会出现在 `blocking_gate_ids`。
   - `register_result()` 支持显式 `gate_result`，保留原有 `passed` 默认映射。

2. **C2-R：完整 definition fingerprint**
   - `GateDefinition` 使用 canonical JSON 对全部定义字段（包括允许的未来字段）计算 `definition_fingerprint`。
   - `register_definition()` 以 fingerprint 比较策略内容；同 version / validator_version 的内容变化也会使旧 GateRun stale。
   - GateRun 保存 definition fingerprint，并在 currentness 判断中再次核对。

3. **C3-R：builder 不得 approval/release**
   - builder 对 `APPROVED`、`RELEASE_CANDIDATE`、`RELEASED` 均被拒绝。
   - builder 与 transition actor 都在边界统一 `strip()` canonicalize；审计记录保存 canonical actor。

4. **I1-R：evidence snapshot hash 闭合**
   - `ValidationContext.evidence_snapshot_hash` 改为必填非空字段。
   - 同 evidence ID 更新若未提供新 hash 会抛出 `ValueError`；ID/hash 同时不变返回 0，hash 变化会 stale。
   - stage registration 保存完整 authoritative context。

5. **I2-R：stage authoritative context**
   - `register_stage_run()` 强制要求完整 `ValidationContext`，不再接受 `None`。
   - `register_result()` 只接受与注册 context 严格相等的 context，禁止同一 stage 的 GateRun 混用配置、证据或其他快照。

6. **I3-R：canonical actor identity**
   - `builder_actor` 和 transition `actor` 都要求非空并保存 stripped canonical 值。
   - padded actor 与 builder identity 被视为同一身份，不能绕过 self-approval/self-release 检查。

## 回归覆盖

- soft `PENDING` + active waiver
- soft `BLOCKED` + active waiver
- same-version definition policy content change
- future definition field change
- builder release-candidate/released transition
- same evidence ID without hash raises
- same evidence ID and same hash does not stale
- mixed validation contexts rejected
- padded actor rejected

## 验证结果

- `pytest tests/gates/test_gate_engine.py tests/gates/test_gate_invalidation.py -q`：**24 passed**
- `pytest -q`：**65 passed**
- `python -m compileall -q src tests`：**exit 0**
- `git diff --check`：**exit 0**

## 模型状态

- 用户偏好：`gpt-5.6-luna + max`。
- 模型回退：**未发生可检测的容量拒绝**；当前平台未提供模型切换接口，本次使用会话可用的最高推理强度继续执行。
