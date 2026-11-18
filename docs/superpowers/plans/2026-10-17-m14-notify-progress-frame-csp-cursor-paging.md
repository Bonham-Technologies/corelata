# M14 Event-Driven Progress, Frame CSP Without Inline Styles, Cursor Paging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close Jira CRL-22, CRL-23 and CRL-24, the last M9 follow-ups (`docs/m9-followups.md`, triaged "later" on 2026-10-15). (1) The worker and the service announce every committed change to a run with `NOTIFY corelata_run, '<run_id>'` in the transaction that writes it; the API holds one `LISTEN` connection and `ProgressFeed` reads a run when it is announced, with a slow heartbeat as the fallback for a lost notification, and polls at `api.progress_poll_s` exactly as today while the connection is down (CRL-22). (2) The report frame's policy allows the report's stylesheet by its SHA-256 hash, computed at build time from the one file the engine renders it from, and the bridge's own style by the frame's nonce, so `style-src` carries no `'unsafe-inline'`; a Playwright journey runs behind a reverse proxy that adds the operator guide's sample policy, so the sample is pinned by a test (CRL-23). (3) `GET /api/runs` pages by a `before=<created_at>|<run_id>` cursor (keyset on `(created_at, id)`), `useRuns` loads the next page by cursor, and the 500-run ceiling note is gone (CRL-24).

**Architecture:** Engine: `store.runs.notify_run(s, run_id)` runs `SELECT pg_notify('corelata_run', '<id>')` in a savepoint after a flush, logging and swallowing its own failure; every write path that changes what `service.run_progress` returns calls it inside its transaction (the worker's claim, state changes, stage records, outcome and failures, the sweep, the service's cancel and queue-failure). API: a new `corelata_api/run_listener.py` (`RunListener`, psycopg 3 `AsyncConnection` in autocommit, `conn.notifies()`) runs as a task on the app lifespan and calls `ProgressFeed.notify(run_id)` / `set_listening(bool)`; each poller now waits on an `asyncio.Event` with a timeout (`heartbeat_s` while listening, `poll_s` otherwise). `GET /api/runs` reads `limit + 1` rows after the decoded cursor and answers `RunPage {runs, next_before}`; `useRuns` becomes a `useInfiniteQuery`. The report stylesheet moves from `report.html.j2` into `render/templates/report.css`, which `render_html` inlines byte for byte and a Vite plugin hashes into `virtual:report-style`; `FRAME_CSP` uses that hash plus the nonce, which `installFrameBridge` now sets on its `<style>`. `api/csp_proxy.py` (a small ASGI proxy over httpx) adds the guide's sample policy; `devstack.py --csp-proxy-port` starts it, and a second Playwright project runs `e2e/csp.spec.ts` through it.

**Tech Stack:** Python 3.12, SQLAlchemy 2 async + psycopg 3.3 (the engine's existing driver; no new dependency), FastAPI, httpx, uvicorn; React 19, TanStack Query 5 (`useInfiniteQuery`), Vite 7 (a local plugin), Vitest 3, msw 2, Playwright 1.56; Markdown docs.

**Spec:** `docs/superpowers/specs/2026-10-12-corelata-v1-design.md` — §8.3 (tables; no migration in M14), §10.1 (API: `GET /api/runs`, `GET /runs/{id}/events`, and their M4a/M9/M10 amendments), §10.3 (web: the run list and the report frame's policy, M9 amendment), §11 (`api.progress_poll_s`), §13 (Playwright). Ticket texts are Jira CRL-22, CRL-23, CRL-24. The plans that specified what this one changes: `docs/superpowers/plans/2026-10-15-m9-efficiency-and-review-state.md` (`ProgressFeed`, `useRuns`/`RunList`, `withBridge`/`FRAME_CSP`) and `docs/superpowers/plans/2026-10-15-m10-review-column-pack-index-cache-budget.md`.

## Global Constraints

- 95% branch coverage for `engine` and `api` (`--cov-fail-under=95`), `filterwarnings = ["error"]`; `ruff check` and `ruff format --check` clean (line length 100). Vitest 95% on lines, branches, functions and statements; `pnpm lint` (eslint, prettier, `tsc --noEmit`) clean.
- Python tests that touch Postgres run against the dev database (`make db-up`; `CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres`, the Makefile's `DB_URL`). A single test file: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/x.py --no-cov -q` (and the same from `api/`). Full gates: `make test-engine`, `make test-api`, `make test-web`, `make lint`, `make e2e`. Do not run the full pytest and Vitest suites concurrently.
- **API changes (R-M14-1, R-M14-4), and nothing else.** `GET /api/runs` gains the query parameter `before: str | None` (max length 100) and answers `RunPage {runs: RunSummary[], next_before: string | null}` instead of `RunSummary[]`; `limit` keeps `ge=1, le=500`, default 100. No other route or response model changes and no route is added: `api/tests/test_openapi.py::test_every_screen_has_its_routes` lists the same 22 paths and stays as it is. `make schema` changes exactly `schema/openapi.json` and `web/src/api/schema.d.ts` (the `RunPage` component, the `before` parameter, the list route's response and its description); `schema/*.json`, the engine's exported models, come out unchanged because `RunPage` lives in `api/corelata_api/routes/runs.py`. Commit both generated files with Task 3; `test_committed_openapi_matches_the_app`, `test_committed_schema_matches_models` and the `web` CI job enforce it.
- **Web changes.** `useRuns(projectId)` (no `limit` argument) is a `useInfiniteQuery` keyed `projectKeys.runs(id)`; `RUN_LIMIT_MAX` and the "Showing the newest 500 runs." note are removed; `RUN_PAGE = 50` stays. `FRAME_CSP`, `installFrameBridge` (a fifth parameter, `nonce`) and `bridgeScript` change; `withBridge`, `cspMeta` and `frameNonce` keep their signatures. `virtual:report-style` is new (declared in `web/src/report-style.d.ts`).
- **No migration and no config schema change.** `api.progress_poll_s` stays (`Field(1.0, gt=0, le=60)`); its meaning changes (R-M14-3) and the operator guide says so. `corelata doctor` is unchanged. The trace format does not change; `report.html` (stored and re-rendered) loses the newline after `<style>` (R-M14-11).
- `api/tests/test_reports.py::test_re_render_failures` monkeypatches `reports._render`; that name stays. `api/tests/test_system.py::test_doctor_is_healthy_against_the_fake_server` is untouched.
- Web tests mock every request with msw (`web/src/test/setup.ts` fails an unmocked one); poll intervals are read through `web/src/test/poll.ts`, never fake timers. Fixtures live in `web/src/test/fixtures.ts` (M14 adds `noRuns`). A loading state is held open by a deferred msw response the test resolves (`web/src/test/deferred.ts`), never by a real delay.
- Commit messages end with exactly these two lines, nothing else after them:
  `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`
  `Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK`
  Write the message to a uniquely named scratchpad file and `git commit -F FILE`. Never `git stash`. Never `git add .` (the SDD workspace is not ignored).
- Version stays `0.1.2` (`engine/pyproject.toml`, `tests/test_version.py`); the controller cuts 0.1.3 after the live rehearsal (R-M14-4).
- Rulings (record in the SDD ledger, carried here). R-M9-1 to R-M9-12, R-M10-1 to R-M10-10, R-M11-1 to R-M11-8, R-M12-1 to R-M12-10 and R-M13-1 to R-M13-12 (`docs/superpowers/plans/2026-10-17-m13-auditor-probe-source-enum-bench-debt.md`, `docs/m13-followups.md` and the earlier plans and follow-ups they cite) stay in force.
  - **R-M14-1 (CRL-24, keyset paging).** `GET /api/runs` keeps `project_id` and `limit` (default and maximum unchanged) and gains `before: str | None`, an opaque cursor the server issues: the last row's `(created_at, id)` encoded as `<created_at ISO-8601 UTC>|<run_id>`; the response model gains `next_before: str | None` (set when the page was full and more rows exist; `null` otherwise). Rows are ordered `(created_at DESC, id DESC)` and the cursor condition is the tuple comparison, so a tie on `created_at` cannot skip or repeat. A malformed cursor is 422. `useRuns` loads the next page by cursor and appends; `RUN_LIMIT_MAX` and the ceiling note go away; `RUN_PAGE` 50 stays. `make schema` regenerates `schema/openapi.json` and `web/src/api/schema.d.ts`; `test_every_screen_has_its_routes` lists the same 22 paths (no new route).
  - **R-M14-2 (CRL-23, frame CSP).** The frame template's `<style>` content is fixed per build: compute its SHA-256 at build or module-load time from the same string the frame uses (a single source of truth; do not hard-code a hash), emit `style-src 'sha256-<hash>'` plus the per-render nonce for the bridge's own `<style>` element (`'nonce-N'`), and drop `'unsafe-inline'` from `style-src`. If any inline `style=` attributes exist in the rendered report HTML, read `engine/corelata/render/html.py` and decide: either the renderer emits none (preferred; convert to classes) or the ruling cannot hold and you say so. Add a test that the policy string contains no `'unsafe-inline'` and that the hash matches the style block, and a Vitest test that the frame still applies the highlight (existing tests may cover it). End-to-end: a Playwright journey runs through a reverse proxy that adds the operator guide's sample `Content-Security-Policy` header to every response. Implement the proxy as a small Python ASGI app in `api/devstack.py` (an option such as `--csp-proxy-port`) or a sibling script under `api/`, forwarding to the dev stack and adding the header; no Docker in the e2e job. The sample policy in the guide becomes a constant the proxy imports (or reads from the guide via a test that asserts they match), so the guide's text is pinned by the test. The journey asserts the claim highlight works under the policy and that no CSP violation is reported (collect `securitypolicyviolation` events or console errors).
  - **R-M14-3 (CRL-22, event-driven progress).** The worker emits `NOTIFY corelata_run, '<run_id>'` in the same transaction as every run-row state change it commits (stage recorded, progress persisted, terminal state, cancellation; find every write path in `worker/execute.py` and the service and list them). The API lifespan holds one dedicated LISTEN connection in a background task; `ProgressFeed` wakes a run's poller on a notification for that run id and otherwise polls at a slow heartbeat (`api.progress_poll_s * 10`, capped at 30 s) as the fallback for a lost or unavailable LISTEN; when the LISTEN connection is down or the driver cannot LISTEN, the feed polls at `api.progress_poll_s` exactly as today and the listener reconnects with backoff (1, 2, 4, 8, max 30 s). `api.progress_poll_s` stays in the config (it is the fallback interval and the heartbeat base); the operator guide explains the new meaning. Terminal states are still delivered to every stream; the M9 guarantees (a stream joining right after a change cannot miss it; the final read) hold: write the tests that pin them under notifications. `corelata doctor` unchanged. The worker's NOTIFY must never fail a run: a NOTIFY error is logged and swallowed. If the engine's driver cannot do LISTEN asynchronously, say so and pick the smallest dependency that can (asyncpg or psycopg async), recorded as a ruling.
  - **R-M14-4 (scope and gates).** `make schema` changes only for CRL-24 (`openapi.json`, `schema.d.ts`); commit them with the route change. Engine and api coverage gates 95%, Vitest thresholds 95%, Playwright journeys stay green; `ci-status` is the required check. Spec amendments: §10.1 (runs paging, progress feed), §10.3 (frame CSP), §11 (proxy policy test); operator guide §6 and the troubleshooting row; README M14 section; `docs/m9-followups.md` items struck "— **closed in M14** (CRL-…)"; new `docs/m14-followups.md`. Version stays 0.1.2; the controller cuts 0.1.3 after a rehearsal.
  - How the plan applies them (from reading the code at 26d9cf4 and applying every task to a scratch copy of `engine/`, `api/` and `web/`: engine 859 passed, api 160 passed, web 168 Vitest passed, ruff and `pnpm lint` clean, `pnpm build` clean, `pnpm e2e` 6 passed including the new `csp-proxy` journey; the image's `web` stage built with the Task 5 Dockerfile):
    - R-M14-1: the cursor is `<created_at>|<run_id>` with the time as `created_at.astimezone(UTC).isoformat(timespec="microseconds")` and `+00:00` written `Z` (`2026-10-17T06:30:01.120000Z|6f1c…`): no `+` to mis-encode in a query string, microseconds as Postgres stores them. `service.run_cursor(summary)` encodes, `service.parse_run_cursor(cursor)` decodes (split at the last `|`, `datetime.fromisoformat`, must be time-zone aware, `uuid.UUID`); anything else raises `InvalidRequestError("invalid cursor 'before': pass the next_before of the previous page")`, which the existing handler answers 422 with that `detail`. The route reads `limit + 1` rows: the extra row says whether `next_before` is set, so a full last page answers `null` and the client asks no empty page. `store.runs.list_runs` orders `(created_at DESC, id DESC)` (it was `id ASC` within a tie) and filters `tuple_(Run.created_at, Run.id) < tuple_(*before)`. Postgres orders `uuid` bytewise, as Python orders `UUID`s, so tests can predict the tie order.
    - R-M14-2: the `<style>` block is not under `web/src`: it is in the engine's `render/templates/report.html.j2`, and the review frame shows the API's claim-id re-render of it (`GET /runs/{id}/report?format=html&with_claim_ids=true`, rendered by the running engine on every cache miss). The single source of truth is therefore a file, `engine/corelata/render/templates/report.css`: `render/html.py` reads its bytes at import and the template inlines them unescaped as `<style>{{ css }}</style>` (so the element's text is the file byte for byte), and `web/vite.config.ts` hashes the same file into the virtual module `virtual:report-style` at build time. The rendered report has no `style=` attributes (the template emits none; markdown is not rendered to HTML), so the ruling holds; an engine test pins both facts. The bridge's style gets the nonce through `installFrameBridge`'s new fifth parameter, which `bridgeScript` passes as a JSON string. The proxy is `api/csp_proxy.py` (sibling of `devstack.py`, development only); its `SAMPLE_POLICY` constant is checked against the guide by a pytest test, and the journey compares the header it receives with the policy it reads from the guide, so the guide's text is pinned twice.
    - R-M14-3: the engine's driver is psycopg 3 (`psycopg[binary]>=3.2`, 3.3.6 locked), whose `AsyncConnection.notifies()` LISTENs asynchronously: no new dependency. The write paths that change what `service.run_progress` returns, each now calling `runs.notify_run` inside its transaction: `worker/execute.py` `_begin` (the claim, and the cancel at job start), `DbObserver.state_changed`, `DbObserver.stage_recorded`, `execute_run`'s outcome transaction, both branches of `_fail_run`; `worker/sweep.py` `sweep_orphans` (one per run it fails); `service.py` `_mark_run_failed` (queue refused the job) and `cancel_run` (the flag, and the immediate end of a `created` run). A completed run makes 14 announcements (the claim, two per stage, the outcome). "Backoff 1, 2, 4, 8, max 30 s" is read as doubling capped at 30: `BACKOFF_S = (1, 2, 4, 8, 16, 30)`, the last repeating, reset after a successful `LISTEN`. "The driver cannot LISTEN" has no case to detect with psycopg (a pooler that swallows notifications connects fine; see the follow-ups); the down state is "not connected", during which the feed polls at `poll_s` and subscribes wait their first read exactly as before.
  - Rulings this plan adds:
    - **R-M14-5 (CRL-22, what is not announced).** Run creation, the review decision (`_store_review_state`) and deletions (`delete_project`, the purge) do not notify. A stream never watches a run before it exists, and a stream ends at the terminal state, so a review decision (completed runs only) reaches no stream; a progress page open on a run whose project is deleted says "deleted" at the next heartbeat. If wrong: that page is up to 30 s late; adding `notify_run` to those paths is one line each.
    - **R-M14-6 (CRL-22, how a notification cannot fail a run).** `notify_run` flushes first (so a failing write still fails where it did, not as a "notification" failure), then runs `pg_notify` inside `s.begin_nested()` and catches `SQLAlchemyError`, logging `run <id>: progress notification not sent: <reason>` at WARNING; the savepoint keeps the caller's transaction usable. A connection lost inside the savepoint still fails the commit afterwards, which is the existing `DB_ERRORS` path (the job is retried). One case cannot be swallowed in the same transaction: Postgres fails a commit when its notification queue is full (8 GB, only when a listening session holds a transaction open); the API's listener is autocommit. If wrong: a full queue fails worker commits; recorded under Later. Corrected by R-M14-15 after the whole-branch review: a lost connection inside the savepoint is re-raised (`DBAPIError.connection_invalidated`), because the swallowed error otherwise became a `PendingRollbackError` at commit, outside `DB_ERRORS`.
    - **R-M14-7 (CRL-22, the listener and the feed).** `RunListener(connect, feed, *, backoff=BACKOFF_S, sleep=asyncio.sleep)` in `api/corelata_api/run_listener.py`, on a dedicated connection outside the SQLAlchemy pool (`listen_connection(url)`: autocommit, `connect_timeout=CONNECT_TIMEOUT_S`, `application_name="corelata-api-listen"`), started by the lifespan as a task and cancelled before `feed.close()`; `create_app(..., listener_connect=listen_connection)` lets tests inject a connect. Log lines: `progress listener connected` (INFO), `progress listener lost the database: <reason>; polling every <poll_s> s, reconnecting in <delay> s` (WARNING), `progress listener failed` (an unexpected exception, with traceback), `progress listener ignored a notification that is not a run id`. `ProgressFeed` gains `notify(run_id)`, `set_listening(bool)`, `listening`, `poll_s`, `heartbeat_s`; `set_listening` wakes every poller on either transition (a change made while nobody listened is read at once; a lost connection goes back to `poll_s` without finishing a 30 s wait); while listening, `subscribe` wakes the poller (the notification of a change between the route's read and the subscription may already have been spent, M9's guarantee). The wake event is cleared before each read, so a notification during a read causes one more read and a burst costs one. If wrong: one read more per stream join while listening; nothing is missed.
    - **R-M14-8 (CRL-22, test support).** `corelata.testing.postgres` gains `RunChannel` and `open_run_channel(url)`, and the shared pytest plugin a `run_channel` fixture (a `LISTEN` connection on the test database). `api/tests/conftest.py::set_run_state` announces its change by default (`notify=False` to write without one), as the worker would; `make_api` takes `listener_connect`. If wrong: test helpers only.
    - **R-M14-9 (CRL-24, the page model).** `RunPage` is declared in `api/corelata_api/routes/runs.py` next to `ReviewResult`, not in `corelata.schema`, so the engine's exported schemas do not change (R-M14-4 allows only `openapi.json` and `schema.d.ts`); the cursor helpers live in `corelata.service` with `list_runs(..., before=)`, which keeps returning `list[RunSummary]` (every existing caller unchanged). `before` has `max_length=100` (a cursor is 64 characters). No index is added: the run table's `project_id` index plus a sort serves a page; a composite index is a Later item. If wrong: one model moves module; the generated client is identical.
    - **R-M14-10 (CRL-24, the run list).** `useRuns` is `useInfiniteQuery` with `initialPageParam: null`, `getNextPageParam: (last) => last.next_before` (TanStack 5 treats `null` as no next page), the first request without `before`; a mutation that invalidates `projectKeys.runs(id)` refetches every loaded page, each next page from the refetched page before it. `RunList` shows the error under the table when rows are already shown (a failed next page or refresh keeps the rows; Show more tries again), the error alone when nothing loaded; Show more is disabled while anything for the list is fetching. If wrong: a failed refresh now keeps stale rows on screen with the error under them instead of replacing them.
    - **R-M14-11 (CRL-23, the stylesheet file).** `report.css` is shipped as package data (`engine/pyproject.toml` artifacts gain `corelata/render/templates/*.css`; `deploy/tests/check-app-image.sh` checks it is in the image); the image's `web` build stage copies it to `/src/engine/corelata/render/templates/` before `pnpm build` (the `.dockerignore` allowlist already includes `engine/corelata/`). `html.py` reads it with `read_bytes().decode("utf-8")`, not `read_text()`, so newline translation cannot make the inlined text differ from the hashed bytes. The template changes from `<style>\n…</style>` to `<style>{{ css }}</style>`: `report.html` loses one newline (the golden `tests/render/golden/varna.html` is edited to match), so a pre-M14 run's stored `report.html` differs from its re-render by that byte. If wrong: a reviewer who wants the stored exports byte-identical across the upgrade adds the newline to the start of `report.css`.
    - **R-M14-12 (CRL-23, the proxy and the journey).** `api/csp_proxy.py` is not in the `corelata_api` package or the image and not under the coverage gate; `api/tests/test_csp_proxy.py` tests it (imports resolve because pytest puts `api/` on `sys.path`). It drops hop-by-hop headers and any upstream `Content-Security-Policy`, adds `SAMPLE_POLICY`, and streams bodies with `aiter_raw` so the progress stream passes live. `devstack.py` gains `--csp-proxy-port` (the proxy in front of the API) and `--progress-poll-s` (default 0.2, for the rehearsal). `web/playwright.config.ts` runs two projects against the one stack: `chromium` (every spec but `csp.spec.ts`, port 8765) and `csp-proxy` (`csp.spec.ts`, port 8766); the web server's readiness URL is the proxy's health. The CI `e2e` job is unchanged: `pnpm e2e` runs both projects. The journey proves the hash and the nonce, not only the absence of errors: it asserts the report body's computed `max-width` (`736px`, from the hashed stylesheet) and the highlight's computed background (`rgb(255, 243, 176)`, from the nonce-bound style); on the scratch copy a one-line change to `report.css` after the build failed it on both the computed style and the violation list. If wrong: test infrastructure only.
    - **R-M14-13 (docs).** The spec's §11 is Configuration, so its M14 amendment records `api.progress_poll_s`'s new meaning, and the proxy-policy journey is recorded where the spec describes the Playwright journeys (§13, as an indented M14 amendment under the Playwright bullet); §10.1 and §10.3 as the brief says. `docs/m10-followups.md` is not edited (its note on the 500-row ceiling test now applies to the 520-row paging test; `docs/m14-followups.md` says so). If wrong: placement only.

## Review Focus

1. **A stream that joins after the change it needs was already announced (and its notification spent on the other streams) must still get that change at once, not at the 30 s heartbeat; and every stream on a run must get the terminal state.** Pinned in Task 2 (`test_a_stream_joining_after_the_notification_was_spent_still_gets_the_change`, `test_a_cancel_shows_on_the_stream_at_once`).
2. **When the database restarts under a watched run, the stream must keep updating at `progress_poll_s` while the listener is down and go back to notifications after it reconnects, without the operator doing anything; a notification lost while the listener is up costs at most one heartbeat.** Pinned in Task 2 (`test_a_lost_connection_is_reported_and_reopened`, `test_when_the_listener_drops_the_feed_polls_at_poll_s_again`, `test_a_reconnect_reads_every_watched_run_once`, `test_with_the_listener_up_a_lost_notification_costs_one_heartbeat`).
3. **A notification that Postgres refuses must not fail the run or lose the write it was announcing.** Pinned in Task 1 (`test_a_failed_notification_is_logged_and_the_writes_still_commit`, `test_a_failed_notification_never_fails_a_run`).
4. **Paging a project while new runs arrive, and through runs created in the same microsecond (a sweep, a bulk return), must show every run exactly once.** Pinned in Task 3 (`test_a_run_created_while_paging_does_not_shift_the_next_page`, `test_list_runs_pages_by_cursor_through_ties_without_gaps`, `test_list_runs_pages_through_a_tie_without_skipping_or_repeating`).
5. **A next page that fails (the database blinks) must keep the rows already shown, say why, and let Show more try again; and an edited report stylesheet must never ship with a stale hash.** Pinned in Task 4 (`keeps the rows when the next page fails, and Show more tries again`) and Task 5 (`test_the_one_style_element_is_report_css_byte_for_byte_and_nothing_else_is_inline`, `hashes the engine's report stylesheet, the text of the report's one style element`), end to end in Task 6 (the journey's computed-style assertions).

---

## File structure

| Path | Responsibility |
|---|---|
| `engine/corelata/store/runs.py` | `RUN_CHANNEL`, `notify_run` (Task 1); `list_runs(..., before=)` keyset (Task 3). |
| `engine/corelata/worker/execute.py`, `worker/sweep.py`, `engine/corelata/service.py` | call `notify_run` on every progress write (Task 1); `service.list_runs(before=)`, `run_cursor`, `parse_run_cursor` (Task 3). |
| `engine/corelata/testing/postgres.py`, `testing/pytest_db.py` | `RunChannel`, `open_run_channel`, the `run_channel` fixture (Task 1). |
| `api/corelata_api/run_listener.py` (new) | `RunListener`, `listen_connection`, `BACKOFF_S`, `APPLICATION_NAME` (Task 2). |
| `api/corelata_api/progress_feed.py`, `app.py`, `context.py`, `routes/progress.py` | wake-ups, heartbeat, the listener task on the lifespan (Task 2). |
| `api/corelata_api/routes/runs.py` | `RunPage`, `before`, `next_before` (Task 3). |
| `schema/openapi.json`, `web/src/api/schema.d.ts` | regenerated by `make schema` (Task 3). |
| `web/src/api/projects.ts`, `api/types.ts`, `pages/new/RunList.tsx`, `test/fixtures.ts` | cursor paging in the run list (Task 4). |
| `engine/corelata/render/templates/report.css` (new), `report.html.j2`, `render/html.py`, `engine/pyproject.toml` | the stylesheet as one file (Task 5). |
| `web/vite.config.ts`, `web/src/report-style.d.ts` (new), `web/src/pages/review/frameBridge.ts` | the hash at build time, the frame's policy (Task 5). |
| `deploy/docker/app.Dockerfile`, `deploy/tests/check-app-image.sh` | the stylesheet in the web build stage and in the image check (Task 5). |
| `api/csp_proxy.py` (new), `api/devstack.py`, `web/playwright.config.ts`, `web/e2e/csp.spec.ts` (new) | the proxy and the journey (Task 6). |
| tests: `engine/tests/worker/test_notify.py` (new), `engine/tests/store/test_runs.py`, `engine/tests/test_service.py`, `engine/tests/render/test_html.py`, `engine/tests/render/golden/varna.html`, `api/tests/conftest.py`, `api/tests/test_progress_feed.py`, `api/tests/test_run_listener.py` (new), `api/tests/test_progress.py`, `api/tests/test_runs.py`, `api/tests/test_integration.py`, `api/tests/test_csp_proxy.py` (new), `web/src/api/projects.test.tsx`, `web/src/pages/new/{RunList,ProjectPicker,NewRunPage,SourcesPanel}.test.tsx`, `web/src/pages/review/frameBridge.test.ts` | the tickets' tests. |
| `README.md`, spec, `docs/operator-guide.md`, `docs/m9-followups.md`, `docs/m14-followups.md` (new) | docs (Task 7). |

Order: Task 1 before Task 2 (the API tests use `runs.notify_run`) and before Task 3 (both edit `store/runs.py` and `service.py`); Task 3 before Task 4 (the regenerated client types); Task 5 before Task 6 (the journey checks the hash). Task 7 documents all six.

---

### Task 1: The engine announces every committed run change on `corelata_run` (CRL-22, part 1)

**Files:**
- Modify: `engine/corelata/store/runs.py` (imports lines 5-14; after `_BATCH = 1000`, line 46), `engine/corelata/worker/execute.py` (`DbObserver` lines 68-93, `_begin` lines 118-155, `_fail_run` lines 210-229, `execute_run` lines 268-289), `engine/corelata/worker/sweep.py` (imports line 11-13; `sweep_orphans` lines 41-52), `engine/corelata/service.py` (`_mark_run_failed` lines 79-87, `cancel_run` lines 360-372), `engine/corelata/testing/postgres.py` (whole file), `engine/corelata/testing/pytest_db.py` (lines 11-12; append)
- Create: `engine/tests/worker/test_notify.py`

**Interfaces:**
- Consumes: `store.db.error_reason(e) -> str`; the existing `tests/worker/conftest.py` helpers `submit(svc, *texts, project="p", **opts) -> uuid.UUID` and `drain(svc) -> int` and the `services`/`fake_backend` fixtures.
- Produces: `corelata.store.runs.RUN_CHANNEL = "corelata_run"`; `corelata.store.runs._NOTIFY` (the `pg_notify` statement, used by an API test); `async def notify_run(s: AsyncSession, run_id: uuid.UUID) -> None` (call it inside the caller's transaction after its writes; never raises a database error of its own); `corelata.testing.postgres.RunChannel` with `async received(wait_s: float = 0.3) -> list[str]`; `corelata.testing.postgres.open_run_channel(url: str)` (async context manager yielding a `RunChannel`); pytest fixture `run_channel`. Log line `run <id>: progress notification not sent: <reason>` (logger `corelata.store`, WARNING).

- [ ] **Step 1: Failing tests**

Create `engine/tests/worker/test_notify.py`:

```python
"""Every committed change to a run's progress is announced on the run channel (CRL-22,
R-M14-3): `NOTIFY corelata_run, '<run_id>'` in the transaction that writes it."""

import pytest
from sqlalchemy import select, text

from corelata import service
from corelata.llm.types import PermanentBackendError
from corelata.schema import RunState
from corelata.store import runs
from corelata.store.models import Run
from corelata.worker import execute
from corelata.worker.sweep import sweep_orphans
from tests.worker.conftest import drain, submit


@pytest.fixture
def announced(monkeypatch) -> list[str]:
    """The run state each `notify_run` call announces, as its own transaction sees it."""
    states: list[str] = []
    real = runs.notify_run

    async def spy(s, run_id):
        states.append(await s.scalar(select(Run.state).where(Run.id == run_id)))
        await real(s, run_id)

    monkeypatch.setattr(runs, "notify_run", spy)
    return states


async def test_a_notification_is_delivered_when_its_transaction_commits(services, run_channel):
    run_id = await submit(services)
    assert await run_channel.received() == []  # creating and queueing a run announces nothing
    async with services.db.session() as s, s.begin():
        await runs.notify_run(s, run_id)
        await runs.notify_run(s, run_id)
        assert await run_channel.received(0.1) == []  # nothing before the commit
    assert await run_channel.received() == [str(run_id)]  # once per transaction


async def test_a_rolled_back_transaction_announces_nothing(services, run_channel):
    run_id = await submit(services)
    with pytest.raises(RuntimeError):
        async with services.db.session() as s, s.begin():
            await runs.notify_run(s, run_id)
            raise RuntimeError("rolled back")
    assert await run_channel.received() == []


async def test_a_failed_notification_is_logged_and_the_writes_still_commit(
    services, run_channel, monkeypatch, caplog
):
    run_id = await submit(services)
    monkeypatch.setattr(runs, "RUN_CHANNEL", "")  # Postgres refuses an empty channel name
    async with services.db.session() as s, s.begin():
        (await runs.get_run(s, run_id, lock=True)).iteration = 1
        await runs.notify_run(s, run_id)
    assert (await service.run_progress(services.db, run_id)).iteration == 1
    assert await run_channel.received() == []
    assert f"run {run_id}: progress notification not sent: " in caplog.text
    assert "channel name cannot be empty" in caplog.text


async def test_a_failed_notification_never_fails_a_run(services, monkeypatch, caplog):
    monkeypatch.setattr(runs, "RUN_CHANNEL", "")
    run_id = await submit(services)
    await drain(services)
    assert (await service.run_progress(services.db, run_id)).state is RunState.COMPLETED
    assert caplog.text.count("progress notification not sent") == 14  # every one, logged


async def test_a_run_announces_every_change_it_commits(services, run_channel, announced):
    run_id = await submit(services)
    await drain(services)
    progress = await service.run_progress(services.db, run_id)
    assert progress.state is RunState.COMPLETED and len(progress.stages) == 6
    # the claim; then per stage the pipeline's state change and the stage's record; the outcome
    assert announced == [
        "ingesting",
        *[state for stage in progress.stages for state in (stage.stage, stage.stage)],
        "completed",
    ]
    assert await run_channel.received() == [str(run_id)] * len(announced)


async def test_a_failed_run_announces_its_failure(services, fake_backend, run_channel, announced):
    fake_backend.script("gate", PermanentBackendError("down"), PermanentBackendError("down"))
    run_id = await submit(services)
    await drain(services)
    assert (await service.run_progress(services.db, run_id)).state is RunState.FAILED
    assert announced[-1] == "failed"
    assert await run_channel.received() == [str(run_id)] * len(announced)


async def test_an_internal_error_announces_the_failure_on_both_paths(
    services, monkeypatch, announced
):
    async def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(execute, "run_report", boom)
    run_id = await submit(services)
    await drain(services)
    assert (await service.run_progress(services.db, run_id)).state is RunState.FAILED
    assert announced == ["ingesting", "failed"]

    announced.clear()
    real = runs.add_llm_calls

    async def broken(*args, **kwargs):  # the leftover calls cannot be written
        monkeypatch.setattr(runs, "add_llm_calls", real)
        raise RuntimeError("write failed")

    monkeypatch.setattr(runs, "add_llm_calls", broken)
    other = await submit(services, project="q")
    await drain(services)
    assert (await service.run_progress(services.db, other)).state is RunState.FAILED
    assert announced == ["ingesting", "failed"]


async def test_cancelling_announces_the_flag_and_the_ending(services, announced):
    queued = await submit(services)
    assert await service.cancel_run(services.db, queued) is RunState.CANCELLED
    assert announced == ["cancelled"]

    announced.clear()
    running = await submit(services, project="q")
    assert await execute._begin(services, running) is not None
    assert await service.cancel_run(services.db, running) is RunState.INGESTING
    assert announced == ["ingesting", "ingesting"]  # the claim, then the flag

    announced.clear()
    flagged = await submit(services, project="r")
    async with services.db.session() as s, s.begin():
        (await runs.get_run(s, flagged, lock=True)).cancel_requested = True  # still created
    await execute.execute_run(services, flagged)
    assert announced == ["cancelled"]  # the worker ends it at job start


class _DownQueue:
    async def defer(self, task: str, *, lock: str | None = None, **kwargs: str) -> None:
        raise ConnectionRefusedError("connection refused")


async def test_a_run_that_could_not_be_queued_announces_its_failure(services, announced):
    services.queue = _DownQueue()
    with pytest.raises(ConnectionRefusedError):
        await submit(services)
    assert announced == ["failed"]


async def test_the_sweep_announces_each_run_it_fails(services, run_channel):
    ids = [await submit(services), await submit(services, project="q")]
    async with services.db.session() as s, s.begin():
        await s.execute(text("UPDATE run SET created_at = now() - interval '10 minutes'"))
    failed, _ = await sweep_orphans(services.db, grace_s=120)
    assert sorted(failed) == sorted(ids)
    assert sorted(await run_channel.received()) == sorted(str(i) for i in ids)
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/worker/test_notify.py --no-cov -q`
Expected: every test errors with `fixture 'run_channel' not found` or fails with `AttributeError: module 'corelata.store.runs' has no attribute 'notify_run'`.

- [ ] **Step 3: The test channel**

Replace `engine/corelata/testing/postgres.py` with:

```python
"""Throwaway Postgres databases for tests. A test session creates one database from the admin
URL in CORELATA_TEST_DATABASE_URL, migrates it and drops it at the end; `truncate_all` empties
it between tests. Copied from Coglossa."""

import contextlib
import uuid
from collections.abc import AsyncIterator

import psycopg
from psycopg import sql
from sqlalchemy import text
from sqlalchemy.engine import make_url

from corelata.store.db import Database, to_libpq_url
from corelata.store.models import Base
from corelata.store.runs import RUN_CHANNEL

TEST_DB_ENV = "CORELATA_TEST_DATABASE_URL"
PROCRASTINATE_TABLES = (
    "procrastinate_events",
    "procrastinate_periodic_defers",
    "procrastinate_jobs",
    "procrastinate_workers",
)


def create_test_database(admin: str) -> str:
    name = f"corelata_test_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(to_libpq_url(admin), autocommit=True, connect_timeout=10) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    return make_url(admin).set(database=name).render_as_string(hide_password=False)


def drop_test_database(admin: str, url: str) -> None:
    name = make_url(url).database
    with psycopg.connect(to_libpq_url(admin), autocommit=True, connect_timeout=10) as conn:
        conn.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
        )


async def truncate_all(db: Database) -> None:
    tables = [t.name for t in Base.metadata.sorted_tables] + list(PROCRASTINATE_TABLES)
    async with db.engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"))


class RunChannel:
    """A LISTEN connection on the run channel (CRL-22): what the worker and the service
    announced, in commit order. `open_run_channel` makes one."""

    def __init__(self, conn: psycopg.AsyncConnection) -> None:
        self._conn = conn

    async def received(self, wait_s: float = 0.3) -> list[str]:
        """The run ids notified since the last call, waiting `wait_s` for any still in flight."""
        return [n.payload async for n in self._conn.notifies(timeout=wait_s)]


@contextlib.asynccontextmanager
async def open_run_channel(url: str) -> AsyncIterator[RunChannel]:
    async with await psycopg.AsyncConnection.connect(
        to_libpq_url(url), autocommit=True, connect_timeout=10
    ) as conn:
        await conn.execute(sql.SQL("LISTEN {}").format(sql.Identifier(RUN_CHANNEL)))
        yield RunChannel(conn)
```

In `engine/corelata/testing/pytest_db.py`, the `TYPE_CHECKING` block (lines 11-12) becomes:

```python
if TYPE_CHECKING:
    from corelata.store.db import Database
    from corelata.testing.postgres import RunChannel
```

and append after the `db` fixture:

```python


@pytest.fixture
async def run_channel(pg_url) -> AsyncIterator["RunChannel"]:
    """A LISTEN connection on the run channel, open for the test (CRL-22)."""
    from corelata.testing.postgres import open_run_channel

    async with open_run_channel(pg_url) as channel:
        yield channel
```

- [ ] **Step 4: `notify_run`**

In `engine/corelata/store/runs.py`, the imports (lines 5-14) become:

```python
import hashlib
import logging
import uuid
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from sqlalchemy import delete, null, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer
```

Between the `corelata.schema` import block and the `corelata.store.models` import block add `from corelata.store.db import error_reason` (ruff's isort puts it before `corelata.store.models`). Replace

```python
_BATCH = 1000


class NotFoundError(LookupError):
    """A requested row does not exist; the message is safe to show to a user."""
```

with

```python
log = logging.getLogger("corelata.store")

_BATCH = 1000

# The channel every change to a run's progress is announced on; the payload is the run id. The
# API's progress listener LISTENs on it (CRL-22, R-M14-3).
RUN_CHANNEL = "corelata_run"
_NOTIFY = text("SELECT pg_notify(:channel, :payload)")


class NotFoundError(LookupError):
    """A requested row does not exist; the message is safe to show to a user."""


async def notify_run(s: AsyncSession, run_id: uuid.UUID) -> None:
    """Announce a change to the run in the caller's transaction: Postgres delivers
    `NOTIFY corelata_run, '<run_id>'` to every listener when the transaction commits, never if
    it rolls back, and once however often one transaction calls this. Call it after the
    transaction's writes to the run. The flush comes first, so a failing write still fails here;
    the notification itself runs in a savepoint, and its failure is logged and swallowed: a
    progress stream falls back to its heartbeat, a run never fails for it (R-M14-3)."""
    await s.flush()
    try:
        async with s.begin_nested():
            await s.execute(_NOTIFY, {"channel": RUN_CHANNEL, "payload": str(run_id)})
    except SQLAlchemyError as e:
        log.warning(
            "run %s: progress notification not sent: %s",
            run_id,
            error_reason(e),
            extra={"run_id": str(run_id)},
        )
```

(`RUN_CHANNEL` is read at call time on purpose: the failure tests set it to `""`.)

- [ ] **Step 5: Every write path calls it**

In `engine/corelata/worker/execute.py`:

- The `DbObserver` docstring becomes `"""The pipeline's observer for a queued run: short transactions between model calls, each` / `announcing the change on the run channel when it commits (CRL-22)."""` (two lines, the second indented four spaces).
- In `state_changed`, after `run.state = record.state.value` add `await runs.notify_run(s, self.run_id)` (inside the `async with`).
- In `stage_recorded`, after `await runs.add_llm_calls(s, self.run_id, self.calls_saved, new, stage=result.stage)` add `await runs.notify_run(s, self.run_id)` (inside the `async with`, before `self.stages_saved += 1`).
- In `_begin`, the cancel branch becomes

```python
        if run.cancel_requested:
            run.state, run.finished_at = RunState.CANCELLED.value, utcnow()
            await runs.notify_run(s, run_id)
            return None
```

  and directly before `return _Inputs(` add `        await runs.notify_run(s, run_id)` (after the `if live != run.config_hash:` block, at the transaction's indentation).
- In `_fail_run`, in both `async with` blocks, after the `if RunState(run.state) not in TERMINAL_STATES:` statement add `await runs.notify_run(s, run_id)` at the `if`'s indentation.
- In `execute_run`, after the `for name, data in files.items():` loop (still inside `async with svc.db.session() as s, s.begin():`) add `                await runs.notify_run(s, run_id)`.

In `engine/corelata/worker/sweep.py`, add `from corelata.store import runs` after `from corelata.schema import TERMINAL_STATES, DiscoveryState, RunState`, and inside `if run_ids:`, after the `await s.execute(update(Run)...)` statement, add

```python
            for run_id in run_ids:
                await runs.notify_run(s, run_id)
```

In `engine/corelata/service.py`, in `_mark_run_failed` after `run.finished_at = utcnow()` add `        await runs.notify_run(s, run_id)`; in `cancel_run` replace

```python
        if state is RunState.CREATED:
            run.state = RunState.CANCELLED.value
            run.finished_at = utcnow()
        return RunState(run.state)
```

with

```python
        if state is RunState.CREATED:
            run.state = RunState.CANCELLED.value
            run.finished_at = utcnow()
        await runs.notify_run(s, run_id)  # the flag shows on the progress page at once
        return RunState(run.state)
```

- [ ] **Step 6: Run the tests**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/worker/test_notify.py --no-cov -q`
Expected: `10 passed`.

Run: `cd engine && uv run ruff check . && uv run ruff format --check . && make -C .. test-engine`
Expected: ruff clean; `849 passed`, coverage at least 95%.

- [ ] **Step 7: Commit**

```bash
cat > <scratchpad>/m14-task1-commit.txt <<'EOF'
feat: announce every committed run change on corelata_run (CRL-22)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git add engine/corelata/store/runs.py engine/corelata/worker/execute.py engine/corelata/worker/sweep.py engine/corelata/service.py engine/corelata/testing/postgres.py engine/corelata/testing/pytest_db.py engine/tests/worker/test_notify.py
git commit -F <scratchpad>/m14-task1-commit.txt
```

---

### Task 2: One LISTEN connection wakes the progress streams (CRL-22, part 2)

**Files:**
- Create: `api/corelata_api/run_listener.py`, `api/tests/test_run_listener.py`
- Modify: `api/corelata_api/progress_feed.py` (whole file), `api/corelata_api/app.py` (imports lines 4-32; `create_app` lines 61-101), `api/corelata_api/context.py` (line 30), `api/corelata_api/routes/progress.py` (docstring lines 1-3), `api/tests/conftest.py` (imports line 18; `make_api` lines 86-101; `set_run_state` lines 170-181)
- Test: `api/tests/test_progress_feed.py` (append), `api/tests/test_progress.py` (imports lines 1-9; append)

**Interfaces:**
- Consumes: Task 1's `corelata.store.runs.RUN_CHANNEL`, `runs.notify_run`, `runs._NOTIFY`; `corelata.store.db.CONNECT_TIMEOUT_S`, `to_libpq_url`, `error_reason`.
- Produces: `corelata_api.progress_feed.ProgressFeed` with `notify(run_id: uuid.UUID) -> None`, `set_listening(listening: bool) -> None`, properties `listening: bool`, `poll_s: float`, `heartbeat_s: float` (`min(poll_s * HEARTBEAT_FACTOR, HEARTBEAT_MAX_S)`, `HEARTBEAT_FACTOR = 10`, `HEARTBEAT_MAX_S = 30.0`); constructor unchanged (`ProgressFeed(fetch, poll_s)`). `corelata_api.run_listener`: `APPLICATION_NAME = "corelata-api-listen"`, `BACKOFF_S = (1.0, 2.0, 4.0, 8.0, 16.0, 30.0)`, `Connect = Callable[[], Awaitable[psycopg.AsyncConnection]]`, `listen_connection(url: str) -> Connect`, `RunListener(connect, feed, *, backoff=BACKOFF_S, sleep=asyncio.sleep)` with `async run() -> None` (runs until cancelled). `create_app(..., listener_connect: Callable[[str], Connect] = listen_connection)`. Test helpers: `api/tests/conftest.py::set_run_state(db, run_id, state, *, notify=True)`, `make_api(..., listener_connect=None, **overrides)`; `tests/test_run_listener.py::until(condition, timeout_s=5.0)`.

- [ ] **Step 1: Failing tests**

Append to `api/tests/test_progress_feed.py`:

```python


# --- notifications (CRL-22, R-M14-3)


def test_the_heartbeat_is_ten_polls_capped_at_thirty_seconds():
    fetch, _ = scripted("gating")
    assert ProgressFeed(fetch, poll_s=1.0).heartbeat_s == 10.0
    assert ProgressFeed(fetch, poll_s=5.0).heartbeat_s == 30.0
    assert ProgressFeed(fetch, poll_s=5.0).poll_s == 5.0


async def test_a_notification_reads_the_run_at_once():
    fetch, calls = scripted("gating", "drafting", "completed")
    feed = ProgressFeed(fetch, poll_s=1.0)  # a 10 s heartbeat: every read below is a wake-up
    feed.set_listening(True)
    q = feed.subscribe(RUN, progress("created"))  # a subscription reads at once
    assert [u.state for u in await drain(q, 1)] == ["gating"]
    feed.notify(RUN)
    assert [u.state for u in await drain(q, 1)] == ["drafting"]
    feed.notify(RUN)
    assert [u.state for u in await drain(q, 1)] == ["completed"]
    await asyncio.sleep(0.02)
    assert calls["n"] == 3 and feed.active == 0


async def test_notifications_during_a_read_cost_one_more_read():
    release = asyncio.Event()
    reads: list[int] = []

    async def fetch(run_id):
        reads.append(1)
        if len(reads) == 1:
            await release.wait()
            return progress("gating")
        return progress("completed")

    feed = ProgressFeed(fetch, poll_s=1.0)
    feed.set_listening(True)
    q = feed.subscribe(RUN, progress("created"))
    while not reads:
        await asyncio.sleep(0)
    for _ in range(5):
        feed.notify(RUN)  # the run changes five times while the first read is in flight
    release.set()
    assert [u.state for u in await drain(q, 2)] == ["gating", "completed"]
    assert len(reads) == 2


async def test_a_stream_joining_after_the_notification_was_spent_still_gets_the_change():
    fetch, calls = scripted("gating", "drafting", "drafting", "completed")
    feed = ProgressFeed(fetch, poll_s=1.0)
    feed.set_listening(True)
    q1 = feed.subscribe(RUN, progress("created"))
    assert [u.state for u in await drain(q1, 1)] == ["gating"]
    feed.notify(RUN)  # the run moved to drafting; only q1 was watching
    assert [u.state for u in await drain(q1, 1)] == ["drafting"]
    q2 = feed.subscribe(RUN, progress("gating"))  # its own read predates the change
    assert [u.state for u in await drain(q2, 1)] == ["drafting"]  # well before the heartbeat
    assert q1.empty()  # q1 is not shown drafting twice
    feed.notify(RUN)
    assert [u.state for u in await drain(q1, 1)] == ["completed"]  # every stream gets the end
    assert [u.state for u in await drain(q2, 1)] == ["completed"]
    assert calls["n"] == 4


async def test_with_the_listener_up_a_lost_notification_costs_one_heartbeat():
    fetch, calls = scripted("gating", "completed")
    feed = ProgressFeed(fetch, poll_s=0.05)  # heartbeat 0.5 s
    feed.set_listening(True)
    q = feed.subscribe(RUN, progress("created"))
    assert [u.state for u in await drain(q, 1)] == ["gating"]
    await asyncio.sleep(0.15)
    assert calls["n"] == 1  # no read at poll_s while the listener is up
    assert [u.state for u in await drain(q, 1)] == ["completed"]  # the heartbeat read


async def test_when_the_listener_drops_the_feed_polls_at_poll_s_again():
    fetch, calls = scripted(*(["gating"] * 1000))
    feed = ProgressFeed(fetch, poll_s=0.02)  # heartbeat 0.2 s
    feed.set_listening(True)
    q = feed.subscribe(RUN, progress("created"))
    await drain(q, 1)
    feed.set_listening(False)  # reads once at once, then every poll_s
    await asyncio.sleep(0.3)
    assert calls["n"] >= 5  # about 15; the heartbeat alone would have read once
    await feed.close()


async def test_a_reconnect_reads_every_watched_run_once():
    fetch, calls = scripted("gating", "completed")
    feed = ProgressFeed(fetch, poll_s=5.0)  # neither the poll nor the heartbeat comes soon
    q1 = feed.subscribe(RUN, progress("created"))
    q2 = feed.subscribe(uuid.uuid4(), progress("created"))
    await asyncio.sleep(0.02)
    assert calls["n"] == 0  # listener down: the first read waits for poll_s, as before
    feed.set_listening(True)  # changes made while nobody listened are read now
    assert [u.state for u in await drain(q1, 1)] == ["gating"]
    assert [u.state for u in await drain(q2, 1)] == ["completed"]
    feed.set_listening(True)  # no change, no read
    await asyncio.sleep(0.02)
    assert calls["n"] == 2
    await feed.close()


def test_a_notification_for_an_unwatched_run_and_a_repeated_state_change_nothing():
    fetch, calls = scripted("gating")
    feed = ProgressFeed(fetch, poll_s=1.0)
    feed.notify(uuid.uuid4())
    feed.set_listening(False)
    assert not feed.listening and feed.active == 0 and calls["n"] == 0
```

Create `api/tests/test_run_listener.py`:

```python
import asyncio
import contextlib
import logging
import uuid
from types import SimpleNamespace

import psycopg
from corelata.store import runs
from corelata.store.db import to_libpq_url

from corelata_api.progress_feed import ProgressFeed
from corelata_api.run_listener import (
    APPLICATION_NAME,
    BACKOFF_S,
    RunListener,
    listen_connection,
)
from tests.test_progress_feed import RUN, drain, progress, scripted


async def until(condition, timeout_s: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while not condition():
        assert asyncio.get_running_loop().time() < deadline, "condition not met in time"
        await asyncio.sleep(0.01)


class Delays:
    """A sleep that records what the listener waits and returns at once."""

    def __init__(self) -> None:
        self.waited: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.waited.append(seconds)
        await asyncio.sleep(0)


@contextlib.asynccontextmanager
async def listening(connect, feed, sleep=asyncio.sleep):
    task = asyncio.create_task(RunListener(connect, feed, sleep=sleep).run())
    try:
        yield task
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def announce(db, payload) -> None:
    async with db.session() as s, s.begin():
        if isinstance(payload, uuid.UUID):
            await runs.notify_run(s, payload)
        else:
            await s.execute(runs._NOTIFY, {"channel": runs.RUN_CHANNEL, "payload": payload})


async def test_a_notification_wakes_the_runs_poller(db, pg_url, caplog):
    caplog.set_level(logging.INFO, logger="corelata.api")
    fetch, calls = scripted("gating", "completed")
    feed = ProgressFeed(fetch, poll_s=5.0)  # poll 5 s, heartbeat 30 s: only a wake-up is fast
    async with listening(listen_connection(pg_url), feed):
        await until(lambda: feed.listening)
        q = feed.subscribe(RUN, progress("created"))
        assert [u.state for u in await drain(q, 1)] == ["gating"]  # the subscription's read
        await announce(db, "not-a-run-id")
        await announce(db, uuid.uuid4())  # another run: nobody watches it
        await announce(db, RUN)
        assert [u.state for u in await drain(q, 1)] == ["completed"]
    assert calls["n"] == 2
    assert "progress listener connected" in caplog.text
    assert "progress listener ignored a notification that is not a run id" in caplog.text
    assert not feed.listening  # cancelled: the feed is told


async def test_a_lost_connection_is_reported_and_reopened(db, pg_url, caplog):
    caplog.set_level(logging.INFO, logger="corelata.api")
    fetch, _ = scripted("gating")
    feed = ProgressFeed(fetch, poll_s=5.0)
    delays = Delays()
    async with listening(listen_connection(pg_url), feed, sleep=delays):
        await until(lambda: feed.listening)
        async with await psycopg.AsyncConnection.connect(
            to_libpq_url(pg_url), autocommit=True
        ) as admin:
            await admin.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE application_name = %s AND datname = current_database()",
                (APPLICATION_NAME,),
            )
        await until(lambda: delays.waited == [1.0] and feed.listening)
    assert "progress listener lost the database: " in caplog.text
    assert "; polling every 5.0 s, reconnecting in 1.0 s" in caplog.text
    assert caplog.text.count("progress listener connected") == 2


async def test_an_unreachable_database_is_retried_with_backoff(caplog):
    fetch, _ = scripted("gating")
    feed = ProgressFeed(fetch, poll_s=1.0)
    delays = Delays()
    attempts = []

    async def refused():
        attempts.append(1)
        if len(attempts) == 3:
            raise RuntimeError("driver bug")  # not a database error: logged with its traceback
        raise OSError("connection refused")

    async with listening(refused, feed, sleep=delays):
        await until(lambda: len(delays.waited) >= 8)
    assert delays.waited[:8] == [1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0, 30.0]
    assert BACKOFF_S == (1.0, 2.0, 4.0, 8.0, 16.0, 30.0)
    assert not feed.listening
    assert (
        "progress listener lost the database: connection refused; polling every 1.0 s, "
        "reconnecting in 1.0 s"
    ) in caplog.text
    assert "progress listener failed" in caplog.text
    assert "progress listener lost the database: RuntimeError; " in caplog.text


class _EndingConnection:
    """A connection whose notification stream ends on its own after one notification."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def execute(self, query) -> None:
        return None

    async def notifies(self):
        yield SimpleNamespace(payload=str(RUN))


async def test_a_notification_stream_that_ends_is_a_lost_connection(caplog):
    fetch, _ = scripted("gating")
    feed = ProgressFeed(fetch, poll_s=1.0)
    delays = Delays()

    async def connect():
        return _EndingConnection()

    async with listening(connect, feed, sleep=delays):
        await until(lambda: len(delays.waited) >= 2)
    assert delays.waited[:2] == [1.0, 1.0]  # each connect succeeded, so no backoff builds up
    assert "progress listener lost the database: the notification stream ended" in caplog.text
```

In `api/tests/test_progress.py`, the imports (lines 1-9) become:

```python
import asyncio
import json
import time
import uuid

import psycopg
from corelata.store import runs
from corelata.store.db import to_libpq_url
from sqlalchemy.exc import OperationalError

from corelata_api.routes import progress as progress_module
from corelata_api.run_listener import APPLICATION_NAME
from tests.conftest import set_run_state, start_run
from tests.test_run_listener import until
```

and append:

```python


# --- event-driven streams (CRL-22, R-M14-3)


async def test_a_stream_follows_the_notifications_not_the_poll(make_api):
    async with make_api(api={"progress_poll_s": 5.0}) as api:  # poll 5 s, heartbeat 30 s
        await until(lambda: api.app.state.ctx.progress.listening)
        run = await start_run(api)
        finisher = asyncio.create_task(_finish_later(api.db, run["run_id"]))
        started = time.monotonic()
        response = await api.client.get(f"/api/runs/{run['run_id']}/events")
        await finisher
        elapsed = time.monotonic() - started
    assert [d["state"] for _, d in _events(response.text)] == ["created", "gating", "completed"]
    assert elapsed < 3.0  # a poll would have taken at least 5 s


async def test_a_cancel_shows_on_the_stream_at_once(make_api):
    async with make_api(api={"progress_poll_s": 5.0}) as api:
        await until(lambda: api.app.state.ctx.progress.listening)
        run = await start_run(api)
        await set_run_state(api.db, run["run_id"], "drafting")

        async def cancel_then_stop():
            await asyncio.sleep(0.3)
            response = await api.client.post(f"/api/runs/{run['run_id']}/cancel")
            assert response.json()["cancel_requested"] is True
            await asyncio.sleep(0.1)
            await set_run_state(api.db, run["run_id"], "cancelled")

        canceller = asyncio.create_task(cancel_then_stop())
        response = await asyncio.wait_for(
            api.client.get(f"/api/runs/{run['run_id']}/events"), timeout=3.0
        )
        await canceller
    seen = [(d["state"], d["cancel_requested"]) for _, d in _events(response.text)]
    assert seen == [("drafting", False), ("drafting", True), ("cancelled", True)]


async def _refused():
    raise OSError("connection refused")


async def test_without_the_listener_the_stream_polls_at_progress_poll_s(make_api, caplog):
    async with make_api(listener_connect=lambda url: _refused) as api:  # poll 0.02 s
        run = await start_run(api)

        async def finish():  # changes nobody announces: only the poll can see them
            await asyncio.sleep(0.2)
            await set_run_state(api.db, run["run_id"], "gating", notify=False)
            await asyncio.sleep(0.2)
            await set_run_state(api.db, run["run_id"], "completed", notify=False)

        finisher = asyncio.create_task(finish())
        response = await asyncio.wait_for(
            api.client.get(f"/api/runs/{run['run_id']}/events"), timeout=3.0
        )
        await finisher
        assert not api.app.state.ctx.progress.listening
    assert [d["state"] for _, d in _events(response.text)] == ["created", "gating", "completed"]
    assert "progress listener lost the database: connection refused" in caplog.text


async def test_shutdown_closes_the_listen_connection(make_api, pg_url):
    async def listeners() -> int:
        async with await psycopg.AsyncConnection.connect(
            to_libpq_url(pg_url), autocommit=True
        ) as conn:
            cursor = await conn.execute(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE application_name = %s AND datname = current_database()",
                (APPLICATION_NAME,),
            )
            return (await cursor.fetchone())[0]

    async with make_api() as api:
        await until(lambda: api.app.state.ctx.progress.listening)
        assert await listeners() == 1
    assert await listeners() == 0
```

In `api/tests/conftest.py`, after `from corelata_api.app import create_app` add `from corelata_api.run_listener import listen_connection`; in `make_api`, replace

```python
    async def make(coglossa_transport=None, queue=None, **overrides) -> AsyncIterator[Api]:
        path = write_config(**overrides)
        cfg, _ = load_config(path)
        queue = queue or RecordingQueue()
        app = create_app(
            cfg, path, open_queue=_recording(queue), coglossa_transport=coglossa_transport
        )
```

with

```python
    async def make(
        coglossa_transport=None, queue=None, listener_connect=None, **overrides
    ) -> AsyncIterator[Api]:
        path = write_config(**overrides)
        cfg, _ = load_config(path)
        queue = queue or RecordingQueue()
        app = create_app(
            cfg,
            path,
            open_queue=_recording(queue),
            coglossa_transport=coglossa_transport,
            listener_connect=listener_connect or listen_connection,
        )
```

and replace `set_run_state` with:

```python
async def set_run_state(db: Database, run_id: str, state: str, *, notify: bool = True) -> None:
    """Move a run on without a worker (tests of routes that need a finished run), announcing the
    change as the worker does (CRL-22) unless `notify` is False."""
    from corelata.store import runs
    from corelata.store.models import utcnow

    async with db.session() as s, s.begin():
        run = await runs.get_run(s, uuid.UUID(run_id), lock=True)
        run.state = state
        run.started_at = run.started_at or utcnow()
        if state in ("completed", "gate_rejected", "failed", "cancelled"):
            run.finished_at = utcnow()
        if notify:
            await runs.notify_run(s, run.id)
```

(With the listener up, the existing `test_changes_are_streamed_until_the_run_ends` and `test_two_streams_on_one_run_share_one_poller_and_leave_none` need the announcement: their changes 0.1 s apart would otherwise fall between two 0.2 s heartbeats.)

- [ ] **Step 2: Run them to see them fail**

Run: `cd api && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/test_progress_feed.py tests/test_run_listener.py tests/test_progress.py --no-cov -q`
Expected: collection fails with `ModuleNotFoundError: No module named 'corelata_api.run_listener'`.

- [ ] **Step 3: The feed wakes on a notification**

Replace `api/corelata_api/progress_feed.py` with:

```python
"""One database poller per run, shared by every open `GET /runs/{id}/events` stream (CRL-8,
R-M9-2). A stream subscribes with the state it has shown and receives each change after it; the
poller runs while anyone listens and stops at the run's terminal state, when the run disappears,
when the database fails, or when the last stream leaves.

The poller reads when the run is announced on the run channel (`notify`, from the API's
`RunListener`, CRL-22) and otherwise at a slow heartbeat, `poll_s * 10` capped at 30 s, in case a
notification was lost. While the listener is down it polls every `poll_s`, as before CRL-22
(R-M14-3)."""

from __future__ import annotations

import asyncio
import contextlib
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

HEARTBEAT_FACTOR = 10
HEARTBEAT_MAX_S = 30.0


class Deleted:
    """The run no longer exists."""


class Ended:
    """The poller stopped without a terminal state (database error); the stream closes and the
    browser reconnects after `retry`."""


DELETED = Deleted()
ENDED = Ended()
Update = RunProgress | Deleted | Ended


@dataclass
class _Watcher:
    joined: int  # the poller's read sequence when the stream subscribed
    shown: RunProgress  # what that stream has displayed


@dataclass
class _Poller:
    queues: dict[asyncio.Queue[Update], _Watcher] = field(default_factory=dict)
    seq: int = 0  # reads started so far
    wake: asyncio.Event = field(default_factory=asyncio.Event)  # read now, do not wait
    task: asyncio.Task[None] = field(init=False)


class ProgressFeed:
    def __init__(self, fetch: Fetch, poll_s: float) -> None:
        self._fetch = fetch
        self._poll_s = poll_s
        self._pollers: dict[uuid.UUID, _Poller] = {}
        self._listening = False

    @property
    def active(self) -> int:
        """Runs with a live poller."""
        return len(self._pollers)

    @property
    def poll_s(self) -> float:
        """The interval while the listener is down (`api.progress_poll_s`)."""
        return self._poll_s

    @property
    def heartbeat_s(self) -> float:
        """The interval while the listener is up: a lost notification costs at most this."""
        return min(self._poll_s * HEARTBEAT_FACTOR, HEARTBEAT_MAX_S)

    @property
    def listening(self) -> bool:
        return self._listening

    def set_listening(self, listening: bool) -> None:
        """The listener connected (True) or lost its connection (False). Either way every poller
        reads once now: a change committed while nobody listened is not left for the heartbeat,
        and after a loss the pollers go back to `poll_s` without finishing a heartbeat wait."""
        if listening == self._listening:
            return
        self._listening = listening
        for poller in self._pollers.values():
            poller.wake.set()

    def notify(self, run_id: uuid.UUID) -> None:
        """The run changed: its poller, if any, reads now. Several notifications before that
        read cost one read."""
        poller = self._pollers.get(run_id)
        if poller is not None:
            poller.wake.set()

    def subscribe(self, run_id: uuid.UUID, last: RunProgress) -> asyncio.Queue[Update]:
        """Updates for one stream. `last` is what the stream has shown. The poller publishes to
        this queue only the result of a read that started after the subscription (so it is at
        least as fresh as the caller's own read, and nothing stale is pushed) and only when it
        differs from what the stream last showed (so a change between the caller's read and its
        subscription is not missed, and nothing is repeated). While the listener is up, a
        subscription starts a read at once: the notification of a change between the caller's
        read and its subscription may already have been spent."""
        queue: asyncio.Queue[Update] = asyncio.Queue()
        poller = self._pollers.get(run_id)
        if poller is None:
            poller = _Poller()
            poller.task = asyncio.create_task(self._run(run_id, poller))
            self._pollers[run_id] = poller
        poller.queues[queue] = _Watcher(poller.seq, last)
        if self._listening:
            poller.wake.set()
        return queue

    def unsubscribe(self, run_id: uuid.UUID, queue: asyncio.Queue[Update]) -> None:
        poller = self._pollers.get(run_id)
        if poller is None:
            return
        poller.queues.pop(queue, None)
        if not poller.queues:
            poller.task.cancel()
            del self._pollers[run_id]

    async def close(self) -> None:
        pollers = list(self._pollers.values())
        self._pollers.clear()
        for poller in pollers:
            for queue in poller.queues:
                queue.put_nowait(ENDED)  # streams still open at shutdown end cleanly
            poller.task.cancel()
        for poller in pollers:
            with contextlib.suppress(asyncio.CancelledError, Exception):  # shutting down
                await poller.task

    @staticmethod
    def _publish(poller: _Poller, update: Update) -> None:
        for queue in poller.queues:
            queue.put_nowait(update)

    @staticmethod
    def _publish_progress(poller: _Poller, seq: int, current: RunProgress) -> None:
        for queue, watcher in poller.queues.items():
            # A terminal state cannot be stale, and the poller stops after it: a stream that
            # joined during the final read must still get it.
            fresh = seq > watcher.joined or current.state in TERMINAL_STATES
            if fresh and current != watcher.shown:
                queue.put_nowait(current)
                watcher.shown = current

    async def _wait(self, poller: _Poller) -> None:
        interval = self.heartbeat_s if self._listening else self._poll_s
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(poller.wake.wait(), interval)
        poller.wake.clear()  # before the read: a notification during it causes another read

    async def _run(self, run_id: uuid.UUID, poller: _Poller) -> None:
        try:
            while True:
                await self._wait(poller)
                poller.seq += 1
                seq = poller.seq
                try:
                    current = await self._fetch(run_id)
                except NotFoundError:
                    self._publish(poller, DELETED)
                    return
                except (OperationalError, InterfaceError) as e:
                    log.warning(
                        "progress poller ended: %s", error_reason(e), extra={"run_id": str(run_id)}
                    )
                    self._publish(poller, ENDED)
                    return
                except Exception:
                    log.exception("progress poller failed", extra={"run_id": str(run_id)})
                    self._publish(poller, ENDED)
                    return
                self._publish_progress(poller, seq, current)
                if current.state in TERMINAL_STATES:
                    return
        finally:
            if self._pollers.get(run_id) is poller:  # a replacement poller's entry is not ours
                del self._pollers[run_id]
```

- [ ] **Step 4: The listener**

Create `api/corelata_api/run_listener.py`:

```python
"""The API's one LISTEN connection (CRL-22, R-M14-3). The worker and the service announce every
committed change to a run on `corelata_run` with the run id; this task hands each one to the
progress feed, which reads that run at once. While the connection is down the feed polls at
`api.progress_poll_s`, and the task reconnects after 1, 2, 4, 8, 16, then every 30 s."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable, Sequence

import psycopg
from corelata.store.db import CONNECT_TIMEOUT_S, error_reason, to_libpq_url
from corelata.store.runs import RUN_CHANNEL
from psycopg import sql

from corelata_api.progress_feed import ProgressFeed

log = logging.getLogger("corelata.api")

APPLICATION_NAME = "corelata-api-listen"  # how the connection shows in pg_stat_activity
BACKOFF_S: tuple[float, ...] = (1.0, 2.0, 4.0, 8.0, 16.0, 30.0)

Connect = Callable[[], Awaitable[psycopg.AsyncConnection]]
Sleep = Callable[[float], Awaitable[None]]


def listen_connection(url: str) -> Connect:
    """Opens the listener's connection: autocommit, so it never holds a transaction open (an open
    transaction on a listening session stops Postgres from trimming its notification queue)."""

    async def connect() -> psycopg.AsyncConnection:
        return await psycopg.AsyncConnection.connect(
            to_libpq_url(url),
            autocommit=True,
            connect_timeout=CONNECT_TIMEOUT_S,
            application_name=APPLICATION_NAME,
        )

    return connect


class RunListener:
    def __init__(
        self,
        connect: Connect,
        feed: ProgressFeed,
        *,
        backoff: Sequence[float] = BACKOFF_S,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._connect = connect
        self._feed = feed
        self._backoff = backoff
        self._sleep = sleep

    async def run(self) -> None:
        """Until cancelled: connect, LISTEN, hand notifications to the feed; on any failure tell
        the feed, wait the next backoff step and start again."""
        failures = 0
        while True:
            try:
                async with await self._connect() as conn:
                    await conn.execute(sql.SQL("LISTEN {}").format(sql.Identifier(RUN_CHANNEL)))
                    failures = 0
                    self._feed.set_listening(True)
                    log.info("progress listener connected")
                    async for note in conn.notifies():
                        self._handle(note.payload)
                    raise psycopg.OperationalError("the notification stream ended")
            except (psycopg.Error, OSError) as e:
                reason = error_reason(e)
            except Exception as e:  # noqa: BLE001 - the listener must outlive any one failure
                log.exception("progress listener failed")
                reason = type(e).__name__
            finally:
                self._feed.set_listening(False)
            delay = self._backoff[min(failures, len(self._backoff) - 1)]
            failures += 1
            log.warning(
                "progress listener lost the database: %s; polling every %s s, reconnecting in %s s",
                reason,
                self._feed.poll_s,
                delay,
            )
            await self._sleep(delay)

    def _handle(self, payload: str) -> None:
        try:
            run_id = uuid.UUID(payload)
        except ValueError:
            log.warning("progress listener ignored a notification that is not a run id")
            return
        self._feed.notify(run_id)
```

- [ ] **Step 5: On the lifespan**

In `api/corelata_api/app.py`: `import asyncio` before `import contextlib`; after `from corelata_api.routes import ROUTERS` add `from corelata_api.run_listener import Connect, RunListener, listen_connection`; after `QueueOpener = …` add `ListenerConnect = Callable[[str], Connect]`. `create_app` gains the keyword parameter `listener_connect: ListenerConnect = listen_connection,` after `coglossa_transport`. In `lifespan`, after the `feed = ProgressFeed(...)` statement add

```python
        # One LISTEN connection for the process; the feed polls until it connects (CRL-22).
        listener = asyncio.create_task(RunListener(listener_connect(db.url), feed).run())
```

and the `finally:` block becomes

```python
        finally:
            listener.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await listener
            await feed.close()
            await db.dispose()
```

In `api/corelata_api/context.py` line 30 becomes `    progress: ProgressFeed  # one poller per run for the SSE streams, woken by NOTIFY (CRL-22)`. In `api/corelata_api/routes/progress.py` the module docstring becomes:

```python
"""Spec §10.1 `GET /runs/{id}/events`: progress as server-sent events. One reader per run however
many streams watch it (`ProgressFeed`, CRL-8), woken by the worker's NOTIFY (CRL-22) and polling
at api.progress_poll_s while the API's LISTEN connection is down. Copied from Coglossa."""
```

- [ ] **Step 6: Run the tests**

Run: `cd api && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/test_progress_feed.py tests/test_run_listener.py tests/test_progress.py --no-cov -q`
Expected: `34 passed`.

Run: `cd api && uv run ruff check . && uv run ruff format --check . && make -C .. test-api`
Expected: ruff clean; `154 passed`, coverage at least 95% (`run_listener.py` and `progress_feed.py` at 100%).

- [ ] **Step 7: Commit**

```bash
cat > <scratchpad>/m14-task2-commit.txt <<'EOF'
feat: event-driven progress streams from one LISTEN connection (CRL-22)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git add api/corelata_api/run_listener.py api/corelata_api/progress_feed.py api/corelata_api/app.py api/corelata_api/context.py api/corelata_api/routes/progress.py api/tests/conftest.py api/tests/test_progress_feed.py api/tests/test_run_listener.py api/tests/test_progress.py
git commit -F <scratchpad>/m14-task2-commit.txt
```

---

### Task 3: `GET /api/runs` pages by cursor (CRL-24, API)

**Files:**
- Modify: `engine/corelata/store/runs.py` (sqlalchemy import; `list_runs`, lines 262-271 before Task 1, about 292 after it), `engine/corelata/service.py` (imports lines 9-10; `list_runs` lines 525-528), `api/corelata_api/routes/runs.py` (after `ReviewResult`, line 34; `list_runs` lines 53-59)
- Test: `engine/tests/store/test_runs.py` (after `test_list_runs_is_newest_first_and_bounded`, line 300), `engine/tests/test_service.py` (imports lines 1-3; after `test_list_runs_returns_summaries`, line 391), `api/tests/test_runs.py` (imports lines 1-4; `test_start_run_queues_one_job` lines 18-21; `test_list_runs_validates_its_parameters` line 59; `test_review_accept_and_return` lines 116-118; `test_a_queue_outage_answers_503_and_the_run_is_failed` line 151), `api/tests/test_integration.py` (line 78)
- Regenerate: `schema/openapi.json`, `web/src/api/schema.d.ts` (`make schema`)

**Interfaces:**
- Consumes: `service.InvalidRequestError` (HTTP 422 through `errors._STATUS`), `RunSummary`.
- Produces: `store.runs.list_runs(s, project_id, *, limit: int, before: tuple[datetime, uuid.UUID] | None = None) -> list[Run]`; `service.list_runs(db, project_id, *, limit: int = 100, before: tuple[datetime, uuid.UUID] | None = None) -> list[RunSummary]`; `service.run_cursor(run: RunSummary) -> str`; `service.parse_run_cursor(cursor: str) -> tuple[datetime, uuid.UUID]` (raises `InvalidRequestError("invalid cursor 'before': pass the next_before of the previous page")`); `corelata_api.routes.runs.RunPage(runs: list[RunSummary], next_before: str | None)`; the generated TypeScript `components["schemas"]["RunPage"]` (`{ next_before: string | null; runs: RunSummary[] }`) and the query parameter `before?: string | null` on `GET /api/runs`, which Task 4 uses.

- [ ] **Step 1: Failing tests**

In `engine/tests/store/test_runs.py`, after `test_list_runs_is_newest_first_and_bounded` add:

```python


async def test_list_runs_pages_through_a_tie_without_skipping_or_repeating(db, tmp_path):
    cfg = build_config()
    storage = LocalStorage(tmp_path / "files")
    prompts = service.PromptLibrary(cfg.prompts_dir)
    pid = await service.create_project(db, "p")
    [sid] = await service.add_source(db, storage, pid, "a.txt", b"Varna port handles grain.")
    ids = []
    for i in range(5):
        req = service.RunRequest(project_id=pid, source_ids=[sid], value_statement=f"v{i}")
        ids.append(await service.start_run(db, storage, RecordingQueue(), cfg, prompts, req))
    async with db.session() as s, s.begin():
        for run_id in ids[1:]:  # four runs created in the same microsecond, one before them
            (await runs.get_run(s, run_id)).created_at = T0
        (await runs.get_run(s, ids[0])).created_at = T0 - timedelta(microseconds=1)
    pages: list[list[uuid.UUID]] = []
    before = None
    async with db.session() as s:
        while page := await runs.list_runs(s, pid, limit=2, before=before):
            pages.append([r.id for r in page])
            before = (page[-1].created_at, page[-1].id)
    # newest first; within the tie, the larger id first (Postgres orders uuids as Python does)
    assert [run_id for page in pages for run_id in page] == [*sorted(ids[1:], reverse=True), ids[0]]
    assert [len(page) for page in pages] == [2, 2, 1]
```

In `engine/tests/test_service.py`, after `import uuid` add `from datetime import UTC, datetime, timedelta, timezone`; after `test_list_runs_returns_summaries` add:

```python


async def test_list_runs_continues_after_a_cursor(svc):
    pid = await svc.project()
    sid = await svc.source(pid)
    for _ in range(3):
        await svc.run(pid, [sid])
    first = await service.list_runs(svc.db, pid, limit=2)
    before = service.parse_run_cursor(service.run_cursor(first[-1]))
    rest = await service.list_runs(svc.db, pid, limit=2, before=before)
    everything = await service.list_runs(svc.db, pid)
    assert [r.run_id for r in first + rest] == [r.run_id for r in everything]
    assert len(rest) == 1


def test_a_run_cursor_is_the_utc_time_to_the_microsecond_and_the_id():
    run_id = "6f1c2a9e-0000-4000-8000-000000000001"
    summary = RunSummary(
        run_id=run_id,
        project_id=str(uuid.uuid4()),
        state=RunState.COMPLETED,
        value_statement="v",
        iteration=0,
        max_iterations=2,
        created_at=datetime(2026, 10, 17, 9, 30, 1, 120000, tzinfo=timezone(timedelta(hours=3))),
    )
    cursor = service.run_cursor(summary)
    assert cursor == f"2026-10-17T06:30:01.120000Z|{run_id}"
    assert service.parse_run_cursor(cursor) == (
        datetime(2026, 10, 17, 6, 30, 1, 120000, tzinfo=UTC),
        uuid.UUID(run_id),
    )


@pytest.mark.parametrize(
    "cursor",
    [
        "",
        "2026-10-17T06:30:01.120000Z",  # no run id
        "|6f1c2a9e-0000-4000-8000-000000000001",  # no time
        "2026-10-17T06:30:01.120000|6f1c2a9e-0000-4000-8000-000000000001",  # no time zone
        "yesterday|6f1c2a9e-0000-4000-8000-000000000001",
        "2026-10-17T06:30:01.120000Z|run-1",
    ],
)
def test_a_malformed_cursor_is_an_invalid_request(cursor):
    with pytest.raises(service.InvalidRequestError) as raised:
        service.parse_run_cursor(cursor)
    assert str(raised.value) == "invalid cursor 'before': pass the next_before of the previous page"
```

In `api/tests/test_runs.py`, the imports (lines 1-4) become:

```python
import uuid
from datetime import UTC, datetime, timedelta

from corelata.service import QueueUnavailableError
from corelata.store import runs
from corelata.store.models import ReviewEvent
```

In `test_start_run_queues_one_job`, replace

```python
    assert listed.status_code == 200
    [summary] = listed.json()
```

with

```python
    assert listed.status_code == 200
    assert listed.json()["next_before"] is None
    [summary] = listed.json()["runs"]
```

In `test_list_runs_validates_its_parameters`, replace the last line, `assert (await api.client.get("/api/runs", params={"project_id": pid})).json() == []`, with:

```python
    assert (await api.client.get("/api/runs", params={"project_id": pid})).json() == {
        "runs": [],
        "next_before": None,
    }
    for before in ("yesterday", "2026-10-17T06:30:01Z|run-1", "x" * 101):
        bad = await api.client.get("/api/runs", params={"project_id": pid, "before": before})
        assert bad.status_code == 422, before
    bad = await api.client.get("/api/runs", params={"project_id": pid, "before": "yesterday"})
    assert bad.json() == {
        "detail": "invalid cursor 'before': pass the next_before of the previous page"
    }


async def _runs_created_at(api, pid: str, sid: str, stamps: list[datetime]) -> list[str]:
    """One run per stamp, with that creation time."""
    body = {"project_id": pid, "source_ids": [sid], "value_statement": STATEMENT}
    ids = [(await api.client.post("/api/runs", json=body)).json()["run_id"] for _ in stamps]
    async with api.db.session() as s, s.begin():
        for run_id, stamp in zip(ids, stamps, strict=True):
            (await runs.get_run(s, uuid.UUID(run_id))).created_at = stamp
    return ids


async def _pages(api, pid: str, limit: int) -> list[dict]:
    pages, before = [], None
    while True:
        params = {"project_id": pid, "limit": limit, **({"before": before} if before else {})}
        response = await api.client.get("/api/runs", params=params)
        assert response.status_code == 200, response.text
        pages.append(response.json())
        before = pages[-1]["next_before"]
        if before is None:
            return pages


async def test_list_runs_pages_by_cursor_through_ties_without_gaps(api):
    pid, sid = await project_with_source(api)
    t0 = datetime(2026, 10, 17, 6, 30, 1, 120000, tzinfo=UTC)
    stamps = [t0 - timedelta(seconds=i // 2) for i in range(7)]  # pairs share a microsecond
    ids = await _runs_created_at(api, pid, sid, stamps)
    pages = await _pages(api, pid, limit=2)
    assert [len(p["runs"]) for p in pages] == [2, 2, 2, 1]
    shown = [r["run_id"] for p in pages for r in p["runs"]]
    newest_first = sorted(zip(stamps, ids, strict=True), reverse=True)  # by time, then id
    assert shown == [run_id for _, run_id in newest_first]  # every run once, in one order
    last = pages[0]["runs"][-1]["run_id"]  # one of the two runs created at t0
    assert pages[0]["next_before"] == f"2026-10-17T06:30:01.120000Z|{last}"


async def test_a_full_last_page_has_no_next_cursor(api):
    pid, sid = await project_with_source(api)
    t0 = datetime(2026, 10, 17, 6, 30, tzinfo=UTC)
    await _runs_created_at(api, pid, sid, [t0 - timedelta(seconds=i) for i in range(4)])
    pages = await _pages(api, pid, limit=2)
    assert [len(p["runs"]) for p in pages] == [2, 2]  # no empty third page
    assert pages[-1]["next_before"] is None


async def test_a_run_created_while_paging_does_not_shift_the_next_page(api):
    pid, sid = await project_with_source(api)
    t0 = datetime(2026, 10, 17, 6, 30, tzinfo=UTC)
    ids = await _runs_created_at(api, pid, sid, [t0 - timedelta(seconds=i) for i in range(4)])
    first = (await api.client.get("/api/runs", params={"project_id": pid, "limit": 2})).json()
    await _runs_created_at(api, pid, sid, [t0 + timedelta(seconds=1)])  # newer than all
    params = {"project_id": pid, "limit": 2, "before": first["next_before"]}
    second = (await api.client.get("/api/runs", params=params)).json()
    assert [r["run_id"] for r in first["runs"] + second["runs"]] == ids
```

In `test_review_accept_and_return` (the `listed = (await api.client.get("/api/runs", …)).json()` statement before `assert {r["run_id"]: r["parent_run_id"] for r in listed} == {`), append `["runs"]` after `.json()`. In `test_a_queue_outage_answers_503_and_the_run_is_failed`, `[summary] = (await api.client.get("/api/runs", params={"project_id": pid})).json()` becomes `[summary] = (await api.client.get("/api/runs", params={"project_id": pid})).json()["runs"]`. In `api/tests/test_integration.py` line 78, `listed = (await api.client.get("/api/runs", params={"project_id": pid})).json()` becomes `listed = (await api.client.get("/api/runs", params={"project_id": pid})).json()["runs"]`.

- [ ] **Step 2: Run them to see them fail**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/store/test_runs.py tests/test_service.py --no-cov -q -k "cursor or tie"`
Expected: FAIL with `TypeError: list_runs() got an unexpected keyword argument 'before'` and `AttributeError: module 'corelata.service' has no attribute 'run_cursor'`.

Run: `cd api && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/test_runs.py tests/test_integration.py --no-cov -q`
Expected: FAIL (`TypeError: list indices must be integers or slices, not str` where the tests read `["runs"]`).

- [ ] **Step 3: Keyset paging in the store and the service**

In `engine/corelata/store/runs.py`, `from sqlalchemy import delete, null, select, text, update` becomes `from sqlalchemy import delete, null, select, text, tuple_, update`, and `list_runs` becomes:

```python
async def list_runs(
    s: AsyncSession,
    project_id: uuid.UUID,
    *,
    limit: int,
    before: tuple[datetime, uuid.UUID] | None = None,
) -> list[Run]:
    """A project's runs, newest first: `(created_at, id)` descending, so runs created in the same
    microsecond keep one order. `before` is the `(created_at, id)` of the last run of the previous
    page; the page holds the runs after it in that order (keyset paging, CRL-24)."""
    query = select(Run).where(Run.project_id == project_id)
    if before is not None:
        query = query.where(tuple_(Run.created_at, Run.id) < tuple_(*before))
    return list(await s.scalars(query.order_by(Run.created_at.desc(), Run.id.desc()).limit(limit)))
```

In `engine/corelata/service.py`, after `from dataclasses import dataclass` add `from datetime import UTC, datetime`, and replace `list_runs` with:

```python
async def list_runs(
    db: Database,
    project_id: uuid.UUID,
    *,
    limit: int = 100,
    before: tuple[datetime, uuid.UUID] | None = None,
) -> list[RunSummary]:
    """A project's runs, newest first; `before` (from `parse_run_cursor`) starts after that run."""
    async with db.session() as s:
        await runs.get_project(s, project_id)
        found = await runs.list_runs(s, project_id, limit=limit, before=before)
        return [_summary(r) for r in found]


def run_cursor(run: RunSummary) -> str:
    """The cursor that pages after `run` (CRL-24, R-M14-1): `<created_at>|<run_id>`, the time in
    ISO-8601 UTC to the microsecond, as Postgres stores it."""
    stamp = run.created_at.astimezone(UTC).isoformat(timespec="microseconds")
    return f"{stamp.replace('+00:00', 'Z')}|{run.run_id}"


def parse_run_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    """`run_cursor`'s inverse. Anything else is an InvalidRequestError (HTTP 422)."""
    stamp, _, run_id = cursor.rpartition("|")
    try:
        created_at = datetime.fromisoformat(stamp)
        if created_at.tzinfo is None:
            raise ValueError("no time zone")
        return created_at, uuid.UUID(run_id)
    except ValueError:
        raise InvalidRequestError(
            "invalid cursor 'before': pass the next_before of the previous page"
        ) from None
```

- [ ] **Step 4: The route**

In `api/corelata_api/routes/runs.py`, after `class ReviewResult` add:

```python


class RunPage(BaseModel):
    """One page of a project's runs, newest first (keyset paging on created_at and id)."""

    runs: list[RunSummary]
    next_before: str | None = Field(
        description="Pass as `before` for the next page; null when this page is the last."
    )
```

and replace the `list_runs` route with:

```python
@router.get("/runs")
async def list_runs(
    ctx: Ctx,
    project_id: uuid.UUID,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    before: Annotated[str | None, Query(max_length=100)] = None,
) -> RunPage:
    """A project's runs, newest first, `limit` at a time; `before` is the previous page's
    `next_before`."""
    after = service.parse_run_cursor(before) if before is not None else None
    found = await service.list_runs(ctx.db, project_id, limit=limit + 1, before=after)
    page = found[:limit]
    more = len(found) > limit  # one row past the page says whether another page exists
    return RunPage(runs=page, next_before=service.run_cursor(page[-1]) if more else None)
```

- [ ] **Step 5: Regenerate the schema**

Run: `make schema && git status --short schema web/src/api/schema.d.ts`
Expected: exactly ` M schema/openapi.json` and ` M web/src/api/schema.d.ts`. `git diff schema/openapi.json` shows a new `RunPage` component (`runs` array of `RunSummary`, `next_before` string-or-null, both required), a `before` query parameter (`maxLength` 100, string or null) and the route's description on `GET /api/runs`, and its `200` response `$ref` to `RunPage`; `schema.d.ts` gains `RunPage: { next_before: string | null; runs: components["schemas"]["RunSummary"][] }` and `before?: string | null`. (The web build fails to type-check until Task 4: `useRuns` still reads `RunSummary[]`. Do not run `pnpm lint` in this task.)

- [ ] **Step 6: Run the tests**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/store/test_runs.py tests/test_service.py --no-cov -q`
Expected: all pass (9 new tests among them).

Run: `cd api && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/test_runs.py tests/test_integration.py tests/test_openapi.py --no-cov -q`
Expected: all pass (`test_every_screen_has_its_routes` and `test_committed_openapi_matches_the_app` included).

Run: `(cd engine && uv run ruff check . && uv run ruff format --check .) && (cd api && uv run ruff check . && uv run ruff format --check .) && make test-engine test-api`
Expected: ruff clean; engine `858 passed`, api `157 passed`, both at least 95% coverage.

- [ ] **Step 7: Commit**

```bash
cat > <scratchpad>/m14-task3-commit.txt <<'EOF'
feat: cursor paging for GET /api/runs (CRL-24)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git add engine/corelata/store/runs.py engine/corelata/service.py engine/tests/store/test_runs.py engine/tests/test_service.py api/corelata_api/routes/runs.py api/tests/test_runs.py api/tests/test_integration.py schema/openapi.json web/src/api/schema.d.ts
git commit -F <scratchpad>/m14-task3-commit.txt
```

---

### Task 4: The run list pages by cursor past 500 runs (CRL-24, web)

**Files:**
- Modify: `web/src/api/projects.ts` (line 1-3 imports; `RUN_PAGE`/`RUN_LIMIT_MAX`/`useRuns`, lines 93-109), `web/src/api/types.ts` (line 10), `web/src/pages/new/RunList.tsx` (whole file), `web/src/test/fixtures.ts` (type imports; after `runSummary`, line 81)
- Test: `web/src/pages/new/RunList.test.tsx` (whole file), `web/src/api/projects.test.tsx` (lines 27-37), `web/src/pages/new/ProjectPicker.test.tsx` (line 3; lines 22, 54, 65, 122), `web/src/pages/new/NewRunPage.test.tsx` (line 3; line 11), `web/src/pages/new/SourcesPanel.test.tsx` (line 3; lines 15, 44, 104, 154)

**Interfaces:**
- Consumes: Task 3's generated `components["schemas"]["RunPage"]` and the `before` query parameter of `GET /api/runs`.
- Produces: `export type RunPage = S["RunPage"]` (`web/src/api/types.ts`); `useRuns(projectId: string | null)` returning TanStack's `UseInfiniteQueryResult<InfiniteData<RunPage, string | null>>` (`data.pages[i].runs`, `hasNextPage`, `fetchNextPage`, `isFetching`); `RUN_PAGE = 50`; fixture `noRuns: RunPage = { runs: [], next_before: null }`. `RUN_LIMIT_MAX` no longer exists.

- [ ] **Step 1: Failing tests**

Replace `web/src/pages/new/RunList.test.tsx` with:

```tsx
import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { RUN_PAGE } from "../../api/projects";
import type { RunSummary } from "../../api/types";
import { deferred } from "../../test/deferred";
import { packs, project, runSummary } from "../../test/fixtures";
import { renderApp } from "../../test/render";
import { server } from "../../test/server";

// The page mounts the run options, which read the packs.
beforeEach(() => server.use(http.get("*/api/packs", () => HttpResponse.json(packs))));

function serveRuns(runs: RunSummary[] | Response) {
  server.use(
    http.get("*/api/projects", () => HttpResponse.json([project])),
    http.get(`*/api/projects/${project.id}/sources`, () => HttpResponse.json([])),
    runs instanceof Response
      ? http.get("*/api/runs", () => runs)
      : http.get("*/api/runs", () => HttpResponse.json({ runs, next_before: null })),
  );
}

function many(n: number): RunSummary[] {
  return Array.from({ length: n }, (_, i) => ({
    ...runSummary,
    run_id: `${String(i).padStart(8, "0")}-0000-0000-0000-000000000000`,
    value_statement: `Statement ${i}`,
  }));
}

const cursorOf = (run: RunSummary) => `${run.created_at}|${run.run_id}`;

/** The API's keyset paging over `all` (newest first): each request answers the runs after its
 * `before` cursor and the cursor of its last run while more remain. Records each `before`. */
function servePaged(all: RunSummary[], options: { failOnce?: string } = {}) {
  const asked: string[] = [];
  let failed = false;
  server.use(
    http.get("*/api/projects", () => HttpResponse.json([project])),
    http.get(`*/api/projects/${project.id}/sources`, () => HttpResponse.json([])),
    http.get("*/api/runs", ({ request }) => {
      const params = new URL(request.url).searchParams;
      const before = params.get("before");
      asked.push(`${params.get("limit")}:${before ?? "-"}`);
      if (before !== null && before === options.failOnce && !failed) {
        failed = true;
        return HttpResponse.json(
          { detail: "the database is unavailable: connection reset" },
          { status: 503 },
        );
      }
      const start = before === null ? 0 : all.findIndex((r) => cursorOf(r) === before) + 1;
      const runs = all.slice(start, start + Number(params.get("limit")));
      const more = start + runs.length < all.length;
      return HttpResponse.json({ runs, next_before: more ? cursorOf(runs.at(-1)!) : null });
    }),
  );
  return asked;
}

it("lists the project's runs with links to progress or review", async () => {
  const running = {
    ...runSummary,
    run_id: "66666666-6666-6666-6666-666666666666",
    state: "drafting" as const,
    status: null,
    finished_at: null,
  };
  serveRuns([running, runSummary]);
  renderApp(`/new?project=${project.id}`);
  const table = await screen.findByRole("table", { name: "Runs" });
  const rows = within(table).getAllByRole("row").slice(1);
  expect(rows).toHaveLength(2);
  expect(within(rows[0]!).getByRole("link", { name: "Progress" })).toHaveAttribute(
    "href",
    `/runs/${running.run_id}`,
  );
  expect(within(rows[1]!).getByRole("link", { name: "Review" })).toHaveAttribute(
    "href",
    `/runs/${runSummary.run_id}/review`,
  );
  expect(within(rows[1]!).getByText("Completed")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Show more" })).not.toBeInTheDocument();
});

it("links a failed run to its outcome", async () => {
  const failed = {
    ...runSummary,
    run_id: "77777777-7777-7777-7777-777777777777",
    state: "failed" as const,
  };
  serveRuns([failed]);
  renderApp(`/new?project=${project.id}`);
  expect(await screen.findByRole("link", { name: "Outcome" })).toHaveAttribute(
    "href",
    `/runs/${failed.run_id}`,
  );
});

it("shows an error when the run list fails", async () => {
  serveRuns(HttpResponse.json({ detail: "runs unavailable" }, { status: 400 }));
  renderApp(`/new?project=${project.id}`);
  expect(await screen.findByRole("alert")).toHaveTextContent("runs unavailable");
  expect(screen.queryByRole("table", { name: "Runs" })).not.toBeInTheDocument();
});

it("pages fifty at a time by cursor and stops at the last page", async () => {
  const all = many(120);
  const asked = servePaged(all);
  const { user } = renderApp(`/new?project=${project.id}`);
  const table = await screen.findByRole("table", { name: "Runs" });
  expect(within(table).getAllByRole("row")).toHaveLength(RUN_PAGE + 1);
  await user.click(screen.getByRole("button", { name: "Show more" }));
  await waitFor(() => expect(within(table).getAllByRole("row")).toHaveLength(101));
  await user.click(screen.getByRole("button", { name: "Show more" }));
  await waitFor(() => expect(within(table).getAllByRole("row")).toHaveLength(121));
  expect(asked).toEqual([`50:-`, `50:${cursorOf(all[49]!)}`, `50:${cursorOf(all[99]!)}`]);
  expect(screen.queryByRole("button", { name: "Show more" })).not.toBeInTheDocument();
  const values = within(table)
    .getAllByRole("cell")
    .filter((c) => c.dir === "auto");
  expect(new Set(values.map((c) => c.textContent)).size).toBe(120); // no run twice
});

it("keeps Show more in place, disabled, while the next page loads", async () => {
  const nextPage = deferred();
  server.use(
    http.get("*/api/projects", () => HttpResponse.json([project])),
    http.get(`*/api/projects/${project.id}/sources`, () => HttpResponse.json([])),
    http.get("*/api/runs", async ({ request }) => {
      const before = new URL(request.url).searchParams.get("before");
      if (before !== null) await nextPage.promise;
      const runs = many(100).slice(before === null ? 0 : 50, before === null ? 50 : 100);
      return HttpResponse.json({ runs, next_before: before === null ? "c1" : "c2" });
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

it("pages past 500 runs to the oldest, with no ceiling", async () => {
  servePaged(many(520));
  const { user } = renderApp(`/new?project=${project.id}`);
  const table = await screen.findByRole("table", { name: "Runs" });
  const rows = () => table.querySelectorAll("tbody tr").length; // 520 rows: skip role queries
  for (let shown = RUN_PAGE; shown < 520; shown += RUN_PAGE) {
    await waitFor(() => expect(screen.getByRole("button", { name: "Show more" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "Show more" }));
    await waitFor(() => expect(rows()).toBe(Math.min(shown + RUN_PAGE, 520)));
  }
  expect(table.querySelector("tbody tr:last-child")).toHaveTextContent("Statement 519");
  expect(screen.queryByRole("button", { name: "Show more" })).not.toBeInTheDocument();
  expect(screen.queryByText(/Showing the newest/)).not.toBeInTheDocument();
});

it("keeps the rows when the next page fails, and Show more tries again", async () => {
  const all = many(80);
  servePaged(all, { failOnce: cursorOf(all[49]!) });
  const { user } = renderApp(`/new?project=${project.id}`);
  const table = await screen.findByRole("table", { name: "Runs" });
  await user.click(screen.getByRole("button", { name: "Show more" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "the database is unavailable: connection reset",
  );
  expect(within(table).getAllByRole("row")).toHaveLength(RUN_PAGE + 1);
  await waitFor(() => expect(screen.getByRole("button", { name: "Show more" })).toBeEnabled());
  await user.click(screen.getByRole("button", { name: "Show more" }));
  await waitFor(() => expect(within(table).getAllByRole("row")).toHaveLength(81));
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("starts each project's run list at the first page again", async () => {
  const other = { ...project, id: "99999999-9999-9999-9999-999999999999", name: "Danube" };
  const asked: string[] = [];
  const errors = vi.spyOn(console, "error");
  server.use(
    http.get("*/api/projects", () => HttpResponse.json([project, other])),
    http.get("*/api/projects/:id/sources", () => HttpResponse.json([])),
    http.get("*/api/runs", ({ request }) => {
      const params = new URL(request.url).searchParams;
      const before = params.get("before");
      asked.push(`${params.get("project_id")}:${before ?? "-"}`);
      const runs = many(100).slice(before === null ? 0 : 50, before === null ? 50 : 100);
      return HttpResponse.json({ runs, next_before: before === null ? "page-2" : null });
    }),
  );
  const { user } = renderApp(`/new?project=${project.id}`);
  await screen.findByRole("table", { name: "Runs" });
  await user.click(screen.getByRole("button", { name: "Show more" }));
  await waitFor(() => expect(asked).toContain(`${project.id}:page-2`));
  await user.selectOptions(screen.getByRole("combobox", { name: "Project" }), other.id);
  await waitFor(() => expect(asked).toContain(`${other.id}:-`));
  expect(asked).not.toContain(`${other.id}:page-2`); // the next page did not carry over
  // siblings with one key kept the old value statement on screen after a switch
  expect(screen.getAllByRole("region", { name: "Value statement" })).toHaveLength(1);
  expect(errors.mock.calls.flat().join(" ")).not.toMatch(/same key/);
  errors.mockRestore();
});
```

In `web/src/api/projects.test.tsx`, replace

```tsx
    http.get("*/api/runs", ({ request }) => {
      expect(new URL(request.url).searchParams.get("project_id")).toBe(project.id);
      return HttpResponse.json([runSummary]);
    }),
```

with

```tsx
    http.get("*/api/runs", ({ request }) => {
      const params = new URL(request.url).searchParams;
      expect(params.get("project_id")).toBe(project.id);
      expect(params.get("limit")).toBe("50");
      expect(params.has("before")).toBe(false); // the first page has no cursor
      return HttpResponse.json({ runs: [runSummary], next_before: null });
    }),
```

and `await waitFor(() => expect(runs.result.current.data).toEqual([runSummary]));` with

```tsx
  await waitFor(() =>
    expect(runs.result.current.data?.pages).toEqual([{ runs: [runSummary], next_before: null }]),
  );
  expect(runs.result.current.hasNextPage).toBe(false);
```

In `ProjectPicker.test.tsx`, `NewRunPage.test.tsx` and `SourcesPanel.test.tsx`, every `http.get("*/api/runs", () => HttpResponse.json([])),` (4, 1 and 4 of them) becomes `http.get("*/api/runs", () => HttpResponse.json(noRuns)),`, and `noRuns` joins each file's `../../test/fixtures` import (alphabetical: `import { noRuns, packs, project, source } from "../../test/fixtures";`, `import { info, noRuns, packs, project, runProgress, sources } from "../../test/fixtures";`, `import { info, noRuns, packs, project, source, sources } from "../../test/fixtures";`).

In `web/src/test/fixtures.ts`, add `RunPage,` to the type import (between `ReportJson`/`ResolvedPack` and `RunProgress`, alphabetical), and after the `runSummary` constant add:

```ts

/** `GET /api/runs` for a project without runs: one page, nothing after it (R-M14-1). */
export const noRuns: RunPage = { runs: [], next_before: null };
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd web && pnpm exec vitest run src/pages/new src/api/projects.test.tsx`
Expected: FAIL: `noRuns` and `RunPage` are not exported yet, and the paging tests see a list that never asks with `before`.

- [ ] **Step 3: The hook and the list**

In `web/src/api/types.ts`, after `export type RunSummary = S["RunSummary"];` add `export type RunPage = S["RunPage"];`.

In `web/src/api/projects.ts`, the first three lines become:

```ts
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { client, unwrap } from "./client";
import type { ProjectView, RunPage, SourceKind, SourceView } from "./types";
```

and everything from `export const RUN_PAGE = 50;` to the end of the file becomes:

```ts
export const RUN_PAGE = 50;

/** A project's runs, newest first, `RUN_PAGE` at a time: each next page continues after the last
 * run shown, by the cursor the API returned with the page before (R-M14-1), so a project of any
 * size can be paged to its oldest run. The key is `projectKeys.runs(id)`: a mutation that
 * invalidates it refetches every loaded page. */
export function useRuns(projectId: string | null) {
  return useInfiniteQuery({
    queryKey: projectKeys.runs(projectId ?? ""),
    queryFn: ({ pageParam }) =>
      unwrap<RunPage>(
        client.GET("/api/runs", {
          params: {
            query: {
              project_id: projectId!,
              limit: RUN_PAGE,
              ...(pageParam === null ? {} : { before: pageParam }),
            },
          },
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (last: RunPage) => last.next_before,
    enabled: projectId !== null,
  });
}
```

Replace `web/src/pages/new/RunList.tsx` with:

```tsx
import { Link } from "react-router";
import { useRuns } from "../../api/projects";
import { StateBadge } from "../../components/StateBadge";
import { ErrorMessage } from "../../components/ErrorMessage";
import { formatDateTime, isTerminal } from "../../lib/format";

export function RunList({ projectId }: { projectId: string }) {
  const runs = useRuns(projectId);
  const rows = runs.data?.pages.flatMap((page) => page.runs) ?? [];
  if (runs.error && rows.length === 0) return <ErrorMessage error={runs.error} />;
  if (rows.length === 0) return null;
  return (
    <section aria-label="Runs" className="panel">
      <h2>Runs</h2>
      <table aria-label="Runs">
        <thead>
          <tr>
            <th>Started</th>
            <th>Value statement</th>
            <th>State</th>
            <th>Open</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((run) => (
            <tr key={run.run_id}>
              <td>{formatDateTime(run.created_at)}</td>
              <td dir="auto">{run.value_statement}</td>
              <td>
                <StateBadge state={run.state} />
              </td>
              <td>
                {run.state === "completed" ? (
                  <Link to={`/runs/${run.run_id}/review`}>Review</Link>
                ) : (
                  <Link to={`/runs/${run.run_id}`}>
                    {isTerminal(run.state) ? "Outcome" : "Progress"}
                  </Link>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {/* a failed next page (or refresh) keeps the rows shown; Show more tries again */}
      {runs.error ? <ErrorMessage error={runs.error} /> : null}
      {runs.hasNextPage ? (
        <button
          type="button"
          className="secondary"
          disabled={runs.isFetching}
          onClick={() => void runs.fetchNextPage()}
        >
          Show more
        </button>
      ) : null}
    </section>
  );
}
```

- [ ] **Step 4: Run the tests**

Run: `cd web && pnpm exec vitest run src/pages/new src/api/projects.test.tsx`
Expected: `8 passed` in `RunList.test.tsx`, every file passes.

Run: `cd web && pnpm lint && pnpm test && pnpm build`
Expected: lint clean; `167 passed` (Task 5 adds one more), every threshold at least 95% (`projects.ts` and `RunList.tsx` at 100%); build clean.

- [ ] **Step 5: Commit**

```bash
cat > <scratchpad>/m14-task4-commit.txt <<'EOF'
feat: the run list pages by cursor past 500 runs (CRL-24)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git add web/src/api/projects.ts web/src/api/types.ts web/src/pages/new/RunList.tsx web/src/test/fixtures.ts web/src/pages/new/RunList.test.tsx web/src/api/projects.test.tsx web/src/pages/new/ProjectPicker.test.tsx web/src/pages/new/NewRunPage.test.tsx web/src/pages/new/SourcesPanel.test.tsx
git commit -F <scratchpad>/m14-task4-commit.txt
```

---

### Task 5: The frame's policy allows the report stylesheet by hash, not `'unsafe-inline'` (CRL-23, part 1)

**Files:**
- Create: `engine/corelata/render/templates/report.css`, `web/src/report-style.d.ts`
- Modify: `engine/corelata/render/templates/report.html.j2` (lines 7-20, the `<style>` block), `engine/corelata/render/html.py` (whole file), `engine/pyproject.toml` (`[tool.hatch.build.targets.wheel] artifacts`, after line 46), `engine/tests/render/golden/varna.html` (lines 7-8), `web/vite.config.ts` (whole file), `web/src/pages/review/frameBridge.ts` (line 1; `installFrameBridge` lines 14-22; `FRAME_CSP` lines 43-46; `bridgeScript` lines 58-66), `deploy/docker/app.Dockerfile` (web stage, lines 12-13), `deploy/tests/check-app-image.sh` (lines 24-27)
- Test: `engine/tests/render/test_html.py` (imports lines 1-6; after `test_html_is_self_contained`, line 75), `web/src/pages/review/frameBridge.test.ts` (imports lines 1-12; `install` lines 14-27; the tests at lines 29-33, 74-86, 88-100; a new test after it)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `corelata.render.html.REPORT_CSS: str` (the stylesheet, the rendered report's one `<style>` element text); the virtual module `virtual:report-style` exporting `REPORT_STYLE_HASH: string` (`sha256-<base64 of SHA-256 of report.css's bytes>`); `FRAME_CSP(nonce) = "default-src 'none'; script-src 'nonce-<n>'; style-src '<REPORT_STYLE_HASH>' 'nonce-<n>'; img-src data:; connect-src 'none'"`; `installFrameBridge(doc, post, listen, css, nonce: string)` (sets `nonce` on its `<style>` when non-empty); `bridgeScript(nonce?)` passes `JSON.stringify(nonce ?? "")` as the fifth argument.

- [ ] **Step 1: Failing tests**

In `engine/tests/render/test_html.py`, the imports (lines 1-6) become:

```python
import re
from pathlib import Path

from lxml import html as lxml_html

from corelata.render import html as html_module
from corelata.render.html import REPORT_CSS, render_html
from corelata.render.outline import DEGRADATION_TITLE
```

and after `test_html_is_self_contained` add:

```python


def test_the_one_style_element_is_report_css_byte_for_byte_and_nothing_else_is_inline():
    css = (Path(html_module.__file__).parent / "templates" / "report.css").read_bytes()
    assert REPORT_CSS.encode("utf-8") == css  # what the web build hashes (CRL-23)
    for with_claim_ids in (False, True):
        out = render_html(
            make_report(), PACK, SOURCES, with_claim_ids=with_claim_ids, open_findings=[]
        )
        assert out.count("<style") == 1 and f"<style>{REPORT_CSS}</style>" in out
        assert '"Times New Roman"' in out  # not escaped
        doc = _doc(out)
        assert doc.xpath("//*[@style]") == []  # no inline style attributes to allow
```

In `web/src/pages/review/frameBridge.test.ts`, the imports become:

```ts
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { REPORT_STYLE_HASH } from "virtual:report-style";
import { reportHtml } from "../../test/fixtures";
import {
  FRAME_CSP,
  HIGHLIGHT_CSS,
  bridgeScript,
  cspMeta,
  frameNonce,
  installFrameBridge,
  withBridge,
  type FrameToHost,
  type HostToFrame,
} from "./frameBridge";
```

`install` becomes:

```ts
function install(html = reportHtml, nonce = "n0nce+/=") {
  const doc = new DOMParser().parseFromString(html, "text/html");
  const posted: FrameToHost[] = [];
  let handler: ((message: HostToFrame) => void) | undefined;
  installFrameBridge(
    doc,
    (m) => posted.push(m),
    (h) => (handler = h),
    HIGHLIGHT_CSS,
    nonce,
  );
  const click = (el: Element) =>
    el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
  return { doc, posted, send: (m: unknown) => handler!(m as HostToFrame), click };
}
```

The first test becomes:

```ts
it("adds the highlight stylesheet to the frame, bound to the nonce, and reports ready", () => {
  const { doc, posted } = install();
  const style = doc.head.querySelector("style:last-of-type");
  expect(style?.textContent).toBe(HIGHLIGHT_CSS);
  expect(style?.getAttribute("nonce")).toBe("n0nce+/=");
  expect(posted).toEqual([{ type: "corelata:ready" }]);
  const unbound = install(reportHtml, "").doc.head.querySelector("style:last-of-type");
  expect(unbound?.hasAttribute("nonce")).toBe(false); // no nonce, no attribute
});
```

In "serialises the installer into the document before </body>, bound to the nonce", replace

```ts
  expect(script).toContain(JSON.stringify(HIGHLIGHT_CSS));
  expect(bridgeScript().startsWith("<script>")).toBe(true); // no nonce, no attribute
```

with

```ts
  expect(script).toContain(`${JSON.stringify(HIGHLIGHT_CSS)}, "n0nce+/=");</script>`);
  expect(bridgeScript().startsWith("<script>")).toBe(true); // no nonce, no attribute
  expect(bridgeScript()).toContain(`${JSON.stringify(HIGHLIGHT_CSS)}, "");</script>`);
```

Replace the test "locks the frame down: nothing loads, the bridge runs by nonce, inline styles stay" through its `expect(FRAME_CSP("abc")).toBe(...)` statement with

```ts
it("locks the frame down: nothing loads, the bridge runs by nonce, the report style by hash", () => {
  expect(FRAME_CSP("abc")).toBe(
    `default-src 'none'; script-src 'nonce-abc'; style-src '${REPORT_STYLE_HASH}' 'nonce-abc'; img-src data:; connect-src 'none'`,
  );
  expect(FRAME_CSP("abc")).not.toContain("unsafe-inline"); // R-M14-2: no inline-style allowance
```

(the rest of that test, from `expect(cspMeta("abc"))`, is unchanged), and after that test add:

```ts
it("hashes the engine's report stylesheet, the text of the report's one style element", () => {
  // engine/tests/render/test_html.py pins that the rendered <style> holds exactly this file.
  const css = readFileSync(resolve("../engine/corelata/render/templates/report.css")); // from web/
  expect(REPORT_STYLE_HASH).toBe(`sha256-${createHash("sha256").update(css).digest("base64")}`);
  expect(REPORT_STYLE_HASH).toMatch(/^sha256-[A-Za-z0-9+/]{43}=$/);
});
```

(The existing "highlights the claim it is told to, scrolls only on request, and clears" test still pins that the frame applies the highlight, through the nonce-bound style.)

- [ ] **Step 2: Run them to see them fail**

Run: `cd engine && uv run pytest tests/render/test_html.py --no-cov -q`
Expected: collection fails with `ImportError: cannot import name 'REPORT_CSS'`.

Run: `cd web && pnpm exec vitest run src/pages/review/frameBridge.test.ts`
Expected: FAIL: `Failed to resolve import "virtual:report-style"`.

- [ ] **Step 3: The stylesheet becomes one file**

Create `engine/corelata/render/templates/report.css` with exactly the eleven lines that are now between `<style>` and `</style>` in `report.html.j2` (ending with one newline):

```css
:root { color-scheme: light dark; }
body.corelata-report { font-family: Georgia, "Times New Roman", serif; line-height: 1.5; max-width: 46rem; margin: 0 auto; padding: 1rem 1.25rem; }
.marking { text-align: center; font-family: system-ui, sans-serif; font-weight: 700; letter-spacing: .08em; border: 1px solid currentColor; padding: .25rem; margin: 0 0 1.5rem; }
.marking.bottom { margin: 2rem 0 0; }
h1 { font-size: 1.6rem; margin: 0 0 1rem; }
h2 { font-size: 1.15rem; margin: 1.5rem 0 .5rem; border-bottom: 1px solid rgba(128,128,128,.4); padding-bottom: .15rem; }
ul { padding-left: 1.25rem; }
li { margin: .3rem 0; }
sup.claim-ids { font-family: system-ui, sans-serif; font-size: .7em; margin-left: .15em; opacity: .7; }
section.appendix { border-top: 2px solid currentColor; margin-top: 2rem; padding-top: .5rem; }
footer.meta { font-family: system-ui, sans-serif; font-size: .8rem; opacity: .7; margin-top: 2rem; }
```

In `report.html.j2`, replace the whole block from `<style>` (line 7) through `</style>` (line 20) with the single line `<style>{{ css }}</style>`.

Replace `engine/corelata/render/html.py` with:

```python
"""HTML render (spec §9): one self-contained file with inline CSS, nothing fetched from anywhere,
safe to open on an air-gapped network. Paragraphs and list items carry data-claim-ids so the
review screen can highlight provenance; the visible superscripts appear only on request.

The stylesheet is `templates/report.css`, and the document's one `<style>` element holds exactly
its text: the web build hashes the same file into the review frame's policy (`style-src
'sha256-…'`, CRL-23), so the report needs no `'unsafe-inline'`. The report has no `style`
attributes."""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from corelata.render.outline import APPENDIX_TITLE, DEGRADATION_TITLE, build_outline
from corelata.schema import Finding, Report, Source
from corelata.standards.schema import ResolvedPack

_TEMPLATES = Path(__file__).parent / "templates"
_ENV = Environment(
    loader=FileSystemLoader(_TEMPLATES),
    autoescape=select_autoescape(default=True, default_for_string=True),
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
)
# Read as bytes and decoded, not read_text(): newline translation would change the hashed text.
REPORT_CSS = (_TEMPLATES / "report.css").read_bytes().decode("utf-8")


def render_html(
    report: Report,
    pack: ResolvedPack,
    sources: list[Source],
    *,
    with_claim_ids: bool = False,
    open_findings: list[Finding] | None = None,
) -> str:
    blocks = build_outline(report, pack, sources, open_findings=open_findings)
    return _ENV.get_template("report.html.j2").render(
        report=report,
        meta=report.metadata,
        blocks=blocks,
        with_claim_ids=with_claim_ids,
        appendix_titles=(DEGRADATION_TITLE, APPENDIX_TITLE),
        css=Markup(REPORT_CSS),  # our own file: not escaped (its quotes must stay quotes)
    )
```

In `engine/tests/render/golden/varna.html`, join lines 7 and 8: `<style>` followed by a newline and `:root { color-scheme: light dark; }` becomes `<style>:root { color-scheme: light dark; }` (the only change to the golden).

In `engine/pyproject.toml`, after `  "corelata/render/templates/**/*.j2",` add `  "corelata/render/templates/*.css",`.

- [ ] **Step 4: The web build hashes it**

Replace `web/vite.config.ts` with:

```ts
/// <reference types="vitest/config" />
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

/** The engine's report stylesheet: the rendered report's one `<style>` element holds exactly
 * this file's text (engine/corelata/render/html.py). */
const REPORT_CSS = fileURLToPath(
  new URL("../engine/corelata/render/templates/report.css", import.meta.url),
);
const REPORT_STYLE = "virtual:report-style";

/** `virtual:report-style` exports `REPORT_STYLE_HASH`, the CSP source (`sha256-<base64>`) of the
 * report stylesheet, computed from the file at build time: the review frame's policy allows that
 * one stylesheet and no other inline style (CRL-23, R-M14-2). */
function reportStyleHash(): Plugin {
  const resolved = `\0${REPORT_STYLE}`;
  return {
    name: "corelata-report-style-hash",
    resolveId: (id) => (id === REPORT_STYLE ? resolved : undefined),
    load(id) {
      if (id !== resolved) return undefined;
      this.addWatchFile(REPORT_CSS);
      const digest = createHash("sha256").update(readFileSync(REPORT_CSS)).digest("base64");
      return `export const REPORT_STYLE_HASH = ${JSON.stringify(`sha256-${digest}`)};\n`;
    },
  };
}

export default defineConfig({
  plugins: [react(), reportStyleHash()],
  server: {
    // `pnpm dev` talks to a local API (`make dev-stack`); server-sent events pass through as is.
    proxy: { "/api": { target: "http://127.0.0.1:8080", changeOrigin: false } },
  },
  test: {
    globals: true,
    testTimeout: 15_000,
    environment: "./src/test/jsdom-env.ts",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,tsx}"],
      exclude: [
        "src/api/schema.d.ts", // generated from schema/openapi.json; types only
        "src/main.tsx", // mounts the app into the page: exercised by the Playwright journeys
        "src/test/**", // the test harness itself
        "src/**/*.test.{ts,tsx}", // tests are not product code
      ],
      reporter: ["text", "lcov"],
      thresholds: { lines: 95, branches: 95, functions: 95, statements: 95 },
    },
  },
});
```

Create `web/src/report-style.d.ts`:

```ts
declare module "virtual:report-style" {
  /** The CSP source of the engine's report stylesheet, `sha256-<base64>`, computed from
   * engine/corelata/render/templates/report.css when the app is built (vite.config.ts). */
  export const REPORT_STYLE_HASH: string;
}
```

In `web/src/pages/review/frameBridge.ts`:

- Line 1, before the module comment: `import { REPORT_STYLE_HASH } from "virtual:report-style";` and a blank line.
- `installFrameBridge` gains a fifth parameter and sets it:

```ts
export function installFrameBridge(
  doc: Document,
  post: (message: FrameToHost) => void,
  listen: (handler: (message: HostToFrame) => void) => void,
  css: string,
  nonce: string,
): void {
  const style = doc.createElement("style");
  if (nonce) style.setAttribute("nonce", nonce); // the frame's policy allows this style by nonce
  style.textContent = css;
  doc.head.appendChild(style);
```

  (the rest of the function is unchanged).
- `FRAME_CSP` and its comment become:

```ts
/** The frame's own policy (R-M9-6, R-M14-2): nothing loads from anywhere; the bridge's script
 * and its highlight style run by nonce; the report's stylesheet is allowed by its hash, computed
 * at build time from the engine's file; no other inline script or style runs. A site proxy's
 * policy is inherited on top of this one (docs/operator-guide.md, section 6). */
export const FRAME_CSP = (nonce: string) =>
  `default-src 'none'; script-src 'nonce-${nonce}'; style-src '${REPORT_STYLE_HASH}' 'nonce-${nonce}'; img-src data:; connect-src 'none'`;
```

- In `bridgeScript`, the last string piece `` ` ${JSON.stringify(HIGHLIGHT_CSS)});</script>` `` becomes `` ` ${JSON.stringify(HIGHLIGHT_CSS)}, ${JSON.stringify(nonce ?? "")});</script>` ``.

- [ ] **Step 5: The image builds with it**

In `deploy/docker/app.Dockerfile`, the web stage's

```dockerfile
COPY web/ ./
RUN pnpm build
```

becomes

```dockerfile
COPY web/ ./
# The report stylesheet: the build hashes it into the review frame's policy (CRL-23).
COPY engine/corelata/render/templates/report.css /src/engine/corelata/render/templates/
RUN pnpm build
```

(`.dockerignore` already admits `engine/corelata/`.) In `deploy/tests/check-app-image.sh`, the package-data list's second line `  prompts/templates/gate/v1.j2 render/templates/report.html.j2 standards/packs/icd203-base/pack.yaml \` becomes the two lines

```sh
  prompts/templates/gate/v1.j2 render/templates/report.html.j2 render/templates/report.css \
  standards/packs/icd203-base/pack.yaml \
```

- [ ] **Step 6: Run the tests**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/render tests/test_invariants.py --no-cov -q`
Expected: all pass (`varna.html` golden included).

Run: `cd web && pnpm exec vitest run src/pages/review && pnpm lint && pnpm test && pnpm build && grep -c "sha256-" dist/assets/*.js`
Expected: `src/pages/review` 52 passed; lint clean; `168 passed`, thresholds held (`frameBridge.ts` 100%); the build prints the bundle, and grep finds the hash in it.

Run: `make test-engine && make deploy-check && docker build --target web -f deploy/docker/app.Dockerfile -t corelata-web-stage:check . && docker image rm corelata-web-stage:check`
Expected: engine `859 passed`; deploy-check clean (shellcheck of `check-app-image.sh`); the web stage builds (the airgap CI job builds the whole image and runs `check-app-image.sh`).

- [ ] **Step 7: Commit**

```bash
cat > <scratchpad>/m14-task5-commit.txt <<'EOF'
feat: hash the report stylesheet into the frame policy, drop unsafe-inline (CRL-23)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git add engine/corelata/render/templates/report.css engine/corelata/render/templates/report.html.j2 engine/corelata/render/html.py engine/pyproject.toml engine/tests/render/test_html.py engine/tests/render/golden/varna.html web/vite.config.ts web/src/report-style.d.ts web/src/pages/review/frameBridge.ts web/src/pages/review/frameBridge.test.ts deploy/docker/app.Dockerfile deploy/tests/check-app-image.sh
git commit -F <scratchpad>/m14-task5-commit.txt
```

---

### Task 6: A Playwright journey behind the guide's sample policy (CRL-23, part 2)

**Files:**
- Create: `api/csp_proxy.py`, `api/tests/test_csp_proxy.py`, `web/e2e/csp.spec.ts`
- Modify: `api/devstack.py` (after line 25; `config` lines 50-51; `main` lines 67-71, 95, 109-112), `web/playwright.config.ts` (whole file)

**Interfaces:**
- Consumes: Task 5's frame policy (the journey checks the hashed stylesheet and the nonce-bound highlight apply); `docs/operator-guide.md` §6's nginx line `add_header Content-Security-Policy "<policy>" always;`.
- Produces: `csp_proxy.SAMPLE_POLICY: str`, `csp_proxy.create_proxy(upstream: str, *, policy: str = SAMPLE_POLICY, transport: httpx.AsyncBaseTransport | None = None)` (an ASGI app), `csp_proxy.main(argv) -> int` (`--upstream URL --host H --port N`); `devstack.py --csp-proxy-port N --progress-poll-s S`; Playwright projects `chromium` and `csp-proxy` (port 8766).

- [ ] **Step 1: Failing tests**

Create `api/tests/test_csp_proxy.py`:

```python
import asyncio
from pathlib import Path

import httpx

from csp_proxy import SAMPLE_POLICY, create_proxy

GUIDE = Path(__file__).resolve().parents[2] / "docs" / "operator-guide.md"


def test_the_proxy_sets_the_operator_guides_sample_policy_word_for_word():
    guide = GUIDE.read_text(encoding="utf-8")
    assert f'add_header Content-Security-Policy "{SAMPLE_POLICY}" always;' in guide


async def upstream(scope, receive, send):
    """Echoes the request and sets a policy of its own, which the proxy must replace."""
    message = await receive()
    echo = "|".join(
        [
            scope["method"],
            scope["raw_path"].decode(),
            scope["query_string"].decode(),
            dict(scope["headers"]).get(b"x-remote-user", b"").decode(),
            message.get("body", b"").decode(),
        ]
    ).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 201,
            "headers": [
                (b"content-type", b"text/plain"),
                (b"content-length", str(len(echo)).encode()),
                (b"content-security-policy", b"default-src *"),
                (b"x-accel-buffering", b"no"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": echo})


async def test_the_proxy_forwards_the_request_and_adds_the_policy():
    proxy = create_proxy("http://app.test", transport=httpx.ASGITransport(app=upstream))
    transport = httpx.ASGITransport(app=proxy)
    async with httpx.AsyncClient(transport=transport, base_url="http://proxy.test") as client:
        response = await client.post(
            "/api/runs/x?limit=2", content=b"body", headers={"X-Remote-User": "ana"}
        )
    assert response.status_code == 201
    assert response.text == "POST|/api/runs/x|limit=2|ana|body"
    assert response.headers.get_list("content-security-policy") == [SAMPLE_POLICY]
    assert response.headers["x-accel-buffering"] == "no"


async def test_the_proxy_closes_its_client_at_shutdown():
    proxy = create_proxy("http://app.test", transport=httpx.ASGITransport(app=upstream))
    inbox: asyncio.Queue = asyncio.Queue()
    for kind in ("lifespan.startup", "lifespan.shutdown"):
        inbox.put_nowait({"type": kind})
    sent: list[str] = []

    async def send(message):
        sent.append(message["type"])

    await proxy({"type": "lifespan"}, inbox.get, send)
    assert sent == ["lifespan.startup.complete", "lifespan.shutdown.complete"]
```

Create `web/e2e/csp.spec.ts`:

```ts
import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";

// Runs in the `csp-proxy` project: every response comes through api/csp_proxy.py, which adds the
// operator guide's sample Content-Security-Policy (docs/operator-guide.md, section 6; CRL-23).
const GUIDE = readFileSync(new URL("../../docs/operator-guide.md", import.meta.url), "utf-8");
const SAMPLE = /add_header Content-Security-Policy "([^"]+)" always;/.exec(GUIDE)?.[1];

const PORT_TEXT = [
  "The port of Varna handles grain, containers and general cargo on Bulgaria's Black Sea coast.",
  "A second grain terminal is planned for 2027, doubling the port's grain handling capacity.",
  "Shippers expect waiting times at Varna to fall by a third once the terminal opens.",
].join("\n\n");
const STATEMENT = "Varna port capacity expansion matters to shippers";

test("a run, its progress and the claim highlight work under the guide's sample policy", async ({
  page,
  request,
}) => {
  expect(SAMPLE, "the guide's sample policy").toBeTruthy();
  const violations: string[] = [];
  page.on("console", (message) => {
    if (/Content Security Policy|Refused to|CSP violation/i.test(message.text()))
      violations.push(message.text());
  });
  await page.addInitScript(() => {
    document.addEventListener("securitypolicyviolation", (event) =>
      console.error(`CSP violation: ${event.violatedDirective} ${event.blockedURI}`),
    );
  });

  const home = await page.goto("/new");
  expect(home?.headers()["content-security-policy"]).toBe(SAMPLE);

  const project = await request.post("/api/projects", { data: { name: `CSP ${Date.now()}` } });
  expect(project.status()).toBe(201);
  const projectId: string = (await project.json()).id;
  const upload = await request.post(`/api/projects/${projectId}/sources`, {
    multipart: {
      file: { name: "port.txt", mimeType: "text/plain", buffer: Buffer.from(PORT_TEXT, "utf-8") },
    },
  });
  expect(upload.status()).toBe(201);
  const [source] = await upload.json();
  const run = await request.post("/api/runs", {
    data: {
      project_id: projectId,
      source_ids: [source.id],
      value_statement: STATEMENT,
      max_iterations: 1,
    },
  });
  expect(run.status()).toBe(202);
  const runId: string = (await run.json()).run_id;

  // Progress arrives over the event stream, through the proxy.
  await page.goto(`/runs/${runId}`);
  const review = page.getByRole("link", { name: "Review the report" });
  await expect(review).toBeVisible({ timeout: 90_000 });
  await review.click();

  const frame = page.frameLocator('iframe[title="Report"]');
  await expect(frame.locator("h1")).toBeVisible();
  // The report's own stylesheet applied (allowed by its hash): 46rem at 16px.
  await expect(frame.locator("body")).toHaveCSS("max-width", "736px");
  await page.getByRole("list", { name: "Claims" }).getByRole("button").first().click();
  // The bridge's highlight style applied (allowed by the nonce), on the claim the page chose.
  await expect(frame.locator(".corelata-highlight").first()).toHaveCSS(
    "background-color",
    "rgb(255, 243, 176)",
  );
  expect(violations, "no Content-Security-Policy violation").toEqual([]);
});
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd api && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/test_csp_proxy.py --no-cov -q`
Expected: collection fails with `ModuleNotFoundError: No module named 'csp_proxy'`.

- [ ] **Step 3: The proxy**

Create `api/csp_proxy.py`:

```python
"""A reverse proxy that adds the operator guide's sample Content-Security-Policy to every
response (docs/operator-guide.md, section 6), for the Playwright journey that pins the sample
(CRL-23, R-M14-2). `devstack.py --csp-proxy-port` starts it in front of the dev stack. It streams
bodies through as they come, so progress streams stay live. Development only: not in the image."""

import argparse
import sys
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import uvicorn

# Must equal the policy in the guide's nginx sample; tests/test_csp_proxy.py checks the two match.
SAMPLE_POLICY = (
    "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; connect-src 'self'; frame-ancestors 'self'"
)
# Headers that describe one hop, not the message (RFC 9110 section 7.6.1); the server sets its own.
HOP_BY_HOP = frozenset(
    {
        b"connection",
        b"keep-alive",
        b"proxy-authenticate",
        b"proxy-authorization",
        b"te",
        b"trailer",
        b"transfer-encoding",
        b"upgrade",
        b"host",
    }
)

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]


def create_proxy(
    upstream: str, *, policy: str = SAMPLE_POLICY, transport: httpx.AsyncBaseTransport | None = None
) -> Callable[[Scope, Receive, Send], Awaitable[None]]:
    client = httpx.AsyncClient(base_url=upstream, transport=transport, timeout=None)

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            while (message := await receive())["type"] != "lifespan.shutdown":
                await send({"type": "lifespan.startup.complete"})
            await client.aclose()
            await send({"type": "lifespan.shutdown.complete"})
            return
        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if not message.get("more_body"):
                break
        path = scope["raw_path"].decode("latin-1")
        if scope["query_string"]:
            path += "?" + scope["query_string"].decode("latin-1")
        request = client.build_request(
            scope["method"],
            path,
            headers=[(k, v) for k, v in scope["headers"] if k.lower() not in HOP_BY_HOP],
            content=body,
        )
        response = await client.send(request, stream=True)
        try:
            headers = [
                (k, v)
                for k, v in response.headers.raw
                if k.lower() not in HOP_BY_HOP and k.lower() != b"content-security-policy"
            ]
            headers.append((b"content-security-policy", policy.encode("ascii")))
            await send(
                {"type": "http.response.start", "status": response.status_code, "headers": headers}
            )
            async for chunk in response.aiter_raw():
                await send({"type": "http.response.body", "body": chunk, "more_body": True})
            await send({"type": "http.response.body", "body": b"", "more_body": False})
        finally:
            await response.aclose()

    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--upstream", required=True, help="e.g. http://127.0.0.1:8765")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args(argv)
    uvicorn.run(
        create_proxy(args.upstream),
        host=args.host,
        port=args.port,
        log_level="warning",
        timeout_graceful_shutdown=2,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: The dev stack starts it; Playwright uses it**

In `api/devstack.py`:

- After the `API = [...]` line add `CSP_PROXY = [sys.executable, str(Path(__file__).with_name("csp_proxy.py"))]`.
- `config` becomes `def config(work: Path, llm_port: int, web_dir: Path | None, progress_poll_s: float = 0.2) -> dict:` and its first line `    api: dict = {"progress_poll_s": progress_poll_s}`.
- After `parser.add_argument("--web-dir", type=Path, help="the built web app (web/dist)")` add

```python
    parser.add_argument(
        "--progress-poll-s",
        type=float,
        default=0.2,
        help="api.progress_poll_s: the poll while the API is not listening (default 0.2)",
    )
    parser.add_argument(
        "--csp-proxy-port",
        type=int,
        help="also serve the stack on this port behind the operator guide's sample CSP",
    )
```

- `path.write_text(yaml.safe_dump(config(work, llm, args.web_dir)), encoding="utf-8")` becomes

```python
        cfg = config(work, llm, args.web_dir, args.progress_poll_s)
        path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
```

- After `address = f"http://{args.host}:{args.port}"` add

```python
        if args.csp_proxy_port is not None:
            proxied = f"http://{args.host}:{args.csp_proxy_port}"
            procs.append(
                subprocess.Popen(
                    [*CSP_PROXY, "--upstream", address, "--host", args.host]
                    + ["--port", str(args.csp_proxy_port)]
                )
            )
            wait_for(f"{proxied}/api/health", 30, procs)
            print(f"The same stack behind the sample CSP: {proxied}", flush=True)
```

Replace `web/playwright.config.ts` with:

```ts
import { defineConfig, devices } from "@playwright/test";

const PORT = 8765;
const CSP_PORT = 8766; // the same stack behind the operator guide's sample policy (CRL-23)

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1, // one stack, one database
  timeout: 120_000,
  expect: { timeout: 30_000 }, // a run takes several seconds against the fake model
  reporter: process.env["CI"] ? [["list"], ["html", { open: "never" }]] : "list",
  use: { baseURL: `http://127.0.0.1:${PORT}`, trace: "retain-on-failure" },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] }, testIgnore: /csp\.spec\.ts/ },
    {
      name: "csp-proxy",
      use: { ...devices["Desktop Chrome"], baseURL: `http://127.0.0.1:${CSP_PORT}` },
      testMatch: /csp\.spec\.ts/,
    },
  ],
  webServer: {
    command:
      `cd ../api && uv run python devstack.py --host 127.0.0.1 --port ${PORT} ` +
      `--web-dir ../web/dist --csp-proxy-port ${CSP_PORT}`,
    url: `http://127.0.0.1:${CSP_PORT}/api/health`, // the proxy answers last
    timeout: 120_000,
    reuseExistingServer: false,
    stdout: "pipe",
    gracefulShutdown: { signal: "SIGTERM", timeout: 15_000 },
  },
});
```

`.github/workflows/ci.yml` does not change: the `e2e` job's `pnpm e2e` runs both projects.

- [ ] **Step 5: Run the tests**

Run: `cd api && uv run ruff check . && uv run ruff format --check . && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/test_csp_proxy.py --no-cov -q && make -C .. test-api`
Expected: ruff clean; `3 passed`; api `160 passed`.

Run: `cd web && pnpm lint && make -C .. e2e`
Expected: lint clean; `6 passed`, the last `[csp-proxy] › e2e/csp.spec.ts:11:1 › a run, its progress and the claim highlight work under the guide's sample policy`.

- [ ] **Step 6: Prove the journey catches a stale hash**

Run (then undo): `printf '/* drift */\n' >> engine/corelata/render/templates/report.css && (cd web && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres pnpm exec playwright test --project=csp-proxy); git restore engine/corelata/render/templates/report.css`
Expected: the journey FAILS at `toHaveCSS("max-width", "736px")` (`Received: "none"`): the dev stack renders the edited file while the build still carries the old hash. After the restore `git status --short engine` prints nothing. (Do not rebuild `web/dist` between the edit and the run.)

- [ ] **Step 7: Commit**

```bash
cat > <scratchpad>/m14-task6-commit.txt <<'EOF'
test: a Playwright journey behind the operator guide's sample CSP (CRL-23)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git add api/csp_proxy.py api/tests/test_csp_proxy.py api/devstack.py web/playwright.config.ts web/e2e/csp.spec.ts
git commit -F <scratchpad>/m14-task6-commit.txt
```

---

### Task 7: Docs

**Files:**
- Modify: `README.md` (before `## Development`), `docs/superpowers/specs/2026-10-12-corelata-v1-design.md` (§10.1 after line 436; §10.3 after line 480; §11 after line 519; §13 line 572), `docs/operator-guide.md` (lines 314-316; §6 lines 410-421; §11 row at line 630), `docs/m9-followups.md` (lines 20-25, 29)
- Create: `docs/m14-followups.md`

- [ ] **Step 1: README**

Insert before `## Development`:

```markdown
## M14: event-driven progress, a frame policy without inline styles, cursor paging

The last M9 follow-ups (CRL-22 to 24). The worker and the service announce every committed change
to a run with `NOTIFY corelata_run, '<run_id>'` in the transaction that writes it, and the API
holds one `LISTEN` connection, so a progress page updates as soon as a stage is recorded, and a
watched run that is not changing costs one read per heartbeat (`api.progress_poll_s` × 10, at
most 30 s) instead of one per `progress_poll_s`; while that connection is down the streams poll
every `api.progress_poll_s` as before and the API reconnects after 1, 2, 4, 8, 16, then every
30 s (CRL-22). The report frame's policy allows the report's stylesheet by its SHA-256 hash,
computed when the web app is built from the engine's `report.css`, and the bridge's highlight
style by the frame's nonce, so `style-src` no longer carries `'unsafe-inline'`; a Playwright
journey runs a report behind a proxy that adds the operator guide's sample policy to every
response, so the sample is a tested configuration (CRL-23). `GET /api/runs` answers
`{runs, next_before}` and takes `before=<next_before>`: keyset paging on `(created_at, id)`, so
the run list pages fifty at a time to a project's oldest run and the 500-run ceiling is gone
(CRL-24).

```

- [ ] **Step 2: Spec amendments**

§10.1: after the M10 amendments paragraph (ends "as well as by its 64 entries.") add a blank line and:

```markdown
M14 amendments: `GET /runs?project_id=&limit=&before=` answers `{runs, next_before}`: the runs
newest first by `(created_at, id)`, `limit` (default 100, at most 500) at a time; `next_before` is
an opaque cursor (`<created_at, ISO-8601 UTC>|<run_id>`) when more runs follow and `null` on the
last page, and `before=<next_before>` answers the runs after it, so a run created while a client
pages does not shift its pages; a malformed cursor is a 422 (CRL-24). The worker and the service
announce every committed change to a run's progress on the Postgres channel `corelata_run`
(payload: the run id) in the transaction that writes it; the API holds one `LISTEN` connection,
and the shared reader of a run's `GET /runs/{id}/events` streams reads it on a notification, with
a heartbeat every `api.progress_poll_s` × 10 (at most 30 s); while that connection is down it
reads every `api.progress_poll_s` and reconnects after 1, 2, 4, 8, 16, then every 30 s (CRL-22).
```

§10.3: after the paragraph that ends "polling backs off to 15 s (M9)." add a blank line and:

```markdown
M14 amendments: the frame's policy allows the report's stylesheet by its SHA-256 hash, computed
when the web app is built from the engine's `render/templates/report.css` (the report's one
`<style>` element holds exactly that file), and the bridge's script and highlight style by the
per-render nonce: `style-src` has no `'unsafe-inline'`, and the report has no `style` attributes
(CRL-23). The run list pages fifty at a time by the API's cursor to the project's oldest run,
with no ceiling (CRL-24).
```

§11: after the paragraph that begins "Strict pydantic (`extra=forbid`)." add a blank line and:

```markdown
M14 amendment (CRL-22): `api.progress_poll_s` (default 1.0) is the progress streams' fallback:
the interval while the API's `LISTEN` connection is down, and the base of the heartbeat while it
is up (× 10, at most 30 s).
```

§13: after the bullet `- **Playwright**: the three screens against the fake model and a seeded database.` add a blank line and (indented two spaces, as the M6/M12/M13 amendments under the scenario bullet are):

```markdown
  *M14 amendment (CRL-23):* one journey runs behind `api/csp_proxy.py`, a proxy in front of the
  dev stack (`devstack.py --csp-proxy-port`) that adds the operator guide's sample
  `Content-Security-Policy` to every response; it follows a run's progress, highlights a claim in
  the report frame, and fails on any policy violation. A pytest test checks that the proxy's
  policy is the guide's sample word for word.
```

- [ ] **Step 3: Operator guide**

In section 5, "Uploads and the API", replace

```markdown
`max_upload_mb` is the size limit for one uploaded source (a reverse proxy in front must allow at
least as much, section 6). `progress_poll_s` is how often the API checks a running report for its
progress streams (once per run, however many analysts watch it). `auth` is explained in section 6.
```

with

```markdown
`max_upload_mb` is the size limit for one uploaded source (a reverse proxy in front must allow at
least as much, section 6). `auth` is explained in section 6.

The worker tells the API about every change to a run through the database (Postgres
`LISTEN`/`NOTIFY`), so a progress page updates as soon as a stage is recorded; the API also reads
each watched run every `progress_poll_s` × 10 seconds (at most 30) in case a message was lost.
`progress_poll_s` (default 1.0) is how often it reads instead while its listening connection is
down, after a database restart for example; it reconnects after 1, 2, 4, 8, 16 and then every 30
seconds, and `docker compose logs api` shows `progress listener lost the database` and
`progress listener connected`. A connection pooler in transaction mode (PgBouncer) between the
API and Postgres passes no notifications: connect the API to Postgres directly, or progress shows
only at the heartbeat.
```

In section 6, "Content-Security-Policy", replace

```markdown
inside a sandboxed frame that carries its own policy (`default-src 'none'`, its one script bound by
a nonce, inline styles only), so nothing in a report can load or send anything.
```

with

```markdown
inside a sandboxed frame that carries its own policy (`default-src 'none'`; its one script and its
highlight style bound by a nonce; the report's stylesheet allowed by its SHA-256 hash; no other
inline script or style), so nothing in a report can load or send anything.
```

and

```markdown
own nonce is generated in the browser, so no proxy policy can name it. If a site policy is
required, start from
```

with

```markdown
own nonce is generated in the browser, so no proxy policy can name it. If a site policy is
required, start from this one, which Corelata's end-to-end tests run the review screen behind
(`api/csp_proxy.py`):
```

The nginx line itself does not change by one character (`api/tests/test_csp_proxy.py` and `web/e2e/csp.spec.ts` read it).

In section 11, replace the row

```markdown
| Clicking a claim does not highlight it in the report; the console shows "Refused to execute inline script" | A proxy `Content-Security-Policy` without `'unsafe-inline'`, or one that lists a nonce or hash, reaches the report frame. See section 6, "Content-Security-Policy". |
```

with

```markdown
| Clicking a claim does not highlight it in the report, or the report shows without its layout; the console shows "Refused to execute inline script" or "Refused to apply inline style" | A proxy `Content-Security-Policy` whose `script-src` or `style-src` lacks `'unsafe-inline'`, or lists a nonce or hash, reaches the report frame. Start from the sample policy in section 6, "Content-Security-Policy": the end-to-end tests run behind it. |
```

- [ ] **Step 4: Follow-ups**

In `docs/m9-followups.md`, append to these bullets (after the bullet's last word, on its last line):

- "Should fix soon", the bullet ending "remove `api.progress_poll_s`.": ` — **closed in M14** (CRL-22: \`RunListener\`; \`progress_poll_s\` is now the fallback)`
- the bullet ending "nonce on the bridge's style element.": ` — **closed in M14** (CRL-23)`
- the bullet ending "e2e run behind a proxy that sets it would pin it.": ` — **closed in M14** (CRL-23: \`api/csp_proxy.py\`, \`e2e/csp.spec.ts\`)`
- "Later", the bullet "Offset or cursor paging for `GET /api/runs` once a project passes 500 runs.": ` — **closed in M14** (CRL-24)`

Nothing else in the file changes; the `ReviewActions` bullet stays open.

Create `docs/m14-followups.md`:

```markdown
# M14 follow-ups

## Divergences from Coglossa

- `RunListener` (one LISTEN connection per API process) and the wake-ups in `ProgressFeed` —
  **backport candidate**, with CGL-18 (the M9 feed): Coglossa's events route still polls per
  stream.
- `runs.notify_run` on every write to a run, `RUN_CHANNEL`, `corelata.testing.postgres.RunChannel`
  — Corelata only until the feed is backported.
- Keyset paging of `GET /api/runs` (`RunPage`, `before`, `next_before`) — Corelata only.
- The report stylesheet as a file hashed by the web build — Corelata only (Coglossa has no report
  frame).

## Spec deviations

- None. §10.1, §10.3, §11 and §13 carry M14 amendments.

## Rulings during execution

- How the plan applied R-M14-1 to R-M14-4, and the rulings it added (R-M14-5 to R-M14-13), are
  in its Global Constraints. Number new ones from R-M14-14.

## Should fix soon

- None.

## Later

- Postgres fails a transaction at commit when its notification queue is full (8 GB by default;
  only a session that LISTENs and holds a transaction open stops it draining). The API's
  listener is autocommit, so only a foreign listener could cause it; the worker would then fail
  to commit a stage. `notify_run` swallows statement errors, not this one.
- Behind a transaction-pooling PgBouncer the API's LISTEN connection connects but receives
  nothing; progress then arrives at the heartbeat (up to 30 s). A self-NOTIFY at connect that
  must come back would detect it, if a site puts a pooler in front of Postgres.
- The bridge's script and highlight style are fixed text too; hashing them as the report's
  stylesheet is hashed would let a strict site policy name all three and drop `'unsafe-inline'`
  from the proxy's policy (a proxy cannot name the frame's nonce, which the browser generates).
- Deleting a project does not announce its runs; a progress page open on one of them says
  "deleted" at the next heartbeat (at most 30 s).
- `GET /api/runs` sorts a project's runs after the `project_id` index; a `(project_id,
  created_at, id)` index would make each page an index range scan once a project holds tens of
  thousands of runs.
- `RunList.test.tsx` renders 520 rows in jsdom to page past 500 (about 1 s); `docs/m10-followups.md`'s
  note on the old ceiling test applies to it.
- A pre-M14 run's stored `report.html` differs from its claim-id re-render by the newline that
  followed `<style>` (R-M14-11); nothing compares them.
```

- [ ] **Step 5: Check nothing else moved**

Run: `make lint && git diff --stat main -- docs/m10-followups.md docs/m11-followups.md docs/m12-followups.md docs/m13-followups.md engine/corelata/bench .github`
Expected: lint clean; the diff prints nothing.

Run: `cd api && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/test_csp_proxy.py --no-cov -q`
Expected: `3 passed` (the guide's nginx line is intact).

- [ ] **Step 6: Commit**

```bash
cat > <scratchpad>/m14-task7-commit.txt <<'EOF'
docs: M14 README section, spec amendments, operator guide, follow-ups

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git add README.md docs/superpowers/specs/2026-10-12-corelata-v1-design.md docs/operator-guide.md docs/m9-followups.md docs/m14-followups.md
git commit -F <scratchpad>/m14-task7-commit.txt
```

---

## Final verification (after the whole-branch review)

```bash
make lint
make test-engine    # 859 passed
make test-api       # 160 passed
make test-web       # 168 passed
make e2e            # 6 passed: five chromium journeys and the csp-proxy journey
make deploy-check
make schema && git status --short schema web/src/api/schema.d.ts   # no output: committed in Task 3
git diff --name-only main -- schema                                # only schema/openapi.json
grep -n '^version' engine/pyproject.toml                            # still 0.1.2
```

CI must be green on all six jobs (engine, api, web, e2e, deploy, airgap) and `ci-status` before the merge. The `airgap` job builds the image with the new web-stage `COPY` and runs `check-app-image.sh`, which now checks `render/templates/report.css`.

## Live rehearsal (the controller runs this after the merge; not a task)

Dev stack with notifications (from the repository root, `make db-up` first; `web/dist` built by `make e2e` or `cd web && pnpm build`):

- [ ] `cd api && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run python devstack.py --port 8080 --web-dir ../web/dist --progress-poll-s 5 --csp-proxy-port 8081`. With `progress_poll_s` 5 the fallback poll is 5 s and the heartbeat 30 s, so a stage that shows within a second of being recorded came by notification. The API log prints `progress listener connected` once.
- [ ] `psql postgresql://corelata:corelata@127.0.0.1:55433/postgres -c "SELECT datname, state, query FROM pg_stat_activity WHERE application_name = 'corelata-api-listen'"` shows one row on the dev stack's `corelata_test_…` database with `query` `LISTEN "corelata_run"`.
- [ ] Open http://127.0.0.1:8080, start a run (Varna example: `docs/examples/varna-port.txt`), and watch the progress page: each stage appears within about a second of the worker's log line for it (the worker logs `run … finished: completed` at the end), never 5 or 30 s later.
- [ ] Kill the listener: `psql … -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE application_name = 'corelata-api-listen'"`. The API logs `progress listener lost the database: …; polling every 5.0 s, reconnecting in 1.0 s`, then `progress listener connected` about a second later. Start a second run: its stages still appear within about a second.
- [ ] Behind the proxy: open http://127.0.0.1:8081, review the run. The developer tools (F12) show the response header `Content-Security-Policy` equal to the guide's sample, no "Refused to …" console line, the report laid out (centred, Georgia), and a clicked claim highlighted in yellow.
- [ ] Paging past 50: create 60 runs and page the list.

```sh
PID=$(curl -s -X POST localhost:8080/api/projects -H 'content-type: application/json' -d '{"name":"paging"}' | jq -r .id)
SID=$(curl -s -F file=@docs/examples/varna-port.txt localhost:8080/api/projects/$PID/sources | jq -r '.[0].id')
for i in $(seq 60); do curl -s -o /dev/null -X POST localhost:8080/api/runs -H 'content-type: application/json' -d "{\"project_id\":\"$PID\",\"source_ids\":[\"$SID\"],\"value_statement\":\"Varna port capacity expansion matters to shippers\"}"; done
curl -s "localhost:8080/api/runs?project_id=$PID&limit=50" | jq '{n: (.runs | length), next_before}'
```

  Expect `n` 50 and a `next_before` like `2026-…Z|<uuid>`; `curl -s "localhost:8080/api/runs?project_id=$PID&limit=50&before=<that>" | jq '.runs | length, .next_before'` gives 10 and `null`. In the browser, the New run screen for project "paging" lists 50 runs, Show more adds 10 and disappears; the network tab shows `before=` on the second request.
- [ ] `make e2e` on the merged main: 6 passed.

Regression against OpenRouter (the CRL-1 configuration, as in the M13 rehearsal):

- [ ] `corelata doctor --config <openrouter.yaml>`: every line PASS, as in M13 (doctor is unchanged).
- [ ] `corelata bench --config <openrouter.yaml> --scenarios real --out bench-m14-real/`: compare with the M13 baseline below; M14 changes nothing a model sees, so a difference is model variance.
- [ ] Fill in the table, add it to Jira CRL-22, CRL-23 and CRL-24 (close them with the rehearsal evidence: the listener log lines, the proxy's header and the paging output); then cut 0.1.3.

| Measure | M13 baseline (2026-10-17) | M14 |
|---|---|---|
| `doctor` | all PASS | |
| Real set: full agreement | 6/8 | |
| Gate agreement | 7/8 | |
| Rule-failure agreement | 3/3 | |
| Duration | 83 s | |
| Stage to progress page (notification) | n/a | |
| Listener reconnect after `pg_terminate_backend` | n/a | |
| CSP journey and manual check behind the sample policy | n/a | |
| 60 runs paged (50 + 10, `next_before` null at the end) | n/a | |
