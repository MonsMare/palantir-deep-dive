# Production Docker Environment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Provide a reproducible single-host production-like Docker Compose environment for AI-FDE with PostgreSQL, Redis Streams, MinIO, API, Worker, Linear Bridge and migration/acceptance profiles.

**Architecture:** Keep SQLite as the offline/test storage mode and add production adapters behind explicit protocols. The Compose app uses one Python image with role-specific commands, while PostgreSQL stores task/runtime metadata, Redis Streams dispatches work, MinIO stores large evidence/artifacts, and the health/readiness layer fails closed.

**Tech Stack:** Docker Compose v2, Python 3.11+, FastAPI, Uvicorn, Pydantic v2, psycopg 3, redis-py, boto3-compatible MinIO, PostgreSQL, Redis, MinIO, pytest and PyYAML.

## Global Constraints

- Compose is a single-host recoverable deployment, not a multi-node HA cluster.
- PostgreSQL is the production fact store for task/runtime data; Redis is a delivery mechanism, not business truth.
- MinIO stores large evidence and artifacts; PostgreSQL stores metadata, hashes, versions and lineage.
- Every service has a healthcheck; readiness checks PostgreSQL, Redis, MinIO, migration version and policy loading.
- Containers run as non-root users, do not use privileged mode and do not mount Docker socket.
- Secrets come from environment or Docker secrets and never enter images, source control, comments or logs.
- Worker delivery is at-least-once and every task must be idempotent.
- Docker assets are validated with Docker Compose config and smoke tests when Docker is available.

---

## Task 1: Add production configuration and optional dependencies

**Files:**
- Modify: pyproject.toml
- Create: src/aifde/production/__init__.py
- Create: src/aifde/production/config.py
- Test: tests/production/test_config.py

**Interfaces:**

- ProductionSettings.from_env(environ: Mapping[str, str]) -> ProductionSettings
- ProductionSettings.redacted() -> dict[str, str | int | bool]
- ProductionSettings.storage_mode, database_url, redis_url, minio_endpoint, linear_mode, max_fix_rounds and task_timeout_seconds.

- [ ] **Step 1: Write failing configuration tests**

~~~python
def test_production_settings_requires_postgres_in_prod():
    with pytest.raises(SettingsError, match="DATABASE_URL"):
        ProductionSettings.from_env({"AIFDE_ENV": "prod", "AIFDE_STORAGE": "postgres"})


def test_redacted_settings_never_returns_secret_values():
    settings = ProductionSettings.from_env({
        "AIFDE_ENV": "test",
        "AIFDE_STORAGE": "sqlite",
        "LINEAR_MODE": "fake",
        "MODEL_API_KEY": "model-secret",
    })
    assert settings.redacted()["MODEL_API_KEY"] == "***"
~~~

- [ ] **Step 2: Run the tests and verify they fail**

Run: pytest tests/production/test_config.py -q

Expected: collection fails because aifde.production.config does not exist.

- [ ] **Step 3: Add optional dependency groups**

Add API and production extras without changing the core dependency set:

~~~toml
[project.optional-dependencies]
api = ["fastapi>=0.115", "uvicorn[standard]>=0.30"]
production = ["psycopg[binary]>=3.2", "redis>=5", "boto3>=1.35"]
~~~

Implement strict environment parsing, safe defaults for test/fake mode and fail-closed production validation.

- [ ] **Step 4: Run focused tests and verify they pass**

Run: pytest tests/production/test_config.py -q

Expected: all focused tests pass.

- [ ] **Step 5: Commit**

~~~text
git add pyproject.toml src/aifde/production tests/production/test_config.py
git commit -m "feat: add production runtime settings"
~~~

## Task 2: Add PostgreSQL runtime persistence and schema migration

**Files:**
- Create: migrations/001_runtime.sql
- Create: src/aifde/persistence/__init__.py
- Create: src/aifde/persistence/postgres.py
- Create: src/aifde/persistence/migrations.py
- Test: tests/persistence/test_postgres_schema.py
- Test: tests/persistence/test_postgres_task_store.py

**Interfaces:**

- PostgresConnectionFactory(database_url: str)
- apply_migrations(connection_factory) -> int
- PostgresTaskStore implements the TaskStore interface from the Linear plan.
- PostgresTaskStore.healthcheck() -> bool
- PostgresTaskStore.schema_version() -> int

- [ ] **Step 1: Write failing schema contract tests**

~~~python
def test_runtime_schema_contains_inbox_outbox_and_lease_tables():
    statements = load_migration_sql("migrations/001_runtime.sql")
    assert "linear_events_inbox" in statements
    assert "outbox_events" in statements
    assert "agent_leases" in statements


def test_postgres_store_is_idempotent_for_same_outbox_key(postgres_connection):
    store = PostgresTaskStore(postgres_connection)
    first = store.enqueue_outbox("comment", "linear", "task-1", {"body": "ok"}, "key-1")
    second = store.enqueue_outbox("comment", "linear", "task-1", {"body": "ok"}, "key-1")
    assert first.outbox_id == second.outbox_id
~~~

- [ ] **Step 2: Run the schema tests and verify they fail**

Run: pytest tests/persistence/test_postgres_schema.py tests/persistence/test_postgres_task_store.py -q

Expected: collection or fixture failure because the migration and adapter do not exist. The Postgres integration test must be skipped with a clear reason when DATABASE_URL is absent.

- [ ] **Step 3: Implement the migration and adapter**

Create tables for task_contracts, task_events, linear_events_inbox, outbox_events, agent_leases, audit_events, runtime_objects and schema_version. Use unique constraints for external_event_id, idempotency_key and task contract version. Keep JSON payloads canonical and store content hashes.

Do not import psycopg at module import time in offline mode. Raise a typed ProductionDependencyError when production storage is selected without the optional package.

- [ ] **Step 4: Run the migration contract tests**

Run: pytest tests/persistence/test_postgres_schema.py -q

Expected: all SQL contract tests pass.

- [ ] **Step 5: Start PostgreSQL in Docker and run integration tests**

Run:

~~~text
docker run --rm --name aifde-postgres-test -e POSTGRES_PASSWORD=test -e POSTGRES_DB=aifde -p 55432:5432 -d postgres:16-alpine
pytest tests/persistence/test_postgres_task_store.py -q
docker stop aifde-postgres-test
~~~

Expected: all Postgres store tests pass and the container is stopped.

- [ ] **Step 6: Commit**

~~~text
git add migrations src/aifde/persistence tests/persistence
git commit -m "feat: add postgres runtime persistence"
~~~

## Task 3: Add Redis Streams and MinIO adapters

**Files:**
- Create: src/aifde/queue/__init__.py
- Create: src/aifde/queue/redis_streams.py
- Create: src/aifde/storage/__init__.py
- Create: src/aifde/storage/object_store.py
- Test: tests/queue/test_redis_streams.py
- Test: tests/storage/test_object_store.py

**Interfaces:**

- RedisStreamQueue.publish(stream: str, envelope: EventEnvelope) -> str
- RedisStreamQueue.consume(stream, group, consumer, count) -> list[QueuedEvent]
- RedisStreamQueue.ack(stream, group, message_id) -> None
- RedisStreamQueue.healthcheck() -> bool
- ObjectStore.put(key: str, content: bytes, content_type: str) -> StoredObject
- ObjectStore.get(key: str) -> bytes
- ObjectStore.healthcheck() -> bool

- [ ] **Step 1: Write failing adapter tests using injected fake clients**

~~~python
def test_queue_envelope_preserves_idempotency_key():
    queue = RedisStreamQueue(FakeRedis())
    message_id = queue.publish("aifde.task.dispatch", EventEnvelope(
        event_id="event-1",
        event_type="agent.run.requested",
        idempotency_key="task-1:run-1",
        payload_ref="task-1",
    ))
    event = queue.fake_messages[message_id]
    assert event.idempotency_key == "task-1:run-1"


def test_object_store_returns_content_hash():
    store = S3ObjectStore(FakeS3Client(), bucket="aifde")
    stored = store.put("evidence/e-1/original", b"abc", "text/plain")
    assert stored.content_hash == hashlib.sha256(b"abc").hexdigest()
~~~

- [ ] **Step 2: Run tests and verify they fail**

Run: pytest tests/queue/test_redis_streams.py tests/storage/test_object_store.py -q

Expected: collection fails because the adapters do not exist.

- [ ] **Step 3: Implement at-least-once queue semantics**

Create Consumer Group support, explicit ACK, bounded claim/lease metadata and typed envelopes. Do not delete messages on processing failure. Keep Redis imports optional for offline tests.

- [ ] **Step 4: Implement MinIO-compatible S3 storage**

Use a boto3-compatible client injected into S3ObjectStore. Store content type, size, hash and object key. Verify the hash on read. Keep bucket creation separate from object writes.

- [ ] **Step 5: Run focused tests and verify they pass**

Run: pytest tests/queue/test_redis_streams.py tests/storage/test_object_store.py -q

Expected: all focused tests pass.

- [ ] **Step 6: Commit**

~~~text
git add src/aifde/queue src/aifde/storage tests/queue tests/storage
git commit -m "feat: add redis streams and minio object adapters"
~~~

## Task 4: Add service entrypoints and production health endpoints

**Files:**
- Create: src/aifde/production/health_app.py
- Create: src/aifde/production/entrypoint.py
- Create: src/aifde/production/__main__.py
- Modify: src/aifde/deployment/health.py
- Test: tests/production/test_health_app.py
- Test: tests/production/test_entrypoint.py

**Interfaces:**

- create_health_app(probes: Mapping[str, Callable[[], bool]]) -> FastAPI
- run_service(mode: Literal["api", "worker", "bridge", "migrate"], settings: ProductionSettings) -> int
- service modes return non-zero on failed migration or required dependency startup.

- [ ] **Step 1: Write failing health and entrypoint tests**

~~~python
def test_ready_is_503_when_postgres_probe_fails():
    app = create_health_app({"postgres": lambda: False, "redis": lambda: True})
    response = TestClient(app).get("/health/ready")
    assert response.status_code == 503
    assert response.json()["ready"] is False


def test_live_does_not_require_dependencies():
    app = create_health_app({"postgres": lambda: False})
    response = TestClient(app).get("/health/live")
    assert response.status_code == 200
~~~

- [ ] **Step 2: Run tests and verify they fail**

Run: pytest tests/production/test_health_app.py tests/production/test_entrypoint.py -q

Expected: collection fails because the health app and service entrypoint do not exist.

- [ ] **Step 3: Implement live/readiness routes**

Return JSON with ready, component status and sanitized detail. Live must only prove that the process is serving. Ready must fail closed and include migration version.

- [ ] **Step 4: Implement service modes**

API starts the health/API application; worker consumes Redis Streams and invokes an injected DomainTaskDispatcher; bridge runs poll and Outbox loops with bounded intervals; migrate applies PostgreSQL migrations and exits. Fake mode must not require Linear API credentials.

- [ ] **Step 5: Run focused tests and verify they pass**

Run: pytest tests/production/test_health_app.py tests/production/test_entrypoint.py -q

Expected: all focused tests pass.

- [ ] **Step 6: Commit**

~~~text
git add src/aifde/production src/aifde/deployment/health.py tests/production
git commit -m "feat: add production service entrypoints and health checks"
~~~

## Task 5: Build the Python image and Compose topology

**Files:**
- Create: Dockerfile
- Create: .dockerignore
- Create: compose.yaml
- Create: .env.example
- Create: docker/healthcheck.py
- Test: tests/production/test_compose_contract.py

**Interfaces:**

- compose.yaml services: postgres, redis, minio, migrate, aifde-api, aifde-worker, aifde-linear-bridge.
- profiles: test for evaluator/smoke services.
- default mode is LINEAR_MODE=fake unless explicitly set to real.

- [ ] **Step 1: Write failing Compose contract tests**

~~~python
def test_compose_declares_required_services():
    document = yaml.safe_load(Path("compose.yaml").read_text())
    assert {
        "postgres", "redis", "minio", "migrate",
        "aifde-api", "aifde-worker", "aifde-linear-bridge",
    } <= set(document["services"])


def test_worker_does_not_mount_docker_socket():
    document = yaml.safe_load(Path("compose.yaml").read_text())
    volumes = document["services"]["aifde-worker"].get("volumes", [])
    assert not any("/var/run/docker.sock" in str(item) for item in volumes)
~~~

- [ ] **Step 2: Run the tests and verify they fail**

Run: pytest tests/production/test_compose_contract.py -q

Expected: failure because compose.yaml and Dockerfile do not exist.

- [ ] **Step 3: Implement the non-root image**

Install the package with API and production extras, use a fixed Python base image, create a non-root user, set a writable /tmp and run service modes through python -m aifde.production.

- [ ] **Step 4: Implement Compose health dependencies and volumes**

Use named volumes for postgres-data, redis-data, minio-data, runs and logs. Add healthchecks for all stateful services. Make migrate complete before application services become ready. Do not put credentials directly in compose.yaml.

- [ ] **Step 5: Run YAML contract tests and Compose config**

Run:

~~~text
pytest tests/production/test_compose_contract.py -q
docker compose config
~~~

Expected: tests pass and docker compose config exits 0.

- [ ] **Step 6: Commit**

~~~text
git add Dockerfile .dockerignore compose.yaml .env.example docker tests/production/test_compose_contract.py
git commit -m "feat: add production docker compose topology"
~~~

## Task 6: Wire the container worker and Bridge to the Linear lifecycle

**Files:**
- Modify: src/aifde/production/entrypoint.py
- Modify: src/aifde/production/health_app.py
- Create: src/aifde/production/runtime_factory.py
- Test: tests/e2e/test_production_compose_runtime.py

- [ ] **Step 1: Write failing runtime wiring tests**

~~~python
def test_fake_mode_builds_bridge_without_linear_credentials():
    runtime = build_runtime({
        "AIFDE_ENV": "test",
        "AIFDE_STORAGE": "sqlite",
        "LINEAR_MODE": "fake",
    })
    assert runtime.bridge.adapter.__class__.__name__ == "FakeLinearAdapter"


def test_real_mode_fails_closed_without_linear_key():
    with pytest.raises(SettingsError, match="LINEAR_API_KEY"):
        build_runtime({
            "AIFDE_ENV": "prod",
            "AIFDE_STORAGE": "postgres",
            "LINEAR_MODE": "real",
            "DATABASE_URL": "postgresql://example",
        })
~~~

- [ ] **Step 2: Run the tests and verify they fail**

Run: pytest tests/e2e/test_production_compose_runtime.py -q

Expected: failure because runtime_factory does not exist.

- [ ] **Step 3: Implement dependency-injected runtime construction**

Construct store, queue, object store, Fake/Real Linear Adapter, Bridge, DomainTaskDispatcher, readiness probes and service loops from ProductionSettings. Keep a single factory so API, worker and Bridge do not create divergent policy or state logic.

- [ ] **Step 4: Run focused runtime tests and verify they pass**

Run: pytest tests/e2e/test_production_compose_runtime.py -q

Expected: all focused tests pass.

- [ ] **Step 5: Commit**

~~~text
git add src/aifde/production tests/e2e/test_production_compose_runtime.py
git commit -m "feat: wire production runtime dependencies"
~~~

## Task 7: Add Docker smoke and persistence recovery acceptance

**Files:**
- Create: tests/production/test_compose_smoke.py
- Create: docker/smoke.ps1
- Create: docs/production-docker-operations.md
- Modify: README.md

- [ ] **Step 1: Write the failing smoke contract**

The test/script must assert:

1. compose config succeeds;
2. stateful services become healthy;
3. migrate exits 0;
4. API live returns 200;
5. API ready returns 200 after all dependencies are healthy;
6. Fake Linear lifecycle can be exercised without LINEAR_API_KEY;
7. PostgreSQL, Redis and MinIO volumes survive service restart.

- [ ] **Step 2: Run the smoke contract before implementation**

Run: pytest tests/production/test_compose_smoke.py -q

Expected: failures identify missing service files or unavailable Docker; if Docker is unavailable, tests must skip with a clear reason and the final verification must report the skip.

- [ ] **Step 3: Implement the smoke script**

Use one PowerShell script for Windows Docker Desktop. It must use explicit Compose project names, clean only the project-owned containers/volumes when requested, poll health with a timeout, and print service logs on failure. It must never remove unrelated Docker resources.

- [ ] **Step 4: Run Docker build and smoke**

Run:

~~~text
docker compose build
docker compose up -d postgres redis minio
docker compose run --rm migrate
docker compose up -d aifde-api aifde-worker aifde-linear-bridge
powershell -ExecutionPolicy Bypass -File docker/smoke.ps1
docker compose down
~~~

Expected: all images build, migration exits 0, health checks pass and the smoke script exits 0.

- [ ] **Step 5: Document operations**

Document startup, Fake/Real Linear switching, logs, health endpoints, backup commands, restart recovery, Dead Letter inspection and safe teardown. State explicitly that Compose is single-host production-like, not HA.

- [ ] **Step 6: Commit**

~~~text
git add tests/production/test_compose_smoke.py docker/smoke.ps1 docs/production-docker-operations.md README.md
git commit -m "test: add docker production smoke and recovery acceptance"
~~~

## Final Docker Plan Verification

- [ ] Run pytest tests/production tests/persistence tests/queue tests/storage -q
- [ ] Run the full pytest -q
- [ ] Run python -m compileall -q src tests
- [ ] Run docker compose config
- [ ] Run Docker build and smoke when Docker is available
- [ ] Check every container is non-root and no service mounts Docker socket
- [ ] Check .env.example contains names only and no credential values
- [ ] Check git diff --check

## Dependency Order

1. Complete the Linear plan Tasks 1–5 before Docker Task 6.
2. Docker Tasks 1–5 may be developed with SQLite/Fake adapters and tested independently.
3. Docker Task 2 provides the PostgreSQL implementation of the TaskStore interface introduced by Linear Task 3.
4. Run the full suite after integrating both plans.
