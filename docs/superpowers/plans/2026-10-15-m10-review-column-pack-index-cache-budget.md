# M10 Review Column, Pack Index and Cache Budget Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the four follow-up tickets filed from `docs/m9-followups.md` (Jira CRL-17, CRL-18, CRL-19, CRL-20): the review decision is stored once on the run row instead of being derived on every progress read, the pack listing stops re-statting every file on every request and sees edits inside symlinked packs, the claim-id render cache gets a byte budget, and the test debt M9 left behind is paid.

**Architecture:** Engine side, migration 0004 adds `run.review_state` (JSON) and backfills it from `review_event`; `service.review_run` recomputes and stores it in every transaction that touches a review event, and `run_progress` reads only the column. `pack_dirs_signature` walks with `os.walk(followlinks=True)` and a visited-realpath guard; `PACK_NAME_MAX_LENGTH` joins `PACK_NAME_PATTERN` as the single source for the API route and the doctor. API side, `PackIndex` re-stats at most once per `min_interval_s` (injectable clock), and `RenderCache` evicts by bytes as well as by count, sized by `api.render_cache_mb`. Web side, tests only, plus the `<head>` regex in `withBridge`. No response model changes and no new route, so `make schema` is not run.

**Tech Stack:** Python 3.12, SQLAlchemy 2 async, Alembic, pydantic 2, FastAPI, asyncio; React 19 + TypeScript, TanStack Query 5, Vitest + msw; Markdown docs.

**Spec:** `docs/superpowers/specs/2026-10-12-corelata-v1-design.md` — §8.3 (tables: `run` columns), §10.1 (API: `GET /runs/{id}`, `GET /packs`, `GET /runs/{id}/report?with_claim_ids=1`), §10.3 (web: review screen, report frame, run list), §11 (`api.*` configuration), §13 (quality gates). The tickets' text is in Jira CRL-17/18/19/20; the items they bundle are quoted in `docs/m9-followups.md` ("Should fix soon" lines 21-32, "Later" lines 42-59).

## Global Constraints

- 95% branch coverage for `engine` and `api` (`--cov-fail-under=95`), `filterwarnings = ["error"]`; `ruff check` and `ruff format --check` clean (line length 100). Vitest 95% on lines, branches, functions and statements; `pnpm lint` (eslint, prettier, `tsc --noEmit`) clean.
- Python tests that touch Postgres run against the dev database (`make db-up`; `CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres`). A single test file: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/x.py --no-cov -q` (and the same from `api/`). Full gates: `make test-engine`, `make test-api`, `make test-web`, `make lint`.
- **No new API route and no response-model change** (R-M10-6). `api/tests/test_openapi.py::test_every_screen_has_its_routes` lists exactly 22 paths and stays as it is; `make schema` is not run; `schema/` and `web/src/api/schema.d.ts` are untouched. `test_committed_openapi_matches_the_app` and the `web` CI job (`pnpm gen:api && git diff --exit-code src/api/schema.d.ts`) enforce it. `ReviewState` keeps its fields.
- The trace format and every export are unchanged. `review_event` stays the audit trail; `run.review_state` is derived from it.
- `api/tests/test_reports.py::test_re_render_failures` monkeypatches `reports._render`; that name stays.
- Web tests mock every request with msw (`web/src/test/setup.ts` fails an unmocked one); poll intervals are read through `web/src/test/poll.ts`, never fake timers. Fixtures live in `web/src/test/fixtures.ts`. A loading state is held open by a deferred msw response the test resolves (`web/src/test/deferred.ts`, Task 6), never by a real delay.
- Commit messages end with the two attribution lines the session uses; write them to a uniquely named scratchpad file and `git commit -F FILE`. Never `git stash`. Never `git add .` (the SDD workspace is not ignored).
- Rulings (record in the SDD ledger, carried here). R-M9-1 to R-M9-10 (`docs/superpowers/plans/2026-10-15-m9-efficiency-and-review-state.md`) and R-M9-11/12 (`docs/m9-followups.md`) stay in force.
  - **R-M10-1** `run.review_state` holds `ReviewState.model_dump(mode="json")` or NULL. `review_run` recomputes it after adding the event as `_review_state(await load_review_events(s, run_id))` inside the same transaction (one extra indexed query on a review, none on progress). `run_progress` reads only `run.review_state` and never `review_event`. Migration 0004 backfills in Python over `review_event` grouped by `run_id` with the same function's rule (write the rule out in SQL or Python inside the migration; the migration must not import `corelata.service`).
  - **R-M10-2** `PackIndex(packs_dir, min_interval_s=1.0, clock=time.monotonic)`: the first call stats; later calls re-stat only when `clock() - last_stat >= min_interval_s`, otherwise they serve the last listing. An edit may take up to one second to appear; the operator guide says so.
  - **R-M10-3** `pack_dirs_signature` uses `os.walk(top, followlinks=True)` with a set of `os.path.realpath` of visited directories to stop cycles; output stays a sorted tuple of `(path, size, mtime_ns)`; a file that vanishes between listing and stat is skipped (M9 behaviour kept).
  - **R-M10-4** `loader.PACK_NAME_MAX_LENGTH = 100`; `routes/packs.py` builds `PackName` from `PACK_NAME_PATTERN.pattern` and `PACK_NAME_MAX_LENGTH`; the doctor's `pack names` WARN covers both the pattern and the length and its fix text interpolates both constants.
  - **R-M10-5** `RenderCache(capacity=64, max_bytes=64 * 1024 * 1024)`; `put` evicts LRU entries until `len(content) + total_bytes <= max_bytes` and `len(self) < capacity`; an entry with `len(content) > max_bytes` is not stored; `max_bytes == 0` stores nothing. `ApiConfig.render_cache_mb: int = Field(64, ge=0)`; the lifespan passes `max_bytes=cfg.api.render_cache_mb * 1024 * 1024`.
  - **R-M10-6** No response model changes and no new route in M10: `make schema` is not run and `schema/`, `web/src/api/schema.d.ts` are untouched. `test_every_screen_has_its_routes` stays at its current path count.
  - **R-M10-7** Web loading-state tests use a deferred msw response the test resolves, never a real delay and never fake timers.
  - **R-M10-8** `withBridge` matches the opening head tag with `/<head\b[^>]*>/i`; when no head is present the meta goes right after the doctype if there is one, else at the start (check what the code does today and keep the doctype case correct).

## Review Focus

1. **A progress poll on a reviewed run must not query `review_event`, and a return whose rerun fails to be created must leave the stored decision as it was before.** Pinned in Task 1 (`test_run_progress_reads_the_stored_decision_not_the_events`, `test_review_run_stores_the_decision_on_the_run_row`).
2. **After an upgrade, every run reviewed before M10 must show the same decision it showed under M9.** Pinned in Task 1 (`test_0004_backfills_review_state_from_the_review_events`).
3. **An operator who edits a rule inside a symlinked pack must see it in `GET /api/packs` within a second, and a link cycle must not hang the API.** Pinned in Task 2 (`test_pack_dirs_signature_follows_a_symlinked_pack_and_stops_at_a_cycle`) and Task 3 (`test_the_listing_is_restatted_at_most_once_per_interval`).
4. **The claim-id render cache must stay within its byte budget and entry count under concurrent load.** Pinned in Task 4 (`test_a_byte_budget_evicts_the_least_recently_used_until_the_new_entry_fits`, `test_concurrent_claim_id_renders_for_65_runs_keep_64_entries`).
5. **Two analysts on one run must share one poller, and a closed tab must stop the polling.** Pinned in Task 5 (`test_two_streams_on_one_run_share_one_poller_and_leave_none`, `test_a_stream_cancelled_mid_wait_unsubscribes_and_stops_the_poller`).

---

## File structure

| Path | Responsibility |
|---|---|
| `engine/corelata/store/migrations/versions/0004_run_review_state.py` (new) | `run.review_state` column and its backfill from `review_event`. |
| `engine/corelata/store/models.py` | `Run.review_state`. |
| `engine/corelata/store/runs.py` | `lock_run`, `set_review_state`. |
| `engine/corelata/service.py` | `_store_review_state`; `review_run` writes it; `_progress`/`run_progress` read it. |
| `engine/corelata/store/migrate.py` | docstring names 0004. |
| `engine/corelata/standards/loader.py` | `PACK_NAME_MAX_LENGTH`; `pack_dirs_signature` follows symlinks. |
| `engine/corelata/doctor.py` | `pack names` checks the length and builds its fix text from the constants. |
| `engine/corelata/config.py`, `engine/corelata.example.yaml`, `deploy/config/corelata.example.yaml` | `api.render_cache_mb`. |
| `api/corelata_api/pack_index.py` | debounce with an injectable clock. |
| `api/corelata_api/routes/packs.py` | `PackName` from the shared constants. |
| `api/corelata_api/render_cache.py`, `api/corelata_api/context.py`, `api/corelata_api/app.py` | byte budget; lifespan wiring. |
| `web/src/pages/review/frameBridge.ts` | head regex; doctype placement. |
| `web/src/test/deferred.ts` (new) | a promise a test settles itself, for loading states. |
| tests: `engine/tests/{test_service,test_doctor,test_cli_ops,test_config}.py`, `engine/tests/store/{test_runs,test_migrations}.py`, `engine/tests/standards/test_loader.py`, `api/tests/{test_packs,test_pack_index (new),test_render_cache,test_reports,test_progress_feed,test_progress}.py`, `web/src/pages/review/{ReviewActions,AuditTab}.test.tsx`, `web/src/pages/review/frameBridge.test.ts`, `web/src/pages/new/RunList.test.tsx` | the tickets' tests. |
| `docs/operator-guide.md`, `README.md`, spec, `docs/m9-followups.md`, `docs/m10-followups.md` (new) | docs. |

---

### Task 1: The review decision lives on the run row (CRL-17)

`run_progress` runs `load_review_events` for every completed run on every call, and the shared SSE poller calls it every `api.progress_poll_s` while a completed run is watched. A return touches the events in three transactions (the placeholder under the row lock, `set_review_child` after the rerun exists, `delete_review_event` when creating it failed), so the stored state is recomputed in each of the three, not only in the first; the second and third take the run row's lock first (`runs.lock_run`) so a concurrent accept on the same run serialises with them.

**Files:**
- Create: `engine/corelata/store/migrations/versions/0004_run_review_state.py`
- Modify: `engine/corelata/store/models.py` (`Run`, after line 149), `engine/corelata/store/runs.py` (after `delete_review_event`, line 536), `engine/corelata/service.py` (`review_run` lines 373-443, `_progress` 463, `run_progress` 485), `engine/corelata/store/migrate.py` (docstring)
- Test: `engine/tests/test_service.py`, `engine/tests/store/test_runs.py`, `engine/tests/store/test_migrations.py`, `engine/tests/test_doctor.py` (line 59), `engine/tests/test_cli_ops.py` (line 56)

**Interfaces:**
- Produces: `Run.review_state: dict | None`; `runs.lock_run(s, run_id) -> None`; `runs.set_review_state(s, run_id, state: dict | None) -> None` (None writes SQL NULL); `service._store_review_state(s, run_id) -> None`; `_progress(run, stages)` (the `review` parameter is gone; it reads `run.review_state`). Alembic head `0004`.

- [ ] **Step 1: Failing tests**

Append to `engine/tests/test_service.py`:

```python
async def test_review_run_stores_the_decision_on_the_run_row(svc, monkeypatch):
    pid = await svc.project()
    run_id = await svc.run(pid, [await svc.source(pid)])
    await _set_state(svc.db, run_id, "completed")
    args = (svc.db, svc.storage, svc.queue, svc.cfg, svc.prompts, run_id)

    async def stored():
        async with svc.db.session() as s:
            return (await runs.get_run(s, run_id)).review_state

    assert await stored() is None
    await service.review_run(*args, ReviewAction.ACCEPT, actor="alice")
    accepted = await stored()
    assert accepted["decision"] == "accepted" and accepted["actor"] == "alice"
    seen = {}

    async def boom(*a, **kw):
        seen["during"] = await stored()  # after the placeholder's transaction committed
        raise RuntimeError("disk full")

    monkeypatch.setattr(service, "_create_run", boom)
    with pytest.raises(RuntimeError):
        await service.review_run(*args, ReviewAction.RETURN, note="x", actor="bob")
    assert seen["during"]["decision"] == "returned" and seen["during"]["child_run_id"] is None
    assert await stored() == accepted  # the placeholder went, and its decision with it
    monkeypatch.undo()
    child = await service.review_run(*args, ReviewAction.RETURN, note="tighten", actor="bob")
    returned = await stored()
    assert returned["decision"] == "returned" and returned["child_run_id"] == str(child)
    async with svc.db.session() as s:
        events = await runs.load_review_events(s, run_id)
    assert returned == service._review_state(events).model_dump(mode="json")


async def test_run_progress_reads_the_stored_decision_not_the_events(svc, monkeypatch):
    pid = await svc.project()
    run_id = await svc.run(pid, [await svc.source(pid)])
    await _set_state(svc.db, run_id, "completed")
    args = (svc.db, svc.storage, svc.queue, svc.cfg, svc.prompts, run_id)
    await service.review_run(*args, ReviewAction.ACCEPT, actor="alice")

    async def forbidden(s, run_id):
        raise AssertionError("run_progress must not read review_event")

    monkeypatch.setattr(runs, "load_review_events", forbidden)
    review = (await service.run_progress(svc.db, run_id)).review
    assert review is not None and (review.decision, review.actor) == ("accepted", "alice")
```

In `engine/tests/store/test_runs.py`, change the import `from corelata.store.models import ClaimEvidenceRow, ClaimRow, utcnow` to `from corelata.store.models import ClaimEvidenceRow, ClaimRow, Run, utcnow`; in `test_get_run_brief_leaves_the_heavy_columns_unloaded` (line 303) add after `assert {"report", ...} <= unloaded`:

```python
        assert "review_state" not in unloaded  # small, and the progress read needs it
```

and after `assert progress.run_id == str(run_id) and progress.stages == []`:

```python
        assert progress.review is None
```

Append:

```python
async def test_set_review_state_writes_and_clears_the_column(db):
    state = {
        "decision": "accepted",
        "at": "2026-10-15T10:00:00Z",
        "actor": "alice",
        "child_run_id": None,
    }
    async with db.session() as s, s.begin():
        project, src = await _project_with_source(s)
        run_id = (await _run(s, project, [src])).id
        assert (await runs.get_run(s, run_id)).review_state is None
        await runs.lock_run(s, run_id)
        await runs.set_review_state(s, run_id, state)
    async with db.session() as s, s.begin():
        assert (await runs.get_run_brief(s, run_id)).review_state == state
        await runs.set_review_state(s, run_id, None)
    async with db.session() as s:
        is_null = await s.scalar(select(Run.review_state.is_(None)).where(Run.id == run_id))
        assert is_null is True  # SQL NULL, not the JSON value null
```

In `engine/tests/store/test_migrations.py`: change `HEAD = "0003"` (line 28) to `HEAD = "0004"`; replace the import lines 1-8 with

```python
import uuid
from datetime import UTC, datetime

from procrastinate.schema import SchemaManager
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import NullPool

from corelata.schema import ReviewState
from corelata.store.db import to_sqlalchemy_url
from corelata.store.migrate import MIGRATIONS_DIR, downgrade, migration_state, upgrade
from corelata.store.models import Base
from corelata.testing.postgres import PROCRASTINATE_TABLES, create_test_database, drop_test_database
```

and append:

```python
# A run row as revision 0003 has it (no review_state); every NOT NULL column is given.
_RUN_AT_0003 = (
    "INSERT INTO run (id, project_id, state, value_statement, extra_guidance, max_iterations, "
    "iteration, config_hash, config_snapshot, pack_name, pack_hash, pack_snapshot, "
    "prompt_versions, corelata_version, digests, cancel_requested, attempts, created_at) "
    "VALUES (:id, :project, 'completed', 'v', '', 2, 1, 'h', '{}', 'icd203-base', 'ph', '{}', "
    "'{}', '0.1.0', '[]', false, 1, :at)"
)
_EVENT = (
    "INSERT INTO review_event (run_id, action, note, actor, child_run_id, at) "
    "VALUES (:run, :action, '', :actor, :child, :at)"
)


def test_0004_backfills_review_state_from_the_review_events(pg_admin):
    url = create_test_database(pg_admin)
    engine = create_engine(to_sqlalchemy_url(url), poolclass=NullPool)
    try:
        upgrade(url, "0003")
        project = uuid.uuid4()
        ids = {k: uuid.uuid4() for k in ("accepted", "returned", "placeholder", "none", "child")}
        t = [datetime(2026, 10, 15, 10, minute, tzinfo=UTC) for minute in range(4)]
        events = [
            ("accepted", "accept", "alice", None, t[0]),
            ("accepted", "accept", "bob", None, t[1]),  # the latest accept wins
            ("returned", "accept", "alice", None, t[0]),
            ("returned", "return", "carol", ids["child"], t[2]),
            ("returned", "accept", "dave", None, t[3]),  # a later accept does not undo a return
            ("placeholder", "return", "erin", None, t[1]),  # its rerun was never linked
        ]
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO project (id, name, created_at) VALUES (:id, 'p', :at)"),
                {"id": project, "at": t[0]},
            )
            for run_id in ids.values():
                conn.execute(text(_RUN_AT_0003), {"id": run_id, "project": project, "at": t[0]})
            for run, action, actor, child, at in events:
                conn.execute(
                    text(_EVENT),
                    {"run": ids[run], "action": action, "actor": actor, "child": child, "at": at},
                )
        upgrade(url)
        with engine.connect() as conn:
            stored = dict(conn.execute(text("SELECT id, review_state FROM run")).all())
        assert ReviewState.model_validate(stored[ids["accepted"]]) == ReviewState(
            decision="accepted", at=t[1], actor="bob"
        )
        assert ReviewState.model_validate(stored[ids["returned"]]) == ReviewState(
            decision="returned", at=t[2], actor="carol", child_run_id=str(ids["child"])
        )
        assert ReviewState.model_validate(stored[ids["placeholder"]]) == ReviewState(
            decision="returned", at=t[1], actor="erin"
        )
        assert stored[ids["none"]] is None and stored[ids["child"]] is None
        downgrade(url, "0003")
        assert "review_state" not in {c["name"] for c in inspect(engine).get_columns("run")}
    finally:
        engine.dispose()
        drop_test_database(pg_admin, url)
```

In `engine/tests/test_doctor.py` line 59 change `assert "0003" in checks["database"].message` to `assert "0004" in checks["database"].message`; in `engine/tests/test_cli_ops.py` line 56 change `"at revision 0003" in out` to `"at revision 0004" in out`.

- [ ] **Step 2: Run them to see them fail**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/test_service.py tests/store/test_runs.py tests/store/test_migrations.py --no-cov -q -k "stores_the_decision or stored_decision or set_review_state or brief or 0004 or migration_state"`
Expected: FAIL — `AttributeError: 'Run' object has no attribute 'review_state'` (service, store), `AttributeError: ... has no attribute 'set_review_state'`, `assert '0003' == '0004'`, and the backfill test fails on `SELECT id, review_state` (`column "review_state" does not exist`).

- [ ] **Step 3: The column and the migration**

`engine/corelata/store/models.py`, in `class Run` after `export_error: Mapped[str | None]  # ...` (line 149):

```python
    review_state: Mapped[Json | None]  # ReviewState JSON, written by review_run (CRL-17)
```

Create `engine/corelata/store/migrations/versions/0004_run_review_state.py`:

```python
"""run.review_state: the review decision, stored once (CRL-17)

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-15 13:00:00.000000

`RunProgress.review` was derived from review_event on every progress read. The decision now lives
on the run row, written by `service.review_run` with each event; review_event stays the audit
trail. The backfill applies `service._review_state`'s rule, written out here so this revision
never imports the service: a return wins (even a placeholder whose rerun was never linked), else
the latest accept. `at` is written as pydantic writes it (`...Z`).
"""

import json
from collections.abc import Sequence
from datetime import UTC
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _iso(at: Any) -> str:
    return at.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _decision(events: list[Any]) -> dict[str, Any]:
    """`events`: one run's (action, actor, child_run_id, at) rows, oldest first."""
    returned = next((e for e in events if e.action == "return"), None)
    if returned is not None:
        child = str(returned.child_run_id) if returned.child_run_id else None
        return {
            "decision": "returned",
            "at": _iso(returned.at),
            "actor": returned.actor,
            "child_run_id": child,
        }
    latest = events[-1]  # no return, so every event is an accept
    return {
        "decision": "accepted",
        "at": _iso(latest.at),
        "actor": latest.actor,
        "child_run_id": None,
    }


def upgrade() -> None:
    op.add_column(
        "run",
        sa.Column("review_state", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT run_id, action, actor, child_run_id, at FROM review_event "
            "ORDER BY run_id, at, id"
        )
    ).all()
    by_run: dict[Any, list[Any]] = {}
    for row in rows:
        by_run.setdefault(row.run_id, []).append(row)
    store = sa.text("UPDATE run SET review_state = CAST(:state AS jsonb) WHERE id = :id")
    for run_id, events in by_run.items():
        bind.execute(store, {"id": run_id, "state": json.dumps(_decision(events))})


def downgrade() -> None:
    op.drop_column("run", "review_state")
```

`engine/corelata/store/migrate.py` docstring line 2-3: change "0003 the orphan-sweep indexes;" to "0003 the orphan-sweep indexes, 0004 `run.review_state`;".

- [ ] **Step 4: Store and service**

`engine/corelata/store/runs.py`: change `from sqlalchemy import delete, select, update` to `from sqlalchemy import delete, null, select, update`, and after `delete_review_event` (line 536-537):

```python
async def lock_run(s: AsyncSession, run_id: uuid.UUID) -> None:
    """Take the run row's lock for the rest of the transaction without loading the row."""
    await s.execute(select(Run.id).where(Run.id == run_id).with_for_update())


async def set_review_state(
    s: AsyncSession, run_id: uuid.UUID, state: dict[str, Any] | None
) -> None:
    """The run's review decision as `ReviewState` JSON (CRL-17, R-M10-1); None is SQL NULL."""
    await s.execute(
        update(Run).where(Run.id == run_id).values(review_state=state if state else null())
    )
```

`engine/corelata/service.py`:

Add `from sqlalchemy.ext.asyncio import AsyncSession` after `from sqlalchemy.exc import IntegrityError`.

Before `review_run` (line 373):

```python
async def _store_review_state(s: AsyncSession, run_id: uuid.UUID) -> None:
    """Recompute the decision from the events this transaction sees and store it on the run
    (CRL-17, R-M10-1): one indexed read per review, none per progress read. The row lock comes
    first, so a concurrent review of the same run waits and then sees this one's events."""
    await runs.lock_run(s, run_id)
    state = _review_state(await runs.load_review_events(s, run_id))
    await runs.set_review_state(s, run_id, state.model_dump(mode="json") if state else None)
```

In `review_run`, the accept branch (lines 394-396) becomes:

```python
        if action is ReviewAction.ACCEPT:
            await runs.add_review_event(s, run_id, action.value, note, actor, None)
            await _store_review_state(s, run_id)
            return None
```

after `event_id = event.id` (line 410) add:

```python
        await _store_review_state(s, run_id)  # "returned", no rerun yet
```

and the tail (lines 436-441) becomes:

```python
        async with db.session() as s, s.begin():
            await runs.set_review_child(s, event_id, child)
            await _store_review_state(s, run_id)
    except BaseException:
        async with db.session() as s, s.begin():
            await runs.delete_review_event(s, event_id)
            await _store_review_state(s, run_id)
        raise
```

Replace `_progress`'s signature line and its `review=review,` argument (lines 463 and 478):

```python
def _progress(run: Run, stages: list) -> RunProgress:
```

```python
        review=ReviewState.model_validate(run.review_state) if run.review_state else None,
```

Replace `run_progress` (lines 485-493) with:

```python
async def run_progress(db: Database, run_id: uuid.UUID) -> RunProgress:
    async with db.session() as s:
        run = await runs.get_run_brief(s, run_id)
        # The decision is stored on the run by review_run (CRL-17, R-M10-1); review_event is
        # never read here.
        return _progress(run, await runs.load_stages(s, run_id))
```

`ReviewEvent` stays imported (`_review_state`'s annotation).

- [ ] **Step 5: Run the engine suite and lint**

Run: `make test-engine` and `cd engine && uv run ruff check . && uv run ruff format --check .`
Expected: all pass, coverage ≥ 95%. `test_models_match_the_migrations` passes (the model and 0004 agree), `test_downgrade_then_upgrade_again` passes through 0004 both ways, `test_run_progress_carries_the_review_decision` still passes unchanged, and `test_a_failed_return_leaves_no_placeholder_event` covers the `None` branch of `_store_review_state`. If ruff format reflows anything in the new code, accept its formatting.

- [ ] **Step 6: Commit**

```bash
cat > <scratchpad>/m10-task1-commit.txt <<'EOF'
feat(engine): store the review decision on the run row (CRL-17)

Migration 0004 adds run.review_state and backfills it from review_event with
the same rule as service._review_state. review_run recomputes it in every
transaction that touches a review event; run_progress reads only the column.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git add engine/corelata/store/migrations/versions/0004_run_review_state.py engine/corelata/store/models.py engine/corelata/store/runs.py engine/corelata/service.py engine/corelata/store/migrate.py engine/tests/test_service.py engine/tests/store/test_runs.py engine/tests/store/test_migrations.py engine/tests/test_doctor.py engine/tests/test_cli_ops.py
git commit -F <scratchpad>/m10-task1-commit.txt
```

---

### Task 2: The signature follows symlinked packs; one pack-name rule (CRL-18, engine)

`Path.rglob` does not descend into a symlinked directory, so a pack linked into `packs_dir` is listed but its edits never change the signature. The doctor's fix text spells the pattern out by hand and ignores the route's 100-character limit.

**Files:**
- Modify: `engine/corelata/standards/loader.py` (imports; `PACK_NAME_MAX_LENGTH` after line 30; `pack_dirs_signature` lines 165-179), `engine/corelata/doctor.py` (import line 24; `_pack_names` lines 160-175)
- Test: `engine/tests/standards/test_loader.py`, `engine/tests/test_doctor.py`

**Interfaces:**
- Produces: `loader.PACK_NAME_MAX_LENGTH: int = 100` (Task 3 uses it in the route); `pack_dirs_signature` keeps its signature and return type (Task 3's `PackIndex` calls it unchanged).

- [ ] **Step 1: Failing tests**

Append to `engine/tests/standards/test_loader.py`:

```python
def test_pack_dirs_signature_follows_a_symlinked_pack_and_stops_at_a_cycle(tmp_path):
    from corelata.standards.loader import list_packs, pack_dirs_signature

    elsewhere = write_pack(tmp_path / "elsewhere", "team", rules=[RULE], extends="icd203-base")
    packs = tmp_path / "packs"
    packs.mkdir()
    (packs / "team").symlink_to(elsewhere, target_is_directory=True)
    (elsewhere / "rules" / "loop").symlink_to(elsewhere, target_is_directory=True)  # a cycle
    assert "team" in [p.name for p in list_packs(packs)]
    rule_file = next((elsewhere / "rules").glob("*.yaml"))
    before = pack_dirs_signature(packs)
    seen = [entry[0] for entry in before if entry[0].endswith(rule_file.name)]
    assert seen == [str(packs / "team" / "rules" / rule_file.name)]  # through the link, once
    assert list(before) == sorted(before)
    later = time.time() + 10
    os.utime(rule_file, (later, later))  # an edit inside the linked pack
    assert pack_dirs_signature(packs) != before
```

`test_pack_dirs_signature_skips_a_file_that_vanished_mid_scan` (line 444) stays as it is: the new walk still calls `Path.stat` directly inside `pack_dirs_signature`, which is what its frame check looks for.

In `engine/tests/test_doctor.py` add `from corelata.standards.loader import PACK_NAME_MAX_LENGTH, PACK_NAME_PATTERN` after `from corelata.schema import CheckStatus`, and append:

```python
async def test_over_long_pack_names_are_a_warning_with_the_shared_rules(tmp_path, server):
    assert PACK_NAME_MAX_LENGTH == 100  # the API route's max_length
    packs = tmp_path / "packs"
    too_long = "a" * (PACK_NAME_MAX_LENGTH + 1)
    for name in (too_long, "b" * PACK_NAME_MAX_LENGTH):
        (packs / name).mkdir(parents=True)
        (packs / name / "pack.yaml").write_text(
            yaml.safe_dump({"name": "x", "version": "1.0", "extends": "icd203-base"}),
            encoding="utf-8",
        )
    path = _config(tmp_path, server.base_url, standards={"packs_dir": str(packs)})
    report = await run_doctor(path, probe=False)
    check = _by_name(report)["pack names"]
    assert check.status is CheckStatus.WARN
    assert check.message == f"1 pack directory cannot be addressed through the API: {too_long}"
    assert PACK_NAME_PATTERN.pattern in check.fix
    assert f"at most {PACK_NAME_MAX_LENGTH} characters" in check.fix
    assert report.ok
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/standards/test_loader.py tests/test_doctor.py --no-cov -q -k "symlinked or over_long or unaddressable or vanished"`
Expected: the symlink test FAILS on `assert seen == [...]` (`[]`: rglob skipped the link); the doctor test FAILS with `ImportError: cannot import name 'PACK_NAME_MAX_LENGTH'`. `test_unaddressable_pack_directories_are_a_warning` and the vanish test pass.

- [ ] **Step 3: The loader**

`engine/corelata/standards/loader.py`: add `import os` after `import json`. After `PACK_NAME_PATTERN = re.compile(...)` (line 30):

```python
# ...and its length limit. The route's `max_length` and the doctor share both (R-M10-4).
PACK_NAME_MAX_LENGTH = 100
```

Replace `pack_dirs_signature` (lines 165-179):

```python
def pack_dirs_signature(packs_dir: Path | None) -> tuple[tuple[str, int, int], ...]:
    """Every file under the pack directories with its size and mtime (ns), sorted. Equal
    signatures mean the listing is unchanged; directory mtimes alone miss an edit inside rules/
    (R-M9-4). Symlinked directories are walked too, each real directory once, so a link cycle
    ends the walk (R-M10-3). Stats only: no file is opened."""
    out: list[tuple[str, int, int]] = []
    visited: set[str] = set()
    for base in (BUILTIN_PACKS_DIR, packs_dir):
        if base is None or not base.is_dir():
            continue
        for top, dirs, files in os.walk(base, followlinks=True):
            real = os.path.realpath(top)
            if real in visited:
                dirs[:] = []  # a cycle, or a second link to a directory already walked
                continue
            visited.add(real)
            for name in files:
                path = Path(top, name)
                try:
                    st = path.stat()
                except FileNotFoundError:  # renamed away (or a dangling link) since the walk
                    continue
                out.append((str(path), st.st_size, st.st_mtime_ns))
    return tuple(sorted(out))
```

- [ ] **Step 4: The doctor**

`engine/corelata/doctor.py` line 24: `from corelata.standards.loader import PACK_NAME_MAX_LENGTH, PACK_NAME_PATTERN, PackError, list_packs`. Replace `_pack_names` (lines 160-175):

```python
def _addressable(name: str) -> bool:
    return len(name) <= PACK_NAME_MAX_LENGTH and PACK_NAME_PATTERN.match(name) is not None


def _pack_names(cfg: CorelataConfig) -> DoctorCheck:
    """A pack directory the API cannot address loads fine but has no `/api/packs/{name}` routes,
    so the Audit tab shows rule ids instead of titles for runs on it (CRL-16, R-M9-7). The rules
    are the route's own: the pattern and the length limit (R-M10-4)."""
    names = [p.name for p in list_packs(cfg.standards.packs_dir)]
    bad = sorted(name for name in names if not _addressable(name))
    if not bad:
        return _check("pack names", CheckStatus.PASS, "every pack directory is addressable")
    noun = "directory" if len(bad) == 1 else "directories"
    return _check(
        "pack names",
        CheckStatus.WARN,
        f"{len(bad)} pack {noun} cannot be addressed through the API: {', '.join(bad)}",
        f"rename to lowercase letters, digits and hyphens ({PACK_NAME_PATTERN.pattern}), at most "
        f"{PACK_NAME_MAX_LENGTH} characters, and point standards.default_pack at the new name",
    )
```

- [ ] **Step 5: Run the engine suite and lint**

Run: `make test-engine` and `cd engine && uv run ruff check . && uv run ruff format --check .`
Expected: all pass; `test_pack_dirs_signature_sees_a_nested_edit` (its `endswith("icd203-base/pack.yaml")` check) and `test_unaddressable_pack_directories_are_a_warning` (its `"lowercase letters, digits and hyphens"` check) still pass.

- [ ] **Step 6: Commit**

```bash
cat > <scratchpad>/m10-task2-commit.txt <<'EOF'
feat(engine): pack signature follows symlinked packs; one pack-name rule (CRL-18)

pack_dirs_signature walks with os.walk(followlinks=True) and stops at a
directory it has already walked, so edits inside a linked pack refresh the
listing and a link cycle ends. PACK_NAME_MAX_LENGTH joins PACK_NAME_PATTERN;
the doctor warns on over-long names and builds its fix text from both.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git add engine/corelata/standards/loader.py engine/corelata/doctor.py engine/tests/standards/test_loader.py engine/tests/test_doctor.py
git commit -F <scratchpad>/m10-task2-commit.txt
```

---

### Task 3: The pack index re-stats at most once a second (CRL-18, API)

Every `GET /api/packs` and every name check in `_known` stats every file under both pack directories.

**Files:**
- Modify: `api/corelata_api/pack_index.py`, `api/corelata_api/routes/packs.py` (import line 8, `PackName` line 18), `docs/operator-guide.md` (lines 223-226)
- Test: `api/tests/test_pack_index.py` (new), `api/tests/test_packs.py`

**Interfaces:**
- Consumes: `loader.PACK_NAME_MAX_LENGTH` (Task 2), `pack_dirs_signature` (unchanged signature).
- Produces: `PackIndex(packs_dir: Path | None, min_interval_s: float = 1.0, clock: Callable[[], float] = time.monotonic)`; `listing()` and `names()` unchanged. `app.py` keeps calling `PackIndex(cfg.standards.packs_dir)`.

- [ ] **Step 1: Failing tests**

Create `api/tests/test_pack_index.py`:

```python
import os
import time

import yaml

from corelata_api import pack_index
from corelata_api.pack_index import PackIndex


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def _team(packs, version: str) -> None:
    team = packs / "team"
    (team / "rules").mkdir(parents=True, exist_ok=True)
    meta = {"name": "team", "version": version, "extends": "icd203-base"}
    (team / "pack.yaml").write_text(yaml.safe_dump(meta), encoding="utf-8")
    later = time.time() + (10 if version != "1.0" else 0)
    os.utime(team / "pack.yaml", (later, later))


def _counting(monkeypatch, name: str) -> dict[str, int]:
    real = getattr(pack_index, name)
    calls = {"n": 0}

    def counting(packs_dir):
        calls["n"] += 1
        return real(packs_dir)

    monkeypatch.setattr(pack_index, name, counting)
    return calls


def test_the_listing_is_restatted_at_most_once_per_interval(tmp_path, monkeypatch):
    stats = _counting(monkeypatch, "pack_dirs_signature")
    packs = tmp_path / "packs"
    _team(packs, "1.0")
    clock = Clock()
    index = PackIndex(packs, min_interval_s=1.0, clock=clock)
    assert [p.name for p in index.listing()] == ["icd203-base", "team"]
    assert stats["n"] == 1  # the first call stats
    clock.now += 0.5
    assert index.names() == {"icd203-base", "team"}
    index.listing()
    assert stats["n"] == 1  # inside the interval: the last listing, no stat
    _team(packs, "1.1")
    assert {p.name: p.version for p in index.listing()}["team"] == "1.0"  # up to 1 s stale
    clock.now += 0.5  # exactly min_interval_s after the stat
    assert {p.name: p.version for p in index.listing()}["team"] == "1.1"
    assert stats["n"] == 2


def test_an_unchanged_signature_keeps_the_listing_without_reparsing(tmp_path, monkeypatch):
    parses = _counting(monkeypatch, "list_packs")
    clock = Clock()
    index = PackIndex(None, min_interval_s=1.0, clock=clock)
    first = index.listing()
    clock.now += 5
    assert index.listing() is first and parses["n"] == 1
```

In `api/tests/test_packs.py` add `from functools import partial` after `import os`, add `from corelata.standards.loader import PACK_NAME_MAX_LENGTH` after `import yaml`, and replace `test_the_listing_is_read_once_until_a_pack_file_changes` (line 75 to the end of the file) with:

```python
async def test_the_listing_is_read_once_until_a_pack_file_changes(make_api, tmp_path, monkeypatch):
    packs = tmp_path / "packs"
    team = packs / "team"
    (team / "rules").mkdir(parents=True)
    meta = {"name": "team", "version": "1.0", "extends": "icd203-base"}
    (team / "pack.yaml").write_text(yaml.safe_dump(meta), encoding="utf-8")
    real = pack_index.list_packs
    calls = {"n": 0}

    def counting(packs_dir):
        calls["n"] += 1
        return real(packs_dir)

    now = {"t": 100.0}
    monkeypatch.setattr(pack_index, "list_packs", counting)
    monkeypatch.setattr(
        "corelata_api.app.PackIndex", partial(pack_index.PackIndex, clock=lambda: now["t"])
    )
    async with make_api(standards={"packs_dir": str(packs), "default_pack": "team"}) as api:
        for _ in range(3):
            listed = (await api.client.get("/api/packs")).json()
            assert [p["name"] for p in listed] == ["icd203-base", "team"]
        assert (await api.client.get("/api/packs/team/validate")).status_code == 200
        assert (await api.client.get("/api/packs/nope/validate")).status_code == 404
        assert calls["n"] == 1  # three listings and two name checks: one read
        edited = yaml.safe_dump({**meta, "version": "1.1"})
        (team / "pack.yaml").write_text(edited, encoding="utf-8")
        later = time.time() + 10
        os.utime(team / "pack.yaml", (later, later))
        now["t"] += 1.0  # the next request may re-stat (R-M10-2)
        listed = {p["name"]: p for p in (await api.client.get("/api/packs")).json()}
        assert listed["team"]["version"] == "1.1" and calls["n"] == 2


async def test_pack_names_follow_the_shared_length_limit(api):
    longest = "a" * PACK_NAME_MAX_LENGTH
    assert (await api.client.get(f"/api/packs/{longest}/validate")).status_code == 404
    assert (await api.client.get(f"/api/packs/{longest}a/validate")).status_code == 422
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd api && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/test_pack_index.py tests/test_packs.py --no-cov -q`
Expected: `test_pack_index.py` FAILS with `TypeError: PackIndex.__init__() got an unexpected keyword argument 'min_interval_s'`; `test_the_listing_is_read_once_until_a_pack_file_changes` FAILS with `TypeError: ... unexpected keyword argument 'clock'` at lifespan start; `test_pack_names_follow_the_shared_length_limit` passes already (the limit was 100; it now pins the constant).

- [ ] **Step 3: The index, the route and the guide**

Replace `api/corelata_api/pack_index.py`:

```python
"""The pack listing `GET /api/packs` serves and the name check the other pack routes make,
re-read only when a file under the pack directories changed (CRL-8, R-M9-4), and that is checked
at most once per `min_interval_s` (CRL-18, R-M10-2): an edit can take up to a second to show.
Resolving and validating still parse on each call: a customer edits packs in place."""

import time
from collections.abc import Callable
from pathlib import Path

from corelata.standards.loader import PackSummary, list_packs, pack_dirs_signature


class PackIndex:
    def __init__(
        self,
        packs_dir: Path | None,
        min_interval_s: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._packs_dir = packs_dir
        self._min_interval_s = min_interval_s
        self._clock = clock
        self._stat_at: float | None = None
        self._signature: tuple[tuple[str, int, int], ...] | None = None
        self._listing: list[PackSummary] = []

    def listing(self) -> list[PackSummary]:
        now = self._clock()
        if self._stat_at is not None and now - self._stat_at < self._min_interval_s:
            return self._listing
        self._stat_at = now
        signature = pack_dirs_signature(self._packs_dir)
        if signature != self._signature:
            self._listing = list_packs(self._packs_dir)
            self._signature = signature
        return self._listing

    def names(self) -> set[str]:
        return {p.name for p in self.listing()}
```

`api/corelata_api/routes/packs.py`: replace the loader import (line 8) and `PackName` (line 18):

```python
from corelata.standards.loader import (
    PACK_NAME_MAX_LENGTH,
    PACK_NAME_PATTERN,
    PackSummary,
    load_pack,
    validate_pack,
)
```

```python
PackName = Annotated[
    str, Path(pattern=PACK_NAME_PATTERN.pattern, max_length=PACK_NAME_MAX_LENGTH)
]
```

Both values are what the route had (`^[a-z0-9][a-z0-9\-]*$`, 100), so `schema/openapi.json` does not change; `test_committed_openapi_matches_the_app` proves it.

`docs/operator-guide.md`, replace lines 223-226 (from "A pack edit needs no restart." to "first:") with:

```markdown
A pack edit needs no restart. The API re-reads the pack list when a file under `config/packs/`
changes and checks for changes at most once a second, so an edit shows on the New run screen
within a second; the resolved pack is read from disk on each request. A run loads and snapshots
its pack when it is started, so an edit applies to the next run; runs already started keep the
pack they began with. A pack directory may be a symbolic link to a directory elsewhere, and edits
inside it are seen the same way; the link's target must be inside what is mounted into the
containers (a link to a host path outside `config/` is broken inside them). Every file under the
pack directories is checked, through links too, so keep only pack files there. Check your edits
first:
```

- [ ] **Step 4: Run the API suite and lint**

Run: `make test-api` and `cd api && uv run ruff check . && uv run ruff format --check .`
Expected: all pass, including `test_customer_packs_with_draft_profiles` (each `make_api` builds its own `PackIndex` with the real clock; its first call stats).

- [ ] **Step 5: Commit**

```bash
cat > <scratchpad>/m10-task3-commit.txt <<'EOF'
feat(api): pack index re-stats at most once a second (CRL-18)

PackIndex takes min_interval_s and an injectable clock and serves its last
listing between checks. The route's PackName uses the loader's pattern and
length constants. The operator guide says an edit shows within a second and
that symlinked packs are followed.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git add api/corelata_api/pack_index.py api/corelata_api/routes/packs.py api/tests/test_pack_index.py api/tests/test_packs.py docs/operator-guide.md
git commit -F <scratchpad>/m10-task3-commit.txt
```

---

### Task 4: The claim-id render cache gets a byte budget (CRL-19)

`RenderCache` holds up to 64 entries whatever their size; a DOCX render with embedded images can be megabytes. The lifespan builds it as `RenderCache()` (`app.py` line 87).

**Files:**
- Modify: `engine/corelata/config.py` (`ApiConfig`, line 132-135), `engine/corelata.example.yaml` (line 47), `deploy/config/corelata.example.yaml` (line 41), `api/corelata_api/render_cache.py`, `api/corelata_api/context.py` (the `renders` comment), `api/corelata_api/app.py` (line 87), `docs/operator-guide.md` (section 5, "Uploads and the API", lines 282-288)
- Test: `engine/tests/test_config.py`, `api/tests/test_render_cache.py`, `api/tests/test_reports.py`

**Interfaces:**
- Produces: `ApiConfig.render_cache_mb: int` (default 64, `ge=0`); `RenderCache(capacity: int = 64, max_bytes: int = 64 * 1024 * 1024)` with `max_bytes` and `total_bytes` properties; `get`, `put`, `__len__` unchanged in signature.

- [ ] **Step 1: Failing tests**

`engine/tests/test_config.py`, after `test_job_retention_days_defaults_to_30_and_must_be_positive` (line 52):

```python
def test_render_cache_mb_defaults_to_64_and_may_be_zero():
    from corelata.config import ApiConfig

    assert ApiConfig().render_cache_mb == 64
    assert ApiConfig(render_cache_mb=0).render_cache_mb == 0  # 0 turns the cache off
    with pytest.raises(ValidationError):
        ApiConfig(render_cache_mb=-1)
```

Append to `api/tests/test_render_cache.py`:

```python
def test_a_byte_budget_evicts_the_least_recently_used_until_the_new_entry_fits():
    cache = RenderCache(capacity=10, max_bytes=10)
    cache.put("r1", "html", b"1111")
    cache.put("r2", "html", b"2222")
    assert cache.get("r1", "html") == b"1111"  # r2 is now the oldest
    cache.put("r3", "html", b"333333")  # 8 + 6 > 10: r2 goes, then 4 + 6 fits
    assert cache.get("r2", "html") is None
    assert len(cache) == 2 and cache.total_bytes == 10
    cache.put("r4", "html", b"4")  # 10 + 1 > 10: r1, the oldest now, goes
    assert cache.get("r1", "html") is None and cache.total_bytes == 7


def test_an_entry_larger_than_the_budget_is_not_stored_and_evicts_nothing():
    cache = RenderCache(capacity=10, max_bytes=4)
    cache.put("r1", "html", b"1111")
    cache.put("r2", "html", b"22222")
    assert cache.get("r2", "html") is None
    assert cache.get("r1", "html") == b"1111" and cache.total_bytes == 4


def test_replacing_an_entry_frees_its_old_bytes():
    cache = RenderCache(capacity=10, max_bytes=8)
    cache.put("r1", "html", b"11111111")
    cache.put("r1", "html", b"11")
    assert len(cache) == 1 and cache.total_bytes == 2
    cache.put("r1", "html", b"x" * 9)  # too large now: the old value is dropped, not kept
    assert len(cache) == 0 and cache.total_bytes == 0


def test_a_zero_budget_stores_nothing():
    cache = RenderCache(max_bytes=0)
    cache.put("r1", "html", b"")
    cache.put("r2", "html", b"x")
    assert len(cache) == 0 and cache.max_bytes == 0


def test_the_budget_defaults_to_64_mib_and_must_not_be_negative():
    assert RenderCache().max_bytes == 64 * 1024 * 1024
    with pytest.raises(ValueError, match="must not be negative"):
        RenderCache(max_bytes=-1)
```

`api/tests/test_reports.py`: add `import asyncio` before `import hashlib`, and append:

```python
async def test_a_claim_id_miss_reads_the_run_twice_and_a_hit_once(api, monkeypatch):
    run = await _completed(api)
    reads: list[str] = []
    real_progress, real_record = reports.service.run_progress, reports.service.get_run_record

    async def progress(db, run_id):
        reads.append("progress")
        return await real_progress(db, run_id)

    async def record(db, run_id):
        reads.append("record")
        return await real_record(db, run_id)

    monkeypatch.setattr(reports.service, "run_progress", progress)
    monkeypatch.setattr(reports.service, "get_run_record", record)
    url = f"/api/runs/{run['run_id']}/report"
    params = {"format": "html", "with_claim_ids": "1"}
    assert (await api.client.get(url, params=params)).status_code == 200
    assert reads == ["progress", "record"]  # the state check, then the record for the render
    reads.clear()
    assert (await api.client.get(url, params=params)).status_code == 200
    assert reads == ["progress"]  # a hit: the state check only


async def test_a_failed_claim_id_render_is_not_cached_and_a_docx_one_is(api, monkeypatch):
    run = await _completed(api)
    real = reports._render
    calls: list[str] = []

    def flaky(record, fmt, **kw):
        calls.append(fmt)
        if len(calls) == 1:
            raise ValueError("renderer crashed")
        return real(record, fmt, **kw)

    monkeypatch.setattr(reports, "_render", flaky)
    renders = api.app.state.ctx.renders
    url = f"/api/runs/{run['run_id']}/report"
    failed = await api.client.get(url, params={"format": "html", "with_claim_ids": "1"})
    assert failed.status_code == 500 and len(renders) == 0
    retried = await api.client.get(url, params={"format": "html", "with_claim_ids": "1"})
    assert retried.status_code == 200 and renders.get(run["run_id"], "html") == retried.content
    for _ in range(2):
        docx = await api.client.get(url, params={"format": "docx", "with_claim_ids": "1"})
        assert docx.status_code == 200 and docx.content[:2] == b"PK"
    assert calls == ["html", "html", "docx"]  # the DOCX was rendered once, then served cached
    assert renders.get(run["run_id"], "docx") == docx.content


async def test_concurrent_claim_id_renders_for_65_runs_keep_64_entries(api, monkeypatch):
    run = await _completed(api)
    completed = await service.run_progress(api.db, uuid.UUID(run["run_id"]))
    record = await service.get_run_record(api.db, uuid.UUID(run["run_id"]))

    async def any_progress(db, run_id):
        await asyncio.sleep(0)  # let the other requests interleave
        return completed

    async def any_record(db, run_id):
        await asyncio.sleep(0)
        return record

    monkeypatch.setattr(reports.service, "run_progress", any_progress)
    monkeypatch.setattr(reports.service, "get_run_record", any_record)
    ids = [str(uuid.uuid4()) for _ in range(65)]
    params = {"format": "html", "with_claim_ids": "1"}
    responses = await asyncio.gather(
        *(api.client.get(f"/api/runs/{i}/report", params=params) for i in ids)
    )
    assert {r.status_code for r in responses} == {200}
    assert len({r.content for r in responses}) == 1
    renders = api.app.state.ctx.renders
    assert len(renders) == 64
    assert renders.total_bytes == 64 * len(responses[0].content)
    assert sum(renders.get(i, "html") is None for i in ids) == 1  # exactly one was evicted


async def test_the_render_budget_comes_from_the_config(make_api):
    async with make_api() as api:
        assert api.app.state.ctx.renders.max_bytes == 64 * 1024 * 1024
    async with make_api(api={"progress_poll_s": 0.02, "render_cache_mb": 0}) as api:
        run = await _completed(api)
        url = f"/api/runs/{run['run_id']}/report"
        served = await api.client.get(url, params={"format": "html", "with_claim_ids": "1"})
        assert served.status_code == 200 and "data-claim-ids" in served.text
        assert len(api.app.state.ctx.renders) == 0  # served, never stored
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/test_config.py --no-cov -q -k render_cache` and `cd api && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/test_render_cache.py tests/test_reports.py --no-cov -q`
Expected: the config test FAILS (`AttributeError: 'ApiConfig' object has no attribute 'render_cache_mb'`); the five new cache tests FAIL (`TypeError: ... unexpected keyword argument 'max_bytes'`, `AttributeError: ... 'total_bytes'`); in `test_reports.py` the concurrency test FAILS on `total_bytes` and the config test on `max_bytes` / the unknown `render_cache_mb` key (strict config: `extra=forbid`); the miss/hit and failed/docx tests pass already (they pin M9 behaviour the ticket asked to test).

- [ ] **Step 3: Config, cache and wiring**

`engine/corelata/config.py`, `ApiConfig` (lines 132-135):

```python
class ApiConfig(_Strict):
    max_upload_mb: int = Field(200, ge=1)
    progress_poll_s: float = Field(1.0, gt=0, le=60)
    # memory for claim-id re-renders (the review screen's report); 0 stores none (CRL-19)
    render_cache_mb: int = Field(64, ge=0)
    web_dir: Path | None = None
```

`engine/corelata.example.yaml` line 47:

```yaml
api: { max_upload_mb: 200, progress_poll_s: 1.0, render_cache_mb: 64 } # upload limit; SSE poll interval; claim-id render memory
```

`deploy/config/corelata.example.yaml` line 41:

```yaml
api: { max_upload_mb: 200, progress_poll_s: 1.0, render_cache_mb: 64 }
```

Replace `api/corelata_api/render_cache.py`:

```python
"""A small LRU for the re-rendered reports `GET /runs/{id}/report?with_claim_ids=1` serves. A
completed run's record never changes, so a render keyed on (run, format) stays valid for the life
of the process (CRL-9, R-M9-5). It is bounded twice: by entry count and by the bytes it holds
(`api.render_cache_mb`, CRL-19, R-M10-5); a render larger than the whole budget is served but
never stored, so one huge report cannot empty the cache."""

from collections import OrderedDict


class RenderCache:
    def __init__(self, capacity: int = 64, max_bytes: int = 64 * 1024 * 1024) -> None:
        if capacity < 1:
            raise ValueError("capacity must be at least 1")
        if max_bytes < 0:
            raise ValueError("max_bytes must not be negative")
        self._capacity = capacity
        self._max_bytes = max_bytes
        self._items: OrderedDict[tuple[str, str], bytes] = OrderedDict()
        self._bytes = 0

    @property
    def max_bytes(self) -> int:
        return self._max_bytes

    @property
    def total_bytes(self) -> int:
        return self._bytes

    def get(self, run_id: str, fmt: str) -> bytes | None:
        key = (run_id, fmt)
        value = self._items.get(key)
        if value is not None:
            self._items.move_to_end(key)
        return value

    def put(self, run_id: str, fmt: str, content: bytes) -> None:
        key = (run_id, fmt)
        old = self._items.pop(key, None)
        if old is not None:
            self._bytes -= len(old)
        if self._max_bytes == 0 or len(content) > self._max_bytes:
            return
        while self._items and (
            len(self._items) >= self._capacity or self._bytes + len(content) > self._max_bytes
        ):
            _, evicted = self._items.popitem(last=False)
            self._bytes -= len(evicted)
        self._items[key] = content
        self._bytes += len(content)

    def __len__(self) -> int:
        return len(self._items)
```

`api/corelata_api/context.py`: the `renders` line becomes

```python
    renders: RenderCache  # claim-id re-renders per (run, format), within api.render_cache_mb
```

`api/corelata_api/app.py` line 87: `renders=RenderCache(),` becomes

```python
                    renders=RenderCache(max_bytes=cfg.api.render_cache_mb * 1024 * 1024),
```

`docs/operator-guide.md` section 5, "Uploads and the API": the code line `api: { max_upload_mb: 200, progress_poll_s: 1.0 }` (line 282) becomes `api: { max_upload_mb: 200, progress_poll_s: 1.0, render_cache_mb: 64 }`, and after the sentence ending "(once per run, however many analysts watch it)." (line 288) insert:

```markdown
`render_cache_mb` (default 64) is how much memory the API keeps for reports re-rendered with
claim ids, which the review screen shows; the oldest are dropped first, a report larger than the
whole budget is rendered on every request instead, and 0 turns the cache off.
```

- [ ] **Step 4: Run both suites and lint**

Run: `make test-engine`, `make test-api`, `make lint`
Expected: all pass. `test_example_config_loads` still passes (the example now names `render_cache_mb`). The four M9 cache tests pass unchanged (`capacity=2` with the default budget behaves as before).

- [ ] **Step 5: Commit**

```bash
cat > <scratchpad>/m10-task4-commit.txt <<'EOF'
feat(api): byte budget for the claim-id render cache (CRL-19)

RenderCache evicts least-recently-used entries until a new render fits both
the entry count and api.render_cache_mb (default 64, 0 turns it off); a
render larger than the budget is served but not stored. Tests pin eviction
under 65 concurrent runs, that failures are not cached and DOCX renders are,
and how many run reads a miss and a hit cost.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git add engine/corelata/config.py engine/corelata.example.yaml deploy/config/corelata.example.yaml engine/tests/test_config.py api/corelata_api/render_cache.py api/corelata_api/context.py api/corelata_api/app.py api/tests/test_render_cache.py api/tests/test_reports.py docs/operator-guide.md
git commit -F <scratchpad>/m10-task4-commit.txt
```

---

### Task 5: Pin the progress feed's sharing and cancellation (CRL-20, API)

No production code changes: both tests pin M9 behaviour. The feed's fetch is `lambda run_id: service.run_progress(db, run_id)` (`app.py` lines 70-72), which looks `service.run_progress` up at call time, so monkeypatching `progress_module.service.run_progress` counts both the route's first read and every poller read. A poller read runs in the task `ProgressFeed.subscribe` created for `ProgressFeed._run`; a route read runs in the request's task.

**Files:**
- Test: `api/tests/test_progress_feed.py`, `api/tests/test_progress.py` (lines 94-102)

**Interfaces:**
- Consumes: `corelata_api.routes.progress._stream(ctx, run_id, first)` (reads only `ctx.progress`).

- [ ] **Step 1: The tests**

`api/tests/test_progress_feed.py`: add `from types import SimpleNamespace` after `from datetime import UTC, datetime`, `import pytest` before `from corelata.schema import RunProgress`, and `from corelata_api.routes.progress import _stream` after the `corelata_api.progress_feed` import. Append:

```python
async def test_a_stream_cancelled_mid_wait_unsubscribes_and_stops_the_poller():
    fetch, calls = scripted(*(["gating"] * 1000))  # never a change: the stream sits in wait_for
    feed = ProgressFeed(fetch, poll_s=0.01)
    stream = _stream(SimpleNamespace(progress=feed), RUN, progress("gating"))
    chunks: list[str] = []

    async def read() -> None:
        async for chunk in stream:
            chunks.append(chunk)

    reader = asyncio.create_task(read())
    await asyncio.sleep(0.05)
    assert feed.active == 1 and calls["n"] >= 2
    assert len(chunks) == 2 and chunks[0] == "retry: 3000\n\n"  # retry, then the first event
    reader.cancel()  # the browser tab closed
    with pytest.raises(asyncio.CancelledError):
        await reader
    assert feed.active == 0  # the stream's finally unsubscribed the last listener
    n = calls["n"]
    await asyncio.sleep(0.05)
    assert calls["n"] == n  # and its poller is gone
```

`api/tests/test_progress.py`: replace `test_two_streams_on_one_run_end_together_and_leave_no_poller` (lines 94-102) with:

```python
async def test_two_streams_on_one_run_share_one_poller_and_leave_none(api, monkeypatch):
    run = await start_run(api)
    real = progress_module.service.run_progress
    readers: list[asyncio.Task] = []

    async def counting(db, run_id):
        readers.append(asyncio.current_task())
        return await real(db, run_id)

    monkeypatch.setattr(progress_module.service, "run_progress", counting)
    finisher = asyncio.create_task(_finish_later(api.db, run["run_id"]))
    url = f"/api/runs/{run['run_id']}/events"
    first, second = await asyncio.gather(api.client.get(url), api.client.get(url))
    await finisher
    for response in (first, second):
        assert [d["state"] for _, d in _events(response.text)] == ["created", "gating", "completed"]
    polled = [t for t in readers if t.get_coro().__qualname__ == "ProgressFeed._run"]
    assert len(set(polled)) == 1  # every poll during the overlap came from one poller
    assert len(readers) - len(polled) == 2  # plus each stream's own first read
    assert api.app.state.ctx.progress.active == 0
```

- [ ] **Step 2: Run them, then check that they bite**

Run: `cd api && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/test_progress_feed.py tests/test_progress.py --no-cov -q`
Expected: all pass.

Then, without committing: comment out `ctx.progress.unsubscribe(run_id, queue)` in `api/corelata_api/routes/progress.py` (the `finally` of `_stream`) and rerun `-k cancelled_mid_wait`: it must FAIL on `assert feed.active == 0`. Restore the line (`git diff api/corelata_api/routes/progress.py` shows nothing). Then in `api/corelata_api/progress_feed.py` `subscribe`, temporarily change `poller = self._pollers.get(run_id)` to `poller = None` and rerun `-k share_one_poller`: it must FAIL on `len(set(polled)) == 1`. Restore it (`git diff api/corelata_api/progress_feed.py` shows nothing).

- [ ] **Step 3: Run the API suite and lint**

Run: `make test-api` and `cd api && uv run ruff check . && uv run ruff format --check .`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
cat > <scratchpad>/m10-task5-commit.txt <<'EOF'
test(api): pin the shared poller and the cancelled stream (CRL-20)

A stream cancelled while it waits for an update unsubscribes in its finally
and the last unsubscribe stops the poller; two streams on one run are fed by
one poller task, counted at the run_progress call.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git add api/tests/test_progress_feed.py api/tests/test_progress.py
git commit -F <scratchpad>/m10-task5-commit.txt
```

---

### Task 6: Web test debt and the head regex (CRL-20, web)

`withBridge` today matches only a bare `<head>` (`/<head\s*>/i`, `frameBridge.ts` line 73); for `<head lang="bg">` it finds nothing and puts the policy at offset 0, before `<!DOCTYPE html>`. `RunList.test.tsx`'s "keeps Show more in place" test also holds its loading state with a real 80 ms delay; R-M10-7 covers it, so it moves to the deferred response too.

**Files:**
- Create: `web/src/test/deferred.ts`
- Modify: `web/src/pages/review/frameBridge.ts` (`withBridge`, lines 69-79)
- Test: `web/src/pages/review/ReviewActions.test.tsx`, `web/src/pages/new/RunList.test.tsx`, `web/src/pages/review/AuditTab.test.tsx`, `web/src/pages/review/frameBridge.test.ts`

**Interfaces:**
- Produces: `deferred(): { promise: Promise<void>; resolve: () => void }`.

- [ ] **Step 1: The helper**

Create `web/src/test/deferred.ts`:

```ts
/** A promise the test settles itself. An msw handler awaits `promise`; the test checks the
 * loading state, then calls `resolve()` (R-M10-7: no real delays, no fake timers). */
export function deferred(): { promise: Promise<void>; resolve: () => void } {
  let resolve!: () => void;
  const promise = new Promise<void>((settle) => {
    resolve = settle;
  });
  return { promise, resolve };
}
```

- [ ] **Step 2: Tests**

`web/src/pages/review/ReviewActions.test.tsx`, append:

```tsx
it("keeps the note through a failed return and clears it after one that succeeds", async () => {
  serveCompleted();
  const posted: unknown[] = [];
  server.use(
    http.post(`*/api/runs/${RUN_ID}/review`, async ({ request }) => {
      posted.push(await request.json());
      if (posted.length === 1) {
        return HttpResponse.json({ detail: "the database is unavailable" }, { status: 503 });
      }
      // No child in the reply: the page stays, so the dialog can be opened again.
      return HttpResponse.json({ action: "return", child: null });
    }),
  );
  const { router, user } = renderApp(`/runs/${RUN_ID}/review`);
  await user.click(await screen.findByRole("button", { name: "Return with note" }));
  const note = screen.getByRole("textbox", { name: "Note for the writer" });
  await user.type(note, "Add the 2027 date");
  await user.click(screen.getByRole("button", { name: "Return" }));
  expect(await within(screen.getByRole("dialog")).findByRole("alert")).toHaveTextContent(
    "the database is unavailable",
  );
  expect(note).toHaveValue("Add the 2027 date");
  await user.click(screen.getByRole("button", { name: "Return" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(posted).toEqual([
    { action: "return", note: "Add the 2027 date" },
    { action: "return", note: "Add the 2027 date" },
  ]);
  expect(router.state.location.pathname).toBe(`/runs/${RUN_ID}/review`);
  await user.click(screen.getByRole("button", { name: "Return with note" }));
  expect(screen.getByRole("textbox", { name: "Note for the writer" })).toHaveValue("");
});
```

`web/src/pages/new/RunList.test.tsx`: add `import { RUN_LIMIT_MAX, RUN_PAGE } from "../../api/projects";` and `import { deferred } from "../../test/deferred";` to the imports. Replace the test `"keeps Show more in place, disabled, while the next page loads"` with:

```tsx
it("keeps Show more in place, disabled, while the next page loads", async () => {
  const nextPage = deferred();
  server.use(
    http.get("*/api/projects", () => HttpResponse.json([project])),
    http.get(`*/api/projects/${project.id}/sources`, () => HttpResponse.json([])),
    http.get("*/api/runs", async ({ request }) => {
      const limit = Number(new URL(request.url).searchParams.get("limit"));
      if (limit > RUN_PAGE) await nextPage.promise;
      return HttpResponse.json(many(limit));
    }),
  );
  const { user } = renderApp(`/new?project=${project.id}`);
  const table = await screen.findByRole("table", { name: "Runs" });
  await user.click(screen.getByRole("button", { name: "Show more" }));
  expect(screen.getByRole("button", { name: "Show more" })).toBeDisabled();
  nextPage.resolve();
  await waitFor(() => expect(within(table).getAllByRole("row")).toHaveLength(101));
  await waitFor(() => expect(screen.getByRole("button", { name: "Show more" })).toBeEnabled());
});
```

and append:

```tsx
it("stops at the API's ceiling of 500 runs and says so", async () => {
  serveRuns([]);
  server.use(
    http.get("*/api/runs", ({ request }) =>
      HttpResponse.json(many(Number(new URL(request.url).searchParams.get("limit")))),
    ),
  );
  const { user } = renderApp(`/new?project=${project.id}`);
  const table = await screen.findByRole("table", { name: "Runs" });
  const rows = () => table.querySelectorAll("tbody tr").length; // 500 rows: skip role queries
  for (let shown = RUN_PAGE; shown < RUN_LIMIT_MAX; shown += RUN_PAGE) {
    await waitFor(() => expect(screen.getByRole("button", { name: "Show more" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "Show more" }));
    await waitFor(() => expect(rows()).toBe(shown + RUN_PAGE));
  }
  expect(screen.queryByRole("button", { name: "Show more" })).not.toBeInTheDocument();
  expect(screen.getByText(`Showing the newest ${RUN_LIMIT_MAX} runs.`)).toBeInTheDocument();
});

it("starts each project's run list at the first page again", async () => {
  const other = { ...project, id: "99999999-9999-9999-9999-999999999999", name: "Danube" };
  const asked: string[] = [];
  server.use(
    http.get("*/api/projects", () => HttpResponse.json([project, other])),
    http.get("*/api/projects/:id/sources", () => HttpResponse.json([])),
    http.get("*/api/runs", ({ request }) => {
      const params = new URL(request.url).searchParams;
      asked.push(`${params.get("project_id")}:${params.get("limit")}`);
      return HttpResponse.json(many(Number(params.get("limit"))));
    }),
  );
  const { user } = renderApp(`/new?project=${project.id}`);
  await screen.findByRole("table", { name: "Runs" });
  await user.click(screen.getByRole("button", { name: "Show more" }));
  await waitFor(() => expect(asked).toContain(`${project.id}:100`));
  await user.selectOptions(screen.getByRole("combobox", { name: "Project" }), other.id);
  await waitFor(() => expect(asked).toContain(`${other.id}:${RUN_PAGE}`));
  expect(asked).not.toContain(`${other.id}:100`); // the page size did not carry over
});
```

(`serveRuns([])` registers the projects and sources handlers; the later `server.use` takes precedence for `/api/runs`.)

`web/src/pages/review/AuditTab.test.tsx`: add `import { deferred } from "../../test/deferred";` and replace the handler and the waits of `"shows a loading state for the rule titles instead of reflowing the table"` (lines 103-119) with:

```tsx
it("shows a loading state for the rule titles instead of reflowing the table", async () => {
  const pack = deferred();
  server.use(
    http.get(`*/api/runs/${RUN_ID}/findings`, () => HttpResponse.json(findings)),
    http.get(`*/api/runs/${RUN_ID}/trace`, () => HttpResponse.json(runTrace)),
    http.get("*/api/packs/icd203-base/resolved", async () => {
      await pack.promise;
      return HttpResponse.json(resolvedPack);
    }),
  );
  renderWithClient(<AuditTab runId={RUN_ID} />);
  expect(await screen.findByText(/Loading rule titles/)).toBeInTheDocument();
  expect(screen.queryByRole("table", { name: "Rules" })).not.toBeInTheDocument();
  pack.resolve();
  expect(await screen.findByRole("table", { name: "Verifiable rules" })).toBeInTheDocument();
  expect(
    within(screen.getByRole("table", { name: "Verifiable rules" })).getByText("Sourcing is clear"),
  ).toHaveAttribute("dir", "auto");
});
```

`web/src/pages/review/frameBridge.test.ts`, append:

```ts
it("puts the policy inside a head that has attributes, after the doctype", () => {
  const doc =
    '<!DOCTYPE html><html lang="bg"><head lang="bg"><title>t</title></head>' +
    "<body><p>x</p></body></html>";
  const out = withBridge(doc, "n");
  expect(out).toBe(
    `<!DOCTYPE html><html lang="bg"><head lang="bg">${cspMeta("n")}<title>t</title></head>` +
      `<body><p>x</p>${bridgeScript("n")}</body></html>`,
  );
  const parsed = new DOMParser().parseFromString(out, "text/html");
  expect(parsed.head.querySelector('meta[http-equiv="Content-Security-Policy"]')).not.toBeNull();
  expect(parsed.doctype?.name).toBe("html");
});

it("puts the policy right after the doctype when there is no head, and <header> is not one", () => {
  expect(withBridge("<!doctype html><header>h</header><p>x</p>", "n")).toBe(
    `<!doctype html>${cspMeta("n")}<header>h</header><p>x</p>${bridgeScript("n")}`,
  );
});
```

- [ ] **Step 3: Run them to see which fail**

Run: `cd web && pnpm vitest run src/pages/review/frameBridge.test.ts src/pages/review/ReviewActions.test.tsx src/pages/new/RunList.test.tsx src/pages/review/AuditTab.test.tsx`
Expected: the two new `frameBridge` tests FAIL (the meta lands before `<!DOCTYPE html>`, and before `<!doctype html>` in the second); every other test passes (they pin M9 behaviour).

- [ ] **Step 4: The regex**

`web/src/pages/review/frameBridge.ts`, replace `withBridge`'s doc comment and its first three body lines (lines 69-74, through `const cut = ...`) with:

```ts
/** The report with its policy at the top of `<head>`, whatever the tag's attributes (R-M10-8);
 * right after the doctype when there is no head (so the document stays in standards mode); else
 * at the very start. The bridge is appended inside `<body>` (or at the end). */
export function withBridge(html: string, nonce: string = frameNonce()): string {
  const meta = cspMeta(nonce);
  const anchor = /<head\b[^>]*>/i.exec(html) ?? /^\s*<!doctype\b[^>]*>/i.exec(html);
  const cut = anchor ? anchor.index + anchor[0].length : 0;
```

The rest of the function is unchanged. `\b` keeps `<header>` from matching.

- [ ] **Step 5: Run the web suite and lint**

Run: `make test-web` and `cd web && pnpm lint`
Expected: clean and green; coverage ≥ 95% on all four measures (`src/test/**` is excluded from coverage). If prettier reformats a test, run `pnpm fmt` and recheck.

- [ ] **Step 6: Commit**

```bash
cat > <scratchpad>/m10-task6-commit.txt <<'EOF'
fix(web): frame policy inside a head with attributes; pay the M9 test debt (CRL-20)

withBridge matches <head ...> and, with no head, places the policy after the
doctype. Tests: the review note is kept through a failed return and cleared
after a successful one; the run list stops at 500 and resets per project;
loading states are held by deferred msw responses instead of real delays.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git add web/src/test/deferred.ts web/src/pages/review/frameBridge.ts web/src/pages/review/frameBridge.test.ts web/src/pages/review/ReviewActions.test.tsx web/src/pages/new/RunList.test.tsx web/src/pages/review/AuditTab.test.tsx
git commit -F <scratchpad>/m10-task6-commit.txt
```

---

### Task 7: Docs

The spec's §10.1 lists routes, not the data model; `run`'s columns are listed in §8.3, so the `review_state` amendment goes there, with a one-line M10 amendment in §10.1 for the route-visible changes and the §11 sample config line. The operator guide has no configuration table: `api.render_cache_mb` was documented in section 5's prose and sample line in Task 4.

**Files:**
- Modify: `README.md` (new `## M10` section before `## Development`, line 190), `docs/superpowers/specs/2026-10-12-corelata-v1-design.md` (§8.3 after line 333, §10.1 after the M9 amendments paragraph ending line 382, §11 line 441), `docs/m9-followups.md` (rewritten with a "Closed in M10" section)
- Create: `docs/m10-followups.md`

- [ ] **Step 1: README**

Insert before `## Development` (line 190):

```markdown
## M10: stored review state and bounded caches

Four follow-ups from M9 (CRL-17 to 20): the review decision is stored on the run row (migration
0004 backfills it from the review events), so a progress read on a completed run no longer queries
`review_event`; the pack listing checks the pack files at most once a second and follows
symlinked pack directories (a link cycle ends the walk), and `corelata doctor` checks pack names
against the API's own pattern and 100-character limit; the claim-id render cache is bounded by
`api.render_cache_mb` (default 64) as well as by its 64 entries; the report frame's policy lands
inside a `<head>` with attributes; and the M9 test debt is paid (a cancelled stream, the shared
poller, the review note, the run-list ceiling, loading states without real delays).

```

- [ ] **Step 2: Spec amendments**

§8.3, after line 333 ("…`finished_at`. A discovery's few model calls are a JSON column on `discovery`."):

```markdown

M10 amendment: `run.review_state` holds the review decision (`ReviewState` JSON: `decision`,
`at`, `actor`, `child_run_id`), written by every review action in the event's transaction;
`review_event` stays the audit trail, and migration 0004 backfilled the column from it.
```

§10.1, after the M9 amendments paragraph (ends line 382 "…`/packs/{name}/...` still read on every call."):

```markdown

M10 amendments: `GET /runs/{id}` reads `review` from `run.review_state` (§8.3), not from the
review events. `GET /packs` checks the pack files at most once a second and follows symlinked
pack directories. The claim-id re-render cache is bounded by `api.render_cache_mb` (default 64)
as well as by its 64 entries.
```

§11, line 441: `api: {max_upload_mb: 200, progress_poll_s: 1.0, web_dir: /app/web}` becomes `api: {max_upload_mb: 200, progress_poll_s: 1.0, render_cache_mb: 64, web_dir: /app/web}`.

- [ ] **Step 3: `docs/m9-followups.md`**

Replace the file with:

```markdown
# M9 follow-ups

## Divergences from Coglossa

- `ProgressFeed` (one poller per run for the SSE streams), `RenderCache` and `PackIndex` on the
  API context — **backport** (CGL-18): Coglossa's events route polls per stream the same way.
- `runs.get_run_brief` (deferred JSON columns for progress reads) — **backport**.

## Spec deviations

- §10.1: none; `review` on `GET /runs/{id}` and the caches are recorded as M9 amendments.

## Rulings during execution

- **R-M9-11**: `ProgressFeed` publishes to a stream only the result of a read that started after
  the stream joined, and only when it differs from what that stream last showed. The route reads
  the run fresh right before subscribing, so nothing stale is pushed and nothing is missed.

## Should fix soon

- `ProgressFeed` polls; LISTEN/NOTIFY from the worker would make the stream event-driven and
  remove `api.progress_poll_s`.
- The frame's `style-src 'unsafe-inline'` could become a hash of the template's `<style>` plus a
  nonce on the bridge's style element.
- The operator guide's sample proxy policy is a starting point, not a tested configuration; an
  e2e run behind a proxy that sets it would pin it.
- `ReviewActions` still allows a return after an accept (the server allows it); decide whether an
  accepted report should be returnable.

## Later

- Offset or cursor paging for `GET /api/runs` once a project passes 500 runs.
- Discovery polling never gives up on a stuck discovery; the worker's stalled-job sweep is what
  ends it. A client-side ceiling (stop after 10 minutes with a message) is a UX question.
- Discovery backoff (R-M9-9, 15 s cap) adds up to 15 s before a finished discovery is shown; a 5 s
  cap would bound load nearly as well (R-M9-12 kept 15 s; a UX question).

## Closed in M10

- `RunProgress.review` is read from the review events on every progress call for a completed
  run (one indexed query); a `review_state` column on `run`, written by `review_run`, would make
  it free. — **closed in M10** (CRL-17)
- `pack_dirs_signature` stats every file under both pack directories on every `GET /api/packs`
  and every name check; a customer directory with hundreds of files turns that into a measurable
  cost. A debounce (re-stat at most once a second) would bound it. — **closed in M10** (CRL-18)
- Symlinked pack directories are listed by `list_packs` but not walked by `pack_dirs_signature`
  (`rglob` does not descend into symlinked directories), so edits inside such a pack never
  refresh the listing: `os.walk(followlinks=True)`, or document the limitation. — **closed in
  M10** (CRL-18)
- The doctor's fix text hard-codes the pack-name pattern, and the API's `max_length=100` is not
  checked by the doctor. — **closed in M10** (CRL-18)
- `RenderCache` is bounded by entry count (64), not bytes: add a byte budget. — **closed in M10**
  (CRL-19)
- Tests to add: `RenderCache` eviction under concurrent requests for 65 different runs. —
  **closed in M10** (CRL-19)
- Tests to add (T1): a failed claim-id render is not cached, and a DOCX claim-id render is; a
  claim-id cache miss reads the run twice (`run_progress`, then `load_record`). — **closed in
  M10** (CRL-19)
- Tests to add: `ProgressFeed` under a cancelled stream mid-`wait_for` (the `finally`
  unsubscribes; a direct test would pin it). — **closed in M10** (CRL-20)
- Tests to add (T2): the API-level two-stream test does not prove sharing; count `run_progress`
  calls during the overlap. — **closed in M10** (CRL-20)
- Tests to add (T5): `setNote("")` after a return has no assertion, so the m4b "note persists"
  item is closed without a test. — **closed in M10** (CRL-20)
- Tests to add (T6): no test for the 500-run ceiling note or the per-project reset; the AuditTab
  loading test uses a real 80 ms delay. — **closed in M10** (CRL-20)
- Tests to add (T8): `withBridge`'s head regex does not match `<head lang="...">` (the meta then
  goes before `<!DOCTYPE>`; safe in srcdoc, untested). — **closed in M10** (CRL-20)
```

- [ ] **Step 4: `docs/m10-followups.md`**

```markdown
# M10 follow-ups

## Divergences from Coglossa

- `run.review_state` and migration 0004 — Corelata only: Coglossa has no review events.
- `PackIndex`'s one-second debounce, `pack_dirs_signature` following symlinks, and
  `RenderCache`'s byte budget — **backport** together with the M9 caches (CGL-18).

## Spec deviations

- None. §8.3, §10.1 and §11 carry M10 amendments (`run.review_state`, the pack-listing refresh,
  `api.render_cache_mb`).

## Rulings during execution

- None yet; number new ones from R-M10-9.

## Should fix soon

- `pack_dirs_signature` now follows symlinks out of the pack directories: a link to a large tree
  is walked once a second while anyone lists packs. The doctor could warn when the walk passes a
  file count (say 2,000).
- `RenderCache` counts payload bytes only, not the per-entry overhead of the key and the
  `bytes` object (well under 1 KiB per entry); fine at 64 entries, worth knowing if the count
  grows.

## Later

- A field added to `ReviewState` needs its own migration to backfill `run.review_state`; the
  model and 0004's written-out rule must be changed together.
- The run-list ceiling test clicks Show more nine times against a 500-row table; if the Vitest
  run slows down, render `RunList` alone with a lower ceiling passed in.
```

- [ ] **Step 5: Check nothing else moved**

Run: `make lint`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
cat > <scratchpad>/m10-task7-commit.txt <<'EOF'
docs: M10 README section, spec amendments, follow-ups closed and filed

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git add README.md docs/superpowers/specs/2026-10-12-corelata-v1-design.md docs/m9-followups.md docs/m10-followups.md
git commit -F <scratchpad>/m10-task7-commit.txt
```

---

## Final verification (after the whole-branch review)

```bash
make lint
make test-engine
make test-api
make test-web
make e2e            # the Playwright journey clicks inside the real frame: the head change must not break the bridge
make deploy-check   # the bundle's example config gained render_cache_mb
git diff --stat main -- schema web/src/api/schema.d.ts   # must print nothing (R-M10-6)
```

CI must be green on all six jobs (engine, api, web, e2e, deploy-check, airgap) before the merge.
