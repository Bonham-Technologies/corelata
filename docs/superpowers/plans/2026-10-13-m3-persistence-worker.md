# Corelata M3: Persistence, Service Layer and Worker — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver spec §14 M3: a Postgres schema under Alembic, a procrastinate worker that executes queued runs and discoveries, a service layer the CLI uses now and the API (M4a) will use unchanged, cancellation and stalled-job requeue, reruns linked through `parent_run_id` (review "return"), and the profile's DOCX reference document stored with the run — so every export the worker writes is reproducible from the database alone (spec §8.4 invariant 5).

**Architecture:** The pipeline stays a single in-process coroutine (`run_report`) and gains a `RunObserver` with three hooks (state changed, stage recorded, cancel requested); a run is **one queue job** that executes the pipeline with a database-backed observer, so stage rows, model calls and token usage land in Postgres while the run proceeds and an analyst's cancel is honoured at the next stage boundary. Rows are the source of truth: `store/records.py` maps a `RunRecord` to rows and back, and every export is rendered from that record. The persistence, worker, storage, migration and Postgres-test modules are copied from Coglossa (spec §4.3) with the product name parameterised; divergences are logged in `docs/m3-followups.md`.

**Tech Stack:** Python 3.12, uv, pydantic v2, SQLAlchemy 2 async + psycopg 3, Alembic, procrastinate 3.10 (Postgres-backed queue, schema vendored), pytest + pytest-asyncio against a real Postgres 16 (`CORELATA_TEST_DATABASE_URL`), Docker Compose for the dev database.

**Spec:** `docs/superpowers/specs/2026-10-12-corelata-v1-design.md` — §4.2 (layout), §4.3 (copy-from-Coglossa rule), §5 (sources), §7.1 (discovery job), §7.2 (state machine, `cancelled`), §7.5 (stalled requeue), §8.3 (tables), §8.4 (invariants), §9 (DOCX reference), §10.1 (service semantics the API will expose: cancel, review accept/return), §10.2 (CLI: `ingest`, `discover`, `run` against the database, `review`, `doctor`, `migrate`, `worker`), §11 (`database`, `storage`, `worker` sections), §13 (real Postgres in tests), §14 (M3 row). M2 follow-ups: `docs/m2-followups.md` (store the DOCX reference with the run). Coglossa source for copied modules: `~/Downloads/coglossa/engine/coglossa/` (`store/`, `storage.py`, `worker/app.py`, `logs.py`, `testing/postgres.py`, `testing/pytest_db.py`, `testing/queue.py`, `doctor.py`, `cli_ops.py`).

**Working directory for every command below:** `engine/` (the package root with `pyproject.toml`). Paths in **Files:** blocks are relative to the repository root. Every `uv run pytest` below needs `CORELATA_TEST_DATABASE_URL` set (Task 1 explains how); `make test-engine` from the repository root sets it.

## Global Constraints

- Python `>=3.12`; `uv` for everything (`uv run pytest`, `uv run ruff ...`). New runtime dependencies are exactly: `sqlalchemy[asyncio]>=2.0.36,<3`, `alembic>=1.14,<2`, `psycopg[binary]>=3.2,<4`, `procrastinate>=3.10,<3.11` (the pins Coglossa ships). No others.
- `pytest` runs with `--cov=corelata --cov-branch --cov-fail-under=95` and `filterwarnings = error`; every task leaves the whole suite green and coverage at or above 95%. `uv run ruff check .` and `uv run ruff format --check .` clean (line length 100, rules E F I B UP SIM).
- Tests use a real Postgres (spec §13). A missing `CORELATA_TEST_DATABASE_URL` **fails** the tests that need it, never skips them. CI gets a `postgres:16-alpine` service (Task 1).
- The engine library has no knowledge of the database: only `corelata.store`, `corelata.service`, `corelata.worker`, `corelata.doctor`, `corelata.cli_ops`, `corelata.cli` (it imports `cli_ops`), `corelata.testing.postgres` and `corelata.testing.pytest_db` may import `sqlalchemy`, `alembic`, `psycopg` or `procrastinate`. `tests/test_boundary.py` (Task 1) enforces it. `corelata run` without `--project` still needs none of them.
- Product name parameterised (spec §4.3): env prefix `CORELATA_`, queue name `corelata`, task names `corelata.run`, `corelata.discover`, `corelata.requeue_stalled`, worker name `corelata-worker`, test database prefix `corelata_test_`, test env var `CORELATA_TEST_DATABASE_URL`, loggers `corelata` and `procrastinate`.
- Every intentional change to a module copied from Coglossa is recorded in `docs/m3-followups.md` under **Divergences from Coglossa** with a one-line reason; an improvement Coglossa should take is tagged **backport** (Task 11 writes the file; earlier tasks note what to record in their reports).
- A database URL is never printed unredacted; it comes only from the environment variable named by `database.url_env` (default `CORELATA_DATABASE_URL`). Every connection has a 10 s connect timeout.
- No transaction is held open across a model call. Every run state change happens in a transaction that holds the run row lock (`SELECT … FOR UPDATE`).
- Timestamps are timezone-aware UTC (`datetime.now(UTC)`).
- Trace invariants (spec §8.4) hold unchanged; invariant 5 in its M3 form: `load_record(db, run_id)` returns a `RunRecord` from rows alone, and `corelata export RUN_ID --out DIR` followed by `corelata report DIR` reproduces every export the worker stored, byte for byte.
- `RunRecord.schema_version` stays `"1"`: the two fields added in Task 3 (`parent_run_id`, `extra_guidance`) are optional with defaults (`docs/trace-format.md`, Compatibility).
- Production modules never import `corelata.testing` (the single sanctioned exception stays `cli.py` importing `corelata.testing.fake_openai` for the `fake-openai` subcommand).
- Exit codes: existing ones unchanged (0 completed clean, 3 findings open, 4 gate rejected, 1 failed, 2 usage or config error, 130 interrupted). Queued-run commands (`ingest`, `run --project`, `discover --project`, `status`, `cancel`, `review`, `export`, `migrate`, `worker`, `doctor`) use 0 success, 2 for a user error (bad arguments, config, pack, unknown id, invalid state), 1 for an unreachable database or an internal error; never a traceback.
- Commits: conventional prefix (`feat:`, `refactor:`, `test:`, `docs:`, `fix:`, `build:`), one task per commit unless a step says otherwise, ending with the attribution lines the session supplies.

## Review Focus

1. A worker killed mid-run (`kill -9`, node reboot): the job is re-queued by the stalled-job task, the new execution starts the run over, and the delivered trace describes only the attempt that produced the report (`run.attempts` = 2, no stage rows from the dead attempt). (Tests in Task 6 and Task 8.)
2. `corelata cancel` while the writer is drafting: no further model call is made after the current stage, the run ends `cancelled` with its stage rows and model calls on record and no report; cancelling a `created` run makes it `cancelled` at once and the job later finds nothing to do. (Task 5 and Task 6.)
3. The same run job delivered twice (procrastinate retry after a database blip): the second delivery finds a terminal run and returns without a model call. (Task 6.)
4. A profile `docx_reference` that is edited or deleted after the run was queued: the run still renders with the bytes stored at submit, and `corelata export` writes them beside the trace so `corelata report DIR --format docx` uses them without `--docx-reference`. (Task 5, Task 6, Task 9.)
5. `CORELATA_DATABASE_URL` unset, malformed, pointing at a host that never answers, or at an unmigrated database: every command that needs the database says so in one line within the connect timeout, without the password, and tells the operator to run `corelata migrate` where that is the fix. (Task 1, Task 8, Task 9.)
6. Model output containing NUL characters: rows are written with the NUL stripped instead of the transaction failing. (Task 2.)

---

## File structure

| Path | Responsibility |
|---|---|
| `engine/pyproject.toml` (modify) | the four dependencies; hatch artifacts for `*.sql` and `*.mako` |
| `engine/corelata/store/__init__.py`, `db.py`, `migrate.py` (new, copied) | URL handling, async engine, `Database`; Alembic programmatic config, `upgrade`, `migration_state`, `ensure_migrated` |
| `engine/corelata/store/migrations/env.py`, `script.py.mako`, `versions/0001_job_queue.py`, `versions/0001_procrastinate_3_10_0.sql` (new) | Alembic environment; revision 0001 installs procrastinate's vendored schema |
| `engine/corelata/store/models.py`, `versions/0002_corelata_schema.py` (new) | spec §8.3 tables as SQLAlchemy models; revision 0002 creates them |
| `engine/corelata/store/runs.py` (new) | data access: projects, sources + units, runs, run sources, stage results, drafts, findings, claims, model calls, exports, review events; `NotFoundError` |
| `engine/corelata/store/records.py` (new) | `RunRecord` ⇄ rows: `load_sources`, `load_record`, `save_outcome`, `clear_trace` |
| `engine/corelata/store/discoveries.py` (new) | discovery rows: create, lock, candidates, view |
| `engine/corelata/storage.py` (new, copied) | `Storage` protocol, `LocalStorage`, `safe_filename`, `display_name`, `build_storage` |
| `engine/corelata/pipeline.py` (modify) | `RunObserver`, `NullObserver`, `RunCancelled`, `run_report(observer=)`, `RunOptions.parent_run_id` |
| `engine/corelata/schema/run.py`, `schema/progress.py`, `schema/doctor.py`, `schema/__init__.py`, `schema/export.py` (modify/new) | `RunRecord.parent_run_id`, `RunRecord.extra_guidance`; `RunProgress`, `DiscoveryState`, `DiscoveryView`; `CheckStatus`, `DoctorCheck`, `DoctorReport`; exported schemas |
| `engine/corelata/exports.py` (new, moved out of `cli.py`) | `render_outputs`, `write_outputs`, `DocxExportError`, `OUTPUT_FILES`, `REPORT_FORMATS` |
| `engine/corelata/service.py` (new) | control plane: projects, `add_source`, `start_run`, `cancel_run`, `review_run`, `run_progress`, `get_run_record`, `start_discovery`, `get_discovery`; `JobQueue` protocol; error types |
| `engine/corelata/worker/__init__.py`, `execute.py`, `app.py` (new; `app.py` copied) | `WorkerServices`, `DbObserver`, `execute_run`, `execute_discovery`, `run_job`; procrastinate app, tasks, `requeue_stalled`, `open_app`, `ProcrastinateQueue`, `run_worker` (burst and long-running) |
| `engine/corelata/logs.py` (new, copied) | JSON logging for the worker |
| `engine/corelata/doctor.py` (new) | `run_doctor`: config, prompts, pack, backends and models, database, storage |
| `engine/corelata/cli_ops.py` (new), `cli.py` (modify) | `migrate`, `worker`, `ingest`, `status`, `cancel`, `review`, `export`, `doctor`; `run`/`discover` with `--project` queue instead of executing; `report` picks up `reference.docx` |
| `engine/corelata/testing/postgres.py`, `pytest_db.py`, `queue.py` (new, copied) | throwaway test databases; `pg_admin`/`pg_url`/`db` fixtures; `RecordingQueue` |
| `deploy/compose.dev.yaml` (new), `Makefile`, `.github/workflows/ci.yml` (modify) | dev Postgres on 127.0.0.1:55433; `db-up`/`db-down`; CI Postgres service |
| `engine/tests/test_boundary.py`, `tests/store/*`, `tests/test_storage.py`, `tests/test_service.py`, `tests/worker/*`, `tests/test_cli_ops.py`, `tests/test_doctor.py` (new); `tests/conftest.py`, `tests/test_pipeline.py`, `tests/test_cli.py`, `tests/schema/test_export.py` (modify) | tests |
| `schema/*.schema.json` (regenerate), `docs/trace-format.md`, `docs/m3-followups.md`, `docs/m2-followups.md`, `README.md`, `engine/corelata.example.yaml`, spec §8.3 (modify) | documentation |

---

### Task 1: Dependencies, database core, job-queue migration, Postgres test plugin, CI

**Files:**
- Modify: `engine/pyproject.toml`
- Create: `engine/corelata/store/__init__.py`
- Create: `engine/corelata/store/db.py`
- Create: `engine/corelata/store/migrate.py`
- Create: `engine/corelata/store/models.py` (the `Base` and the two safe column types only; tables come in Task 2)
- Create: `engine/corelata/store/migrations/env.py`
- Create: `engine/corelata/store/migrations/script.py.mako`
- Create: `engine/corelata/store/migrations/versions/0001_job_queue.py`
- Create: `engine/corelata/store/migrations/versions/0001_procrastinate_3_10_0.sql` (copied verbatim)
- Create: `engine/corelata/testing/postgres.py`
- Create: `engine/corelata/testing/pytest_db.py`
- Create: `deploy/compose.dev.yaml`
- Modify: `Makefile`, `.github/workflows/ci.yml`
- Modify: `engine/tests/conftest.py` (add `pytest_plugins`)
- Create: `engine/tests/test_boundary.py`, `engine/tests/store/__init__.py`, `engine/tests/store/test_db.py`, `engine/tests/store/test_migrations.py`

**Interfaces:**
- Consumes: `CorelataConfig.database.url()`, `ConfigError` (`corelata/config.py`).
- Produces: `store.db.Database(url)` with `.engine`, `.sessions`, `.session()`, `.ping()`, `.dispose()`, `.url`; `to_sqlalchemy_url`, `to_libpq_url`, `redact`, `error_reason`, `database_url(cfg)`, `CONNECT_ARGS`; `store.migrate.upgrade(url, revision="head")`, `downgrade(url, revision="base")`, `migration_state(url) -> MigrationState(current, head, up_to_date)`, `ensure_migrated(url)`, `connect_error(url, e)`, `MIGRATIONS_DIR`; `store.models.Base`, `Json`, `JsonList`, `SafeText`, `SafeJSONB`, `utcnow`, `strip_nul`; test fixtures `pg_admin`, `pg_url`, `db`; `testing.postgres.TEST_DB_ENV`, `create_test_database`, `drop_test_database`, `truncate_all`, `PROCRASTINATE_TABLES`.

- [ ] **Step 1: Add the dependencies and packaging artifacts**

In `engine/pyproject.toml`, extend `dependencies` and the hatch artifacts:

```toml
dependencies = [
  "pydantic>=2.9,<3",
  "httpx>=0.27,<1",
  "pyyaml>=6.0",
  "jinja2>=3.1",
  "python-docx>=1.2,<2",
  "lxml>=5.2,<7",
  "pdfminer.six>=20240706",
  "sqlalchemy[asyncio]>=2.0.36,<3",
  "alembic>=1.14,<2",
  "psycopg[binary]>=3.2,<4",
  "procrastinate>=3.10,<3.11",
]
```

```toml
[tool.hatch.build.targets.wheel]
packages = ["corelata"]
artifacts = [
  "corelata/standards/packs/**/*.yaml",
  "corelata/prompts/templates/**/*.j2",
  "corelata/render/templates/**/*.j2",
  "corelata/ingest/vendor/*.json",
  "corelata/store/migrations/versions/*.sql",
  "corelata/store/migrations/script.py.mako",
]
```

Run: `uv sync --all-groups` (updates `engine/uv.lock`; commit it with this task).

- [ ] **Step 2: Start the development database**

Create `deploy/compose.dev.yaml` (port 55433: Coglossa's dev database already uses 55432 on this machine):

```yaml
# Development and test database only; the deployable compose file arrives in M5.
name: corelata-dev
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: corelata
      POSTGRES_PASSWORD: corelata
      POSTGRES_DB: corelata
    ports: ["127.0.0.1:55433:5432"]
    tmpfs: [/var/lib/postgresql/data]  # throwaway: tests create and drop their own databases
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U corelata"]
      interval: 2s
      timeout: 3s
      retries: 30
```

Replace the `Makefile`:

```make
.PHONY: test test-engine lint fmt schema db-up db-down

DB_URL ?= postgresql://corelata:corelata@127.0.0.1:55433/postgres
COMPOSE_DEV = docker compose -f deploy/compose.dev.yaml

test: test-engine

test-engine: db-up
	cd engine && CORELATA_TEST_DATABASE_URL=$${CORELATA_TEST_DATABASE_URL:-$(DB_URL)} uv run pytest

db-up:
	$(COMPOSE_DEV) up -d --wait postgres

db-down:
	$(COMPOSE_DEV) down

lint:
	cd engine && uv run ruff check . && uv run ruff format --check .

fmt:
	cd engine && uv run ruff format . && uv run ruff check --fix .

schema:
	cd engine && uv run python -m corelata.schema.export ../schema
```

Run from the repository root: `make db-up`. Then, for every `uv run pytest` in this plan, export once per shell:

```bash
export CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres
```

Add the Postgres service to `.github/workflows/ci.yml`:

```yaml
name: ci
on:
  push:
    branches: [main]
  pull_request:
jobs:
  engine:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_USER: corelata
          POSTGRES_PASSWORD: corelata
          POSTGRES_DB: corelata
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U corelata"
          --health-interval 2s --health-timeout 3s --health-retries 30
    env:
      CORELATA_TEST_DATABASE_URL: postgresql://corelata:corelata@127.0.0.1:5432/postgres
    defaults:
      run:
        working-directory: engine
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with:
          python-version: "3.12"
      - run: uv sync --all-groups
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run pytest
```

- [ ] **Step 3: Write the failing tests for URL handling and migrations**

`engine/tests/store/__init__.py`: empty file.

`engine/tests/store/test_db.py`:

```python
import pytest

from corelata.config import ConfigError
from corelata.store.db import (
    Database,
    database_url,
    error_reason,
    redact,
    to_libpq_url,
    to_sqlalchemy_url,
)
from tests.conftest import build_config


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("postgresql://u:p@h:5432/d", "postgresql+psycopg://u:p@h:5432/d"),
        ("postgres://u:p@h/d", "postgresql+psycopg://u:p@h/d"),
        ("postgresql+psycopg://u:p@h/d", "postgresql+psycopg://u:p@h/d"),
    ],
)
def test_to_sqlalchemy_url(url, expected):
    assert to_sqlalchemy_url(url) == expected


def test_to_libpq_url():
    assert to_libpq_url("postgresql+psycopg://u:p@h/d") == "postgresql://u:p@h/d"


@pytest.mark.parametrize("url", ["mysql://u:p@h/d", "not a url", "sqlite:///x.db"])
def test_non_postgres_urls_are_rejected(url):
    with pytest.raises(ConfigError, match="postgresql://"):
        to_sqlalchemy_url(url)


@pytest.mark.parametrize(
    "url", ["postgresql://u:secret@h:abc/d", "postgresql://u:secret@[::1/d", "not a url"]
)
def test_malformed_urls_are_a_config_error_without_the_password(url):
    with pytest.raises(ConfigError, match="invalid database URL") as caught:
        to_sqlalchemy_url(url)
    assert "secret" not in str(caught.value) and caught.value.__cause__ is None


def test_redact_hides_the_password():
    assert redact("postgresql://u:secret@h/d") == "postgresql://u:***@h/d"


def test_database_url(monkeypatch):
    cfg = build_config()
    monkeypatch.delenv("CORELATA_DATABASE_URL", raising=False)
    with pytest.raises(ConfigError, match="set CORELATA_DATABASE_URL"):
        database_url(cfg)
    monkeypatch.setenv("CORELATA_DATABASE_URL", "mysql://x")
    with pytest.raises(ConfigError, match="postgresql://"):
        database_url(cfg)
    monkeypatch.setenv("CORELATA_DATABASE_URL", "postgresql://u:p@h/d")
    assert database_url(cfg) == "postgresql://u:p@h/d"


async def test_ping(db):
    await db.ping()


async def test_ping_fails_cleanly_for_an_unreachable_server():
    from sqlalchemy.exc import OperationalError

    database = Database("postgresql://u:p@127.0.0.1:9/nowhere")
    with pytest.raises(OperationalError):
        await database.ping()
    await database.dispose()


def test_error_reason_is_the_first_line_of_the_driver_error():
    from sqlalchemy.exc import OperationalError

    orig = Exception("  connection refused\n\tIs the server running?\n")
    assert error_reason(OperationalError("SELECT 1", {}, orig)) == "connection refused"
    assert error_reason(ValueError("plain\nsecond")) == "plain"
    assert error_reason(ValueError()) == "ValueError"


@pytest.fixture
def silent_server():
    """A TCP port that completes the handshake and then never answers, like a black-holed
    database host: without a connect timeout a client waits for the OS TCP timeout or longer."""
    import socket

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(8)
    yield f"postgresql://u:p@127.0.0.1:{sock.getsockname()[1]}/d"
    sock.close()


@pytest.fixture
def short_connect_timeout(monkeypatch):
    from corelata.store import db as db_module
    from corelata.store import migrate

    short = {"connect_timeout": 2}  # libpq's minimum
    monkeypatch.setattr(db_module, "CONNECT_ARGS", short)
    monkeypatch.setattr(migrate, "CONNECT_ARGS", short)


def test_connections_have_a_connect_timeout():
    from corelata.store.db import CONNECT_ARGS

    assert CONNECT_ARGS == {"connect_timeout": 10}


async def test_the_database_gives_up_on_a_silent_host(silent_server, short_connect_timeout):
    import asyncio

    from sqlalchemy.exc import OperationalError

    database = Database(silent_server)
    with pytest.raises(OperationalError, match="timeout"):
        await asyncio.wait_for(database.ping(), 15)
    await database.dispose()


async def test_the_migration_check_gives_up_on_a_silent_host(silent_server, short_connect_timeout):
    import asyncio

    from corelata.store.migrate import ensure_migrated

    with pytest.raises(ConfigError, match="cannot connect to the database.*timeout"):
        await asyncio.wait_for(asyncio.to_thread(ensure_migrated, silent_server), 15)
```

`engine/tests/store/test_migrations.py` (Task 2 extends `OUR_TABLES` and the head revision; in this task the head is `"0001"` and there are no tables of our own yet):

```python
from procrastinate.schema import SchemaManager
from sqlalchemy import create_engine, inspect
from sqlalchemy.pool import NullPool

from corelata.store.db import to_sqlalchemy_url
from corelata.store.migrate import MIGRATIONS_DIR, downgrade, migration_state, upgrade
from corelata.store.models import Base
from corelata.testing.postgres import PROCRASTINATE_TABLES, create_test_database, drop_test_database

OUR_TABLES: set[str] = set()
HEAD = "0001"


def _tables(url):
    engine = create_engine(to_sqlalchemy_url(url), poolclass=NullPool)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_vendored_procrastinate_schema_matches_the_installed_package():
    vendored = MIGRATIONS_DIR / "versions" / "0001_procrastinate_3_10_0.sql"
    assert vendored.read_text(encoding="utf-8") == SchemaManager.get_schema(), (
        "the installed procrastinate's schema differs from the one revision 0001 installs: "
        "add a new Alembic revision that applies procrastinate's migration SQL"
    )


def test_upgrade_creates_our_tables_and_the_job_queue(pg_url):
    tables = _tables(pg_url)
    assert tables >= OUR_TABLES
    assert set(PROCRASTINATE_TABLES) <= tables
    assert set(Base.metadata.tables) == OUR_TABLES


def test_migration_state_is_current(pg_url):
    state = migration_state(pg_url)
    assert state.current == state.head == HEAD
    assert state.up_to_date


def test_downgrade_then_upgrade_again(pg_admin):
    url = create_test_database(pg_admin)
    try:
        empty = migration_state(url)
        assert empty.current is None and not empty.up_to_date
        upgrade(url)
        downgrade(url)
        assert not (_tables(url) & (OUR_TABLES | set(PROCRASTINATE_TABLES)))
        upgrade(url)
        assert migration_state(url).up_to_date
    finally:
        drop_test_database(pg_admin, url)
```

`engine/tests/test_boundary.py`:

```python
"""Spec §4.2: the engine library has no knowledge of the database."""

import pkgutil
import subprocess
import sys

import corelata

# Modules that may use the database; everything else in corelata is library code.
DATABASE_MODULES = (
    "corelata.store",
    "corelata.service",
    "corelata.worker",
    "corelata.doctor",
    "corelata.cli_ops",
    "corelata.cli",  # imports cli_ops
    "corelata.testing.postgres",
    "corelata.testing.pytest_db",
)


def _is_database_module(name: str) -> bool:
    return any(name == d or name.startswith(d + ".") for d in DATABASE_MODULES)


LIBRARY = sorted(
    m.name
    for m in pkgutil.walk_packages(corelata.__path__, "corelata.")
    if not _is_database_module(m.name)
)
FORBIDDEN = ("sqlalchemy", "alembic", "psycopg", "procrastinate")


def test_library_modules_do_not_import_database_packages():
    code = (
        "import importlib, sys\n"
        f"for m in {LIBRARY!r}: importlib.import_module(m)\n"
        f"bad = sorted(m for m in sys.modules if m.split('.')[0] in {FORBIDDEN!r})\n"
        "print(','.join(bad))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "", f"library imports database packages: {result.stdout}"


def test_discovery_finds_the_library():
    for name in ("corelata.render.docx", "corelata.ingest.pdf", "corelata.pipeline"):
        assert name in LIBRARY
    assert "corelata.store.db" not in LIBRARY
```

Add to the top of `engine/tests/conftest.py`, after the imports:

```python
pytest_plugins = ["corelata.testing.pytest_db"]
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `uv run pytest tests/store tests/test_boundary.py -v --no-cov`
Expected: FAIL / ERROR with `ModuleNotFoundError: No module named 'corelata.store'` and the plugin import error.

- [ ] **Step 5: Copy and rename the database core**

`engine/corelata/store/__init__.py`:

```python
"""Persistence (spec §8.3): Postgres tables, migrations and data access. The engine library
(ingest, stages, pipeline, render) never imports this package."""
```

`engine/corelata/store/db.py`:

```python
"""Database URLs and the async engine (SQLAlchemy 2 + psycopg 3). Copied from Coglossa."""

from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from corelata.config import ConfigError, CorelataConfig

_EXAMPLE = "postgresql://user:password@host:5432/corelata"
# Without a connect timeout a firewalled host hangs every command for the OS TCP timeout.
CONNECT_TIMEOUT_S = 10
CONNECT_ARGS = {"connect_timeout": CONNECT_TIMEOUT_S}  # psycopg/libpq connection parameter


def _parse(url: str) -> URL:
    try:
        parsed = make_url(url)
    except (ArgumentError, ValueError):  # ValueError: a non-numeric port
        # never echo the URL or the parser's message: either can contain the password
        raise ConfigError(f"invalid database URL; expected {_EXAMPLE}") from None
    if parsed.drivername.split("+")[0] not in ("postgresql", "postgres"):
        raise ConfigError(f"unsupported database '{parsed.drivername}'; expected {_EXAMPLE}")
    return parsed


def to_sqlalchemy_url(url: str) -> str:
    return _parse(url).set(drivername="postgresql+psycopg").render_as_string(hide_password=False)


def to_libpq_url(url: str) -> str:
    return _parse(url).set(drivername="postgresql").render_as_string(hide_password=False)


def redact(url: str) -> str:
    return _parse(url).render_as_string(hide_password=True)


def error_reason(e: BaseException) -> str:
    """One line for a user: the driver's message (SQLAlchemy wraps it in `orig`)."""
    original = getattr(e, "orig", None) or e
    lines = str(original).strip().splitlines()
    return lines[0] if lines else type(original).__name__


def database_url(cfg: CorelataConfig) -> str:
    url = cfg.database.url()
    if url is None:
        raise ConfigError(f"no database configured: set {cfg.database.url_env} to {_EXAMPLE}")
    _parse(url)
    return url


class Database:
    def __init__(self, url: str) -> None:
        self.url = url
        self.engine: AsyncEngine = create_async_engine(
            to_sqlalchemy_url(url), pool_pre_ping=True, connect_args=dict(CONNECT_ARGS)
        )
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    def session(self) -> AsyncSession:
        return self.sessions()

    async def ping(self) -> None:
        async with self.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    async def dispose(self) -> None:
        await self.engine.dispose()
```

`engine/corelata/store/migrate.py`:

```python
"""Schema migrations (spec §8.3: Alembic). Revision 0001 installs procrastinate's job-queue
schema, revision 0002 the Corelata tables; a procrastinate upgrade needs a new revision that
applies its migration SQL. Copied from Coglossa."""

from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.pool import NullPool

from corelata.config import ConfigError
from corelata.store.db import CONNECT_ARGS, error_reason, redact, to_sqlalchemy_url

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def alembic_config(url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.attributes["url"] = to_sqlalchemy_url(url)  # attributes avoid ConfigParser '%' escaping
    return cfg


def upgrade(url: str, revision: str = "head") -> None:
    command.upgrade(alembic_config(url), revision)


def downgrade(url: str, revision: str = "base") -> None:
    command.downgrade(alembic_config(url), revision)


@dataclass(frozen=True)
class MigrationState:
    current: str | None
    head: str

    @property
    def up_to_date(self) -> bool:
        return self.current == self.head


def migration_state(url: str) -> MigrationState:
    head = ScriptDirectory.from_config(alembic_config(url)).get_current_head()
    engine = create_engine(
        to_sqlalchemy_url(url), poolclass=NullPool, connect_args=dict(CONNECT_ARGS)
    )
    try:
        with engine.connect() as conn:
            current = MigrationContext.configure(conn).get_current_revision()
    finally:
        engine.dispose()
    return MigrationState(current=current, head=head or "")


def connect_error(url: str, e: BaseException) -> ConfigError:
    return ConfigError(f"cannot connect to the database at {redact(url)}: {error_reason(e)}")


def ensure_migrated(url: str) -> None:
    """Refuse, with one line, a database that is unreachable or not at the head revision."""
    try:
        state = migration_state(url)
    except (OperationalError, InterfaceError) as e:
        raise connect_error(url, e) from e
    if not state.up_to_date:
        raise ConfigError(
            f"the database schema is at revision {state.current or 'none'} but this version "
            f"needs {state.head}: run `corelata migrate`"
        )
```

`engine/corelata/store/models.py` (Task 2 appends the tables below `Base`):

```python
"""Postgres schema (spec §8.3). JSONB columns hold Pydantic models dumped with mode="json";
their shapes are the exported schemas in schema/. Rows cascade from their project, so deleting
a project deletes everything that belongs to it. Copied from Coglossa; tables are Corelata's."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Dialect, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

Json = dict[str, Any]
JsonList = list[Any]


def utcnow() -> datetime:
    return datetime.now(UTC)


def strip_nul(value: Any) -> Any:
    """Postgres rejects NUL characters in text and jsonb values, and model output can contain
    them; every string written through these types loses its NUL characters instead of failing
    the transaction. Dict keys and nested lists are cleaned too."""
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, dict):
        return {strip_nul(k): strip_nul(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [strip_nul(v) for v in value]
    return value


class SafeText(TypeDecorator[str]):
    """TEXT that drops NUL characters on write (see strip_nul)."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: Dialect) -> str | None:
        return strip_nul(value)


class SafeJSONB(TypeDecorator[Any]):
    """JSONB that drops NUL characters from every string inside the value on write."""

    impl = JSONB
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Dialect) -> Any:
        return strip_nul(value)


class Base(DeclarativeBase):
    type_annotation_map = {
        Json: SafeJSONB,
        JsonList: SafeJSONB,
        datetime: TIMESTAMP(timezone=True),
        uuid.UUID: UUID(as_uuid=True),
        str: SafeText,
    }


def _cascade(target: str, **kwargs: Any) -> Any:
    return mapped_column(ForeignKey(target, ondelete="CASCADE"), **kwargs)
```

(`_cascade` is unused until Task 2; ruff does not flag unused module-level functions.)

`engine/corelata/store/migrations/env.py`:

```python
"""Alembic environment: online migrations against the URL corelata.store.migrate passes in."""

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from corelata.store.db import CONNECT_ARGS
from corelata.store.models import Base


def _ours(name: str | None, type_: str, parent_names: object) -> bool:
    # procrastinate's tables share the database; autogenerate must never touch them
    return type_ != "table" or name in Base.metadata.tables


engine = create_engine(
    context.config.attributes["url"], poolclass=NullPool, connect_args=dict(CONNECT_ARGS)
)
with engine.connect() as connection:
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        include_name=_ours,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()
engine.dispose()
```

`engine/corelata/store/migrations/script.py.mako` (Alembic's template; revisions committed in this repo are hand-edited to `collections.abc.Sequence` and `str | Sequence[str] | None`, which ruff accepts):

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

# revision identifiers, used by Alembic.
revision: str = ${repr(up_revision)}
down_revision: Union[str, Sequence[str], None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    """Upgrade schema."""
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    """Downgrade schema."""
    ${downgrades if downgrades else "pass"}
```

Copy the vendored procrastinate schema verbatim:

```bash
mkdir -p corelata/store/migrations/versions
cp ~/Downloads/coglossa/engine/coglossa/store/migrations/versions/0001_procrastinate_3_10_0.sql corelata/store/migrations/versions/0001_procrastinate_3_10_0.sql
```

(`test_vendored_procrastinate_schema_matches_the_installed_package` proves the copy equals `SchemaManager.get_schema()` for the installed 3.10.x; if it does not, regenerate the file with `uv run python -c "from procrastinate.schema import SchemaManager; print(SchemaManager.get_schema(), end='')" > corelata/store/migrations/versions/0001_procrastinate_3_10_0.sql`.)

`engine/corelata/store/migrations/versions/0001_job_queue.py`:

```python
"""procrastinate job queue

Revision ID: 0001
Revises:
Create Date: 2026-10-13 12:00:00.000000

"""

from collections.abc import Sequence
from pathlib import Path

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# procrastinate 3.10.0's schema.sql, vendored verbatim so this revision never changes. A
# procrastinate upgrade needs a new revision that applies its migration SQL
# (tests/store/test_migrations.py fails when the installed schema differs from this file).
_PROCRASTINATE_SCHEMA = Path(__file__).with_name("0001_procrastinate_3_10_0.sql")

_DROP_PROCRASTINATE = """
DROP TABLE IF EXISTS procrastinate_events, procrastinate_periodic_defers, procrastinate_jobs,
    procrastinate_workers CASCADE;
DO $$
DECLARE r record;
BEGIN
    FOR r IN SELECT oid::regprocedure AS fn FROM pg_proc WHERE proname LIKE 'procrastinate%' LOOP
        EXECUTE 'DROP FUNCTION IF EXISTS ' || r.fn || ' CASCADE';
    END LOOP;
END $$;
DROP TYPE IF EXISTS procrastinate_job_status, procrastinate_job_event_type,
    procrastinate_job_to_defer_v1 CASCADE;
"""


def _raw(sql: str) -> None:
    # The raw psycopg connection: this SQL contains '%' that SQLAlchemy would read as
    # placeholders. It runs inside the migration's transaction.
    op.get_bind().connection.driver_connection.execute(sql)


def upgrade() -> None:
    """Install procrastinate's job queue (spec §4.1, §8.3)."""
    _raw(_PROCRASTINATE_SCHEMA.read_text(encoding="utf-8"))


def downgrade() -> None:
    """Remove the job queue."""
    _raw(_DROP_PROCRASTINATE)
```

- [ ] **Step 6: Copy the Postgres test plugin**

`engine/corelata/testing/postgres.py`:

```python
"""Throwaway Postgres databases for tests. A test session creates one database from the admin
URL in CORELATA_TEST_DATABASE_URL, migrates it and drops it at the end; `truncate_all` empties
it between tests. Copied from Coglossa."""

import uuid

import psycopg
from psycopg import sql
from sqlalchemy import text
from sqlalchemy.engine import make_url

from corelata.store.db import Database, to_libpq_url
from corelata.store.models import Base

TEST_DB_ENV = "CORELATA_TEST_DATABASE_URL"
PROCRASTINATE_TABLES = (
    "procrastinate_events",
    "procrastinate_periodic_defers",
    "procrastinate_jobs",
    "procrastinate_workers",
)


def create_test_database(admin: str) -> str:
    name = f"corelata_test_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(to_libpq_url(admin), autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    return make_url(admin).set(database=name).render_as_string(hide_password=False)


def drop_test_database(admin: str, url: str) -> None:
    name = make_url(url).database
    with psycopg.connect(to_libpq_url(admin), autocommit=True) as conn:
        conn.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
        )


async def truncate_all(db: Database) -> None:
    tables = [t.name for t in Base.metadata.sorted_tables] + list(PROCRASTINATE_TABLES)
    async with db.engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"))
```

`engine/corelata/testing/pytest_db.py` (one divergence from Coglossa, tagged **backport** in Task 11: the database is dropped even when `upgrade` raises):

```python
"""Pytest plugin with the Postgres fixtures shared by the engine (and later API) test suites;
load it with `pytest_plugins = ["corelata.testing.pytest_db"]`. The database imports stay
inside the fixtures so tests that need no database never import SQLAlchemy or psycopg."""

import os
from collections.abc import AsyncIterator, Iterator
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from corelata.store.db import Database


@pytest.fixture(scope="session")
def pg_admin() -> str:
    from corelata.testing.postgres import TEST_DB_ENV

    admin = os.environ.get(TEST_DB_ENV)
    if not admin:
        pytest.fail(
            f"{TEST_DB_ENV} is not set. Start Postgres with `make db-up` and set "
            f"{TEST_DB_ENV}=postgresql://corelata:corelata@127.0.0.1:55433/postgres "
            "(`make test-engine` does both).",
            pytrace=False,
        )
    return admin


@pytest.fixture(scope="session")
def pg_url(pg_admin) -> Iterator[str]:
    from corelata.store.migrate import upgrade
    from corelata.testing.postgres import create_test_database, drop_test_database

    url = create_test_database(pg_admin)
    try:
        upgrade(url)
        yield url
    finally:
        drop_test_database(pg_admin, url)


@pytest.fixture
async def db(pg_url) -> AsyncIterator["Database"]:
    from corelata.store.db import Database
    from corelata.testing.postgres import truncate_all

    database = Database(pg_url)
    await truncate_all(database)
    yield database
    await database.dispose()
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/store tests/test_boundary.py -v --no-cov`
Expected: PASS (13 tests in `test_db.py`, 4 in `test_migrations.py`, 2 in `test_boundary.py`).

Run: `uv run pytest` (whole suite with coverage) and `uv run ruff check . && uv run ruff format --check .`
Expected: PASS, coverage ≥ 95%, lint clean. (`store/migrations/env.py` runs inside Alembic's subprocess-free import, so it is covered by `pg_url`; if `script.py.mako` or `versions/*.sql` confuse coverage they are not `.py` files and are ignored.)

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml uv.lock corelata/store corelata/testing/postgres.py corelata/testing/pytest_db.py tests/conftest.py tests/store tests/test_boundary.py ../deploy/compose.dev.yaml ../Makefile ../.github/workflows/ci.yml
git commit -m "build: database core, job-queue migration and Postgres test plugin (M3 Task 1)"
```

---

### Task 2: Tables, revision 0002 and row-level data access

**Files:**
- Modify: `engine/corelata/store/models.py` (append the tables)
- Create: `engine/corelata/store/migrations/versions/0002_corelata_schema.py`
- Create: `engine/corelata/store/runs.py`
- Modify: `engine/tests/store/test_migrations.py`
- Create: `engine/tests/store/test_runs.py`

**Interfaces:**
- Consumes: `Base`, `_cascade`, `Json`, `JsonList`, `utcnow` (Task 1); pydantic models `Source`, `SourceUnit`, `StageResult`, `DraftRecord`, `Finding`, `LLMCallRecord`, `Report`, `TERMINAL_STATES` (`corelata.schema`).
- Produces: ORM classes `Project`, `SourceRow`, `SourceUnitRow`, `Run`, `RunSource`, `StageResultRow`, `DraftRow`, `ClaimRow`, `ClaimEvidenceRow`, `AuditFindingRow`, `LLMCall`, `ExportRow`, `ReviewEvent`, `Discovery`, `DiscoverySource`, `DiscoveryCandidate`; `store.runs` functions listed in Step 3 and `NotFoundError`. Every function takes an `AsyncSession` and never commits.

- [ ] **Step 1: Write the failing tests**

Replace the two constants at the top of `engine/tests/store/test_migrations.py` and add the two tests below:

```python
OUR_TABLES = {
    "project",
    "source",
    "source_unit",
    "run",
    "run_source",
    "stage_result",
    "draft",
    "claim",
    "claim_evidence",
    "audit_finding",
    "llm_call",
    "export",
    "review_event",
    "discovery",
    "discovery_source",
    "discovery_candidate",
}
HEAD = "0002"
```

```python
def test_models_match_the_migrations(pg_url):
    from alembic.autogenerate import compare_metadata
    from alembic.runtime.migration import MigrationContext

    engine = create_engine(to_sqlalchemy_url(pg_url), poolclass=NullPool)
    try:
        with engine.connect() as conn:
            context = MigrationContext.configure(
                conn,
                opts={
                    "compare_type": True,
                    "include_name": lambda name, type_, _: (
                        type_ != "table" or name in Base.metadata.tables
                    ),
                },
            )
            assert compare_metadata(context, Base.metadata) == []
    finally:
        engine.dispose()


async def test_deleting_a_project_cascades(db):
    import uuid

    from sqlalchemy import select

    from corelata.store.models import (
        AuditFindingRow,
        DraftRow,
        LLMCall,
        Project,
        Run,
        RunSource,
        SourceRow,
        SourceUnitRow,
        StageResultRow,
    )
    from corelata.store.models import utcnow as now

    async with db.session() as s, s.begin():
        project = Project(name="p")
        s.add(project)
        await s.flush()
        src = SourceRow(
            project_id=project.id, kind="file", name="a.txt", format="txt", sha256="x",
            storage_key="k", provenance={},
        )
        s.add(src)
        await s.flush()
        s.add(SourceUnitRow(source_id=src.id, ordinal=1, unit_id="u1", text="t", locator="para 1",
                            kind="paragraph", meta={}))
        run = Run(
            project_id=project.id, value_statement="v", max_iterations=2, config_hash="h",
            config_snapshot={}, pack_name="icd203-base", pack_hash="ph", pack_snapshot={},
            prompt_versions={}, corelata_version="0.1.0",
        )
        s.add(run)
        await s.flush()
        s.add(RunSource(run_id=run.id, ordinal=1, source_id=src.id))
        s.add(StageResultRow(run_id=run.id, ordinal=0, stage="ingesting", iteration=0, ok=True,
                             started_at=now(), finished_at=now()))
        s.add(DraftRow(run_id=run.id, ordinal=0, role="writer", iteration=0, report={}))
        s.add(AuditFindingRow(run_id=run.id, ordinal=0, iteration=0, rule_id="r", verdict="pass",
                              severity="minor", route_to="writer", evidence="e"))
        s.add(LLMCall(run_id=run.id, ordinal=0, stage="gating", role="gate", backend="b",
                      model="m", prompt_id="gate", prompt_version=1, attempt=1, ok=True,
                      latency_ms=1))
    async with db.session() as s, s.begin():
        await s.delete(await s.get(Project, project.id))
    async with db.session() as s:
        for model in (SourceRow, SourceUnitRow, Run, RunSource, StageResultRow, DraftRow,
                      AuditFindingRow, LLMCall):
            assert (await s.scalars(select(model))).all() == []
    assert uuid.UUID(str(project.id))  # ids are UUIDs
```

`engine/tests/store/test_runs.py`:

```python
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from corelata.schema import (
    Claim,
    ClaimKind,
    DraftRecord,
    Finding,
    LLMCallRecord,
    Report,
    ReportBody,
    ReportMetadata,
    StageResult,
    Verdict,
)
from corelata.store import runs
from corelata.store.models import ClaimEvidenceRow, ClaimRow
from corelata.testing.sources import text_source
from tests.render.fixtures import make_report
from tests.stages.conftest import PORT

T0 = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


async def _project_with_source(s, name="p"):
    project = await runs.get_or_create_project(s, name)
    source = text_source("src1", *PORT, name="port.txt")
    row = await runs.add_source(s, project.id, source, storage_key=f"projects/{project.id}/x")
    return project, row


async def _run(s, project, source_rows, **extra):
    base = dict(
        project_id=project.id,
        value_statement="Varna port capacity expansion matters to shippers",
        profile=None,
        max_iterations=2,
        extra_guidance="",
        config_hash="h",
        config_snapshot={},
        pack_name="icd203-base",
        pack_hash="ph",
        pack_snapshot={"name": "icd203-base"},
        prompt_versions={"gate": 1},
        corelata_version="0.1.0",
        docx_reference_key=None,
        parent_run_id=None,
        source_ids=[r.id for r in source_rows],
    )
    return await runs.create_run(s, **{**base, **extra})


async def test_get_or_create_project_is_idempotent(db):
    async with db.session() as s, s.begin():
        a = await runs.get_or_create_project(s, "novel")
        b = await runs.get_or_create_project(s, "novel")
        assert a.id == b.id
        assert [p.name for p in await runs.list_projects(s)] == ["novel"]
        assert (await runs.find_project(s, "novel")).id == a.id
        assert (await runs.get_project(s, a.id)).name == "novel"
        with pytest.raises(runs.NotFoundError, match="not found"):
            await runs.get_project(s, uuid.uuid4())
        with pytest.raises(runs.NotFoundError, match="not found"):
            await runs.find_project(s, "missing")


async def test_source_round_trip_strips_nul(db):
    async with db.session() as s, s.begin():
        project = await runs.get_or_create_project(s, "p")
        source = text_source("src1", "clean", "has\x00nul", name="n.txt")
        row = await runs.add_source(s, project.id, source, storage_key="k")
    async with db.session() as s:
        rows = await runs.list_sources(s, project.id)
        assert [r.id for r in rows] == [row.id]
        loaded = await runs.load_source(s, rows[0], as_id="src7")
        assert loaded.id == "src7" and loaded.name == "n.txt" and loaded.sha256 == source.sha256
        assert [u.text for u in loaded.units] == ["clean", "hasnul"]
        assert [u.id for u in loaded.units] == ["u1", "u2"]
        assert (await runs.get_source(s, row.id)).name == "n.txt"
        with pytest.raises(runs.NotFoundError):
            await runs.get_source(s, uuid.uuid4())


async def test_create_and_get_run_with_sources_in_order(db):
    async with db.session() as s, s.begin():
        project, a = await _project_with_source(s)
        b = await runs.add_source(s, project.id, text_source("x", "b"), storage_key="kb")
        run = await _run(s, project, [b, a])
    async with db.session() as s, s.begin():
        got = await runs.get_run(s, run.id, lock=True)
        assert got.state == "created" and got.attempts == 0 and got.cancel_requested is False
        assert await runs.run_source_ids(s, run.id) == [b.id, a.id]
        assert await runs.cancel_flag(s, run.id) is False
        with pytest.raises(runs.NotFoundError, match="not found"):
            await runs.get_run(s, uuid.uuid4())


async def test_create_run_rejects_a_source_from_another_project(db):
    async with db.session() as s, s.begin():
        project, a = await _project_with_source(s, "p1")
        other, b = await _project_with_source(s, "p2")
        with pytest.raises(runs.NotFoundError, match="not in project"):
            await _run(s, project, [a, b])


async def test_stage_draft_finding_and_call_round_trips(db):
    stage = StageResult(stage="gating", iteration=0, ok=False, error="boom", started_at=T0,
                        finished_at=T0)
    body = ReportBody.model_validate(make_report().model_dump(exclude={"metadata"}))
    draft = DraftRecord(role="writer", iteration=0, report=body)
    finding = Finding(rule_id="icd203.tc.8", verdict=Verdict.FAIL, evidence="e",
                      cited_units=["src1/u1"], claim_ids=["c1"], recommendation="fix",
                      severity="blocking", route_to="writer", iteration=1)
    call = LLMCallRecord(role="gate", backend="fake", model="m", prompt_id="gate",
                         prompt_version=1, attempt=1, ok=True, latency_ms=3, tokens_in=10,
                         tokens_out=5, request={"messages": []}, response="{}")
    async with db.session() as s, s.begin():
        project, src = await _project_with_source(s)
        run = await _run(s, project, [src])
        await runs.add_stage(s, run.id, 0, stage)
        await runs.add_drafts(s, run.id, 0, [draft])
        await runs.add_findings(s, run.id, 0, [finding])
        await runs.add_llm_calls(s, run.id, 0, [call], stage="gating")
        await runs.add_llm_calls(s, run.id, 1, [call.model_copy(update={"attempt": 2})],
                                 stage="gating")
    async with db.session() as s:
        assert await runs.load_stages(s, run.id) == [stage]
        assert await runs.load_drafts(s, run.id) == [draft]
        assert await runs.load_findings(s, run.id) == [finding]
        calls = await runs.load_llm_calls(s, run.id)
        assert [c.attempt for c in calls] == [1, 2] and calls[0] == call


async def test_replace_claims_resolves_sources(db):
    report = make_report()  # one claim, evidence ["src1/u1"]
    async with db.session() as s, s.begin():
        project, src = await _project_with_source(s)
        run = await _run(s, project, [src])
        await runs.replace_claims(s, run.id, report, [src.id])
        await runs.replace_claims(s, run.id, report, [src.id])  # idempotent
    async with db.session() as s:
        claims = (await s.scalars(select(ClaimRow))).all()
        assert sorted(c.claim_id for c in claims) == sorted(c.id for c in report.claims)
        evidence = (await s.scalars(select(ClaimEvidenceRow))).all()
        assert all(e.source_id == src.id for e in evidence)
        assert {e.unit_ref for e in evidence} == {
            ref for c in report.claims for ref in c.evidence
        }


async def test_claim_evidence_for_an_unknown_source_has_no_source_id(db):
    report = Report(
        title="t", handling_marking="UNCLASSIFIED", key_judgments=[], scope_note="",
        sources=[], analysis=[], alternatives=[], gaps_and_indicators=[],
        claims=[Claim(id="c1", text="x", kind=ClaimKind.FACT, evidence=["src9/u1"])],
        metadata=ReportMetadata(pack_name="p", pack_hash="h"),
    )
    async with db.session() as s, s.begin():
        project, src = await _project_with_source(s)
        run = await _run(s, project, [src])
        await runs.replace_claims(s, run.id, report, [src.id])
    async with db.session() as s:
        [e] = (await s.scalars(select(ClaimEvidenceRow))).all()
        assert e.source_id is None and e.unit_ref == "src9/u1" and e.unit_id == "u1"


async def test_exports_review_events_and_clear_trace(db):
    async with db.session() as s, s.begin():
        project, src = await _project_with_source(s)
        run = await _run(s, project, [src])
        child = await _run(s, project, [src], parent_run_id=run.id)
        export = await runs.add_export(s, run.id, "report.md", "runs/x/report.md", b"# hi")
        assert export.size == 4 and len(export.sha256) == 64
        event = await runs.add_review_event(s, run.id, "return", "tighten", "alice", child.id)
        assert event.child_run_id == child.id and event.at.tzinfo is not None
        await runs.add_stage(s, run.id, 0, StageResult(stage="ingesting", iteration=0, ok=True,
                                                       started_at=T0, finished_at=T0))
        await runs.add_llm_calls(
            s, run.id, 0,
            [LLMCallRecord(role="gate", backend="b", model="m", prompt_id="gate",
                           prompt_version=1, attempt=1, ok=True)],
            stage="gating",
        )
    async with db.session() as s, s.begin():
        assert [e.name for e in await runs.list_exports(s, run.id)] == ["report.md"]
        await runs.clear_trace(s, run.id)
    async with db.session() as s:
        assert await runs.load_stages(s, run.id) == []
        assert await runs.load_llm_calls(s, run.id) == []
        assert await runs.list_exports(s, run.id) == []
        assert (await runs.get_run(s, child.id)).parent_run_id == run.id


async def test_delete_project_removes_its_runs(db):
    async with db.session() as s, s.begin():
        project, src = await _project_with_source(s)
        run = await _run(s, project, [src])
    async with db.session() as s, s.begin():
        await runs.delete_project(s, project.id)
    async with db.session() as s:
        with pytest.raises(runs.NotFoundError):
            await runs.get_run(s, run.id)
```

(`tests.render.fixtures.make_report` exists from M2 and returns a `ReportBody` whose claims cite `src1/u…` refs. If its name differs, use the fixture report builder that `tests/render/test_markdown.py` imports.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/store -v --no-cov`
Expected: FAIL with `ImportError` (no `corelata.store.runs`, no table classes) and `HEAD` mismatch.

- [ ] **Step 3: Append the tables to models.py**

Add these imports at the top of `engine/corelata/store/models.py` (replace the existing `from sqlalchemy import ...` line):

```python
from sqlalchemy import (
    BigInteger,
    Dialect,
    ForeignKey,
    Identity,
    Text,
    UniqueConstraint,
)
```

Append below `_cascade`:

```python
class Project(Base):
    __tablename__ = "project"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(unique=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class SourceRow(Base):
    """One uploaded file or one imported Coglossa run (spec §3, §5.1). A Coglossa export that
    carries a translation guide gives two rows sharing one stored file."""

    __tablename__ = "source"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = _cascade("project.id", index=True)
    kind: Mapped[str]  # SourceKind
    name: Mapped[str]
    format: Mapped[str]
    sha256: Mapped[str]
    storage_key: Mapped[str]
    provenance: Mapped[Json] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class SourceUnitRow(Base):
    __tablename__ = "source_unit"
    source_id: Mapped[uuid.UUID] = _cascade("source.id", primary_key=True)
    ordinal: Mapped[int] = mapped_column(primary_key=True)
    unit_id: Mapped[str]
    text: Mapped[str]
    locator: Mapped[str]
    kind: Mapped[str]  # BlockKind
    meta: Mapped[Json] = mapped_column(default=dict)


class Run(Base):
    """Spec §8.3. `digests` lives here rather than in stage_result rows (spec §5.4) so the trace
    reads back without parsing stage output; the ingesting stage row still lists what was digested."""

    __tablename__ = "run"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = _cascade("project.id", index=True)
    parent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("run.id", ondelete="SET NULL")
    )
    state: Mapped[str] = mapped_column(default="created", index=True)  # RunState
    status: Mapped[str | None]  # ReportStatus, completed runs only
    value_statement: Mapped[str]
    extra_guidance: Mapped[str] = mapped_column(default="")
    profile: Mapped[str | None]
    max_iterations: Mapped[int]
    iteration: Mapped[int] = mapped_column(default=0)
    config_hash: Mapped[str]
    config_snapshot: Mapped[Json]
    pack_name: Mapped[str]
    pack_hash: Mapped[str]
    pack_snapshot: Mapped[Json]
    prompt_versions: Mapped[Json]
    corelata_version: Mapped[str]
    docx_reference_key: Mapped[str | None]  # the profile's reference document, stored at submit
    gate: Mapped[Json | None]  # GateVerdict
    digests: Mapped[JsonList] = mapped_column(default=list)  # list[Digest]
    report: Mapped[Json | None]  # Report, delivered runs only
    token_usage: Mapped[Json | None]  # Usage, updated after every stage
    cancel_requested: Mapped[bool] = mapped_column(default=False)
    attempts: Mapped[int] = mapped_column(default=0)  # executions the worker started
    error: Mapped[str | None]
    export_error: Mapped[str | None]  # the DOCX export failed after the run completed
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]


class RunSource(Base):
    """The run's sources in order; ordinal n is source id "src<n>" inside the run's trace."""

    __tablename__ = "run_source"
    run_id: Mapped[uuid.UUID] = _cascade("run.id", primary_key=True)
    ordinal: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[uuid.UUID] = _cascade("source.id", index=True)


class StageResultRow(Base):
    """One attempt of one stage (spec §8.3); `ordinal` is its position in the trace."""

    __tablename__ = "stage_result"
    __table_args__ = (UniqueConstraint("run_id", "ordinal"),)
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_id: Mapped[uuid.UUID] = _cascade("run.id", index=True)
    ordinal: Mapped[int]
    stage: Mapped[str]
    iteration: Mapped[int]
    ok: Mapped[bool]
    output: Mapped[Json | None]
    error: Mapped[str | None]
    started_at: Mapped[datetime]
    finished_at: Mapped[datetime]


class DraftRow(Base):
    __tablename__ = "draft"
    __table_args__ = (UniqueConstraint("run_id", "ordinal"),)
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_id: Mapped[uuid.UUID] = _cascade("run.id", index=True)
    ordinal: Mapped[int]
    role: Mapped[str]
    iteration: Mapped[int]
    report: Mapped[Json]  # ReportBody


class ClaimRow(Base):
    """The delivered report's claims (spec §8.3 `claim`); drafts keep theirs in their JSON."""

    __tablename__ = "claim"
    __table_args__ = (UniqueConstraint("run_id", "claim_id"),)
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_id: Mapped[uuid.UUID] = _cascade("run.id", index=True)
    claim_id: Mapped[str]
    text: Mapped[str]
    kind: Mapped[str]
    likelihood_term: Mapped[str | None]


class ClaimEvidenceRow(Base):
    __tablename__ = "claim_evidence"
    claim_pk: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("claim.id", ondelete="CASCADE"), primary_key=True
    )
    ordinal: Mapped[int] = mapped_column(primary_key=True)
    unit_ref: Mapped[str]  # "<source_id>/<unit_id>" as the claim cites it
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("source.id", ondelete="SET NULL")
    )
    unit_id: Mapped[str]


class AuditFindingRow(Base):
    __tablename__ = "audit_finding"
    __table_args__ = (UniqueConstraint("run_id", "ordinal"),)
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_id: Mapped[uuid.UUID] = _cascade("run.id", index=True)
    ordinal: Mapped[int]
    iteration: Mapped[int]
    rule_id: Mapped[str]
    verdict: Mapped[str]
    severity: Mapped[str]
    route_to: Mapped[str]
    evidence: Mapped[str]
    cited_units: Mapped[JsonList] = mapped_column(default=list)
    claim_ids: Mapped[JsonList] = mapped_column(default=list)
    recommendation: Mapped[str] = mapped_column(default="")


class LLMCall(Base):
    __tablename__ = "llm_call"
    __table_args__ = (UniqueConstraint("run_id", "ordinal"),)
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_id: Mapped[uuid.UUID] = _cascade("run.id", index=True)
    ordinal: Mapped[int]
    stage: Mapped[str]  # the run state when the call was made
    role: Mapped[str]
    backend: Mapped[str]
    model: Mapped[str]
    prompt_id: Mapped[str]
    prompt_version: Mapped[int]
    attempt: Mapped[int]
    ok: Mapped[bool]
    latency_ms: Mapped[int]
    tokens_in: Mapped[int | None]
    tokens_out: Mapped[int | None]
    error: Mapped[str | None]
    request: Mapped[Json | None]  # only when audit.store_llm_io
    response: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ExportRow(Base):
    """A file the worker rendered for a finished run and put in storage (spec §7.2, §8.3)."""

    __tablename__ = "export"
    __table_args__ = (UniqueConstraint("run_id", "name"),)
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_id: Mapped[uuid.UUID] = _cascade("run.id", index=True)
    name: Mapped[str]  # trace.json, gate.json, report.json, report.md, report.html, report.docx
    storage_key: Mapped[str]
    sha256: Mapped[str]
    size: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ReviewEvent(Base):
    """Spec §10.1 review actions; a `return` links the run it created."""

    __tablename__ = "review_event"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_id: Mapped[uuid.UUID] = _cascade("run.id", index=True)
    action: Mapped[str]  # accept | return
    note: Mapped[str] = mapped_column(default="")
    actor: Mapped[str | None]
    child_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("run.id", ondelete="SET NULL")
    )
    at: Mapped[datetime] = mapped_column(default=utcnow)


class Discovery(Base):
    """Spec §7.1: a discovery job; its model calls are few, so they live in a JSON column."""

    __tablename__ = "discovery"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = _cascade("project.id", index=True)
    audience_hint: Mapped[str] = mapped_column(default="")
    state: Mapped[str] = mapped_column(default="created", index=True)  # DiscoveryState
    error: Mapped[str | None]
    llm_calls: Mapped[JsonList] = mapped_column(default=list)  # list[LLMCallRecord]
    token_usage: Mapped[Json | None]  # Usage
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]


class DiscoverySource(Base):
    __tablename__ = "discovery_source"
    discovery_id: Mapped[uuid.UUID] = _cascade("discovery.id", primary_key=True)
    ordinal: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[uuid.UUID] = _cascade("source.id", index=True)


class DiscoveryCandidate(Base):
    __tablename__ = "discovery_candidate"
    discovery_id: Mapped[uuid.UUID] = _cascade("discovery.id", primary_key=True)
    ordinal: Mapped[int] = mapped_column(primary_key=True)
    text: Mapped[str]
    audience: Mapped[str]
    evidence: Mapped[JsonList] = mapped_column(default=list)
    confidence_note: Mapped[str] = mapped_column(default="")
```

- [ ] **Step 4: Write revision 0002**

`engine/corelata/store/migrations/versions/0002_corelata_schema.py`:

```python
"""corelata schema (spec §8.3)

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-13 12:00:01.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TS = postgresql.TIMESTAMP(timezone=True)


def _jsonb() -> postgresql.JSONB:
    return postgresql.JSONB(astext_type=sa.Text())


def _identity() -> sa.Column:
    return sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False)


def _run_fk(**kw: object) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["run_id"], ["run.id"], ondelete="CASCADE", **kw)


def upgrade() -> None:
    """Create the Corelata tables."""
    op.create_table(
        "project",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("created_at", _TS, nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "source",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("format", sa.Text(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("provenance", _jsonb(), nullable=False),
        sa.Column("created_at", _TS, nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_source_project_id"), "source", ["project_id"], unique=False)
    op.create_table(
        "source_unit",
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("unit_id", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("locator", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("meta", _jsonb(), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["source.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("source_id", "ordinal"),
    )
    op.create_table(
        "run",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("parent_run_id", sa.UUID(), nullable=True),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("value_statement", sa.Text(), nullable=False),
        sa.Column("extra_guidance", sa.Text(), nullable=False),
        sa.Column("profile", sa.Text(), nullable=True),
        sa.Column("max_iterations", sa.Integer(), nullable=False),
        sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column("config_hash", sa.Text(), nullable=False),
        sa.Column("config_snapshot", _jsonb(), nullable=False),
        sa.Column("pack_name", sa.Text(), nullable=False),
        sa.Column("pack_hash", sa.Text(), nullable=False),
        sa.Column("pack_snapshot", _jsonb(), nullable=False),
        sa.Column("prompt_versions", _jsonb(), nullable=False),
        sa.Column("corelata_version", sa.Text(), nullable=False),
        sa.Column("docx_reference_key", sa.Text(), nullable=True),
        sa.Column("gate", _jsonb(), nullable=True),
        sa.Column("digests", _jsonb(), nullable=False),
        sa.Column("report", _jsonb(), nullable=True),
        sa.Column("token_usage", _jsonb(), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("export_error", sa.Text(), nullable=True),
        sa.Column("created_at", _TS, nullable=False),
        sa.Column("started_at", _TS, nullable=True),
        sa.Column("finished_at", _TS, nullable=True),
        sa.ForeignKeyConstraint(["parent_run_id"], ["run.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_run_project_id"), "run", ["project_id"], unique=False)
    op.create_index(op.f("ix_run_state"), "run", ["state"], unique=False)
    op.create_table(
        "run_source",
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        _run_fk(),
        sa.ForeignKeyConstraint(["source_id"], ["source.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("run_id", "ordinal"),
    )
    op.create_index(op.f("ix_run_source_source_id"), "run_source", ["source_id"], unique=False)
    op.create_table(
        "stage_result",
        _identity(),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("output", _jsonb(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", _TS, nullable=False),
        sa.Column("finished_at", _TS, nullable=False),
        _run_fk(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "ordinal"),
    )
    op.create_index(op.f("ix_stage_result_run_id"), "stage_result", ["run_id"], unique=False)
    op.create_table(
        "draft",
        _identity(),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column("report", _jsonb(), nullable=False),
        _run_fk(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "ordinal"),
    )
    op.create_index(op.f("ix_draft_run_id"), "draft", ["run_id"], unique=False)
    op.create_table(
        "claim",
        _identity(),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("claim_id", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("likelihood_term", sa.Text(), nullable=True),
        _run_fk(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "claim_id"),
    )
    op.create_index(op.f("ix_claim_run_id"), "claim", ["run_id"], unique=False)
    op.create_table(
        "claim_evidence",
        sa.Column("claim_pk", sa.BigInteger(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("unit_ref", sa.Text(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=True),
        sa.Column("unit_id", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["claim_pk"], ["claim.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["source.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("claim_pk", "ordinal"),
    )
    op.create_table(
        "audit_finding",
        _identity(),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column("rule_id", sa.Text(), nullable=False),
        sa.Column("verdict", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("route_to", sa.Text(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("cited_units", _jsonb(), nullable=False),
        sa.Column("claim_ids", _jsonb(), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=False),
        _run_fk(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "ordinal"),
    )
    op.create_index(op.f("ix_audit_finding_run_id"), "audit_finding", ["run_id"], unique=False)
    op.create_table(
        "llm_call",
        _identity(),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("backend", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("prompt_id", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.Integer(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("request", _jsonb(), nullable=True),
        sa.Column("response", sa.Text(), nullable=True),
        sa.Column("created_at", _TS, nullable=False),
        _run_fk(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "ordinal"),
    )
    op.create_index(op.f("ix_llm_call_run_id"), "llm_call", ["run_id"], unique=False)
    op.create_table(
        "export",
        _identity(),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("created_at", _TS, nullable=False),
        _run_fk(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "name"),
    )
    op.create_index(op.f("ix_export_run_id"), "export", ["run_id"], unique=False)
    op.create_table(
        "review_event",
        _identity(),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=True),
        sa.Column("child_run_id", sa.UUID(), nullable=True),
        sa.Column("at", _TS, nullable=False),
        sa.ForeignKeyConstraint(["child_run_id"], ["run.id"], ondelete="SET NULL"),
        _run_fk(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_review_event_run_id"), "review_event", ["run_id"], unique=False)
    op.create_table(
        "discovery",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("audience_hint", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("llm_calls", _jsonb(), nullable=False),
        sa.Column("token_usage", _jsonb(), nullable=True),
        sa.Column("created_at", _TS, nullable=False),
        sa.Column("started_at", _TS, nullable=True),
        sa.Column("finished_at", _TS, nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_discovery_project_id"), "discovery", ["project_id"], unique=False)
    op.create_index(op.f("ix_discovery_state"), "discovery", ["state"], unique=False)
    op.create_table(
        "discovery_source",
        sa.Column("discovery_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["discovery_id"], ["discovery.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["source.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("discovery_id", "ordinal"),
    )
    op.create_index(
        op.f("ix_discovery_source_source_id"), "discovery_source", ["source_id"], unique=False
    )
    op.create_table(
        "discovery_candidate",
        sa.Column("discovery_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("audience", sa.Text(), nullable=False),
        sa.Column("evidence", _jsonb(), nullable=False),
        sa.Column("confidence_note", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["discovery_id"], ["discovery.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("discovery_id", "ordinal"),
    )


_TABLES_REVERSED = (
    "discovery_candidate",
    "discovery_source",
    "discovery",
    "review_event",
    "export",
    "llm_call",
    "audit_finding",
    "claim_evidence",
    "claim",
    "draft",
    "stage_result",
    "run_source",
    "run",
    "source_unit",
    "source",
    "project",
)


def downgrade() -> None:
    """Drop the Corelata tables (indexes go with them)."""
    for name in _TABLES_REVERSED:
        op.drop_table(name)
```

If `test_models_match_the_migrations` reports a difference, fix the revision to match the models (never the other way round) and record the detail in the task report.

- [ ] **Step 5: Write the data-access module**

`engine/corelata/store/runs.py`:

```python
"""Data access for projects, sources, runs and everything a run produces (spec §8.3). Functions
take an AsyncSession and never commit: the caller owns the transaction
(`async with db.session() as s, s.begin(): ...`)."""

import hashlib
import uuid
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from corelata.schema import (
    BlockKind,
    DraftRecord,
    Finding,
    LLMCallRecord,
    Report,
    Source,
    SourceKind,
    SourceUnit,
    StageResult,
    Verdict,
    split_ref,
)
from corelata.store.models import (
    AuditFindingRow,
    ClaimEvidenceRow,
    ClaimRow,
    DraftRow,
    ExportRow,
    LLMCall,
    Project,
    ReviewEvent,
    Run,
    RunSource,
    SourceRow,
    SourceUnitRow,
    StageResultRow,
)

_BATCH = 1000


class NotFoundError(LookupError):
    """A requested row does not exist; the message is safe to show to a user."""


# ---------------------------------------------------------------- projects


async def get_or_create_project(s: AsyncSession, name: str) -> Project:
    await s.execute(
        pg_insert(Project)
        .values(id=uuid.uuid4(), name=name)
        .on_conflict_do_nothing(index_elements=[Project.name])
    )
    return await find_project(s, name)


async def find_project(s: AsyncSession, name: str) -> Project:
    project = await s.scalar(select(Project).where(Project.name == name))
    if project is None:
        raise NotFoundError(f"project '{name}' not found")
    return project


async def get_project(s: AsyncSession, project_id: uuid.UUID) -> Project:
    project = await s.get(Project, project_id)
    if project is None:
        raise NotFoundError(f"project {project_id} not found")
    return project


async def list_projects(s: AsyncSession) -> list[Project]:
    return list(await s.scalars(select(Project).order_by(Project.created_at, Project.name)))


async def delete_project(s: AsyncSession, project_id: uuid.UUID) -> None:
    await s.delete(await get_project(s, project_id))
    await s.flush()


# ---------------------------------------------------------------- sources


async def _insert_many(s: AsyncSession, table: Any, rows: list[dict[str, Any]]) -> None:
    for start in range(0, len(rows), _BATCH):
        await s.execute(pg_insert(table).values(rows[start : start + _BATCH]))


async def add_source(
    s: AsyncSession,
    project_id: uuid.UUID,
    source: Source,
    *,
    storage_key: str,
    source_id: uuid.UUID | None = None,
) -> SourceRow:
    """Store a parsed source and its units. `source.id` (the in-run name) is not kept: a run
    names its sources src1, src2, … by position (see RunSource)."""
    row = SourceRow(
        id=source_id or uuid.uuid4(),
        project_id=project_id,
        kind=source.kind.value,
        name=source.name,
        format=source.format,
        sha256=source.sha256,
        storage_key=storage_key,
        provenance=dict(source.provenance),
    )
    s.add(row)
    await s.flush()
    await _insert_many(
        s,
        SourceUnitRow.__table__,
        [
            {
                "source_id": row.id,
                "ordinal": i,
                "unit_id": u.id,
                "text": u.text.replace("\x00", ""),
                "locator": u.locator,
                "kind": u.kind.value,
                "meta": u.meta,
            }
            for i, u in enumerate(source.units, start=1)
        ],
    )
    return row


async def get_source(s: AsyncSession, source_id: uuid.UUID) -> SourceRow:
    row = await s.get(SourceRow, source_id)
    if row is None:
        raise NotFoundError(f"source {source_id} not found")
    return row


async def list_sources(s: AsyncSession, project_id: uuid.UUID) -> list[SourceRow]:
    return list(
        await s.scalars(
            select(SourceRow)
            .where(SourceRow.project_id == project_id)
            .order_by(SourceRow.created_at, SourceRow.id)
        )
    )


async def load_source(s: AsyncSession, row: SourceRow, *, as_id: str) -> Source:
    units = await s.scalars(
        select(SourceUnitRow)
        .where(SourceUnitRow.source_id == row.id)
        .order_by(SourceUnitRow.ordinal)
    )
    return Source(
        id=as_id,
        kind=SourceKind(row.kind),
        name=row.name,
        format=row.format,
        sha256=row.sha256,
        provenance=dict(row.provenance),
        units=[
            SourceUnit(id=u.unit_id, text=u.text, locator=u.locator, kind=BlockKind(u.kind),
                       meta=dict(u.meta))
            for u in units
        ],
    )


# ---------------------------------------------------------------- runs


async def create_run(
    s: AsyncSession,
    *,
    project_id: uuid.UUID,
    value_statement: str,
    profile: str | None,
    max_iterations: int,
    extra_guidance: str,
    config_hash: str,
    config_snapshot: dict[str, Any],
    pack_name: str,
    pack_hash: str,
    pack_snapshot: dict[str, Any],
    prompt_versions: dict[str, int],
    corelata_version: str,
    docx_reference_key: str | None,
    parent_run_id: uuid.UUID | None,
    source_ids: list[uuid.UUID],
    run_id: uuid.UUID | None = None,
    created_at: datetime | None = None,
) -> Run:
    """A run row plus its ordered sources; every source must belong to the project."""
    rows = {r.id: r for r in await list_sources(s, project_id)}
    for sid in source_ids:
        if sid not in rows:
            raise NotFoundError(f"source {sid} not in project {project_id}")
    run = Run(
        id=run_id or uuid.uuid4(),
        project_id=project_id,
        parent_run_id=parent_run_id,
        value_statement=value_statement,
        extra_guidance=extra_guidance,
        profile=profile,
        max_iterations=max_iterations,
        config_hash=config_hash,
        config_snapshot=config_snapshot,
        pack_name=pack_name,
        pack_hash=pack_hash,
        pack_snapshot=pack_snapshot,
        prompt_versions=prompt_versions,
        corelata_version=corelata_version,
        docx_reference_key=docx_reference_key,
        digests=[],
    )
    if created_at is not None:
        run.created_at = created_at
    s.add(run)
    await s.flush()
    s.add_all(
        RunSource(run_id=run.id, ordinal=i, source_id=sid)
        for i, sid in enumerate(source_ids, start=1)
    )
    await s.flush()
    return run


async def get_run(s: AsyncSession, run_id: uuid.UUID, *, lock: bool = False) -> Run:
    query = select(Run).where(Run.id == run_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    run = await s.scalar(query)
    if run is None:
        raise NotFoundError(f"run {run_id} not found")
    return run


async def run_source_ids(s: AsyncSession, run_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        await s.scalars(
            select(RunSource.source_id)
            .where(RunSource.run_id == run_id)
            .order_by(RunSource.ordinal)
        )
    )


async def cancel_flag(s: AsyncSession, run_id: uuid.UUID) -> bool:
    flag = await s.scalar(select(Run.cancel_requested).where(Run.id == run_id))
    if flag is None:
        raise NotFoundError(f"run {run_id} not found")
    return bool(flag)


# ---------------------------------------------------------------- what a run produces


async def add_stage(s: AsyncSession, run_id: uuid.UUID, ordinal: int, result: StageResult) -> None:
    s.add(StageResultRow(run_id=run_id, ordinal=ordinal, **result.model_dump()))
    await s.flush()


async def load_stages(s: AsyncSession, run_id: uuid.UUID) -> list[StageResult]:
    rows = await s.scalars(
        select(StageResultRow)
        .where(StageResultRow.run_id == run_id)
        .order_by(StageResultRow.ordinal)
    )
    return [
        StageResult(stage=r.stage, iteration=r.iteration, ok=r.ok, output=r.output,
                    error=r.error, started_at=r.started_at, finished_at=r.finished_at)
        for r in rows
    ]


async def add_drafts(
    s: AsyncSession, run_id: uuid.UUID, start: int, drafts: Iterable[DraftRecord]
) -> None:
    s.add_all(
        DraftRow(run_id=run_id, ordinal=start + i, role=d.role, iteration=d.iteration,
                 report=d.report.model_dump(mode="json"))
        for i, d in enumerate(drafts)
    )
    await s.flush()


async def load_drafts(s: AsyncSession, run_id: uuid.UUID) -> list[DraftRecord]:
    rows = await s.scalars(
        select(DraftRow).where(DraftRow.run_id == run_id).order_by(DraftRow.ordinal)
    )
    return [DraftRecord(role=r.role, iteration=r.iteration, report=r.report) for r in rows]


async def add_findings(
    s: AsyncSession, run_id: uuid.UUID, start: int, findings: Iterable[Finding]
) -> None:
    s.add_all(
        AuditFindingRow(
            run_id=run_id,
            ordinal=start + i,
            iteration=f.iteration,
            rule_id=f.rule_id,
            verdict=f.verdict.value,
            severity=f.severity,
            route_to=f.route_to,
            evidence=f.evidence,
            cited_units=list(f.cited_units),
            claim_ids=list(f.claim_ids),
            recommendation=f.recommendation,
        )
        for i, f in enumerate(findings)
    )
    await s.flush()


async def load_findings(s: AsyncSession, run_id: uuid.UUID) -> list[Finding]:
    rows = await s.scalars(
        select(AuditFindingRow)
        .where(AuditFindingRow.run_id == run_id)
        .order_by(AuditFindingRow.ordinal)
    )
    return [
        Finding(
            rule_id=r.rule_id,
            verdict=Verdict(r.verdict),
            evidence=r.evidence,
            cited_units=list(r.cited_units),
            claim_ids=list(r.claim_ids),
            recommendation=r.recommendation,
            severity=r.severity,
            route_to=r.route_to,
            iteration=r.iteration,
        )
        for r in rows
    ]


async def add_llm_calls(
    s: AsyncSession,
    run_id: uuid.UUID,
    start: int,
    records: Iterable[LLMCallRecord],
    *,
    stage: str,
) -> None:
    s.add_all(
        LLMCall(run_id=run_id, ordinal=start + i, stage=stage, **r.model_dump())
        for i, r in enumerate(records)
    )
    await s.flush()


async def load_llm_calls(s: AsyncSession, run_id: uuid.UUID) -> list[LLMCallRecord]:
    rows = await s.scalars(
        select(LLMCall).where(LLMCall.run_id == run_id).order_by(LLMCall.ordinal)
    )
    return [
        LLMCallRecord(
            role=r.role,
            backend=r.backend,
            model=r.model,
            prompt_id=r.prompt_id,
            prompt_version=r.prompt_version,
            attempt=r.attempt,
            ok=r.ok,
            latency_ms=r.latency_ms,
            tokens_in=r.tokens_in,
            tokens_out=r.tokens_out,
            error=r.error,
            request=r.request,
            response=r.response,
        )
        for r in rows
    ]


async def replace_claims(
    s: AsyncSession, run_id: uuid.UUID, report: Report, source_ids: list[uuid.UUID]
) -> None:
    """Index the delivered report's claims and evidence (spec §8.3 `claim`, `claim_evidence`).
    `source_ids` is the run's sources in order, so "src<n>" resolves to source_ids[n-1]; a ref
    that does not resolve keeps its text and no source id."""
    await s.execute(delete(ClaimRow).where(ClaimRow.run_id == run_id))
    for claim in report.claims:
        row = ClaimRow(
            run_id=run_id,
            claim_id=claim.id,
            text=claim.text,
            kind=claim.kind.value,
            likelihood_term=claim.likelihood_term,
        )
        s.add(row)
        await s.flush()
        for i, ref in enumerate(claim.evidence):
            src, unit = split_ref(ref)
            resolved: uuid.UUID | None = None
            if src.startswith("src") and src[3:].isdigit():
                n = int(src[3:])
                if 1 <= n <= len(source_ids):
                    resolved = source_ids[n - 1]
            s.add(ClaimEvidenceRow(claim_pk=row.id, ordinal=i, unit_ref=ref,
                                   source_id=resolved, unit_id=unit))
    await s.flush()


async def add_export(
    s: AsyncSession, run_id: uuid.UUID, name: str, storage_key: str, data: bytes
) -> ExportRow:
    row = ExportRow(
        run_id=run_id,
        name=name,
        storage_key=storage_key,
        sha256=hashlib.sha256(data).hexdigest(),
        size=len(data),
    )
    s.add(row)
    await s.flush()
    return row


async def list_exports(s: AsyncSession, run_id: uuid.UUID) -> list[ExportRow]:
    return list(
        await s.scalars(
            select(ExportRow).where(ExportRow.run_id == run_id).order_by(ExportRow.name)
        )
    )


async def add_review_event(
    s: AsyncSession,
    run_id: uuid.UUID,
    action: str,
    note: str,
    actor: str | None,
    child_run_id: uuid.UUID | None,
) -> ReviewEvent:
    event = ReviewEvent(run_id=run_id, action=action, note=note, actor=actor,
                        child_run_id=child_run_id)
    s.add(event)
    await s.flush()
    return event


async def clear_trace(s: AsyncSession, run_id: uuid.UUID) -> None:
    """Remove everything an earlier execution of the run produced (a worker that died mid-run);
    the run row itself stays."""
    for table in (StageResultRow, DraftRow, ClaimRow, AuditFindingRow, LLMCall, ExportRow):
        await s.execute(delete(table).where(table.run_id == run_id))
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/store -v --no-cov`
Expected: PASS. Then `uv run pytest` and `uv run ruff check . && uv run ruff format --check .`: PASS, ≥ 95%, clean.

- [ ] **Step 7: Commit**

```bash
git add corelata/store tests/store
git commit -m "feat: Corelata tables, revision 0002 and row-level data access (M3 Task 2)"
```

---

### Task 3: Pipeline observer, cancellation and the two new trace fields

**Files:**
- Modify: `engine/corelata/pipeline.py`
- Modify: `engine/corelata/schema/run.py`
- Modify: `engine/tests/conftest.py` (the `run` fixture passes `observer`)
- Modify: `engine/tests/test_pipeline.py`
- Regenerate: `schema/run-record.schema.json` (`make schema` from the repository root)
- Modify: `docs/trace-format.md`

**Interfaces:**
- Consumes: `_Run.stage()` and `_Run.execute()` as they are after M2.
- Produces: `pipeline.RunObserver` (Protocol: `async state_changed(record)`, `async stage_recorded(record, result)`, `async cancel_requested() -> bool`), `pipeline.NullObserver`, `pipeline.RunCancelled`, `run_report(..., observer: RunObserver | None = None)`, `RunOptions.parent_run_id: str | None`, `RunRecord.parent_run_id: str | None = None`, `RunRecord.extra_guidance: str = ""`. A cancel observed before a stage ends the run in `RunState.CANCELLED` with no report and the stages so far on record; `run_report` never raises `RunCancelled`.

- [ ] **Step 1: Write the failing tests**

Change the `run` fixture in `engine/tests/conftest.py` so the observer can be passed:

```python
@pytest.fixture
def run(make_config, fake_backend):
    """Execute a whole run in-process against the fake backend with a frozen clock."""

    async def _run(
        *sources,
        statement="Varna port capacity expansion matters to shippers",
        cfg=None,
        observer=None,
        **opts,
    ):
        cfg = cfg or make_config()
        sources = list(sources) or [text_source("src1", *PORT)]
        return await run_report(
            cfg,
            sources,
            RunOptions(value_statement=statement, **opts),
            backends={"fake": fake_backend},
            prompts=PromptLibrary(),
            log=CallLog(),
            now=lambda: datetime(2026, 10, 12, tzinfo=UTC),
            observer=observer,
        )

    return _run
```

Append to `engine/tests/test_pipeline.py`:

```python
class _Recording:
    """An observer that records what it sees and asks for a cancel after one named stage."""

    def __init__(self, cancel_after: str | None = None, cancel_now: bool = False) -> None:
        self.states: list[str] = []
        self.stages: list[tuple[str, int, bool]] = []
        self.cancel_after = cancel_after
        self.cancel_now = cancel_now

    async def state_changed(self, record):
        self.states.append(record.state.value)

    async def stage_recorded(self, record, result):
        assert record.stages[-1] is result
        self.stages.append((result.stage, result.iteration, result.ok))

    async def cancel_requested(self) -> bool:
        if self.cancel_now:
            return True
        return bool(self.stages) and self.stages[-1][0] == self.cancel_after


async def test_observer_sees_every_state_change_and_stage(run):
    obs = _Recording()
    record = await run(observer=obs)
    assert record.state is RunState.COMPLETED
    assert obs.states == ["ingesting", "gating", "drafting", "conveying", "auditing", "rendering"]
    assert obs.stages == [(s.stage, s.iteration, s.ok) for s in record.stages]


async def test_cancel_after_the_gate_stops_before_the_writer(run, fake_backend):
    obs = _Recording(cancel_after="gating")
    record = await run(observer=obs)
    assert record.state is RunState.CANCELLED and record.report is None
    assert record.status is None and record.error is None
    assert [s.stage for s in record.stages] == ["ingesting", "gating"]
    assert record.gate is not None  # what ran is on record
    assert not _payloads(fake_backend, "writer")
    assert record.usage.calls == len(record.llm_calls) == 1


async def test_cancel_before_anything_ran(run, fake_backend):
    record = await run(observer=_Recording(cancel_now=True))
    assert record.state is RunState.CANCELLED
    assert record.stages == [] and fake_backend.requests == []


async def test_a_cancel_during_the_loop_keeps_the_findings_so_far(run, fake_backend):
    obs = _Recording(cancel_after="auditing")
    record = await run(text_source("src1", *PORT, "UNSOURCED claim marker"), observer=obs)
    assert record.state is RunState.CANCELLED
    assert record.findings and record.drafts and record.report is None
    assert [s.stage for s in record.stages][-1] == "auditing"


async def test_parent_run_and_guidance_are_on_the_record(run):
    record = await run(parent_run_id="0f2c", extra_guidance="Reviewer note: tighten the scope")
    assert record.parent_run_id == "0f2c"
    assert record.extra_guidance == "Reviewer note: tighten the scope"
    plain = await run()
    assert plain.parent_run_id is None and plain.extra_guidance == ""
    assert plain.created_at == datetime(2026, 10, 12, tzinfo=UTC)  # the fixture's clock
    queued = await run(created_at=datetime(2026, 10, 1, 9, 30, tzinfo=UTC))
    assert queued.created_at == datetime(2026, 10, 1, 9, 30, tzinfo=UTC)
```

(`from datetime import UTC, datetime` at the top of the test module.)

(`_payloads` and `text_source`/`PORT` are already imported or defined in `test_pipeline.py`; add `from corelata.schema import RunState` and the `text_source`/`PORT` imports if they are missing.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_pipeline.py -v --no-cov -k "observer or cancel or parent_run"`
Expected: FAIL with `TypeError: run_report() got an unexpected keyword argument 'observer'` and `RunOptions.__init__() got an unexpected keyword argument 'parent_run_id'`.

- [ ] **Step 3: Add the record fields**

In `engine/corelata/schema/run.py`, add to `RunRecord` after `profile`:

```python
    parent_run_id: str | None = None  # the run this one reruns (review "return" or rejection)
    extra_guidance: str = ""  # additional writer guidance the analyst or a reviewer supplied
```

- [ ] **Step 4: Add the observer to the pipeline**

In `engine/corelata/pipeline.py`, after `RunOptions`, add:

```python
class RunObserver(Protocol):
    """What a host (the worker) learns while a run executes, and the one question the pipeline
    asks it (spec §7.2 `cancelled`, §10.1 cancel). Hooks run between model calls; they must not
    raise for the run to stay unattended."""

    async def state_changed(self, record: RunRecord) -> None: ...

    async def stage_recorded(self, record: RunRecord, result: StageResult) -> None: ...

    async def cancel_requested(self) -> bool: ...


class NullObserver:
    async def state_changed(self, record: RunRecord) -> None:
        return None

    async def stage_recorded(self, record: RunRecord, result: StageResult) -> None:
        return None

    async def cancel_requested(self) -> bool:
        return False


class RunCancelled(Exception):
    """The observer asked for a cancel; caught in execute(), never leaves run_report."""
```

Add `from typing import Any, Protocol` to the imports and two fields to `RunOptions`:

```python
    parent_run_id: str | None = None
    created_at: datetime | None = None  # when the run was created, if before this execution
```

`_Run.__init__` takes `observer: RunObserver` (keyword) and stores `self.observer = observer`; the `RunRecord(...)` construction gains `parent_run_id=options.parent_run_id, extra_guidance=options.extra_guidance` and uses `created_at=options.created_at or now()` (a queued run was created when it was submitted, not when the worker picked it up; `corelata run` passes nothing and keeps today's behaviour).

Replace the opening of `_Run.stage` so a cancel is checked and the state change announced:

```python
    async def stage[T](
        self,
        state: RunState,
        iteration: int,
        fn: Callable[[], Awaitable[T]],
        output: Callable[[T], dict[str, Any] | None] = lambda r: None,
    ) -> T:
        """Run one stage with the spec §7.5 retry ladder; record every attempt. A cancel the
        observer reports is honoured here, between stages, never inside a model call."""
        if await self.observer.cancel_requested():
            raise RunCancelled
        self.record.state = state
        await self.observer.state_changed(self.record)
        attempts = 0
        while True:
```

Make `_record_stage` async and notify after appending; every call site becomes `await self._record_stage(...)` (three in `stage`, one in `execute`):

```python
    async def _record_stage(
        self,
        state: RunState,
        iteration: int,
        started: datetime,
        *,
        output: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        result = StageResult(
            stage=state.value,
            iteration=iteration,
            ok=error is None,
            output=output,
            error=error,
            started_at=started,
            finished_at=self.now(),
        )
        self.record.stages.append(result)
        await self.observer.stage_recorded(self.record, result)
```

In `execute()`, announce the rendering state and catch the cancel:

```python
            rec.state = RunState.RENDERING
            await self.observer.state_changed(rec)
            started = self.now()
```

```python
        except RunCancelled:
            rec.state = RunState.CANCELLED
        except (*AGENT_FAILURES, StageError) as e:
            rec.state = RunState.FAILED
            rec.error = str(e)
        return self._finish()
```

`run_report` gains `observer: RunObserver | None = None` and passes `observer=observer or NullObserver()` to `_Run`.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_pipeline.py tests/test_scenarios.py -v --no-cov`
Expected: PASS (the scenario fixtures are unaffected: `NullObserver` is the default).

- [ ] **Step 6: Regenerate the schema and document the fields**

Run from the repository root: `make schema`. `schema/run-record.schema.json` now carries `parent_run_id` and `extra_guidance`. Run `uv run pytest tests/schema -v --no-cov`: PASS.

In `docs/trace-format.md`, extend the Identity bullet under **RunRecord**:

```markdown
- Identity: `run_id`, `created_at`, `corelata_version`, `config_hash`, `prompt_versions`
  (prompt id → version used), `pack_name`, `pack_hash`, `pack_snapshot` (the resolved pack as
  JSON — edit the pack directory later and this run still means what it meant), `profile`,
  `parent_run_id` (the run this one reruns after a review "return" or a gate rejection; null
  for a first run), `extra_guidance` (additional writer guidance the analyst or a reviewer
  supplied; empty when none).
```

and the Outcome bullet: after "terminal states `completed`, `gate_rejected`, `failed`, `cancelled`" add "— a `cancelled` run keeps the stages and model calls made before the analyst's cancel took effect and has no `report`".

- [ ] **Step 7: Run everything and commit**

Run: `uv run pytest` and `uv run ruff check . && uv run ruff format --check .`
Expected: PASS, ≥ 95%, clean.

```bash
git add corelata/pipeline.py corelata/schema/run.py tests/conftest.py tests/test_pipeline.py ../schema/run-record.schema.json ../docs/trace-format.md
git commit -m "feat: pipeline observer with cancellation; parent_run_id and extra_guidance on the trace (M3 Task 3)"
```

---

### Task 4: Storage and the record ⇄ rows mapping

**Files:**
- Create: `engine/corelata/storage.py` (copied)
- Create: `engine/corelata/store/records.py`
- Create: `engine/tests/test_storage.py`, `engine/tests/store/test_records.py`

**Interfaces:**
- Consumes: `store.runs` (Task 2), `RunRecord` with the Task 3 fields, `CallLog.usage()`.
- Produces: `storage.Storage` protocol (`put`, `get`, `local_file`, `delete_prefix`, `check_writable`), `LocalStorage(root)`, `StorageError`, `safe_filename`, `display_name`, `FILE_MODE`, `build_storage(cfg.storage)`; `records.load_sources(s, run_id) -> list[Source]`, `records.load_record(s, run_id) -> RunRecord`, `records.save_outcome(s, run, record, *, source_ids, stages_from=0, calls_from=0) -> None`.

- [ ] **Step 1: Write the failing tests**

`engine/tests/test_storage.py`: copy `~/Downloads/coglossa/engine/tests/test_storage.py` verbatim and replace every `coglossa` with `corelata` (imports, the two `monkeypatch.setattr("corelata.storage.os.replace", …)` / `"corelata.storage.shutil.rmtree"` targets). The expectations are unchanged; `test_stored_files_are_group_readable_and_synced` still asserts `FILE_MODE == 0o640`.

`engine/tests/store/test_records.py`:

```python
import uuid

import pytest

from corelata.schema import RunState
from corelata.store import records, runs
from corelata.testing.sources import text_source
from tests.stages.conftest import PORT

STATEMENT = "Varna port capacity expansion matters to shippers"


async def _rows_for(db, record, sources):
    """Project, source and run rows that correspond to an in-process record."""
    async with db.session() as s, s.begin():
        project = await runs.get_or_create_project(s, "p")
        source_rows = [
            await runs.add_source(s, project.id, src, storage_key=f"k/{src.id}") for src in sources
        ]
        run = await runs.create_run(
            s,
            project_id=project.id,
            value_statement=record.value_statement,
            profile=record.profile,
            max_iterations=record.max_iterations,
            extra_guidance=record.extra_guidance,
            config_hash=record.config_hash,
            config_snapshot={},
            pack_name=record.pack_name,
            pack_hash=record.pack_hash,
            pack_snapshot=record.pack_snapshot,
            prompt_versions=record.prompt_versions,
            corelata_version=record.corelata_version,
            docx_reference_key=None,
            parent_run_id=None,
            source_ids=[r.id for r in source_rows],
            run_id=uuid.UUID(record.run_id),
            created_at=record.created_at,
        )
    return run.id, [r.id for r in source_rows]


@pytest.mark.parametrize(
    ("statement", "extra", "state"),
    [
        (STATEMENT, "", RunState.COMPLETED),
        ("Antarctic penguin colonies are shrinking", "", RunState.GATE_REJECTED),
        (STATEMENT, "UNSOURCED", RunState.COMPLETED),
    ],
)
async def test_record_round_trips_through_rows(db, run, statement, extra, state):
    rid = uuid.uuid4()
    sources = [text_source("src1", *PORT), text_source("src2", "Shippers welcomed Varna.", extra)]
    record = await run(*sources, statement=statement, run_id=str(rid))
    assert record.state is state
    run_id, source_ids = await _rows_for(db, record, sources)
    async with db.session() as s, s.begin():
        row = await runs.get_run(s, run_id, lock=True)
        await records.save_outcome(s, row, record, source_ids=source_ids)
    async with db.session() as s:
        loaded = await records.load_record(s, run_id)
        row = await runs.get_run(s, run_id)
    assert loaded.model_dump() == record.model_dump()
    assert row.finished_at is not None and row.state == state.value
    assert row.token_usage == record.usage.model_dump()
    assert (row.report is None) == (record.report is None)


async def test_load_sources_keeps_the_run_order_and_names(db, run):
    rid = uuid.uuid4()
    a, b = text_source("src1", "alpha"), text_source("src2", "beta", name="b.md")
    record = await run(a, b, run_id=str(rid))
    run_id, source_ids = await _rows_for(db, record, [b, a])  # stored in the other order
    async with db.session() as s:
        loaded = await records.load_sources(s, run_id)
    assert [(x.id, x.name) for x in loaded] == [("src1", "b.md"), ("src2", "src1.txt")]
    assert loaded[0].units[0].text == "beta"


async def test_save_outcome_appends_only_what_is_not_persisted_yet(db, run):
    rid = uuid.uuid4()
    record = await run(run_id=str(rid))
    run_id, source_ids = await _rows_for(db, record, [text_source("src1", *PORT)])
    async with db.session() as s, s.begin():
        await runs.add_stage(s, run_id, 0, record.stages[0])
        await runs.add_llm_calls(s, run_id, 0, record.llm_calls[:1], stage="gating")
        row = await runs.get_run(s, run_id, lock=True)
        await records.save_outcome(
            s, row, record, source_ids=source_ids, stages_from=1, calls_from=1
        )
    async with db.session() as s:
        loaded = await records.load_record(s, run_id)
    assert loaded.stages == record.stages and loaded.llm_calls == record.llm_calls


async def test_load_record_of_an_unknown_run(db):
    async with db.session() as s:
        with pytest.raises(runs.NotFoundError):
            await records.load_record(s, uuid.uuid4())
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_storage.py tests/store/test_records.py -v --no-cov`
Expected: FAIL with `ModuleNotFoundError` for `corelata.storage` and `corelata.store.records`.

- [ ] **Step 3: Copy the storage module**

`engine/corelata/storage.py`: copy `~/Downloads/coglossa/engine/coglossa/storage.py` verbatim, then: replace `from coglossa.config import StorageConfig` with `from corelata.config import StorageConfig`; change the module docstring's first line to `"""Stored files (spec §4.2 `storage`, §11): uploaded sources, the reference document of a run and the worker's exports, behind a Storage interface with a local-volume implementation.`; in `check_writable` use `prefix=".corelata-check-"`; in `safe_filename` keep the fallback `"document"`. Everything else (`StorageError`, `Storage`, `safe_filename`, `FILE_MODE = 0o640`, `display_name`, `LocalStorage` with atomic `put`, `get`, `local_file`, `delete_prefix`, `check_writable`, `build_storage`) stays as copied.

- [ ] **Step 4: Write the records module**

`engine/corelata/store/records.py`:

```python
"""A run's rows as the trace record and back (spec §8.4 invariant 5: every export is derived
from stored rows). `load_record` rebuilds the `RunRecord` that `corelata run` would have
written; `save_outcome` stores what a finished (or cancelled, or failed) run produced."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from corelata.llm.agent import CallLog
from corelata.schema import (
    Digest,
    GateVerdict,
    Report,
    ReportStatus,
    RunRecord,
    RunState,
    Source,
)
from corelata.store import runs
from corelata.store.models import Run, utcnow


async def load_sources(s: AsyncSession, run_id: uuid.UUID) -> list[Source]:
    """The run's sources, named src1, src2, … by their position (RunSource.ordinal)."""
    ids = await runs.run_source_ids(s, run_id)
    return [
        await runs.load_source(s, await runs.get_source(s, sid), as_id=f"src{i}")
        for i, sid in enumerate(ids, start=1)
    ]


async def load_record(s: AsyncSession, run_id: uuid.UUID) -> RunRecord:
    run = await runs.get_run(s, run_id)
    calls = await runs.load_llm_calls(s, run_id)
    return RunRecord(
        corelata_version=run.corelata_version,
        run_id=str(run.id),
        created_at=run.created_at,
        state=RunState(run.state),
        status=ReportStatus(run.status) if run.status else None,
        value_statement=run.value_statement,
        profile=run.profile,
        parent_run_id=str(run.parent_run_id) if run.parent_run_id else None,
        extra_guidance=run.extra_guidance,
        pack_name=run.pack_name,
        pack_hash=run.pack_hash,
        pack_snapshot=run.pack_snapshot,
        config_hash=run.config_hash,
        prompt_versions=run.prompt_versions,
        sources=await load_sources(s, run_id),
        digests=[Digest.model_validate(d) for d in run.digests],
        gate=GateVerdict.model_validate(run.gate) if run.gate else None,
        stages=await runs.load_stages(s, run_id),
        drafts=await runs.load_drafts(s, run_id),
        findings=await runs.load_findings(s, run_id),
        report=Report.model_validate(run.report) if run.report else None,
        iterations=run.iteration,
        max_iterations=run.max_iterations,
        usage=CallLog(records=calls).usage(),
        llm_calls=calls,
        error=run.error,
    )


async def save_outcome(
    s: AsyncSession,
    run: Run,
    record: RunRecord,
    *,
    source_ids: list[uuid.UUID],
    stages_from: int = 0,
    calls_from: int = 0,
) -> None:
    """Store a finished run. `stages_from` and `calls_from` are how many stage results and
    model calls the observer already persisted while the run executed; the rest is appended.
    Drafts, findings and claims are written here in full. The caller holds the run row lock."""
    run.state = record.state.value
    run.status = record.status.value if record.status else None
    run.error = record.error
    run.gate = record.gate.model_dump(mode="json") if record.gate else None
    run.digests = [d.model_dump(mode="json") for d in record.digests]
    run.report = record.report.model_dump(mode="json") if record.report else None
    run.iteration = record.iterations
    run.token_usage = record.usage.model_dump()
    run.finished_at = utcnow()
    for i, stage in enumerate(record.stages[stages_from:], start=stages_from):
        await runs.add_stage(s, run.id, i, stage)
    await runs.add_drafts(s, run.id, 0, record.drafts)
    await runs.add_findings(s, run.id, 0, record.findings)
    await runs.add_llm_calls(
        s, run.id, calls_from, record.llm_calls[calls_from:], stage=record.state.value
    )
    if record.report is not None:
        await runs.replace_claims(s, run.id, record.report, source_ids)
    await s.flush()
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_storage.py tests/store -v --no-cov`
Expected: PASS. If `test_record_round_trips_through_rows` reports a difference in `pack_snapshot`, check that the fixture `run` passes the pack through `pack_snapshot=pack.model_dump(mode="json")` (it does; JSONB round-trips JSON values unchanged) and that `created_at` came back timezone-aware (TIMESTAMP WITH TIME ZONE does).

Run: `uv run pytest` and `uv run ruff check . && uv run ruff format --check .`: PASS, ≥ 95%, clean.

- [ ] **Step 6: Commit**

```bash
git add corelata/storage.py corelata/store/records.py tests/test_storage.py tests/store/test_records.py
git commit -m "feat: file storage and the run record to rows mapping (M3 Task 4)"
```

---

### Task 5: Service layer — projects, sources, queued runs, cancel, review

**Files:**
- Create: `engine/corelata/schema/progress.py`
- Modify: `engine/corelata/schema/__init__.py`, `engine/corelata/schema/export.py`
- Create: `engine/corelata/service.py`
- Create: `engine/corelata/testing/queue.py` (copied)
- Create: `engine/tests/test_service.py`
- Regenerate: `schema/run-progress.schema.json`, `schema/discovery-view.schema.json` (`make schema`)

**Interfaces:**
- Consumes: `store.runs`, `store.records`, `storage` (Tasks 2 and 4); `load_run_pack`, `pack_hash`, `config_hash`, `PromptLibrary.versions`, `run_prompt_ids`, `make_source`, `load_coglossa_export`, `check_extension`.
- Produces: `schema.ReviewAction` (`accept` | `return`), `schema.RunProgress`, `schema.DiscoveryState`, `schema.DiscoveryView`; `service.JobQueue` (Protocol `async defer(task, *, lock=None, **kwargs: str)`), `service.TASK_RUN = "corelata.run"`, `service.TASK_DISCOVER = "corelata.discover"`, `service.run_lock(run_id)`, `service.discovery_lock(discovery_id)`, `service.RunRequest`, `service.ConflictError`, `service.InvalidRunStateError`, `service.InvalidRequestError`, and the coroutines `create_project`, `list_projects`, `add_source`, `list_sources`, `start_run`, `cancel_run`, `review_run`, `run_progress`, `get_run_record`, `reference_document`; `testing.queue.RecordingQueue` with `.jobs`, `.attempts`, `.pop()`. Task 7 adds `start_discovery` and `get_discovery` to this module.

- [ ] **Step 1: Write the progress schemas**

`engine/corelata/schema/progress.py`:

```python
"""What the control plane reports about queued work (spec §10.1 GET /runs/{id}, SSE, discovery).
Pure views over stored rows; the API serves them unchanged in M4a."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from corelata.schema.common import Usage
from corelata.schema.gate import CandidateStatement
from corelata.schema.report import ReportStatus
from corelata.schema.run import RunState, StageResult


class ReviewAction(StrEnum):
    ACCEPT = "accept"
    RETURN = "return"


class RunProgress(BaseModel):
    run_id: str
    project_id: str
    parent_run_id: str | None = None
    state: RunState
    status: ReportStatus | None = None
    iteration: int
    max_iterations: int
    stages: list[StageResult] = Field(default_factory=list)  # every attempt recorded so far
    usage: Usage | None = None
    cancel_requested: bool = False
    attempts: int = 0  # executions the worker started (2 after a crash and a requeue)
    error: str | None = None
    export_error: str | None = None  # the run completed but its DOCX export failed
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class DiscoveryState(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class DiscoveryView(BaseModel):
    discovery_id: str
    project_id: str
    state: DiscoveryState
    audience_hint: str = ""
    source_ids: list[str]
    candidates: list[CandidateStatement] = Field(default_factory=list)
    usage: Usage | None = None
    error: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
```

Export them from `engine/corelata/schema/__init__.py` (add `from corelata.schema.progress import DiscoveryState, DiscoveryView, ReviewAction, RunProgress` and the four names to `__all__`), and add to `EXPORTED` in `engine/corelata/schema/export.py`:

```python
    "run-progress": RunProgress,
    "discovery-view": DiscoveryView,
```

Run `make schema` from the repository root; the two new files appear under `schema/`.

- [ ] **Step 2: Copy the recording queue**

`engine/corelata/testing/queue.py`:

```python
"""In-memory JobQueue for tests. Like procrastinate, a queueing lock that is already queued
is not queued again; `attempts` records every defer call so tests can see duplicates."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class QueuedJob:
    task: str
    lock: str | None
    kwargs: dict[str, str] = field(default_factory=dict)


class RecordingQueue:
    def __init__(self) -> None:
        self.jobs: list[QueuedJob] = []
        self.attempts: list[QueuedJob] = []

    async def defer(self, task: str, *, lock: str | None = None, **kwargs: str) -> None:
        job = QueuedJob(task, lock, kwargs)
        self.attempts.append(job)
        if lock is not None and any(j.lock == lock for j in self.jobs):
            return
        self.jobs.append(job)

    def pop(self) -> QueuedJob | None:
        return self.jobs.pop(0) if self.jobs else None
```

- [ ] **Step 3: Write the failing tests**

`engine/tests/test_service.py`:

```python
import json
import uuid

import pytest
from docx import Document
from sqlalchemy import select, text

from corelata import service
from corelata.config import CorelataConfig
from corelata.ingest.base import IngestError
from corelata.store.models import ReviewEvent
from corelata.prompts.library import PromptLibrary
from corelata.schema import ReviewAction, RunState
from corelata.standards.loader import PackError, load_pack, pack_hash
from corelata.storage import LocalStorage
from corelata.store import runs
from corelata.store.models import utcnow
from corelata.testing.queue import RecordingQueue
from tests.ingest.test_coglossa import export as coglossa_export
from tests.stages.conftest import PORT
from tests.standards.test_loader import write_pack

STATEMENT = "Varna port capacity expansion matters to shippers"


class Svc:
    """The handles every service call takes, bundled for the tests."""

    def __init__(self, db, tmp_path, cfg: CorelataConfig) -> None:
        self.db = db
        self.storage = LocalStorage(tmp_path / "files")
        self.queue = RecordingQueue()
        self.cfg = cfg
        self.prompts = PromptLibrary(cfg.prompts_dir)

    async def project(self, name="p") -> uuid.UUID:
        return await service.create_project(self.db, name)

    async def source(self, project_id, text="\n\n".join(PORT), name="port.txt") -> uuid.UUID:
        [sid] = await service.add_source(
            self.db, self.storage, project_id, name, text.encode("utf-8")
        )
        return sid

    async def run(self, project_id, source_ids, **kw) -> uuid.UUID:
        req = service.RunRequest(
            project_id=project_id, source_ids=source_ids, value_statement=STATEMENT, **kw
        )
        return await service.start_run(
            self.db, self.storage, self.queue, self.cfg, self.prompts, req
        )


@pytest.fixture
def svc(db, tmp_path, make_config):
    return Svc(db, tmp_path, make_config())


async def _set_state(db, run_id, state: str):
    async with db.session() as s, s.begin():
        run = await runs.get_run(s, run_id, lock=True)
        run.state = state
        run.started_at = utcnow()


async def test_projects(svc):
    pid = await svc.project("novel")
    assert await svc.project("novel") == pid
    assert [(p.id, p.name) for p in await service.list_projects(svc.db)] == [(pid, "novel")]


async def test_add_source_stores_the_file_and_the_units(svc):
    pid = await svc.project()
    sid = await svc.source(pid, name="Mon rapport (v2).txt")
    async with svc.db.session() as s:
        [row] = await runs.list_sources(s, pid)
        assert row.id == sid and row.name == "Mon rapport (v2).txt" and row.format == "txt"
        assert row.storage_key == f"projects/{pid}/sources/{sid}/Mon_rapport__v2_.txt"
        loaded = await runs.load_source(s, row, as_id="src1")
    assert [u.text for u in loaded.units] == PORT
    assert svc.storage.get(row.storage_key).decode() == "\n\n".join(PORT)
    assert [r.id for r in await service.list_sources(svc.db, pid)] == [sid]


async def test_add_source_rejects_bad_uploads_and_leaves_no_file(svc, tmp_path):
    pid = await svc.project()
    with pytest.raises(IngestError, match="unsupported file type"):
        await service.add_source(svc.db, svc.storage, pid, "x.png", b"\x89PNG")
    with pytest.raises(IngestError, match="is empty"):
        await service.add_source(svc.db, svc.storage, pid, "x.txt", b"")
    with pytest.raises(service.InvalidRequestError, match="no file name"):
        await service.add_source(svc.db, svc.storage, pid, "", b"x")
    with pytest.raises(IngestError, match="no usable text"):
        await service.add_source(svc.db, svc.storage, pid, "blank.txt", b"\n\n  \n")
    with pytest.raises(runs.NotFoundError):
        await service.add_source(svc.db, svc.storage, uuid.uuid4(), "a.txt", b"hello")
    assert not list((tmp_path / "files").rglob("*.txt"))
    async with svc.db.session() as s:
        assert await runs.list_sources(s, pid) == []


async def test_add_coglossa_export_gives_the_translation_and_its_guide(svc):
    pid = await svc.project()
    data = json.dumps(coglossa_export()).encode("utf-8")
    ids = await service.add_source(
        svc.db, svc.storage, pid, "letter.coglossa.json", data, coglossa_export=True
    )
    assert len(ids) == 2
    async with svc.db.session() as s:
        rows = {r.id: r for r in await runs.list_sources(s, pid)}
    main, guide = (rows[i] for i in ids)
    assert main.kind == "coglossa_export" and main.provenance["coglossa_run_id"] == "run-42"
    assert main.name == "letter.coglossa.json" and guide.storage_key == main.storage_key
    assert guide.format == "coglossa-guide"


async def test_start_run_queues_one_job_and_snapshots_the_pack(svc):
    pid = await svc.project()
    sid = await svc.source(pid)
    run_id = await svc.run(pid, [sid], extra_guidance="Keep it short")
    assert [(j.task, j.lock, j.kwargs) for j in svc.queue.jobs] == [
        (service.TASK_RUN, f"run:{run_id}", {"run_id": str(run_id)})
    ]
    pack = load_pack("icd203-base")
    async with svc.db.session() as s:
        run = await runs.get_run(s, run_id)
        assert await runs.run_source_ids(s, run_id) == [sid]
    assert run.state == "created" and run.max_iterations == svc.cfg.pipeline.max_iterations
    assert run.pack_hash == pack_hash(pack) and run.pack_snapshot == pack.model_dump(mode="json")
    assert run.pack_name == "icd203-base" and run.profile is None
    assert run.config_snapshot["pipeline"]["max_iterations"] == 2
    assert run.prompt_versions["writer"] >= 1 and run.corelata_version
    assert run.extra_guidance == "Keep it short" and run.docx_reference_key is None
    progress = await service.run_progress(svc.db, run_id)
    assert progress.state is RunState.CREATED and progress.stages == [] and progress.usage is None
    assert progress.project_id == str(pid) and progress.created_at.tzinfo is not None


async def test_start_run_validates_its_request(svc):
    pid = await svc.project()
    sid = await svc.source(pid)
    other = await svc.project("other")
    foreign = await svc.source(other)
    with pytest.raises(service.InvalidRequestError, match="value statement"):
        await service.start_run(
            svc.db, svc.storage, svc.queue, svc.cfg, svc.prompts,
            service.RunRequest(project_id=pid, source_ids=[sid], value_statement="  "),
        )
    with pytest.raises(service.InvalidRequestError, match="at least one source"):
        await svc.run(pid, [])
    with pytest.raises(service.InvalidRequestError, match="between 0 and 10"):
        await svc.run(pid, [sid], max_iterations=11)
    with pytest.raises(runs.NotFoundError, match="not in project"):
        await svc.run(pid, [sid, foreign])
    with pytest.raises(PackError, match="profile 'nope' not found"):
        await svc.run(pid, [sid], profile="nope")
    with pytest.raises(runs.NotFoundError, match="not found"):
        await svc.run(pid, [sid], parent_run_id=uuid.uuid4())
    assert svc.queue.jobs == []
    async with svc.db.session() as s:
        assert (await s.execute(text("SELECT count(*) FROM run"))).scalar() == 0


async def test_start_run_stores_the_profile_reference_document(db, tmp_path, make_config):
    pack = write_pack(
        tmp_path / "packs", "house", rules=[], extends="icd203-base", template=None, lexicon=None,
        profiles={"east": {"name": "east", "extends": "house",
                           "format": {"docx_reference": "templates/east.docx"}}},
    )
    (pack / "templates").mkdir()
    Document().save(str(pack / "templates" / "east.docx"))
    cfg = make_config(standards={"packs_dir": str(tmp_path / "packs"), "default_pack": "house"})
    svc = Svc(db, tmp_path, cfg)
    pid = await svc.project()
    sid = await svc.source(pid)
    run_id = await svc.run(pid, [sid], profile="east")
    async with svc.db.session() as s:
        run = await runs.get_run(s, run_id)
    assert run.profile == "east" and run.docx_reference_key == f"runs/{run_id}/reference.docx"
    stored = svc.storage.get(run.docx_reference_key)
    assert stored == (pack / "templates" / "east.docx").read_bytes()
    assert await service.reference_document(svc.db, svc.storage, run_id) == stored
    (pack / "templates" / "east.docx").unlink()  # Review Focus 4: the run keeps its copy
    assert await service.reference_document(svc.db, svc.storage, run_id) == stored


async def test_cancel_a_created_run_ends_it_at_once(svc):
    pid = await svc.project()
    run_id = await svc.run(pid, [await svc.source(pid)])
    assert await service.cancel_run(svc.db, run_id) is RunState.CANCELLED
    progress = await service.run_progress(svc.db, run_id)
    assert progress.cancel_requested and progress.finished_at is not None
    with pytest.raises(service.InvalidRunStateError, match="already cancelled"):
        await service.cancel_run(svc.db, run_id)


async def test_cancel_a_running_run_only_sets_the_flag(svc):
    pid = await svc.project()
    run_id = await svc.run(pid, [await svc.source(pid)])
    await _set_state(svc.db, run_id, "drafting")
    assert await service.cancel_run(svc.db, run_id) is RunState.DRAFTING
    progress = await service.run_progress(svc.db, run_id)
    assert progress.cancel_requested and progress.state is RunState.DRAFTING
    assert progress.finished_at is None
    with pytest.raises(runs.NotFoundError):
        await service.cancel_run(svc.db, uuid.uuid4())


async def test_review_needs_a_completed_run(svc):
    pid = await svc.project()
    run_id = await svc.run(pid, [await svc.source(pid)])
    with pytest.raises(service.InvalidRunStateError, match="only a completed run"):
        await service.review_run(
            svc.db, svc.storage, svc.queue, svc.cfg, svc.prompts, run_id, ReviewAction.ACCEPT
        )


async def test_accept_records_an_event_and_queues_nothing(svc):
    pid = await svc.project()
    run_id = await svc.run(pid, [await svc.source(pid)])
    await _set_state(svc.db, run_id, "completed")
    svc.queue.jobs.clear()
    child = await service.review_run(
        svc.db, svc.storage, svc.queue, svc.cfg, svc.prompts, run_id, ReviewAction.ACCEPT,
        note="good", actor="alice",
    )
    assert child is None and svc.queue.jobs == []
    async with svc.db.session() as s:
        from sqlalchemy import select

        from corelata.store.models import ReviewEvent

        [event] = (await s.scalars(select(ReviewEvent))).all()
    assert (event.run_id, event.action, event.note, event.actor, event.child_run_id) == (
        run_id, "accept", "good", "alice", None,
    )


async def test_return_creates_a_linked_run_seeded_with_the_note(db, tmp_path, make_config):
    pack = write_pack(
        tmp_path / "packs", "house", rules=[], extends="icd203-base", template=None, lexicon=None,
        profiles={"east": {"name": "east", "extends": "house",
                           "format": {"docx_reference": "templates/east.docx"}}},
    )
    (pack / "templates").mkdir()
    Document().save(str(pack / "templates" / "east.docx"))
    cfg = make_config(standards={"packs_dir": str(tmp_path / "packs"), "default_pack": "house"})
    svc = Svc(db, tmp_path, cfg)
    pid = await svc.project()
    a, b = await svc.source(pid), await svc.source(pid, text="Shippers welcomed Varna.", name="b.md")
    run_id = await svc.run(pid, [b, a], profile="east", max_iterations=1, extra_guidance="Brief")
    await _set_state(svc.db, run_id, "completed")
    svc.queue.jobs.clear()
    with pytest.raises(service.InvalidRequestError, match="needs a note"):
        await service.review_run(
            svc.db, svc.storage, svc.queue, svc.cfg, svc.prompts, run_id, ReviewAction.RETURN
        )
    child = await service.review_run(
        svc.db, svc.storage, svc.queue, svc.cfg, svc.prompts, run_id, ReviewAction.RETURN,
        note="Tighten the scope.", actor="alice",
    )
    assert child is not None and child != run_id
    assert [(j.task, j.lock) for j in svc.queue.jobs] == [(service.TASK_RUN, f"run:{child}")]
    async with svc.db.session() as s:
        parent, kid = await runs.get_run(s, run_id), await runs.get_run(s, child)
        assert await runs.run_source_ids(s, child) == [b, a]
        from sqlalchemy import select

        from corelata.store.models import ReviewEvent

        [event] = (await s.scalars(select(ReviewEvent))).all()
    assert kid.parent_run_id == run_id and kid.state == "created"
    assert kid.extra_guidance == "Brief\nReviewer note: Tighten the scope."
    assert (kid.value_statement, kid.profile, kid.max_iterations) == (STATEMENT, "east", 1)
    assert (kid.pack_snapshot, kid.pack_hash) == (parent.pack_snapshot, parent.pack_hash)
    assert kid.docx_reference_key == f"runs/{child}/reference.docx"
    assert svc.storage.get(kid.docx_reference_key) == svc.storage.get(parent.docx_reference_key)
    assert (event.action, event.child_run_id) == ("return", child)
    progress = await service.run_progress(svc.db, child)
    assert progress.parent_run_id == str(run_id)


async def test_get_run_record_rebuilds_the_trace(svc):
    pid = await svc.project()
    run_id = await svc.run(pid, [await svc.source(pid)])
    record = await service.get_run_record(svc.db, run_id)
    assert record.run_id == str(run_id) and record.state is RunState.CREATED
    assert [s.id for s in record.sources] == ["src1"] and record.report is None
```

(The two `from sqlalchemy import select` / `from corelata.store.models import ReviewEvent` lines inside the review tests are covered by the module-level imports; drop the inline ones when writing the file.)

- [ ] **Step 4: Run the tests to verify they fail**

Run: `uv run pytest tests/test_service.py -v --no-cov`
Expected: FAIL with `ModuleNotFoundError: No module named 'corelata.service'`.

- [ ] **Step 5: Write the service module**

`engine/corelata/service.py`:

```python
"""Control plane (spec §10.1 semantics, §10.2 commands): projects, sources, queued runs,
cancel and review. The CLI uses it now and the REST API will in M4a. It never calls a model:
work reaches the worker through a JobQueue. Task 7 adds discoveries."""

import contextlib
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from corelata import __version__
from corelata.config import CorelataConfig, config_hash
from corelata.ingest.base import IngestError
from corelata.ingest.coglossa import load_coglossa_export
from corelata.ingest.registry import check_extension
from corelata.ingest.units import make_source
from corelata.pipeline import load_run_pack
from corelata.prompts.check import run_prompt_ids
from corelata.prompts.library import PromptLibrary
from corelata.schema import (
    TERMINAL_STATES,
    ReviewAction,
    RunProgress,
    RunRecord,
    RunState,
    Usage,
)
from corelata.standards.loader import pack_hash
from corelata.storage import Storage, StorageError, display_name, safe_filename
from corelata.store import records, runs
from corelata.store.db import Database
from corelata.store.models import Project, Run, SourceRow, utcnow

TASK_RUN = "corelata.run"
TASK_DISCOVER = "corelata.discover"
_MAX_FILENAME = 255


class JobQueue(Protocol):
    async def defer(self, task: str, *, lock: str | None = None, **kwargs: str) -> None: ...


class ConflictError(Exception):
    """The request conflicts with the current data; the message says why (HTTP 409)."""


class InvalidRunStateError(ConflictError):
    """The run is not in a state that allows the action; the message says why."""


class InvalidRequestError(ValueError):
    """The request itself is invalid; the message says why (HTTP 422)."""


def run_lock(run_id: uuid.UUID) -> str:
    return f"run:{run_id}"


def discovery_lock(discovery_id: uuid.UUID) -> str:
    return f"discovery:{discovery_id}"


@dataclass(frozen=True)
class RunRequest:
    project_id: uuid.UUID
    source_ids: list[uuid.UUID]
    value_statement: str
    profile: str | None = None
    max_iterations: int | None = None
    extra_guidance: str = ""
    parent_run_id: uuid.UUID | None = None


# ---------------------------------------------------------------- projects and sources


async def create_project(db: Database, name: str) -> uuid.UUID:
    async with db.session() as s, s.begin():
        return (await runs.get_or_create_project(s, name)).id


async def list_projects(db: Database) -> list[Project]:
    async with db.session() as s:
        return await runs.list_projects(s)


async def list_sources(db: Database, project_id: uuid.UUID) -> list[SourceRow]:
    async with db.session() as s:
        await runs.get_project(s, project_id)
        return await runs.list_sources(s, project_id)


async def add_source(
    db: Database,
    storage: Storage,
    project_id: uuid.UUID,
    filename: str,
    data: bytes,
    *,
    coglossa_export: bool = False,
) -> list[uuid.UUID]:
    """Store an upload, parse it into units (spec §5) and record it. Returns the new source ids:
    one, or two for a Coglossa export that carries a translation guide. A file that cannot be
    parsed is not kept."""
    name = display_name(filename)
    if not name:
        raise InvalidRequestError("the upload has no file name")
    if len(name) > _MAX_FILENAME:
        raise InvalidRequestError(f"the file name is longer than {_MAX_FILENAME} characters")
    if not coglossa_export:
        check_extension(name)
    if not data:
        raise IngestError(f"{name} is empty")
    async with db.session() as s:
        await runs.get_project(s, project_id)
    source_id = uuid.uuid4()
    prefix = f"projects/{project_id}/sources/{source_id}/"
    key = prefix + safe_filename(name)
    try:
        storage.put(key, data)
        with storage.local_file(key) as path:
            parsed = (
                load_coglossa_export("src1", path) if coglossa_export else [make_source("src1", path)]
            )
        parsed[0] = parsed[0].model_copy(update={"name": name})
        ids: list[uuid.UUID] = []
        async with db.session() as s, s.begin():
            for i, source in enumerate(parsed):
                row = await runs.add_source(
                    s, project_id, source, storage_key=key,
                    source_id=source_id if i == 0 else None,
                )
                ids.append(row.id)
    except BaseException:
        with contextlib.suppress(StorageError):  # nothing points at the file
            storage.delete_prefix(prefix)
        raise
    return ids


# ---------------------------------------------------------------- runs


async def _create_run(
    db: Database,
    storage: Storage,
    cfg: CorelataConfig,
    prompts: PromptLibrary,
    req: RunRequest,
    *,
    pack_name: str,
    pack_hash_: str,
    pack_snapshot: dict[str, Any],
    profile: str | None,
    reference: bytes | None,
) -> uuid.UUID:
    """The run row, its ordered sources and, when the profile has one, a copy of the reference
    document under runs/<id>/ so the run renders with the template it was queued with."""
    run_id = uuid.uuid4()
    key = f"runs/{run_id}/reference.docx" if reference is not None else None
    try:
        if key is not None:
            storage.put(key, reference)
        async with db.session() as s, s.begin():
            if req.parent_run_id is not None:
                await runs.get_run(s, req.parent_run_id)
            await runs.create_run(
                s,
                project_id=req.project_id,
                value_statement=req.value_statement.strip(),
                profile=profile,
                max_iterations=(
                    cfg.pipeline.max_iterations
                    if req.max_iterations is None
                    else req.max_iterations
                ),
                extra_guidance=req.extra_guidance,
                config_hash=config_hash(cfg),
                config_snapshot=cfg.model_dump(mode="json"),
                pack_name=pack_name,
                pack_hash=pack_hash_,
                pack_snapshot=pack_snapshot,
                prompt_versions=prompts.versions(run_prompt_ids()),
                corelata_version=__version__,
                docx_reference_key=key,
                parent_run_id=req.parent_run_id,
                source_ids=req.source_ids,
                run_id=run_id,
            )
    except BaseException:
        if key is not None:
            with contextlib.suppress(StorageError):
                storage.delete_prefix(f"runs/{run_id}/")
        raise
    return run_id


def _validate(req: RunRequest) -> None:
    if not req.value_statement.strip():
        raise InvalidRequestError("a run needs a value statement")
    if not req.source_ids:
        raise InvalidRequestError("a run needs at least one source")
    if req.max_iterations is not None and not 0 <= req.max_iterations <= 10:
        raise InvalidRequestError("max_iterations must be between 0 and 10")


async def start_run(
    db: Database,
    storage: Storage,
    queue: JobQueue,
    cfg: CorelataConfig,
    prompts: PromptLibrary,
    req: RunRequest,
) -> uuid.UUID:
    """Snapshot the pack, store the run and queue it (spec §7.2 `created`)."""
    _validate(req)
    pack = load_run_pack(cfg, req.profile)  # PackError for an unknown or draft profile
    reference = (
        pack.docx_reference_path.read_bytes() if pack.docx_reference_path is not None else None
    )
    run_id = await _create_run(
        db,
        storage,
        cfg,
        prompts,
        req,
        pack_name=pack.name,
        pack_hash_=pack_hash(pack),
        pack_snapshot=pack.model_dump(mode="json"),
        profile=pack.profile,
        reference=reference,
    )
    await queue.defer(TASK_RUN, lock=run_lock(run_id), run_id=str(run_id))
    return run_id


async def cancel_run(db: Database, run_id: uuid.UUID) -> RunState:
    """Ask a run to stop. A run nothing is executing yet ends at once; a running one stops at
    its next stage boundary (the pipeline polls the flag). Returns the state after the call."""
    async with db.session() as s, s.begin():
        run = await runs.get_run(s, run_id, lock=True)
        state = RunState(run.state)
        if state in TERMINAL_STATES:
            raise InvalidRunStateError(f"run {run_id} is already {state.value}")
        run.cancel_requested = True
        if state is RunState.CREATED:
            run.state = RunState.CANCELLED.value
            run.finished_at = utcnow()
        return RunState(run.state)


async def review_run(
    db: Database,
    storage: Storage,
    queue: JobQueue,
    cfg: CorelataConfig,
    prompts: PromptLibrary,
    run_id: uuid.UUID,
    action: ReviewAction,
    *,
    note: str = "",
    actor: str | None = None,
) -> uuid.UUID | None:
    """Spec §10.1 review: `accept` records the decision; `return` records it and creates a
    linked run (`parent_run_id`) over the same sources, statement and pack snapshot, with the
    note appended to the writer guidance. Returns the new run's id for a return."""
    async with db.session() as s, s.begin():
        run = await runs.get_run(s, run_id, lock=True)
        if RunState(run.state) is not RunState.COMPLETED:
            raise InvalidRunStateError(
                f"run {run_id} is {run.state}; only a completed run can be reviewed"
            )
        if action is ReviewAction.ACCEPT:
            await runs.add_review_event(s, run_id, action.value, note, actor, None)
            return None
        if not note.strip():
            raise InvalidRequestError("a return needs a note for the writer")
        source_ids = await runs.run_source_ids(s, run_id)
    reference = storage.get(run.docx_reference_key) if run.docx_reference_key else None
    guidance = f"{run.extra_guidance}\nReviewer note: {note.strip()}".strip()
    child = await _create_run(
        db,
        storage,
        cfg,
        prompts,
        RunRequest(
            project_id=run.project_id,
            source_ids=source_ids,
            value_statement=run.value_statement,
            profile=run.profile,
            max_iterations=run.max_iterations,
            extra_guidance=guidance,
            parent_run_id=run_id,
        ),
        pack_name=run.pack_name,
        pack_hash_=run.pack_hash,
        pack_snapshot=run.pack_snapshot,
        profile=run.profile,
        reference=reference,
    )
    async with db.session() as s, s.begin():
        await runs.add_review_event(s, run_id, action.value, note, actor, child)
    await queue.defer(TASK_RUN, lock=run_lock(child), run_id=str(child))
    return child


def _progress(run: Run, stages: list) -> RunProgress:
    return RunProgress(
        run_id=str(run.id),
        project_id=str(run.project_id),
        parent_run_id=str(run.parent_run_id) if run.parent_run_id else None,
        state=RunState(run.state),
        status=run.status,
        iteration=run.iteration,
        max_iterations=run.max_iterations,
        stages=stages,
        usage=Usage.model_validate(run.token_usage) if run.token_usage else None,
        cancel_requested=run.cancel_requested,
        attempts=run.attempts,
        error=run.error,
        export_error=run.export_error,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


async def run_progress(db: Database, run_id: uuid.UUID) -> RunProgress:
    async with db.session() as s:
        run = await runs.get_run(s, run_id)
        return _progress(run, await runs.load_stages(s, run_id))


async def get_run_record(db: Database, run_id: uuid.UUID) -> RunRecord:
    async with db.session() as s:
        return await records.load_record(s, run_id)


async def reference_document(db: Database, storage: Storage, run_id: uuid.UUID) -> bytes | None:
    """The DOCX reference the run was queued with, or None when its profile names none."""
    async with db.session() as s:
        run = await runs.get_run(s, run_id)
    return storage.get(run.docx_reference_key) if run.docx_reference_key else None
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_service.py tests/schema -v --no-cov`
Expected: PASS. Then `uv run pytest` and `uv run ruff check . && uv run ruff format --check .`: PASS, ≥ 95%, clean.

- [ ] **Step 7: Commit**

```bash
git add corelata/schema corelata/service.py corelata/testing/queue.py tests/test_service.py ../schema
git commit -m "feat: service layer for projects, sources, queued runs, cancel and review (M3 Task 5)"
```

---

### Task 6: Worker execution of a run — observer, restart, failure, exports

**Files:**
- Create: `engine/corelata/exports.py` (moved out of `cli.py`)
- Modify: `engine/corelata/cli.py` (import from `exports`), `engine/tests/test_cli.py` (one monkeypatch target)
- Create: `engine/corelata/worker/__init__.py`, `engine/corelata/worker/execute.py`
- Create: `engine/tests/worker/__init__.py`, `engine/tests/worker/conftest.py`, `engine/tests/worker/test_execute.py`

**Interfaces:**
- Consumes: `run_report(..., observer=)`, `RunOptions(created_at=, parent_run_id=)` (Task 3); `store.records`, `store.runs` (Tasks 2, 4); `service.TASK_RUN`, `service.TASK_DISCOVER`, `service.JobQueue`, `service.start_run` (Task 5); `render_outputs`.
- Produces: `exports.render_outputs`, `exports.write_outputs`, `exports.dump_json`, `exports.DocxExportError`, `exports.OUTPUT_FILES`, `exports.REPORT_FORMATS` (same behaviour as the `cli.py` functions they replace); `worker.execute.WorkerServices(cfg, db, storage, queue, backends, prompts)` with `call_log()` and `aclose()`; `worker.execute.DbObserver`; `worker.execute.execute_run(svc, run_id)`; `worker.execute.run_job(svc, task, kwargs)` (Task 7 adds the discover branch); `worker.execute.DB_ERRORS`.

- [ ] **Step 1: Move the export helpers out of the CLI**

Create `engine/corelata/exports.py` with the module docstring `"""A run's files (spec §7.2 rendering, §8.4 invariant 5): the same functions write a run directory for `corelata run` and the worker's stored exports."""` and move these from `cli.py` unchanged except for the renames shown: `OUTPUT_FILES`, `REPORT_FORMATS`, `_report_file`, `_trace_files`, `render_outputs`, `_json` → `dump_json` (public), `DocxExportError`, `write_outputs`. Imports the module needs: `json`, `Path`, `Iterable`, `render_docx`, `render_html`, `render_markdown`, `RunRecord`, `ResolvedPack`, `delivered_open_findings`.

In `cli.py`, delete the moved code and import it:

```python
from corelata.exports import (
    REPORT_FORMATS,
    DocxExportError,
    dump_json,
    render_outputs,
    write_outputs,
)
```

and replace the remaining `_json(` calls in `cli.py` with `dump_json(`. `tests/test_cli.py` imports `render_outputs` from `corelata.cli`; that still works through the import above. Change its one monkeypatch target `"corelata.cli.render_docx"` to `"corelata.exports.render_docx"`.

Run: `uv run pytest tests/test_cli.py -v --no-cov` — PASS before going on.

- [ ] **Step 2: Write the failing tests**

`engine/tests/worker/__init__.py`: empty.

`engine/tests/worker/conftest.py`:

```python
import uuid

import pytest

from corelata import service
from corelata.llm.payload import parse_input
from corelata.prompts.library import PromptLibrary
from corelata.schema import RunState
from corelata.storage import LocalStorage
from corelata.testing.queue import RecordingQueue
from corelata.worker.execute import WorkerServices, run_job
from tests.conftest import build_config
from tests.stages.conftest import PORT

STATEMENT = "Varna port capacity expansion matters to shippers"


def make_services(db, fake_backend, tmp_path, **cfg_overrides) -> WorkerServices:
    cfg = build_config(**cfg_overrides)
    return WorkerServices(
        cfg=cfg,
        db=db,
        storage=LocalStorage(tmp_path / "files"),
        queue=RecordingQueue(),
        backends={"fake": fake_backend},
        prompts=PromptLibrary(cfg.prompts_dir),
    )


@pytest.fixture
def services(db, fake_backend, tmp_path):
    return make_services(db, fake_backend, tmp_path)


async def submit(svc, *texts: str, statement: str = STATEMENT, project: str = "p", **opts):
    """A project, one source per text (the Varna paragraphs by default) and a queued run."""
    pid = await service.create_project(svc.db, project)
    ids: list[uuid.UUID] = []
    for i, text in enumerate(texts or ["\n\n".join(PORT)]):
        ids += await service.add_source(svc.db, svc.storage, pid, f"s{i}.txt", text.encode())
    req = service.RunRequest(project_id=pid, source_ids=ids, value_statement=statement, **opts)
    return await service.start_run(svc.db, svc.storage, svc.queue, svc.cfg, svc.prompts, req)


async def drain(svc, *, limit: int = 50) -> int:
    """Run queued jobs in order until the queue is empty (a deterministic in-test worker)."""
    count = 0
    while (job := svc.queue.pop()) is not None:
        await run_job(svc, job.task, job.kwargs)
        count += 1
        assert count < limit, "job loop did not settle"
    return count


async def state(db, run_id) -> RunState:
    return (await service.run_progress(db, run_id)).state


def tasks_sent(fake_backend) -> list[str]:
    return [parse_input([m.model_dump() for m in r.messages])["task"] for r in fake_backend.requests]
```

`engine/tests/worker/test_execute.py`:

```python
import uuid

import pytest
from docx import Document
from sqlalchemy import select

from corelata import service
from corelata.config import config_hash
from corelata.exports import render_outputs
from corelata.llm.payload import parse_input
from corelata.llm.types import PermanentBackendError
from corelata.schema import ReportStatus, RunState
from corelata.standards.schema import ResolvedPack
from corelata.store import runs
from corelata.store.models import DraftRow, LLMCall, StageResultRow
from corelata.testing.fake_backend import FakeBackend
from corelata.worker import execute
from corelata.worker.execute import run_job
from tests.standards.test_loader import write_pack
from tests.worker.conftest import drain, make_services, state, submit, tasks_sent

EXPORTS = {"trace.json", "gate.json", "report.json", "report.md", "report.html", "report.docx"}


def _as_bytes(value: str | bytes) -> bytes:
    return value if isinstance(value, bytes) else value.encode("utf-8")


async def _exports(svc, run_id) -> dict[str, bytes]:
    async with svc.db.session() as s:
        rows = await runs.list_exports(s, run_id)
    return {r.name: svc.storage.get(r.storage_key) for r in rows}


async def test_a_queued_run_completes_and_its_exports_are_reproducible(services):
    run_id = await submit(services)
    assert await drain(services) == 1
    progress = await service.run_progress(services.db, run_id)
    assert progress.state is RunState.COMPLETED and progress.status is ReportStatus.CLEAN
    assert progress.attempts == 1 and progress.finished_at is not None
    assert [s.stage for s in progress.stages] == [
        "ingesting", "gating", "drafting", "conveying", "auditing", "rendering",
    ]
    assert progress.usage is not None and progress.usage.calls == 4
    stored = await _exports(services, run_id)
    assert set(stored) == EXPORTS and stored["report.docx"][:2] == b"PK"
    record = await service.get_run_record(services.db, run_id)
    pack = ResolvedPack.model_validate(record.pack_snapshot)
    again = render_outputs(record, pack, with_claim_ids=False)
    assert {k: _as_bytes(v) for k, v in again.items()} == stored  # spec §8.4 invariant 5
    assert record.report is not None and record.report.metadata.run_id == str(run_id)
    async with services.db.session() as s:
        rows = (await s.scalars(select(LLMCall).order_by(LLMCall.ordinal))).all()
        assert [r.stage for r in rows] == ["gating", "drafting", "conveying", "auditing"]
        assert all(r.request is not None for r in rows)


class _Spy(FakeBackend):
    """Looks at the run from outside while the writer is being called."""

    def __init__(self) -> None:
        super().__init__(name="fake")
        self.db = None
        self.run_id = None
        self.seen = None
        self.cancel = False

    async def chat(self, request):
        payload = parse_input([m.model_dump() for m in request.messages])
        if payload["task"] == "writer" and self.seen is None:
            self.seen = await service.run_progress(self.db, self.run_id)
            if self.cancel:
                await service.cancel_run(self.db, self.run_id)
        return await super().chat(request)


async def test_progress_is_visible_while_the_run_executes(db, tmp_path):
    spy = _Spy()
    svc = make_services(db, spy, tmp_path)
    run_id = await submit(svc)
    spy.db, spy.run_id = db, run_id
    await drain(svc)
    assert spy.seen is not None
    assert spy.seen.state is RunState.DRAFTING and spy.seen.attempts == 1
    assert [s.stage for s in spy.seen.stages] == ["ingesting", "gating"]
    assert spy.seen.usage is not None and spy.seen.usage.calls == 1
    assert spy.seen.started_at is not None and spy.seen.finished_at is None


async def test_cancel_during_drafting_stops_before_the_conveyor(db, tmp_path):
    spy = _Spy()
    spy.cancel = True
    svc = make_services(db, spy, tmp_path)
    run_id = await submit(svc)
    spy.db, spy.run_id = db, run_id
    await drain(svc)
    assert tasks_sent(spy) == ["gate", "writer"]
    progress = await service.run_progress(db, run_id)
    assert progress.state is RunState.CANCELLED and progress.cancel_requested
    assert progress.status is None and progress.error is None and progress.finished_at
    assert [s.stage for s in progress.stages] == ["ingesting", "gating", "drafting"]
    record = await service.get_run_record(db, run_id)
    assert record.report is None and [d.role for d in record.drafts] == ["writer"]
    assert len(record.llm_calls) == 2
    assert set(await _exports(svc, run_id)) == {"trace.json", "gate.json"}


async def test_cancel_before_the_worker_starts_leaves_the_job_a_no_op(services, fake_backend):
    run_id = await submit(services)
    await service.cancel_run(services.db, run_id)
    await drain(services)
    assert fake_backend.requests == []
    progress = await service.run_progress(services.db, run_id)
    assert progress.state is RunState.CANCELLED and progress.attempts == 0


async def test_a_cancel_flag_seen_at_job_start_ends_the_run(services, fake_backend):
    run_id = await submit(services)
    async with services.db.session() as s, s.begin():
        (await runs.get_run(s, run_id, lock=True)).cancel_requested = True  # state still created
    await drain(services)
    assert fake_backend.requests == []
    assert await state(services.db, run_id) is RunState.CANCELLED


async def test_a_redelivered_job_for_a_finished_run_does_nothing(services, fake_backend):
    run_id = await submit(services)
    await drain(services)
    calls = len(fake_backend.requests)
    await run_job(services, service.TASK_RUN, {"run_id": str(run_id)})
    assert len(fake_backend.requests) == calls
    assert (await service.run_progress(services.db, run_id)).attempts == 1


async def test_a_crashed_execution_is_started_over(services, fake_backend, caplog):
    run_id = await submit(services)
    async with services.db.session() as s, s.begin():  # what a worker that died mid-run leaves
        run = await runs.get_run(s, run_id, lock=True)
        run.state, run.attempts, run.iteration = "drafting", 1, 0
        from datetime import UTC, datetime

        t = datetime(2026, 10, 13, tzinfo=UTC)
        s.add(StageResultRow(run_id=run_id, ordinal=0, stage="ingesting", iteration=0, ok=True,
                             started_at=t, finished_at=t))
        s.add(StageResultRow(run_id=run_id, ordinal=1, stage="gating", iteration=0, ok=True,
                             started_at=t, finished_at=t))
        s.add(LLMCall(run_id=run_id, ordinal=0, stage="gating", role="gate", backend="fake",
                      model="m", prompt_id="gate", prompt_version=1, attempt=1, ok=True,
                      latency_ms=1))
    await drain(services)
    progress = await service.run_progress(services.db, run_id)
    assert progress.state is RunState.COMPLETED and progress.attempts == 2
    assert [s.stage for s in progress.stages].count("ingesting") == 1
    record = await service.get_run_record(services.db, run_id)
    assert len(record.llm_calls) == 4 == record.usage.calls
    assert "restarted" in caplog.text


async def test_an_unexpected_error_fails_the_run_without_a_traceback_in_the_row(
    services, monkeypatch
):
    async def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(execute, "run_report", boom)
    run_id = await submit(services)
    await drain(services)
    progress = await service.run_progress(services.db, run_id)
    assert progress.state is RunState.FAILED
    assert progress.error == "internal error: RuntimeError: boom"
    assert progress.finished_at is not None and progress.attempts == 1
    assert await _exports(services, run_id) == {}


async def test_a_model_failure_ends_failed_with_the_calls_on_record(services, fake_backend):
    fake_backend.script("gate", PermanentBackendError("down"), PermanentBackendError("down"))
    run_id = await submit(services)
    await drain(services)
    progress = await service.run_progress(services.db, run_id)
    assert progress.state is RunState.FAILED and "down" in (progress.error or "")
    assert [s.ok for s in progress.stages] == [True, False, False]
    record = await service.get_run_record(services.db, run_id)
    assert len(record.llm_calls) == 2 and not any(c.ok for c in record.llm_calls)
    assert set(await _exports(services, run_id)) == {"trace.json"}


async def test_a_missing_reference_document_fails_the_run(services):
    run_id = await submit(services)
    async with services.db.session() as s, s.begin():
        (await runs.get_run(s, run_id, lock=True)).docx_reference_key = "runs/x/reference.docx"
    await drain(services)
    progress = await service.run_progress(services.db, run_id)
    assert progress.state is RunState.FAILED
    assert progress.error.startswith("internal error: StorageError: stored file not found")


def _house_pack(tmp_path):
    pack = write_pack(
        tmp_path / "packs", "house", rules=[], extends="icd203-base", template=None, lexicon=None,
        profiles={"east": {"name": "east", "extends": "house",
                           "format": {"docx_reference": "templates/east.docx"}}},
    )
    (pack / "templates").mkdir()
    doc = Document()
    doc.sections[0].header.paragraphs[0].text = "HOUSE STYLE"
    doc.save(str(pack / "templates" / "east.docx"))
    return {"packs_dir": str(tmp_path / "packs"), "default_pack": "house"}


async def test_the_run_renders_with_the_stored_reference_even_after_it_changed(
    db, fake_backend, tmp_path
):
    svc = make_services(db, fake_backend, tmp_path, standards=_house_pack(tmp_path))
    run_id = await submit(svc, profile="east")
    (tmp_path / "packs" / "house" / "templates" / "east.docx").unlink()  # Review Focus 4
    await drain(svc)
    progress = await service.run_progress(db, run_id)
    assert progress.state is RunState.COMPLETED and progress.export_error is None
    docx = (await _exports(svc, run_id))["report.docx"]
    import io

    rendered = Document(io.BytesIO(docx))
    assert any("UNCLASSIFIED" in p.text for p in rendered.sections[0].header.paragraphs)
    assert rendered.sections[0].page_width == Document().sections[0].page_width


async def test_a_broken_reference_document_fails_only_the_docx_export(db, fake_backend, tmp_path):
    svc = make_services(db, fake_backend, tmp_path, standards=_house_pack(tmp_path))
    run_id = await submit(svc, profile="east")
    svc.storage.put(f"runs/{run_id}/reference.docx", b"not a docx at all")
    await drain(svc)
    progress = await service.run_progress(db, run_id)
    assert progress.state is RunState.COMPLETED and progress.status is ReportStatus.CLEAN
    assert progress.export_error is not None and progress.export_error.startswith("DOCX export failed")
    assert set(await _exports(svc, run_id)) == EXPORTS - {"report.docx"}


async def test_a_configuration_change_since_submit_is_recorded(services, caplog):
    run_id = await submit(services)
    old = config_hash(services.cfg)
    pipeline = services.cfg.pipeline.model_copy(update={"max_iterations": 3})
    services.cfg = services.cfg.model_copy(update={"pipeline": pipeline})
    await drain(services)
    record = await service.get_run_record(services.db, run_id)
    assert record.config_hash == config_hash(services.cfg) != old
    assert record.max_iterations == 2  # the run's own bound, chosen at submit, is kept
    assert "configuration changed" in caplog.text


async def test_store_llm_io_off_keeps_no_prompts_or_replies(db, fake_backend, tmp_path):
    svc = make_services(db, fake_backend, tmp_path, audit={"store_llm_io": False})
    run_id = await submit(svc)
    await drain(svc)
    async with db.session() as s:
        rows = (await s.scalars(select(LLMCall))).all()
    assert rows and all(r.request is None and r.response is None for r in rows)


async def test_drafts_and_findings_are_stored_once(services):
    run_id = await submit(services, "\n\n".join(["Varna port capacity grew.", "UNSOURCED claim"]))
    await drain(services)
    record = await service.get_run_record(services.db, run_id)
    async with services.db.session() as s:
        drafts = (await s.scalars(select(DraftRow))).all()
    assert len(drafts) == len(record.drafts) >= 2
    assert record.findings and record.iterations >= 1


async def test_run_job_rejects_unknown_tasks_and_closes_cleanly(services, fake_backend):
    with pytest.raises(ValueError, match="unknown job"):
        await run_job(services, "corelata.nope", {"run_id": str(uuid.uuid4())})
    await services.aclose()
    assert fake_backend.closed


async def test_a_job_for_an_unknown_run_is_skipped(services, caplog):
    await run_job(services, service.TASK_RUN, {"run_id": str(uuid.uuid4())})
    assert "skipped" in caplog.text
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/worker -v --no-cov`
Expected: FAIL with `ModuleNotFoundError: No module named 'corelata.worker'`.

- [ ] **Step 4: Write the worker execution module**

`engine/corelata/worker/__init__.py`:

```python
"""The queue worker (spec §4.2, §7.5): job bodies in execute.py, procrastinate wiring in app.py."""
```

`engine/corelata/worker/execute.py`:

```python
"""Worker job bodies (spec §7.2, §7.5). A run is one job: the pipeline executes in-process with
an observer that writes every state change, stage result and model call to Postgres as it
happens, so progress is visible and a cancel is honoured at the next stage. A job delivered
again for a finished run does nothing; one delivered for a run whose earlier execution died
starts the run over (model calls are not replayable, and a run is minutes, spec §16). No
transaction is held across a model call."""

import contextlib
import logging
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.exc import InterfaceError, OperationalError

from corelata.config import CorelataConfig, config_hash
from corelata.exports import render_outputs
from corelata.llm.agent import CallLog
from corelata.llm.types import Backend
from corelata.pipeline import RunOptions, run_report
from corelata.prompts.library import PromptLibrary
from corelata.schema import TERMINAL_STATES, RunRecord, RunState, Source, StageResult
from corelata.service import TASK_RUN, JobQueue
from corelata.standards.schema import ResolvedPack
from corelata.storage import Storage
from corelata.store import records, runs
from corelata.store.db import Database
from corelata.store.models import utcnow

log = logging.getLogger("corelata.worker")

DB_ERRORS: tuple[type[Exception], ...] = (OperationalError, InterfaceError)


@dataclass
class WorkerServices:
    cfg: CorelataConfig
    db: Database
    storage: Storage
    queue: JobQueue
    backends: dict[str, Backend]
    prompts: PromptLibrary

    def call_log(self) -> CallLog:
        return CallLog(store_io=self.cfg.audit.store_llm_io)

    async def aclose(self) -> None:
        for backend in self.backends.values():
            await backend.aclose()
        await self.db.dispose()


def _internal(e: BaseException) -> str:
    return f"internal error: {type(e).__name__}: {e}"


class DbObserver:
    """The pipeline's observer for a queued run: short transactions between model calls."""

    def __init__(self, db: Database, run_id: uuid.UUID, calls: CallLog) -> None:
        self.db = db
        self.run_id = run_id
        self.calls = calls
        self.stages_saved = 0
        self.calls_saved = 0

    async def state_changed(self, record: RunRecord) -> None:
        async with self.db.session() as s, s.begin():
            run = await runs.get_run(s, self.run_id, lock=True)
            run.state = record.state.value

    async def stage_recorded(self, record: RunRecord, result: StageResult) -> None:
        new = self.calls.records[self.calls_saved :]
        async with self.db.session() as s, s.begin():
            run = await runs.get_run(s, self.run_id, lock=True)
            run.state = record.state.value
            run.iteration = result.iteration
            run.token_usage = self.calls.usage().model_dump()
            await runs.add_stage(s, self.run_id, self.stages_saved, result)
            await runs.add_llm_calls(s, self.run_id, self.calls_saved, new, stage=result.stage)
        self.stages_saved += 1
        self.calls_saved += len(new)

    async def cancel_requested(self) -> bool:
        async with self.db.session() as s:
            return await runs.cancel_flag(s, self.run_id)


@dataclass
class _Inputs:
    sources: list[Source]
    source_ids: list[uuid.UUID]
    pack_snapshot: dict
    value_statement: str
    profile: str | None
    max_iterations: int
    extra_guidance: str
    parent_run_id: str | None
    docx_reference_key: str | None
    created_at: datetime


async def _begin(svc: WorkerServices, run_id: uuid.UUID) -> _Inputs | None:
    """Claim the run under its row lock. None: nothing to do (finished, or cancelled before any
    work). A run left mid-flight by a dead worker is wiped and started over."""
    async with svc.db.session() as s, s.begin():
        run = await runs.get_run(s, run_id, lock=True)
        if RunState(run.state) in TERMINAL_STATES:
            log.info("run %s is already %s", run_id, run.state, extra={"run_id": str(run_id)})
            return None
        if run.cancel_requested:
            run.state, run.finished_at = RunState.CANCELLED.value, utcnow()
            return None
        if run.attempts:
            log.warning(
                "run %s restarted: its earlier execution did not finish",
                run_id,
                extra={"run_id": str(run_id)},
            )
            await runs.clear_trace(s, run_id)
        run.attempts += 1
        run.started_at, run.finished_at = utcnow(), None
        run.error = run.export_error = run.status = run.report = run.gate = None
        run.digests, run.token_usage, run.iteration = [], None, 0
        live = config_hash(svc.cfg)
        if live != run.config_hash:
            log.warning(
                "run %s: configuration changed since it was queued (%s -> %s); running with the "
                "current configuration",
                run_id,
                run.config_hash,
                live,
                extra={"run_id": str(run_id)},
            )
            run.config_hash = live
            run.config_snapshot = svc.cfg.model_dump(mode="json")
        return _Inputs(
            sources=await records.load_sources(s, run_id),
            source_ids=await runs.run_source_ids(s, run_id),
            pack_snapshot=run.pack_snapshot,
            value_statement=run.value_statement,
            profile=run.profile,
            max_iterations=run.max_iterations,
            extra_guidance=run.extra_guidance,
            parent_run_id=str(run.parent_run_id) if run.parent_run_id else None,
            docx_reference_key=run.docx_reference_key,
            created_at=run.created_at,
        )


@contextlib.contextmanager
def _reference(storage: Storage, key: str | None) -> Iterator[Path | None]:
    if key is None:
        yield None
        return
    with storage.local_file(key) as path:
        yield path


def _render(record: RunRecord, pack: ResolvedPack) -> tuple[dict[str, bytes], str | None]:
    """Every export as bytes. The DOCX is the only render that reads a file (the reference
    document); its failure is reported, not fatal: the trace and the other renders stand."""
    files = {
        name: content if isinstance(content, bytes) else content.encode("utf-8")
        for name, content in render_outputs(
            record, pack, with_claim_ids=False, formats=("json", "md", "html")
        ).items()
    }
    if record.report is None:
        return files, None
    try:
        docx = render_outputs(
            record,
            pack,
            with_claim_ids=False,
            docx_reference=pack.docx_reference_path,
            formats=("docx",),
        )["report.docx"]
    except Exception as e:  # noqa: BLE001 - whatever the reference document provokes
        return files, f"DOCX export failed: {e or type(e).__name__}"
    assert isinstance(docx, bytes)
    files["report.docx"] = docx
    return files, None


async def _fail_run(
    svc: WorkerServices, run_id: uuid.UUID, message: str, observer: DbObserver
) -> None:
    async with svc.db.session() as s, s.begin():
        run = await runs.get_run(s, run_id, lock=True)
        new = observer.calls.records[observer.calls_saved :]
        await runs.add_llm_calls(s, run_id, observer.calls_saved, new, stage=run.state)
        run.token_usage = observer.calls.usage().model_dump()
        if RunState(run.state) not in TERMINAL_STATES:
            run.state, run.error, run.finished_at = RunState.FAILED.value, message, utcnow()


async def execute_run(svc: WorkerServices, run_id: uuid.UUID) -> None:
    inputs = await _begin(svc, run_id)
    if inputs is None:
        return
    pack = ResolvedPack.model_validate(inputs.pack_snapshot)
    observer = DbObserver(svc.db, run_id, svc.call_log())
    try:
        with _reference(svc.storage, inputs.docx_reference_key) as reference:
            pack.docx_reference_path = reference
            record = await run_report(
                svc.cfg,
                inputs.sources,
                RunOptions(
                    value_statement=inputs.value_statement,
                    profile=inputs.profile,
                    max_iterations=inputs.max_iterations,
                    extra_guidance=inputs.extra_guidance,
                    run_id=str(run_id),
                    parent_run_id=inputs.parent_run_id,
                    created_at=inputs.created_at,
                ),
                backends=svc.backends,
                prompts=svc.prompts,
                log=observer.calls,
                pack=pack,
                observer=observer,
            )
            files, export_error = _render(record, pack)
    except DB_ERRORS:
        raise
    except Exception as e:
        log.exception("run %s failed", run_id, extra={"run_id": str(run_id)})
        await _fail_run(svc, run_id, _internal(e), observer)
        return
    try:
        async with svc.db.session() as s, s.begin():
            run = await runs.get_run(s, run_id, lock=True)
            await records.save_outcome(
                s,
                run,
                record,
                source_ids=inputs.source_ids,
                stages_from=observer.stages_saved,
                calls_from=observer.calls_saved,
            )
            run.export_error = export_error
            for name, data in files.items():
                key = f"runs/{run_id}/{name}"
                svc.storage.put(key, data)
                await runs.add_export(s, run_id, name, key, data)
    except DB_ERRORS:
        raise
    except Exception as e:
        log.exception("saving run %s failed", run_id, extra={"run_id": str(run_id)})
        await _fail_run(svc, run_id, _internal(e), observer)
        return
    log.info(
        "run %s finished: %s",
        run_id,
        record.state.value,
        extra={"run_id": str(run_id), "state": record.state.value},
    )


async def run_job(svc: WorkerServices, task: str, kwargs: dict[str, str]) -> None:
    """Dispatch one queue job. A job for a deleted run is skipped (not an error)."""
    try:
        if task == TASK_RUN:
            await execute_run(svc, uuid.UUID(kwargs["run_id"]))
        else:
            raise ValueError(f"unknown job '{task}'")
    except runs.NotFoundError as e:
        log.info("job skipped: %s", e)
```

(Add `from datetime import datetime` to the imports for `_Inputs.created_at`.)

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/worker -v --no-cov`
Expected: PASS. Notes for failures you may see:
- `test_a_queued_run_completes...` usage.calls == 4: gate, writer, conveyor, auditor against the fake backend with the Varna source (no digests, clean first audit). If the synthetic auditor loops on these paragraphs, adjust the expected call count to the observed one and say so in the report.
- `test_the_run_renders_with_the_stored_reference...`: the M2 DOCX renderer marks every header with the handling marking and strips the old header text; the test checks the marking is present and the page geometry is the reference's (equal to python-docx's default here, since both came from `Document()`).

Then `uv run pytest` and `uv run ruff check . && uv run ruff format --check .`: PASS, ≥ 95%, clean.

- [ ] **Step 6: Commit**

```bash
git add corelata/exports.py corelata/cli.py corelata/worker tests/test_cli.py tests/worker
git commit -m "feat: worker execution of a run with live progress, cancel, restart and stored exports (M3 Task 6)"
```

---

### Task 7: Discovery job

**Files:**
- Create: `engine/corelata/store/discoveries.py`
- Modify: `engine/corelata/service.py` (add `start_discovery`, `get_discovery`)
- Modify: `engine/corelata/worker/execute.py` (add `execute_discovery`, the `run_job` branch)
- Create: `engine/tests/store/test_discoveries.py`, `engine/tests/worker/test_discover.py`

**Interfaces:**
- Consumes: `Discovery`, `DiscoverySource`, `DiscoveryCandidate` rows (Task 2); `DiscoveryState`, `DiscoveryView` (Task 5); `pipeline.discover(cfg, sources, *, backends, prompts, log, audience_hint, pack)`; `load_run_pack`.
- Produces: `store.discoveries.create(s, *, project_id, source_ids, audience_hint) -> Discovery`, `get(s, discovery_id, *, lock=False) -> Discovery`, `source_ids(s, discovery_id) -> list[uuid.UUID]`, `set_candidates(s, discovery_id, result: DiscoveryResult) -> None`, `view(s, discovery_id) -> DiscoveryView`; `service.start_discovery(db, queue, project_id, source_ids, audience_hint="") -> uuid.UUID`, `service.get_discovery(db, discovery_id) -> DiscoveryView`; `worker.execute.execute_discovery(svc, discovery_id)`; `run_job` dispatches `TASK_DISCOVER` with `{"discovery_id": ...}`.

- [ ] **Step 1: Write the failing tests**

`engine/tests/store/test_discoveries.py`:

```python
import uuid

import pytest

from corelata.schema import CandidateStatement, DiscoveryResult, DiscoveryState
from corelata.store import discoveries, runs
from corelata.testing.sources import text_source


async def _project_with_sources(s, n=2, name="p"):
    project = await runs.get_or_create_project(s, name)
    rows = [
        await runs.add_source(s, project.id, text_source(f"x{i}", f"text {i}"), storage_key=f"k{i}")
        for i in range(n)
    ]
    return project, rows


async def test_create_get_and_view(db):
    async with db.session() as s, s.begin():
        project, (a, b) = await _project_with_sources(s)
        row = await discoveries.create(
            s, project_id=project.id, source_ids=[b.id, a.id], audience_hint="shippers"
        )
    async with db.session() as s, s.begin():
        got = await discoveries.get(s, row.id, lock=True)
        assert got.state == "created" and got.audience_hint == "shippers"
        assert await discoveries.source_ids(s, row.id) == [b.id, a.id]
        view = await discoveries.view(s, row.id)
    assert view.state is DiscoveryState.CREATED and view.candidates == [] and view.usage is None
    assert view.source_ids == [str(b.id), str(a.id)] and view.project_id == str(project.id)
    assert view.discovery_id == str(row.id) and view.created_at.tzinfo is not None
    async with db.session() as s:
        with pytest.raises(runs.NotFoundError, match="not found"):
            await discoveries.get(s, uuid.uuid4())
        with pytest.raises(runs.NotFoundError, match="not found"):
            await discoveries.view(s, uuid.uuid4())


async def test_create_rejects_a_foreign_source(db):
    async with db.session() as s, s.begin():
        project, (a, _) = await _project_with_sources(s, name="p1")
        _, (foreign, _) = await _project_with_sources(s, name="p2")
        with pytest.raises(runs.NotFoundError, match="not in project"):
            await discoveries.create(
                s, project_id=project.id, source_ids=[a.id, foreign.id], audience_hint=""
            )


async def test_candidates_replace_earlier_ones(db):
    result = DiscoveryResult(
        candidates=[
            CandidateStatement(text="A", audience="ops", evidence=["src1/u1"], confidence_note="n"),
            CandidateStatement(text="B", audience="ops"),
        ]
    )
    async with db.session() as s, s.begin():
        project, (a, _) = await _project_with_sources(s)
        row = await discoveries.create(s, project_id=project.id, source_ids=[a.id], audience_hint="")
        await discoveries.set_candidates(s, row.id, result)
        await discoveries.set_candidates(s, row.id, result)
    async with db.session() as s:
        view = await discoveries.view(s, row.id)
    assert view.candidates == result.candidates
```

`engine/tests/worker/test_discover.py`:

```python
import uuid

import pytest

from corelata import service
from corelata.llm.types import PermanentBackendError
from corelata.schema import DiscoveryState
from corelata.store import discoveries
from corelata.worker.execute import run_job
from tests.stages.conftest import PORT
from tests.worker.conftest import drain, tasks_sent


async def _queue_discovery(svc, *texts, audience_hint=""):
    pid = await service.create_project(svc.db, "p")
    ids = []
    for i, text in enumerate(texts or ["\n\n".join(PORT), "Shippers welcomed the capacity."]):
        ids += await service.add_source(svc.db, svc.storage, pid, f"d{i}.txt", text.encode())
    did = await service.start_discovery(svc.db, svc.queue, pid, ids, audience_hint)
    return did, ids


async def test_a_discovery_runs_through_the_queue(services, fake_backend):
    did, ids = await _queue_discovery(services, audience_hint="port operators")
    assert [(j.task, j.lock, j.kwargs) for j in services.queue.jobs] == [
        (service.TASK_DISCOVER, f"discovery:{did}", {"discovery_id": str(did)})
    ]
    assert await drain(services) == 1
    view = await service.get_discovery(services.db, did)
    assert view.state is DiscoveryState.COMPLETED and view.error is None
    assert len(view.candidates) == 2  # the synthetic gate proposes one per source
    assert view.source_ids == [str(i) for i in ids]
    assert view.usage is not None and view.usage.calls == 1
    assert view.started_at is not None and view.finished_at is not None
    assert tasks_sent(fake_backend) == ["discover"]
    from corelata.llm.payload import parse_input

    payload = parse_input([m.model_dump() for m in fake_backend.requests[0].messages])
    assert payload["audience_hint"] == "port operators"
    async with services.db.session() as s:
        row = await discoveries.get(s, did)
    assert len(row.llm_calls) == 1 and row.llm_calls[0]["role"] == "gate"


async def test_a_model_failure_ends_the_discovery_failed(services, fake_backend):
    fake_backend.script("discover", PermanentBackendError("down"), PermanentBackendError("down"))
    did, _ = await _queue_discovery(services)
    await drain(services)
    view = await service.get_discovery(services.db, did)
    assert view.state is DiscoveryState.FAILED and "down" in (view.error or "")
    assert view.candidates == [] and view.finished_at is not None


async def test_an_unexpected_error_is_recorded(services, monkeypatch):
    from corelata.worker import execute

    async def boom(*a, **k):
        raise RuntimeError("kaput")

    monkeypatch.setattr(execute, "discover", boom)
    did, _ = await _queue_discovery(services)
    await drain(services)
    view = await service.get_discovery(services.db, did)
    assert view.state is DiscoveryState.FAILED
    assert view.error == "internal error: RuntimeError: kaput"


async def test_a_redelivered_discovery_job_does_nothing(services, fake_backend):
    did, _ = await _queue_discovery(services)
    await drain(services)
    await run_job(services, service.TASK_DISCOVER, {"discovery_id": str(did)})
    assert len(fake_backend.requests) == 1


async def test_a_discovery_left_running_by_a_dead_worker_is_redone(services, fake_backend, caplog):
    did, _ = await _queue_discovery(services)
    async with services.db.session() as s, s.begin():
        (await discoveries.get(s, did, lock=True)).state = "running"
    await drain(services)
    view = await service.get_discovery(services.db, did)
    assert view.state is DiscoveryState.COMPLETED and len(fake_backend.requests) == 1
    assert "restarted" in caplog.text


async def test_start_discovery_validates(services):
    pid = await service.create_project(services.db, "p")
    with pytest.raises(service.InvalidRequestError, match="at least one source"):
        await service.start_discovery(services.db, services.queue, pid, [])
    with pytest.raises(service.InvalidRequestError, match="at least one source"):
        await service.start_discovery(services.db, services.queue, pid, [], "x")
    assert services.queue.jobs == []


async def test_a_job_for_an_unknown_discovery_is_skipped(services, caplog):
    await run_job(services, service.TASK_DISCOVER, {"discovery_id": str(uuid.uuid4())})
    assert "skipped" in caplog.text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/store/test_discoveries.py tests/worker/test_discover.py -v --no-cov`
Expected: FAIL with `ModuleNotFoundError: No module named 'corelata.store.discoveries'`.

- [ ] **Step 3: Write the discovery data access**

`engine/corelata/store/discoveries.py`:

```python
"""Discovery rows (spec §7.1): a job that proposes value statements over chosen sources."""

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from corelata.llm.agent import CallLog
from corelata.schema import (
    CandidateStatement,
    DiscoveryResult,
    DiscoveryState,
    DiscoveryView,
    LLMCallRecord,
)
from corelata.store import runs
from corelata.store.models import Discovery, DiscoveryCandidate, DiscoverySource


async def create(
    s: AsyncSession, *, project_id: uuid.UUID, source_ids: list[uuid.UUID], audience_hint: str
) -> Discovery:
    known = {r.id for r in await runs.list_sources(s, project_id)}
    for sid in source_ids:
        if sid not in known:
            raise runs.NotFoundError(f"source {sid} not in project {project_id}")
    row = Discovery(project_id=project_id, audience_hint=audience_hint, llm_calls=[])
    s.add(row)
    await s.flush()
    s.add_all(
        DiscoverySource(discovery_id=row.id, ordinal=i, source_id=sid)
        for i, sid in enumerate(source_ids, start=1)
    )
    await s.flush()
    return row


async def get(s: AsyncSession, discovery_id: uuid.UUID, *, lock: bool = False) -> Discovery:
    query = select(Discovery).where(Discovery.id == discovery_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    row = await s.scalar(query)
    if row is None:
        raise runs.NotFoundError(f"discovery {discovery_id} not found")
    return row


async def source_ids(s: AsyncSession, discovery_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        await s.scalars(
            select(DiscoverySource.source_id)
            .where(DiscoverySource.discovery_id == discovery_id)
            .order_by(DiscoverySource.ordinal)
        )
    )


async def set_candidates(s: AsyncSession, discovery_id: uuid.UUID, result: DiscoveryResult) -> None:
    await s.execute(
        delete(DiscoveryCandidate).where(DiscoveryCandidate.discovery_id == discovery_id)
    )
    s.add_all(
        DiscoveryCandidate(
            discovery_id=discovery_id,
            ordinal=i,
            text=c.text,
            audience=c.audience,
            evidence=list(c.evidence),
            confidence_note=c.confidence_note,
        )
        for i, c in enumerate(result.candidates, start=1)
    )
    await s.flush()


async def view(s: AsyncSession, discovery_id: uuid.UUID) -> DiscoveryView:
    row = await get(s, discovery_id)
    candidates = await s.scalars(
        select(DiscoveryCandidate)
        .where(DiscoveryCandidate.discovery_id == discovery_id)
        .order_by(DiscoveryCandidate.ordinal)
    )
    calls = [LLMCallRecord.model_validate(c) for c in row.llm_calls]
    return DiscoveryView(
        discovery_id=str(row.id),
        project_id=str(row.project_id),
        state=DiscoveryState(row.state),
        audience_hint=row.audience_hint,
        source_ids=[str(sid) for sid in await source_ids(s, discovery_id)],
        candidates=[
            CandidateStatement(
                text=c.text,
                audience=c.audience,
                evidence=list(c.evidence),
                confidence_note=c.confidence_note,
            )
            for c in candidates
        ],
        usage=CallLog(records=calls).usage() if calls else None,
        error=row.error,
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
    )
```

- [ ] **Step 4: Add the service functions**

Append to `engine/corelata/service.py` (and add `from corelata.store import discoveries` and `DiscoveryView` to the schema import):

```python
# ---------------------------------------------------------------- discovery (spec §7.1)


async def start_discovery(
    db: Database,
    queue: JobQueue,
    project_id: uuid.UUID,
    source_ids: list[uuid.UUID],
    audience_hint: str = "",
) -> uuid.UUID:
    """Queue a discovery over the chosen sources. It never starts a run by itself."""
    if not source_ids:
        raise InvalidRequestError("a discovery needs at least one source")
    async with db.session() as s, s.begin():
        row = await discoveries.create(
            s, project_id=project_id, source_ids=source_ids, audience_hint=audience_hint.strip()
        )
    await queue.defer(TASK_DISCOVER, lock=discovery_lock(row.id), discovery_id=str(row.id))
    return row.id


async def get_discovery(db: Database, discovery_id: uuid.UUID) -> DiscoveryView:
    async with db.session() as s:
        return await discoveries.view(s, discovery_id)
```

- [ ] **Step 5: Add the worker job**

In `engine/corelata/worker/execute.py`, add imports `from corelata.pipeline import RunOptions, discover, load_run_pack, run_report`, `from corelata.service import TASK_DISCOVER, TASK_RUN, JobQueue`, `from corelata.schema import DiscoveryState` (extend the existing schema import) and `from corelata.store import discoveries, records, runs`, then add:

```python
async def execute_discovery(svc: WorkerServices, discovery_id: uuid.UUID) -> None:
    """One discovery job (spec §7.1). Finished discoveries are left alone; one a dead worker
    left `running` is done again."""
    async with svc.db.session() as s, s.begin():
        row = await discoveries.get(s, discovery_id, lock=True)
        state = DiscoveryState(row.state)
        if state in (DiscoveryState.COMPLETED, DiscoveryState.FAILED):
            return
        if state is DiscoveryState.RUNNING:
            log.warning("discovery %s restarted: its earlier execution did not finish", discovery_id)
        row.state, row.started_at, row.error = DiscoveryState.RUNNING.value, utcnow(), None
        ids = await discoveries.source_ids(s, discovery_id)
        sources = [
            await runs.load_source(s, await runs.get_source(s, sid), as_id=f"src{i}")
            for i, sid in enumerate(ids, start=1)
        ]
        audience_hint = row.audience_hint
    calls = svc.call_log()
    error: str | None = None
    result = None
    try:
        result = await discover(
            svc.cfg,
            sources,
            backends=svc.backends,
            prompts=svc.prompts,
            log=calls,
            audience_hint=audience_hint,
            pack=load_run_pack(svc.cfg, None),
        )
    except DB_ERRORS:
        raise
    except (*AGENT_FAILURES, StageError, PackError, ValueError) as e:
        error = str(e)
    except Exception as e:  # noqa: BLE001 - recorded, never raised out of a job
        log.exception("discovery %s failed", discovery_id)
        error = _internal(e)
    async with svc.db.session() as s, s.begin():
        row = await discoveries.get(s, discovery_id, lock=True)
        row.llm_calls = [r.model_dump(mode="json") for r in calls.records]
        row.token_usage = calls.usage().model_dump()
        row.finished_at = utcnow()
        if result is not None:
            await discoveries.set_candidates(s, discovery_id, result)
            row.state = DiscoveryState.COMPLETED.value
        else:
            row.state, row.error = DiscoveryState.FAILED.value, error
```

with `from corelata.llm.agent import AGENT_FAILURES, CallLog`, `from corelata.stages.context import StageError` and `from corelata.standards.loader import PackError` added to the imports. Extend `run_job`:

```python
        if task == TASK_RUN:
            await execute_run(svc, uuid.UUID(kwargs["run_id"]))
        elif task == TASK_DISCOVER:
            await execute_discovery(svc, uuid.UUID(kwargs["discovery_id"]))
        else:
            raise ValueError(f"unknown job '{task}'")
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/store/test_discoveries.py tests/worker -v --no-cov`
Expected: PASS. (If the synthetic discover handler yields a different candidate count for two sources, read `corelata/testing/synthetic.py::_discover` and adjust the expected count, saying so in the report.) Then `uv run pytest` and lint: PASS, ≥ 95%, clean.

- [ ] **Step 7: Commit**

```bash
git add corelata/store/discoveries.py corelata/service.py corelata/worker/execute.py tests/store/test_discoveries.py tests/worker/test_discover.py
git commit -m "feat: discovery job through the queue (M3 Task 7)"
```

---

### Task 8: procrastinate app, stalled-job requeue, `corelata migrate` and `corelata worker`

**Files:**
- Create: `engine/corelata/worker/app.py` (copied, adapted)
- Create: `engine/corelata/logs.py` (copied)
- Create: `engine/corelata/cli_ops.py` (the `migrate` and `worker` commands; Tasks 9 and 10 extend it)
- Modify: `engine/corelata/cli.py` (dispatch to `cli_ops`)
- Modify: `engine/tests/conftest.py` (`_restore_log_handlers` autouse fixture)
- Create: `engine/tests/worker/test_app.py`, `engine/tests/test_cli_ops.py`, `engine/tests/test_logs.py`

**Interfaces:**
- Consumes: `WorkerServices`, `run_job`, `DB_ERRORS` (Task 6); `service.TASK_RUN`, `TASK_DISCOVER`, `JobQueue`; `store.db`, `store.migrate`; `build_backends`, `validate_prompts`, `build_storage`.
- Produces: `worker.app.app` (procrastinate App), `QUEUE = "corelata"`, `SERVICES_KEY = "corelata_services"`, `TASK_REQUEUE_STALLED = "corelata.requeue_stalled"`, `run_task`, `discover_task`, `requeue_stalled(manager, seconds) -> int`, `requeue_stalled_task`, `open_app(url)` (async context manager), `ProcrastinateQueue(opened)`, `build_services(cfg, queue) -> WorkerServices`, `run_worker(cfg, *, burst=False, install_signal_handlers=True, services_factory=build_services)`; `logs.configure_json_logging(level=INFO, stream=None) -> Handler`, `logs.remove_json_logging(handler)`, `logs.JsonFormatter`; `cli_ops.add_commands(sub)`, `cli_ops.COMMANDS`, `cli_ops.run_command(args) -> int`, `cli_ops._load`, `cli_ops._with_db`, `cli_ops._with_queue`, `cli_ops.USER_ERRORS`.

- [ ] **Step 1: Write the failing tests**

Add to `engine/tests/conftest.py` (with `import logging` and `from collections.abc import Iterator`):

```python
@pytest.fixture(autouse=True)
def _restore_log_handlers() -> Iterator[None]:
    """A JSON log handler a test installs writes to that test's captured stream; detach it
    afterwards so later tests don't log to a closed stream."""
    loggers = [logging.getLogger(name) for name in ("corelata", "procrastinate")]
    saved = [(lg.handlers[:], lg.level) for lg in loggers]
    yield
    for lg, (handlers, level) in zip(loggers, saved, strict=True):
        lg.handlers = handlers
        lg.setLevel(level)
```

`engine/tests/test_logs.py`:

```python
import io
import json
import logging

from corelata.logs import configure_json_logging, remove_json_logging


def test_json_logging_is_idempotent_and_structured():
    stream = io.StringIO()
    first = configure_json_logging(stream=stream)
    handler = configure_json_logging(stream=stream)  # replaces, never doubles
    assert first not in logging.getLogger("corelata").handlers
    log = logging.getLogger("corelata.worker")
    log.info("stage complete", extra={"run_id": "r1", "stage": "gating"})
    try:
        raise ValueError("x")
    except ValueError:
        log.exception("failed")
    lines = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert lines[0]["message"] == "stage complete" and lines[0]["run_id"] == "r1"
    assert lines[0]["stage"] == "gating" and lines[0]["level"] == "info"
    assert lines[0]["ts"].endswith("+00:00") and lines[0]["logger"] == "corelata.worker"
    assert "ValueError: x" in lines[1]["exception"]
    remove_json_logging(handler)
    assert handler not in logging.getLogger("corelata").handlers
    assert handler not in logging.getLogger("procrastinate").handlers
```

`engine/tests/worker/test_app.py`:

```python
import asyncio
import dataclasses
import os
import signal
from types import SimpleNamespace

import procrastinate
import pytest
from sqlalchemy import text

from corelata import service
from corelata.config import ConfigError
from corelata.schema import RunState
from corelata.store import migrate
from corelata.store.db import Database
from corelata.store.migrate import MigrationState
from corelata.worker import app as worker_app
from corelata.worker.app import ProcrastinateQueue, open_app, requeue_stalled, run_worker
from tests.worker.conftest import make_services, state, submit


@pytest.fixture
def worker_env(db, fake_backend, tmp_path, monkeypatch, pg_url):
    monkeypatch.setenv("CORELATA_DATABASE_URL", pg_url)
    svc = make_services(db, fake_backend, tmp_path)

    async def factory(cfg, queue):
        # its own Database: run_worker closes the services when it stops
        return dataclasses.replace(svc, db=Database(pg_url), queue=queue)

    return svc, factory


async def _submit(svc, pg_url, **opts):
    async with open_app(pg_url) as opened:
        return await submit(dataclasses.replace(svc, queue=ProcrastinateQueue(opened)), **opts)


async def _jobs(db, task=service.TASK_RUN):
    async with db.engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT status, lock, queueing_lock FROM procrastinate_jobs WHERE task_name = :t"),
            {"t": task},
        )
        return [tuple(r) for r in rows]


def _record_jobs(monkeypatch):
    seen = []

    async def fake_run_job(svc, task, kwargs):
        seen.append((task, kwargs))

    monkeypatch.setattr(worker_app, "run_job", fake_run_job)
    return seen


async def _burst(svc, factory, **kw):
    await run_worker(
        svc.cfg, burst=True, install_signal_handlers=False, services_factory=factory, **kw
    )


async def test_the_worker_completes_a_queued_run(worker_env, pg_url):
    svc, factory = worker_env
    run_id = await _submit(svc, pg_url)
    await _burst(svc, factory)
    assert await state(svc.db, run_id) is RunState.COMPLETED
    assert await _jobs(svc.db) == []  # successful jobs are deleted


async def test_the_worker_runs_a_discovery(worker_env, pg_url):
    svc, factory = worker_env
    pid = await service.create_project(svc.db, "p")
    ids = await service.add_source(svc.db, svc.storage, pid, "a.txt", b"Varna port grew.")
    async with open_app(pg_url) as opened:
        did = await service.start_discovery(svc.db, ProcrastinateQueue(opened), pid, ids)
    await _burst(svc, factory)
    assert (await service.get_discovery(svc.db, did)).state.value == "completed"


async def test_queueing_lock_deduplicates_and_serialises(db, pg_url):
    async with open_app(pg_url) as opened:
        queue = ProcrastinateQueue(opened)
        await queue.defer(service.TASK_RUN, lock="run:r", run_id="r")
        await queue.defer(service.TASK_RUN, lock="run:r", run_id="r")
    # one waiting job; its lock also stops two copies from running at the same time
    assert await _jobs(db) == [("todo", "run:r", "run:r")]


async def test_burst_requeues_the_jobs_of_a_crashed_worker(worker_env, pg_url, monkeypatch):
    svc, factory = worker_env
    seen = _record_jobs(monkeypatch)
    monkeypatch.setattr(worker_app, "_BURST_POLL_S", 0.05)
    # a short pass may end before the periodic re-queue job is deferred: burst mode can't rely on it
    monkeypatch.setattr(worker_app.app.periodic_registry, "periodic_tasks", {})
    async with open_app(pg_url) as opened:
        await ProcrastinateQueue(opened).defer(service.TASK_RUN, lock="run:k", run_id="k")
    async with svc.db.engine.begin() as conn:  # its worker died and was pruned
        await conn.execute(text("UPDATE procrastinate_jobs SET status = 'doing'"))
    await asyncio.wait_for(_burst(svc, factory), timeout=30)
    assert (service.TASK_RUN, {"run_id": "k"}) in seen


async def _stalled_copy_with_a_waiting_copy(db, pg_url, lock, run_id):
    """A copy of a job left 'doing' by a crashed worker, and a second copy waiting behind it
    (queueing locks only dedupe waiting jobs)."""
    async with open_app(pg_url) as opened:
        queue = ProcrastinateQueue(opened)
        await queue.defer(service.TASK_RUN, lock=lock, run_id=run_id)
        async with db.engine.begin() as conn:
            await conn.execute(
                text("UPDATE procrastinate_jobs SET status = 'doing' WHERE lock = :l"),
                {"l": lock},
            )
        await queue.defer(service.TASK_RUN, lock=lock, run_id=run_id)


async def test_burst_does_not_spin_on_a_job_whose_lock_is_held(worker_env, pg_url, monkeypatch):
    svc, factory = worker_env
    seen = _record_jobs(monkeypatch)
    monkeypatch.setattr(worker_app, "_BURST_POLL_S", 0.05)
    monkeypatch.setattr(worker_app.app.periodic_registry, "periodic_tasks", {})
    await _stalled_copy_with_a_waiting_copy(svc.db, pg_url, "run:h", "h")
    await asyncio.wait_for(_burst(svc, factory), timeout=30)
    assert seen == [(service.TASK_RUN, {"run_id": "h"})]  # the waiting copy ran
    assert await _jobs(svc.db) == [("failed", "run:h", "run:h")]  # the stalled copy


async def test_requeue_stalled_closes_a_copy_that_has_a_waiting_twin(db, pg_url):
    await _stalled_copy_with_a_waiting_copy(db, pg_url, "run:t", "t")
    async with open_app(pg_url) as opened:
        queue = ProcrastinateQueue(opened)
        await queue.defer(service.TASK_DISCOVER, lock="discovery:u", discovery_id="u")
        async with db.engine.begin() as conn:
            await conn.execute(
                text("UPDATE procrastinate_jobs SET status = 'doing' WHERE lock = 'discovery:u'")
            )
        assert await requeue_stalled(opened.job_manager, 60) == 1
    assert sorted(await _jobs(db)) == [
        ("failed", "run:t", "run:t"),
        ("todo", "run:t", "run:t"),
    ]
    assert await _jobs(db, service.TASK_DISCOVER) == [("todo", "discovery:u", "discovery:u")]


async def test_requeue_stalled_raises_other_constraint_errors():
    from procrastinate.exceptions import UniqueViolation

    class Manager:
        async def get_stalled_jobs(self, *, seconds_since_heartbeat):
            return ["job-1"]

        async def retry_job(self, job):
            raise UniqueViolation(constraint_name="other", queueing_lock=None)

    with pytest.raises(UniqueViolation):
        await requeue_stalled(Manager(), 60)


async def test_workers_use_the_configured_stalled_timeout(worker_env, monkeypatch):
    svc, factory = worker_env
    calls = []

    async def spy(self, **options):
        calls.append(options)

    monkeypatch.setattr(procrastinate.App, "run_worker_async", spy)
    worker = svc.cfg.worker.model_copy(update={"stalled_after_s": 45})
    cfg = svc.cfg.model_copy(update={"worker": worker})
    await run_worker(cfg, burst=True, install_signal_handlers=False, services_factory=factory)
    await run_worker(cfg, install_signal_handlers=False, services_factory=factory)
    assert [c["stalled_worker_timeout"] for c in calls] == [45, 45]
    assert all(c["queues"] == ["corelata"] and c["name"] == "corelata-worker" for c in calls)


async def test_a_stop_signal_ends_burst_mode(worker_env, pg_url, monkeypatch):
    svc, factory = worker_env

    async def stop_then_queue_more(services, task, kwargs):
        os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.sleep(0.1)  # the signal handler runs
        await services.queue.defer(service.TASK_RUN, lock="run:s2", run_id="s2")

    monkeypatch.setattr(worker_app, "run_job", stop_then_queue_more)
    async with open_app(pg_url) as opened:
        await ProcrastinateQueue(opened).defer(service.TASK_RUN, lock="run:s", run_id="s")
    await asyncio.wait_for(
        run_worker(svc.cfg, burst=True, install_signal_handlers=True, services_factory=factory),
        timeout=30,
    )
    assert await _jobs(svc.db) == [("todo", "run:s2", "run:s2")]  # not run: stopped


async def test_the_long_running_worker_runs_jobs_until_cancelled(worker_env, pg_url):
    svc, factory = worker_env
    closed = []

    async def tracking_factory(cfg, queue):
        services = await factory(cfg, queue)
        original = services.aclose

        async def aclose():
            closed.append(True)
            await original()

        services.aclose = aclose
        return services

    run_id = await _submit(svc, pg_url)
    task = asyncio.create_task(
        run_worker(svc.cfg, install_signal_handlers=False, services_factory=tracking_factory)
    )
    for _ in range(300):
        if await state(svc.db, run_id) is RunState.COMPLETED:
            break
        await asyncio.sleep(0.05)
    assert not task.done()  # still waiting for more jobs
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await state(svc.db, run_id) is RunState.COMPLETED
    assert closed == [True]


async def test_cancelling_burst_mode_propagates(worker_env, pg_url, monkeypatch):
    svc, factory = worker_env
    started = asyncio.Event()

    async def slow_job(services, task, kwargs):
        started.set()
        await asyncio.sleep(0.2)

    monkeypatch.setattr(worker_app, "run_job", slow_job)
    async with open_app(pg_url) as opened:
        await ProcrastinateQueue(opened).defer(service.TASK_RUN, lock="run:c", run_id="c")
    task = asyncio.create_task(_burst(svc, factory))
    await asyncio.wait_for(started.wait(), timeout=30)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_requeue_stalled():
    class Manager:
        def __init__(self):
            self.retried = []

        async def get_stalled_jobs(self, *, seconds_since_heartbeat):
            assert seconds_since_heartbeat == 60
            return ["job-1", "job-2"]

        async def retry_job(self, job):
            self.retried.append(job)

    manager = Manager()
    assert await requeue_stalled(manager, 60) == 2
    assert manager.retried == ["job-1", "job-2"]


async def test_requeue_stalled_task_uses_the_configured_threshold(make_config):
    seen = []

    class Manager:
        async def get_stalled_jobs(self, *, seconds_since_heartbeat):
            seen.append(seconds_since_heartbeat)
            return []

    cfg = make_config(worker={"stalled_after_s": 90})
    context = SimpleNamespace(
        app=SimpleNamespace(job_manager=Manager()),
        additional_context={worker_app.SERVICES_KEY: SimpleNamespace(cfg=cfg)},
    )
    await worker_app.requeue_stalled_task(context, timestamp=0)
    assert seen == [90]


async def test_worker_refuses_an_unmigrated_database(worker_env, monkeypatch):
    svc, factory = worker_env
    monkeypatch.setattr(migrate, "migration_state", lambda url: MigrationState(None, "0002"))
    with pytest.raises(ConfigError, match="corelata migrate"):
        await _burst(svc, factory)


async def test_worker_refuses_an_unreachable_database(worker_env, monkeypatch):
    svc, factory = worker_env
    monkeypatch.setenv("CORELATA_DATABASE_URL", "postgresql://u:secret@127.0.0.1:9/x")
    with pytest.raises(ConfigError, match="cannot connect") as info:
        await _burst(svc, factory)
    assert "secret" not in str(info.value)


async def test_build_services(tmp_path, monkeypatch, pg_url, make_config):
    monkeypatch.setenv("CORELATA_DATABASE_URL", pg_url)
    cfg = make_config(storage={"path": str(tmp_path / "files")})
    svc = await worker_app.build_services(cfg, queue=None)
    try:
        assert set(svc.backends) == {"fake"} and (tmp_path / "files").is_dir()
    finally:
        await svc.aclose()


async def test_the_queue_connection_has_a_connect_timeout(pg_url, monkeypatch):
    real = procrastinate.PsycopgConnector
    seen: dict = {}

    def spy(**kwargs):
        seen.update(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(procrastinate, "PsycopgConnector", spy)
    async with open_app(pg_url):
        pass
    assert seen["kwargs"] == {"connect_timeout": 10}
```

`engine/tests/test_cli_ops.py` (Task 9 adds the run-lifecycle tests to this file):

```python
import logging

import pytest
import yaml

from corelata.cli import main
from corelata.testing.fake_openai import FakeOpenAIServer
from tests.conftest import BASE_CONFIG


@pytest.fixture
def server():
    with FakeOpenAIServer() as srv:
        yield srv


@pytest.fixture
def setup(db, tmp_path, server, monkeypatch, pg_url):
    """A config file pointing at the fake model, the test database and a storage directory."""
    monkeypatch.setenv("CORELATA_DATABASE_URL", pg_url)
    data = {
        **BASE_CONFIG,
        "backends": {"fake": {"base_url": server.base_url}},
        "storage": {"path": str(tmp_path / "files")},
        "worker": {"concurrency": 2, "stalled_after_s": 60},
    }
    config = tmp_path / "corelata.yaml"
    config.write_text(yaml.safe_dump(data), encoding="utf-8")
    doc = tmp_path / "port.txt"
    doc.write_text(
        "The port of Varna expanded its container capacity in 2025.\n\n"
        "Capacity expansion was financed by a state bank.\n\n"
        "Container traffic through Varna rose 40 percent.",
        encoding="utf-8",
    )
    return config, doc


def _cli(capsys, *argv) -> tuple[int, str, str]:
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_migrate_is_idempotent_and_redacts_the_url(setup, capsys):
    config, _ = setup
    code, out, _ = _cli(capsys, "migrate", "--config", str(config))
    assert code == 0 and "at revision 0002" in out and "corelata:corelata@" not in out


def test_migrate_unreachable_database(setup, capsys, monkeypatch):
    config, _ = setup
    monkeypatch.setenv("CORELATA_DATABASE_URL", "postgresql://u:secret@127.0.0.1:9/x")
    code, _, err = _cli(capsys, "migrate", "--config", str(config))
    assert code == 1 and "error: cannot connect to the database at postgresql://u:***@" in err
    assert "secret" not in err and len(err.strip().splitlines()) == 1


def test_missing_database_configuration_is_a_usage_error(setup, capsys, monkeypatch):
    config, _ = setup
    monkeypatch.delenv("CORELATA_DATABASE_URL")
    code, _, err = _cli(capsys, "worker", "--burst", "--config", str(config))
    assert code == 2 and "set CORELATA_DATABASE_URL" in err


def test_worker_burst_on_an_empty_queue_exits_and_removes_its_log_handler(setup, capsys):
    config, _ = setup
    before = list(logging.getLogger("corelata").handlers)
    code, _, _ = _cli(capsys, "worker", "--burst", "--config", str(config))
    assert code == 0 and logging.getLogger("corelata").handlers == before


def test_internal_errors_have_no_traceback(setup, capsys, monkeypatch):
    import corelata.cli_ops as ops

    config, _ = setup

    def boom(args):
        raise RuntimeError("kaput")

    monkeypatch.setitem(ops.COMMANDS, "migrate", boom)
    code, _, err = _cli(capsys, "migrate", "--config", str(config))
    assert code == 1 and err.strip() == "error: internal error: RuntimeError: kaput"


def test_ctrl_c_is_reported(setup, capsys, monkeypatch):
    import corelata.cli_ops as ops

    config, _ = setup

    def interrupt(args):
        raise KeyboardInterrupt

    monkeypatch.setitem(ops.COMMANDS, "worker", interrupt)
    code, _, err = _cli(capsys, "worker", "--config", str(config))
    assert code == 130 and err.strip() == "interrupted"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_logs.py tests/worker/test_app.py tests/test_cli_ops.py -v --no-cov`
Expected: FAIL / ERROR with `ModuleNotFoundError` for `corelata.logs`, `corelata.worker.app`; `migrate` is not a known subcommand (argparse exits 2 with usage).

- [ ] **Step 3: Copy the JSON logging**

`engine/corelata/logs.py`: copy `~/Downloads/coglossa/engine/coglossa/logs.py` verbatim with `_LOGGERS = ("corelata", "procrastinate")`, `_FIELDS = ("run_id", "discovery_id", "stage", "state", "duration_ms")` and the docstring `"""Structured JSON logs for long-running processes (the worker). Copied from Coglossa."""`.

- [ ] **Step 4: Write the procrastinate app**

`engine/corelata/worker/app.py`:

```python
"""procrastinate wiring (spec §4.1, §7.5). Queue jobs call corelata.worker.execute; a periodic
job re-queues jobs whose worker stopped sending heartbeats (a crashed or killed worker), and
execute_run starts such a run over. Copied from Coglossa without the scorer."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import procrastinate
from procrastinate import JobContext, RetryStrategy, signals
from procrastinate.exceptions import AlreadyEnqueued, UniqueViolation
from procrastinate.jobs import Status
from procrastinate.manager import QUEUEING_LOCK_CONSTRAINT
from sqlalchemy.exc import InterfaceError, OperationalError

from corelata.config import CorelataConfig
from corelata.llm.registry import build_backends
from corelata.prompts.check import validate_prompts
from corelata.prompts.library import PromptLibrary
from corelata.service import TASK_DISCOVER, TASK_RUN, JobQueue
from corelata.storage import build_storage
from corelata.store.db import CONNECT_ARGS, Database, database_url, to_libpq_url
from corelata.store.migrate import ensure_migrated
from corelata.worker.execute import WorkerServices, run_job

log = logging.getLogger("corelata.worker")

QUEUE = "corelata"
WORKER_NAME = "corelata-worker"
SERVICES_KEY = "corelata_services"
TASK_REQUEUE_STALLED = "corelata.requeue_stalled"
_DB_RETRY = RetryStrategy(
    max_attempts=5,
    wait=5,
    exponential_wait=2,
    retry_exceptions={OperationalError, InterfaceError},
)
_BURST_POLL_S = 1.0  # burst mode: pause before looking again while other workers run jobs

# The connector is replaced by open_app(); this one is never opened.
app = procrastinate.App(connector=procrastinate.PsycopgConnector())


def _services(context: JobContext) -> WorkerServices:
    return context.additional_context[SERVICES_KEY]


@app.task(name=TASK_RUN, queue=QUEUE, pass_context=True, retry=_DB_RETRY)
async def run_task(context: JobContext, run_id: str) -> None:
    await run_job(_services(context), TASK_RUN, {"run_id": run_id})


@app.task(name=TASK_DISCOVER, queue=QUEUE, pass_context=True, retry=_DB_RETRY)
async def discover_task(context: JobContext, discovery_id: str) -> None:
    await run_job(_services(context), TASK_DISCOVER, {"discovery_id": discovery_id})


async def requeue_stalled(manager: Any, seconds: float) -> int:
    """Re-queue the jobs of workers silent for `seconds`; returns how many were re-queued.
    A stalled job whose copy is already waiting (same queueing lock) can't be re-queued: it
    is closed as failed instead, and the waiting copy does the work."""
    requeued = 0
    for job in await manager.get_stalled_jobs(seconds_since_heartbeat=seconds):
        try:
            await manager.retry_job(job)
        except UniqueViolation as e:
            if e.constraint_name != QUEUEING_LOCK_CONSTRAINT:
                raise
            await manager.finish_job_by_id_async(job.id, Status.FAILED, delete_job=False)
            log.warning(
                "closed job %s (%s) from a worker that stopped responding: a copy is waiting",
                job.id,
                job.queueing_lock,
            )
            continue
        requeued += 1
    if requeued:
        log.warning("re-queued %d job(s) from a worker that stopped responding", requeued)
    return requeued


@app.periodic(cron="* * * * *", periodic_id="requeue-stalled")
@app.task(name=TASK_REQUEUE_STALLED, queue=QUEUE, pass_context=True)
async def requeue_stalled_task(context: JobContext, timestamp: int) -> None:
    await requeue_stalled(context.app.job_manager, _services(context).cfg.worker.stalled_after_s)


@contextlib.asynccontextmanager
async def open_app(url: str) -> AsyncIterator[procrastinate.App]:
    connector = procrastinate.PsycopgConnector(
        conninfo=to_libpq_url(url), kwargs=dict(CONNECT_ARGS)
    )
    with app.replace_connector(connector) as opened:
        async with opened.open_async():
            yield opened


class ProcrastinateQueue:
    def __init__(self, opened: procrastinate.App) -> None:
        self._app = opened

    async def defer(self, task: str, *, lock: str | None = None, **kwargs: str) -> None:
        # queueing_lock: one waiting copy of a job; lock: copies never run at the same time
        deferrer = self._app.configure_task(task, queue=QUEUE, queueing_lock=lock, lock=lock)
        with contextlib.suppress(AlreadyEnqueued):  # already waiting: idempotent by design
            await deferrer.defer_async(**kwargs)


async def build_services(cfg: CorelataConfig, queue: JobQueue) -> WorkerServices:
    prompts = PromptLibrary(cfg.prompts_dir)
    validate_prompts(cfg, prompts)
    storage = build_storage(cfg.storage)
    storage.check_writable()
    return WorkerServices(
        cfg=cfg,
        db=Database(database_url(cfg)),
        storage=storage,
        queue=queue,
        backends=build_backends(cfg),
        prompts=prompts,
    )


ServicesFactory = Callable[[CorelataConfig, JobQueue], Awaitable[WorkerServices]]

# Jobs a burst worker still has to wait for: due jobs it can fetch, and jobs another worker is
# running (they may queue follow-ups). A waiting job whose lock is held by a running job can't
# be fetched (procrastinate_fetch_job_v2), so it is not due: the running job is waited for.
# A retry scheduled for later is left to a long-running worker, so a failing job never keeps
# burst mode alive. Every job is deferred with queueing_lock = lock, so two waiting jobs never
# share a lock and a due job is never held back by an earlier waiting one.
_PENDING_SQL = """
SELECT count(*) FILTER (
           WHERE status = 'todo'
             AND (scheduled_at IS NULL OR scheduled_at <= now())
             AND NOT EXISTS (
                 SELECT 1 FROM procrastinate_jobs AS holder
                  WHERE holder.lock = jobs.lock AND holder.status = 'doing'
             )
       ) AS due,
       count(*) FILTER (WHERE status = 'doing') AS running
  FROM procrastinate_jobs AS jobs
 WHERE queue_name = %(queue)s
"""


async def _queue_settled(opened: procrastinate.App, stalled_after_s: float) -> bool:
    row = await opened.connector.execute_query_one_async(_PENDING_SQL, queue=QUEUE)
    if row["due"]:
        return False
    if row["running"]:
        # A crashed worker's jobs stay 'doing' until re-queued. The periodic job may not get
        # to run in a short pass, so burst mode re-queues them itself.
        await requeue_stalled(opened.job_manager, stalled_after_s)
        await asyncio.sleep(_BURST_POLL_S)
        return False
    return True


async def _run_burst(
    opened: procrastinate.App,
    cfg: CorelataConfig,
    install_signal_handlers: bool,
    options: dict[str, Any],
) -> None:
    """Drain the queue, including jobs that running jobs queue. procrastinate's own burst
    mode (wait=False) stops at the first empty fetch, so it runs in passes until the queue
    has settled. A stop signal ends the current pass gracefully and the loop."""
    stopped = False
    current: asyncio.Task[None] | None = None

    def stop() -> None:
        nonlocal stopped
        stopped = True
        if current is not None:
            current.cancel()  # procrastinate stops fetching and waits for running jobs

    handlers = signals.on_stop(stop) if install_signal_handlers else contextlib.nullcontext()
    with handlers:
        while not stopped:  # a signal may also arrive between passes
            current = asyncio.create_task(
                opened.run_worker_async(wait=False, install_signal_handlers=False, **options)
            )
            try:
                await current
            except asyncio.CancelledError:
                if not stopped:
                    raise
            if stopped or await _queue_settled(opened, cfg.worker.stalled_after_s):
                return


async def run_worker(
    cfg: CorelataConfig,
    *,
    burst: bool = False,
    install_signal_handlers: bool = True,
    services_factory: ServicesFactory = build_services,
) -> None:
    url = database_url(cfg)
    await asyncio.to_thread(ensure_migrated, url)
    async with open_app(url) as opened:
        services = await services_factory(cfg, ProcrastinateQueue(opened))
        options: dict[str, Any] = {
            "queues": [QUEUE],
            "concurrency": cfg.worker.concurrency,
            "name": WORKER_NAME,
            "additional_context": {SERVICES_KEY: services},
            "delete_jobs": "successful",
            # procrastinate's own default (30 s) would detach a slow live worker's jobs, and
            # the stalled-job query re-queues detached jobs at once
            "stalled_worker_timeout": cfg.worker.stalled_after_s,
        }
        try:
            if burst:
                await _run_burst(opened, cfg, install_signal_handlers, options)
            else:
                await opened.run_worker_async(
                    wait=True, install_signal_handlers=install_signal_handlers, **options
                )
        finally:
            await services.aclose()
```

- [ ] **Step 5: Write the CLI operations module and wire it in**

`engine/corelata/cli_ops.py`:

```python
"""CLI commands for the queued deployment (spec §10.2): `migrate`, `worker`, and (Tasks 9 and
10) the run lifecycle and `doctor`. They talk to Postgres; `corelata run FILES` without
`--project` needs none of them."""

import argparse
import asyncio
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path

from corelata import service
from corelata.config import ConfigError, CorelataConfig, default_config_path, load_config
from corelata.ingest.base import IngestError
from corelata.logs import configure_json_logging, remove_json_logging
from corelata.standards.loader import PackError
from corelata.storage import StorageError
from corelata.store.db import Database, database_url, error_reason, redact
from corelata.store.migrate import connect_error, ensure_migrated, migration_state, upgrade
from corelata.store.runs import NotFoundError
from corelata.worker.app import ProcrastinateQueue, open_app, run_worker
from corelata.worker.execute import DB_ERRORS

EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_INTERRUPTED = 0, 1, 2, 130
USER_ERRORS = (
    ConfigError,
    IngestError,
    PackError,
    StorageError,
    NotFoundError,
    service.ConflictError,
    service.InvalidRequestError,
    OSError,
)


def _config_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=Path, default=default_config_path())


def add_commands(sub: argparse._SubParsersAction) -> None:
    _config_arg(sub.add_parser("migrate", help="create or upgrade the database schema"))
    worker = sub.add_parser("worker", help="process queued runs and discoveries")
    _config_arg(worker)
    worker.add_argument("--burst", action="store_true", help="exit when the queue is empty")


def _load(args: argparse.Namespace) -> CorelataConfig:
    cfg, warnings = load_config(args.config)
    for warning in warnings:
        print(f"{warning.level}: {warning.message}", file=sys.stderr)
    return cfg


def _with_db[T](cfg: CorelataConfig, fn: Callable[[Database], Awaitable[T]]) -> T:
    url = database_url(cfg)
    ensure_migrated(url)  # one clear line instead of a missing-table error

    async def go() -> T:
        db = Database(url)
        try:
            return await fn(db)
        finally:
            await db.dispose()

    return asyncio.run(go())


def _with_queue[T](
    cfg: CorelataConfig, fn: Callable[[Database, service.JobQueue], Awaitable[T]]
) -> T:
    async def go(db: Database) -> T:
        async with open_app(db.url) as opened:
            return await fn(db, ProcrastinateQueue(opened))

    return _with_db(cfg, go)


def _migrate(args: argparse.Namespace) -> int:
    cfg = _load(args)
    url = database_url(cfg)
    try:
        upgrade(url)
    except DB_ERRORS as e:
        raise connect_error(url, e) from e
    print(f"database at {redact(url)} is at revision {migration_state(url).head}")
    return EXIT_OK


def _worker(args: argparse.Namespace) -> int:
    cfg = _load(args)
    handler = configure_json_logging()
    try:
        asyncio.run(run_worker(cfg, burst=args.burst))
    finally:
        remove_json_logging(handler)
    return EXIT_OK


COMMANDS: dict[str, Callable[[argparse.Namespace], int]] = {
    "migrate": _migrate,
    "worker": _worker,
}


def run_command(args: argparse.Namespace) -> int:
    try:
        return COMMANDS[args.command](args)
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return EXIT_INTERRUPTED
    except USER_ERRORS as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_USAGE
    except DB_ERRORS as e:
        print(f"error: cannot reach the database: {error_reason(e)}", file=sys.stderr)
    except Exception as e:  # noqa: BLE001 - last resort: never show a traceback to the user
        print(f"error: internal error: {type(e).__name__}: {e}", file=sys.stderr)
    return EXIT_FAILED
```

In `engine/corelata/cli.py`: import `from corelata.cli_ops import COMMANDS, add_commands, run_command`; call `add_commands(sub)` at the end of `build_parser` (before `return parser`); and at the top of the `try` block in `main`, before the existing `if args.command == "run":`, add:

```python
        if args.command in COMMANDS:
            return run_command(args)
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_logs.py tests/worker tests/test_cli_ops.py tests/test_boundary.py -v --no-cov`
Expected: PASS. Then `uv run pytest` and lint: PASS, ≥ 95%, clean.

- [ ] **Step 7: Commit**

```bash
git add corelata/worker/app.py corelata/logs.py corelata/cli_ops.py corelata/cli.py tests/conftest.py tests/worker/test_app.py tests/test_cli_ops.py tests/test_logs.py
git commit -m "feat: procrastinate worker with stalled-job requeue; corelata migrate and worker (M3 Task 8)"
```

---

### Task 9: Queued-run CLI — `ingest`, `run --project`, `discover --project`, `status`, `cancel`, `review`, `export`; `report` finds the stored reference

**Files:**
- Modify: `engine/corelata/cli_ops.py`, `engine/corelata/cli.py`
- Modify: `engine/tests/test_cli_ops.py`, `engine/tests/test_cli.py`

**Interfaces:**
- Consumes: every `service.*` coroutine (Tasks 5, 7), `exports.write_outputs`, `cli_ops._with_db`/`_with_queue`/`run_command` (Task 8).
- Produces: subcommands `ingest FILES... --project NAME [--coglossa-export FILE]...`, `run ... --project NAME [--source-id ID]... [--parent-run RUN_ID]` (queues instead of executing), `discover ... --project NAME [--source-id ID]...`, `status ID [--json]`, `cancel RUN_ID`, `review RUN_ID (--accept | --return) [--note TEXT] [--actor NAME]`, `export RUN_ID --out DIR`; `run_command(args, command=None)`; `corelata report RUN_DIR` uses `RUN_DIR/reference.docx` when present.

- [ ] **Step 1: Write the failing tests**

Append to `engine/tests/test_cli_ops.py`:

```python
import json
import re
import uuid

from docx import Document

from corelata.exports import OUTPUT_FILES
from corelata.testing.postgres import create_test_database, drop_test_database
from tests.standards.test_loader import write_pack

STATEMENT = "Varna port capacity expansion matters to shippers"


def _run_id(out: str) -> str:
    return re.search(r"run (\S+) queued", out).group(1)


def test_queued_run_lifecycle(setup, capsys, tmp_path):
    config, doc = setup
    args = ["--config", str(config)]
    code, out, _ = _cli(capsys, "run", str(doc), "--project", "p", "--statement", STATEMENT, *args)
    assert code == 0 and "queued in project 'p'" in out
    run_id = _run_id(out)
    code, out, _ = _cli(capsys, "status", run_id, *args)
    assert code == 0 and out.startswith(f"run {run_id}: created")
    assert _cli(capsys, "worker", "--burst", *args)[0] == 0
    code, out, _ = _cli(capsys, "status", run_id, *args)
    assert code == 0 and "completed (clean)" in out and "stages: ingesting@0 ok" in out
    assert "usage: 4 calls" in out and "attempts 1" in out
    code, out, _ = _cli(capsys, "status", run_id, "--json", *args)
    assert code == 0 and json.loads(out)["state"] == "completed"
    out_dir = tmp_path / "export"
    code, out, _ = _cli(capsys, "export", run_id, "--out", str(out_dir), *args)
    assert code == 0 and str(out_dir) in out
    assert {p.name for p in out_dir.iterdir()} == set(OUTPUT_FILES)
    code, out, _ = _cli(capsys, "report", str(out_dir), "--format", "md")
    assert code == 0 and out.startswith("UNCLASSIFIED\n")
    assert _cli(capsys, "trace", str(out_dir))[0] == 0
    trace = json.loads((out_dir / "trace.json").read_text(encoding="utf-8"))
    assert trace["run_id"] == run_id and trace["state"] == "completed"


def test_ingest_then_run_by_source_id(setup, capsys):
    config, doc = setup
    args = ["--config", str(config)]
    code, out, _ = _cli(capsys, "ingest", str(doc), "--project", "p", *args)
    assert code == 0
    [sid] = out.split()
    uuid.UUID(sid)
    code, out, _ = _cli(
        capsys, "run", "--project", "p", "--source-id", sid, "--statement", STATEMENT, *args
    )
    assert code == 0
    run_id = _run_id(out)
    assert _cli(capsys, "worker", "--burst", *args)[0] == 0
    assert "completed" in _cli(capsys, "status", run_id, *args)[1]


def test_source_id_needs_project(setup, capsys):
    config, _ = setup
    code, _, err = _cli(
        capsys, "run", "--source-id", str(uuid.uuid4()), "--statement", "x",
        "--config", str(config),
    )
    assert code == 2 and "--source-id needs --project" in err


def test_discover_through_the_queue(setup, capsys):
    config, doc = setup
    args = ["--config", str(config)]
    code, out, _ = _cli(
        capsys, "discover", str(doc), "--project", "p", "--audience", "shippers", *args
    )
    assert code == 0
    did = re.search(r"discovery (\S+) queued", out).group(1)
    code, out, _ = _cli(capsys, "status", did, *args)
    assert code == 0 and out.startswith(f"discovery {did}: created")
    assert _cli(capsys, "worker", "--burst", *args)[0] == 0
    code, out, _ = _cli(capsys, "status", did, *args)
    assert code == 0 and "completed" in out and "\n  1. " in out and "shippers" in out
    code, out, _ = _cli(capsys, "status", did, "--json", *args)
    assert json.loads(out)["candidates"]


def test_cancel_a_queued_run(setup, capsys):
    config, doc = setup
    args = ["--config", str(config)]
    run_id = _run_id(_cli(capsys, "run", str(doc), "--project", "p", "--statement", STATEMENT, *args)[1])
    code, out, _ = _cli(capsys, "cancel", run_id, *args)
    assert code == 0 and out.strip() == f"run {run_id} cancelled"
    assert _cli(capsys, "worker", "--burst", *args)[0] == 0
    assert "cancelled" in _cli(capsys, "status", run_id, *args)[1]
    code, _, err = _cli(capsys, "cancel", run_id, *args)
    assert code == 2 and "already cancelled" in err


def test_review_accept_and_return(setup, capsys):
    config, doc = setup
    args = ["--config", str(config)]
    run_id = _run_id(_cli(capsys, "run", str(doc), "--project", "p", "--statement", STATEMENT, *args)[1])
    code, _, err = _cli(capsys, "review", run_id, "--accept", *args)
    assert code == 2 and "only a completed run" in err
    assert _cli(capsys, "worker", "--burst", *args)[0] == 0
    code, out, _ = _cli(capsys, "review", run_id, "--accept", "--actor", "alice", *args)
    assert code == 0 and out.strip() == f"run {run_id} accepted"
    code, _, err = _cli(capsys, "review", run_id, "--return", *args)
    assert code == 2 and "needs a note" in err
    code, out, _ = _cli(capsys, "review", run_id, "--return", "--note", "Tighten the scope.", *args)
    assert code == 0
    child = re.search(r"new run (\S+) queued", out).group(1)
    code, out, _ = _cli(capsys, "status", child, *args)
    assert code == 0 and f"parent: {run_id}" in out
    assert _cli(capsys, "worker", "--burst", *args)[0] == 0
    assert "completed" in _cli(capsys, "status", child, *args)[1]


def test_export_carries_the_reference_document_and_report_uses_it(setup, capsys, tmp_path):
    config, doc = setup
    pack = write_pack(
        tmp_path / "packs", "house", rules=[], extends="icd203-base", template=None, lexicon=None,
        profiles={"east": {"name": "east", "extends": "house",
                           "format": {"docx_reference": "templates/east.docx"}}},
    )
    (pack / "templates").mkdir()
    Document().save(str(pack / "templates" / "east.docx"))
    data = yaml.safe_load(config.read_text(encoding="utf-8"))
    data["standards"] = {"packs_dir": str(tmp_path / "packs"), "default_pack": "house"}
    config.write_text(yaml.safe_dump(data), encoding="utf-8")
    args = ["--config", str(config)]
    run_id = _run_id(
        _cli(capsys, "run", str(doc), "--project", "p", "--profile", "east",
             "--statement", STATEMENT, *args)[1]
    )
    assert _cli(capsys, "worker", "--burst", *args)[0] == 0
    out_dir = tmp_path / "export"
    assert _cli(capsys, "export", run_id, "--out", str(out_dir), *args)[0] == 0
    assert (out_dir / "reference.docx").is_file()
    code, _, err = _cli(
        capsys, "report", str(out_dir), "--format", "docx", "--out", str(tmp_path / "again.docx")
    )
    assert code == 0 and err == ""  # no "neutral template" note: the reference was found
    assert (tmp_path / "again.docx").read_bytes() == (out_dir / "report.docx").read_bytes()


def test_unknown_and_malformed_ids(setup, capsys):
    config, _ = setup
    args = ["--config", str(config)]
    code, _, err = _cli(capsys, "status", str(uuid.uuid4()), *args)
    assert code == 2 and "no run or discovery" in err
    code, _, err = _cli(capsys, "status", "nope", *args)
    assert code == 2 and "not a run or discovery id" in err
    code, _, err = _cli(capsys, "cancel", str(uuid.uuid4()), *args)
    assert code == 2 and "not found" in err


def test_unsupported_input_and_missing_file(setup, capsys, tmp_path):
    config, _ = setup
    bad = tmp_path / "x.png"
    bad.write_bytes(b"\x89PNG")
    code, _, err = _cli(capsys, "ingest", str(bad), "--project", "p", "--config", str(config))
    assert code == 2 and "unsupported file type" in err
    code, _, err = _cli(
        capsys, "ingest", str(tmp_path / "missing.txt"), "--project", "p", "--config", str(config)
    )
    assert code == 2 and "input file not found" in err
    code, _, err = _cli(capsys, "ingest", "--project", "p", "--config", str(config))
    assert code == 2 and "at least one input file" in err


def test_an_unmigrated_database_is_refused(setup, capsys, pg_admin, monkeypatch):
    config, doc = setup
    url = create_test_database(pg_admin)
    try:
        monkeypatch.setenv("CORELATA_DATABASE_URL", url)
        code, _, err = _cli(
            capsys, "run", str(doc), "--project", "p", "--statement", STATEMENT,
            "--config", str(config),
        )
        assert code == 2 and "run `corelata migrate`" in err
    finally:
        drop_test_database(pg_admin, url)
```

(Merge the imports with the ones already at the top of the file.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_cli_ops.py -v --no-cov`
Expected: the new tests FAIL (argparse rejects `--project`, `ingest`, `status`, …).

- [ ] **Step 3: Extend the parsers**

In `engine/corelata/cli.py`:

- `run` gains:

```python
    run.add_argument(
        "--project", help="queue the run in this project instead of executing it here (database)"
    )
    run.add_argument(
        "--source-id",
        action="append",
        default=[],
        help="an already ingested source to include (with --project; repeatable)",
    )
    run.add_argument("--parent-run", help="the run this one reruns (with --project)")
```

- `discover` gains the same `--project` and `--source-id` arguments.
- `_run`: right after `statement = _statement(args)` succeeds, add:

```python
    if args.source_id and args.project is None:
        return _usage("--source-id needs --project")
    if args.project is not None:
        args.value_statement = statement
        return run_command(args, "queue-run")
```

  (Move the `statement = _statement(args)` call into its own `try` so this check runs before `_setup` loads the files.)

- `_discover`: at the top:

```python
    if args.source_id and args.project is None:
        return _usage("--source-id needs --project")
    if args.project is not None:
        return run_command(args, "queue-discover")
```

- `_report`: default the reference to the exported one:

```python
    reference = args.docx_reference
    if reference is None and (args.run_dir / "reference.docx").is_file():
        reference = args.run_dir / "reference.docx"
```

  (the existing stderr note stays, now only when no reference was found anywhere).

In `engine/corelata/cli_ops.py`, extend `add_commands`:

```python
    ingest = sub.add_parser("ingest", help="add source files to a project (database)")
    _config_arg(ingest)
    ingest.add_argument("inputs", nargs="*", type=Path)
    ingest.add_argument("--coglossa-export", action="append", default=[], type=Path)
    ingest.add_argument("--project", required=True)

    status = sub.add_parser("status", help="show a queued run or discovery")
    _config_arg(status)
    status.add_argument("id")
    status.add_argument("--json", action="store_true")

    cancel = sub.add_parser("cancel", help="cancel a queued or running run")
    _config_arg(cancel)
    cancel.add_argument("run_id")

    review = sub.add_parser("review", help="accept a completed run, or return it with a note")
    _config_arg(review)
    review.add_argument("run_id")
    action = review.add_mutually_exclusive_group(required=True)
    action.add_argument("--accept", dest="action", action="store_const", const="accept")
    action.add_argument("--return", dest="action", action="store_const", const="return")
    review.add_argument("--note", default="", help="guidance for the writer (required for return)")
    review.add_argument("--actor", help="who reviewed")

    export = sub.add_parser("export", help="write a run directory (trace and exports) from the database")
    _config_arg(export)
    export.add_argument("run_id")
    export.add_argument("--out", type=Path, required=True)
```

- [ ] **Step 4: Write the commands**

Add to `engine/corelata/cli_ops.py` (imports: `json`, `uuid`, `from corelata.exports import DocxExportError, dump_json, write_outputs`, `from corelata.prompts.check import validate_prompts`, `from corelata.prompts.library import PromptLibrary`, `from corelata.schema import TERMINAL_STATES, DiscoveryView, ReviewAction, RunProgress`, `from corelata.standards.schema import ResolvedPack`, `from corelata.storage import StorageError, build_storage`):

```python
def _id(text: str, what: str) -> uuid.UUID:
    try:
        return uuid.UUID(text)
    except ValueError:
        raise ConfigError(f"'{text}' is not a {what} id") from None


def _read(path: Path) -> bytes:
    if not path.is_file():
        raise IngestError(f"input file not found: {path}")
    return path.read_bytes()


async def _ingest_files(
    db: Database, storage, project_id: uuid.UUID, inputs: list[Path], exports: list[Path]
) -> list[uuid.UUID]:
    ids: list[uuid.UUID] = []
    for path in inputs:
        ids += await service.add_source(db, storage, project_id, path.name, _read(path))
    for path in exports:
        ids += await service.add_source(
            db, storage, project_id, path.name, _read(path), coglossa_export=True
        )
    return ids


def _ingest(args: argparse.Namespace) -> int:
    cfg = _load(args)
    if not args.inputs and not args.coglossa_export:
        raise ConfigError("give at least one input file or --coglossa-export")
    storage = build_storage(cfg.storage)

    async def go(db: Database) -> list[uuid.UUID]:
        pid = await service.create_project(db, args.project)
        return await _ingest_files(db, storage, pid, args.inputs, args.coglossa_export)

    for sid in _with_db(cfg, go):
        print(sid)
    return EXIT_OK


def _queue_run(args: argparse.Namespace) -> int:
    cfg = _load(args)
    if not args.inputs and not args.coglossa_export and not args.source_id:
        raise ConfigError("give input files, --coglossa-export or --source-id")
    storage = build_storage(cfg.storage)
    prompts = PromptLibrary(cfg.prompts_dir)
    validate_prompts(cfg, prompts)
    parent = _id(args.parent_run, "run") if args.parent_run else None

    async def go(db: Database, queue: service.JobQueue) -> uuid.UUID:
        pid = await service.create_project(db, args.project)
        ids = [_id(s, "source") for s in args.source_id]
        ids += await _ingest_files(db, storage, pid, args.inputs, args.coglossa_export)
        req = service.RunRequest(
            project_id=pid,
            source_ids=ids,
            value_statement=args.value_statement,
            profile=args.profile,
            max_iterations=args.max_iterations,
            extra_guidance=args.guidance,
            parent_run_id=parent,
        )
        return await service.start_run(db, storage, queue, cfg, prompts, req)

    run_id = _with_queue(cfg, go)
    print(f"run {run_id} queued in project '{args.project}'")
    return EXIT_OK


def _queue_discover(args: argparse.Namespace) -> int:
    cfg = _load(args)
    if not args.inputs and not args.coglossa_export and not args.source_id:
        raise ConfigError("give input files, --coglossa-export or --source-id")
    storage = build_storage(cfg.storage)

    async def go(db: Database, queue: service.JobQueue) -> uuid.UUID:
        pid = await service.create_project(db, args.project)
        ids = [_id(s, "source") for s in args.source_id]
        ids += await _ingest_files(db, storage, pid, args.inputs, args.coglossa_export)
        return await service.start_discovery(db, queue, pid, ids, args.audience)

    did = _with_queue(cfg, go)
    print(f"discovery {did} queued in project '{args.project}'")
    return EXIT_OK


def _show_run(p: RunProgress) -> str:
    status = f" ({p.status.value})" if p.status else ""
    lines = [
        f"run {p.run_id}: {p.state.value}{status}  iteration {p.iteration}/{p.max_iterations}"
        f"  attempts {p.attempts}"
    ]
    if p.parent_run_id:
        lines.append(f"parent: {p.parent_run_id}")
    if p.stages:
        lines.append(
            "stages: " + ", ".join(f"{s.stage}@{s.iteration} {'ok' if s.ok else 'failed'}" for s in p.stages)
        )
    if p.usage:
        lines.append(
            f"usage: {p.usage.calls} calls, in {p.usage.tokens_in} tokens, "
            f"out {p.usage.tokens_out} tokens"
        )
    if p.error:
        lines.append(f"error: {p.error}")
    if p.export_error:
        lines.append(f"export error: {p.export_error}")
    if p.cancel_requested and p.state not in TERMINAL_STATES:
        lines.append("cancel requested; the run stops after the current stage")
    return "\n".join(lines) + "\n"


def _show_discovery(d: DiscoveryView) -> str:
    lines = [f"discovery {d.discovery_id}: {d.state.value}  sources {len(d.source_ids)}"]
    if d.audience_hint:
        lines.append(f"audience hint: {d.audience_hint}")
    for i, c in enumerate(d.candidates, start=1):
        lines.append(f"  {i}. {c.text}")
        lines.append(f"     audience: {c.audience}; evidence: {', '.join(c.evidence) or 'none'}")
        if c.confidence_note:
            lines.append(f"     note: {c.confidence_note}")
    if d.error:
        lines.append(f"error: {d.error}")
    return "\n".join(lines) + "\n"


def _status(args: argparse.Namespace) -> int:
    cfg = _load(args)
    some_id = _id(args.id, "run or discovery")

    async def go(db: Database) -> RunProgress | DiscoveryView:
        try:
            return await service.run_progress(db, some_id)
        except NotFoundError:
            try:
                return await service.get_discovery(db, some_id)
            except NotFoundError:
                raise NotFoundError(f"no run or discovery {some_id}") from None

    view = _with_db(cfg, go)
    if args.json:
        print(dump_json(view.model_dump(mode="json")), end="")
    elif isinstance(view, RunProgress):
        print(_show_run(view), end="")
    else:
        print(_show_discovery(view), end="")
    return EXIT_OK


def _cancel(args: argparse.Namespace) -> int:
    cfg = _load(args)
    run_id = _id(args.run_id, "run")
    state = _with_db(cfg, lambda db: service.cancel_run(db, run_id))
    if state in TERMINAL_STATES:
        print(f"run {run_id} cancelled")
    else:
        print(f"run {run_id}: cancel requested; it stops after the current stage")
    return EXIT_OK


def _review(args: argparse.Namespace) -> int:
    cfg = _load(args)
    run_id = _id(args.run_id, "run")
    storage = build_storage(cfg.storage)
    prompts = PromptLibrary(cfg.prompts_dir)
    action = ReviewAction(args.action)

    async def go(db: Database, queue: service.JobQueue) -> uuid.UUID | None:
        return await service.review_run(
            db, storage, queue, cfg, prompts, run_id, action, note=args.note, actor=args.actor
        )

    child = _with_queue(cfg, go)
    if action is ReviewAction.ACCEPT:
        print(f"run {run_id} accepted")
    else:
        print(f"run {run_id} returned; new run {child} queued")
    return EXIT_OK


def _export(args: argparse.Namespace) -> int:
    cfg = _load(args)
    run_id = _id(args.run_id, "run")
    storage = build_storage(cfg.storage)

    async def go(db: Database):
        record = await service.get_run_record(db, run_id)
        return record, await service.reference_document(db, storage, run_id)

    record, reference = _with_db(cfg, go)
    pack = ResolvedPack.model_validate(record.pack_snapshot)
    out: Path = args.out
    if out.exists() and not out.is_dir():
        raise ConfigError(f"{out} is not a directory")
    out.mkdir(parents=True, exist_ok=True)
    if reference is not None:
        (out / "reference.docx").write_bytes(reference)
        pack.docx_reference_path = out / "reference.docx"
    write_outputs(out, record, pack, with_claim_ids=False)
    print(f"run {run_id} ({record.state.value}) -> {out}")
    return EXIT_OK
```

Register them and let `run_command` take the command name:

```python
COMMANDS: dict[str, Callable[[argparse.Namespace], int]] = {
    "migrate": _migrate,
    "worker": _worker,
    "ingest": _ingest,
    "status": _status,
    "cancel": _cancel,
    "review": _review,
    "export": _export,
    "queue-run": _queue_run,  # `corelata run --project`, dispatched by cli.py
    "queue-discover": _queue_discover,  # `corelata discover --project`
}


def run_command(args: argparse.Namespace, command: str | None = None) -> int:
    try:
        return COMMANDS[command or args.command](args)
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return EXIT_INTERRUPTED
    except USER_ERRORS as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_USAGE
    except DocxExportError as e:
        print(f"error: the DOCX export failed: {e}", file=sys.stderr)
    except DB_ERRORS as e:
        print(f"error: cannot reach the database: {error_reason(e)}", file=sys.stderr)
    except Exception as e:  # noqa: BLE001 - last resort: never show a traceback to the user
        print(f"error: internal error: {type(e).__name__}: {e}", file=sys.stderr)
    return EXIT_FAILED
```

`cli.main` dispatches only names argparse can produce (`args.command in COMMANDS`), so `queue-run` and `queue-discover` are reachable only through `_run` and `_discover`.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_cli_ops.py tests/test_cli.py -v --no-cov`
Expected: PASS. Then `uv run pytest` and lint: PASS, ≥ 95%, clean.

- [ ] **Step 6: Commit**

```bash
git add corelata/cli.py corelata/cli_ops.py tests/test_cli_ops.py tests/test_cli.py
git commit -m "feat: queued-run CLI: ingest, run/discover --project, status, cancel, review, export (M3 Task 9)"
```

---

### Task 10: `corelata doctor`

**Files:**
- Create: `engine/corelata/schema/doctor.py`; modify `engine/corelata/schema/__init__.py`, `engine/corelata/schema/export.py`
- Create: `engine/corelata/doctor.py`
- Modify: `engine/corelata/cli_ops.py`
- Create: `engine/tests/test_doctor.py`
- Regenerate: `schema/doctor-report.schema.json`

**Interfaces:**
- Consumes: `load_config`, `validate_prompts`, `load_run_pack`, `build_backends`, `Backend.list_models`/`chat`, `migration_state`, `connect_error`, `redact`, `build_storage`, `DB_ERRORS`, `extract_json`, `render_input`.
- Produces: `schema.CheckStatus` (`pass` | `warn` | `fail`), `schema.DoctorCheck{name, status, message, fix}`, `schema.DoctorReport{checks, ok}` with `DoctorReport.of(checks)`; `doctor.run_doctor(config_path, *, probe=True, backends_factory=build_backends) -> DoctorReport`; subcommand `doctor [--json] [--no-probe]` (exit 0 when `report.ok`, else 1).

- [ ] **Step 1: Write the failing tests**

`engine/corelata/schema/doctor.py`:

```python
"""`corelata doctor` results (spec §10.1 GET /system/doctor, §10.2)."""

from enum import StrEnum

from pydantic import BaseModel


class CheckStatus(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


class DoctorCheck(BaseModel):
    name: str
    status: CheckStatus
    message: str
    fix: str = ""


class DoctorReport(BaseModel):
    checks: list[DoctorCheck]
    ok: bool

    @classmethod
    def of(cls, checks: list[DoctorCheck]) -> "DoctorReport":
        return cls(checks=checks, ok=all(c.status is not CheckStatus.FAIL for c in checks))
```

Export the three names from `schema/__init__.py` and add `"doctor-report": DoctorReport` to `EXPORTED`; run `make schema`.

`engine/tests/test_doctor.py`:

```python
import json

import pytest
import yaml
from sqlalchemy.engine import make_url

from corelata.cli import main
from corelata.doctor import run_doctor
from corelata.llm.types import PermanentBackendError
from corelata.schema import CheckStatus
from corelata.testing.fake_backend import FakeBackend
from corelata.testing.fake_openai import FakeOpenAIServer
from corelata.testing.postgres import create_test_database, drop_test_database


def _config(tmp_path, server_url, **extra):
    cfg = {
        "backends": {"local": {"base_url": server_url, "max_concurrency": 2, "timeout_s": 5}},
        "models": {"fake-model": {"backend": "local", "context_window": 4096}},
        "roles": {r: {"model": "fake-model"} for r in ("gate", "writer", "conveyor", "auditor")},
        "storage": {"path": str(tmp_path / "files")},
        **extra,
    }
    path = tmp_path / "corelata.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return path


def _by_name(report):
    return {c.name: c for c in report.checks}


@pytest.fixture
def server():
    with FakeOpenAIServer() as srv:
        yield srv


async def test_a_healthy_installation(tmp_path, server, monkeypatch, pg_url):
    monkeypatch.setenv("CORELATA_DATABASE_URL", pg_url)
    report = await run_doctor(_config(tmp_path, server.base_url))
    checks = _by_name(report)
    assert report.ok
    for name in ("config", "prompts", "pack", "backend local", "model fake-model", "database",
                 "storage"):
        assert checks[name].status is CheckStatus.PASS, (name, checks[name])
    assert "fake-model" in checks["backend local"].message
    assert "icd203-base" in checks["pack"].message
    assert "json_schema output works" in checks["model fake-model"].message
    assert "0002" in checks["database"].message
    assert f":{make_url(pg_url).password}@" not in checks["database"].message  # redacted


async def test_model_not_served(tmp_path, server, monkeypatch):
    monkeypatch.delenv("CORELATA_DATABASE_URL", raising=False)
    path = _config(
        tmp_path, server.base_url,
        models={"big": {"backend": "local", "name": "other-model", "context_window": 4096}},
        roles={r: {"model": "big"} for r in ("gate", "writer", "conveyor", "auditor")},
    )
    report = await run_doctor(path)
    check = _by_name(report)["model big"]
    assert check.status is CheckStatus.FAIL and "not served" in check.message
    assert check.fix == "set models.big.name to one of: fake-model"
    assert _by_name(report)["database"].status is CheckStatus.WARN
    assert "set CORELATA_DATABASE_URL" in _by_name(report)["database"].fix
    assert not report.ok


async def test_unreachable_backend(tmp_path):
    report = await run_doctor(_config(tmp_path, "http://127.0.0.1:9/v1"))
    check = _by_name(report)["backend local"]
    assert check.status is CheckStatus.FAIL and "fake-model" not in check.message
    assert "model fake-model" not in _by_name(report)


async def test_no_probe_skips_the_test_completions(tmp_path, server):
    report = await run_doctor(_config(tmp_path, server.base_url), probe=False)
    check = _by_name(report)["model fake-model"]
    assert check.status is CheckStatus.PASS and check.message == "served"
    assert server.requests == []


async def test_failed_completion_is_reported(tmp_path, server):
    class Broken(FakeBackend):
        async def list_models(self):
            return ["fake-model"]

        async def chat(self, request):
            raise PermanentBackendError("quota")

    report = await run_doctor(
        _config(tmp_path, server.base_url), backends_factory=lambda cfg: {"local": Broken()}
    )
    check = _by_name(report)["model fake-model"]
    assert check.status is CheckStatus.FAIL and "quota" in check.message


async def test_structured_output_not_honoured(tmp_path, server):
    class Prose(FakeBackend):
        async def list_models(self):
            return ["fake-model"]

        async def chat(self, request):
            from corelata.llm.types import ChatResponse

            return ChatResponse(content="Sure! Here you go.")

    report = await run_doctor(
        _config(tmp_path, server.base_url), backends_factory=lambda cfg: {"local": Prose()}
    )
    check = _by_name(report)["model fake-model"]
    assert check.status is CheckStatus.FAIL and "did not return the requested JSON" in check.message
    assert check.fix == "set models.fake-model.structured_output to json_object or none"


async def test_database_states(tmp_path, server, monkeypatch, pg_admin):
    monkeypatch.setenv("CORELATA_DATABASE_URL", "postgresql://u:secret@127.0.0.1:9/x")
    report = await run_doctor(_config(tmp_path, server.base_url), probe=False)
    db_check = _by_name(report)["database"]
    assert db_check.status is CheckStatus.FAIL and "secret" not in db_check.message
    url = create_test_database(pg_admin)
    try:
        monkeypatch.setenv("CORELATA_DATABASE_URL", url)
        report = await run_doctor(_config(tmp_path, server.base_url), probe=False)
        assert _by_name(report)["database"].fix == "run corelata migrate"
    finally:
        drop_test_database(pg_admin, url)


async def test_storage_not_writable(tmp_path, server):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    path = _config(tmp_path, server.base_url, storage={"path": str(blocker / "sub")})
    report = await run_doctor(path, probe=False)
    assert _by_name(report)["storage"].status is CheckStatus.FAIL


async def test_pack_problems_are_reported(tmp_path, server):
    path = _config(tmp_path, server.base_url, standards={"default_profile": "nope"})
    report = await run_doctor(path, probe=False)
    check = _by_name(report)["pack"]
    assert check.status is CheckStatus.FAIL and "profile 'nope' not found" in check.message


async def test_invalid_config_stops_early(tmp_path):
    path = tmp_path / "corelata.yaml"
    path.write_text("backends: {}\nmodels: {}\n", encoding="utf-8")
    report = await run_doctor(path)
    assert [c.name for c in report.checks] == ["config"]
    assert report.checks[0].status is CheckStatus.FAIL and not report.ok


async def test_config_warnings_are_reported(tmp_path, server, monkeypatch):
    from corelata import doctor
    from corelata.config import ConfigIssue, load_config

    def with_warning(path):
        cfg, _ = load_config(path)
        return cfg, [ConfigIssue(level="warning", message="something to look at")]

    monkeypatch.setattr(doctor, "load_config", with_warning)
    report = await run_doctor(_config(tmp_path, server.base_url), probe=False)
    warn = [c for c in report.checks if c.name == "config" and c.status is CheckStatus.WARN]
    assert warn and warn[0].message == "something to look at" and report.ok


def test_cli_text_and_json(tmp_path, server, capsys, monkeypatch):
    monkeypatch.delenv("CORELATA_DATABASE_URL", raising=False)
    path = _config(tmp_path, server.base_url)
    assert main(["doctor", "--config", str(path), "--no-probe"]) == 0
    out = capsys.readouterr().out
    assert "PASS  backend local" in out and "WARN  database" in out
    assert "fix: set CORELATA_DATABASE_URL" in out
    assert main(["doctor", "--config", str(path), "--json", "--no-probe"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True and data["checks"][0]["name"] == "config"
    bad = _config(tmp_path, "http://127.0.0.1:9/v1")
    assert main(["doctor", "--config", str(bad), "--no-probe"]) == 1


async def test_an_unexpected_error_fails_one_check_and_the_rest_still_run(
    tmp_path, server, monkeypatch
):
    def boom(*_a, **_k):
        raise RuntimeError("kaput")

    monkeypatch.setattr("corelata.doctor.load_run_pack", boom)
    monkeypatch.setattr("corelata.doctor.migration_state", boom)
    monkeypatch.setenv("CORELATA_DATABASE_URL", "postgresql://u:p@127.0.0.1:9/x")
    report = await run_doctor(_config(tmp_path, server.base_url), probe=False)
    checks = _by_name(report)
    assert checks["pack"].status is CheckStatus.FAIL
    assert checks["pack"].message == "internal error: RuntimeError: kaput"
    assert checks["database"].status is CheckStatus.FAIL and "kaput" in checks["database"].message
    assert checks["model fake-model"].status is CheckStatus.PASS
    assert checks["storage"].status is CheckStatus.PASS and not report.ok
```

(`validate_config` today produces errors only, never warnings, so the WARN branch is exercised by monkeypatching `corelata.doctor.load_config` as the test does.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_doctor.py -v --no-cov`
Expected: FAIL with `ModuleNotFoundError: No module named 'corelata.doctor'`.

- [ ] **Step 3: Write the doctor**

`engine/corelata/doctor.py`:

```python
"""`corelata doctor` (spec §10.2): check an installation end to end and say how to fix what is
wrong. Every check reports pass, warn or fail with a plain-language fix. Adapted from Coglossa:
no scorer or language tiers; a standards-pack check instead."""

import asyncio
import json
from collections.abc import Awaitable, Callable
from pathlib import Path

from corelata.config import ConfigError, CorelataConfig, ModelConfig, StructuredOutput, load_config
from corelata.llm.agent import extract_json
from corelata.llm.payload import render_input
from corelata.llm.registry import build_backends
from corelata.llm.types import Backend, BackendError, ChatMessage, ChatRequest, OutputTruncatedError
from corelata.pipeline import load_run_pack
from corelata.prompts.check import validate_prompts
from corelata.prompts.library import PromptLibrary
from corelata.schema import CheckStatus, DoctorCheck, DoctorReport
from corelata.standards.loader import PackError
from corelata.storage import StorageError, build_storage
from corelata.store.db import redact
from corelata.store.migrate import connect_error, migration_state
from corelata.worker.execute import DB_ERRORS

PING_SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "additionalProperties": False,
}
_ORDER = {CheckStatus.PASS: 0, CheckStatus.WARN: 1, CheckStatus.FAIL: 2}

BackendsFactory = Callable[[CorelataConfig], dict[str, Backend]]


def _check(name: str, status: CheckStatus, message: str, fix: str = "") -> DoctorCheck:
    return DoctorCheck(name=name, status=status, message=message, fix=fix)


def _crashed(name: str, e: Exception) -> DoctorCheck:
    return _check(name, CheckStatus.FAIL, f"internal error: {type(e).__name__}: {e}")


def _guard(name: str, fn: Callable[[], DoctorCheck]) -> DoctorCheck:
    """A diagnostic reports every check: an unexpected error becomes that check's failure."""
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        return _crashed(name, e)


async def _aguard(name: str, fn: Callable[[], Awaitable[DoctorCheck]]) -> DoctorCheck:
    try:
        return await fn()
    except Exception as e:  # noqa: BLE001
        return _crashed(name, e)


async def run_doctor(
    config_path: Path,
    *,
    probe: bool = True,
    backends_factory: BackendsFactory = build_backends,
) -> DoctorReport:
    try:
        cfg, issues = load_config(config_path)
    except ConfigError as e:
        return DoctorReport.of(
            [_check("config", CheckStatus.FAIL, str(e), "edit the file; see corelata.example.yaml")]
        )
    checks = [_check("config", CheckStatus.PASS, f"{config_path} is valid")]
    checks += [_check("config", CheckStatus.WARN, i.message) for i in issues]
    checks.append(_guard("prompts", lambda: _prompts(cfg)))
    checks.append(_guard("pack", lambda: _pack(cfg)))
    checks += await _backends(cfg, probe, backends_factory)
    checks.append(await _aguard("database", lambda: _database(cfg)))
    checks.append(_guard("storage", lambda: _storage(cfg)))
    return DoctorReport.of(checks)


def _prompts(cfg: CorelataConfig) -> DoctorCheck:
    try:
        validate_prompts(cfg, PromptLibrary(cfg.prompts_dir))
    except ConfigError as e:
        return _check("prompts", CheckStatus.FAIL, str(e), "fix or remove the override in prompts_dir")
    return _check("prompts", CheckStatus.PASS, "every prompt renders")


def _pack(cfg: CorelataConfig) -> DoctorCheck:
    try:
        pack = load_run_pack(cfg, None)
    except PackError as e:
        return _check(
            "pack", CheckStatus.FAIL, str(e), "fix standards.default_pack / default_profile or the pack directory"
        )
    profile = f" with profile {pack.profile}" if pack.profile else ""
    return _check(
        "pack", CheckStatus.PASS, f"{pack.name} {pack.version}{profile}: {len(pack.rules)} rules"
    )


async def _backends(cfg: CorelataConfig, probe: bool, factory: BackendsFactory) -> list[DoctorCheck]:
    try:
        backends = factory(cfg)
    except ConfigError as e:
        return [_check("backends", CheckStatus.FAIL, str(e), "fix the backend kind")]
    except Exception as e:  # noqa: BLE001
        return [_crashed("backends", e)]
    checks: list[DoctorCheck] = []
    try:
        for name, backend in backends.items():
            checks += await _backend(cfg, name, backend, probe)
    finally:
        for backend in backends.values():
            await backend.aclose()
    return checks


async def _backend(
    cfg: CorelataConfig, name: str, backend: Backend, probe: bool
) -> list[DoctorCheck]:
    label = f"backend {name}"
    try:
        served = await backend.list_models()
    except BackendError as e:
        return [
            _check(label, CheckStatus.FAIL, f"unreachable: {e}", "check the URL and that the server is up")
        ]
    checks = [_check(label, CheckStatus.PASS, f"serves {', '.join(served) or 'no models'}")]
    for key, model in cfg.models.items():
        if model.backend == name:
            checks.append(
                await _aguard(
                    f"model {key}", lambda k=key, m=model: _model(k, m, backend, served, probe)
                )
            )
    return checks


def _ping(model_id: str, mode: StructuredOutput) -> ChatRequest:
    return ChatRequest(
        model=model_id,
        messages=[
            ChatMessage(role="system", content='Reply with the JSON object {"ok": true}.'),
            ChatMessage(role="user", content=render_input({"task": "ping"})),
        ],
        schema_name="Ping",
        json_schema=PING_SCHEMA,
        structured_output=mode,
        temperature=0,
        max_tokens=50,
    )


async def _model(
    key: str, model: ModelConfig, backend: Backend, served: list[str], probe: bool
) -> DoctorCheck:
    label = f"model {key}"
    model_id = model.name or key
    if model_id not in served:
        return _check(
            label,
            CheckStatus.FAIL,
            f"'{model_id}' is not served by backend {model.backend}",
            f"set models.{key}.name to one of: {', '.join(served)}",
        )
    if not probe:
        return _check(label, CheckStatus.PASS, "served")
    parts: list[DoctorCheck] = []
    try:
        await backend.chat(_ping(model_id, StructuredOutput.NONE))
        parts.append(_check(label, CheckStatus.PASS, "test completion succeeded"))
    except OutputTruncatedError:  # cut at max_tokens: the model answered
        parts.append(_check(label, CheckStatus.PASS, "test completion succeeded"))
    except BackendError as e:
        parts.append(
            _check(label, CheckStatus.FAIL, f"test completion failed: {e}", "check the model id and server logs")
        )
    if model.structured_output is not StructuredOutput.NONE and parts[0].status is CheckStatus.PASS:
        parts.append(await _structured(label, key, model, model_id, backend))
    worst = max(parts, key=lambda c: _ORDER[c.status])
    fix = next((c.fix for c in parts if c.status is not CheckStatus.PASS), "")
    return _check(label, worst.status, "; ".join(c.message for c in parts), fix)


async def _structured(
    label: str, key: str, model: ModelConfig, model_id: str, backend: Backend
) -> DoctorCheck:
    fix = f"set models.{key}.structured_output to json_object or none"
    try:
        reply = await backend.chat(_ping(model_id, model.structured_output))
        data = json.loads(extract_json(reply.content))
    except BackendError as e:
        return _check(label, CheckStatus.FAIL, f"{model.structured_output.value} request failed: {e}", fix)
    except ValueError:
        data = None
    if not isinstance(data, dict) or not isinstance(data.get("ok"), bool):
        return _check(
            label,
            CheckStatus.FAIL,
            f"the server did not return the requested JSON ({model.structured_output.value})",
            fix,
        )
    return _check(label, CheckStatus.PASS, f"{model.structured_output.value} output works")


async def _database(cfg: CorelataConfig) -> DoctorCheck:
    url = cfg.database.url()
    env = cfg.database.url_env
    if url is None:
        return _check(
            "database",
            CheckStatus.WARN,
            f"{env} is not set: needed by corelata worker and the queued commands, not by corelata run",
            f"set {env}=postgresql://user:password@host:5432/corelata",
        )
    try:
        state = await asyncio.to_thread(migration_state, url)
    except ConfigError as e:
        return _check("database", CheckStatus.FAIL, str(e), f"fix {env}")
    except DB_ERRORS as e:
        return _check(
            "database",
            CheckStatus.FAIL,
            str(connect_error(url, e)),
            "check the URL, the credentials and that Postgres is running",
        )
    if not state.up_to_date:
        return _check(
            "database",
            CheckStatus.FAIL,
            f"schema at revision {state.current or 'none'}, expected {state.head}",
            "run corelata migrate",
        )
    return _check("database", CheckStatus.PASS, f"{redact(url)} at revision {state.head}")


def _storage(cfg: CorelataConfig) -> DoctorCheck:
    try:
        build_storage(cfg.storage).check_writable()
    except StorageError as e:
        return _check("storage", CheckStatus.FAIL, str(e), "fix storage.path or its permissions")
    return _check("storage", CheckStatus.PASS, f"{cfg.storage.path} is writable")
```

(Long lines above must be wrapped to 100 columns when written; ruff format does it.)

In `cli_ops.py`, add the parser and the command:

```python
    doctor = sub.add_parser("doctor", help="check the installation")
    _config_arg(doctor)
    doctor.add_argument("--json", action="store_true", help="print the result as JSON")
    doctor.add_argument("--no-probe", action="store_true", help="skip the test completions")
```

```python
def _doctor(args: argparse.Namespace) -> int:
    from corelata.doctor import run_doctor
    from corelata.schema import CheckStatus

    report = asyncio.run(run_doctor(args.config, probe=not args.no_probe))
    if args.json:
        print(report.model_dump_json(indent=2))
    else:
        for c in report.checks:
            print(f"{c.status.value.upper():<5} {c.name}: {c.message}")
            if c.fix and c.status is not CheckStatus.PASS:
                print(f"      fix: {c.fix}")
    return EXIT_OK if report.ok else EXIT_FAILED
```

and `"doctor": _doctor` in `COMMANDS`.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_doctor.py tests/schema -v --no-cov` — PASS. Then `uv run pytest` and lint: PASS, ≥ 95%, clean.

- [ ] **Step 5: Commit**

```bash
git add corelata/schema corelata/doctor.py corelata/cli_ops.py tests/test_doctor.py ../schema
git commit -m "feat: corelata doctor checks config, prompts, pack, models, database and storage (M3 Task 10)"
```

---

### Task 11: Documentation, example config, follow-ups ledger, spec amendments

**Files:**
- Create: `docs/m3-followups.md`
- Modify: `docs/m2-followups.md`, `docs/m1-followups.md`, `docs/trace-format.md`, `README.md`, `engine/corelata.example.yaml`, `docs/superpowers/specs/2026-10-12-corelata-v1-design.md` (§8.3, §10.2)

- [ ] **Step 1: README**

Append after the M2 section of `README.md`:

```markdown
## M3: queued runs against Postgres

The same engine runs unattended behind a job queue. Point `CORELATA_DATABASE_URL` at Postgres
16, set `storage.path` in `corelata.yaml`, then:

    uv run corelata migrate                                 # create or upgrade the schema
    uv run corelata worker &                                # process queued runs and discoveries
    uv run corelata run ../docs/examples/*.txt --project demo --statement "Varna port capacity expansion matters to shippers"
    uv run corelata status <run-id>                         # state, stages, token usage
    uv run corelata cancel <run-id>                         # stops after the current stage
    uv run corelata review <run-id> --return --note "Tighten the scope"   # a linked rerun
    uv run corelata export <run-id> --out /tmp/run2         # trace and renders from the database
    uv run corelata report /tmp/run2 --format docx --out report.docx      # uses the stored reference
    uv run corelata discover ../docs/examples/*.txt --project demo        # proposes value statements
    uv run corelata ingest more.pdf --project demo          # sources for later runs (--source-id)
    uv run corelata doctor                                  # config, prompts, pack, models, database, storage

A run is one queue job: progress, stage results and model calls land in Postgres as it goes,
and a worker that dies mid-run is detected by the stalled-job task; the run starts over and its
trace describes the attempt that produced the report (`attempts` counts them). Every export the
worker stores is reproducible from the database alone (`corelata export`).

## Development

    make db-up && make lint && make test-engine   # Postgres 16 in Docker, ruff, pytest (95% gate)

Tests need `CORELATA_TEST_DATABASE_URL` (an admin URL; `make test-engine` sets it to the dev
database on 127.0.0.1:55433). The suite creates a throwaway database per session.
```

(Replace the previous Development section's first line; keep its scenario-fixture paragraph.)

- [ ] **Step 2: Example configuration**

In `engine/corelata.example.yaml`, replace the commented M3+ block:

```yaml
# Queued deployment (corelata migrate / worker / run --project / status ...). `corelata run FILES`
# without --project needs none of these.
database: { url_env: CORELATA_DATABASE_URL }   # the variable holding postgresql://user:pass@host:5432/corelata
storage: { kind: local, path: ./files }        # uploaded sources, reference documents, exports
worker: { concurrency: 2, stalled_after_s: 900 } # runs at once per worker; requeue after this silence
# api: { max_upload_mb: 200 }                    # M4a
# auth: { mode: trusted_header, header: X-Remote-User }
# integrations:
#   coglossa: { base_url: http://coglossa-api:8080, api_key_env: CORELATA_COGLOSSA_KEY }
```

(`storage.path` is resolved relative to the config file; `./files` keeps a developer's checkout self-contained. `corelata run` without `--project` must still work with this file: the `database` section only names an environment variable and `storage` is not touched.)

Run: `uv run corelata run ../docs/examples/*.txt --statement "Varna port capacity expansion matters to shippers" --config corelata.example.yaml --out /tmp/m3-smoke` against a running `uv run corelata fake-openai` — exit 0. (Stop the fake server afterwards.)

- [ ] **Step 3: Trace format and follow-up ledgers**

`docs/trace-format.md`: in the first paragraph replace "(and, from M3, every row the API serves)" with "(and, for a queued run, what `corelata export RUN_ID --out DIR` writes from the database)"; in "Files in a run directory" add a row `reference.docx | the run's profile named one (queued runs only) | the profile's DOCX reference as stored when the run was queued; `corelata report DIR --format docx` uses it`; and in the paragraph under the table replace "(a run directory does not carry it; M3 stores it with the run)" with "(or `DIR/reference.docx` when present, which `corelata export` writes)".

`docs/m2-followups.md`: under **Should fix soon**, mark the first bullet (stored reference document) with "— **Closed in M3**: the reference is stored at submit under `runs/<id>/reference.docx`, the worker renders with it, and `corelata export` writes it beside the trace." and the `ResolvedPack.docx_reference_path` bullet with "— still open; the worker sets the field from the stored copy."

`docs/m1-followups.md`: mark "doctor command (M3, needs the database)" as closed in M3.

Create `docs/m3-followups.md`:

```markdown
# M3 follow-ups

## Divergences from Coglossa

- Product name parameterised (spec §4.3): env `CORELATA_DATABASE_URL`, `CORELATA_TEST_DATABASE_URL`,
  queue `corelata`, tasks `corelata.run`, `corelata.discover`, `corelata.requeue_stalled`, worker
  name `corelata-worker`, test databases `corelata_test_*`, loggers `corelata`/`procrastinate`.
- Migrations: two revisions (`0001_job_queue` installs procrastinate's vendored schema,
  `0002_corelata_schema` the tables) instead of Coglossa's single `0001`. Reason: Task 1 could be
  tested on its own and a procrastinate upgrade stays a one-revision change.
- `corelata migrate` instead of `coglossa db upgrade` (spec §10.2 names `migrate`).
- `cli_ops.run_command`: user errors exit 2 (Corelata's usage/config code), not 1 as in
  Coglossa; `PackError`, `OSError` and `DocxExportError` are handled too.
- `worker/app.py`: no scorer wait, no `scorer_wait_s`; `build_services` builds the pack-free
  `WorkerServices`. `logs.py`: `_FIELDS` adds `discovery_id`.
- `doctor.py`: no scorer or language-tier checks; a `pack` check (default pack and profile load)
  is added; `--no-probe` skips the test completions (Coglossa's flag skips its context probe).
- `testing/pytest_db.py`: the session database is dropped even when `upgrade` raises
  (**backport**: Coglossa's `pg_url` leaks the database on a failed upgrade).
- Storage keys: `projects/<project>/sources/<source>/<file>`, `runs/<run>/reference.docx`,
  `runs/<run>/<export>`; Coglossa uses `projects/<project>/documents/<document>/<file>`.
- Worker model: one job per run (`execute_run`) with a database-backed pipeline observer, and a
  restart from scratch after a crash, instead of Coglossa's per-stage/per-chunk idempotent jobs.
  Reason: a Corelata run is minutes (spec §16) and its model calls are not replayable.

## Spec deviations

- §8.3 tables: `run_source` (run ↔ source order) and `discovery_source` added; `digests` is a
  JSON column on `run` (spec §5.4 says stage_result rows; the ingesting stage row still lists
  what was digested); a discovery's model calls are a JSON column on `discovery`; `run` gains
  `extra_guidance`, `docx_reference_key`, `gate`, `digests`, `report`, `cancel_requested`,
  `attempts`, `export_error`, `started_at`, `finished_at`; `export` rows record the worker's
  stored renders. Recorded in the spec (§8.3) by Task 11.
- §7.2 `ingesting`: sources are parsed into units when they are uploaded (`ingest`,
  `run --project FILES`), so a bad file is refused immediately; the run's ingesting stage does
  the budget check and the digests, as in M1/M2.
- The worker executes with the live configuration; when it differs from the submit-time
  snapshot the run's `config_hash`/`config_snapshot` are replaced and a warning logged, so the
  trace tells the truth about what produced the report.
- `RunRecord.created_at` of a queued run is the submit time (the run row's `created_at`), not
  the time the worker started; `started_at` on the row carries the latter.

## Should fix soon

- `corelata status` and `run_progress` read the run row and every stage row on each call; the
  M4a SSE stream polls it every `api.progress_poll_s`. Fine for one analyst; LISTEN/NOTIFY later.
- Stalled job copies closed as `failed` accumulate in `procrastinate_jobs` (Coglossa has the same
  note); a periodic cleanup belongs in M5's operations guide.
- `clear_trace` on restart deletes the dead attempt's rows. If a crashed attempt's partial trace
  turns out to matter for incident analysis, keep the rows with an `attempt` column instead.
- `add_source` parses the upload inside the request (PDF parsing can take seconds); the API
  (M4a) should run it in a thread.
- `cancel_run` on a run whose worker died between stage boundaries waits for the stalled-job
  requeue; the restarted execution then sees the flag at once.

## Later

- M4a: `POST /runs` → `service.start_run`; `GET /runs/{id}` → `run_progress`; SSE polls it;
  `GET /runs/{id}/report` → `export` rows (or `render_outputs` on `get_run_record`);
  `GET /runs/{id}/trace|findings|claims/{id}` → `corelata.trace` on `get_run_record`;
  `POST /runs/{id}/review` → `review_run`; `POST /discoveries` → `start_discovery`;
  `GET /system/doctor` → `run_doctor`.
- M5: compose `migrate` one-shot service runs `corelata migrate`; `worker` gets
  `stop_grace_period` long enough for a stage to finish (a killed stage is redone from scratch).
```

- [ ] **Step 4: Spec amendments**

In the spec, §8.3, replace the paragraph with:

```markdown
`project`, `source`, `source_unit`, `run`, `run_source` (the run's sources in order; ordinal n is
`src<n>` in the trace), `discovery`, `discovery_source`, `discovery_candidate`, `stage_result`
(one row per attempt of every stage, with iteration and output JSON), `draft` (role, iteration,
`Report` JSON), `claim`, `claim_evidence` (the delivered report's claims and the units they
cite), `audit_finding`, `llm_call`, `review_event`, `export` (the worker's stored renders).
Procrastinate's tables are vendored as in Coglossa. `run` holds `state`, `status`, `config_hash`,
`config_snapshot`, `pack_hash`, `pack_snapshot`, `profile`, `value_statement`, `extra_guidance`,
`iteration`, `max_iterations`, `parent_run_id` (for reruns after rejection or return),
`docx_reference_key` (the profile's reference document as stored when the run was queued),
`gate`, `digests` (M3: on the run row rather than in stage_result), `report`, `token_usage` JSON,
`cancel_requested`, `attempts`, `error`, `export_error`, `created_at`, `started_at`,
`finished_at`. A discovery's few model calls are a JSON column on `discovery`.
```

In §10.2, after the sentence "`corelata run` can execute in-process without Postgres for M1 (results written to a directory), and against the database from M3." add: "With `--project NAME` (M3) `run` and `discover` ingest their inputs into the project and queue the work; `ingest`, `status`, `cancel`, `review`, `export`, `migrate`, `worker` and `doctor` complete the queued surface."

- [ ] **Step 5: Verify and commit**

Run: `uv run pytest` and `uv run ruff check . && uv run ruff format --check .` — PASS, ≥ 95%, clean. Run `make schema` and `git status --short ../schema` — no changes (everything regenerated in earlier tasks is committed).

```bash
git add ../README.md corelata.example.yaml ../docs/m3-followups.md ../docs/m2-followups.md ../docs/m1-followups.md ../docs/trace-format.md ../docs/superpowers/specs/2026-10-12-corelata-v1-design.md
git commit -m "docs: M3 README section, example config, follow-ups ledger and spec §8.3/§10.2 amendments (M3 Task 11)"
```

---

## Self-review notes (plan author)

- Spec coverage, §14 M3 row: Postgres schema (Tasks 1, 2), alembic (1, 2), procrastinate worker (6, 8), service layer (5, 7), discovery job (7), stalled requeue (8), `parent_run_id` reruns (3, 5, 9). Exit test "a run executes through the queue; cancel and requeue tested": Task 8 `test_the_worker_completes_a_queued_run` (real procrastinate), Task 6 cancel tests, Task 8 requeue tests, Task 9 CLI lifecycle. Stored DOCX reference (M2 follow-up): Tasks 5, 6, 9. `doctor`, `migrate`, `worker`, `ingest`, `review` (§10.2): Tasks 8, 9, 10.
- Type consistency checked: `runs.create_run(... source_ids=, run_id=, created_at=)` (Task 2) is called the same way in Tasks 4 and 5; `records.save_outcome(s, run, record, *, source_ids, stages_from, calls_from)` (Task 4) matches Task 6; `DbObserver.stages_saved`/`calls_saved` (Task 6) match `save_outcome`'s keywords; `service.RunRequest` fields match `_create_run` and `cli_ops._queue_run`; `RunObserver` method names match `DbObserver`; `TASK_RUN`/`TASK_DISCOVER` kwargs are `run_id` / `discovery_id` strings everywhere; `RunOptions.created_at` (Task 3) is what Task 6 passes.
- Review Focus 1–6 each have a named test: 1 → Task 6 `test_a_crashed_execution_is_started_over`, Task 8 `test_burst_requeues_the_jobs_of_a_crashed_worker`; 2 → Task 6 cancel tests, Task 5 `test_cancel_a_created_run_ends_it_at_once`; 3 → Task 6 `test_a_redelivered_job_for_a_finished_run_does_nothing`; 4 → Task 5 `test_start_run_stores_the_profile_reference_document`, Task 6 `test_the_run_renders_with_the_stored_reference_even_after_it_changed`, Task 9 `test_export_carries_the_reference_document_and_report_uses_it`; 5 → Task 1 silent-host tests, Task 8 `test_migrate_unreachable_database`/`test_missing_database_configuration_is_a_usage_error`, Task 9 `test_an_unmigrated_database_is_refused`; 6 → Task 2 `test_source_round_trip_strips_nul`.
