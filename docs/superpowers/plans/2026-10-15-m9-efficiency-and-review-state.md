# M9 Efficiency and Review State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the four remaining triage tickets (Jira CRL-8, CRL-9, CRL-15, CRL-16): the API stops paying a full-record load and a per-stream database poll for things it can answer cheaply, the review screen shows what the server knows instead of what this tab remembers, the run list pages, polling backs off, the report frame carries its own Content-Security-Policy and the operator guide says what a proxy policy must allow, and `corelata doctor` warns about pack directories the API cannot address.

**Architecture:** Server side, three small per-process caches hang off the API's `ApiContext` (a render LRU, a shared progress poller per run, a pack index keyed on a file signature), `run_progress` reads a lighter run row and carries the review decision for completed runs, and the report route checks state before it loads anything. Web side, the review and progress screens derive their state from `RunProgress`, the run list raises `limit` in pages, discovery polling backs off, and `withBridge` injects a nonce-bound meta CSP. No new routes; one response model gains a field (`RunProgress.review`), so `make schema` runs once (Task 4) and the generated OpenAPI document and TypeScript types are committed with it.

**Tech Stack:** Python 3.12, FastAPI, pydantic 2, SQLAlchemy 2 async (`defer`), asyncio; React 19 + TypeScript, TanStack Query 5, Vitest + msw, Playwright; Markdown docs.

**Spec:** `docs/superpowers/specs/2026-10-12-corelata-v1-design.md` — §10.1 (API: `GET /runs/{id}`, `GET /runs/{id}/events`, `GET /runs/{id}/report`, `GET /packs`, review), §10.3 (web: Progress and Review screens, the sandboxed frame, polling fallback, Audit tab pack lookup), §12 (reverse proxy), §13 (quality gates). The tickets' text is in Jira CRL-8/9/15/16 (filed from the triage in CRL-2); the items they bundle are quoted in `docs/m3-followups.md` (lines 54-55), `docs/m4a-followups.md` (41-48, 58-60), `docs/m4b-followups.md` (58-78) and `docs/m7-followups.md` (32-34).

## Global Constraints

- 95% branch coverage for `engine` and `api` (`--cov-fail-under=95`), `filterwarnings = ["error"]`; `ruff check` and `ruff format --check` clean (line length 100). Vitest 95% on lines, branches, functions and statements; `pnpm lint` (eslint, prettier, `tsc --noEmit`) clean.
- Python tests that touch Postgres run against the dev database (`make db-up`; `CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres`). A single test file: `cd api && CORELATA_TEST_DATABASE_URL=... uv run pytest tests/test_x.py --no-cov`.
- **No new API route.** `api/tests/test_openapi.py::test_every_screen_has_its_routes` lists exactly 22 paths and stays as it is. The one response-model change (`RunProgress.review`, Task 4) is the only reason to run `make schema`; that task commits `schema/openapi.json`, `schema/run-progress.schema.json` and `web/src/api/schema.d.ts` together. `api/tests/test_openapi.py::test_committed_openapi_matches_the_app` and the `web` CI job (`pnpm gen:api && git diff --exit-code src/api/schema.d.ts`) enforce it.
- The trace format and every export are unchanged. `StageResult.output` stays in `RunProgress.stages`.
- `api/tests/test_reports.py::test_re_render_failures` monkeypatches `reports._render`; that name stays.
- Web tests mock every request with msw (`web/src/test/setup.ts` fails an unmocked one); poll intervals are read through `web/src/test/poll.ts`, never fake timers. Fixtures live in `web/src/test/fixtures.ts`.
- Commit messages end with the two attribution lines the session uses; write them to a uniquely named scratchpad file and `git commit -F FILE`. Never `git stash`. Never `git add .` (the SDD workspace is not ignored).
- Rulings (record in the SDD ledger, carried here):
  - **R-M9-1** The review decision rides on `RunProgress.review` (`ReviewState`: decision, time, actor, rerun id), populated only for completed runs so a live run's progress polls pay nothing. No new route.
  - **R-M9-2** Every open `GET /runs/{id}/events` stream on one run shares one poller (`ProgressFeed`, per app), which stops at the run's terminal state, when the run disappears, when the database fails, or when the last stream leaves. Heartbeats stay per stream; `api.progress_poll_s` keeps its meaning.
  - **R-M9-3** The progress read defers the run row's large JSON columns (`report`, `pack_snapshot`, `config_snapshot`, `digests`, `gate`) through `runs.get_run_brief`; nothing in the progress path may touch them.
  - **R-M9-4** The pack listing is cached on a signature of every file under the pack directories (name, size, mtime ns); directory mtimes alone miss an edit inside `rules/`. `resolved` and `validate` still parse on each call.
  - **R-M9-5** Claim-id re-renders are cached per (run, format) in a 64-entry LRU per app: a completed run's record is immutable, and a deleted run is a 404 before the cache is consulted.
  - **R-M9-6** The report frame's CSP binds the bridge by a per-render **nonce**, not a hash: the bridge's serialised text differs between builds (`Function.prototype.toString` of a minified function) and SHA-256 in the browser is asynchronous. `style-src 'unsafe-inline'` because the report's stylesheet and the bridge's highlight style are inline; `default-src 'none'`, `img-src data:`, `connect-src 'none'`.
  - **R-M9-7** Unaddressable pack names are a `corelata doctor` WARN, not a listing field (no schema churn); the pattern lives once, as `corelata.standards.loader.PACK_NAME_PATTERN`, and the API route uses it.
  - **R-M9-8** The run list pages by raising `limit` in steps of 50 up to the API's ceiling of 500; no offset parameter.
  - **R-M9-9** Discovery polling backs off 1 s, 2 s, 4 s, 8 s, then every 15 s, counting polls as `dataUpdateCount + fetchFailureCount`.
  - **R-M9-10** A cancel that arrived after the pipeline's last poll shows as a sentence inside the completed outcome; the state badge keeps the state.

## Review Focus

1. **Two analysts watching the same run must not double the database load, and the second to open the page must still see the latest state at once.** Pinned in Task 2 (`test_two_subscribers_share_one_poller_and_see_the_same_updates`, `test_a_late_subscriber_gets_the_latest_state_at_once`).
2. **An operator who edits a rule file inside an existing pack must see the change in `GET /api/packs` on the next request.** Pinned in Task 3 (`test_the_listing_is_read_once_until_a_pack_file_changes`, `test_pack_dirs_signature_sees_a_nested_edit`).
3. **After a project is deleted, a cached claim-id render must not be served.** Pinned in Task 1 (`test_a_deleted_run_is_not_served_from_the_cache`).
4. **A reload of the review screen after Accept must keep Accept disabled, and a run that was returned must say so and lead to the rerun.** Pinned in Task 5 (`a reload shows an accepted run as decided`, `a returned run shows the decision and links to the rerun`).
5. **With the frame's meta CSP in place, clicking a cited paragraph in a real browser must still highlight the claim.** Pinned by the existing Playwright journey (`web/e2e/journey.spec.ts` lines 57-70), which the final verification runs (`make e2e`); Task 8 keeps the nonce identical in the meta tag and the script tag (`puts the same nonce in the policy and on the bridge`).

---

## File structure

| Path | Responsibility |
|---|---|
| `api/corelata_api/render_cache.py` (new) | `RenderCache`: LRU of claim-id renders per (run, format). |
| `api/corelata_api/progress_feed.py` (new) | `ProgressFeed`: one poller per run shared by every SSE stream. |
| `api/corelata_api/pack_index.py` (new) | `PackIndex`: the pack listing, re-read when the file signature changes. |
| `api/corelata_api/context.py`, `api/corelata_api/app.py` | three new `ApiContext` fields built in the lifespan; the feed is closed before the database. |
| `api/corelata_api/routes/reports.py` | state check first, stored file for the plain case, record only for the re-render, cache. |
| `api/corelata_api/routes/progress.py` | the stream consumes the feed's queue; heartbeats by `wait_for` timeout. |
| `api/corelata_api/routes/packs.py` | listing and name check through the index; pattern from the loader. |
| `engine/corelata/store/runs.py` | `get_run_brief`, `load_review_events`. |
| `engine/corelata/service.py` | `run_progress` uses the brief row and carries `review`; `_review_state`. |
| `engine/corelata/schema/progress.py` | `ReviewDecision`, `ReviewState`, `RunProgress.review`. |
| `engine/corelata/standards/loader.py` | `PACK_NAME_PATTERN`, `pack_dirs_signature`. |
| `engine/corelata/doctor.py` | the `pack names` check. |
| `schema/openapi.json`, `schema/run-progress.schema.json`, `web/src/api/schema.d.ts` | regenerated once (Task 4). |
| `web/src/api/runs.ts`, `events.ts`, `projects.ts`, `discoveries.ts`, `packs.ts` | review invalidation, cancel invalidation, `exact: true`, paged `useRuns`, backoff, pack stale time. |
| `web/src/pages/review/ReviewActions.tsx`, `ReviewPage.tsx`, `AuditTab.tsx`, `frameBridge.ts`, `ReportFrame.tsx` | server-derived decision, `json.error`, loading state and `dir="auto"`, nonce + meta CSP. |
| `web/src/pages/run/RunOutcome.tsx`, `StageTimeline.tsx` | late-cancel sentence; spoken status words and `dir="auto"`. |
| `web/src/pages/new/RunList.tsx`, `NewRunPage.tsx` | Show more; `key={projectId}`. |
| `docs/operator-guide.md`, `README.md`, `docs/m9-followups.md`, earlier follow-up files, spec | docs. |

---

### Task 1: Report routes stop loading the record (CRL-9)

`get_report` loads every model-call body, claim and draft to learn whether a report exists, then (without `with_claim_ids`) ignores all of it and serves a stored file. The `with_claim_ids=1` path re-renders on every call.

**Files:**
- Create: `api/corelata_api/render_cache.py`
- Modify: `api/corelata_api/context.py` (`ApiContext.renders`), `api/corelata_api/app.py` (lifespan), `api/corelata_api/routes/reports.py` (`get_report`, new `_claim_ids_render`)
- Test: `api/tests/test_render_cache.py` (new), `api/tests/test_reports.py`

**Interfaces:**
- Produces: `RenderCache(capacity: int = 64)` with `get(run_id: str, fmt: str) -> bytes | None`, `put(run_id: str, fmt: str, content: bytes) -> None`, `__len__`; `ApiContext.renders: RenderCache`. Tasks 2 and 3 add their own fields next to it, in the same way.

- [ ] **Step 1: Failing cache tests**

Create `api/tests/test_render_cache.py`:

```python
import pytest

from corelata_api.render_cache import RenderCache


def test_returns_what_was_put_and_none_otherwise():
    cache = RenderCache(capacity=2)
    assert cache.get("r1", "html") is None
    cache.put("r1", "html", b"<p>1</p>")
    assert cache.get("r1", "html") == b"<p>1</p>"
    assert cache.get("r1", "md") is None  # the format is part of the key


def test_evicts_the_least_recently_used_entry():
    cache = RenderCache(capacity=2)
    cache.put("r1", "html", b"1")
    cache.put("r2", "html", b"2")
    assert cache.get("r1", "html") == b"1"  # r1 is now the most recent
    cache.put("r3", "html", b"3")
    assert len(cache) == 2
    assert cache.get("r2", "html") is None
    assert cache.get("r1", "html") == b"1" and cache.get("r3", "html") == b"3"


def test_putting_the_same_key_replaces_without_growing():
    cache = RenderCache(capacity=1)
    cache.put("r1", "html", b"a")
    cache.put("r1", "html", b"b")
    assert len(cache) == 1 and cache.get("r1", "html") == b"b"


def test_capacity_must_be_positive():
    with pytest.raises(ValueError, match="at least 1"):
        RenderCache(capacity=0)
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd api && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/test_render_cache.py --no-cov`
Expected: FAIL with `ModuleNotFoundError: No module named 'corelata_api.render_cache'`

- [ ] **Step 3: The cache**

Create `api/corelata_api/render_cache.py`:

```python
"""A small LRU for the re-rendered reports `GET /runs/{id}/report?with_claim_ids=1` serves. A
completed run's record never changes, so a render keyed on (run, format) stays valid for the life
of the process; the capacity bounds memory on a shared analyst host (CRL-9, R-M9-5)."""

from collections import OrderedDict


class RenderCache:
    def __init__(self, capacity: int = 64) -> None:
        if capacity < 1:
            raise ValueError("capacity must be at least 1")
        self._capacity = capacity
        self._items: OrderedDict[tuple[str, str], bytes] = OrderedDict()

    def get(self, run_id: str, fmt: str) -> bytes | None:
        key = (run_id, fmt)
        value = self._items.get(key)
        if value is not None:
            self._items.move_to_end(key)
        return value

    def put(self, run_id: str, fmt: str, content: bytes) -> None:
        key = (run_id, fmt)
        self._items[key] = content
        self._items.move_to_end(key)
        while len(self._items) > self._capacity:
            self._items.popitem(last=False)

    def __len__(self) -> int:
        return len(self._items)
```

- [ ] **Step 4: Run the cache tests**

Run: the Step 2 command. Expected: 4 passed.

- [ ] **Step 5: Wire the cache into the context**

In `api/corelata_api/context.py`, import `RenderCache` and add a field to the frozen dataclass after `coglossa`:

```python
    renders: RenderCache  # claim-id re-renders, per (run, format) (CRL-9)
```

In `api/corelata_api/app.py`, inside the lifespan's `ApiContext(...)` call (lines 68-80), add `renders=RenderCache(),` after the `coglossa=(...)` argument, and import `from corelata_api.render_cache import RenderCache`. `ApiContext(` is constructed nowhere else (`grep -rn "ApiContext(" api/` shows only `app.py:68`); confirm before moving on.

- [ ] **Step 6: Failing route tests**

Append to `api/tests/test_reports.py`:

```python
async def test_stored_report_does_not_load_the_record(api, monkeypatch):
    run = await _completed(api)

    async def forbidden(db, run_id):
        raise AssertionError("the stored path must not load the record")

    monkeypatch.setattr(reports.service, "get_run_record", forbidden)
    for fmt in ("json", "md", "html", "docx"):
        response = await api.client.get(f"/api/runs/{run['run_id']}/report", params={"format": fmt})
        assert response.status_code == 200, (fmt, response.text)
    exports = await api.client.get(f"/api/runs/{run['run_id']}/exports/trace.json")
    assert exports.status_code == 200


async def test_claim_ids_render_is_cached_per_run_and_format(api, monkeypatch):
    run = await _completed(api)
    real = reports._render
    calls: list[str] = []

    def counting(record, fmt, **kw):
        calls.append(fmt)
        return real(record, fmt, **kw)

    monkeypatch.setattr(reports, "_render", counting)
    url = f"/api/runs/{run['run_id']}/report"
    first = await api.client.get(url, params={"format": "html", "with_claim_ids": "1"})
    second = await api.client.get(url, params={"format": "html", "with_claim_ids": "1"})
    assert first.status_code == second.status_code == 200
    assert first.content == second.content and "data-claim-ids" in first.text
    md = await api.client.get(url, params={"format": "md", "with_claim_ids": "1"})
    assert md.status_code == 200
    assert calls == ["html", "md"]  # one render per (run, format)
    assert len(api.client._transport.app.state.ctx.renders) == 2  # noqa: SLF001


async def test_a_deleted_run_is_not_served_from_the_cache(api):
    run = await _completed(api)
    url = f"/api/runs/{run['run_id']}/report"
    assert (await api.client.get(url, params={"format": "html", "with_claim_ids": "1"})).status_code == 200
    async with api.db.session() as s, s.begin():
        await runs.delete_project(s, uuid.UUID(run["project_id"]))
    gone = await api.client.get(url, params={"format": "html", "with_claim_ids": "1"})
    assert gone.status_code == 404
```

If `api.client._transport.app` is not how the `Api` fixture exposes the app (check `api/tests/conftest.py` lines 58-97), add an `app` attribute to the `Api` dataclass in `conftest.py` and use `api.app.state.ctx.renders` instead.

- [ ] **Step 7: Run them to see them fail**

Run: `cd api && CORELATA_TEST_DATABASE_URL=... uv run pytest tests/test_reports.py --no-cov -k "stored_report_does_not or cached_per_run or not_served_from_the_cache"`
Expected: the first fails with the `AssertionError` surfacing as a 500 (`assert 500 == 200`); the second fails on `calls == ["html", "md"]` (two html renders); the third passes already (keep it: it pins Review Focus 3 once the cache exists).

- [ ] **Step 8: The route**

In `api/corelata_api/routes/reports.py`:

Change the import line `from corelata.schema import Finding, RunRecord` to `from corelata.schema import Finding, RunRecord, RunState`.

Add after `_render` (line 67):

```python
async def _claim_ids_render(ctx: ApiContext, run_id: uuid.UUID, fmt: str) -> bytes:
    """The re-render, once per (run, format) for the life of the process (R-M9-5): the record is
    loaded only here, and only on a miss."""
    cached = ctx.renders.get(str(run_id), fmt)
    if cached is not None:
        return cached
    record = await _record_with_report(ctx, run_id)
    reference = None
    if fmt == "docx":
        reference = await service.reference_document(ctx.db, ctx.storage, run_id)
    try:
        content = await asyncio.to_thread(
            _render, record, fmt, with_claim_ids=True, reference=reference
        )
    except Exception as e:
        if fmt == "docx":
            raise InvalidRunStateError(
                f"DOCX export failed: {str(e) or type(e).__name__}"
            ) from e
        raise
    ctx.renders.put(str(run_id), fmt, content)
    return content
```

Replace the body of `get_report` (lines 85-114; keep the decorator, signature and docstring as they are) with:

```python
    progress = await service.run_progress(ctx.db, run_id)  # an unknown run is a plain 404
    if progress.state is not RunState.COMPLETED:
        raise InvalidRunStateError(f"run {run_id} has no report (state {progress.state.value})")
    if format == "docx" and progress.export_error:
        raise InvalidRunStateError(progress.export_error)
    if with_claim_ids:
        content = await _claim_ids_render(ctx, run_id, format)
    else:
        stored = await service.stored_export(ctx.db, ctx.storage, run_id, f"report.{format}")
        if stored is None:
            raise NotFoundError(f"run {run_id} has no stored export report.{format}")
        content = stored
    return _file(
        content,
        media=MEDIA[format],
        filename=f"report-{str(run_id)[:8]}.{format}",
        attachment=download or format == "docx",
    )
```

Read the current lines 85-114 first and keep whatever the existing `_file(...)` call passes if it differs from the above. `_record_with_report` stays (used by `get_claim` and `_claim_ids_render`). Update the module docstring's second sentence to: "the report is served from the worker's stored export … unless claim ids are requested, which re-renders from the stored record once per run and format (CRL-9)."

- [ ] **Step 9: Run the whole API suite and lint**

Run: `make test-api` and `cd api && uv run ruff check . && uv run ruff format --check .`
Expected: all pass, coverage ≥ 95%. `test_report_before_completion_is_409` still passes because the message is unchanged; `test_re_render_failures` still passes because the docx wrapping and the html re-raise are unchanged.

- [ ] **Step 10: Commit**

```bash
git add api/corelata_api/render_cache.py api/corelata_api/context.py api/corelata_api/app.py api/corelata_api/routes/reports.py api/tests/test_render_cache.py api/tests/test_reports.py
git commit -F <scratchpad file>   # "feat(api): report routes check state first and cache claim-id renders (CRL-9)"
```

---

### Task 2: One progress poller per run, and a lighter progress read (CRL-8, server)

Every open SSE stream polls `run_progress` on its own timer, and `run_progress` loads the run row with its report, pack snapshot and digests to read a dozen scalar columns.

**Files:**
- Modify: `engine/corelata/store/runs.py` (new `get_run_brief`), `engine/corelata/service.py` (`run_progress`)
- Create: `api/corelata_api/progress_feed.py`
- Modify: `api/corelata_api/context.py` (`ApiContext.progress`), `api/corelata_api/app.py` (lifespan), `api/corelata_api/routes/progress.py` (`_stream`)
- Test: `engine/tests/store/test_runs.py`, `api/tests/test_progress_feed.py` (new), `api/tests/test_progress.py`

**Interfaces:**
- Consumes: `ApiContext` field pattern from Task 1.
- Produces: `runs.get_run_brief(s, run_id) -> Run` (heavy columns deferred); `ProgressFeed(fetch: Callable[[uuid.UUID], Awaitable[RunProgress]], poll_s: float)` with `subscribe(run_id, last) -> asyncio.Queue[Update]`, `unsubscribe(run_id, queue)`, `active: int`, `async close()`; sentinels `DELETED`, `ENDED`; `Update = RunProgress | Deleted | Ended`. Task 4 changes `run_progress`'s body again (adds `review`); it keeps `get_run_brief`.

- [ ] **Step 1: Failing store test**

Append to `engine/tests/store/test_runs.py`:

```python
async def test_get_run_brief_leaves_the_heavy_columns_unloaded(db):
    from sqlalchemy import inspect

    async with db.session() as s, s.begin():
        project, row = await _project_with_source(s)
        run_id = await _run(s, project, [row])
    async with db.session() as s:
        run = await runs.get_run_brief(s, run_id)
        unloaded = inspect(run).unloaded
        assert {"report", "pack_snapshot", "config_snapshot", "digests", "gate"} <= unloaded
        assert run.state == "created" and run.max_iterations == 2 and run.pack_name == "icd203-base"
        progress = service._progress(run, [])
        assert progress.run_id == str(run_id) and progress.stages == []
        with pytest.raises(runs.NotFoundError):
            await runs.get_run_brief(s, uuid.uuid4())
```

Check what `_run` returns (line 58: `runs.create_run(...)`); if it returns a `Run` rather than an id, use `.id`.

- [ ] **Step 2: Run it to see it fail**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=... uv run pytest tests/store/test_runs.py --no-cov -k brief`
Expected: FAIL with `AttributeError: module 'corelata.store.runs' has no attribute 'get_run_brief'`

- [ ] **Step 3: The brief read**

In `engine/corelata/store/runs.py`, add `from sqlalchemy.orm import defer` to the imports, and after `get_run` (line 245):

```python
HEAVY_RUN_COLUMNS = (Run.report, Run.pack_snapshot, Run.config_snapshot, Run.digests, Run.gate)


async def get_run_brief(s: AsyncSession, run_id: uuid.UUID) -> Run:
    """The run row without its large JSON columns, for progress views (CRL-8, R-M9-3). The
    deferred attributes must not be read: in an async session a lazy load raises."""
    query = select(Run).where(Run.id == run_id).options(*(defer(c) for c in HEAVY_RUN_COLUMNS))
    run = await s.scalar(query)
    if run is None:
        raise NotFoundError(f"run {run_id} not found")
    return run
```

In `engine/corelata/service.py` `run_progress` (lines 465-468), replace `runs.get_run(s, run_id)` with `runs.get_run_brief(s, run_id)`.

- [ ] **Step 4: Run the engine suite**

Run: `make test-engine`
Expected: all pass (the service tests cover `run_progress`; the new test passes).

- [ ] **Step 5: Failing feed tests**

Create `api/tests/test_progress_feed.py`:

```python
import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from corelata.schema import RunProgress
from corelata.store.runs import NotFoundError
from sqlalchemy.exc import OperationalError

from corelata_api.progress_feed import DELETED, ENDED, ProgressFeed

RUN = uuid.uuid4()


def progress(state: str) -> RunProgress:
    return RunProgress(
        run_id=str(RUN),
        project_id=str(uuid.uuid4()),
        state=state,
        iteration=0,
        max_iterations=2,
        created_at=datetime(2026, 10, 15, tzinfo=UTC),
    )


def scripted(*states):
    """A fetch that answers the given states in order (the last one repeats), counting calls; an
    exception in the script is raised."""
    queue = list(states)
    calls = {"n": 0}

    async def fetch(run_id):
        calls["n"] += 1
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return progress(item)

    return fetch, calls


async def drain(queue, n):
    return [await asyncio.wait_for(queue.get(), 1.0) for _ in range(n)]


async def test_two_subscribers_share_one_poller_and_see_the_same_updates():
    fetch, calls = scripted("gating", "drafting", "drafting", "completed")
    feed = ProgressFeed(fetch, poll_s=0.01)
    first = progress("created")
    q1 = feed.subscribe(RUN, first)
    q2 = feed.subscribe(RUN, first)
    assert feed.active == 1
    seen1, seen2 = await drain(q1, 3), await drain(q2, 3)
    assert [u.state for u in seen1] == ["gating", "drafting", "completed"]
    assert [u.state for u in seen2] == ["gating", "drafting", "completed"]
    await asyncio.sleep(0.05)
    assert calls["n"] == 4 and feed.active == 0  # one read per tick, stopped at the terminal state
    feed.unsubscribe(RUN, q1)
    feed.unsubscribe(RUN, q2)


async def test_a_late_subscriber_gets_the_latest_state_at_once():
    fetch, _ = scripted("gating", "drafting", *(["drafting"] * 20), "completed")
    feed = ProgressFeed(fetch, poll_s=0.01)
    q1 = feed.subscribe(RUN, progress("created"))
    [gating, drafting] = await drain(q1, 2)
    q2 = feed.subscribe(RUN, progress("created"))  # joins after two changes, while it still polls
    assert q2.get_nowait().state == "drafting"  # the poller's latest, queued immediately
    assert feed.active == 1
    [done] = await drain(q2, 1)
    assert done.state == "completed"
    await feed.close()


async def test_the_poller_stops_when_the_last_subscriber_leaves():
    fetch, calls = scripted(*(["gating"] * 100))
    feed = ProgressFeed(fetch, poll_s=0.01)
    q1 = feed.subscribe(RUN, progress("created"))
    q2 = feed.subscribe(RUN, progress("created"))
    await drain(q1, 1)
    feed.unsubscribe(RUN, q1)
    assert feed.active == 1
    feed.unsubscribe(RUN, q2)
    assert feed.active == 0
    await asyncio.sleep(0.05)
    n = calls["n"]
    await asyncio.sleep(0.05)
    assert calls["n"] == n  # nothing polls an unwatched run


async def test_a_deleted_run_and_a_database_error_end_the_feed():
    fetch, _ = scripted(NotFoundError("gone"))
    feed = ProgressFeed(fetch, poll_s=0.01)
    q = feed.subscribe(RUN, progress("created"))
    assert (await drain(q, 1)) == [DELETED]
    await asyncio.sleep(0.02)
    assert feed.active == 0

    fetch, _ = scripted(OperationalError("SELECT", {}, ConnectionResetError("gone")))
    feed = ProgressFeed(fetch, poll_s=0.01)
    q = feed.subscribe(RUN, progress("created"))
    assert (await drain(q, 1)) == [ENDED]
    await asyncio.sleep(0.02)
    assert feed.active == 0


async def test_close_cancels_every_poller():
    fetch, _ = scripted(*(["gating"] * 100))
    feed = ProgressFeed(fetch, poll_s=0.01)
    feed.subscribe(RUN, progress("created"))
    feed.subscribe(uuid.uuid4(), progress("created"))
    assert feed.active == 2
    await feed.close()
    assert feed.active == 0
    await feed.close()  # idempotent
```

Confirm `RunProgress`'s required fields against `engine/corelata/schema/progress.py` lines 20-36 (`run_id`, `project_id`, `state`, `iteration`, `max_iterations`, `created_at`); add any the model requires.

- [ ] **Step 6: Run them to see them fail**

Run: `cd api && CORELATA_TEST_DATABASE_URL=... uv run pytest tests/test_progress_feed.py --no-cov`
Expected: FAIL with `ModuleNotFoundError: No module named 'corelata_api.progress_feed'`

- [ ] **Step 7: The feed**

Create `api/corelata_api/progress_feed.py`:

```python
"""One database poller per run, shared by every open `GET /runs/{id}/events` stream (CRL-8,
R-M9-2). A stream subscribes with the state it has shown and receives each change after it; the
poller runs while anyone listens and stops at the run's terminal state, when the run disappears,
when the database fails, or when the last stream leaves."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from corelata.schema import TERMINAL_STATES, RunProgress
from corelata.store.db import error_reason
from corelata.store.runs import NotFoundError
from sqlalchemy.exc import InterfaceError, OperationalError

log = logging.getLogger("corelata.api")

Fetch = Callable[[uuid.UUID], Awaitable[RunProgress]]


class Deleted:
    """The run no longer exists."""


class Ended:
    """The poller stopped without a terminal state (database error); the stream closes and the
    browser reconnects after `retry`."""


DELETED = Deleted()
ENDED = Ended()
Update = RunProgress | Deleted | Ended


@dataclass
class _Poller:
    task: asyncio.Task[None]
    queues: set[asyncio.Queue[Update]] = field(default_factory=set)
    latest: RunProgress | None = None


class ProgressFeed:
    def __init__(self, fetch: Fetch, poll_s: float) -> None:
        self._fetch = fetch
        self._poll_s = poll_s
        self._pollers: dict[uuid.UUID, _Poller] = {}

    @property
    def active(self) -> int:
        """Runs with a live poller."""
        return len(self._pollers)

    def subscribe(self, run_id: uuid.UUID, last: RunProgress) -> asyncio.Queue[Update]:
        """Updates after `last`. When the shared poller already saw something newer, it is queued
        at once, so a late subscriber never waits a whole poll for a change that happened."""
        queue: asyncio.Queue[Update] = asyncio.Queue()
        poller = self._pollers.get(run_id)
        if poller is None:
            poller = _Poller(task=asyncio.create_task(self._run(run_id)))
            self._pollers[run_id] = poller
        poller.queues.add(queue)
        if poller.latest is not None and poller.latest != last:
            queue.put_nowait(poller.latest)
        return queue

    def unsubscribe(self, run_id: uuid.UUID, queue: asyncio.Queue[Update]) -> None:
        poller = self._pollers.get(run_id)
        if poller is None:
            return
        poller.queues.discard(queue)
        if not poller.queues:
            poller.task.cancel()
            self._pollers.pop(run_id, None)

    async def close(self) -> None:
        pollers = list(self._pollers.values())
        self._pollers.clear()
        for poller in pollers:
            poller.task.cancel()
        for poller in pollers:
            try:
                await poller.task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001 - shutting down
                pass

    def _publish(self, run_id: uuid.UUID, update: Update) -> None:
        poller = self._pollers.get(run_id)
        if poller is None:
            return
        for queue in poller.queues:
            queue.put_nowait(update)

    async def _run(self, run_id: uuid.UUID) -> None:
        last: RunProgress | None = None
        try:
            while True:
                await asyncio.sleep(self._poll_s)
                try:
                    current = await self._fetch(run_id)
                except NotFoundError:
                    self._publish(run_id, DELETED)
                    return
                except (OperationalError, InterfaceError) as e:
                    log.warning(
                        "progress poller ended: %s", error_reason(e), extra={"run_id": str(run_id)}
                    )
                    self._publish(run_id, ENDED)
                    return
                poller = self._pollers.get(run_id)
                if poller is not None:
                    poller.latest = current
                if current != last:
                    self._publish(run_id, current)
                    last = current
                if current.state in TERMINAL_STATES:
                    return
        finally:
            self._pollers.pop(run_id, None)
```

- [ ] **Step 8: Run the feed tests**

Run: the Step 6 command. Expected: 5 passed.

- [ ] **Step 9: Wire the feed into the app and the route**

`api/corelata_api/context.py`: import `ProgressFeed` and add after `renders`:

```python
    progress: ProgressFeed  # one database poller per run for the SSE streams (CRL-8)
```

`api/corelata_api/app.py` lifespan (lines 63-83): create the feed before the queue opens and close it before the database is disposed:

```python
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        db = Database(database_url(cfg))
        feed = ProgressFeed(lambda run_id: service.run_progress(db, run_id), cfg.api.progress_poll_s)
        try:
            async with open_queue(db.url) as queue:
                app.state.ctx = ApiContext(
                    ...existing arguments...,
                    renders=RenderCache(),
                    progress=feed,
                )
                yield
        finally:
            await feed.close()
            await db.dispose()
```

Import `from corelata import service` and `from corelata_api.progress_feed import ProgressFeed` in `app.py` (check whether `service` is already imported). The lambda must look `service.run_progress` up at call time (it does), so `api/tests/test_progress.py::test_a_database_error_ends_the_stream`, which monkeypatches `progress_module.service.run_progress`, keeps working.

`api/corelata_api/routes/progress.py`: replace `_stream` (lines 29-51) with

```python
async def _stream(ctx: ApiContext, run_id: uuid.UUID, first: RunProgress) -> AsyncIterator[str]:
    yield "retry: 3000\n\n"
    yield _event(first)
    last = first
    if last.state in TERMINAL_STATES:
        return
    queue = ctx.progress.subscribe(run_id, last)
    try:
        while last.state not in TERMINAL_STATES:
            try:
                update = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_S)
            except TimeoutError:
                yield ": keep-alive\n\n"
                continue
            if isinstance(update, Deleted):
                yield "event: deleted\ndata: {}\n\n"
                return
            if isinstance(update, Ended):
                return  # the browser reconnects after `retry`
            if update != last:
                yield _event(update)
                last = update
    finally:
        ctx.progress.unsubscribe(run_id, queue)
```

Imports: add `from corelata_api.progress_feed import Deleted, Ended`; drop the now-unused `service` (keep it: `run_events` still calls `service.run_progress` for `first`), `error_reason`, `NotFoundError`, `InterfaceError`, `OperationalError`, `log`/`logging` if nothing else in the module uses them (ruff F401 will tell). Update the module docstring: "Polls the database once per run at api.progress_poll_s however many streams watch it (`ProgressFeed`, CRL-8)."

- [ ] **Step 10: An API-level test for two streams**

Append to `api/tests/test_progress.py`:

```python
async def test_two_streams_on_one_run_end_together_and_leave_no_poller(api):
    run = await start_run(api)
    finisher = asyncio.create_task(_finish_later(api.db, run["run_id"]))
    url = f"/api/runs/{run['run_id']}/events"
    first, second = await asyncio.gather(api.client.get(url), api.client.get(url))
    await finisher
    for response in (first, second):
        assert [d["state"] for _, d in _events(response.text)] == ["created", "gating", "completed"]
    assert api.client._transport.app.state.ctx.progress.active == 0  # noqa: SLF001
```

Use the same app handle as Task 1 Step 6 settled on.

- [ ] **Step 11: Run the API suite and lint**

Run: `make test-api` and `cd api && uv run ruff check . && uv run ruff format --check .`
Expected: all pass. `test_a_quiet_stream_sends_keep_alives` (patches `HEARTBEAT_S` to 0.04) passes because `_stream` reads the module global at each `wait_for`. `test_a_database_error_ends_the_stream` still counts exactly 2 calls (the route's `first`, then the poller's one failing read).

- [ ] **Step 12: Commit**

```bash
git add engine/corelata/store/runs.py engine/corelata/service.py engine/tests/store/test_runs.py api/corelata_api/progress_feed.py api/corelata_api/context.py api/corelata_api/app.py api/corelata_api/routes/progress.py api/tests/test_progress_feed.py api/tests/test_progress.py
git commit -F <scratchpad file>   # "feat(api): one progress poller per run; progress reads skip the heavy run columns (CRL-8)"
```

---

### Task 3: The pack listing is read once until a pack file changes (CRL-8, server)

`GET /api/packs` parses every pack on every call, and `_known` does it again for every `resolved`/`validate` request.

**Files:**
- Modify: `engine/corelata/standards/loader.py` (`PACK_NAME_PATTERN`, `pack_dirs_signature`)
- Create: `api/corelata_api/pack_index.py`
- Modify: `api/corelata_api/context.py` (`ApiContext.packs`), `api/corelata_api/app.py`, `api/corelata_api/routes/packs.py`
- Test: `engine/tests/standards/test_loader.py`, `api/tests/test_packs.py`

**Interfaces:**
- Produces: `loader.PACK_NAME_PATTERN: re.Pattern[str]` (used by Task 8's doctor check), `loader.pack_dirs_signature(packs_dir: Path | None) -> tuple[tuple[str, int, int], ...]`, `PackIndex(packs_dir)` with `listing() -> list[PackSummary]` and `names() -> set[str]`; `ApiContext.packs: PackIndex`.

- [ ] **Step 1: Failing loader test**

Append to `engine/tests/standards/test_loader.py` (add `import os` and `import time` at the top):

```python
def test_pack_dirs_signature_sees_a_nested_edit(tmp_path):
    from corelata.standards.loader import PACK_NAME_PATTERN, pack_dirs_signature

    write_pack(tmp_path, "team", rules=[RULE], extends="icd203-base")
    before = pack_dirs_signature(tmp_path)
    assert pack_dirs_signature(tmp_path) == before  # stable while nothing changes
    assert any(entry[0].endswith("icd203-base/pack.yaml") for entry in before)  # built-in included
    rule_file = next(tmp_path.glob("team/rules/*.yaml"))
    later = time.time() + 10
    os.utime(rule_file, (later, later))  # an edit inside rules/: the directory's mtime is unchanged
    assert pack_dirs_signature(tmp_path) != before
    assert pack_dirs_signature(None) == pack_dirs_signature(tmp_path / "missing")  # built-in only
    assert PACK_NAME_PATTERN.match("team-east") and not PACK_NAME_PATTERN.match("Customer_A")
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=... uv run pytest tests/standards/test_loader.py --no-cov -k signature`
Expected: FAIL with `ImportError: cannot import name 'PACK_NAME_PATTERN'`

- [ ] **Step 3: The signature and the pattern**

In `engine/corelata/standards/loader.py`, add `import re` to the imports, and after `BUILTIN_PACKS_DIR` (line 26):

```python
# What `/api/packs/{name}` accepts; a directory named otherwise loads but cannot be addressed
# through the API (the doctor warns about it, R-M9-7).
PACK_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9\-]*$")
```

After `list_packs` (line 158):

```python
def pack_dirs_signature(packs_dir: Path | None) -> tuple[tuple[str, int, int], ...]:
    """Every file under the pack directories with its size and mtime (ns). Equal signatures mean
    the listing is unchanged; directory mtimes alone miss an edit inside rules/ (R-M9-4). Stats
    only: no file is opened."""
    out: list[tuple[str, int, int]] = []
    for base in (BUILTIN_PACKS_DIR, packs_dir):
        if base is None or not base.is_dir():
            continue
        for path in sorted(p for p in base.rglob("*") if p.is_file()):
            st = path.stat()
            out.append((str(path), st.st_size, st.st_mtime_ns))
    return tuple(out)
```

- [ ] **Step 4: Run the loader test**

Run: the Step 2 command. Expected: PASS.

- [ ] **Step 5: Failing API test**

Append to `api/tests/test_packs.py` (add `import os`, `import time` and `from corelata_api import pack_index` at the top):

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

    monkeypatch.setattr(pack_index, "list_packs", counting)
    async with make_api(standards={"packs_dir": str(packs), "default_pack": "team"}) as api:
        for _ in range(3):
            listed = (await api.client.get("/api/packs")).json()
            assert [p["name"] for p in listed] == ["icd203-base", "team"]
        assert (await api.client.get("/api/packs/team/validate")).status_code == 200
        assert (await api.client.get("/api/packs/nope/validate")).status_code == 404
        assert calls["n"] == 1  # three listings and two name checks: one read
        (team / "pack.yaml").write_text(yaml.safe_dump({**meta, "version": "1.1"}), encoding="utf-8")
        later = time.time() + 10
        os.utime(team / "pack.yaml", (later, later))
        listed = {p["name"]: p for p in (await api.client.get("/api/packs")).json()}
        assert listed["team"]["version"] == "1.1" and calls["n"] == 2
```

- [ ] **Step 6: Run it to see it fail**

Run: `cd api && CORELATA_TEST_DATABASE_URL=... uv run pytest tests/test_packs.py --no-cov -k read_once`
Expected: FAIL with `ImportError: cannot import name 'pack_index'`

- [ ] **Step 7: The index and the routes**

Create `api/corelata_api/pack_index.py`:

```python
"""The pack listing `GET /api/packs` serves and the name check the other pack routes make,
re-read only when a file under the pack directories changed (CRL-8, R-M9-4). Resolving and
validating still parse on each call: a customer edits packs in place and expects to see it."""

from pathlib import Path

from corelata.standards.loader import PackSummary, list_packs, pack_dirs_signature


class PackIndex:
    def __init__(self, packs_dir: Path | None) -> None:
        self._packs_dir = packs_dir
        self._signature: tuple[tuple[str, int, int], ...] | None = None
        self._listing: list[PackSummary] = []

    def listing(self) -> list[PackSummary]:
        signature = pack_dirs_signature(self._packs_dir)
        if signature != self._signature:
            self._listing = list_packs(self._packs_dir)
            self._signature = signature
        return self._listing

    def names(self) -> set[str]:
        return {p.name for p in self.listing()}
```

`api/corelata_api/context.py`: import `PackIndex`, add after `progress`:

```python
    packs: PackIndex  # the pack listing, re-read when a pack file changes (CRL-8)
```

`api/corelata_api/app.py`: `packs=PackIndex(cfg.standards.packs_dir),` in the `ApiContext(...)` call; import it.

`api/corelata_api/routes/packs.py`:

```python
"""Spec §10.1 packs: what is installed, how a pack resolves with a profile, and whether it is
valid. The listing is re-read when a pack file changes (`PackIndex`); resolving and validating
read the directories on every call, since a customer edits them in place."""

from typing import Annotated

from corelata.config import ConfigIssue
from corelata.standards.loader import PACK_NAME_PATTERN, PackSummary, load_pack, validate_pack
from corelata.standards.schema import ResolvedPack
from corelata.store.runs import NotFoundError
from fastapi import APIRouter, Path
from pydantic import BaseModel

from corelata_api.context import Ctx

router = APIRouter(tags=["packs"])

PackName = Annotated[str, Path(pattern=PACK_NAME_PATTERN.pattern, max_length=100)]


class PackValidation(BaseModel):
    ok: bool
    issues: list[ConfigIssue]


def _known(ctx: Ctx, name: str) -> None:
    if name not in ctx.packs.names():
        raise NotFoundError(f"pack '{name}' not found")


@router.get("/packs")
async def get_packs(ctx: Ctx) -> list[PackSummary]:
    return ctx.packs.listing()
```

`get_resolved` and `get_validation` stay as they are. `PACK_NAME_PATTERN.pattern` is the same string as before (`^[a-z0-9][a-z0-9\-]*$`), so `schema/openapi.json` does not change; `test_committed_openapi_matches_the_app` proves it.

- [ ] **Step 8: Run the API suite and lint**

Run: `make test-api` and `cd api && uv run ruff check . && uv run ruff format --check .`
Expected: all pass, including `test_customer_packs_with_draft_profiles` (each `make_api` builds its own `PackIndex`).

- [ ] **Step 9: Commit**

```bash
git add engine/corelata/standards/loader.py engine/tests/standards/test_loader.py api/corelata_api/pack_index.py api/corelata_api/context.py api/corelata_api/app.py api/corelata_api/routes/packs.py api/tests/test_packs.py
git commit -F <scratchpad file>   # "feat(api): pack listing cached on a file signature (CRL-8)"
```

---

### Task 4: `RunProgress.review` (CRL-15, backend) and the schema regeneration

The review screen cannot know whether a run was accepted or returned: no response carries the review events.

**Files:**
- Modify: `engine/corelata/schema/progress.py` (`ReviewDecision`, `ReviewState`, `RunProgress.review`), `engine/corelata/schema/__init__.py` (exports), `engine/corelata/store/runs.py` (`load_review_events`), `engine/corelata/service.py` (`_review_state`, `_progress`, `run_progress`)
- Regenerate: `schema/openapi.json`, `schema/run-progress.schema.json`, `web/src/api/schema.d.ts` (`make schema`)
- Modify: `web/src/api/types.ts` (export `ReviewState`, `ReviewDecision`), `web/src/test/fixtures.ts` (`review: null`)
- Test: `engine/tests/test_service.py`, `api/tests/test_runs.py`

**Interfaces:**
- Consumes: `runs.get_run_brief` (Task 2).
- Produces: `ReviewDecision` (`accepted` | `returned`), `ReviewState(decision, at: datetime, actor: str | None = None, child_run_id: str | None = None)`, `RunProgress.review: ReviewState | None = None`; `runs.load_review_events(s, run_id) -> list[ReviewEvent]`; `service._review_state(events) -> ReviewState | None`; TypeScript `ReviewState`, `ReviewDecision` in `web/src/api/types.ts`. Task 5 reads `progress.review`.

- [ ] **Step 1: Failing service test**

Append to `engine/tests/test_service.py`:

```python
async def test_run_progress_carries_the_review_decision(svc):
    pid = await svc.project()
    run_id = await svc.run(pid, [await svc.source(pid)])
    assert (await service.run_progress(svc.db, run_id)).review is None
    await _set_state(svc.db, run_id, "completed")
    assert (await service.run_progress(svc.db, run_id)).review is None  # completed, not reviewed
    args = (svc.db, svc.storage, svc.queue, svc.cfg, svc.prompts, run_id)
    await service.review_run(*args, ReviewAction.ACCEPT, actor="alice")
    accepted = (await service.run_progress(svc.db, run_id)).review
    assert accepted is not None
    assert (accepted.decision, accepted.actor, accepted.child_run_id) == ("accepted", "alice", None)
    child = await service.review_run(*args, ReviewAction.RETURN, note="tighten", actor="bob")
    returned = (await service.run_progress(svc.db, run_id)).review
    assert returned is not None
    assert (returned.decision, returned.actor, returned.child_run_id) == (
        "returned",
        "bob",
        str(child),
    )
    assert returned.at >= accepted.at
    assert (await service.run_progress(svc.db, child)).review is None


def test_review_state_prefers_the_return_and_the_latest_accept():
    from corelata.store.models import ReviewEvent

    t = [utcnow() for _ in range(3)]
    accept_a = ReviewEvent(action="accept", note="", actor="a", child_run_id=None, at=t[0])
    accept_b = ReviewEvent(action="accept", note="", actor="b", child_run_id=None, at=t[1])
    pending = ReviewEvent(action="return", note="x", actor="c", child_run_id=None, at=t[2])
    assert service._review_state([]) is None
    latest = service._review_state([accept_a, accept_b])
    assert latest is not None and latest.actor == "b"
    placeholder = service._review_state([accept_a, pending])
    assert placeholder is not None
    assert placeholder.decision == "returned" and placeholder.child_run_id is None
```

`_set_state` and `utcnow` are already in the module (lines 20, 64).

- [ ] **Step 2: Run them to see them fail**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=... uv run pytest tests/test_service.py --no-cov -k "review_decision or review_state_prefers"`
Expected: FAIL with `AttributeError: 'RunProgress' object has no attribute 'review'` and `module 'corelata.service' has no attribute '_review_state'`

- [ ] **Step 3: Schema, store and service**

`engine/corelata/schema/progress.py`, after `ReviewAction` (line 17):

```python
class ReviewDecision(StrEnum):
    ACCEPTED = "accepted"
    RETURNED = "returned"


class ReviewState(BaseModel):
    """What a reviewer decided about a completed run (spec §10.1), from its review events. A
    `return` wins over an `accept`: the rerun supersedes the accepted report (R-M9-1)."""

    decision: ReviewDecision
    at: datetime
    actor: str | None = None
    child_run_id: str | None = None  # the rerun a return created; None while it is being made
```

In `RunProgress`, after `export_error` (line 33):

```python
    review: ReviewState | None = None  # completed runs only (M9, CRL-15)
```

`engine/corelata/schema/__init__.py`: add `ReviewDecision` and `ReviewState` to the import from `.progress` and to `__all__`, next to `ReviewAction` (lines 35 and 108).

`engine/corelata/store/runs.py`, after `return_event` (line 502):

```python
async def load_review_events(s: AsyncSession, run_id: uuid.UUID) -> list[ReviewEvent]:
    """Every review action on the run, oldest first."""
    return list(
        await s.scalars(
            select(ReviewEvent)
            .where(ReviewEvent.run_id == run_id)
            .order_by(ReviewEvent.at, ReviewEvent.id)
        )
    )
```

`engine/corelata/service.py`: import `ReviewDecision, ReviewState` from `corelata.schema` (find the existing `from corelata.schema import (...)` block) and `ReviewEvent` from `corelata.store.models` if not already imported. Before `_progress` (line 444):

```python
def _review_state(events: list[ReviewEvent]) -> ReviewState | None:
    """The decision the review events amount to: a return (even one whose rerun is still being
    created) over the latest accept; None when nobody reviewed the run."""
    returned = next((e for e in events if e.action == ReviewAction.RETURN.value), None)
    if returned is not None:
        return ReviewState(
            decision=ReviewDecision.RETURNED,
            at=returned.at,
            actor=returned.actor,
            child_run_id=str(returned.child_run_id) if returned.child_run_id else None,
        )
    accepted = next((e for e in reversed(events) if e.action == ReviewAction.ACCEPT.value), None)
    if accepted is None:
        return None
    return ReviewState(decision=ReviewDecision.ACCEPTED, at=accepted.at, actor=accepted.actor)
```

`_progress` gains a keyword parameter and passes it through:

```python
def _progress(run: Run, stages: list, review: ReviewState | None = None) -> RunProgress:
    return RunProgress(
        ...existing fields...,
        review=review,
    )
```

`run_progress`:

```python
async def run_progress(db: Database, run_id: uuid.UUID) -> RunProgress:
    async with db.session() as s:
        run = await runs.get_run_brief(s, run_id)
        # Review events exist only for completed runs (review_run checks), so a live run's
        # progress polls pay nothing for this (R-M9-1).
        events = []
        if run.state == RunState.COMPLETED.value:
            events = await runs.load_review_events(s, run_id)
        return _progress(run, await runs.load_stages(s, run_id), _review_state(events))
```

- [ ] **Step 4: Run the engine suite**

Run: `make test-engine` and `cd engine && uv run ruff check . && uv run ruff format --check .`
Expected: all pass.

- [ ] **Step 5: API test**

In `api/tests/test_runs.py::test_review_accept_and_return`, after the `accept` assertions (line 101) add:

```python
        shown = (await api.client.get(f"/api/runs/{run['run_id']}")).json()["review"]
        assert shown["decision"] == "accepted" and shown["actor"] == "ana"
        assert shown["child_run_id"] is None
```

and after `assert events[1].child_run_id == uuid.UUID(child["run_id"])` (line 126):

```python
        shown = (await api.client.get(f"/api/runs/{run['run_id']}")).json()["review"]
        assert shown["decision"] == "returned" and shown["child_run_id"] == child["run_id"]
        assert child["review"] is None
```

In `test_start_run_queues_one_job` (line 13) add `and run["review"] is None` to the first assertion.

- [ ] **Step 6: Regenerate the schema and types**

Run: `make schema` then `make test-api`.
Expected: `schema/openapi.json` and `schema/run-progress.schema.json` gain `ReviewState`/`ReviewDecision` and the `review` field; `web/src/api/schema.d.ts` gains the matching types; `test_committed_openapi_matches_the_app` and `test_every_screen_has_its_routes` pass (no route changed).

- [ ] **Step 7: Web types and fixtures**

`web/src/api/types.ts`: after `export type ReviewResult = S["ReviewResult"];` add

```ts
export type ReviewState = S["ReviewState"];
export type ReviewDecision = S["ReviewDecision"];
```

`web/src/test/fixtures.ts` `runProgress()` (line 46): add `review: null,` after `export_error: null,`.

Run: `cd web && pnpm lint && pnpm test`
Expected: clean and green (nothing reads `review` yet).

- [ ] **Step 8: Commit**

```bash
git add engine/corelata/schema/progress.py engine/corelata/schema/__init__.py engine/corelata/store/runs.py engine/corelata/service.py engine/tests/test_service.py api/tests/test_runs.py schema/openapi.json schema/run-progress.schema.json web/src/api/schema.d.ts web/src/api/types.ts web/src/test/fixtures.ts
git commit -F <scratchpad file>   # "feat: RunProgress.review carries the review decision of a completed run (CRL-15)"
```

If `make schema` touched other files under `schema/` (it rewrites every exported JSON schema), add those too, after checking the diff is only formatting or the new field.

---

### Task 5: The review and progress screens reflect server state (CRL-15, web)

**Files:**
- Modify: `web/src/api/runs.ts` (`useCancelRun`, `useReview`), `web/src/api/events.ts` (`exact: true`), `web/src/pages/review/ReviewActions.tsx`, `web/src/pages/review/ReviewPage.tsx`, `web/src/pages/run/RunOutcome.tsx`
- Test: `web/src/api/runs.test.tsx`, `web/src/pages/review/ReviewActions.test.tsx`, `web/src/pages/review/ReviewPage.test.tsx`, `web/src/pages/run/RunOutcome.test.tsx`, `web/src/pages/run/RunPage.test.tsx`

**Interfaces:**
- Consumes: `RunProgress.review` (`ReviewState | null | undefined`, Task 4).
- Produces: `ReviewActions({ runId, review }: { runId: string; review: ReviewState | null })`.

- [ ] **Step 1: Failing tests**

In `web/src/pages/review/ReviewActions.test.tsx`, replace the test `"accepts, then disables both actions; shows a conflict (test_accept_and_conflict)"` (lines 44-61) with:

```tsx
const accepted = {
  decision: "accepted" as const,
  at: "2026-10-15T10:00:00Z",
  actor: "ana",
  child_run_id: null,
};

it("accepts, then shows the server's decision and disables both actions (test_accept_and_conflict)", async () => {
  let decided = false;
  server.use(
    http.get(`*/api/runs/${RUN_ID}`, () =>
      HttpResponse.json(
        runProgress({
          state: "completed",
          status: "clean",
          iteration: 1,
          review: decided ? accepted : null,
        }),
      ),
    ),
    http.get(`*/api/runs/${RUN_ID}/report`, () => HttpResponse.text(reportHtml)),
    http.get(`*/api/runs/${RUN_ID}/exports/report.json`, () => HttpResponse.json(reportJson)),
    http.get(`*/api/runs/${RUN_ID}/trace`, () =>
      HttpResponse.json({ detail: "x" }, { status: 500 }),
    ),
    http.get(`*/api/runs/${RUN_ID}/findings`, () => HttpResponse.json([])),
  );
  let posted: unknown;
  server.use(
    http.post(`*/api/runs/${RUN_ID}/review`, async ({ request }) => {
      posted = await request.json();
      decided = true;
      return HttpResponse.json({ action: "accept", child: null });
    }),
  );
  const { user } = renderApp(`/runs/${RUN_ID}/review`);
  await user.click(await screen.findByRole("button", { name: "Accept" }));
  expect(await screen.findByRole("status", { name: "Review decision" })).toHaveTextContent(
    "Accepted",
  );
  expect(posted).toEqual({ action: "accept", note: "" });
  expect(screen.getByRole("button", { name: "Accept" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Return with note" })).toBeDisabled();
});

it("a reload shows an accepted run as decided", async () => {
  serveCompleted({ review: accepted });
  renderApp(`/runs/${RUN_ID}/review`);
  expect(await screen.findByRole("status", { name: "Review decision" })).toHaveTextContent(
    "Accepted",
  );
  expect(screen.getByRole("button", { name: "Accept" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Return with note" })).toBeDisabled();
  expect(screen.queryByRole("link", { name: "Open the rerun" })).not.toBeInTheDocument();
});

it("a returned run shows the decision and links to the rerun", async () => {
  serveCompleted({
    review: {
      decision: "returned",
      at: "2026-10-15T10:00:00Z",
      actor: "ana",
      child_run_id: "77777777-7777-7777-7777-777777777777",
    },
  });
  renderApp(`/runs/${RUN_ID}/review`);
  expect(await screen.findByRole("status", { name: "Review decision" })).toHaveTextContent(
    "Returned",
  );
  expect(screen.getByRole("link", { name: "Open the rerun" })).toHaveAttribute(
    "href",
    "/runs/77777777-7777-7777-7777-777777777777",
  );
  expect(screen.getByRole("button", { name: "Accept" })).toBeDisabled();
});
```

and change `serveCompleted` (lines 7-19) to take overrides:

```tsx
function serveCompleted(overrides: Parameters<typeof runProgress>[0] = {}) {
  server.use(
    http.get(`*/api/runs/${RUN_ID}`, () =>
      HttpResponse.json(
        runProgress({ state: "completed", status: "clean", iteration: 1, ...overrides }),
      ),
    ),
    ...the four other handlers unchanged...
  );
}
```

In `web/src/pages/review/ReviewPage.test.tsx` add:

```tsx
it("shows a failed report.json on the header and falls back to a plain title", async () => {
  server.use(
    http.get(`*/api/runs/${RUN_ID}`, () =>
      HttpResponse.json(runProgress({ state: "completed", status: "clean", iteration: 1 })),
    ),
    http.get(`*/api/runs/${RUN_ID}/report`, () => HttpResponse.text(reportHtml)),
    http.get(`*/api/runs/${RUN_ID}/exports/report.json`, () =>
      HttpResponse.json({ detail: "report.json unavailable" }, { status: 500 }),
    ),
    ...tabHandlers,
  );
  renderApp(`/runs/${RUN_ID}/review`);
  expect(await screen.findByRole("heading", { name: "Report" })).toBeInTheDocument();
  // The Provenance tab reports the same failure below; the header's alert comes first.
  expect(screen.getAllByRole("alert")[0]).toHaveTextContent("report.json unavailable");
});
```

In `web/src/api/runs.test.tsx` add:

```tsx
it("a cancel invalidates the project's run list and the run itself", async () => {
  const { projectKeys } = await import("./projects");
  const client = makeQueryClient({ retry: false });
  const pid = runProgress().project_id;
  client.setQueryData(projectKeys.runs(pid), []);
  server.use(
    http.post(`*/api/runs/${RUN_ID}/cancel`, () =>
      HttpResponse.json(runProgress({ state: "drafting", cancel_requested: true })),
    ),
  );
  const cancel = renderHook(() => useCancelRun(RUN_ID), {
    wrapper: ({ children }) => <Providers client={client}>{children}</Providers>,
  });
  cancel.result.current.mutate();
  await waitFor(() => expect(cancel.result.current.data?.cancel_requested).toBe(true));
  expect(client.getQueryState(projectKeys.runs(pid))?.isInvalidated).toBe(true);
  expect(client.getQueryData(runKeys.one(RUN_ID))).toMatchObject({ cancel_requested: true });
});

it("an accepted review refreshes the run so the decision comes from the server", async () => {
  const client = makeQueryClient({ retry: false });
  client.setQueryData(runKeys.one(RUN_ID), runProgress({ state: "completed" }));
  server.use(
    http.post(`*/api/runs/${RUN_ID}/review`, () => HttpResponse.json({ action: "accept", child: null })),
  );
  const review = renderHook(() => useReview(RUN_ID), {
    wrapper: ({ children }) => <Providers client={client}>{children}</Providers>,
  });
  review.result.current.mutate({ action: "accept", note: "" });
  await waitFor(() => expect(review.result.current.data?.action).toBe("accept"));
  expect(client.getQueryState(runKeys.one(RUN_ID))?.isInvalidated).toBe(true);
});
```

(Import `projectKeys` statically at the top instead of the dynamic import if the module graph allows; `runs.ts` already imports it, so it does.)

In `web/src/pages/run/RunOutcome.test.tsx` add:

```tsx
it("says when a cancel arrived too late to stop a delivered report", async () => {
  renderTerminal({ state: "completed", status: "clean", cancel_requested: true });
  expect(
    await screen.findByText(/A cancel was requested, but the run had already finished/),
  ).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Review the report" })).toBeInTheDocument();
});
```

In `web/src/pages/run/RunPage.test.tsx`, in `"ends on a deleted event with the not-found message"`, capture the client and assert the exact invalidation:

```tsx
  const { queryClient } = renderApp(`/runs/${RUN_ID}`);
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");
  ...existing steps...
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["runs", RUN_ID], exact: true });
```

- [ ] **Step 2: Run the web tests to see them fail**

Run: `cd web && pnpm test -- --run src/pages/review src/api/runs.test.tsx src/pages/run`
Expected: the new tests fail (no `review` prop, no invalidation, no sentence, `exact` missing); the rest pass.

- [ ] **Step 3: Implement**

`web/src/api/runs.ts`:

```ts
export function useCancelRun(runId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      unwrap<RunProgress>(
        client.POST("/api/runs/{run_id}/cancel", { params: { path: { run_id: runId } } }),
      ),
    onSuccess: (run) => {
      queryClient.setQueryData(runKeys.one(runId), run);
      void queryClient.invalidateQueries({ queryKey: projectKeys.runs(run.project_id) });
    },
  });
}

export function useReview(runId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { action: ReviewAction; note: string }) =>
      unwrap<ReviewResult>(
        client.POST("/api/runs/{run_id}/review", { params: { path: { run_id: runId } }, body }),
      ),
    onSuccess: (result) => {
      // The decision now lives on the server (RunProgress.review): refetch the run, exactly.
      void queryClient.invalidateQueries({ queryKey: runKeys.one(runId), exact: true });
      if (result.child) {
        queryClient.setQueryData(runKeys.one(result.child.run_id), result.child);
        void queryClient.invalidateQueries({ queryKey: projectKeys.runs(result.child.project_id) });
      }
    },
  });
}
```

`web/src/api/events.ts` line 50: `void queryClient.invalidateQueries({ queryKey: runKeys.one(runId), exact: true });`

`web/src/pages/review/ReviewActions.tsx`: import `Link` from `react-router` and `type ReviewState` from `../../api/types`; the component becomes

```tsx
export function ReviewActions({ runId, review }: { runId: string; review: ReviewState | null }) {
  const send = useReview(runId);
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const noteId = useId();
  const busy = send.isPending;
  const decided = review !== null;

  function accept() {
    send.mutate({ action: "accept", note: "" });
  }

  function sendReturn() {
    send.mutate(
      { action: "return", note: note.trim() },
      {
        onSuccess: (result) => {
          setOpen(false);
          setNote("");
          if (result.child) navigate(`/runs/${result.child.run_id}`);
        },
      },
    );
  }
  ...
      <button type="button" onClick={accept} disabled={busy || decided}>Accept</button>
      <button ... disabled={busy || decided}>Return with note</button>
      {review ? (
        <>
          <span
            role="status"
            aria-label="Review decision"
            className={`badge ${review.decision === "accepted" ? "ok" : "warn"}`}
          >
            {review.decision === "accepted" ? "Accepted" : "Returned"}
          </span>
          {review.child_run_id ? (
            <Link to={`/runs/${review.child_run_id}`}>Open the rerun</Link>
          ) : null}
        </>
      ) : null}
```

Remove the `decided` state and the `onSuccess: () => setDecided("accepted")`. Rename the mutation variable if `send` collides with the existing `send()` function (the sketch above renames the function to `sendReturn`; keep `onConfirm={sendReturn}`).

`web/src/pages/review/ReviewPage.tsx`: `<ReviewActions runId={runId} review={run.data?.review ?? null} />`, and inside `<header className="row">` after the open-findings span: `{json.error ? <ErrorMessage error={json.error} /> : null}`.

`web/src/pages/run/RunOutcome.tsx`, `completed` case, after the status paragraph:

```tsx
          {progress.cancel_requested ? (
            <p className="muted">
              A cancel was requested, but the run had already finished its last stage, so the
              report was delivered.
            </p>
          ) : null}
```

- [ ] **Step 4: Run the web suite and lint**

Run: `cd web && pnpm lint && pnpm test`
Expected: clean; all tests pass; coverage ≥ 95% on all four measures.

- [ ] **Step 5: Commit**

```bash
git add web/src/api/runs.ts web/src/api/events.ts web/src/pages/review/ReviewActions.tsx web/src/pages/review/ReviewPage.tsx web/src/pages/run/RunOutcome.tsx web/src/api/runs.test.tsx web/src/pages/review/ReviewActions.test.tsx web/src/pages/review/ReviewPage.test.tsx web/src/pages/run/RunOutcome.test.tsx web/src/pages/run/RunPage.test.tsx
git commit -F <scratchpad file>   # "feat(web): review and progress screens reflect server state (CRL-15)"
```

---

### Task 6: Run list paging and the accessibility polish (CRL-15, web)

**Files:**
- Modify: `web/src/api/projects.ts` (`useRuns`, `RUN_PAGE`, `RUN_LIMIT_MAX`), `web/src/pages/new/RunList.tsx`, `web/src/pages/new/NewRunPage.tsx` (line 113, `key`), `web/src/pages/run/StageTimeline.tsx`, `web/src/pages/review/AuditTab.tsx`
- Test: `web/src/pages/new/RunList.test.tsx`, `web/src/pages/run/StageTimeline.test.tsx`, `web/src/pages/review/AuditTab.test.tsx`

**Interfaces:**
- Produces: `useRuns(projectId: string | null, limit = RUN_PAGE)` with query key `[...projectKeys.runs(id), limit]` (invalidation by the `projectKeys.runs(id)` prefix keeps working); `RUN_PAGE = 50`, `RUN_LIMIT_MAX = 500`; `STATUS_TEXT: Record<RowStatus, string>` in `StageTimeline.tsx`.

- [ ] **Step 1: Failing tests**

`web/src/pages/new/RunList.test.tsx`: add

```tsx
function many(n: number, from = 0) {
  return Array.from({ length: n }, (_, i) => ({
    ...runSummary,
    run_id: `${String(from + i).padStart(8, "0")}-0000-0000-0000-000000000000`,
    value_statement: `Statement ${from + i}`,
  }));
}

it("pages the run list fifty at a time up to the API's ceiling", async () => {
  const limits: string[] = [];
  server.use(
    http.get("*/api/projects", () => HttpResponse.json([project])),
    http.get(`*/api/projects/${project.id}/sources`, () => HttpResponse.json([])),
    http.get("*/api/runs", ({ request }) => {
      const limit = new URL(request.url).searchParams.get("limit")!;
      limits.push(limit);
      return HttpResponse.json(many(Math.min(Number(limit), 60)));
    }),
  );
  const { user } = renderApp(`/new?project=${project.id}`);
  const table = await screen.findByRole("table", { name: "Runs" });
  expect(within(table).getAllByRole("row")).toHaveLength(51);
  await user.click(screen.getByRole("button", { name: "Show more" }));
  await waitFor(() => expect(within(table).getAllByRole("row")).toHaveLength(61));
  expect(limits).toEqual(["50", "100"]);
  expect(screen.queryByRole("button", { name: "Show more" })).not.toBeInTheDocument();
});
```

(import `waitFor` from testing-library.) `web/src/pages/run/StageTimeline.test.tsx` line 77: change `expect(items[0]).toHaveTextContent("done");` to `expect(items[0]).toHaveTextContent("finished");` and add after it `expect(items[5]).toHaveTextContent("not started");`. In the `"shows a failed stage's error"` test add `expect(within(items[1]!).getByText(/model unreachable/)).toHaveAttribute("dir", "auto");`. Line 101 (`toHaveTextContent("Checking the valuerunning")`) concatenates the label, the sr-only text and the description; with spoken status it becomes `"Checking the valuein progressrunning"`, so replace that assertion with two: `toHaveTextContent("Checking the value")` and `toHaveTextContent("in progress")`.

`web/src/pages/review/AuditTab.test.tsx`: add

```tsx
it("shows a loading state for the rule titles instead of reflowing the table", async () => {
  server.use(
    http.get(`*/api/runs/${RUN_ID}/findings`, () => HttpResponse.json(findings)),
    http.get(`*/api/runs/${RUN_ID}/trace`, () => HttpResponse.json(runTrace)),
    http.get("*/api/packs/icd203-base/resolved", async () => {
      await new Promise((resolve) => setTimeout(resolve, 80));
      return HttpResponse.json(resolvedPack);
    }),
  );
  renderWithClient(<AuditTab runId={RUN_ID} />);
  expect(await screen.findByText(/Loading rule titles/)).toBeInTheDocument();
  expect(screen.queryByRole("table", { name: "Rules" })).not.toBeInTheDocument();
  expect(await screen.findByRole("table", { name: "Verifiable rules" })).toBeInTheDocument();
  expect(within(screen.getByRole("table", { name: "Verifiable rules" })).getByText("Sourcing is clear"))
    .toHaveAttribute("dir", "auto");
});
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd web && pnpm test -- --run src/pages/new/RunList.test.tsx src/pages/run/StageTimeline.test.tsx src/pages/review/AuditTab.test.tsx`
Expected: the three new/changed expectations fail.

- [ ] **Step 3: Implement**

`web/src/api/projects.ts`: import `keepPreviousData` from `@tanstack/react-query`; replace `useRuns` (lines 93-102):

```ts
export const RUN_PAGE = 50;
export const RUN_LIMIT_MAX = 500; // the API's ceiling (`GET /api/runs` limit le=500)

/** A project's runs, newest first; `limit` grows by pages (R-M9-8). The key keeps the
 * `projectKeys.runs(id)` prefix, so mutations invalidate every page at once. */
export function useRuns(projectId: string | null, limit: number = RUN_PAGE) {
  return useQuery({
    queryKey: [...projectKeys.runs(projectId ?? ""), limit] as const,
    queryFn: () =>
      unwrap<RunSummary[]>(
        client.GET("/api/runs", { params: { query: { project_id: projectId!, limit } } }),
      ),
    enabled: projectId !== null,
    placeholderData: keepPreviousData,
  });
}
```

`web/src/pages/new/RunList.tsx`:

```tsx
import { useState } from "react";
import { Link } from "react-router";
import { RUN_LIMIT_MAX, RUN_PAGE, useRuns } from "../../api/projects";
...
export function RunList({ projectId }: { projectId: string }) {
  const [limit, setLimit] = useState(RUN_PAGE);
  const runs = useRuns(projectId, limit);
  if (runs.error) return <ErrorMessage error={runs.error} />;
  if (!runs.data || runs.data.length === 0) return null;
  const more = runs.data.length >= limit && limit < RUN_LIMIT_MAX;
  return (
    <section aria-label="Runs" className="panel">
      <h2>Runs</h2>
      <table aria-label="Runs">...unchanged...</table>
      {more ? (
        <button
          type="button"
          className="secondary"
          disabled={runs.isFetching}
          onClick={() => setLimit(Math.min(limit + RUN_PAGE, RUN_LIMIT_MAX))}
        >
          Show more
        </button>
      ) : null}
      {!more && limit >= RUN_LIMIT_MAX ? (
        <p className="muted">Showing the newest {RUN_LIMIT_MAX} runs.</p>
      ) : null}
    </section>
  );
}
```

`web/src/pages/new/NewRunPage.tsx` line 113: `<RunList key={projectId} projectId={projectId} />` so the page size resets when the project changes.

`web/src/pages/run/StageTimeline.tsx`:

```tsx
/** Spoken status for screen readers: the data-status token is for CSS. */
export const STATUS_TEXT: Record<RowStatus, string> = {
  done: "finished",
  failed: "failed",
  running: "in progress",
  pending: "not started",
};
...
          <span className="sr-only">{STATUS_TEXT[row.status]}</span>
          <span className="muted" dir="auto">
            {describe(row, progress)}
          </span>
```

`web/src/pages/review/AuditTab.tsx`: in `RuleTable` (lines 55-58) add `dir="auto"` to the `<strong>` and the muted rule-id span; in `AuditTab`:

```tsx
  const loadingTitles =
    trace.isPending || (pack.isPending && pack.fetchStatus === "fetching");
  ...
      {loadingTitles ? (
        <Loading what="Loading rule titles" />
      ) : pack.data ? (
        <>
          <RuleTable label="Verifiable rules" rows={rows.filter((r) => !r.advisory)} />
          <RuleTable label="Advisory rules" rows={rows.filter((r) => r.advisory)} />
        </>
      ) : (
        <RuleTable label="Rules" rows={rows} />
      )}
```

(`useResolvedPack(null, …)` is disabled, so `isPending` alone would show the loader forever when the trace failed; `fetchStatus === "fetching"` guards that. `Loading` is already imported.)

- [ ] **Step 4: Run the web suite and lint**

Run: `cd web && pnpm lint && pnpm test`
Expected: clean and green. `RunList.test.tsx`'s existing tests still pass (their handlers ignore `limit`).

- [ ] **Step 5: Commit**

```bash
git add web/src/api/projects.ts web/src/pages/new/RunList.tsx web/src/pages/new/NewRunPage.tsx web/src/pages/run/StageTimeline.tsx web/src/pages/review/AuditTab.tsx web/src/pages/new/RunList.test.tsx web/src/pages/run/StageTimeline.test.tsx web/src/pages/review/AuditTab.test.tsx
git commit -F <scratchpad file>   # "feat(web): page the run list; spoken stage status; Audit tab loading state (CRL-15)"
```

---

### Task 7: Discovery polling backs off; the resolved pack stays fresh longer (CRL-8, web)

**Files:**
- Modify: `web/src/api/discoveries.ts`, `web/src/api/packs.ts`
- Test: `web/src/api/discoveries.test.tsx`, `web/src/api/packs.test.tsx`

**Interfaces:**
- Produces: `discoveryPollInterval(view, error = null, polls = 0)`, `DISCOVERY_POLL_MAX_MS = 15_000`; `RESOLVED_PACK_STALE_MS = 600_000`.

- [ ] **Step 1: Failing tests**

`web/src/api/discoveries.test.tsx`: import `DISCOVERY_POLL_MAX_MS` and extend the first test:

```tsx
it("polls a discovery until it ends, backing off to a cap", () => {
  ...existing seven expectations...
  expect(discoveryPollInterval(undefined, null, 1)).toBe(DISCOVERY_POLL_MS);
  expect(discoveryPollInterval(undefined, null, 2)).toBe(2 * DISCOVERY_POLL_MS);
  expect(discoveryPollInterval(undefined, null, 3)).toBe(4 * DISCOVERY_POLL_MS);
  expect(discoveryPollInterval(undefined, null, 4)).toBe(8 * DISCOVERY_POLL_MS);
  expect(discoveryPollInterval(undefined, null, 5)).toBe(DISCOVERY_POLL_MAX_MS);
  expect(discoveryPollInterval(undefined, null, 40)).toBe(DISCOVERY_POLL_MAX_MS);
  expect(discoveryPollInterval(discoveryView({ state: "completed" }), null, 9)).toBe(false);
});

it("useDiscovery counts its polls for the backoff", async () => {
  let served = 0;
  server.use(
    http.get(`*/api/discoveries/${DISCOVERY_ID}`, () => {
      served += 1;
      return HttpResponse.json(discoveryView({ state: "running" }));
    }),
  );
  const client = makeQueryClient({ retry: false });
  const read = renderHook(() => useDiscovery(DISCOVERY_ID), {
    wrapper: ({ children }) => <Providers client={client}>{children}</Providers>,
  });
  await waitFor(() => expect(read.result.current.data?.state).toBe("running"));
  const query = client.getQueryCache().find({ queryKey: ["discoveries", DISCOVERY_ID] })!;
  const option = query.observers[0]!.options.refetchInterval as (q: typeof query) => unknown;
  expect(option(query)).toBe(DISCOVERY_POLL_MS); // one poll so far
  await read.result.current.refetch();
  expect(served).toBe(2);
  expect(option(query)).toBe(2 * DISCOVERY_POLL_MS);
});
```

`web/src/api/packs.test.tsx`: add

```tsx
it("keeps a resolved pack fresh for ten minutes (the Audit tab opens often)", async () => {
  server.use(http.get("*/api/packs/icd203-base/resolved", () => HttpResponse.json(resolvedPack)));
  const client = makeQueryClient({ retry: false });
  const resolved = renderHook(() => useResolvedPack("icd203-base", null), {
    wrapper: ({ children }) => <Providers client={client}>{children}</Providers>,
  });
  await waitFor(() => expect(resolved.result.current.data).toBeTruthy());
  const query = client.getQueryCache().find({ queryKey: ["packs", "icd203-base", "resolved", null] })!;
  expect(query.observers[0]!.options.staleTime).toBe(RESOLVED_PACK_STALE_MS);
  expect(RESOLVED_PACK_STALE_MS).toBe(10 * 60_000);
});
```

(import `RESOLVED_PACK_STALE_MS` from `./packs`.)

- [ ] **Step 2: Run them to see them fail**

Run: `cd web && pnpm test -- --run src/api/discoveries.test.tsx src/api/packs.test.tsx`
Expected: FAIL (missing exports; interval 1000 for every count).

- [ ] **Step 3: Implement**

`web/src/api/discoveries.ts`:

```ts
export const DISCOVERY_POLL_MS = 1000;
export const DISCOVERY_POLL_MAX_MS = 15_000;

/** 1 s, 2 s, 4 s, 8 s, then every 15 s (R-M9-9): a discovery that never ends costs little.
 * `polls` is how many answers (or failures) the query has had so far. */
export function discoveryPollInterval(
  view: DiscoveryView | undefined,
  error: Error | null = null,
  polls = 0,
): number | false {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false;
  if (view && (view.state === "completed" || view.state === "failed")) return false;
  return Math.min(DISCOVERY_POLL_MS * 2 ** Math.max(0, polls - 1), DISCOVERY_POLL_MAX_MS);
}
...
    refetchInterval: (query) =>
      discoveryPollInterval(
        query.state.data,
        query.state.error,
        query.state.dataUpdateCount + query.state.fetchFailureCount,
      ),
```

`web/src/api/packs.ts`:

```ts
/** The Audit tab resolves the run's pack on every review open; a customer edit shows within this
 * long (CRL-8). The pack listing (`usePacks`) keeps its minute: the New run screen picks from it. */
export const RESOLVED_PACK_STALE_MS = 10 * 60_000;
...
    staleTime: RESOLVED_PACK_STALE_MS,   // in useResolvedPack
```

- [ ] **Step 4: Run the web suite and lint**

Run: `cd web && pnpm lint && pnpm test`
Expected: clean and green.

- [ ] **Step 5: Commit**

```bash
git add web/src/api/discoveries.ts web/src/api/packs.ts web/src/api/discoveries.test.tsx web/src/api/packs.test.tsx
git commit -F <scratchpad file>   # "feat(web): discovery polling backs off; resolved packs stay fresh ten minutes (CRL-8)"
```

---

### Task 8: The frame's own CSP, the proxy guidance, and the pack-name check (CRL-16)

**Files:**
- Modify: `web/src/pages/review/frameBridge.ts` (`frameNonce`, `cspMeta`, `bridgeScript(nonce)`, `withBridge(html, nonce)`), `web/src/pages/review/ReportFrame.tsx` (unchanged call, comment)
- Modify: `docs/operator-guide.md` (section 6 after line 372; troubleshooting table)
- Modify: `engine/corelata/doctor.py` (`_pack_names`)
- Test: `web/src/pages/review/frameBridge.test.ts`, `web/src/pages/review/ReportFrame.test.tsx`, `engine/tests/test_doctor.py`

**Interfaces:**
- Consumes: `PACK_NAME_PATTERN` (Task 3).
- Produces: `frameNonce(): string`, `cspMeta(nonce: string): string`, `FRAME_CSP(nonce: string): string`, `bridgeScript(nonce?: string)`, `withBridge(html: string, nonce = frameNonce())`; doctor check named `pack names`.

- [ ] **Step 1: Failing web tests**

`web/src/pages/review/frameBridge.test.ts`: import `cspMeta`, `frameNonce`, `FRAME_CSP`; replace the two serialisation tests (lines 71-83) with

```ts
it("serialises the installer into the document before </body>, bound to the nonce", () => {
  const script = bridgeScript("n0nce+/=");
  expect(script.startsWith('<script nonce="n0nce+/=">')).toBe(true);
  expect(script).toContain("corelata:highlight");
  expect(script).toContain(JSON.stringify(HIGHLIGHT_CSS));
  expect(bridgeScript().startsWith("<script>")).toBe(true); // no nonce, no attribute
  const out = withBridge(reportHtml, "n0nce+/=");
  expect(out).toContain(`${script}</body>`);
  expect(out).toContain(`<head>${cspMeta("n0nce+/=")}`);
  expect(out.indexOf("<meta http-equiv")).toBeLessThan(out.indexOf("<style"));
  expect(withBridge("<p>no head or body</p>", "n")).toBe(
    `${cspMeta("n")}<p>no head or body</p>${bridgeScript("n")}`,
  );
});

it("locks the frame down: nothing loads, the bridge runs by nonce, inline styles stay", () => {
  expect(FRAME_CSP("abc")).toBe(
    "default-src 'none'; script-src 'nonce-abc'; style-src 'unsafe-inline'; img-src data:; connect-src 'none'",
  );
  expect(cspMeta("abc")).toBe(
    `<meta http-equiv="Content-Security-Policy" content="${FRAME_CSP("abc")}">`,
  );
  const a = frameNonce();
  const b = frameNonce();
  expect(a).not.toBe(b);
  expect(a).toMatch(/^[A-Za-z0-9+/]+=*$/); // base64: legal in a CSP nonce and an attribute
  expect(a.length).toBeGreaterThanOrEqual(22); // 128 bits
});

it("finds the closing tag by position in the original, whatever the case or characters", () => {
  const doc = "<html><body><p>İstanbul</p></BODY></html>"; // "İ" lowercases to two code units
  expect(withBridge(doc, "n")).toBe(
    `${cspMeta("n")}<html><body><p>İstanbul</p>${bridgeScript("n")}</BODY></html>`,
  );
});
```

`web/src/pages/review/ReportFrame.test.tsx`, first test: after `expect(srcdoc.indexOf("<script")).toBeLessThan(srcdoc.lastIndexOf("</body>"));` (adjust the existing `"<script>"` search to `"<script"`) add

```ts
  const policy = /nonce-([A-Za-z0-9+/=]+)'/.exec(srcdoc)![1];
  const onScript = /<script nonce="([^"]+)">/.exec(srcdoc)![1];
  expect(policy).toBe(onScript); // puts the same nonce in the policy and on the bridge
  expect(srcdoc.indexOf("<meta http-equiv=\"Content-Security-Policy\"")).toBeLessThan(
    srcdoc.indexOf("<script"),
  );
```

and rename the test to `"puts the report and the bridge into a scriptable frame with no origin and its own policy"`.

- [ ] **Step 2: Run them to see them fail**

Run: `cd web && pnpm test -- --run src/pages/review/frameBridge.test.ts src/pages/review/ReportFrame.test.tsx`
Expected: FAIL (missing exports; no meta tag).

- [ ] **Step 3: Implement the frame policy**

`web/src/pages/review/frameBridge.ts`, replace `bridgeScript` and `withBridge` (lines 42-57):

```ts
/** The frame's own policy (R-M9-6): nothing loads from anywhere, the bridge runs by nonce, the
 * report's stylesheet and the bridge's highlight style are inline. A site proxy's policy is
 * inherited on top of this one (docs/operator-guide.md, section 6). */
export const FRAME_CSP = (nonce: string) =>
  `default-src 'none'; script-src 'nonce-${nonce}'; style-src 'unsafe-inline'; img-src data:; connect-src 'none'`;

export function frameNonce(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return btoa(String.fromCharCode(...bytes));
}

export function cspMeta(nonce: string): string {
  return `<meta http-equiv="Content-Security-Policy" content="${FRAME_CSP(nonce)}">`;
}

/** The `<script>` that installs the bridge: it talks to `parent` and trusts only `parent`. */
export function bridgeScript(nonce?: string): string {
  const attr = nonce ? ` nonce="${nonce}"` : "";
  return (
    `<script${attr}>(${installFrameBridge.toString()})(document,` +
    ' function (m) { parent.postMessage(m, "*"); },' +
    ' function (h) { addEventListener("message", function (e) { if (e.source === parent) h(e.data); }); },' +
    ` ${JSON.stringify(HIGHLIGHT_CSS)});</script>`
  );
}

/** The report with its policy at the top of `<head>` (or at the very start when there is none)
 * and the bridge appended inside `<body>` (or at the end). */
export function withBridge(html: string, nonce: string = frameNonce()): string {
  const meta = cspMeta(nonce);
  const head = /<head\s*>/i.exec(html);
  const cut = head ? head.index + head[0].length : 0;
  const withMeta = html.slice(0, cut) + meta + html.slice(cut);
  const script = bridgeScript(nonce);
  const at = [...withMeta.matchAll(/<\/body\s*>/gi)].at(-1)?.index; // length-preserving search
  return at === undefined
    ? withMeta + script
    : withMeta.slice(0, at) + script + withMeta.slice(at);
}
```

`ReportFrame.tsx` needs no code change (`withBridge(html)` draws a fresh nonce per report); extend its header comment with "The document carries its own Content-Security-Policy (M9)".

- [ ] **Step 4: Run the web suite**

Run: `cd web && pnpm lint && pnpm test`
Expected: clean and green (`ReviewPage.test.tsx:98` reads the srcdoc for content only).

- [ ] **Step 5: Operator guide**

In `docs/operator-guide.md`, after line 372 ("…overwriting anything the client sent.") and before `## 7. Running it`, insert:

````markdown

### Content-Security-Policy

Corelata sends no `Content-Security-Policy` header of its own. The review screen shows the report
inside a sandboxed frame that carries its own policy (`default-src 'none'`, its one script bound by
a nonce, inline styles only), so nothing in a report can load or send anything.

If your proxy adds a `Content-Security-Policy` header to every response, the frame inherits that
policy too. A policy whose `script-src` or `style-src` lacks `'unsafe-inline'` blocks the frame's
script and the report's stylesheet: the report still shows, but clicking a claim no longer
highlights it, and the analyst sees no error. If a site policy is required, start from

```nginx
add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'self'" always;
```

and check in the browser's developer console (F12) on a review screen that no "Refused to execute
inline script" or "Refused to apply inline style" message appears.
````

In the troubleshooting table (line 563, after the 401 row) add:

```markdown
| Clicking a claim does not highlight it in the report; the console shows "Refused to execute inline script" | A proxy `Content-Security-Policy` without `'unsafe-inline'` reaches the report frame. See section 6, "Content-Security-Policy". |
```

Also in section 5 (line 287) change "`progress_poll_s` is how often the progress stream checks a run." to "`progress_poll_s` is how often the API checks a running report for its progress streams (once per run, however many analysts watch it)."

- [ ] **Step 6: Failing doctor test**

In `engine/tests/test_doctor.py::test_a_healthy_installation`, add `"pack names",` to the tuple of PASS checks (line 45-53). Append:

```python
async def test_unaddressable_pack_directories_are_a_warning(tmp_path, server):
    packs = tmp_path / "packs"
    for name in ("Customer_A", "team-east", "2nd.draft"):
        (packs / name).mkdir(parents=True)
        (packs / name / "pack.yaml").write_text(
            yaml.safe_dump({"name": "team-east", "version": "1.0", "extends": "icd203-base"}),
            encoding="utf-8",
        )
    path = _config(tmp_path, server.base_url, standards={"packs_dir": str(packs)})
    report = await run_doctor(path, probe=False)
    check = _by_name(report)["pack names"]
    assert check.status is CheckStatus.WARN
    assert "2nd.draft, Customer_A" in check.message and "team-east" not in check.message
    assert "lowercase letters, digits and hyphens" in check.fix
    assert report.ok  # a warning does not fail the installation
```

- [ ] **Step 7: Run it to see it fail**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=... uv run pytest tests/test_doctor.py --no-cov -k "pack_directories or healthy"`
Expected: FAIL with `KeyError: 'pack names'`

- [ ] **Step 8: The doctor check**

`engine/corelata/doctor.py`: import `PACK_NAME_PATTERN, list_packs` from `corelata.standards.loader` (check what the module already imports from there), add after line 80 `checks.append(_guard("pack names", lambda: _pack_names(cfg)))`, and after `_pack` (line 157):

```python
def _pack_names(cfg: CorelataConfig) -> DoctorCheck:
    """A pack directory the API cannot address loads fine but has no `/api/packs/{name}` routes,
    so the Audit tab shows rule ids instead of titles for runs on it (CRL-16, R-M9-7)."""
    bad = sorted(
        p.name for p in list_packs(cfg.standards.packs_dir) if not PACK_NAME_PATTERN.match(p.name)
    )
    if not bad:
        return _check("pack names", CheckStatus.PASS, "every pack directory is addressable")
    noun = "directory" if len(bad) == 1 else "directories"
    return _check(
        "pack names",
        CheckStatus.WARN,
        f"{len(bad)} pack {noun} cannot be addressed through the API: {', '.join(bad)}",
        "rename to lowercase letters, digits and hyphens (^[a-z0-9][a-z0-9-]*$) and point "
        "standards.default_pack at the new name",
    )
```

- [ ] **Step 9: Run the engine suite and lint**

Run: `make test-engine` and `cd engine && uv run ruff check . && uv run ruff format --check .`
Expected: all pass. If `test_a_healthy_installation` or another doctor test asserts the exact list or order of check names, update it.

- [ ] **Step 10: Commit**

```bash
git add web/src/pages/review/frameBridge.ts web/src/pages/review/ReportFrame.tsx web/src/pages/review/frameBridge.test.ts web/src/pages/review/ReportFrame.test.tsx docs/operator-guide.md engine/corelata/doctor.py engine/tests/test_doctor.py
git commit -F <scratchpad file>   # "feat: report frame carries its own CSP; proxy CSP guidance; doctor warns on unaddressable pack names (CRL-16)"
```

---

### Task 9: Docs

**Files:**
- Modify: `README.md` (new `## M9` section before `## Development`), `docs/superpowers/specs/2026-10-12-corelata-v1-design.md` (§10.1 and §10.3 amendments), `docs/m3-followups.md`, `docs/m4a-followups.md`, `docs/m4b-followups.md`, `docs/m7-followups.md` (closed markers)
- Create: `docs/m9-followups.md`

- [ ] **Step 1: README**

Insert before `## Development` (line 176):

```markdown
## M9: efficiency and review state

The last four triage tickets (CRL-8, 9, 15, 16): the report routes check the run's state before
loading anything, serve the stored file for the plain case and cache claim-id re-renders per run
and format; every progress stream on one run shares one database poller and the progress read
skips the run row's large JSON columns; the pack listing is re-read only when a pack file changes;
`GET /api/runs/{id}` carries the review decision of a completed run, so the review screen shows
"Accepted" or "Returned" (with a link to the rerun) after a reload, a cancel invalidates the
project's run list, the run list pages fifty at a time, and a cancel that arrived too late is
explained on the outcome; discovery polling backs off to 15 s; the report frame carries its own
Content-Security-Policy (bridge by nonce, nothing loads from anywhere) and the operator guide says
what a proxy policy must allow; `corelata doctor` warns about pack directories the API cannot
address.
```

- [ ] **Step 2: Spec amendments**

In §10.1, after the "M4a amendments" paragraph (ends line 376 "…re-renders from the stored record."), add:

```markdown

M9 amendments: `GET /runs/{id}` carries `review` for a completed run (`decision` accepted or
returned, `at`, `actor`, `child_run_id` for a return); a live run's progress carries `null`. The
report route checks the run's state before loading anything and caches claim-id re-renders per
run and format for the life of the process. Every `GET /runs/{id}/events` stream on one run
shares one database poller. `GET /packs` is re-read only when a file under the pack directories
changes; `/packs/{name}/...` still read on every call.
```

In §10.3, after "The Sources tab shows each source's SHA-256 (M7)." add:

```markdown
The report frame's document carries its own Content-Security-Policy (`default-src 'none'`, the
bridge by nonce, inline styles only; M9). The review screen derives "Accepted" / "Returned" from
`GET /runs/{id}`'s `review`; the run list on the New run screen pages fifty at a time; discovery
polling backs off to 15 s (M9).
```

- [ ] **Step 3: Follow-up files**

Append ` — **closed in M9** (CRL-n)` to each closed line, in the style of the existing M8 markers:

- `docs/m3-followups.md` line 54-55 (`corelata status` and `run_progress` read…): CRL-8.
- `docs/m4a-followups.md` lines 41-42 (pack names): CRL-16; 43-44 (docx re-render temp file): CRL-9; 46-48 (report routes load the full RunRecord): CRL-9; 58-59 (events polls per stream): CRL-8; 60 (`GET /api/packs/*` reads…): CRL-8.
- `docs/m4b-followups.md` line 58 (Audit tab reflows): CRL-15; 59 (`dir="auto"` missing): CRL-15; 62 (discovery polling backoff): CRL-8; 63 (`useCancelRun`): CRL-15; 64-65 (`exact: true`): CRL-15; 67 (`json.error`): CRL-15; 68 (note persists): CRL-15; 69 (Accepted is local): CRL-15; 70 (sr-only token): CRL-15; 71 (RunList 100): CRL-15; 78 (Audit tab fetches the live pack): CRL-8.
- `docs/m7-followups.md` lines 32-34 (in-frame CSP): CRL-16.

Leave line 60 of `docs/m4b-followups.md` (no loading state while a claim's evidence loads) and line 61 (`onStreamFailed` ref) open: they are not part of these tickets.

- [ ] **Step 4: `docs/m9-followups.md`**

```markdown
# M9 follow-ups

## Divergences from Coglossa

- `ProgressFeed` (one poller per run for the SSE streams), `RenderCache` and `PackIndex` on the
  API context — **backport** (CGL-18): Coglossa's events route polls per stream the same way.
- `runs.get_run_brief` (deferred JSON columns for progress reads) — **backport**.

## Spec deviations

- §10.1: none; `review` on `GET /runs/{id}` and the caches are recorded as M9 amendments.

## Should fix soon

- `RunProgress.review` is read from the review events on every progress call for a completed
  run (one indexed query); a `review_state` column on `run`, written by `review_run`, would make
  it free.
- `ProgressFeed` polls; LISTEN/NOTIFY from the worker would make the stream event-driven and
  remove `api.progress_poll_s`.
- `pack_dirs_signature` stats every file under both pack directories on every `GET /api/packs`
  and every name check; a customer directory with hundreds of files turns that into a measurable
  cost. A debounce (re-stat at most once a second) would bound it.
- The frame's `style-src 'unsafe-inline'` could become a hash of the template's `<style>` plus a
  nonce on the bridge's style element.
- The operator guide's sample proxy policy is a starting point, not a tested configuration; an
  e2e run behind a proxy that sets it would pin it.
- `ReviewActions` still allows a return after an accept (the server allows it); decide whether an
  accepted report should be returnable.

## Later

- Tests to add: `ProgressFeed` under a cancelled stream mid-`wait_for` (the `finally`
  unsubscribes; a direct test would pin it).
- Tests to add: `RenderCache` eviction under concurrent requests for 65 different runs.
- Offset or cursor paging for `GET /api/runs` once a project passes 500 runs.
- Discovery polling never gives up on a stuck discovery; the worker's stalled-job sweep is what
  ends it. A client-side ceiling (stop after 10 minutes with a message) is a UX question.
```

- [ ] **Step 5: Lint the docs are not code; run the quick checks**

Run: `make lint` (confirms nothing else moved).

- [ ] **Step 6: Commit**

```bash
git add README.md docs/superpowers/specs/2026-10-12-corelata-v1-design.md docs/m3-followups.md docs/m4a-followups.md docs/m4b-followups.md docs/m7-followups.md docs/m9-followups.md
git commit -F <scratchpad file>   # "docs: M9 README section, spec amendments, follow-ups closed and filed"
```

---

## Final verification (after the whole-branch review)

```bash
make lint
make test-engine
make test-api
cd web && pnpm test && cd ..
make e2e            # the Playwright journey clicks inside the real frame: the meta CSP must not break the bridge
```

CI must be green on all six jobs (engine, api, web, e2e, deploy-check, airgap) before the merge.
