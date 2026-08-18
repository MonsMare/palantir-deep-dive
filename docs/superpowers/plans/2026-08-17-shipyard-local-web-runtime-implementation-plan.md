# Shipyard Local Web Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 为当前 AI-FDE Shipyard 增加一个可恢复、默认本地安全、浏览器优先的 Local Web Runtime，使 FDE 可以通过 shipyard init 和 shipyard web 进入 Workbench，并复用现有 Application Service 完成项目审阅。

**Architecture:** 在现有 Shipyard Application Service、SQLite Registry、FastAPI Shipyard routes 和 React Workbench 之上增加一个明确的 Local Runtime composition root。Runtime 负责读取严格配置、创建本地目录、绑定单一 owner 身份、装配 SQLite/Artifact Store/API/静态前端，并由 CLI 管理 init 与 web 生命周期。API 路由只负责 HTTP 转换；所有领域写入仍由 ShipyardApplicationService 授权。

**Tech Stack:** Python 3.11、Pydantic 2、PyYAML、SQLite、FastAPI、Uvicorn、React 18、TypeScript、Vite、Vitest、pytest、FastAPI TestClient。

## Global Constraints

- AI-FDE Shipyard 是构建、评测、门禁和发布候选控制面，不实现客户生产环境中的持续预测、决策或业务动作。
- Local Profile 默认只绑定 127.0.0.1；第一版本地 Web 不提供局域网开放开关、客户生产 Action、任意出网和任意宿主机命令。
- Application Service 是唯一状态写入边界；浏览器、Agent、Worker、插件和 CLI 不得直接写 Shipyard Registry。
- Agent 只能提交 Proposal 和验证结果，不能批准自身 Proposal、改变 Gate 状态或创建 Release Candidate。
- L0 只实现 Local Web Composition Root、配置、目录、单一 owner 身份、Shipyard-only API、静态 Workbench 托管和 init/web CLI。
- L0 不实现 L1 的 Agent Worker、任务队列、Sandbox 执行器和模型网关；不实现 L3 的 PostgreSQL、MinIO、Redis/NATS、OIDC、多用户 ACL 和 Docker Compose。
- Local Profile 的持久化使用 SQLite 和本地内容目录；已有 ShipyardStore、SQLiteRegistry、ShipyardApplicationService 和现有 Workbench API 合约必须优先复用。
- 不修改或覆盖工作区中已有的用户变更；实现时只编辑任务列出的文件，并在每个任务结束前检查暂存文件清单。
- Python 依赖继续支持 >=3.11；FastAPI 和 Uvicorn 作为 web 可选依赖加入安装入口，不把 API 依赖隐式复制到前端。
- 所有配置、路径、身份、静态资源缺失、端口冲突和数据库错误都必须给出确定错误；无法验证时 fail closed。
- 每个任务先写失败测试，再写最小实现，再运行该任务的专门测试，最后提交独立 commit。

---

## 0. 实施边界与代码地图

本计划只实施设计文档中的 L0。L0 完成后，用户可以在当前仓库中执行：

~~~text
python -m pip install -e ".[web]"
cd workbench
npm ci
npm run build
cd ..
shipyard init . --owner alice
shipyard web --project .
~~~

浏览器访问本地 Workbench，静态资源和 API 由同一个 Uvicorn 进程提供。若使用现有软件交付 seed，可以在启动 Web 前向 .shipyard/shipyard.db 初始化演示数据；seed 脚本仍然只负责数据初始化，不负责启动 Web。

### 0.1 将创建的文件

| 文件 | 单一责任 |
| --- | --- |
| src/aifde/shipyard/config.py | 严格解析 Local Profile 配置、生成 ShipyardPaths、创建默认配置和检查路径边界 |
| src/aifde/shipyard/identity.py | 增加 LocalOwnerIdentityProvider，将本地单一 owner 映射为可信 Principal |
| src/aifde/api/runtime_routes.py | 提供 healthz、readyz 和 runtime-config 等本地运行时端点 |
| src/aifde/api/static.py | 解析 Workbench dist 目录并以 SPA 静态资源挂载 |
| src/aifde/shipyard/runtime.py | 创建和关闭 LocalShipyardRuntime，装配 Registry、身份、Application Service 和 FastAPI |
| src/aifde/shipyard/cli.py | 实现 shipyard init、shipyard web 和可测试的 CLI 入口 |
| workbench/src/runtime.ts | 加载同源 runtime-config 并构造前端启动配置 |
| tests/shipyard/test_runtime_config.py | 配置、默认目录、覆盖和路径安全测试 |
| tests/shipyard/test_local_identity.py | 本地 owner 身份和角色固定测试 |
| tests/shipyard/test_local_runtime.py | Runtime composition root、持久化和关闭行为测试 |
| tests/shipyard/test_cli.py | init/web CLI 行为测试 |
| tests/api/test_runtime_routes.py | runtime API、静态页面和 readiness 测试 |
| tests/e2e/test_shipyard_local_web.py | 本地 Web 的 HTTP 垂直切片测试 |
| workbench/src/runtime.test.ts | 前端 runtime-config 加载和错误测试 |

### 0.2 将修改的文件

| 文件 | 修改责任 |
| --- | --- |
| src/aifde/api/app.py | 保留既有 create_app，并新增只挂载 Shipyard Workbench 的 create_shipyard_app |
| src/aifde/api/__init__.py | 导出新的应用工厂和运行时路由接口 |
| src/aifde/shipyard/__init__.py | 导出 Local Profile 的公开配置、Runtime 和身份类型 |
| pyproject.toml | 添加 web optional dependency 和 shipyard console script |
| .gitignore | 忽略项目级 .shipyard/ 和前端 workbench/dist/ 生成物 |
| workbench/src/api.ts | 将 API client 改为可注入 base URL/identity，移除模块级固定配置依赖 |
| workbench/src/main.tsx | 在渲染 App 前加载 runtime-config，并在启动失败时显示明确错误 |
| README.md | 增加 Local Web 安装、初始化、启动和 seed 说明 |

### 0.3 明确不修改的关键文件

L0 不修改以下核心领域文件：

- src/aifde/registry/sqlite.py；
- src/aifde/shipyard/service.py；
- src/aifde/shipyard/contracts.py；
- scripts/shipyard_seed.py；
- projects/supplier-delay-builder-demo/README.md；
- projects/supplier-delay-builder-demo/fixtures/purchase_orders.json；
- 当前工作区已经被用户修改的其他文件。

如果实现发现这些文件必须改动，先停止当前任务并重新评估边界；不能为了方便在 SQLite 或 Application Service 中插入 Web 特定逻辑。

---

## Task 1: 建立 Local Profile 配置与项目目录边界

**Files:**

- Create: src/aifde/shipyard/config.py
- Create: tests/shipyard/test_runtime_config.py
- Modify: src/aifde/shipyard/__init__.py
- Modify: .gitignore

**Interfaces:**

- ShipyardPaths.from_project_root(project_root: Path) -> ShipyardPaths
- ShipyardPaths.ensure_directories() -> None
- LocalRuntimeConfig.load(project_root: Path, config_path: Path | None = None) -> LocalRuntimeConfig
- LocalRuntimeConfig.resolve_frontend_dir() -> Path
- write_default_config(project_root: Path, *, owner: str, force: bool = False) -> Path
- LocalRuntimeConfig 必须暴露 profile、owner、server、required_gate_ids、paths 和 sandbox 属性。

### Step 1: 写配置和路径的失败测试

- [ ] 在 tests/shipyard/test_runtime_config.py 中写出以下测试：

~~~python
from pathlib import Path

import pytest

from aifde.shipyard.config import (
    LocalRuntimeConfig,
    ShipyardPaths,
    write_default_config,
)


def test_default_config_creates_local_profile_and_project_state(tmp_path: Path) -> None:
    config_path = write_default_config(tmp_path, owner="alice")

    config = LocalRuntimeConfig.load(tmp_path, config_path)

    assert config.profile == "local"
    assert config.owner == "alice"
    assert config.server.host == "127.0.0.1"
    assert config.server.port == 3080
    assert config.required_gate_ids == (
        "semantic.integrity",
        "release.governance",
    )
    assert config.paths.database_path == (tmp_path / ".shipyard/shipyard.db").resolve()
    assert config.resolve_frontend_dir() == (tmp_path / "workbench/dist").resolve()


def test_paths_are_created_without_deleting_existing_state(tmp_path: Path) -> None:
    paths = ShipyardPaths.from_project_root(tmp_path)
    paths.artifact_path.mkdir(parents=True)
    marker = paths.artifact_path / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    paths.ensure_directories()

    assert marker.read_text(encoding="utf-8") == "keep"
    assert paths.database_path.parent.is_dir()
    assert paths.evidence_path.is_dir()
    assert paths.runs_path.is_dir()
    assert paths.logs_path.is_dir()
    assert paths.releases_path.is_dir()
    assert paths.plugins_path.is_dir()


def test_config_rejects_non_loopback_host(tmp_path: Path) -> None:
    config_path = write_default_config(tmp_path, owner="alice")
    text = config_path.read_text(encoding="utf-8")
    config_path.write_text(
        text.replace("host: 127.0.0.1", "host: 0.0.0.0"),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="127.0.0.1"):
        LocalRuntimeConfig.load(tmp_path, config_path)


def test_config_rejects_frontend_path_escape(tmp_path: Path) -> None:
    config_path = write_default_config(tmp_path, owner="alice")
    text = config_path.read_text(encoding="utf-8")
    config_path.write_text(
        text.replace("frontend_dir: workbench/dist", "frontend_dir: ../outside"),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="inside project_root"):
        LocalRuntimeConfig.load(tmp_path, config_path)


def test_default_config_refuses_overwrite_without_force(tmp_path: Path) -> None:
    write_default_config(tmp_path, owner="alice")

    with pytest.raises(FileExistsError):
        write_default_config(tmp_path, owner="bob")
~~~

### Step 2: 运行失败测试

- [ ] 运行：

~~~text
pytest tests/shipyard/test_runtime_config.py -q
~~~

预期：测试在新模块不存在或接口未实现时失败；失败原因应指向 aifde.shipyard.config 或缺失的具体方法，而不是 pytest 配置错误。

### Step 3: 实现严格配置和目录类型

- [ ] 在 src/aifde/shipyard/config.py 中定义以下结构：

~~~python
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
import yaml


def _is_within(candidate: Path, root: Path) -> bool:
    return candidate == root or root in candidate.parents


@dataclass(frozen=True, slots=True)
class ShipyardPaths:
    project_root: Path
    state_root: Path
    database_path: Path
    artifact_path: Path
    evidence_path: Path
    workspaces_path: Path
    runs_path: Path
    logs_path: Path
    releases_path: Path
    plugins_path: Path
    cache_path: Path
    secrets_path: Path

    @classmethod
    def from_project_root(cls, project_root: Path) -> "ShipyardPaths":
        root = project_root.expanduser().resolve()
        state = root / ".shipyard"
        return cls(
            project_root=root,
            state_root=state,
            database_path=state / "shipyard.db",
            artifact_path=state / "artifacts",
            evidence_path=state / "evidence",
            workspaces_path=state / "workspaces",
            runs_path=state / "runs",
            logs_path=state / "logs",
            releases_path=state / "releases",
            plugins_path=state / "plugins",
            cache_path=state / "cache",
            secrets_path=state / "secrets",
        )

    def ensure_directories(self) -> None:
        for path in (
            self.state_root,
            self.artifact_path,
            self.evidence_path,
            self.workspaces_path,
            self.runs_path,
            self.logs_path,
            self.releases_path,
            self.plugins_path,
            self.cache_path,
            self.secrets_path,
        ):
            path.mkdir(parents=True, exist_ok=True)


class LocalServerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    host: Literal["127.0.0.1"] = "127.0.0.1"
    port: int = Field(default=3080, ge=1024, le=65535)
    open_browser: bool = False


class LocalSandboxConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    filesystem: Literal["workspace_only"] = "workspace_only"
    network: Literal["deny"] = "deny"
    production_actions: Literal["deny"] = "deny"


class LocalRuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(default=1, ge=1)
    profile: Literal["local"] = "local"
    project_root: Path
    owner: str
    frontend_dir: str = "workbench/dist"
    required_gate_ids: tuple[str, ...] = (
        "semantic.integrity",
        "release.governance",
    )
    server: LocalServerConfig = Field(default_factory=LocalServerConfig)
    sandbox: LocalSandboxConfig = Field(default_factory=LocalSandboxConfig)

    @property
    def paths(self) -> ShipyardPaths:
        return ShipyardPaths.from_project_root(self.project_root)

    def resolve_frontend_dir(self) -> Path:
        candidate = Path(self.frontend_dir)
        if not candidate.is_absolute():
            candidate = self.project_root / candidate
        resolved = candidate.expanduser().resolve()
        if not _is_within(resolved, self.project_root):
            raise ValueError("frontend_dir must remain inside project_root")
        return resolved

    @classmethod
    def load(
        cls,
        project_root: Path,
        config_path: Path | None = None,
    ) -> "LocalRuntimeConfig":
        root = project_root.expanduser().resolve()
        path = config_path or (root / ".shipyard/config.yaml")
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("local runtime config must be a mapping")
        values = dict(raw)
        values["project_root"] = root
        return cls.model_validate(values)


def write_default_config(
    project_root: Path,
    *,
    owner: str,
    force: bool = False,
) -> Path:
    root = project_root.expanduser().resolve()
    path = root / ".shipyard/config.yaml"
    if path.exists() and not force:
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        yaml.safe_dump(
            {
                "schema_version": 1,
                "profile": "local",
                "owner": owner,
                "frontend_dir": "workbench/dist",
                "required_gate_ids": [
                    "semantic.integrity",
                    "release.governance",
                ],
                "server": {
                    "host": "127.0.0.1",
                    "port": 3080,
                    "open_browser": False,
                },
                "sandbox": {
                    "filesystem": "workspace_only",
                    "network": "deny",
                    "production_actions": "deny",
                },
            },
            stream,
            sort_keys=False,
            allow_unicode=True,
        )
    return path
~~~

- [ ] 使用 yaml.safe_load 读取 .shipyard/config.yaml；当文件内容不是 mapping、schema_version 不是 1、存在未知字段、host 不是 127.0.0.1、frontend_dir 越出 project_root 或 owner 为空时抛出 ValueError。
- [ ] load 必须把 project_root 解析为绝对路径，并把相对 frontend_dir 相对于 project_root 解析。
- [ ] write_default_config 只创建目录和配置文件，不创建 SQLite 数据库，不清空已有 Artifact、Evidence、Run 或 Release 文件。
- [ ] 默认 YAML 必须包含以下有效值：

~~~yaml
schema_version: 1
profile: local
owner: alice
frontend_dir: workbench/dist
required_gate_ids:
  - semantic.integrity
  - release.governance
server:
  host: 127.0.0.1
  port: 3080
  open_browser: false
sandbox:
  filesystem: workspace_only
  network: deny
  production_actions: deny
~~~

- [ ] 在 .gitignore 添加：

~~~text
.shipyard/
workbench/dist/
~~~

- [ ] 从 src/aifde/shipyard/__init__.py 导出 LocalRuntimeConfig、ShipyardPaths 和 write_default_config。

### Step 4: 运行配置测试

- [ ] 运行：

~~~text
pytest tests/shipyard/test_runtime_config.py -q
~~~

预期：所有配置、目录创建、覆盖拒绝和路径边界测试通过。

### Step 5: 检查并提交 Task 1

- [ ] 运行：

~~~text
git diff --check
git diff --name-only
~~~

- [ ] 确认暂存前的修改只包含 Task 1 文件，不包含当前工作区已有的用户修改。
- [ ] 提交：

~~~text
git add src/aifde/shipyard/config.py src/aifde/shipyard/__init__.py tests/shipyard/test_runtime_config.py .gitignore
git commit -m "feat: add Shipyard local runtime configuration"
~~~

---

## Task 2: 增加本地单一 Owner 身份提供器

**Files:**

- Modify: src/aifde/shipyard/identity.py
- Modify: src/aifde/shipyard/__init__.py
- Create: tests/shipyard/test_local_identity.py

**Interfaces:**

- LocalOwnerIdentityProvider(owner: str, roles: Iterable[str] = ("workspace-owner", "release-owner"))
- LocalOwnerIdentityProvider.principal -> Principal
- LocalOwnerIdentityProvider.resolve(request_context: Mapping[str, str]) -> Principal
- LocalOwnerIdentityProvider.verify(principal: Principal) -> Principal

Local Profile 只有一个人类 owner。它不是把任意请求头变成可信身份，而是只接受配置中的精确 subject；请求头仍然由既有 identity_dependency 解析，Application Service 仍然执行 verify。

### Step 1: 写失败测试

- [ ] 在 tests/shipyard/test_local_identity.py 中写：

~~~python
from collections.abc import Mapping

import pytest

from aifde.shipyard.identity import (
    LocalOwnerIdentityProvider,
    Principal,
    UnauthorizedError,
)


def test_local_owner_provider_resolves_only_configured_owner() -> None:
    provider = LocalOwnerIdentityProvider("alice")

    assert provider.resolve({"X-Shipyard-Identity": "alice"}) == provider.principal
    assert provider.principal == Principal(
        subject="alice",
        kind="human",
        roles=frozenset({"workspace-owner", "release-owner"}),
    )


@pytest.mark.parametrize(
    "context",
    [{}, {"X-Shipyard-Identity": "bob"}, {"X-Shipyard-Identity": ""}],
)
def test_local_owner_provider_rejects_missing_or_other_subject(
    context: Mapping[str, str],
) -> None:
    provider = LocalOwnerIdentityProvider("alice")

    with pytest.raises(UnauthorizedError):
        provider.resolve(context)


def test_local_owner_provider_rejects_claimed_roles_or_kind() -> None:
    provider = LocalOwnerIdentityProvider("alice")

    with pytest.raises(UnauthorizedError):
        provider.verify(
            Principal(
                subject="alice",
                kind="agent",
                roles=frozenset({"workspace-owner"}),
            )
        )
~~~

### Step 2: 运行失败测试

- [ ] 运行：

~~~text
pytest tests/shipyard/test_local_identity.py -q
~~~

预期：新类型不存在或尚未导出时失败。

### Step 3: 实现本地 provider

- [ ] 在 identity.py 中新增 LocalOwnerIdentityProvider，不要修改 Principal、IdentityProvider 或 FakeIdentityProvider 的既有语义。
- [ ] 构造函数把 owner 规范化为非空字符串，并把 roles 固化为 frozenset。
- [ ] principal 返回：

~~~python
Principal(
    subject=self._owner,
    kind="human",
    roles=self._roles,
)
~~~

- [ ] resolve 按既有 provider 兼容的三个键顺序读取 subject、X-Shipyard-Identity、x-shipyard-identity；缺失、空白或非 owner 都抛出 UnauthorizedError。
- [ ] verify 只接受与 provider.principal 完全相等的 Principal；subject 相同但 kind 或 roles 不同也抛出 UnauthorizedError。
- [ ] 将 LocalOwnerIdentityProvider 加入 __all__，并从 shipyard package 导出。

### Step 4: 运行身份测试

- [ ] 运行：

~~~text
pytest tests/shipyard/test_local_identity.py tests/shipyard/test_service.py -q
~~~

预期：本地身份测试和既有 Application Service 授权测试全部通过。

### Step 5: 提交 Task 2

- [ ] 检查：

~~~text
git diff --check
git diff --name-only
~~~

- [ ] 提交：

~~~text
git add src/aifde/shipyard/identity.py src/aifde/shipyard/__init__.py tests/shipyard/test_local_identity.py
git commit -m "feat: add local owner identity provider"
~~~

---

## Task 3: 创建 Shipyard-only API、运行时端点和静态 Workbench 挂载

**Files:**

- Create: src/aifde/api/runtime_routes.py
- Create: src/aifde/api/static.py
- Modify: src/aifde/api/app.py
- Modify: src/aifde/api/__init__.py
- Create: tests/api/test_runtime_routes.py

**Interfaces:**

- RuntimeConfigResponse
- build_runtime_router(config: LocalRuntimeConfig, readiness: Callable[[], ReadinessReport]) -> APIRouter
- resolve_workbench_dist(project_root: Path, configured_dir: Path | None = None) -> Path
- mount_workbench(app: FastAPI, directory: Path) -> None
- create_shipyard_app(*, shipyard_service: ShipyardApplicationService, runtime_config: LocalRuntimeConfig, frontend_dir: Path, readiness: Callable[[], ReadinessReport]) -> FastAPI

既有 create_app 必须保持原始参数和 legacy routes 行为；新的 Local Runtime 使用 create_shipyard_app，只挂载 Workbench API、运行时端点和静态前端，不把 legacy stage/action API 混入本地 Shipyard 控制面。

### Step 1: 写失败的 HTTP contract tests

- [ ] 在 tests/api/test_runtime_routes.py 中写：

~~~python
from pathlib import Path

from fastapi.testclient import TestClient

from aifde.api.app import create_shipyard_app
from aifde.deployment.health import HealthCheck, ReadinessReport
from aifde.shipyard.config import LocalRuntimeConfig


def ready_report() -> ReadinessReport:
    return ReadinessReport(
        ready=True,
        checks={
            "registry": HealthCheck(
                component="registry",
                status="ready",
                detail="probe passed",
            )
        },
    )


def test_runtime_routes_expose_health_readiness_and_local_identity(
    tmp_path: Path,
    shipyard_service,
) -> None:
    frontend = tmp_path / "dist"
    frontend.mkdir()
    (frontend / "index.html").write_text(
        "<html><body>Shipyard Workbench</body></html>",
        encoding="utf-8",
    )
    config = LocalRuntimeConfig(
        project_root=tmp_path,
        owner="alice",
    )
    app = create_shipyard_app(
        shipyard_service=shipyard_service,
        runtime_config=config,
        frontend_dir=frontend,
        readiness=ready_report,
    )

    client = TestClient(app)

    assert client.get("/healthz").json()["status"] == "ok"
    assert client.get("/readyz").status_code == 200
    assert client.get("/runtime-config").json() == {
        "profile": "local",
        "api_base_url": "",
        "identity": "alice",
    }
    assert client.get("/").status_code == 200
    assert "Shipyard Workbench" in client.get("/").text
~~~

- [ ] 为测试提供最小的 shipyard_service fixture：使用 SQLiteRegistry(tmp_path / "shipyard.db")、LocalOwnerIdentityProvider("alice") 和 ShipyardApplicationService，required gates 使用 {"semantic.integrity", "release.governance"}。fixture 在 yield 后关闭 Registry。

### Step 2: 运行失败测试

- [ ] 运行：

~~~text
pytest tests/api/test_runtime_routes.py -q
~~~

预期：新工厂、runtime routes 或静态挂载接口不存在时失败。

### Step 3: 实现运行时路由

- [ ] 在 runtime_routes.py 中定义严格响应模型：

~~~python
class RuntimeConfigResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    profile: Literal["local"]
    api_base_url: str
    identity: str
~~~

- [ ] build_runtime_router 注册：

  - GET /healthz：返回 {"status": "ok", "profile": config.profile}，不需要身份头；
  - GET /readyz：返回 ReadinessReport；当 report.ready 为 false 时返回 HTTP 503，并把完整 report 放在 detail；
  - GET /runtime-config：返回 profile、空字符串 api_base_url 和 config.owner；该 endpoint 不返回任何 secret、文件路径或模型 key。

- [ ] readyz 的失败响应必须可被 JSON 解析，字段至少包含 ready=false 和每个 component 的 status/detail。

### Step 4: 实现静态资源解析和挂载

- [ ] 在 static.py 中实现：

~~~python
class FrontendNotBuiltError(RuntimeError):
    pass


def resolve_workbench_dist(
    project_root: Path,
    configured_dir: Path | None = None,
) -> Path:
    root = project_root.expanduser().resolve()
    directory = configured_dir or (root / "workbench/dist")
    resolved = directory.expanduser().resolve()
    if not _is_within(resolved, root):
        raise ValueError("frontend directory must remain inside project_root")
    if not resolved.is_dir() or not (resolved / "index.html").is_file():
        raise FrontendNotBuiltError(
            "Workbench assets are missing; run npm run build before shipyard web"
        )
    return resolved


def mount_workbench(app: FastAPI, directory: Path) -> None:
    from fastapi.staticfiles import StaticFiles

    app.mount(
        "/",
        StaticFiles(directory=directory, html=True),
        name="workbench",
    )
~~~

- [ ] resolve_workbench_dist 必须：

  1. 将 project_root 和 configured_dir 解析为绝对路径；
  2. 确认 configured_dir 在 project_root 内；
  3. 确认目录存在且包含 index.html；
  4. 不满足条件时抛出 FrontendNotBuiltError，错误消息明确包含 npm run build；
  5. 不接受任意文件路径作为目录，不进行自动创建。

- [ ] mount_workbench 使用 FastAPI StaticFiles(directory=directory, html=True) 挂载到 /；API routes 和 runtime routes 必须先加入，以便 /workspaces、/healthz 和 /runtime-config 不被静态路由截获。

### Step 5: 实现只挂载 Shipyard 的应用工厂

- [ ] 在 app.py 中保留现有 create_app 原样语义，新增：

~~~python
def create_shipyard_app(
    *,
    shipyard_service: ShipyardApplicationService,
    runtime_config: LocalRuntimeConfig,
    frontend_dir: Path,
    readiness: Callable[[], ReadinessReport],
) -> Any:
    if FastAPI is None:
        raise RuntimeError("FastAPI is required for the Shipyard Web Runtime")
    app = FastAPI(title="AI-FDE Shipyard Workbench")
    app.include_router(build_runtime_router(runtime_config, readiness))
    app.include_router(build_shipyard_router(shipyard_service))
    mount_workbench(app, frontend_dir)
    return app
~~~

- [ ] 工厂构造 FastAPI 实例，设置 title 为 AI-FDE Shipyard Workbench，挂载顺序固定为：

  1. build_runtime_router(runtime_config, readiness)；
  2. build_shipyard_router(shipyard_service)；
  3. mount_workbench(app, frontend_dir)。

- [ ] 不在工厂中创建新的 Registry、IdentityProvider 或 Application Service；它们必须由 Runtime composition root 注入。
- [ ] 从 api/__init__.py 导出 create_shipyard_app、RuntimeConfigResponse、build_runtime_router 和 resolve_workbench_dist。

### Step 6: 运行 API 和回归测试

- [ ] 运行：

~~~text
pytest tests/api/test_runtime_routes.py tests/api/test_shipyard_routes.py -q
~~~

预期：新 runtime endpoints 和原有 Shipyard API 测试全部通过，且既有 create_app legacy route 测试不变。

### Step 7: 提交 Task 3

- [ ] 检查：

~~~text
git diff --check
git diff --name-only
~~~

- [ ] 提交：

~~~text
git add src/aifde/api/app.py src/aifde/api/__init__.py src/aifde/api/runtime_routes.py src/aifde/api/static.py tests/api/test_runtime_routes.py
git commit -m "feat: add Shipyard runtime API and static Workbench serving"
~~~

---

## Task 4: 实现 LocalShipyardRuntime composition root

**Files:**

- Create: src/aifde/shipyard/runtime.py
- Modify: src/aifde/shipyard/__init__.py
- Create: tests/shipyard/test_local_runtime.py

**Interfaces:**

- LocalShipyardRuntime
- build_local_runtime(config: LocalRuntimeConfig) -> LocalShipyardRuntime
- LocalShipyardRuntime.close() -> None
- LocalShipyardRuntime.url -> str
- LocalShipyardRuntime.readiness() -> ReadinessReport

### Step 1: 写 Runtime 装配失败测试

- [ ] 在 tests/shipyard/test_local_runtime.py 中写：

~~~python
from pathlib import Path

from fastapi.testclient import TestClient

from aifde.shipyard.config import LocalRuntimeConfig, write_default_config
from aifde.shipyard.runtime import build_local_runtime


def test_local_runtime_assembles_authenticated_shipyard_app(tmp_path: Path) -> None:
    frontend = tmp_path / "workbench/dist"
    frontend.mkdir(parents=True)
    (frontend / "index.html").write_text("workbench", encoding="utf-8")
    write_default_config(tmp_path, owner="alice")
    config = LocalRuntimeConfig.load(tmp_path)

    runtime = build_local_runtime(config)
    try:
        client = TestClient(runtime.app)
        response = client.post(
            "/workspaces",
            headers={"X-Shipyard-Identity": "alice"},
            json={
                "workspace_id": "ws-local",
                "project_id": "project-local",
                "name": "Local Workbench",
                "domain_pack": "software_delivery",
            },
        )

        assert response.status_code == 201
        assert response.json()["owner"] == "alice"
        assert runtime.url == "http://127.0.0.1:3080"
        assert runtime.readiness().ready is True
    finally:
        runtime.close()


def test_local_runtime_reopens_sqlite_state(tmp_path: Path) -> None:
    frontend = tmp_path / "workbench/dist"
    frontend.mkdir(parents=True)
    (frontend / "index.html").write_text("workbench", encoding="utf-8")
    config_path = write_default_config(tmp_path, owner="alice")
    config = LocalRuntimeConfig.load(tmp_path, config_path)

    first = build_local_runtime(config)
    first.service.create_workspace(
        {
            "workspace_id": "ws-reopen",
            "project_id": "project-reopen",
            "name": "Reopen",
            "domain_pack": "software_delivery",
        },
        first.identity.principal,
    )
    first.close()

    second = build_local_runtime(config)
    try:
        workspaces = second.service.list_workspaces(second.identity.principal)
        assert [workspace.workspace_id for workspace in workspaces] == ["ws-reopen"]
    finally:
        second.close()
~~~

### Step 2: 运行失败测试

- [ ] 运行：

~~~text
pytest tests/shipyard/test_local_runtime.py -q
~~~

预期：runtime 模块不存在或尚未完成装配时失败。

### Step 3: 实现 Runtime 数据结构

- [ ] 在 runtime.py 中定义：

~~~python
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI

from aifde.api.app import create_shipyard_app
from aifde.deployment.health import HealthCheck, ReadinessReport
from aifde.registry.sqlite import SQLiteRegistry
from aifde.shipyard.config import LocalRuntimeConfig, ShipyardPaths
from aifde.shipyard.identity import LocalOwnerIdentityProvider
from aifde.shipyard.service import ShipyardApplicationService


class LocalShipyardRuntime:
    def __init__(
        self,
        *,
        config: LocalRuntimeConfig,
        paths: ShipyardPaths,
        registry: SQLiteRegistry,
        identity: LocalOwnerIdentityProvider,
        service: ShipyardApplicationService,
        frontend_dir: Path,
    ) -> None:
        self.config = config
        self.paths = paths
        self.registry = registry
        self.identity = identity
        self.service = service
        self.frontend_dir = frontend_dir
        self.closed = False
        self.app = create_shipyard_app(
            shipyard_service=service,
            runtime_config=config,
            frontend_dir=frontend_dir,
            readiness=self.readiness,
        )

    @property
    def url(self) -> str:
        return "http://" + self.config.server.host + ":" + str(self.config.server.port)

    def readiness(self) -> ReadinessReport:
        checks = {
            "registry": HealthCheck(
                component="registry",
                status=(
                    "ready"
                    if self.paths.database_path.exists() and not self.closed
                    else "not_ready"
                ),
                detail=(
                    "SQLite registry is open"
                    if self.paths.database_path.exists() and not self.closed
                    else "SQLite registry is closed or missing"
                ),
            ),
            "artifact_store": HealthCheck(
                component="artifact_store",
                status=(
                    "ready"
                    if self.paths.artifact_path.is_dir()
                    else "not_ready"
                ),
                detail=(
                    "Artifact directory is available"
                    if self.paths.artifact_path.is_dir()
                    else "Artifact directory is missing"
                ),
            ),
            "frontend": HealthCheck(
                component="frontend",
                status=(
                    "ready"
                    if self.frontend_dir.is_dir()
                    and (self.frontend_dir / "index.html").is_file()
                    else "not_ready"
                ),
                detail=(
                    "Workbench assets are available"
                    if self.frontend_dir.is_dir()
                    and (self.frontend_dir / "index.html").is_file()
                    else "Workbench index.html is missing"
                ),
            ),
        }
        return ReadinessReport(
            ready=all(check.status == "ready" for check in checks.values()),
            checks=checks,
        )

    def close(self) -> None:
        if self.closed:
            return
        self.registry.close()
        self.closed = True


def build_local_runtime(config: LocalRuntimeConfig) -> LocalShipyardRuntime:
    paths = config.paths
    paths.ensure_directories()
    frontend_dir = resolve_workbench_dist(
        config.project_root,
        config.resolve_frontend_dir(),
    )
    registry: SQLiteRegistry | None = None
    try:
        registry = SQLiteRegistry(paths.database_path)
        identity = LocalOwnerIdentityProvider(config.owner)
        service = ShipyardApplicationService(
            registry,
            identity_provider=identity,
            required_gate_ids=frozenset(config.required_gate_ids),
        )
        return LocalShipyardRuntime(
            config=config,
            paths=paths,
            registry=registry,
            identity=identity,
            service=service,
            frontend_dir=frontend_dir,
        )
    except BaseException:
        if registry is not None:
            registry.close()
        raise
~~~

- [ ] build_local_runtime 的装配顺序固定为：

  1. config.paths.ensure_directories()；
  2. frontend_dir = config.resolve_frontend_dir()；
  3. resolve_workbench_dist(config.project_root, frontend_dir)；
  4. registry = SQLiteRegistry(config.paths.database_path)；
  5. identity = LocalOwnerIdentityProvider(config.owner)；
  6. service = ShipyardApplicationService(registry, identity_provider=identity, required_gate_ids=frozenset(config.required_gate_ids))；
  7. 创建 Runtime 对象；
  8. 使用 Runtime 的 readiness 回调创建 create_shipyard_app；
  9. 将 app 放入 Runtime 并返回。

- [ ] build_local_runtime 在前端目录校验失败时必须在打开 SQLite 前抛出 FrontendNotBuiltError，避免产生半初始化的数据库。
- [ ] Runtime 不创建 GateEngine、StageRunner、ActionBroker 或 Legacy API；L0 的应用工厂只加载 Shipyard Workbench routes。

### Step 4: 实现 readiness 和关闭语义

- [ ] readiness 返回三个检查：

~~~text
registry: database_path.exists() and not closed
artifact_store: artifact_path.is_dir()
frontend: frontend_dir.is_dir() and (frontend_dir / "index.html").is_file()
~~~

- [ ] 所有 check 通过时返回 ReadinessReport(ready=True, checks=checks)；任一检查失败时返回 ready=False，不抛出异常。
- [ ] close 必须幂等：第一次关闭 SQLite Registry 并将 closed 设为 True；第二次不重复关闭、不抛出异常。
- [ ] close 不删除任何 .shipyard 文件。
- [ ] build_local_runtime 发生中途异常时关闭已经打开的 Registry，再重新抛出原始异常。

### Step 5: 运行 Runtime 测试和完整 Shipyard 测试

- [ ] 运行：

~~~text
pytest tests/shipyard/test_local_runtime.py tests/shipyard tests/api/test_shipyard_routes.py -q
~~~

预期：Runtime 新测试、既有 Shipyard contract/store/service 测试和 HTTP contract 测试全部通过。

### Step 6: 提交 Task 4

- [ ] 检查：

~~~text
git diff --check
git diff --name-only
~~~

- [ ] 提交：

~~~text
git add src/aifde/shipyard/runtime.py src/aifde/shipyard/__init__.py tests/shipyard/test_local_runtime.py
git commit -m "feat: add local Shipyard runtime composition root"
~~~

---

## Task 5: 增加 shipyard init/web CLI 和 Python 安装入口

**Files:**

- Create: src/aifde/shipyard/cli.py
- Create: tests/shipyard/test_cli.py
- Modify: pyproject.toml
- Modify: README.md

**Interfaces:**

- build_parser() -> argparse.ArgumentParser
- main(argv: Sequence[str] | None = None) -> int
- run_local_web(runtime: LocalShipyardRuntime, *, uvicorn_runner: Callable[..., Any] | None = None, browser_opener: Callable[[str], Any] | None = None) -> None

### Step 1: 写 CLI 失败测试

- [ ] 在 tests/shipyard/test_cli.py 中写：

~~~python
from pathlib import Path

from aifde.shipyard import cli


def test_init_creates_config_and_runtime_directories(tmp_path: Path) -> None:
    exit_code = cli.main(["init", str(tmp_path), "--owner", "alice"])

    assert exit_code == 0
    assert (tmp_path / ".shipyard/config.yaml").is_file()
    assert (tmp_path / ".shipyard/artifacts").is_dir()
    assert (tmp_path / ".shipyard/shipyard.db").exists() is False


def test_init_does_not_overwrite_without_force(tmp_path: Path) -> None:
    assert cli.main(["init", str(tmp_path), "--owner", "alice"]) == 0

    assert cli.main(["init", str(tmp_path), "--owner", "bob"]) == 2


def test_web_delegates_to_injected_local_web_runner(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cli.main(["init", str(tmp_path), "--owner", "alice"])
    frontend = tmp_path / "workbench/dist"
    frontend.mkdir(parents=True)
    (frontend / "index.html").write_text("workbench", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_run(runtime, *, uvicorn_runner=None, browser_opener=None):
        captured.update(
            runtime=runtime,
            host=runtime.config.server.host,
            port=runtime.config.server.port,
        )

    monkeypatch.setattr(cli, "run_local_web", fake_run)

    assert cli.main(["web", "--project", str(tmp_path)]) == 0
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 3080
~~~

- [ ] 测试中不要真正启动 Uvicorn、打开浏览器或占用端口；通过模块级可注入 runner 验证 CLI 传参。

### Step 2: 运行失败测试

- [ ] 运行：

~~~text
pytest tests/shipyard/test_cli.py -q
~~~

预期：CLI 模块不存在、console parser 不完整或 runtime runner 未注入时失败。

### Step 3: 实现 CLI parser

- [ ] 在 cli.py 中实现两个子命令：

~~~text
shipyard init PROJECT_DIRECTORY --owner SUBJECT [--force]
shipyard web --project PROJECT_DIRECTORY [--config PATH] [--frontend-dir PATH] [--port PORT] [--open-browser]
~~~

- [ ] init：

  1. 解析 project directory 为绝对路径；
  2. 要求目录已经存在且是目录；
  3. 调用 write_default_config；
  4. 使用返回的 config path 调用 LocalRuntimeConfig.load；
  5. 调用加载后 config.paths.ensure_directories()；
  6. 打印 config 路径和下一步启动命令；
  7. 成功返回 0；
  8. FileExistsError、路径非法或 owner 空白返回 2，并把可读错误写到 stderr。

- [ ] web：

  1. 读取 config；
  2. 只允许 profile=local；
  3. 支持命令行覆盖 frontend-dir、port 和 open-browser；
  4. host 固定为 127.0.0.1，不增加 --host 0.0.0.0；
  5. 调用 build_local_runtime；
  6. 打印 http://127.0.0.1:<port>；
  7. 调用 run_local_web；
  8. 无论 Uvicorn 正常返回还是抛出异常，都在 finally 中调用 runtime.close；
  9. 配置、静态资源、依赖或运行错误返回 2。

- [ ] run_local_web 的默认 runner 是延迟导入的 uvicorn.run，这样未安装 web extra 时 shipyard init 仍可使用；调用 web 时给出安装命令：

~~~text
python -m pip install -e ".[web]"
~~~

- [ ] run_local_web 的默认 browser_opener 是 webbrowser.open；只有配置 open_browser=true 或传入 --open-browser 时调用，默认不自动打开浏览器。

### Step 4: 增加安装入口

- [ ] 在 pyproject.toml 中增加：

~~~toml
[project.optional-dependencies]
web = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
]

[project.scripts]
shipyard = "aifde.shipyard.cli:main"
~~~

- [ ] 不把 FastAPI 和 Uvicorn 的导入移到普通 aifde 顶层初始化路径；未安装 web extra 时，核心 Python 模块和 shipyard init 仍可导入。
- [ ] 若现有 pyproject 已有 optional-dependencies 或 project.scripts，合并到已有 section，不创建重复 TOML section。

### Step 5: 更新 README 启动说明

- [ ] 在 README.md 增加 Local Web Runtime 小节，包含以下可复制流程：

~~~powershell
python -m pip install -e ".[web]"
Set-Location workbench
npm ci
npm run build
Set-Location ..
shipyard init . --owner alice
shipyard web --project .
~~~

- [ ] 同时说明：

  - 默认地址是 http://127.0.0.1:3080；
  - .shipyard/ 是本地状态目录，不应提交到 Git；
  - scripts/shipyard_seed.py 只初始化演示数据库，不启动 Web；
  - 如果 workbench/dist/index.html 不存在，需要先运行 npm run build；
  - Local Web 不连接客户系统、不执行生产 Action；
  - 后续 headless、团队内网和 Docker profile 不属于 L0。

### Step 6: 运行 CLI、安装入口和回归测试

- [ ] 运行：

~~~text
pytest tests/shipyard/test_cli.py tests/shipyard/test_local_runtime.py -q
python -m compileall -q src tests
python -m pip install -e ".[web]"
shipyard --help
shipyard init --help
shipyard web --help
~~~

预期：CLI 帮助正常输出，init/web 解析器存在，Python 编译无错误。

### Step 7: 提交 Task 5

- [ ] 检查：

~~~text
git diff --check
git diff --name-only
~~~

- [ ] 提交：

~~~text
git add src/aifde/shipyard/cli.py tests/shipyard/test_cli.py pyproject.toml README.md
git commit -m "feat: add Shipyard init and web commands"
~~~

---

## Task 6: 让 React Workbench 通过同源 runtime-config 启动

**Files:**

- Create: workbench/src/runtime.ts
- Create: workbench/src/runtime.test.ts
- Modify: workbench/src/api.ts
- Modify: workbench/src/main.tsx

**Interfaces:**

- WorkbenchRuntimeConfig
- loadRuntimeConfig(fetcher?: typeof fetch) -> Promise<WorkbenchRuntimeConfig>
- ShipyardApiClient(options?: { apiBaseUrl?: string; identity?: string })

现有 App 组件继续接收 api: ShipyardApi，这样现有 App.test.tsx 的 fake API 测试无需依赖浏览器启动流程。只有 main.tsx 负责加载 runtime-config 和实例化真实 client。

### Step 1: 写 runtime-config 失败测试

- [ ] 在 workbench/src/runtime.test.ts 中写：

~~~typescript
import { describe, expect, it } from "vitest";

import { loadRuntimeConfig } from "./runtime";

describe("loadRuntimeConfig", () => {
  it("loads same-origin profile and identity", async () => {
    const fetcher = async () =>
      new Response(
        JSON.stringify({
          profile: "local",
          api_base_url: "",
          identity: "alice",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );

    await expect(loadRuntimeConfig(fetcher)).resolves.toEqual({
      profile: "local",
      apiBaseUrl: "",
      identity: "alice",
    });
  });

  it("rejects a missing or invalid identity", async () => {
    const fetcher = async () =>
      new Response(JSON.stringify({ profile: "local", api_base_url: "" }), {
        status: 200,
      });

    await expect(loadRuntimeConfig(fetcher)).rejects.toThrow(
      "runtime-config identity is missing",
    );
  });

  it("includes the HTTP status when the endpoint is unavailable", async () => {
    const fetcher = async () => new Response("not found", { status: 404 });

    await expect(loadRuntimeConfig(fetcher)).rejects.toThrow(
      "runtime-config request failed (404)",
    );
  });
});
~~~

### Step 2: 运行前端失败测试

- [ ] 运行：

~~~text
cd workbench
npm test -- --run src/runtime.test.ts
cd ..
~~~

预期：runtime.ts 不存在或验证逻辑缺失时失败。

### Step 3: 实现前端 runtime loader

- [ ] 创建 workbench/src/runtime.ts：

~~~typescript
export interface WorkbenchRuntimeConfig {
  profile: "local";
  apiBaseUrl: string;
  identity: string;
}

export async function loadRuntimeConfig(
  fetcher: typeof fetch = fetch,
): Promise<WorkbenchRuntimeConfig> {
  const response = await fetcher("/runtime-config", {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    throw new Error(
      "runtime-config request failed (" + response.status + ")",
    );
  }
  const body = (await response.json()) as Record<string, unknown>;
  if (body.profile !== "local") {
    throw new Error("unsupported runtime profile");
  }
  if (typeof body.identity !== "string" || body.identity.trim() === "") {
    throw new Error("runtime-config identity is missing");
  }
  if (typeof body.api_base_url !== "string") {
    throw new Error("runtime-config api_base_url is missing");
  }
  return {
    profile: "local",
    apiBaseUrl: body.api_base_url,
    identity: body.identity,
  };
}
~~~

- [ ] 不从 runtime-config 返回数据库路径、project root、插件路径、模型 URL 或任何 secret。

### Step 4: 改造 API client 为显式配置

- [ ] 修改 workbench/src/api.ts：

~~~typescript
export class ShipyardApiClient implements ShipyardApi {
  private readonly apiBaseUrl: string;
  private readonly identity: string;

  constructor(options: { apiBaseUrl?: string; identity?: string } = {}) {
    this.apiBaseUrl = (
      options.apiBaseUrl ??
      import.meta.env.VITE_SHIPYARD_API_URL ??
      ""
    ).replace(/\/+$/, "");
    this.identity =
      options.identity ?? import.meta.env.VITE_SHIPYARD_IDENTITY ?? "";
  }

  private pathFor(path: string): string {
    return this.apiBaseUrl + path;
  }

  // listWorkspaces/getSnapshot/mutations continue using request().
}
~~~

- [ ] 删除模块级 apiBaseUrl 和 identity，避免 main.tsx 在加载 runtime-config 前固定读取空身份。
- [ ] request 使用 this.pathFor(path)，继续设置 X-Shipyard-Identity，但当 identity 为空时抛出明确的 Error，不发送没有身份的业务请求。
- [ ] 保留构造函数无参数兼容性，使 Vite 环境变量和已有外部消费者仍可使用；Local Web 由 main.tsx 传入 runtime-config。

### Step 5: 改造 main.tsx 启动流程

- [ ] 将当前直接渲染改为：

~~~typescript
import { loadRuntimeConfig } from "./runtime";

async function bootstrap(): Promise<void> {
  try {
    const runtime = await loadRuntimeConfig();
    createRoot(root).render(
      <StrictMode>
        <App
          api={
            new ShipyardApiClient({
              apiBaseUrl: runtime.apiBaseUrl,
              identity: runtime.identity,
            })
          }
        />
      </StrictMode>,
    );
  } catch (error) {
    root.setAttribute("role", "alert");
    root.textContent =
      error instanceof Error
        ? "Unable to start Shipyard Workbench: " + error.message
        : "Unable to start Shipyard Workbench";
  }
}

void bootstrap();
~~~

- [ ] 启动错误不得把 stack trace、API key 或本地绝对路径写入页面。
- [ ] 不修改 App 的业务门禁判断、Proposal 审阅和 Release Candidate UI；本任务只改变真实 API client 的启动配置。

### Step 6: 运行前端测试和构建

- [ ] 运行：

~~~text
cd workbench
npm test -- --run
npm run build
cd ..
~~~

预期：现有 App tests 和新的 runtime-config tests 全部通过，Vite 在 workbench/dist 生成 index.html。

### Step 7: 提交 Task 6

- [ ] 检查：

~~~text
git diff --check
git diff --name-only
~~~

- [ ] 提交：

~~~text
git add workbench/src/runtime.ts workbench/src/runtime.test.ts workbench/src/api.ts workbench/src/main.tsx
git commit -m "feat: bootstrap Workbench from local runtime config"
~~~

---

## Task 7: 打通本地 Web HTTP 垂直切片

**Files:**

- Create: tests/e2e/test_shipyard_local_web.py
- Modify: tests/api/test_runtime_routes.py
- Modify: README.md

**Interfaces:**

- 使用 Task 4 的 build_local_runtime；
- 使用 Task 3 的 create_shipyard_app、healthz、readyz、runtime-config；
- 使用 Task 6 生成的静态 Workbench dist。

### Step 1: 写端到端失败测试

- [ ] 在 tests/e2e/test_shipyard_local_web.py 中写一个完整的 TestClient 流程：

~~~python
from pathlib import Path

from fastapi.testclient import TestClient

from aifde.shipyard.config import LocalRuntimeConfig, write_default_config
from aifde.shipyard.runtime import build_local_runtime


def test_local_web_serves_ui_and_governed_workspace_api(tmp_path: Path) -> None:
    frontend = tmp_path / "workbench/dist"
    frontend.mkdir(parents=True)
    (frontend / "index.html").write_text(
        "<html><body>Shipyard Workbench</body></html>",
        encoding="utf-8",
    )
    write_default_config(tmp_path, owner="alice")
    config = LocalRuntimeConfig.load(tmp_path)

    runtime = build_local_runtime(config)
    try:
        client = TestClient(runtime.app)

        assert client.get("/healthz").status_code == 200
        assert client.get("/readyz").json()["ready"] is True
        assert client.get("/").status_code == 200

        created = client.post(
            "/workspaces",
            headers={"X-Shipyard-Identity": "alice"},
            json={
                "workspace_id": "ws-e2e",
                "project_id": "project-e2e",
                "name": "E2E Workbench",
                "domain_pack": "software_delivery",
            },
        )
        assert created.status_code == 201

        forbidden = client.get(
            "/workspaces",
            headers={"X-Shipyard-Identity": "bob"},
        )
        assert forbidden.status_code == 403
    finally:
        runtime.close()
~~~

- [ ] 在同一测试文件加入：

  - 缺少身份头访问 /workspaces 返回 401；
  - GET /runtime-config 不返回 database_path、project_root、api_key 字段；
  - GET /readyz 在 runtime.close 后返回 503；
  - 前端目录缺失时 build_local_runtime 抛出 FrontendNotBuiltError，且 .shipyard/shipyard.db 不存在。

### Step 2: 运行垂直切片测试

- [ ] 运行：

~~~text
pytest tests/e2e/test_shipyard_local_web.py tests/api/test_runtime_routes.py -q
~~~

预期：所有 Local Web API、静态页面、身份隔离、readiness 和缺失前端测试通过。

### Step 3: 使用真实构建产物验证

- [ ] 在仓库根目录按顺序运行：

~~~text
cd workbench
npm ci
npm run build
cd ..
python -m pip install -e ".[web]"
shipyard init . --owner alice --force
shipyard web --project .
~~~

- [ ] 在另一个终端使用 Python HTTP client 或浏览器访问：

~~~text
GET http://127.0.0.1:3080/healthz
GET http://127.0.0.1:3080/readyz
GET http://127.0.0.1:3080/runtime-config
GET http://127.0.0.1:3080/
~~~

- [ ] 验证：

  - healthz 返回 profile=local；
  - readyz 为 ready=true；
  - runtime-config identity 为 alice 且没有本地路径或 secret；
  - / 返回 Workbench index；
  - 浏览器能够加载静态 JS/CSS；
  - Workbench 显示空 workspace 或 seed 后的 workspace；
  - Ctrl+C 后进程退出，.shipyard/ 保留。

### Step 4: 验证 seed 与 Web 边界

- [ ] 在临时数据库上运行现有 seed：

~~~text
python scripts/shipyard_seed.py --database .shipyard/shipyard.db --owner alice
~~~

- [ ] 重启 shipyard web --project .，确认 Workbench 能读取 seed 的 Workspace、Artifact、Gate Review 和 Release Candidate。
- [ ] 确认 seed 输出中的 external_connections 仍为空、production_actions_executed 仍为 false。
- [ ] 不对 scripts/shipyard_seed.py 添加 Web 启动逻辑。

### Step 5: 提交 Task 7

- [ ] 检查：

~~~text
git diff --check
git diff --name-only
~~~

- [ ] 提交：

~~~text
git add tests/e2e/test_shipyard_local_web.py tests/api/test_runtime_routes.py README.md
git commit -m "test: verify local Shipyard Web vertical slice"
~~~

---

## Task 8: 完成 L0 全量验证和交付检查

**Files:**

- No new production files.
- Review only: all files created or modified by Tasks 1-7.

### Step 1: Python 专项验证

- [ ] 运行：

~~~text
pytest tests/shipyard tests/api tests/e2e/test_shipyard_workbench_flow.py tests/e2e/test_shipyard_local_web.py -q
~~~

预期：所有 Shipyard、API 和两个 Workbench E2E 测试通过，失败数为 0。

### Step 2: Python 全量验证

- [ ] 运行：

~~~text
pytest -q
python -m compileall -q src tests
~~~

预期：全量 pytest 通过，compileall 返回退出码 0。

### Step 3: 前端全量验证

- [ ] 运行：

~~~text
cd workbench
npm test -- --run
npm run build
cd ..
~~~

预期：全部 Vitest 测试通过，TypeScript 检查和 Vite build 退出码为 0。

### Step 4: CLI 和安全边界验证

- [ ] 运行：

~~~text
shipyard --help
shipyard init --help
shipyard web --help
git diff --check
git status --short
~~~

- [ ] 逐项确认：

  - CLI 只新增 init/web，不出现生产 Action、远程开放 host 或客户连接器选项；
  - Local Profile 默认 host 为 127.0.0.1；
  - .shipyard/ 和 workbench/dist/ 不会被 Git 跟踪；
  - 当前用户已有修改仍然存在；
  - 所有 Task commit 的文件清单没有包含用户未授权文件；
  - git log --oneline --max-count=8 可以列出本实施计划的 Task commit，再对列表中的每个 commit 运行 git show --name-only --format=oneline；
  - 代码中没有绕过 Application Service 写 Registry 的新路径；
  - runtime-config 没有文件路径、模型地址或 secret；
  - Local Web 没有生产 Action endpoint。

### Step 5: 形成实施结果记录

- [ ] 在实现分支的最终说明中记录：

  - L0 实际新增的命令；
  - 本地安装和前端构建命令；
  - Python 专项和全量测试结果；
  - 前端测试和 build 结果；
  - 默认安全边界；
  - 明确未实现的 L1/L3/L4 能力；
  - 真实浏览器验证的 URL 和结果；
  - 产生的 commit 列表。

- [ ] 不把“能启动本地 Web”描述为“已具备客户生产运行时”或“已完成完整 AI-FDE”。

---

## 计划与设计文档的覆盖检查

在保存计划后，按设计文档逐节核对以下映射：

| 设计要求 | 计划任务 |
| --- | --- |
| Local Profile 默认 127.0.0.1 | Task 1、Task 5、Task 8 |
| SQLite、文件 Artifact Store、本地目录 | Task 1、Task 4 |
| Workbench 同源静态 Web | Task 3、Task 6、Task 7 |
| Application Service 唯一写入边界 | Task 3、Task 4、Task 7 |
| 本地 owner 身份与 owner-only 授权 | Task 2、Task 7 |
| healthz、readyz、runtime-config | Task 3、Task 7 |
| 进程重启后保持状态 | Task 4、Task 7 |
| CLI init/web | Task 5 |
| headless、Worker、Sandbox、Docker 不提前实现 | Global Constraints、Task 5、Task 8 |
| 前端 Workbench 与 Chat sidecar 的边界 | Task 6；不修改 App 领域 UI |
| 失败时 fail closed | Task 1、Task 3、Task 4、Task 7 |
| 验收、回归和审计 | Task 7、Task 8 |

自审结果：

- 计划只覆盖 L0，没有把设计中的 L1-L4 混入本次代码任务；
- 所有计划接口在首次使用前都在对应任务的 Interfaces 段定义；
- 所有失败路径都有明确的异常、HTTP 状态或退出码；
- 没有用 Agent 自报状态替代 Application Service、Gate 或 Registry；
- 没有使用模糊的待办占位符代替文件、函数、命令或验收条件；
- 任务结束时均有专门测试和独立 commit。

## 执行交接

计划已准备好。实现时必须在执行会话中逐任务遵循 TDD、独立验证和提交规则。

可选择两种执行方式：

1. **Subagent-Driven（推荐）**：每个任务派发一个新的子 Agent，主 Agent 在任务之间审查代码、运行测试并决定是否进入下一任务。若采用此方式，子 Agent 只能使用 gpt-5.6-luna。
2. **Inline Execution**：在当前会话中使用 executing-plans，按任务批次执行并在检查点停下审阅。
