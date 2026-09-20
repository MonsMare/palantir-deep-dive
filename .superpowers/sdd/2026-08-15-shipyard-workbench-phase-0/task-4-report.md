# Task 4 Report: Expose the Workbench application API

## 实现摘要

- 新增 `src/aifde/api/shipyard_routes.py`，提供 brief 要求的 Workspace、Decision Case、Agent Proposal、Proposal Decision、Gate Review、Release Candidate 和 Snapshot HTTP 端点。
- 所有 mutating request model 使用 `extra="forbid"`；`actor`、`authority`、`approval` 等未声明字段由 Pydantic 直接返回 422。身份只从 `X-Shipyard-Identity` header 经 `service.identity_provider.resolve({"X-Shipyard-Identity": header})` 得到，并把 canonical `Principal` 交给 Service。
- 路由层只做 HTTP/Pydantic 转换和异常映射，不访问 Registry、GateEngine、Action Broker 或 Domain Pack。写入全部委托 `ShipyardApplicationService`。
- `UnauthorizedError` → 403，缺失身份 header → 401，stale/release eligibility → 409，Service/contract validation → 422，missing record → 404。
- `create_app(..., shipyard_service=None)` 保持旧调用兼容；只有显式传入服务时才挂载 Workbench router。既有 stage/action API 保持原路由。
- 为满足列表端点且不让路由接触 Registry，Service 新增只读 `get_workspace()`、`list_workspaces()` 和 `list_decision_cases()`；`list_workspaces()` 按 workspace identity 返回最新 revision，响应只包含合同数据，不暴露内部句柄。
- 所有响应先转换为 JSON-safe Pydantic 数据；Snapshot 使用严格响应模型，包含的 Artifact、Proposal、Gate Review、Release Candidate 和 AuditEvent 均可直接 JSON 序列化。

## 红灯

先写入真实 `TestClient` 路由测试，再运行：

```text
$ pytest tests/api/test_shipyard_routes.py -q
EEEEEEEEEEEE.                                                            [100%]
1 passed, 12 errors in 2.08s
```

首个错误为预期的缺失能力：`TypeError: create_app() got an unexpected keyword argument 'shipyard_service'`；其余 Workbench 场景因此在 fixture 建 app 时失败。可选 router 未传 Service 的 404 测试先通过，证明测试入口有效。

## 绿灯

```text
$ pytest tests/api/test_shipyard_routes.py -q
................                                                         [100%]
16 passed in 3.55s
```

测试覆盖 authenticated header owner、body actor/authority/approval 422、missing/unknown identity、human/agent/system role、stale proposal 409、release conflict 409、真实 Gate/Release JSON 响应、Snapshot 序列化、missing record 404 和 optional router mount。

变更文件逐个编译检查：

```text
$ python -m py_compile src\aifde\api\shipyard_routes.py src\aifde\api\app.py src\aifde\api\__init__.py src\aifde\shipyard\service.py tests\api\test_shipyard_routes.py
# exit 0
```

## 回归

brief 指定回归命令：

```text
$ pytest tests/api tests/shipyard/test_service.py -q
........................................................                 [100%]
56 passed in 5.37s
```

API 单独回归（包含旧 stage/action routes）：

```text
$ pytest tests/api -q
.......................................                                  [100%]
39 passed in 4.45s
```

全仓回归：

```text
$ pytest -q --tb=no
403 passed, 14 failed, 13 errors in 32.30s
```

全仓的 14 failures / 13 errors 与 Task 3 基线相同，集中在既有 Builder、SHACL、Ontology IR 和 Runtime 路径；本任务没有修改这些路径。全仓 `compileall` 另被既有 `src/aifde/ontology/shapes.py:97` 的 `SyntaxError: f-string: expecting '}'` 阻断；本任务变更文件的逐文件 `py_compile` 已通过。

## 自审

- 新路由文件不持有或访问 Registry、GateEngine、Action Broker、Domain Pack；只依赖 `ShipyardApplicationService` 和其 `identity_provider`。
- 认证来源固定为 header；请求 JSON 没有 actor/authority/approval 逃逸路径，Service 的 kind/identity 校验仍是最终授权边界。
- human 只能执行 Workspace/Decision Case/Proposal Decision/Release Candidate；agent 只能提交 Proposal；system 只能记录 Gate Review；这些边界由 Service 判断，路由没有复制业务策略。
- stale proposal 和 release eligibility 的 Service 异常分别保持 409；missing records 不会转成 500。
- 旧 API 的 39 个 API 测试全部通过；不传 `shipyard_service` 时 `/workspaces` 不存在，传入时 Workbench router 才出现。
- staged diff `git diff --cached --check` 无 whitespace error；变更后最终 `git status --short` 在实现提交前为空。

## 提交 SHA

- 实现提交：`8ab7b397910b1a5004c1551412fd3a73e95d10bf` (`feat: expose Shipyard Workbench API`)

## 遗留疑问 / concerns

- 全仓既有 Builder/SHACL/Ontology/Runtime 失败和 `ontology/shapes.py` 语法错误未在 Task 4 范围内处理；它们不影响 brief 指定的 API + Shipyard 回归。
- Workbench API 当前使用 Task 3 显式注入的 `FakeIdentityProvider`/实现提供认证目录；生产部署仍需替换为真实 IdentityProvider，这是现有 Service 合同的配置责任，不在本任务新增生产认证实现。
