# Task 5：构建最小 React/TypeScript Workbench 报告

## 实现摘要

- 新增 `workbench/` Vite 前端，使用 React 18、TypeScript、TanStack Query、Vitest、Testing Library。
- 按 Task 4 的真实 `SnapshotResponse` 定义 `ProjectWorkspace`、`DecisionCase`、`Artifact`、`AgentProposal`、`GateReviewSnapshot`、`ReleaseCandidate`、`AuditEvent` 与 `WorkspaceSnapshot`，没有臆造后端字段。
- 实现三栏 review-first 控制面：Project Home / workspace phase、Decision Case、Artifact Review、Proposal history、Gate Review、Release Candidate 与 audit tail。
- Gate Review 只要状态不是 `passed` 或标记为 `stale`，就显示 gate ID 与阻断原因并禁用 Release Candidate 按钮；所有 required gates 通过时显示 `Release Candidate available`、`All required gates passed`，按钮只调用已认证 API client 的 candidate endpoint，不在前端伪造发布。
- Agent proposal 只展示状态、hash、evidence、risk 和 open questions；没有 agent approve/批准控件，也没有客户生产 Action 控件。
- API client 从 `VITE_SHIPYARD_API_URL`、`VITE_SHIPYARD_IDENTITY` 读取配置，所有请求带 `X-Shipyard-Identity`；Decision Case、Proposal Decision、Release Candidate mutation 只 invalidate 受影响 workspace 的 snapshot query。

## 安装

环境：

- Node.js `v24.15.0`
- npm `11.12.1`

命令：

```powershell
cd workbench
npm install
```

结果：首次安装新增 119 个 package，审计 120 个 package，`0 vulnerabilities`；最终复验为 `up to date`、`0 vulnerabilities`。依赖版本固定在 `workbench/package.json`，并生成 `workbench/package-lock.json`。

## TDD 红/绿记录

1. 先写入 `workbench/src/App.test.tsx`，包含完整 `fakeApiWithBlockedGate` 与 passed-gates fixture。
2. 初始 RED：

   ```text
   npm test -- --run
   Error: Cannot find module './App'
   Tests  no tests
   ```

   这是预期的缺失 UI 实现失败。

3. 首轮实现后，4 个 UI 测试中 3 个通过；blocked gate 测试因 `semantic.integrity` 同时出现在 Gate Review 和 Release 阻断列表而暴露了测试查询过窄的问题，改为多元素可见性断言。
4. 追加 Snapshot API failure 回归测试后再次 RED：错误响应错误地停留在 `Loading workspace snapshot`，没有进入用户可见的 alert 状态；调整错误分支顺序后 GREEN。
5. 最终命令：

   ```powershell
   npm test -- --run
   ```

   结果：`1 test file passed`，`5 tests passed`。

覆盖断言包括：

- 中文 Decision Case：`软件需求对齐与工期预测`。
- blocked Release Candidate 与 `semantic.integrity` gate。
- 无 Agent approve/批准/审批/同意控件、无 production action 控件。
- 所有 gate passed 时的 `Release Candidate available`、`All required gates passed` 与 authenticated API 状态。
- Workspace catalog 和 workspace snapshot API failure 的用户可见错误状态。

## Build

命令：

```powershell
npm run build
```

结果：TypeScript 检查与 Vite production build 均 exit `0`；确认生成 `workbench/dist/index.html` 及 CSS/JS bundle（构建输出包含 `dist/index.html 0.45 kB`）。`dist/`、`node_modules/` 和 `tsconfig.tsbuildinfo` 由 `workbench/.gitignore` 排除，未提交生成物。

## 修改文件

- `workbench/.gitignore`
- `workbench/index.html`
- `workbench/package.json`
- `workbench/package-lock.json`
- `workbench/tsconfig.json`
- `workbench/vite.config.ts`
- `workbench/src/main.tsx`
- `workbench/src/App.tsx`
- `workbench/src/api.ts`
- `workbench/src/types.ts`
- `workbench/src/styles.css`
- `workbench/src/App.test.tsx`
- 本报告：`.superpowers/sdd/2026-08-15-shipyard-workbench-phase-0/task-5-report.md`

未修改 Python 文件、Task 4 API 或 Docker。

## 自审

- 可访问性：页面使用 `main`、`aside`、`nav`、`aria-label`、`aria-labelledby`、原生 button、`aria-current`、`role="status"` 与 `role="alert"`；错误、加载和 release 状态均有用户可见文本。
- 安全边界：UI 只展示 Agent proposal，未提供 approve/批准控件；Release Candidate 按钮 blocked 时 disabled，passed 时通过 `ShipyardApiClient` 发起带身份 header 的 API 请求，不执行客户生产 Action。
- 数据一致性：Artifact 显示 `version`、content hash、evidence refs；Gate 显示 `passed/blocked/stale`、violations、warnings、artifact hashes 与 evidence；Proposal、Release Candidate 和 audit tail 显示状态/hash/追踪信息。
- 查询缓存：三类 mutation 的成功回调均只调用精确的 `workspace snapshot` query invalidation，没有全局刷新或伪造本地发布状态。
- Promise/error：查询函数交给 TanStack Query 捕获错误；按钮使用 `mutate` 而非未处理的 `mutateAsync`；API JSON 解析失败和非 2xx 均转换为 `ShipyardApiError`，并在界面显示 alert。
- 边界检查：最终 `git diff --cached --check` 无 whitespace error；最终变更没有 `.py` 文件；`npm install`、5 个测试和 build 均已重新运行并通过。

## 提交 SHA

实现提交：`df08d0b04d4db89cbe8a9b63f3fe4746d108e235`（`feat: add Shipyard Workbench review surface`）。

## 遗留疑问 / concerns

- 运行环境需要配置 `VITE_SHIPYARD_API_URL` 与 `VITE_SHIPYARD_IDENTITY`；未配置身份时 API 会按 Task 4 合同返回认证错误，UI 会显示失败状态，这是有意保留的认证边界。
- Task 4 当前没有独立的客户生产 release endpoint；本任务只调用已提供的 Release Candidate API，未新增后端、未执行生产 Action。除此之外无阻塞项。

## Fix round 1：处理 reviewer 的 I-1 / I-2 / I-3

本轮只修改 reviewer 标记的三个 Important；M-1（成功空/非 JSON body）与 M-2（API client/header/invalidation 直接单测）按要求延后，未在本轮实现。

### 根因与修复

- I-1：新增 `VITE_SHIPYARD_REQUIRED_GATES` 解析；未配置时对 `software_delivery` 使用 `semantic.integrity` 与 `release.governance` 默认 required gate 集合。`evaluateReleaseReadiness(...)` 按每个 `gate_id` 的 `(revision, created_at, snapshot 顺序)` 选择 current/latest review，校验 required gate 是否齐全、Artifact 是否非空、current review 是否 `passed` 且非 `stale`，以及每个 Gate Review 的 `artifact_hashes` 是否与当前 Artifact 集合完全相等。GatePanel 只显示 current review；Release Candidate 请求只提交 `currentArtifactIds` 与 required current `currentGateRunIds`。
- I-2：Gate Review 新增 revision、created_at、自身 content hash 和 gate run ID 展示；Release Candidate 新增 status、created_by、created_at、content hash、artifact/gate 引用、manifest artifact hashes、manifest gate run IDs 和 manifest digest。`HashValue` 现在把完整 hash 放在可访问 DOM 文本和 `aria-label` 中，不再只把完整值藏在 title。
- I-3：blocked 测试断言按钮 `toBeDisabled()` 且点击不会调用 release API；passed fixture 同时包含两个真实 required gates、非空 Artifact 和匹配 hash，并用 `vi.fn`/点击断言 authenticated release API 只在点击时调用，参数只包含当前 Artifact 与两个 current required gate runs。新增 failed、blocked、pending、stale、missing required gate、empty Artifact、hash mismatch 和 older-passed/latest-current review 测试；既有无 Agent approve/production Action 断言保持不变。

### Fix round 1 RED

先补充 fixture 和测试，再运行：

```powershell
npm test -- --run
```

结果：`13 tests | 4 failed`。失败准确暴露四个 readiness 缺口：missing required gate 没有显示阻断、空 Artifact 仍启用按钮、Artifact hash mismatch 仍启用按钮、旧 passed review 未被 current/latest review 选择逻辑替代。

### Fix round 1 GREEN

实现 readiness policy、current review 选择、证据展示和受限 release payload 后运行同一命令：

```text
Test Files  1 passed (1)
Tests       13 passed (13)
```

### Fix round 1 Build

```powershell
npm run build
```

结果：`tsc --noEmit` 与 Vite production build 均 exit `0`；重新生成 `workbench/dist/index.html`、CSS 和 JS bundle。

### Fix round 1 修改文件

- `workbench/src/App.tsx`
- `workbench/src/App.test.tsx`
- `workbench/src/styles.css`
- 本报告追加本节

未修改 Python、Task 4 API、package 依赖或 Docker；M-1/M-2 未处理。

### Fix round 1 自审

- Readiness 不再把 snapshot 中任意一条 passed gate 当作 release-ready；缺少 required gate、非 current review、failed/blocked/pending、stale、空 Artifact、hash key/value 不精确匹配都会阻断。
- Release button blocked 时原生 disabled，点击不会触发 API；passed 时通过注入的 authenticated API client 调用，payload 只使用 current Artifact IDs 与 required current Gate Review run IDs。
- Gate/Release evidence 的完整 hash 在 DOM 文本中可访问；manifest 的 artifact hash、gate run IDs 与 digest 分项可审阅。
- 最终仍无 Agent approve/批准/审批/同意控件和客户 production Action 控件；`git diff --cached --check` 通过，fix diff 没有 `.py` 文件。

### Fix round 1 提交 SHA

实现提交：`39e719df299f6c2ecb538f3744538a15dca5c5c3`（`fix: harden Shipyard Workbench release readiness`）。

### Fix round 1 concerns

- required gate 默认策略仅对 `domain_pack === "software_delivery"` 生效；其他 domain pack 需要通过 `VITE_SHIPYARD_REQUIRED_GATES` 显式配置，否则 UI 保守地保持 blocked。
- M-1/M-2 仍按 reviewer 指定延后；本轮没有扩大到成功空 body/API client 直接单测范围。
