# M16 Review and Discovery Decisions, Review Minors and Rehearsal Findings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close Jira CRL-21 (the owner's three decisions of 2026-10-18) and CRL-37 (the M14/M15 review minors), and fold in the CRL-1 VM rehearsal findings: (1) an accepted report can no longer be returned: the API answers 409 `run <id> was accepted; start a new run to change it`, the CLI says the same, and the decision is taken under the run's row lock; (2) the discovery screen stops polling 10 minutes after the discovery was created, measured on the server's clock, and says so; the discovery lives in the URL so a reload reads it again; (3) discovery polling backs off 1, 2, 4 s, then every 5 s; (4) the review minors: notification and listener tests wait for what they expect, the `broken` patch hits the call it means, the web suite fails on an unmocked request and the seven requests CI printed are mocked, `frameBridge.test.ts` resolves `report.css` from its own file, `restore.sh` removes psql's message file on every exit including a signal, the API's lifespan does not swallow its own cancellation and survives a dead listener, and the development CSP proxy answers 502 and is pinned to stream; (5) the rehearsal's guide findings (the demo as an installation, `CORELATA_HTTP_BIND`, the HTTP API, backups outside the bundle, old images after an upgrade), a run error that names an unreachable model server, and a Dependabot ignore for `@types/node` majors.

**Architecture:** Engine: `service.review_run` refuses a `return` when the run's stored `review_state` (read by `get_run(..., lock=True)`, which re-reads the row under `FOR UPDATE`) says `accepted`; nothing else in the review rules moves. `llm/openai_compat.OpenAICompatBackend._send` maps `httpx.ConnectError` to `<backend>: model server unreachable (<base_url>): ConnectError: …`. Web: `api/discoveries.ts` keeps the read's age (`DiscoveryRead.age_ms`, from the answer's `Date` header minus `created_at`), `discoveryPollInterval` returns `false` once it is 10 minutes or more and caps at 5 s, `Suggestions` shows the fixed message in its `role="status"` paragraph, and `ValueStatement` keeps the discovery id in `?discovery=` (replace navigation). Tests: `RunChannel.received(count)` and `received_until(payload)` wait for what is expected; `setup.ts` records msw's unhandled requests and fails the test. Deploy/API: one `on_exit` EXIT trap in `restore.sh` installed before `mktemp`, with INT/TERM traps that exit; `corelata_api.app.stop_listener`; a 502 branch in `csp_proxy.py`. Docs: README, spec §10.1/§10.3, operator guide §3, §4, §7, §9, §10, §11, follow-ups.

**Tech Stack:** Python 3.12, SQLAlchemy 2 async + psycopg 3.3, FastAPI, httpx; React 19, React Router 7, TanStack Query 5, Vitest 4, msw 2.15, Playwright; bash (3.2 on macOS, 5.2 on CI), shellcheck 0.10.0 (pinned container); Dependabot; Markdown docs.

**Spec:** `docs/superpowers/specs/2026-10-12-corelata-v1-design.md` — §10.1 (the review route, M4a/M9/M14/M15 amendments), §10.3 (New run screen discovery, Review screen, M9/M15 amendments), §12 (packaging, backups, restore). Ticket texts: Jira CRL-21 (its last comment, "Decided … Implemented in M16", holds the behaviour and the copy), CRL-37 (the minors in its description), CRL-1 (the VM rehearsal report's "Guide findings" G1 to G5 and product defect D2). Context: `docs/m9-followups.md` (CRL-21's origin), `docs/m14-followups.md` and `docs/m15-followups.md` (the minors), `docs/superpowers/plans/2026-10-18-m15-return-recovery-doctor-repair-deploy-diagnostics.md` (R-M15-1 to R-M15-22, the return rules this plan builds on).

## Global Constraints

- 95% branch coverage for `engine` and `api` (`--cov-fail-under=95`), `filterwarnings = ["error"]`; `ruff check` and `ruff format --check` clean (line length 100). Vitest 95% on lines, branches, functions and statements; `pnpm lint` (eslint, prettier, `tsc --noEmit`) clean; `pnpm build` clean. Playwright journeys stay green (`make e2e`: 6, one journey gains a reload step). `ci-status` is the required check.
- Python tests that touch Postgres run against the dev database (`make db-up`; `CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres`). A single test file: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/x.py --no-cov -q` (and the same from `api/`). Full gates: `make test-engine`, `make test-api`, `make test-web`, `make lint`, `make e2e`, `make deploy-check`. Do not run the full pytest and Vitest suites concurrently.
- **No schema change, no migration, no config change.** `make schema` leaves `schema/` and `web/src/api/schema.d.ts` unchanged (verified on the scratch copy). Do not edit the docstrings of `ReviewState` (`engine/corelata/schema/progress.py`) or of the review route (`api/corelata_api/routes/runs.py`): both are descriptions in `schema/openapi.json`. The only API-visible change is a new 409 detail text on `POST /api/runs/{id}/review`; no route, request or response model changes, and `api/tests/test_openapi.py` is untouched. Alembic head stays `0005`.
- Web tests mock every request with msw; after Task 4 `web/src/test/setup.ts` fails any test that makes an unmocked request. Poll intervals are read through `web/src/test/poll.ts` (`runRefetchInterval`, and `discoveryRefetchInterval` from Task 2), never fake timers. Fixtures live in `web/src/test/fixtures.ts`.
- Shell scripts pass the pinned shellcheck (`make deploy-check`); `deploy/tests/test-restore.sh` runs `restore.sh` against its stub `docker` and must pass on macOS bash 3.2 and on Linux bash 5 (`docker run --rm -v "$PWD/deploy:/d" ubuntu:24.04 /d/tests/test-restore.sh`).
- Commit messages end with exactly these two lines, nothing after them (R-M16-6):
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`
  `Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK`
  Write the message to a uniquely named scratchpad file and `git commit -F FILE`. Never `git stash`. Never `git add .` (the SDD workspace is not ignored).
- Version stays `0.1.4` (`engine/pyproject.toml`, `tests/test_version.py`); the controller cuts 0.1.5 after the live rehearsal.
- Rulings (record in the SDD ledger, carried here). R-M9-1 to R-M9-12, R-M10-1 to R-M10-10, R-M11-1 to R-M11-8, R-M12-1 to R-M12-10, R-M13-1 to R-M13-12, R-M14-1 to R-M14-15 and R-M15-1 to R-M15-22 stay in force, except where R-M16-1 adds a refusal and R-M16-3 replaces R-M9-9's cap.
  - **R-M16-1 (CRL-21.1, no return after accept).** Once a run's stored decision is an accept (`ReviewState.decision == accepted`), `review_run(action=return)` raises the conflict error (HTTP 409) with the text `run <id> was accepted; start a new run to change it`; the CLI's `review --return` prints the same and exits as other conflicts do. Unchanged from M15: accept after a freed return (failed, cancelled, gate-rejected rerun) is allowed; a live or completed return still wins over a later accept, so an accept recorded after such a return leaves the decision "returned" and a later return is refused by the existing live-return rule, not this one. Accept after accept stays as today (read the code; if it is allowed, keep it). The Review screen already shows no actions after an accept: verify, no web change expected beyond tests. The rule must hold under the parent's row lock like the live-return check (decide on the stored decision read inside the locked transaction).
  - **R-M16-2 (CRL-21.2, stuck-discovery ceiling).** The discovery screen stops polling once the discovery has been running for 10 minutes measured from the discovery's server-side `created_at` (or the equivalent field; do not use the page's open time, so a reload does not restart the clock); it shows, in a polite live region, exactly: `Discovery has not finished after 10 minutes. It may still be running, or its worker may have stopped. Reload this page to check again, or start a new discovery.` A reload reads once and, if still running past 10 minutes, shows the message again without polling. A terminal state seen at any time shows as today. Pin it with poll-interval tests through `web/src/test/poll.ts` (never fake timers), using a fixture `created_at` older than 10 minutes.
  - **R-M16-3 (CRL-21.3, discovery poll cap 5 s).** Back-off 1, 2, 4 s, then every 5 s (was 1, 2, 4, 8, then 15 s). Update the constant, its tests, and any docs that state 15 s (README M9, spec §10.3 amendment, operator guide if it mentions it).
  - **R-M16-4 (CRL-37).** Each item in CRL-37's description, as written there; tests only where it says test, behaviour changes only in `restore.sh` (trap chained with the existing `trap restart EXIT`; every exit path removes the temp file, including a signal; extend `test-restore.sh`), `api/corelata_api/app.py` (the lifespan must not swallow a cancellation of itself: cancel the listener, await it, suppress only the listener's own `CancelledError`; a listener that ended with an exception is logged and the rest of the shutdown still runs; pin both with tests) and `api/csp_proxy.py` (502 with a short text body on an upstream `httpx.HTTPError`; a test that a two-chunk upstream body reaches the client as two chunks, gated so a buffered read would fail it). The msw notices: mock the missing requests in those tests so a full `pnpm test` prints no "unhandled request"; then make `web/src/test/setup.ts` fail on an unhandled request in every test if it does not already (find why these notices are printed and fix the cause).
  - **R-M16-5 (scope, gates, docs, release).** No migration, no config change; `make schema` is a no-op. Engine and api coverage 95%, Vitest 95%, Playwright 6 green, `ci-status` required. Docs: README M16 section; spec amendments (§10.1 return-after-accept, §10.3 discovery ceiling and cap); operator guide where it describes reviews or discovery; `docs/m15-followups.md` and `docs/m14-followups.md` items struck "— **closed in M16** (CRL-37)"; CRL-21's entries in `docs/m9-followups.md` struck; new `docs/m16-followups.md`. Version stays 0.1.4; the controller cuts 0.1.5 after the rehearsal.
  - **R-M16-6 (attribution).** Every commit message ends with exactly the two lines above.
  - **R-M16-7 (CRL-1 G1, the demo as an installation: document the `.env` route).** The guide gains the route the VM rehearsal used: after `./install.sh`, the line `COMPOSE_FILE=compose.yaml:compose.demo.yaml` in `.env` makes every plain `docker compose` command in the directory, and `backup.sh` and `restore.sh`, act on the demo stack, and section 10 carries it over with `.env`. The guide says that this stack reads `config/corelata.demo.yaml` (the overlay sets `CORELATA_CONFIG`; edit nothing there, `install.sh` checks it against `SHA256SUMS`) and that its Compose project is `corelata-demo`, so its volumes are `corelata-demo_pgdata` and `corelata-demo_files`, not the names section 9 gives. Option two (one project for both) is rejected: the overlay's own project is what keeps a demo's placeholder reports out of a real installation's volumes (section 4 promises that), and changing it would move the demo's volumes for every existing user. No compose file changes, so no CI change; the air-gap test already runs install, backup, a second-site upgrade and a restore with `compose.demo.yaml` in `COMPOSE_FILE` (exported, `deploy/tests/airgap-test.sh` step 4), and the live rehearsal runs the documented `.env` route. If wrong: the paragraph goes; nothing else depends on it.
  - **R-M16-8 (CRL-1 G2).** Section 3 step 5 and the section 11 "Port 8080 is taken" row name `CORELATA_HTTP_BIND=127.0.0.1` (publish on the loopback address only, behind a proxy or an SSH tunnel) beside `CORELATA_HTTP_PORT`; `deploy/compose.yaml` publishes `${CORELATA_HTTP_BIND:-0.0.0.0}:${CORELATA_HTTP_PORT:-8080}:8080` and `check_compose.py` already pins both.
  - **R-M16-9 (CRL-1 G3, verified).** Section 7 gains one paragraph on the HTTP API: everything the web app does is under `/api`; `GET /api/openapi.json` describes it, behind the same sign-in (`api/corelata_api/app.py` mounts it on the protected router), and `GET /api/health` needs no sign-in. Verified in `api/corelata_api/routes/runs.py`: `GET /api/runs` requires `project_id` (a required `uuid.UUID` query parameter, so its absence is a 422) and answers `{runs, next_before}`, `limit` default 100, at most 500, `before=<next_before>` for the next page.
  - **R-M16-10 (CRL-1 G4, verified).** `backup.sh` takes a directory (`./backup.sh [DIR]`, default `./backups`; it creates it). Section 10 step 1 becomes `./backup.sh /srv/backups/corelata` (outside the bundle directory, which an upgrade leaves behind), and the step says to keep the old bundle's tarball and `.sha256`; "Going back" names that directory, and notes that `./install.sh` in the old directory loads the old image again if it was removed.
  - **R-M16-11 (CRL-1 G5).** Section 10 gains a step 7 after the crontab step (not inside step 6, which is about the crontab): once the new version works, `docker image ls corelata/app` and `docker image rm corelata/app:<old version>`; a note that `postgres:16-alpine` is one tag that a newer bundle may load with a different image, which leaves the old image untagged (`<none>` in `docker image ls`), removable with `docker image prune`.
  - **R-M16-12 (CRL-1 D2, one place exists).** Every model request goes through `OpenAICompatBackend._send` (`engine/corelata/llm/openai_compat.py`), which today turns every `httpx.TransportError` into `<backend>: <Type>: <message>`. `httpx.ConnectError` (refused, not listening, a name that does not resolve) gets its own branch before it: `<backend>: model server unreachable (<base_url without credentials or trailing slash>): ConnectError: <message>`, still a `TransientBackendError` (retried as before). The demo's rerun error becomes `demo: model server unreachable (http://fake-openai:8000/v1): ConnectError: [Errno -3] Temporary failure in name resolution`. Other transport errors keep their text. Doctor's own `/models` probe (`doctor.py`) uses its own client and is unchanged; its test completion goes through the backend and gains the clearer text.
  - **R-M16-13 (Dependabot).** `.github/dependabot.yml`'s npm block gains `ignore: - dependency-name: "@types/node" update-types: ["version-update:semver-major"]`, mirroring the docker block: CI (`node-version: "22"`) and the image (`node:22-bookworm-slim`) pin Node 22, so `@types/node` majors follow the runtime, not npm.
  - Rulings this plan adds (from reading the code at 6aba4ed and applying Tasks 1-6 to a scratch copy of the repository: engine 904 passed (890 before), coverage 98.4%; api 169 (165), 99.7%; web 192 Vitest (182), 98.4/95.9/99.6/99.5%, no msw notice; e2e 6 passed; ruff, `pnpm lint` and `pnpm build` clean; `make schema` a no-op; `make deploy-check` clean, `test-restore.sh` 17 ok lines on bash 3.2 and on `ubuntu:24.04` bash 5; each new test of Tasks 1, 3, 5 and 6 seen failing against today's code):
    - **R-M16-14 (CRL-21.2, the discovery lives in the URL; contradicts the brief).** R-M16-2's "a reload reads once" cannot happen today: `ValueStatement` keeps the discovery id in React state, so a reload forgets it and the screen shows no discovery at all. The id moves to the New run screen's URL, `?project=<id>&discovery=<id>` (the screen already keeps the project there, M4b), written with replace navigation so Back does not step through discoveries; "Suggest value" replaces it, and choosing another project drops it (`NewRunPage.changeProject` sets `{project}` only). `ValueStatement`'s tests render inside a router (`renderRoute` in `web/src/test/render.tsx`); the Playwright journey reloads after the suggestions show. If wrong: a reload loses the discovery, and the message's "reload this page to check again" misleads.
    - **R-M16-15 (CRL-21.2, which clock).** The age is the server's time minus `created_at`, both from the API host: `useDiscovery` reads the answer's `Date` header (uvicorn sets it) and stores `age_ms` with the view (`DiscoveryRead`); without a parseable header it uses the browser's clock. A workstation whose clock is ten minutes ahead would otherwise show the message on the first read and never poll (pinned both ways). The ceiling and the interval are pure functions of the stored read, so the render and the refetch interval always agree; each read is a new object (its `age_ms` differs), so the screen re-renders on every poll. `discoveryView()`'s fixture `created_at` becomes "now" (a fixed 2026-10-13 date would be past the ceiling); `minutesAgo(n)` makes an old one.
    - **R-M16-16 (CRL-21.1, where the check sits).** The order in `review_run` becomes: the run must be completed (409), a return needs a note (422), the stored decision must not be an accept (409, new), then the live-return rule (409). A note-less return on an accepted run therefore answers 422 first, as today's API test expects for any note-less return. The check reads `run.review_state`, the row `get_run(..., lock=True)` re-reads under `FOR UPDATE` with `populate_existing`, so a return that waited for an accept's lock sees the committed accept (pinned with a held accept and `pg_stat_activity`). The stored decision is "accepted" only when no live return exists (R-M15-10), so the new check never pre-empts the live-return message.
    - **R-M16-17 (CRL-21.1, the Review screen).** "Shows no actions" reads as today's behaviour: after an accept both **Accept** and **Return with note** stay rendered and disabled (`ReviewActions`, `decided`), as after a live return. No web code change; a new test pins that a page opened before another reviewer accepted gets the 409 text inside the Return dialog, re-reads the run (R-M15-21) and then shows "Accepted" with both buttons disabled.
    - **R-M16-18 (CRL-21.2, the copy is corrected; controller ruling).** The copy agreed in CRL-21 said "The worker marks a stalled discovery as failed on its next sweep", which is not always true: the sweep (`worker/sweep.py`) fails a discovery only when its job is gone; a discovery whose worker died is re-queued after `worker.stalled_after_s` (900 s by default, 120 s in the demo) and runs again, and nothing sweeps while no worker runs. The controller proposed that copy and the owner accepted "a 10 minute ceiling and a message", so the message is corrected to say only what is true: `Discovery has not finished after 10 minutes. It may still be running, or its worker may have stopped. Reload this page to check again, or start a new discovery.` (R-M16-2 and every test use this text.) A per-discovery deadline in the worker goes to `docs/m16-followups.md` ("Later"). If wrong: one string and its tests change back.
    - **R-M16-19 (CRL-37, why msw printed and the tests passed).** `onUnhandledRequest: "error"` (already set) only prints the request and makes that one `fetch` reject; the component shows its network error and the test passes. `setup.ts` now passes a callback that records `METHOD /path` and calls msw's `print.error()`, and fails the test in `afterEach` (after `cleanup()`), or the file in `afterAll` for a request that lands after the last test. The notices are timing-dependent: the loaded scratch machine printed none, main's CI log (run 39173635601) printed seven, all fixed in Task 4: `GET /api/projects` in three Layout tests, `GET /api/packs/icd203-base/resolved` in two AuditTab tests, `GET /api/runs/<id>/claims/c1` in one ReviewPage test, `GET /api/runs/<id>` in one NewRunPage test. With the recorder, six of the seven failed locally before the fix.
    - **R-M16-20 (CRL-37, restore.sh's one handler).** "Chained with `trap restart EXIT`" is done by one handler: `on_exit` (it removes psql's message file if one is set, then does what `restart` did) is installed before the `mktemp`, with `trap 'exit 130' INT` and `trap 'exit 143' TERM` so a signal runs it; the later `restart` function and its `trap` line go, `stopped=true` stays where it was. `mktemp` gets an explicit template, `"${TMPDIR:-/tmp}/corelata-restore.XXXXXX"`: macOS's bare `mktemp` ignored `TMPDIR` on the scratch run, and the test needs a directory it can watch. The test runs the restore under `set -m`, so it has a process group of its own, and the stub `docker` signals that group (`kill -TERM 0`) from inside the schema query, as a signal reaches every process of a foreground job. It sends TERM, not INT: a test script started where SIGINT is ignored on entry (a background job, a process substitution; seen on the scratch copy) passes that disposition on, and bash can neither trap nor reset it, so an INT case would be flaky; `restore.sh` traps INT the same way, and the rehearsal presses Ctrl-C. Against today's trap layout the new case fails on both bash 3.2 and bash 5 (`FAIL: TERM: psql's message file was left behind`).
    - **R-M16-21 (CRL-37, the lifespan).** `corelata_api.app.stop_listener(task)` cancels and awaits the listener; a `CancelledError` is suppressed only when the awaiting task is not itself being cancelled (`asyncio.current_task().cancelling()`), and any other exception is logged at ERROR, `progress listener had stopped with an error`, with its traceback. The lifespan's `finally` runs it inside `try/finally`, so `feed.close()` and `db.dispose()` run whether the listener died or the shutdown itself was cancelled, and the cancellation then propagates. Both pinned against a real lifespan; both tests fail against today's code.
    - **R-M16-22 (CRL-37, the proxy's 502).** The text is `bad gateway: <upstream> did not answer (<ExceptionType>)`, `text/plain; charset=utf-8`, with the sample policy header like every other answer. The streaming test drives the ASGI app directly with an upstream stream that yields its second chunk only after the proxy sent the first to the client; a buffered proxy times out (checked on the scratch copy).
    - **R-M16-23 (CRL-37, the notification helper).** `RunChannel.received(count=0, *, timeout_s=10.0)` returns once `count` notifications have arrived plus any within `SETTLE_S` (0.05 s), so one too many still shows; with no count it waits `QUIET_S` (0.3 s), the check that nothing came. `received_until(payload)` returns everything up to the first `payload`. psycopg's `notifies(stop_after=)` stops after the batch that reaches the count, so the helper buffers what it read beyond. Its own tests are in `engine/tests/testing/test_run_channel.py`. `test_notify.py`'s 14 becomes `2 * len(progress.stages) + 2`. The `broken` patch (`test_rerun_end.py`, and its twin in `test_notify.py`, the same shape) now raises on every call while `run_report` is still `boom`, so the only `add_llm_calls` call left is `_fail_run`'s and its fallback is reached for certain; the tests assert the fallback's log line.
    - **R-M16-24 (docs, history).** The README's M9 section and the spec's §10.3 M9 sentence say what M9 shipped; they keep "15 s" and gain "(5 s since M16)" rather than being rewritten. The operator guide never states the discovery cadence; it gains the ceiling message in section 11.

## Review Focus

1. **An accept and a return race on the same report: the return must wait for the accept's row lock and then be refused with the accept's text, leaving no rerun and no return event; in the other order the accept must be recorded and the report stay "returned" with the one rerun.** Pinned in Task 1 (`test_a_return_that_waits_for_an_accepts_lock_is_refused`, `test_an_accept_that_waits_for_a_returns_lock_leaves_the_report_returned`).
2. **A reload of a stuck discovery page must read the discovery once, show the 10-minute message at once and not poll; a workstation clock that is off must not move the ceiling.** Pinned in Task 2 (`a read of a discovery older than 10 minutes shows it once and does not poll (a reload)`, `a discovery still running 10 minutes after it started says so and stops asking`, `a workstation clock that is off does not move the ceiling`, `keeps the discovery in the URL, so a reload reads it again`, the journey's reload step).
3. **A discovery that finishes just after the ceiling: a read past 10 minutes that says completed shows the suggestions, not the message; one that still says running stops polling, and a later reload shows how it ended.** Pinned in Task 2 (`a discovery that ends on the read past the ceiling shows its result, not the message`, `stops at the read that crosses the ceiling, and a later reload shows how it ended`).
4. **A signal (Ctrl-C or TERM) while `restore.sh` lists the schemas must leave no temporary file, stop nothing, and exit 130 or 143.** Pinned in Task 5 (`test-restore.sh`: "a signal during the schema query leaves no temporary file and stops nothing", with TERM, and the `restore()` helper's check after every other case); Ctrl-C itself in the live rehearsal (B).
5. **An API shutdown while the listener is reconnecting (or dead) must still close the progress feed and the database pool, and a cancellation of the shutdown itself must reach its caller.** Pinned in Task 5 (`test_a_cancelled_shutdown_is_not_swallowed`: the listener is slow to stop, as one waiting in its backoff sleep or a connect; `test_a_listener_that_died_is_logged_and_the_shutdown_still_runs`).

---

## File structure

| Path | Responsibility |
|---|---|
| `engine/corelata/service.py` | `review_run`: the accepted-run refusal and its docstring (Task 1). |
| `engine/tests/test_return.py`, `engine/tests/test_service.py`, `engine/tests/test_cli_ops.py`, `api/tests/test_runs.py`, `web/src/pages/review/ReviewActions.test.tsx` | CRL-21.1 tests; three existing tests stop returning an accepted run (Task 1). |
| `web/src/api/discoveries.ts`, `web/src/pages/new/Suggestions.tsx`, `web/src/pages/new/ValueStatement.tsx` | the ceiling, the 5 s cap, the server-clock age, the discovery in the URL (Task 2). |
| `web/src/test/poll.ts`, `web/src/test/render.tsx`, `web/src/test/fixtures.ts` | `discoveryRefetchInterval`, `renderRoute`, `discoveryView()` "now", `minutesAgo` (Task 2). |
| `web/src/api/discoveries.test.tsx`, `web/src/pages/new/Suggestions.test.tsx`, `web/src/pages/new/ValueStatement.test.tsx`, `web/e2e/journey.spec.ts` | Task 2's tests. |
| `engine/corelata/testing/postgres.py`, `engine/tests/testing/test_run_channel.py` (new), `engine/tests/worker/test_notify.py`, `engine/tests/worker/test_rerun_end.py`, `api/tests/test_run_listener.py` | test robustness (Task 3). |
| `web/src/test/setup.ts`, `web/src/components/Layout.test.tsx`, `web/src/pages/review/AuditTab.test.tsx`, `web/src/pages/review/ReviewPage.test.tsx`, `web/src/pages/new/NewRunPage.test.tsx`, `web/src/pages/review/frameBridge.test.ts` | web test hygiene (Task 4). |
| `deploy/restore.sh`, `deploy/tests/test-restore.sh`, `api/corelata_api/app.py`, `api/tests/test_app.py`, `api/csp_proxy.py`, `api/tests/test_csp_proxy.py` | small hardening (Task 5). |
| `engine/corelata/llm/openai_compat.py`, `engine/tests/llm/test_openai_compat.py`, `.github/dependabot.yml` | the unreachable-server message, the `@types/node` ignore (Task 6). |
| `README.md`, the spec, `docs/operator-guide.md`, `docs/m9-followups.md`, `docs/m14-followups.md`, `docs/m15-followups.md`, `docs/m16-followups.md` (new) | docs (Task 7). |

Order: Task 4 changes `setup.ts` so an unmocked request fails its test; Tasks 1 and 2 already mock everything they request (checked on the scratch copy with Task 4 applied), so the order below is safe in either direction. Tasks 3, 5 and 6 are independent of the others. Task 7 documents all six.

---

### Task 1: An accepted report cannot be returned (CRL-21.1: engine, CLI, API, web test)

**Files:**
- Modify: `engine/corelata/service.py` (`review_run`: docstring and the block after the note check)
- Test: `engine/tests/test_return.py` (module docstring, imports, append), `engine/tests/test_service.py` (`test_run_progress_carries_the_review_decision`, `test_review_run_stores_the_decision_on_the_run_row`), `engine/tests/test_cli_ops.py` (`test_review_accept_and_return`), `api/tests/test_runs.py` (`test_review_accept_and_return`), `web/src/pages/review/ReviewActions.test.tsx` (append)

**Interfaces:**
- Consumes: `tests.test_service.Svc`, `_set_state(db, run_id, state)`; `tests/test_return.py`'s `_completed`, `_review`, `_children`; `service._store_review_state(s, run_id)`; `runs.add_review_event(s, run_id, action, note, actor, child)`; the web test's `serveCompleted`-style handlers, `accepted` and `ReviewState` already in `ReviewActions.test.tsx`.
- Produces: the 409 text `run <id> was accepted; start a new run to change it` (`service.ConflictError`). No new names.

- [ ] **Step 1: Failing engine tests**

In `engine/tests/test_return.py` replace the module docstring and add the `text` import:

```python
"""A return is spent only while its rerun is live or completed (CRL-34, R-M15-1, R-M15-3); an
accepted run cannot be returned (CRL-21, R-M16-1)."""

import asyncio
import uuid

import pytest
from docx import Document
from sqlalchemy import text
```

(the `from corelata ...` and `from tests.test_service ...` imports stay as they are), and append to the end of the file:

```python


ACCEPTED = "was accepted; start a new run to change it"


async def _events(svc: Svc, run_id: uuid.UUID) -> list[tuple[str, str | None]]:
    async with svc.db.session() as s:
        return [(e.action, e.actor) for e in await runs.load_review_events(s, run_id)]


async def test_an_accepted_run_cannot_be_returned(svc):
    pid, run_id = await _completed(svc)
    assert await _review(svc, run_id, ReviewAction.ACCEPT, actor="ana") is None
    jobs = list(svc.queue.jobs)
    with pytest.raises(service.ConflictError) as refused:
        await _review(svc, run_id, ReviewAction.RETURN, note="Tighten the scope", actor="bob")
    assert str(refused.value) == f"run {run_id} {ACCEPTED}"
    assert await _children(svc, pid, run_id) == []
    assert svc.queue.jobs == jobs  # nothing queued
    assert await _events(svc, run_id) == [("accept", "ana")]  # nothing recorded
    review = (await service.run_progress(svc.db, run_id)).review
    assert review is not None and (review.decision, review.actor) == ("accepted", "ana")


async def test_a_return_needs_its_note_before_the_accept_is_considered(svc):
    _, run_id = await _completed(svc)
    await _review(svc, run_id, ReviewAction.ACCEPT)
    with pytest.raises(service.InvalidRequestError, match="needs a note"):
        await _review(svc, run_id, ReviewAction.RETURN, note="  ")


async def test_accept_after_accept_is_still_allowed_and_the_latest_decides(svc):
    _, run_id = await _completed(svc)
    await _review(svc, run_id, ReviewAction.ACCEPT, actor="ana")
    assert await _review(svc, run_id, ReviewAction.ACCEPT, actor="bob") is None
    review = (await service.run_progress(svc.db, run_id)).review
    assert review is not None and (review.decision, review.actor) == ("accepted", "bob")


@pytest.mark.parametrize("ending", ["failed", "cancelled", "gate_rejected"])
async def test_an_accept_after_a_freed_return_closes_the_run(svc, ending):
    pid, run_id = await _completed(svc)
    first = await _review(svc, run_id, ReviewAction.RETURN, note="x", actor="ana")
    await _set_state(svc.db, first, ending)
    assert await _review(svc, run_id, ReviewAction.ACCEPT, actor="bob") is None  # as in M15
    with pytest.raises(service.ConflictError, match=ACCEPTED):
        await _review(svc, run_id, ReviewAction.RETURN, note="y")
    assert await _children(svc, pid, run_id) == [str(first)]


async def test_a_live_return_still_wins_over_a_later_accept_and_refuses_by_its_own_rule(svc):
    pid, run_id = await _completed(svc)
    child = await _review(svc, run_id, ReviewAction.RETURN, note="x", actor="ana")
    assert await _review(svc, run_id, ReviewAction.ACCEPT, actor="bob") is None
    review = (await service.run_progress(svc.db, run_id)).review
    assert review is not None and review.decision == "returned"  # R-M9-1, unchanged
    with pytest.raises(service.ConflictError, match=f"already returned; its rerun is {child}"):
        await _review(svc, run_id, ReviewAction.RETURN, note="y")
    # once that rerun fails, the later accept is the decision, and it closes the run
    await _set_state(svc.db, child, "failed")
    async with svc.db.session() as s, s.begin():
        await service._store_review_state(s, run_id)  # what the worker's ending path does
    with pytest.raises(service.ConflictError, match=ACCEPTED):
        await _review(svc, run_id, ReviewAction.RETURN, note="z")
    assert await _children(svc, pid, run_id) == [str(child)]


_LOCK_WAITERS = text(
    "SELECT count(*) FROM pg_stat_activity "
    "WHERE datname = current_database() AND wait_event_type = 'Lock'"
)


async def _until_a_session_waits_for_a_lock(svc: Svc) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 10
    while True:
        async with svc.db.session() as s:
            if await s.scalar(_LOCK_WAITERS):
                return
        assert loop.time() < deadline, "no session waited for the run's row lock"
        await asyncio.sleep(0.02)


def _hold(monkeypatch, action: ReviewAction) -> tuple[asyncio.Event, asyncio.Event]:
    """Make the review recording `action` stop inside its transaction, with the run's row lock
    held, until the second event is set."""
    reached, release = asyncio.Event(), asyncio.Event()
    real = runs.add_review_event

    async def held(s, rid, recorded, *args):
        if recorded == action.value:
            reached.set()
            await release.wait()
        return await real(s, rid, recorded, *args)

    monkeypatch.setattr(runs, "add_review_event", held)
    return reached, release


async def test_a_return_that_waits_for_an_accepts_lock_is_refused(svc, monkeypatch):
    pid, run_id = await _completed(svc)
    reached, release = _hold(monkeypatch, ReviewAction.ACCEPT)
    accept = asyncio.create_task(_review(svc, run_id, ReviewAction.ACCEPT, actor="ana"))
    await reached.wait()  # the accept holds the row lock and has not committed
    returning = asyncio.create_task(_review(svc, run_id, ReviewAction.RETURN, note="x"))
    await _until_a_session_waits_for_a_lock(svc)  # the return waits for that lock
    release.set()
    assert await accept is None
    with pytest.raises(service.ConflictError, match=ACCEPTED):
        await returning  # it decided on the decision committed while it waited
    assert await _children(svc, pid, run_id) == []
    assert await _events(svc, run_id) == [("accept", "ana")]


async def test_an_accept_that_waits_for_a_returns_lock_leaves_the_report_returned(svc, monkeypatch):
    pid, run_id = await _completed(svc)
    reached, release = _hold(monkeypatch, ReviewAction.RETURN)
    returning = asyncio.create_task(_review(svc, run_id, ReviewAction.RETURN, note="x"))
    await reached.wait()
    accept = asyncio.create_task(_review(svc, run_id, ReviewAction.ACCEPT, actor="bob"))
    await _until_a_session_waits_for_a_lock(svc)
    release.set()
    child = await returning
    assert await accept is None
    assert await _children(svc, pid, run_id) == [str(child)]
    review = (await service.run_progress(svc.db, run_id)).review
    assert review is not None and review.decision == "returned"
    assert review.child_run_id == str(child)
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/test_return.py --no-cov -q`
Expected: 6 failures (`test_an_accepted_run_cannot_be_returned`, the three `test_an_accept_after_a_freed_return_closes_the_run` cases, `test_a_live_return_still_wins_...` and `test_a_return_that_waits_for_an_accepts_lock_is_refused`), each `Failed: DID NOT RAISE <class 'corelata.service.ConflictError'>`; the other new tests pass already (they pin behaviour that stays).

- [ ] **Step 3: Refuse a return on an accepted run**

In `engine/corelata/service.py`, `review_run`, replace the docstring with:

```python
    """Spec §10.1 review: `accept` records the decision; `return` records it and creates a
    linked run (`parent_run_id`) over the same sources, statement and pack snapshot, with the
    note appended to the writer guidance. Returns the new run's id for a return. A run whose
    rerun ended without a report can be returned again (R-M15-1); a run whose stored decision
    is an accept cannot be returned (R-M16-1). The rerun, the return event and the stored
    decision commit in one transaction under the run's row lock (R-M15-3): a second return, or
    a return racing an accept, waits for the lock and then sees the other's decision, and an
    interrupted return leaves nothing behind unless its commit landed. A rerun left without a
    queued job (a cancellation during `_defer_run`, after the commit) stays CREATED and spends
    the return until the orphan sweep fails it, which frees the return."""
```

and replace

```python
            if not note.strip():
                raise InvalidRequestError("a return needs a note for the writer")
            events = await runs.load_review_events(s, run_id)
```

with

```python
            if not note.strip():
                raise InvalidRequestError("a return needs a note for the writer")
            if (run.review_state or {}).get("decision") == ReviewDecision.ACCEPTED.value:
                # An accept is the reviewer's final word on the report, which may already have
                # gone out (CRL-21, R-M16-1). Read under the row lock, so an accept that commits
                # while this return waits for the lock is seen here.
                raise ConflictError(f"run {run_id} was accepted; start a new run to change it")
            events = await runs.load_review_events(s, run_id)
```

(`ReviewDecision` is already imported from `corelata.schema`.)

- [ ] **Step 4: Run the new tests**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/test_return.py --no-cov -q`
Expected: 19 passed.

- [ ] **Step 5: Existing tests that returned an accepted run**

Three tests accept a run and then return it; they now return first, then accept the completed rerun (or record the accept after the rerun failed).

In `engine/tests/test_service.py`, `test_run_progress_carries_the_review_decision`, replace everything after the line `args = (svc.db, svc.storage, svc.queue, svc.cfg, svc.prompts, run_id)` with:

```python
    child = await service.review_run(*args, ReviewAction.RETURN, note="tighten", actor="bob")
    returned = (await service.run_progress(svc.db, run_id)).review
    assert returned is not None
    assert (returned.decision, returned.actor, returned.child_run_id) == (
        "returned",
        "bob",
        str(child),
    )
    assert (await service.run_progress(svc.db, child)).review is None
    await _set_state(svc.db, child, "completed")
    child_args = (svc.db, svc.storage, svc.queue, svc.cfg, svc.prompts, child)
    await service.review_run(*child_args, ReviewAction.ACCEPT, actor="alice")
    accepted = (await service.run_progress(svc.db, child)).review
    assert accepted is not None
    assert (accepted.decision, accepted.actor, accepted.child_run_id) == ("accepted", "alice", None)
    assert accepted.at >= returned.at
```

In `test_review_run_stores_the_decision_on_the_run_row`, replace

```python
    assert await stored() is None
    await service.review_run(*args, ReviewAction.ACCEPT, actor="alice")
    accepted = await stored()
    assert accepted["decision"] == "accepted" and accepted["actor"] == "alice"
    seen = {}
```

with

```python
    assert await stored() is None
    seen = {}
```

replace

```python
    assert seen["during"] == accepted  # nothing of the return is visible before it commits
    assert await stored() == accepted  # and nothing of it stays (R-M15-3)
```

with

```python
    assert seen == {"during": None}  # nothing of the return is visible before it commits
    assert await stored() is None  # and nothing of it stays (R-M15-3)
```

and append to the end of that test (after `assert returned == service._review_state(events, reruns).model_dump(mode="json")`):

```python
    await _set_state(svc.db, child, "failed")  # the rerun failed, so an accept decides
    async with svc.db.session() as s, s.begin():
        await service._store_review_state(s, run_id)
    await service.review_run(*args, ReviewAction.ACCEPT, actor="alice")
    accepted = await stored()
    assert accepted["decision"] == "accepted" and accepted["actor"] == "alice"
```

In `engine/tests/test_cli_ops.py`, `test_review_accept_and_return`, replace everything after the `run_id = _run_id(...)` statement with:

```python
    code, _, err = _cli(capsys, "review", run_id, "--accept", *args)
    assert code == 2 and "only a completed run" in err
    assert _cli(capsys, "worker", "--burst", *args)[0] == 0
    code, _, err = _cli(capsys, "review", run_id, "--return", *args)
    assert code == 2 and "needs a note" in err
    code, out, _ = _cli(capsys, "review", run_id, "--return", "--note", "Tighten the scope.", *args)
    assert code == 0
    child = re.search(r"new run (\S+) queued", out).group(1)
    code, out, _ = _cli(capsys, "status", child, *args)
    assert code == 0 and f"parent: {run_id}" in out
    assert _cli(capsys, "worker", "--burst", *args)[0] == 0
    assert "completed" in _cli(capsys, "status", child, *args)[1]
    code, out, _ = _cli(capsys, "review", child, "--accept", "--actor", "alice", *args)
    assert code == 0 and out.strip() == f"run {child} accepted"
    # an accepted report is final (CRL-21, R-M16-1): the CLI says so as the API does
    code, out, err = _cli(capsys, "review", child, "--return", "--note", "One more pass.", *args)
    assert (code, out) == (2, "")
    assert err.strip() == f"error: run {child} was accepted; start a new run to change it"
```

In `api/tests/test_runs.py` replace the whole of `test_review_accept_and_return` with:

```python
async def test_review_accept_and_return(make_api):
    async with make_api(auth={"mode": "trusted_header"}) as api:
        headers = {"X-Remote-User": " ana "}
        api.client.headers.update(headers)
        run = await start_run(api)
        await set_run_state(api.db, run["run_id"], "completed")
        review = f"/api/runs/{run['run_id']}/review"
        empty = await api.client.post(review, json={"action": "return", "note": "  "})
        assert empty.status_code == 422 and "needs a note" in empty.json()["detail"]
        returned = await api.client.post(review, json={"action": "return", "note": "Tighten it"})
        assert returned.status_code == 200, returned.text
        child = returned.json()["child"]
        assert child["parent_run_id"] == run["run_id"] and child["state"] == "created"
        assert [j.kwargs["run_id"] for j in api.queue.jobs] == [run["run_id"], child["run_id"]]
        listed = (
            await api.client.get("/api/runs", params={"project_id": run["project_id"]})
        ).json()["runs"]
        assert {r["run_id"]: r["parent_run_id"] for r in listed} == {
            run["run_id"]: None,
            child["run_id"]: run["run_id"],
        }
        shown = (await api.client.get(f"/api/runs/{run['run_id']}")).json()["review"]
        assert shown["decision"] == "returned" and shown["child_run_id"] == child["run_id"]
        assert shown["actor"] == "ana"
        assert child["review"] is None
        again = await api.client.post(review, json={"action": "return", "note": "Once more"})
        assert again.status_code == 409 and "already returned" in again.json()["detail"]

        # the rerun's report is accepted, which is final (CRL-21, R-M16-1)
        await set_run_state(api.db, child["run_id"], "completed")
        child_review = f"/api/runs/{child['run_id']}/review"
        accept = await api.client.post(child_review, json={"action": "accept"})
        assert accept.status_code == 200 and accept.json() == {"action": "accept", "child": None}
        shown = (await api.client.get(f"/api/runs/{child['run_id']}")).json()["review"]
        assert shown["decision"] == "accepted" and shown["actor"] == "ana"
        assert shown["child_run_id"] is None
        refused = await api.client.post(child_review, json={"action": "return", "note": "Redo"})
        assert refused.status_code == 409
        assert refused.json() == {
            "detail": f"run {child['run_id']} was accepted; start a new run to change it"
        }
        assert len(api.queue.jobs) == 2  # nothing more was queued
        async with api.db.session() as s:
            events = (await s.scalars(select(ReviewEvent).order_by(ReviewEvent.at))).all()
        assert [(e.run_id, e.action, e.note, e.actor) for e in events] == [
            (uuid.UUID(run["run_id"]), "return", "Tighten it", "ana"),
            (uuid.UUID(child["run_id"]), "accept", "", "ana"),
        ]
        assert events[0].child_run_id == uuid.UUID(child["run_id"])
```

- [ ] **Step 6: The Review screen with a stale page (no web code change, R-M16-17)**

Append to `web/src/pages/review/ReviewActions.test.tsx`:

```tsx

it("a stale page whose report another reviewer accepted shows the refusal, then the decision (R-M16-1)", async () => {
  let review: ReviewState | null = null; // this page loaded before the other reviewer accepted
  server.use(
    http.get(`*/api/runs/${RUN_ID}`, () =>
      HttpResponse.json(runProgress({ state: "completed", status: "clean", iteration: 1, review })),
    ),
    http.get(`*/api/runs/${RUN_ID}/report`, () => HttpResponse.text(reportHtml)),
    http.get(`*/api/runs/${RUN_ID}/exports/report.json`, () => HttpResponse.json(reportJson)),
    http.get(`*/api/runs/${RUN_ID}/trace`, () =>
      HttpResponse.json({ detail: "x" }, { status: 500 }),
    ),
    http.get(`*/api/runs/${RUN_ID}/findings`, () => HttpResponse.json([])),
    http.post(`*/api/runs/${RUN_ID}/review`, () => {
      review = accepted;
      return HttpResponse.json(
        { detail: `run ${RUN_ID} was accepted; start a new run to change it` },
        { status: 409 },
      );
    }),
  );
  const { user } = renderApp(`/runs/${RUN_ID}/review`);
  await user.click(await screen.findByRole("button", { name: "Return with note" }));
  await user.type(screen.getByRole("textbox", { name: "Note for the writer" }), "One more pass");
  await user.click(screen.getByRole("button", { name: "Return" }));
  expect(await within(screen.getByRole("dialog")).findByRole("alert")).toHaveTextContent(
    "was accepted; start a new run to change it",
  );
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  expect(await screen.findByRole("status", { name: "Review decision" })).toHaveTextContent(
    "Accepted",
  );
  expect(screen.getByRole("button", { name: "Accept" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Return with note" })).toBeDisabled();
});
```

This test passes before and after Step 3 (the web follows the server); it pins R-M16-17.

- [ ] **Step 7: Run the touched suites**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/test_return.py tests/test_service.py tests/test_cli_ops.py --no-cov -q`
Expected: all pass.

Run: `cd api && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/test_runs.py --no-cov -q`
Expected: 13 passed.

Run: `cd web && pnpm exec vitest run src/pages/review/ReviewActions.test.tsx`
Expected: 22 passed.

Run: `make schema && git status --short schema web/src/api/schema.d.ts`
Expected: no output.

- [ ] **Step 8: Commit**

```bash
cat > <scratchpad>/m16-task1-commit.txt <<'EOF'
feat: CRL-21 an accepted report cannot be returned

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git add engine/corelata/service.py engine/tests/test_return.py engine/tests/test_service.py engine/tests/test_cli_ops.py api/tests/test_runs.py web/src/pages/review/ReviewActions.test.tsx
git commit -F <scratchpad>/m16-task1-commit.txt
```

---

### Task 2: The discovery screen stops after 10 minutes, polls at most every 5 s, and survives a reload (CRL-21.2, CRL-21.3: web)

**Files:**
- Modify: `web/src/api/discoveries.ts` (whole file), `web/src/pages/new/Suggestions.tsx` (import; one branch), `web/src/pages/new/ValueStatement.tsx` (imports; the discovery id), `web/src/test/poll.ts` (whole file), `web/src/test/render.tsx` (add `renderRoute`), `web/src/test/fixtures.ts` (`discoveryView`; add `minutesAgo`), `web/e2e/journey.spec.ts` (after the suggestions show)
- Test: `web/src/api/discoveries.test.tsx` (whole file), `web/src/pages/new/Suggestions.test.tsx` (imports; new tests), `web/src/pages/new/ValueStatement.test.tsx` (render through a router; one new test)

**Interfaces:**
- Consumes: `ApiError`, `client`, `unwrap` (`web/src/api/client.ts`); `DiscoveryView` (`web/src/api/types.ts`); `makeQueryClient`, `Providers`; `routes` is not used (`renderRoute` builds a one-route router).
- Produces: in `web/src/api/discoveries.ts`: `DISCOVERY_POLL_MAX_MS = 5000`, `DISCOVERY_CEILING_MS = 600_000`, `DISCOVERY_STALLED: string` (the R-M16-2 copy), `type DiscoveryRead = DiscoveryView & { age_ms: number }`, `discoveryAge(view: DiscoveryView, serverDate: string | null, now: number): number`, `discoveryStalled(view: DiscoveryRead | undefined): boolean`, `discoveryPollInterval(view: DiscoveryRead | undefined, error?: Error | null, polls?: number): number | false`; `useDiscovery(id)` now returns `DiscoveryRead` data. In `web/src/test/poll.ts`: `discoveryRefetchInterval(queryClient, discoveryId): unknown`. In `web/src/test/render.tsx`: `renderRoute(element: ReactNode, path: string) -> { router, user, queryClient }`. In `web/src/test/fixtures.ts`: `minutesAgo(minutes: number): string`; `discoveryView()`'s default `created_at` is the current time.

- [ ] **Step 1: Failing hook tests**

Replace `web/src/api/discoveries.test.tsx` with:

```tsx
import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { makeQueryClient, Providers } from "../Providers";
import {
  candidates,
  DISCOVERY_ID,
  discoveryView,
  minutesAgo,
  project,
  source,
} from "../test/fixtures";
import { discoveryRefetchInterval } from "../test/poll";
import { server } from "../test/server";
import { ApiError } from "./client";
import {
  DISCOVERY_CEILING_MS,
  DISCOVERY_POLL_MAX_MS,
  DISCOVERY_POLL_MS,
  discoveryAge,
  discoveryPollInterval,
  discoveryStalled,
  useDiscovery,
  useStartDiscovery,
  type DiscoveryRead,
} from "./discoveries";
import type { DiscoveryView } from "./types";

function wrapper({ children }: { children: ReactNode }) {
  return <Providers client={makeQueryClient({ retry: false })}>{children}</Providers>;
}

function read(overrides: Partial<DiscoveryView> = {}, ageMs = 0): DiscoveryRead {
  return { ...discoveryView(overrides), age_ms: ageMs };
}

function renderDiscovery() {
  const client = makeQueryClient({ retry: false });
  const hook = renderHook(() => useDiscovery(DISCOVERY_ID), {
    wrapper: ({ children }) => <Providers client={client}>{children}</Providers>,
  });
  return { client, hook };
}

it("polls a discovery until it ends, backing off 1, 2, 4 s, then every 5 s (R-M16-3)", () => {
  expect(DISCOVERY_POLL_MAX_MS).toBe(5000);
  expect(discoveryPollInterval(undefined)).toBe(DISCOVERY_POLL_MS);
  expect(discoveryPollInterval(read({ state: "running" }))).toBe(DISCOVERY_POLL_MS);
  expect(discoveryPollInterval(read({ state: "completed" }))).toBe(false);
  expect(discoveryPollInterval(read({ state: "failed" }))).toBe(false);
  expect(discoveryPollInterval(undefined, new ApiError(404, "gone"))).toBe(false);
  expect(discoveryPollInterval(undefined, new ApiError(500, "boom"))).toBe(DISCOVERY_POLL_MS);
  expect(discoveryPollInterval(undefined, new Error("network"))).toBe(DISCOVERY_POLL_MS);
  expect([1, 2, 3, 4, 5, 40].map((polls) => discoveryPollInterval(undefined, null, polls))).toEqual(
    [1000, 2000, 4000, 5000, 5000, 5000],
  );
  expect(discoveryPollInterval(read({ state: "completed" }), null, 9)).toBe(false);
});

it("stops polling once the discovery has run 10 minutes, and only while it runs (R-M16-2)", () => {
  const justUnder = read({ state: "running" }, DISCOVERY_CEILING_MS - 1);
  const atCeiling = read({ state: "running" }, DISCOVERY_CEILING_MS);
  expect(discoveryStalled(justUnder)).toBe(false);
  expect(discoveryPollInterval(justUnder, null, 9)).toBe(DISCOVERY_POLL_MAX_MS);
  expect(discoveryStalled(atCeiling)).toBe(true);
  expect(discoveryPollInterval(atCeiling, null, 9)).toBe(false);
  expect(discoveryStalled(read({ state: "created" }, DISCOVERY_CEILING_MS))).toBe(true);
  // an ended discovery is shown as it ended, however old
  expect(discoveryStalled(read({ state: "completed" }, 2 * DISCOVERY_CEILING_MS))).toBe(false);
  expect(discoveryStalled(read({ state: "failed" }, 2 * DISCOVERY_CEILING_MS))).toBe(false);
  expect(discoveryStalled(undefined)).toBe(false);
});

it("measures a discovery's age on the server's clock when the answer carries one", () => {
  const view = discoveryView({ created_at: "2026-10-18T10:00:00.500Z" });
  const now = Date.parse("2026-10-18T10:00:03Z");
  expect(discoveryAge(view, "Sun, 18 Oct 2026 10:11:00 GMT", now)).toBe(659_500);
  expect(discoveryAge(view, null, now)).toBe(2_500); // no header: the browser's clock
  expect(discoveryAge(view, "not a date", now)).toBe(2_500);
});

it("a read of a discovery older than 10 minutes shows it once and does not poll (a reload)", async () => {
  let served = 0;
  server.use(
    http.get(`*/api/discoveries/${DISCOVERY_ID}`, () => {
      served += 1;
      return HttpResponse.json(discoveryView({ state: "running", created_at: minutesAgo(11) }));
    }),
  );
  const { client, hook } = renderDiscovery();
  await waitFor(() => expect(hook.result.current.data?.state).toBe("running"));
  expect(hook.result.current.data!.age_ms).toBeGreaterThanOrEqual(DISCOVERY_CEILING_MS);
  expect(discoveryRefetchInterval(client, DISCOVERY_ID)).toBe(false);
  expect(served).toBe(1);
});

it("a workstation clock that is off does not move the ceiling: the server's Date decides", async () => {
  const created = Date.now();
  server.use(
    http.get(`*/api/discoveries/${DISCOVERY_ID}`, () =>
      HttpResponse.json(
        discoveryView({ state: "running", created_at: new Date(created).toISOString() }),
        // the server says 11 minutes have passed; this machine's clock says none
        { headers: { Date: new Date(created + 11 * 60_000).toUTCString() } },
      ),
    ),
  );
  const behind = renderDiscovery();
  await waitFor(() => expect(behind.hook.result.current.data?.state).toBe("running"));
  expect(discoveryRefetchInterval(behind.client, DISCOVERY_ID)).toBe(false);

  const ahead = minutesAgo(20); // this machine's clock runs 20 minutes ahead of the server's
  server.use(
    http.get(`*/api/discoveries/${DISCOVERY_ID}`, () =>
      HttpResponse.json(discoveryView({ state: "running", created_at: ahead }), {
        headers: { Date: new Date(Date.parse(ahead) + 30_000).toUTCString() },
      }),
    ),
  );
  const fast = renderDiscovery();
  await waitFor(() => expect(fast.hook.result.current.data?.state).toBe("running"));
  expect(discoveryRefetchInterval(fast.client, DISCOVERY_ID)).toBe(DISCOVERY_POLL_MS);
});

it("useDiscovery counts its polls for the backoff", async () => {
  let served = 0;
  server.use(
    http.get(`*/api/discoveries/${DISCOVERY_ID}`, () => {
      served += 1;
      return HttpResponse.json(discoveryView({ state: "running" }));
    }),
  );
  const { client, hook } = renderDiscovery();
  await waitFor(() => expect(hook.result.current.data?.state).toBe("running"));
  expect(discoveryRefetchInterval(client, DISCOVERY_ID)).toBe(DISCOVERY_POLL_MS); // one poll so far
  await hook.result.current.refetch();
  await waitFor(() => expect(served).toBe(2));
  expect(discoveryRefetchInterval(client, DISCOVERY_ID)).toBe(2 * DISCOVERY_POLL_MS);
});

it("starts a discovery and reads it", async () => {
  server.use(
    http.post("*/api/discoveries", async ({ request }) => {
      expect(await request.json()).toEqual({
        project_id: project.id,
        source_ids: [source.id],
        audience_hint: "ministers",
      });
      return HttpResponse.json(discoveryView(), { status: 202 });
    }),
    http.get(`*/api/discoveries/${DISCOVERY_ID}`, () =>
      HttpResponse.json(discoveryView({ state: "completed", candidates })),
    ),
  );
  const start = renderHook(() => useStartDiscovery(), { wrapper });
  start.result.current.mutate({
    project_id: project.id,
    source_ids: [source.id],
    audience_hint: "ministers",
  });
  await waitFor(() => expect(start.result.current.data?.discovery_id).toBe(DISCOVERY_ID));
  const reader = renderHook(() => useDiscovery(DISCOVERY_ID), { wrapper });
  await waitFor(() => expect(reader.result.current.data?.candidates).toEqual(candidates));
  const idle = renderHook(() => useDiscovery(null), { wrapper });
  expect(idle.result.current.fetchStatus).toBe("idle");
});
```

Replace `web/src/test/poll.ts` with:

```ts
import type { Query, QueryClient, QueryKey } from "@tanstack/react-query";
import { discoveryKeys } from "../api/discoveries";
import { runKeys } from "../api/runs";

/** What the active observer of the query `queryKey` would use as its refetch interval now. */
function refetchInterval(queryClient: QueryClient, queryKey: QueryKey): unknown {
  const query = queryClient.getQueryCache().find({ queryKey })!;
  const option = query.observers[0]!.options.refetchInterval as (q: Query) => unknown;
  return option(query);
}

/** What the run query's active observer would use as its refetch interval right now. */
export function runRefetchInterval(queryClient: QueryClient, runId: string): unknown {
  return refetchInterval(queryClient, runKeys.one(runId));
}

/** The same for a discovery's query (R-M16-2, R-M16-3). */
export function discoveryRefetchInterval(queryClient: QueryClient, discoveryId: string): unknown {
  return refetchInterval(queryClient, discoveryKeys.one(discoveryId));
}
```

In `web/src/test/fixtures.ts`, in `discoveryView`, replace `    created_at: "2026-10-13T10:03:00Z",` with:

```ts
    // just created, by the clock the page reads its age with (no `Date` header in tests): a
    // fixed past date would be past the 10-minute ceiling (R-M16-2)
    created_at: new Date().toISOString(),
```

and add after the `discoveryView` function:

```ts

/** A `created_at` that many minutes ago, by the test's clock. */
export function minutesAgo(minutes: number): string {
  return new Date(Date.now() - minutes * 60_000).toISOString();
}
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd web && pnpm exec vitest run src/api/discoveries.test.tsx`
Expected: FAIL: `expected 15000 to be 5000`, `discoveryStalled is not a function`, `discoveryAge is not a function`, and the two hook tests that read an old discovery see an interval of `1000` instead of `false` (`pnpm lint` would also reject the missing exports).

- [ ] **Step 3: The ceiling, the cap and the server-clock age**

Replace `web/src/api/discoveries.ts` with:

```ts
import { useMutation, useQuery } from "@tanstack/react-query";
import { ApiError, client, unwrap } from "./client";
import type { DiscoveryView } from "./types";

export const discoveryKeys = { one: (id: string) => ["discoveries", id] as const };
export const DISCOVERY_POLL_MS = 1000;
export const DISCOVERY_POLL_MAX_MS = 5000;
/** How long a discovery may run before the screen stops asking (CRL-21, R-M16-2). */
export const DISCOVERY_CEILING_MS = 10 * 60_000;
export const DISCOVERY_STALLED =
  "Discovery has not finished after 10 minutes. It may still be running, or its worker may have stopped. Reload this page to check again, or start a new discovery.";

/** A discovery as one read saw it, with how old it was then: the time on the server's clock
 * (the answer's `Date` header) minus its `created_at`, so neither a reload nor a workstation
 * clock that is off moves the ceiling (R-M16-15). Without the header, the browser's clock. */
export type DiscoveryRead = DiscoveryView & { age_ms: number };

export function discoveryAge(view: DiscoveryView, serverDate: string | null, now: number): number {
  const at = serverDate ? Date.parse(serverDate) : Number.NaN;
  return (Number.isNaN(at) ? now : at) - Date.parse(view.created_at);
}

function ended(view: DiscoveryView | undefined): boolean {
  return view?.state === "completed" || view?.state === "failed";
}

/** Still running 10 minutes after it was created, as of the latest read (R-M16-2). */
export function discoveryStalled(view: DiscoveryRead | undefined): boolean {
  return view !== undefined && !ended(view) && view.age_ms >= DISCOVERY_CEILING_MS;
}

/** 1 s, 2 s, 4 s, then every 5 s (R-M9-9, R-M16-3), until the discovery ends or has run for
 * 10 minutes (R-M16-2). `polls` is how many answers (or failures) the query has had so far. */
export function discoveryPollInterval(
  view: DiscoveryRead | undefined,
  error: Error | null = null,
  polls = 0,
): number | false {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false;
  if (ended(view) || discoveryStalled(view)) return false;
  return Math.min(DISCOVERY_POLL_MS * 2 ** Math.max(0, polls - 1), DISCOVERY_POLL_MAX_MS);
}

export type StartDiscovery = { project_id: string; source_ids: string[]; audience_hint: string };

export function useStartDiscovery() {
  return useMutation({
    mutationFn: (body: StartDiscovery) =>
      unwrap<DiscoveryView>(client.POST("/api/discoveries", { body })),
  });
}

/** A discovery takes a few seconds; there is no event stream for it, so poll until it ends. */
export function useDiscovery(discoveryId: string | null) {
  return useQuery({
    queryKey: discoveryKeys.one(discoveryId ?? ""),
    queryFn: async (): Promise<DiscoveryRead> => {
      let date: string | null = null;
      const view = await unwrap<DiscoveryView>(
        client
          .GET("/api/discoveries/{discovery_id}", {
            params: { path: { discovery_id: discoveryId! } },
          })
          .then((result) => {
            date = result.response.headers.get("date");
            return result;
          }),
      );
      return { ...view, age_ms: discoveryAge(view, date, Date.now()) };
    },
    enabled: discoveryId !== null,
    refetchInterval: (query) =>
      discoveryPollInterval(
        query.state.data,
        query.state.error,
        query.state.dataUpdateCount + query.state.fetchFailureCount,
      ),
  });
}
```

- [ ] **Step 4: Run the hook tests**

Run: `cd web && pnpm exec vitest run src/api/discoveries.test.tsx`
Expected: 7 passed.

- [ ] **Step 5: Failing screen tests**

In `web/src/pages/new/Suggestions.test.tsx` replace the imports with:

```tsx
import { screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { DISCOVERY_STALLED } from "../../api/discoveries";
import type { DiscoveryView } from "../../api/types";
import { candidates, DISCOVERY_ID, discoveryView, minutesAgo, source } from "../../test/fixtures";
import { discoveryRefetchInterval } from "../../test/poll";
import { renderWithClient } from "../../test/render";
import { server } from "../../test/server";
import { Suggestions } from "./Suggestions";
```

and insert after the `serveView` function:

```tsx

/** Answers each read with the next [view, seconds] pair: the view, created at `created`, with a
 * `Date` header that many seconds later (the server's clock). The last pair repeats. */
function serveSequence(created: string, answers: [DiscoveryView, number][]): () => number {
  let served = 0;
  server.use(
    http.get(`*/api/discoveries/${DISCOVERY_ID}`, () => {
      const [view, seconds] = answers[Math.min(served, answers.length - 1)]!;
      served += 1;
      const date = new Date(Date.parse(created) + seconds * 1000).toUTCString();
      return HttpResponse.json({ ...view, created_at: created }, { headers: { Date: date } });
    }),
  );
  return () => served;
}

it("a discovery still running 10 minutes after it started says so and stops asking (R-M16-2)", async () => {
  let served = 0;
  server.use(
    http.get(`*/api/discoveries/${DISCOVERY_ID}`, () => {
      served += 1;
      return HttpResponse.json(discoveryView({ state: "running", created_at: minutesAgo(11) }));
    }),
  );
  const { queryClient } = renderWithClient(
    <Suggestions discoveryId={DISCOVERY_ID} onPick={() => {}} />,
  );
  const status = await screen.findByText(DISCOVERY_STALLED);
  expect(status).toHaveAttribute("role", "status"); // a polite live region
  expect(status).toHaveTextContent(
    "Discovery has not finished after 10 minutes. It may still be running, or its worker may have stopped. Reload this page to check again, or start a new discovery.",
  );
  expect(discoveryRefetchInterval(queryClient, DISCOVERY_ID)).toBe(false);
  expect(served).toBe(1);
});

it("stops at the read that crosses the ceiling, and a later reload shows how it ended", async () => {
  const created = new Date(Date.now() - 3_600_000).toISOString(); // only the server's Date matters
  const served = serveSequence(created, [
    [discoveryView({ state: "running" }), 9 * 60 + 59], // 1 s under the ceiling
    [discoveryView({ state: "running" }), 10 * 60 + 1],
  ]);
  const first = renderWithClient(<Suggestions discoveryId={DISCOVERY_ID} onPick={() => {}} />);
  await waitFor(() => expect(served()).toBe(1));
  expect(await screen.findByText("Looking for value in the selected sources…")).toBeInTheDocument();
  await waitFor(() => expect(discoveryRefetchInterval(first.queryClient, DISCOVERY_ID)).toBe(1000));
  expect(await screen.findByText(DISCOVERY_STALLED, {}, { timeout: 5000 })).toBeInTheDocument();
  expect(discoveryRefetchInterval(first.queryClient, DISCOVERY_ID)).toBe(false);
  expect(served()).toBe(2);
  first.queryClient.clear();

  // the worker finished after the page stopped asking: a reload reads it once and shows it
  serveSequence(created, [[discoveryView({ state: "completed", candidates }), 10 * 60 + 30]]);
  renderWithClient(<Suggestions discoveryId={DISCOVERY_ID} onPick={() => {}} />);
  expect(await screen.findAllByRole("list", { name: "Suggested value statements" })).toHaveLength(
    1,
  );
});

it("a discovery that ends on the read past the ceiling shows its result, not the message", async () => {
  const created = new Date(Date.now() - 3_600_000).toISOString();
  serveSequence(created, [
    [discoveryView({ state: "running" }), 9 * 60 + 58],
    [discoveryView({ state: "completed", candidates }), 10 * 60 + 2],
  ]);
  const { queryClient } = renderWithClient(
    <Suggestions discoveryId={DISCOVERY_ID} onPick={() => {}} />,
  );
  const list = await screen.findByRole(
    "list",
    { name: "Suggested value statements" },
    { timeout: 5000 },
  );
  expect(list.children).toHaveLength(2);
  expect(screen.queryByText(DISCOVERY_STALLED)).not.toBeInTheDocument();
  expect(discoveryRefetchInterval(queryClient, DISCOVERY_ID)).toBe(false);
});

it("a failed discovery older than the ceiling shows its error", async () => {
  serveView(discoveryView({ state: "failed", error: "no queued job", created_at: minutesAgo(30) }));
  renderWithClient(<Suggestions discoveryId={DISCOVERY_ID} onPick={() => {}} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("no queued job");
  expect(screen.queryByText(DISCOVERY_STALLED)).not.toBeInTheDocument();
});
```

In `web/src/test/render.tsx` add before `/** A component outside the router, with a query client. */`:

```tsx
/** One component as the page at `path` (which sets its search parameters), with a query
 * client: for components that keep state in the URL. */
export function renderRoute(element: ReactNode, path: string) {
  const pathname = new URL(path, "http://corelata.test").pathname;
  const router = createMemoryRouter([{ path: pathname, element }], { initialEntries: [path] });
  const queryClient = makeQueryClient({ retry: false });
  const user = userEvent.setup();
  render(
    <Providers client={queryClient}>
      <RouterProvider router={router} />
    </Providers>,
  );
  return { router, user, queryClient };
}

```

In `web/src/pages/new/ValueStatement.test.tsx`: replace `import { renderWithClient } from "../../test/render";` with `import { renderRoute } from "../../test/render";`; add before `function Host(`:

```tsx
const PAGE = `/new?project=${project.id}`;

```

replace every `renderWithClient(<Host sourceIds={[source.id]} />)` with `renderRoute(<Host sourceIds={[source.id]} />, PAGE)` and `renderWithClient(<Host sourceIds={[]} />)` with `renderRoute(<Host sourceIds={[]} />, PAGE)` (four calls); and insert after the first test (the one ending `toHaveValue(candidates[1]!.text);`):

```tsx

it("keeps the discovery in the URL, so a reload reads it again (R-M16-14)", async () => {
  const other = "55555555-5555-5555-5555-555555555555";
  server.use(
    http.post("*/api/discoveries", () =>
      HttpResponse.json(discoveryView({ discovery_id: other }), { status: 202 }),
    ),
    http.get(`*/api/discoveries/${DISCOVERY_ID}`, () =>
      HttpResponse.json(discoveryView({ state: "completed", candidates })),
    ),
    http.get(`*/api/discoveries/${other}`, () =>
      HttpResponse.json(discoveryView({ discovery_id: other, state: "running" })),
    ),
  );
  // a reload of a page that had started a discovery: no click, the URL names it
  const { router, user } = renderRoute(
    <Host sourceIds={[source.id]} />,
    `${PAGE}&discovery=${DISCOVERY_ID}`,
  );
  expect(
    await screen.findByRole("list", { name: "Suggested value statements" }),
  ).toBeInTheDocument();
  // a new discovery replaces it in the URL (no new history entry) and its state shows
  await user.click(screen.getByRole("button", { name: "Suggest value" }));
  await waitFor(() =>
    expect(router.state.location.search).toBe(`?project=${project.id}&discovery=${other}`),
  );
  expect(router.state.historyAction).toBe("REPLACE");
  expect(await screen.findByRole("status", { name: "Discovery" })).toHaveTextContent(
    "Looking for value",
  );
});
```

- [ ] **Step 6: Run them to see them fail**

Run: `cd web && pnpm exec vitest run src/pages/new/Suggestions.test.tsx src/pages/new/ValueStatement.test.tsx`
Expected: the stalled-message tests fail (`Unable to find an element with the text: Discovery has not finished after 10 minutes. …`), and `keeps the discovery in the URL …` fails (`Unable to find role="list"`: today's `ValueStatement` ignores `?discovery=`).

- [ ] **Step 7: Show the message; keep the discovery in the URL**

In `web/src/pages/new/Suggestions.tsx` replace the first import line with:

```tsx
import { DISCOVERY_STALLED, discoveryStalled, useDiscovery } from "../../api/discoveries";
```

and replace

```tsx
  if (discovery.error) return <ErrorMessage error={discovery.error} />;
  if (!view || view.state === "created" || view.state === "running") {
```

with

```tsx
  if (discovery.error) return <ErrorMessage error={discovery.error} />;
  if (discoveryStalled(view)) {
    // Polling has stopped (R-M16-2); role="status" is a polite live region.
    return (
      <p role="status" aria-label="Discovery" className="muted">
        {DISCOVERY_STALLED}
      </p>
    );
  }
  if (!view || view.state === "created" || view.state === "running") {
```

In `web/src/pages/new/ValueStatement.tsx` replace the first two import lines with:

```tsx
import { useId } from "react";
import { useSearchParams } from "react-router";
import { useStartDiscovery } from "../../api/discoveries";
```

and replace

```tsx
  const start = useStartDiscovery();
  const [discoveryId, setDiscoveryId] = useState<string | null>(null);
  const id = useId();
  const canSuggest = sourceIds.length > 0 && !start.isPending;

  function suggest() {
```

with

```tsx
  const start = useStartDiscovery();
  // The discovery lives in the URL, so a reload reads it again instead of forgetting it
  // (R-M16-14); replace, so Back does not step through earlier discoveries.
  const [params, setParams] = useSearchParams();
  const discoveryId = params.get("discovery");
  const id = useId();
  const canSuggest = sourceIds.length > 0 && !start.isPending;

  function setDiscoveryId(value: string | null) {
    setParams(
      (current) => {
        const next = new URLSearchParams(current);
        if (value) next.set("discovery", value);
        else next.delete("discovery");
        return next;
      },
      { replace: true },
    );
  }

  function suggest() {
```

(`suggest()` keeps calling `setDiscoveryId(null)` and `setDiscoveryId(view.discovery_id)` as before.)

- [ ] **Step 8: The journey reloads the page**

In `web/e2e/journey.spec.ts` replace

```ts
  const suggestions = page.getByRole("list", { name: "Suggested value statements" });
  await expect(suggestions).toBeVisible();
```

with

```ts
  const suggestions = page.getByRole("list", { name: "Suggested value statements" });
  await expect(suggestions).toBeVisible();
  // the discovery is in the URL: a reload reads it again (R-M16-14)
  await expect(page).toHaveURL(/[?&]discovery=[0-9a-f-]+/);
  await page.reload();
  await expect(suggestions).toBeVisible();
```

- [ ] **Step 9: Run the web checks**

Run: `cd web && pnpm exec vitest run src/api/discoveries.test.tsx src/pages/new`
Expected: all pass (Suggestions 9, ValueStatement 4, discoveries 7, and the other `pages/new` files unchanged).

Run: `cd web && pnpm lint && pnpm build`
Expected: clean.

- [ ] **Step 10: Commit**

```bash
cat > <scratchpad>/m16-task2-commit.txt <<'EOF'
feat: CRL-21 discovery stops after 10 minutes, polls every 5 s at most, survives a reload

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git add web/src/api/discoveries.ts web/src/api/discoveries.test.tsx web/src/pages/new/Suggestions.tsx web/src/pages/new/Suggestions.test.tsx web/src/pages/new/ValueStatement.tsx web/src/pages/new/ValueStatement.test.tsx web/src/test/poll.ts web/src/test/render.tsx web/src/test/fixtures.ts web/e2e/journey.spec.ts
git commit -F <scratchpad>/m16-task2-commit.txt
```

---

### Task 3: Notification and listener tests wait for what they expect (CRL-37: engine and API tests)

**Files:**
- Modify: `engine/corelata/testing/postgres.py` (`RunChannel`; `import asyncio`)
- Create: `engine/tests/testing/test_run_channel.py`
- Test: `engine/tests/worker/test_notify.py`, `engine/tests/worker/test_rerun_end.py`, `api/tests/test_run_listener.py`

**Interfaces:**
- Consumes: the `run_channel` and `pg_url` fixtures (`corelata/testing/pytest_db.py`); `runs.RUN_CHANNEL`; `to_libpq_url`.
- Produces: `RunChannel.received(count: int = 0, *, timeout_s: float = 10.0) -> list[str]`, `RunChannel.received_until(payload: str, *, timeout_s: float = 10.0) -> list[str]`, `RunChannel.QUIET_S = 0.3`, `RunChannel.SETTLE_S = 0.05`. `received(wait_s)` (a float) is gone; every caller is updated here. `Delays(stop_after: int | None = None)` in `api/tests/test_run_listener.py`.

- [ ] **Step 1: Failing helper tests**

Create `engine/tests/testing/test_run_channel.py`:

```python
"""The test helper that listens on the run channel waits for what a test expects, not a fixed
time (CRL-37)."""

import asyncio

import psycopg
from psycopg import sql

from corelata.store.db import to_libpq_url
from corelata.store.runs import RUN_CHANNEL
from corelata.testing.postgres import RunChannel


async def _notify(pg_url: str, *payloads: str, delay_s: float = 0.0) -> None:
    await asyncio.sleep(delay_s)
    async with await psycopg.AsyncConnection.connect(to_libpq_url(pg_url), autocommit=True) as c:
        for payload in payloads:
            await c.execute(
                sql.SQL("SELECT pg_notify({}, {})").format(
                    sql.Literal(RUN_CHANNEL), sql.Literal(payload)
                )
            )


async def test_it_returns_as_soon_as_the_expected_notifications_arrive(pg_url, run_channel):
    loop = asyncio.get_running_loop()
    late = asyncio.create_task(_notify(pg_url, "a", "b", delay_s=0.5))  # later than QUIET_S
    started = loop.time()
    assert await run_channel.received(2) == ["a", "b"]
    assert loop.time() - started < 0.5 + RunChannel.QUIET_S  # no fixed wait after them
    await late


async def test_one_too_many_and_one_missing_both_show(pg_url, run_channel):
    await _notify(pg_url, "a", "b")
    assert await run_channel.received(1) == ["a", "b"]  # the extra one is not hidden
    assert await run_channel.received(1, timeout_s=0.2) == []  # a missing one: what came
    assert await run_channel.received() == []


async def test_received_until_stops_at_the_payload_or_the_timeout(pg_url, run_channel):
    await _notify(pg_url, "a", "b", "c")
    assert await run_channel.received_until("b") == ["a", "b"]
    assert await run_channel.received_until("z", timeout_s=0.2) == ["c"]
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/testing/test_run_channel.py --no-cov -q`
Expected: 3 failed: `AttributeError: type object 'RunChannel' has no attribute 'QUIET_S'` (after a 2 s wait: today `2` is read as `wait_s`), `TypeError: RunChannel.received() got an unexpected keyword argument 'timeout_s'`, `AttributeError: 'RunChannel' object has no attribute 'received_until'`.

- [ ] **Step 3: The helper**

In `engine/corelata/testing/postgres.py` add `import asyncio` above `import contextlib`, and replace the `RunChannel` class with:

```python
class RunChannel:
    """A LISTEN connection on the run channel (CRL-22): what the worker and the service
    announced, in commit order. `open_run_channel` makes one. Each call waits for what the test
    expects rather than a fixed time (CRL-37)."""

    QUIET_S = 0.3  # how long "nothing was announced" waits for a late notification
    SETTLE_S = 0.05  # how long, after the expected ones, it waits for one too many

    def __init__(self, conn: psycopg.AsyncConnection) -> None:
        self._conn = conn
        self._pending: list[str] = []  # read from the connection, not yet returned

    async def _read(self, timeout_s: float, stop_after: int | None = None) -> None:
        # psycopg stops after the batch that reaches `stop_after`, so this may read more
        async for n in self._conn.notifies(timeout=timeout_s, stop_after=stop_after):
            self._pending.append(n.payload)

    async def received(self, count: int = 0, *, timeout_s: float = 10.0) -> list[str]:
        """The run ids notified since the last call. With `count`, it returns as soon as that
        many have arrived (waiting at most `timeout_s`, then returning what came, so the test's
        assertion shows what is missing) plus any that follow within SETTLE_S, so one too many
        still shows. With no count, nothing is expected: it waits QUIET_S for a late one."""
        if count > len(self._pending):
            await self._read(timeout_s, count - len(self._pending))
        await self._read(self.SETTLE_S if count else self.QUIET_S)
        got, self._pending = self._pending, []
        return got

    async def received_until(self, payload: str, *, timeout_s: float = 10.0) -> list[str]:
        """The run ids notified since the last call, up to and including the first `payload`
        (or all that came within `timeout_s`, without it); later ones wait for the next call."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s
        while payload not in self._pending and (left := deadline - loop.time()) > 0:
            seen = len(self._pending)
            await self._read(left, 1)
            if len(self._pending) == seen:
                break  # timed out
        cut = self._pending.index(payload) + 1 if payload in self._pending else None
        got = self._pending[:cut]
        self._pending = self._pending[len(got) :]
        return got
```

- [ ] **Step 4: The callers**

In `engine/tests/worker/test_notify.py`:

- In `test_a_notification_is_delivered_when_its_transaction_commits` replace the two lines `assert await run_channel.received(0.1) == []  # nothing before the commit` and `assert await run_channel.received() == [str(run_id)]  # once per transaction` with `assert await run_channel.received() == []  # nothing before the commit` (same indentation as before) and `assert await run_channel.received(1) == [str(run_id)]  # once per transaction`.
- Replace the body of `test_a_failed_notification_never_fails_a_run` after `run_id = await submit(services)` with:

```python
    await drain(services)
    progress = await service.run_progress(services.db, run_id)
    assert progress.state is RunState.COMPLETED
    # every one is logged: the claim, two per stage (its state, its record), the outcome, as
    # test_a_run_announces_every_change_it_commits counts them
    sent = 2 * len(progress.stages) + 2
    assert caplog.text.count("progress notification not sent") == sent
```

- In `test_a_run_announces_every_change_it_commits` and `test_a_failed_run_announces_its_failure` replace `assert await run_channel.received() == [str(run_id)] * len(announced)` with `assert await run_channel.received(len(announced)) == [str(run_id)] * len(announced)`.
- In `test_the_sweep_announces_each_run_it_fails` replace `assert sorted(await run_channel.received()) == sorted(str(i) for i in ids)` with `assert sorted(await run_channel.received(len(ids))) == sorted(str(i) for i in ids)`.
- `test_an_internal_error_announces_the_failure_on_both_paths` gains the `caplog` fixture (`services, monkeypatch, announced, caplog`), and its second half, from `announced.clear()` on, becomes:

```python
    announced.clear()

    async def broken(*args, **kwargs):  # _fail_run cannot write the leftover calls
        raise RuntimeError("write failed")

    # run_report is still `boom`, so nothing but _fail_run writes calls: its fallback ends the run
    monkeypatch.setattr(runs, "add_llm_calls", broken)
    other = await submit(services, project="q")
    await drain(services)
    assert (await service.run_progress(services.db, other)).state is RunState.FAILED
    assert announced == ["ingesting", "failed"]
    assert f"run {other}: leftover calls not saved" in caplog.text
```

In `engine/tests/worker/test_rerun_end.py`:

- In `test_a_rerun_that_fails_frees_its_parent_and_announces_it` replace the comment of `await run_channel.received()  # what the return itself announced` with `# forget what the run and the return announced`, and replace the last line `assert str(parent) in await run_channel.received()  # the Review page's run is announced` with:

```python
    # the Review page's run is announced, after the rerun's own changes
    announced = await run_channel.received_until(str(parent))
    assert announced[-1] == str(parent) and set(announced[:-1]) == {str(child)}
```

- `test_an_internal_error_on_either_failure_path_frees_the_parent` gains `caplog` (signature `async def test_an_internal_error_on_either_failure_path_frees_the_parent(\n    services, monkeypatch, caplog\n):`), and everything from `other, _ = await _returned_in(services, "q")` to the end becomes:

```python
    other, rerun = await _returned_in(services, "q")

    async def broken(*args, **kwargs):  # _fail_run cannot write the leftover calls
        raise RuntimeError("write failed")

    # run_report is still `boom`, so nothing but _fail_run writes calls: its fallback ends the run
    monkeypatch.setattr(runs, "add_llm_calls", broken)
    await drain(services)
    assert f"run {rerun}: leftover calls not saved" in caplog.text
    assert (await _review(services, other)).child_state is RunState.FAILED
```

- In `test_a_rerun_the_sweep_fails_frees_the_parent` replace `assert sorted(await run_channel.received()) == sorted([str(child), str(parent)])` with `assert sorted(await run_channel.received(2)) == sorted([str(child), str(parent)])` (its earlier bare `await run_channel.received()` stays: it forgets what came before).
- In `test_a_run_without_a_parent_announces_only_itself` replace `assert set(await run_channel.received()) == {str(run_id)}` with:

```python
    sent = 2 * len((await service.run_progress(services.db, run_id)).stages) + 2
    assert await run_channel.received(sent) == [str(run_id)] * sent
```

In `api/tests/test_run_listener.py` replace the `Delays` class with:

```python
class Delays:
    """A sleep that records what the listener waits and returns at once; after `stop_after`
    waits it parks until the listener is cancelled, so a listener that keeps failing does not
    spin (and log) for the rest of the test."""

    def __init__(self, stop_after: int | None = None) -> None:
        self.waited: list[float] = []
        self._stop_after = stop_after

    async def __call__(self, seconds: float) -> None:
        self.waited.append(seconds)
        if self._stop_after is not None and len(self.waited) >= self._stop_after:
            await asyncio.Event().wait()  # the test has what it asserts on
        await asyncio.sleep(0)
```

and:

- in `test_a_lost_connection_is_reported_and_reopened`: `delays = Delays(stop_after=2)  # a second loss would park the listener, not spin it`;
- in `test_an_unreachable_database_is_retried_with_backoff`: `delays = Delays(stop_after=8)`, and replace

```python
        await until(lambda: len(delays.waited) >= 8)
    assert delays.waited[:8] == [1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0, 30.0]
```

with

```python
        await until(lambda: len(delays.waited) == 8)
    assert delays.waited == [1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0, 30.0]
    assert len(attempts) == 8  # it stopped after the asserted calls
    assert caplog.text.count("progress listener lost the database") == 8
```

- in `test_a_notification_stream_that_ends_is_a_lost_connection`: `delays = Delays(stop_after=2)`, `await until(lambda: len(delays.waited) == 2)` and `assert delays.waited == [1.0, 1.0]  # each connect succeeded, so no backoff builds up`.

- [ ] **Step 5: Run the tests**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/testing/test_run_channel.py tests/worker/test_notify.py tests/worker/test_rerun_end.py --no-cov -q`
Expected: 26 passed (no test above 1.5 s in `--durations=3`).

Run: `cd api && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/test_run_listener.py --no-cov -q`
Expected: 5 passed.

Run: `cd engine && uv run ruff check . && uv run ruff format --check .` and the same in `api/`.
Expected: clean.

- [ ] **Step 6: Commit**

```bash
cat > <scratchpad>/m16-task3-commit.txt <<'EOF'
test: CRL-37 notification and listener tests wait for what they expect

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git add engine/corelata/testing/postgres.py engine/tests/testing/test_run_channel.py engine/tests/worker/test_notify.py engine/tests/worker/test_rerun_end.py api/tests/test_run_listener.py
git commit -F <scratchpad>/m16-task3-commit.txt
```

---

### Task 4: The web suite fails on an unmocked request, and mocks the ones it made (CRL-37: web tests)

**Files:**
- Modify: `web/src/test/setup.ts` (the msw lifecycle)
- Test: `web/src/components/Layout.test.tsx`, `web/src/pages/review/AuditTab.test.tsx` (two tests), `web/src/pages/review/ReviewPage.test.tsx` (one test), `web/src/pages/new/NewRunPage.test.tsx` (one test), `web/src/pages/review/frameBridge.test.ts` (imports; one test)

**Interfaces:**
- Consumes: `server` (`web/src/test/server.ts`); fixtures `resolvedPack`, `claimProvenance`, `reportJson`, `runProgress`.
- Produces: nothing new; a test that makes an unmocked request now fails with `unhandled request(s) in this test: GET /api/...; mock them with server.use`.

- [ ] **Step 1: Make an unhandled request fail its test**

In `web/src/test/setup.ts` replace

```ts
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  cleanup();
  server.resetHandlers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
afterAll(() => server.close());
```

with

```ts
// msw's "error" strategy only prints the request and fails that fetch; the component under test
// shows a network error and the test still passes. Record every unhandled request and fail the
// test it happened in (or, after the file's last test, the file) instead (CRL-37).
const unhandled: string[] = [];

function failOnUnhandled(when: string) {
  const seen = unhandled.splice(0);
  if (seen.length > 0) {
    throw new Error(`unhandled request(s) ${when}: ${seen.join(", ")}; mock them with server.use`);
  }
}

beforeAll(() =>
  server.listen({
    onUnhandledRequest: (request, print) => {
      unhandled.push(`${request.method} ${new URL(request.url).pathname}`);
      print.error();
    },
  }),
);
afterEach(() => {
  cleanup();
  server.resetHandlers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  failOnUnhandled("in this test");
});
afterAll(() => {
  server.close();
  failOnUnhandled("after the last test of this file");
});
```

- [ ] **Step 2: Run the four files to see them fail**

Run: `cd web && pnpm exec vitest run src/components/Layout.test.tsx src/pages/review/AuditTab.test.tsx src/pages/review/ReviewPage.test.tsx src/pages/new/NewRunPage.test.tsx`
Expected: up to seven failures, each `Error: unhandled request(s) in this test: …`: `GET /api/projects` (three Layout tests), `GET /api/packs/icd203-base/resolved` ("shows a findings error", "says so when no findings were recorded"), `GET /api/runs/33333333-3333-3333-3333-333333333333/claims/c1` ("selects a claim from the report, …"), `GET /api/runs/33333333-3333-3333-3333-333333333333` ("starts a run with the chosen sources, …"). Which of them fire before the test ends depends on the machine's speed (the scratch run failed six; main's CI printed all seven); all seven are mocked below.

- [ ] **Step 3: Mock the requests**

`web/src/components/Layout.test.tsx`: insert after `import { server } from "../test/server";`:

```tsx

// "/new" is the new-run screen, which lists the projects
beforeEach(() => server.use(http.get("*/api/projects", () => HttpResponse.json([]))));
```

`web/src/pages/review/AuditTab.test.tsx`: in "shows a findings error" and in "says so when no findings were recorded", add as the last handler of the `server.use(...)` call:

```tsx
    http.get("*/api/packs/icd203-base/resolved", () => HttpResponse.json(resolvedPack)),
```

`web/src/pages/review/ReviewPage.test.tsx`: in "selects a claim from the report, opens provenance, and pluralises open findings", add after `...tabHandlers,`:

```tsx
    // selecting c1 opens the Provenance tab, which reads it
    http.get(`*/api/runs/${RUN_ID}/claims/c1`, () =>
      HttpResponse.json({ ...claimProvenance, claim: reportJson.claims[0]! }),
    ),
```

`web/src/pages/new/NewRunPage.test.tsx`: in "starts a run with the chosen sources, statement, profile and iterations, then opens its progress", add after the `http.post("*/api/runs", …)` handler:

```tsx
    // the progress screen it opens reads the run
    http.get(`*/api/runs/${runProgress().run_id}`, () => HttpResponse.json(runProgress())),
```

- [ ] **Step 4: `frameBridge.test.ts` reads `report.css` from its own location**

Replace `import { resolve } from "node:path";` with:

```ts
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
```

and in "hashes the engine's report stylesheet, the text of the report's one style element" replace

```ts
  const css = readFileSync(resolve("../engine/corelata/render/templates/report.css")); // from web/
```

with

```ts
  // From this file, as vite.config.ts does, not from the directory the tests run in. Not
  // `new URL(path, import.meta.url)`: Vite rewrites that pattern into an asset URL.
  const here = dirname(fileURLToPath(import.meta.url));
  const css = readFileSync(
    resolve(here, "../../../../engine/corelata/render/templates/report.css"),
  );
```

(`new URL("../../../../engine/…", import.meta.url)` was tried on the scratch copy and failed with `TypeError: The URL must be of scheme file`.)

- [ ] **Step 5: Run the web suite**

Run: `cd web/src && ../node_modules/.bin/vitest run pages/review/frameBridge.test.ts --root ..`
Expected: 10 passed (from `web/src`; before Step 4 the stylesheet test failed there with `ENOENT`).

Run: `cd web && pnpm test 2>&1 | tee <scratchpad>/m16-vitest.txt | tail -5; grep -c "intercepted a request" <scratchpad>/m16-vitest.txt`
Expected: every test passes, coverage at or above 95% on all four measures, and the count is `0`.

Run: `cd web && pnpm lint`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
cat > <scratchpad>/m16-task4-commit.txt <<'EOF'
test: CRL-37 an unmocked request fails its web test; mock the seven CI printed

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git add web/src/test/setup.ts web/src/components/Layout.test.tsx web/src/pages/review/AuditTab.test.tsx web/src/pages/review/ReviewPage.test.tsx web/src/pages/new/NewRunPage.test.tsx web/src/pages/review/frameBridge.test.ts
git commit -F <scratchpad>/m16-task4-commit.txt
```

---

### Task 5: `restore.sh` cleans up on every exit; the API's shutdown and the dev proxy's errors (CRL-37: deploy and API)

**Files:**
- Modify: `deploy/restore.sh` (from the comment before `psql_err=$(mktemp)` to `stopped=true`), `api/corelata_api/app.py` (imports, `log`, `stop_listener`, the lifespan's `finally`), `api/csp_proxy.py` (`client.send`)
- Test: `deploy/tests/test-restore.sh` (stub, `restore()`, a new case), `api/tests/test_app.py` (imports; two tests and a fixture), `api/tests/test_csp_proxy.py` (two tests)

**Interfaces:**
- Consumes: the stub `docker` in `test-restore.sh` (`DOCKER_LOG`, `STUB_SCHEMA_*`); `write_config` (`api/tests/conftest.py`); `RunListener.run`, `ProgressFeed.close`, `Database.dispose` as imported in `corelata_api.app`.
- Produces: `deploy/restore.sh`'s `on_exit` (replaces `restart`); the stub's `STUB_SCHEMA_SIGNAL`; `corelata_api.app.stop_listener(listener: asyncio.Task[None]) -> None`; `corelata_api.app.log` (`corelata.api`); the proxy's 502 text `bad gateway: <upstream> did not answer (<ExceptionType>)`.

- [ ] **Step 1: Failing restore test**

In `deploy/tests/test-restore.sh`:

- In the stub, add as the first line of the `*"pg_namespace"*)` branch:

```bash
    # the restore runs in a process group of its own (set -m below): signal all of it
    [ -z "${STUB_SCHEMA_SIGNAL:-}" ] || kill -"$STUB_SCHEMA_SIGNAL" 0
```

- Replace `mkdir -p "$work/bin" "$work/src"` with `mkdir -p "$work/bin" "$work/src" "$work/tmp"`.
- Replace the `restore()` function with:

```bash
restore() {  # runs restore.sh with --yes; output in $work/out, docker calls in $work/log
  : >"$work/log"
  local rc=0
  TMPDIR="$work/tmp" DOCKER_LOG="$work/log" "$deploy/restore.sh" --yes "$@" >"$work/out" 2>&1 || rc=$?
  # whatever the outcome, restore.sh leaves no temporary file behind
  [ -z "$(ls -A "$work/tmp")" ] || fail "a temporary file was left behind: $(ls -A "$work/tmp")"
  return "$rc"
}
```

- Insert after the line `echo "ok - a warning on stderr is not read as a schema name"`:

```bash

# A signal while the schema query runs. TERM, not INT: a shell started in the background (a
# CI wrapper, a process substitution) inherits SIGINT ignored, and an ignored-on-entry signal
# can be neither trapped nor delivered; restore.sh traps both the same way. The live rehearsal
# presses Ctrl-C.
: >"$work/log"
set -m # job control: the background restore gets a process group of its own for the stub to signal
STUB_SCHEMA_SIGNAL=TERM TMPDIR="$work/tmp" DOCKER_LOG="$work/log" \
  "$deploy/restore.sh" --yes "$work/db.dump" "$work/files.tar.gz" >"$work/out" 2>&1 &
rc=0
wait $! || rc=$?
set +m
[ "$rc" = 143 ] || fail "TERM: expected exit 143, got $rc: $(cat "$work/out")"
[ -z "$(ls -A "$work/tmp")" ] || fail "TERM: psql's message file was left behind: $(ls -A "$work/tmp")"
! grep -q "stop" "$work/log" || fail "TERM: services were stopped"
echo "ok - a signal during the schema query leaves no temporary file and stops nothing"
```

- [ ] **Step 2: Run it to see it fail**

Change only the `mktemp` line of `deploy/restore.sh` first (Step 3's template), so the test can see the file: `psql_err=$(mktemp "${TMPDIR:-/tmp}/corelata-restore.XXXXXX")`.
Run: `deploy/tests/test-restore.sh`
Expected: `FAIL: TERM: psql's message file was left behind: corelata-restore.XXXXXX` (random suffix): today's EXIT trap is installed only after the schema query.

- [ ] **Step 3: One exit handler from the first temporary file on**

In `deploy/restore.sh` replace everything from the comment line `# restore.sh empties and refills \`public\` only.` through `stopped=true` (the end of today's `trap restart EXIT` block) with:

```bash
# Every exit from here on runs on_exit: an error, a refusal, Ctrl-C or a TERM (the INT and
# TERM traps exit, which runs the EXIT trap). It removes psql's message file and, once api and
# worker were stopped, brings Corelata back up after a failure.
psql_err=""
stopped=false
on_exit() {
  local rc=$?
  [ -z "$psql_err" ] || rm -f "$psql_err"
  if $stopped && [ $rc -ne 0 ]; then
    docker compose up -d >/dev/null 2>&1 || echo "error: Corelata could not be restarted; run docker compose up -d" >&2
  fi
}
trap on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# restore.sh empties and refills `public` only. Anything else in the database (an extension's
# schema, a reporting schema someone added) would be left out of step with the restored data,
# so it is refused here, before anything is stopped. psql's stderr goes to a file of its own, so
# a warning from docker compose can never be read as a schema name, and a failure shows why.
psql_err=$(mktemp "${TMPDIR:-/tmp}/corelata-restore.XXXXXX")
if ! foreign=$(docker compose exec -T postgres psql -X -q -t -A -U corelata -d corelata -c \
  "SELECT nspname FROM pg_namespace WHERE nspname NOT IN ('public', 'pg_catalog', 'information_schema') AND left(nspname, 3) <> 'pg_' ORDER BY 1" 2>"$psql_err" | tr '\n' ' ' | sed 's/ *$//'); then
  echo "error: could not list the database's schemas; is the database up (docker compose ps)?" >&2
  if [ -s "$psql_err" ]; then
    echo "psql said:" >&2
    sed 's/^/  /' "$psql_err" >&2
  fi
  exit 1
fi
rm -f "$psql_err"
psql_err=""
[ -z "$foreign" ] || die "the database holds schemas restore.sh does not manage: $foreign; move or drop them, then run the restore again"

if ! $yes; then
  [ -t 0 ] || die "this needs a terminal to confirm; add --yes to restore without asking"
  read -r -p "This replaces all Corelata data with the backup. Type 'restore' to go on: " answer
  [ "$answer" = restore ] || die "nothing was restored"
fi

# 2. From here on, on_exit brings Corelata back up if anything fails.
stopped=true
```

(The rest of the script, from `docker compose stop api worker` on, is unchanged.)

- [ ] **Step 4: Run the restore tests on both shells and shellcheck**

Run: `deploy/tests/test-restore.sh`
Expected: 17 `ok -` lines, then `restore.sh: all tests passed` (also when run as `grep -c "^ok -" <(deploy/tests/test-restore.sh)`, where SIGINT is ignored).

Run: `docker run --rm -v "$PWD/deploy:/d" ubuntu:24.04 /d/tests/test-restore.sh | tail -1`
Expected: `restore.sh: all tests passed` (bash 5.2, GNU coreutils, as on CI).

Run: `make deploy-check`
Expected: shellcheck clean, `test-install.sh`, `test-restore.sh` and `check_compose.py` pass.

- [ ] **Step 5: Failing lifespan and proxy tests**

In `api/tests/test_app.py` add `import asyncio` above `import logging`, add `from corelata_api import app as app_module` above `from corelata_api.app import create_app`, and append:

```python


@pytest.fixture
def shutdown(monkeypatch) -> list[str]:
    """What the lifespan closed at shutdown, in order: the progress feed and the database."""
    closed: list[str] = []
    real_close, real_dispose = app_module.ProgressFeed.close, app_module.Database.dispose

    async def close(self):
        closed.append("feed")
        await real_close(self)

    async def dispose(self):
        closed.append("db")
        await real_dispose(self)

    monkeypatch.setattr(app_module.ProgressFeed, "close", close)
    monkeypatch.setattr(app_module.Database, "dispose", dispose)
    return closed


async def test_a_listener_that_died_is_logged_and_the_shutdown_still_runs(
    write_config, monkeypatch, shutdown, caplog
):
    async def died(self):
        raise RuntimeError("listener bug")

    monkeypatch.setattr(app_module.RunListener, "run", died)
    path = write_config()
    cfg, _ = load_config(path)
    app = create_app(cfg, path)
    with caplog.at_level(logging.ERROR, logger="corelata.api"):
        async with app.router.lifespan_context(app):
            await asyncio.sleep(0)  # the listener task runs and dies
    assert shutdown == ["feed", "db"]
    [record] = [r for r in caplog.records if "progress listener had stopped" in r.getMessage()]
    assert record.exc_info is not None and "listener bug" in str(record.exc_info[1])


async def test_a_cancelled_shutdown_is_not_swallowed(write_config, monkeypatch, shutdown):
    stopping, release = asyncio.Event(), asyncio.Event()
    listeners: list[asyncio.Task] = []

    async def slow_to_stop(self):  # a listener that takes a while to end once cancelled
        listeners.append(asyncio.current_task())
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            stopping.set()
            await release.wait()
            raise

    monkeypatch.setattr(app_module.RunListener, "run", slow_to_stop)
    path = write_config()
    cfg, _ = load_config(path)
    app = create_app(cfg, path)

    async def lifespan() -> None:
        async with app.router.lifespan_context(app):
            await asyncio.sleep(0)

    task = asyncio.create_task(lifespan())
    await stopping.wait()  # the shutdown is waiting for the listener to end
    task.cancel()  # and the shutdown itself is cancelled (a second Ctrl-C, a server timeout)
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled()  # the cancellation reached the lifespan's caller
    assert shutdown == ["feed", "db"]  # and the rest of the shutdown ran first
    release.set()
    await asyncio.gather(*listeners, return_exceptions=True)
```

Append to `api/tests/test_csp_proxy.py`:

```python


async def test_an_unreachable_upstream_is_a_502_with_a_short_text():
    def refused(request):
        raise httpx.ConnectError("connection refused", request=request)

    proxy = create_proxy("http://app.test", transport=httpx.MockTransport(refused))
    transport = httpx.ASGITransport(app=proxy)
    async with httpx.AsyncClient(transport=transport, base_url="http://proxy.test") as client:
        response = await client.get("/api/health")
    assert response.status_code == 502
    assert response.text == "bad gateway: http://app.test did not answer (ConnectError)"
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    assert response.headers.get_list("content-security-policy") == [SAMPLE_POLICY]


class _TwoChunks(httpx.AsyncByteStream):
    """An upstream body in two chunks; the second is sent only after the proxy has passed the
    first to its client, so a proxy that buffered the body would wait here forever."""

    def __init__(self, forwarded: asyncio.Event) -> None:
        self._forwarded = forwarded

    async def __aiter__(self):
        yield b"first "
        await asyncio.wait_for(self._forwarded.wait(), timeout=5)
        yield b"second"


async def test_a_streamed_body_is_forwarded_chunk_by_chunk():
    forwarded = asyncio.Event()

    async def handler(request):
        return httpx.Response(
            200, headers={"content-type": "text/plain"}, stream=_TwoChunks(forwarded)
        )

    proxy = create_proxy("http://app.test", transport=httpx.MockTransport(handler))
    inbox: asyncio.Queue = asyncio.Queue()
    inbox.put_nowait({"type": "http.request", "body": b"", "more_body": False})
    bodies: list[tuple[bytes, bool]] = []

    async def send(message):
        if message["type"] == "http.response.body":
            bodies.append((message["body"], message["more_body"]))
            if message["body"] == b"first ":
                forwarded.set()  # the client has the first chunk: the upstream may go on

    scope = {
        "type": "http",
        "method": "GET",
        "raw_path": b"/api/runs/x/events",
        "query_string": b"",
        "headers": [],
    }
    await proxy(scope, inbox.get, send)
    assert bodies == [(b"first ", True), (b"second", True), (b"", False)]
```

- [ ] **Step 6: Run them to see them fail**

Run: `cd api && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/test_app.py tests/test_csp_proxy.py --no-cov -q`
Expected: three failures: `test_a_listener_that_died_...` (`RuntimeError: listener bug` escapes the lifespan, so `feed.close()` never runs), `test_a_cancelled_shutdown_is_not_swallowed` (`Failed: DID NOT RAISE CancelledError`), `test_an_unreachable_upstream_is_a_502_...` (`httpx.ConnectError` propagates). `test_a_streamed_body_is_forwarded_chunk_by_chunk` passes (the proxy streams today; with its `aiter_raw()` loop replaced by one `await response.aread()` it fails with `TimeoutError`, checked on the scratch copy).

- [ ] **Step 7: The lifespan and the proxy**

In `api/corelata_api/app.py` add `import logging` below `import contextlib`; add above `QueueOpener = ...`:

```python
log = logging.getLogger("corelata.api")

```

add above `health = APIRouter(prefix="/api", tags=["system"])`:

```python
async def stop_listener(listener: asyncio.Task[None]) -> None:
    """Cancel the LISTEN task and wait for it to end (CRL-37). Its own cancellation is the
    expected end; a cancellation of the task stopping it (the lifespan, cancelled while it
    waits) is not ours to swallow and propagates. A listener that had died of an error is
    logged, so the rest of the shutdown still runs."""
    listener.cancel()
    try:
        await listener
    except asyncio.CancelledError:
        current = asyncio.current_task()
        if current is not None and current.cancelling():
            raise
    except Exception:
        log.exception("progress listener had stopped with an error")


```

and replace the lifespan's

```python
        finally:
            listener.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await listener
            await feed.close()
            await db.dispose()
```

with

```python
        finally:
            try:
                await stop_listener(listener)
            finally:
                await feed.close()
                await db.dispose()
```

In `api/csp_proxy.py` replace

```python
        response = await client.send(request, stream=True)
        try:
```

with

```python
        try:
            response = await client.send(request, stream=True)
        except httpx.HTTPError as e:
            # the dev stack behind it is down or restarting: a gateway error, not a crash (CRL-37)
            text = f"bad gateway: {upstream} did not answer ({type(e).__name__})".encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 502,
                    "headers": [
                        (b"content-type", b"text/plain; charset=utf-8"),
                        (b"content-length", str(len(text)).encode()),
                        (b"content-security-policy", policy.encode("ascii")),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": text})
            return
        try:
```

- [ ] **Step 8: Run the API tests**

Run: `cd api && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/test_app.py tests/test_csp_proxy.py --no-cov -q`
Expected: 54 passed.

Run: `cd api && uv run ruff check . && uv run ruff format --check .`
Expected: clean.

- [ ] **Step 9: Commit**

```bash
cat > <scratchpad>/m16-task5-commit.txt <<'EOF'
fix: CRL-37 restore.sh cleans up on a signal; API shutdown and dev proxy errors

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git add deploy/restore.sh deploy/tests/test-restore.sh api/corelata_api/app.py api/tests/test_app.py api/csp_proxy.py api/tests/test_csp_proxy.py
git commit -F <scratchpad>/m16-task5-commit.txt
```

---

### Task 6: A run's error names an unreachable model server; Dependabot leaves `@types/node` majors alone (CRL-1 D2, Dependabot)

**Files:**
- Modify: `engine/corelata/llm/openai_compat.py` (`_send`; a helper `_shown`), `.github/dependabot.yml` (the npm block)
- Test: `engine/tests/llm/test_openai_compat.py` (append after `test_timeout_and_connection_errors_are_transient`)

**Interfaces:**
- Consumes: `OpenAICompatBackend(name, base_url, *, transport=...)`, `_backend(handler)` and `_req()` (helpers in the test file).
- Produces: the error text `<backend>: model server unreachable (<base_url>): ConnectError: <message>` (a `TransientBackendError`, as before); `openai_compat._shown(url: httpx.URL) -> str`.

- [ ] **Step 1: Failing test**

In `engine/tests/llm/test_openai_compat.py` insert after `test_timeout_and_connection_errors_are_transient`:

```python


async def test_an_unreachable_server_is_named_in_the_error():
    """What a run's error says when the model server is down (CRL-1 D2)."""

    def unresolved(request):
        raise httpx.ConnectError("[Errno -3] Temporary failure in name resolution", request=request)

    backend = OpenAICompatBackend(
        "demo",
        "http://user:secret@fake-openai:8000/v1/",
        transport=httpx.MockTransport(unresolved),
    )
    with pytest.raises(TransientBackendError) as raised:
        await backend.chat(_req())
    assert str(raised.value) == (
        "demo: model server unreachable (http://fake-openai:8000/v1): "
        "ConnectError: [Errno -3] Temporary failure in name resolution"
    )
    with pytest.raises(TransientBackendError, match=r"^demo: model server unreachable \("):
        await backend.list_models()  # every request through the backend names it

    def reset(request):  # another transport error keeps its plain message
        raise httpx.ReadError("connection reset", request=request)

    with pytest.raises(TransientBackendError) as raised:
        await _backend(reset).chat(_req())
    assert str(raised.value) == "gpu-a: ReadError: connection reset"
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd engine && uv run pytest tests/llm/test_openai_compat.py --no-cov -q`
Expected: FAIL: `AssertionError` on the message, today `demo: ConnectError: [Errno -3] Temporary failure in name resolution`.

- [ ] **Step 3: Name the server**

In `engine/corelata/llm/openai_compat.py`, `_send`, insert between the `httpx.TimeoutException` branch and the `httpx.TransportError` branch:

```python
        except httpx.ConnectError as e:
            # down, not listening, or a name that does not resolve: say which server (CRL-1 D2)
            raise TransientBackendError(
                f"{self.name}: model server unreachable ({_shown(self._client.base_url)}): "
                f"{type(e).__name__}: {e}"
            ) from e
```

and add above `def _payload(`:

```python
def _shown(url: httpx.URL) -> str:
    """The server's URL for an error message: without credentials or the trailing slash."""
    return str(url.copy_with(username=None, password=None)).rstrip("/")


```

- [ ] **Step 4: Dependabot**

In `.github/dependabot.yml`, in the `package-ecosystem: "npm"` block, add after its `groups:` entry (same indentation as `groups:`):

```yaml
    # @types/node describes the Node runtime, which CI and the image pin to 22: its major
    # follows the runtime when the project moves to a new Node line, not npm.
    ignore:
      - dependency-name: "@types/node"
        update-types: ["version-update:semver-major"]
```

- [ ] **Step 5: Run the checks**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/llm/test_openai_compat.py tests/test_doctor.py --no-cov -q`
Expected: all pass (doctor's tests do not depend on the old text).

Run: `cd engine && uv run python -c "import yaml; d = yaml.safe_load(open('../.github/dependabot.yml')); print([u.get('ignore') for u in d['updates']])"`
Expected: `[None, None, [{'dependency-name': '@types/node', 'update-types': ['version-update:semver-major']}], [{'dependency-name': '*', 'update-types': ['version-update:semver-major']}], None]`.

- [ ] **Step 6: Commit**

```bash
cat > <scratchpad>/m16-task6-commit.txt <<'EOF'
fix: CRL-1 a run's error names an unreachable model server; ignore @types/node majors

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git add engine/corelata/llm/openai_compat.py engine/tests/llm/test_openai_compat.py .github/dependabot.yml
git commit -F <scratchpad>/m16-task6-commit.txt
```

---

### Task 7: Docs

**Files:**
- Modify: `README.md` (the M9 section; a new M16 section before `## Development`), `docs/superpowers/specs/2026-10-12-corelata-v1-design.md` (§10.1 after the M15 amendments; §10.3: the M9 sentence and after the M15 amendments), `docs/operator-guide.md` (§3 step 5; §4 after the demo's removal paragraph; §7 after the `review --return` paragraph; §9 "On a new host"; §10 steps 1 and 6, a new step 7, "Going back"; §11 two rows changed, two added), `docs/m9-followups.md`, `docs/m14-followups.md`, `docs/m15-followups.md`
- Create: `docs/m16-followups.md`

**Interfaces:**
- Consumes: the behaviour of Tasks 1-6 as their tests pin it (message texts, ruling numbers).
- Produces: documentation only.

- [ ] **Step 1: README**

In the M9 section replace `discovery polling backs off to 15 s;` with `discovery polling backs off to 15 s (5 s since M16);`.

Insert before `## Development`:

```markdown
## M16: an accepted report is final, a stuck discovery says so

CRL-21 (the owner's decisions of 2026-10-18), CRL-37 (review minors) and the CRL-1 rehearsal
findings. An accept is the reviewer's final word: `POST /api/runs/{id}/review` with `return` on
an accepted run answers 409 "run … was accepted; start a new run to change it", and
`corelata review --return` says the same; the decision is taken under the run's row lock, so a
return that waited for an accept is refused. An accept after a rerun that failed, was cancelled
or stopped at the gate is still allowed, and a live or completed return still wins over a later
accept. The New run screen stops asking about a discovery 10 minutes after it was created
(measured on the server's clock) and says that it has not finished; the discovery is in the URL,
so a reload reads it again, and polling backs off 1, 2, 4 s, then every 5 s (was 15 s) (CRL-21).
`restore.sh` removes its temporary file on every exit, a Ctrl-C included; the API's shutdown
closes the database pool even when its listener died, and no longer swallows its own
cancellation; the development CSP proxy answers 502 when the stack behind it is down; a web test
that makes an unmocked request now fails, and the notification tests wait for what they expect
instead of a fixed time (CRL-37). A run whose model server is down fails with "model server
unreachable (<url>)" before the network error. The operator guide shows how to rehearse an
installation, its backups, an upgrade and a restore with the demo model, names
`CORELATA_HTTP_BIND`, points at the HTTP API's OpenAPI description, writes the pre-upgrade backup
outside the bundle directory and removes the old image after an upgrade (CRL-1).
```

- [ ] **Step 2: Spec amendments**

§10.1, after the paragraph that starts `M15 amendments: a \`return\` is spent only while its rerun is running or completed.`:

```markdown
M16 amendment: an accept is final. `POST /runs/{id}/review` with `return` on a run whose stored
decision is `accepted` is a 409 (`run <id> was accepted; start a new run to change it`), decided
on the decision read under the run's row lock; `corelata review --return` prints the same and
exits 2. A note-less return is still a 422 first. Unchanged: an accept after a rerun that ended
without a report is allowed, an accept after a live or completed return leaves the decision
"returned", and accept after accept is allowed, the latest deciding (CRL-21).
```

§10.3: replace `discovery
polling backs off to 15 s (M9).` with `discovery
polling backs off to 15 s (M9; 5 s since M16).`, and after the paragraph that starts `M15 amendments: when the decision is a return whose rerun ended without a report,` add:

```markdown
M16 amendments: the New run screen keeps the discovery in its URL (`?project=<id>&discovery=<id>`,
replaced by each **Suggest value**), so a reload reads it again. Discovery polling backs off 1, 2,
4 s, then every 5 s, and stops once a read finds the discovery still created or running 10
minutes after its `created_at`, measured on the server's clock (the answer's `Date` header);
the screen then says, in a polite live region, "Discovery has not finished after 10 minutes. It may still be running, or its worker may have stopped. Reload this page to check again, or start a new discovery." A reload reads once and shows the same without polling; a discovery seen
completed or failed shows as before, however old. After an accept, **Accept** and **Return with
note** stay disabled; a page opened before another reviewer accepted gets the 409 in the Return
dialog and re-reads the run (CRL-21).
```

- [ ] **Step 3: Operator guide**

§3, replace step 5 (`5. Open \`http://<host>:8080\` in a browser.`) with:

```markdown
5. Open `http://<host>:8080` in a browser. To publish the port on this host's loopback address
   only (behind a reverse proxy, or reached through an SSH tunnel), add
   `CORELATA_HTTP_BIND=127.0.0.1` to `.env`; `CORELATA_HTTP_PORT` changes the port. Apply either
   as in "Applying changes" (section 5).
```

§4, after the paragraph that ends `` `docker compose -f compose.yaml -f compose.demo.yaml down -v` `` (the "Remove the demo, its data included" block) and before `Stop the demo before you start the real installation`, add:

````markdown
**Rehearsing an installation with the demo model.** To try backups, an upgrade and a restore
without a model server, make the overlay part of this directory's Compose setup instead of
passing `-f` each time: after `./install.sh`, add one line to `.env`:

```
COMPOSE_FILE=compose.yaml:compose.demo.yaml
```

Every plain `docker compose` command in this directory then acts on the demo stack, and so do
`backup.sh` and `restore.sh`, which run them: sections 7 to 10 apply as written, and section 10
carries the line over when it copies `.env`. Two differences: the stack reads
`config/corelata.demo.yaml` (the overlay sets it), not `config/corelata.yaml`, so leave the demo
file as shipped (`install.sh` checks it); and the Compose project is `corelata-demo`, so the
volumes are `corelata-demo_pgdata` and `corelata-demo_files`, not the names section 9 gives. To
move to your model servers, run `docker compose down -v` (the demo's data goes with it), remove
the line, edit `config/corelata.yaml` and start as in section 3.
````

§7, after the paragraph that starts `` `review --return` queues a new run that carries the note `` add:

```markdown
An accept is final: `review --return` (or **Return with note**) on an accepted run is refused
with "run … was accepted; start a new run to change it". Start a new run on the same sources
instead.

**The HTTP API.** Everything the web app does goes through the HTTP API under `/api`, which a
script can call as well (uploads, runs, reviews, exports). `GET /api/openapi.json` describes
every route; it needs the same sign-in as the rest (section 6), while `GET /api/health` needs
none. Listing runs needs the project: `GET /api/runs?project_id=<id>` answers
`{"runs": [...], "next_before": ...}`, newest first, 100 at a time (`limit`, at most 500); pass
`before=<next_before>` for the next page. Without `project_id` it is a 422.
```

§9, "On a new host", step 2: replace `2. Copy \`config/corelata.yaml\`, \`config/packs/\` and \`.env\` over the freshly created ones.` with:

```markdown
2. Copy `config/corelata.yaml`, `config/packs/` and `.env` over the freshly created ones (a
   `.env` with the demo's `COMPOSE_FILE` line, section 4, restores the demo stack).
```

§10: replace step 1 with:

```markdown
1. In the old directory, take a backup outside the bundle directories, which an upgrade leaves
   behind: `./backup.sh /srv/backups/corelata`. Keep the old bundle's
   `corelata-<version>-linux-amd64.tar` and `.sha256` too: going back needs both.
```

and after step 6 add:

```markdown
7. Once the new version works, remove the old image: `docker image ls corelata/app` lists them,
   `docker image rm corelata/app:<old version>` removes one. `postgres:16-alpine` is one tag: a
   newer bundle may load a newer image under it, which leaves the old one untagged (`<none>` in
   `docker image ls`); `docker image prune` removes untagged images.
```

In "**Going back.**" replace `restore the pre-upgrade backup
from step 1 with \`./restore.sh\` in the old directory.` with `restore the pre-upgrade backup
from step 1 (in \`/srv/backups/corelata\`) with \`./restore.sh\` in the old directory; if you
removed the old image (step 7), run \`./install.sh\` there first, which loads it again from the old
bundle.`

§11: replace the "Port 8080 is taken" row with:

```markdown
| Port 8080 is taken | Set `CORELATA_HTTP_PORT=8081` (or another) in `.env` and recreate `api`. `CORELATA_HTTP_BIND=127.0.0.1` in the same file publishes the port on the loopback address only (behind a reverse proxy or an SSH tunnel). |
```

and add after the row that starts `| The Review screen says "The rerun failed: …"`:

```markdown
| A return is refused with "was accepted; start a new run to change it" | The report was accepted, which is final. Start a new run on the same sources and statement; the accepted report stays as it was. |
| The New run screen says "Discovery has not finished after 10 minutes" | The discovery is still queued or running. Check `docker compose ps worker` and `docker compose logs worker`: a stopped worker leaves it queued; a worker that died mid-discovery has it restarted after `worker.stalled_after_s`; a discovery whose job was lost is marked failed by the next sweep. Reload the page to read it again, or start a new discovery. |
| A run failed with "model server unreachable (…)" | The model server named in the parentheses refused the connection, is not listening, or its name does not resolve from the containers. Check it is up and reachable from a container (`docker compose exec api curl -s <base_url>/models`). |
```

- [ ] **Step 4: Follow-up files**

Append to the end of each item's last line:

- `docs/m9-followups.md`, the item ending `decide whether an\n  accepted report should be returnable.`: ` — **closed in M16** (CRL-21: an accept is final; R-M16-1).`
- `docs/m9-followups.md`, the item ending `(stop after 10 minutes with a message) is a UX question.`: ` — **closed in M16** (CRL-21: a 10-minute ceiling with a message; R-M16-2).`
- `docs/m9-followups.md`, the item ending `(R-M9-12 kept 15 s; a UX question).`: ` — **closed in M16** (CRL-21: 5 s; R-M16-3).`
- `docs/m14-followups.md`, the `app.py`'s lifespan item (ending `with uvicorn's lifespan protocol and \`run()\` catching \`Exception\`.`): ` — **closed in M16** (CRL-37).`
- `docs/m14-followups.md`, the `test_an_unreachable_database_is_retried_with_backoff` item: ` — **closed in M16** (CRL-37).`
- `docs/m14-followups.md`, the `RunChannel.received` item: ` — **closed in M16** (CRL-37).`
- `docs/m14-followups.md`, the `frameBridge.test.ts` item (ending `(unreachable through\n  \`withBridge\`).`): ` — **closed in M16** (CRL-37), the stylesheet path; the empty-nonce branch stays unreachable.`
- `docs/m14-followups.md`, the `api/csp_proxy.py` item (ending `without a cap.`): ` — **closed in M16** (CRL-37), the 502 and the streaming test; the disconnect and the body cap stay (development only).`
- `docs/m14-followups.md`, the msw item (ending `and should be silenced or mocked.`): ` — **closed in M16** (CRL-37: mocked, and an unmocked request now fails its test).`
- `docs/m15-followups.md`, the `test_rerun_end.py`'s `broken` item: ` — **closed in M16** (CRL-37).`
- `docs/m15-followups.md`, the `restore.sh` temporary-file item: ` — **closed in M16** (CRL-37).`

Create `docs/m16-followups.md`:

```markdown
# M16 follow-ups

## Divergences from Coglossa

- `restore.sh`'s single `on_exit` trap and the `corelata-restore.XXXXXX` temporary file —
  **backport** with CGL-18 (Coglossa's restore script has the same late `trap restart EXIT`).
- `corelata_api.app.stop_listener` — Corelata only (Coglossa's API has no LISTEN task).
- `OpenAICompatBackend`'s "model server unreachable (<url>)" — **backport candidate**: Coglossa's
  adapter formats transport errors the same way.
- `web/src/test/setup.ts` failing a test on an unmocked request — **backport candidate** for
  Coglossa's web tests.
- The accept-is-final rule, the discovery ceiling and the discovery in the URL — Corelata only.

## Spec deviations

- None. §10.1 and §10.3 carry M16 amendments.

## Rulings during execution

- How the plan applied R-M16-1 to R-M16-13, and the rulings it added (R-M16-14 to R-M16-24), are
  in its Global Constraints. Number new ones from R-M16-25.

## Should fix soon

- None.

## Later

- The ceiling's message no longer promises a sweep (R-M16-18): the sweep fails a discovery only
  when its job is gone; a discovery whose worker died is re-queued after `worker.stalled_after_s`
  (900 s by default) and runs again, and nothing sweeps while no worker runs. A per-discovery
  deadline in the worker would let the screen say how a stuck discovery will end.
- The discovery's age falls back to the browser's clock when an answer has no `Date` header (a
  proxy that strips it); a skewed workstation behind such a proxy is back to the client clock.
- The New run screen keeps the discovery in the URL but not the chosen sources: a reload selects
  every source again (as before M16), so a discovery made on a subset shows next to a full
  selection.
- `received_until`'s deadline branch (the loop ends because the time is up between two
  notifications) has no test of its own; the timeout case is covered by an empty read.
- An accept is final for the run; a report accepted by mistake needs a new run. An "undo
  accept" (with an audit event) would be a product decision.
```

- [ ] **Step 5: Check nothing else moved**

Run: `make lint && git diff --stat main -- docs/m1-followups.md docs/m2-followups.md docs/m3-followups.md docs/m4a-followups.md docs/m4b-followups.md docs/m5-followups.md docs/m6-followups.md docs/m7-followups.md docs/m8-followups.md docs/m10-followups.md docs/m11-followups.md docs/m12-followups.md docs/m13-followups.md engine/corelata/bench schema`
Expected: lint clean; the diff prints nothing.

Run: `cd api && uv run pytest tests/test_csp_proxy.py::test_the_proxy_sets_the_operator_guides_sample_policy_word_for_word --no-cov -q`
Expected: 1 passed (the guide's nginx sample is untouched).

- [ ] **Step 6: Commit**

```bash
cat > <scratchpad>/m16-task7-commit.txt <<'EOF'
docs: M16 README section, spec amendments, operator guide (CRL-1 findings), follow-ups

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git add README.md docs/superpowers/specs/2026-10-12-corelata-v1-design.md docs/operator-guide.md docs/m9-followups.md docs/m14-followups.md docs/m15-followups.md docs/m16-followups.md
git commit -F <scratchpad>/m16-task7-commit.txt
```

---

## Final verification (after the whole-branch review)

```bash
make lint
make test-engine    # 904 passed (890 before)
make test-api       # 169 passed (165)
make test-web       # 192 passed (182), no "intercepted a request" in the output
make e2e            # 6 passed
make deploy-check
make schema && git status --short schema web/src/api/schema.d.ts   # no output
grep -n '^version' engine/pyproject.toml                            # still 0.1.4
```

CI must be green on all six jobs (engine, api, web, e2e, deploy, airgap) and `ci-status` before the merge. The web job's log must show no msw "intercepted a request" line.

## Live rehearsal (the controller runs this after the merge; not a task)

**A. Reviews and discovery on a dev stack.** A stack by hand, so the worker and the model can be stopped under a running API. From the repository root, `make db-up` and `web/dist` built (`cd web && pnpm build`). Write `<scratchpad>/m16.yaml`:

```yaml
backends:
  local: {base_url: "http://127.0.0.1:8000/v1", max_concurrency: 4}
models:
  m1: {backend: local, name: fake-model, context_window: 32768}
roles:
  gate: {model: m1}
  writer: {model: m1}
  conveyor: {model: m1}
  auditor: {model: m1}
storage: {path: <scratchpad>/m16-files}
```

```sh
export CORELATA_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/corelata_m16
psql postgresql://corelata:corelata@127.0.0.1:55433/postgres -c 'CREATE DATABASE corelata_m16'
CFG=<scratchpad>/m16.yaml
(cd engine && uv run corelata migrate --config $CFG)
# three terminals, each with CORELATA_DATABASE_URL exported:
cd engine && uv run corelata fake-openai --port 8000                            # A: the model
cd engine && uv run corelata worker --config $CFG                               # B: the worker
cd api && uv run corelata-api --config $CFG --port 8080 --web-dir ../web/dist   # C: the API
```

- [ ] Accept and try to return. Open http://127.0.0.1:8080, start a run on `docs/examples/varna-port.txt` ("Varna port capacity expansion matters to shippers"), wait for `completed`, open its review, **Accept**. Both **Accept** and **Return with note** are disabled and the badge says "Accepted". Then `curl -s -X POST localhost:8080/api/runs/<id>/review -H 'content-type: application/json' -d '{"action":"return","note":"again"}'` answers `409` with `{"detail":"run <id> was accepted; start a new run to change it"}`, and `(cd engine && uv run corelata review <id> --return --note again --config $CFG); echo "exit=$?"` prints `error: run <id> was accepted; start a new run to change it` and `exit=2`.
- [ ] A stale tab. Start a second run, open its review in two tabs, accept in the first; in the second (not focused since), **Return with note**, type a note, **Return**: the dialog shows the 409 text; **Cancel**; the tab shows "Accepted" with both buttons disabled.
- [ ] The poll cadence. Stop terminal B (the worker), click **Suggest value**: the URL gains `&discovery=<id>`, and the browser's network tab shows `GET /api/discoveries/<id>` at about 1, 2, 4, 5, 5 s intervals (then every 5 s); the screen says "Looking for value in the selected sources…".
- [ ] The ceiling, without waiting 10 minutes (the product is unchanged; the rehearsal moves the discovery's `created_at` in the rehearsal database, which is what the ceiling reads): `psql "$CORELATA_DATABASE_URL" -c "UPDATE discovery SET created_at = now() - interval '11 minutes' WHERE id = '<id>'"`. Within 5 s the open tab shows exactly "Discovery has not finished after 10 minutes. It may still be running, or its worker may have stopped. Reload this page to check again, or start a new discovery." and the network tab shows no further `GET /api/discoveries/<id>`. Reload: one `GET /api/discoveries/<id>`, the same message, no more requests. Start terminal B again: the worker runs the discovery (its job was still queued); reload: the suggestions show.
- [ ] Drop the rehearsal database: `psql postgresql://corelata:corelata@127.0.0.1:55433/postgres -c 'DROP DATABASE corelata_m16'`.

**B. `restore.sh` and Ctrl-C.** In an install directory (the 0.1.4 rehearsal install, or `make bundle` + `./install.sh`, with the M16 `deploy/restore.sh` copied over the installed one), `./backup.sh /tmp/m16-backups`. The schema query must be slow enough to press Ctrl-C during it: pause the database container for it, `docker compose pause postgres` in a second shell, then in the first `./restore.sh --yes /tmp/m16-backups/corelata-db-*.dump /tmp/m16-backups/corelata-files-*.tar.gz` (it hangs on `docker compose exec ... psql`), Ctrl-C, then `docker compose unpause postgres`. Expect exit 130 (`echo $?`), `ls "${TMPDIR:-/tmp}"/corelata-restore.*` finds nothing, and `docker compose ps` shows `api` and `worker` still running. (`restore.sh` first runs `docker compose up -d --wait postgres`, which waits on a paused container's health check; if it hangs there instead, pause the container right after the "pg_restore -l" check, watching `ps` for the `psql` call.)

**C. The demo as an installation, by the guide's commands only (R-M16-7).** On a host with Docker (the CRL-1 VM, or locally): unpack the bundle from `make bundle` (or the 0.1.5 release candidate), `./install.sh`, append `COMPOSE_FILE=compose.yaml:compose.demo.yaml` and (on the VM) `CORELATA_HTTP_PORT=8090` and `CORELATA_HTTP_BIND=127.0.0.1` to `.env`; `docker compose up -d --wait`; `docker compose exec api corelata doctor` (all PASS, `config: /etc/corelata/corelata.demo.yaml is valid`); start a run with the section 4 command written without `-f` (`docker compose exec worker corelata run /opt/corelata/examples/varna-port.txt --project demo --statement "Varna port capacity expansion matters to shippers"`); `./backup.sh /srv/backups/corelata` (or a scratch directory); `docker volume ls` shows `corelata-demo_pgdata` and `corelata-demo_files`; `./restore.sh --yes <dump> <archive>`; doctor again; the run is back. Stop the model (`docker compose stop fake-openai`), return the report: the rerun fails with `demo: model server unreachable (http://fake-openai:8000/v1): ConnectError: …`. Tear down with `docker compose down -v` and `docker image rm corelata/app:<version> postgres:16-alpine`.

**D. Gates and the OpenRouter regression.**

- [ ] `make e2e`: 6 passed.
- [ ] `corelata doctor --config <openrouter.yaml>`: every line PASS.
- [ ] `corelata bench --config <openrouter.yaml> --scenarios real --out bench-m16-real/`: compare with the M15 baseline below; M16 changes nothing a run sends, so a difference is model variance.
- [ ] Fill in the table, add it to Jira CRL-21, CRL-37 and CRL-1 (close CRL-21 and CRL-37 with the rehearsal evidence; note on CRL-1 which guide findings the release carries); then cut 0.1.5.

| Measure | M15 baseline (2026-10-18) | M16 |
|---|---|---|
| `doctor` (OpenRouter) | all PASS | |
| Real set: full agreement | 6/8 | |
| Gate agreement | 7/8 | |
| Rule-failure agreement | 3/4 | |
| Duration | 76 s | |
| Return of an accepted run: UI disabled, API 409, CLI exit 2 | n/a | |
| Discovery cadence 1, 2, 4, 5, 5 s | n/a | |
| 10-minute message, then no requests; same after a reload | n/a | |
| `restore.sh` Ctrl-C during the schema query: exit 130, no temp file | n/a | |
| Demo installation: backup and restore by the guide's commands | n/a | |
