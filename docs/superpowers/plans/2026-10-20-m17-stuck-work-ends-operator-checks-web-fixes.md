# M17 Stuck Work Ends on Its Own, Early Operator Checks, Web Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close Jira CRL-38, CRL-39 and CRL-40: (1) a discovery has a deadline (`worker.discovery_deadline_s`, default 600 s): once it is that old and not ended it is failed with "Discovery did not finish within 10 minutes and was stopped. Start a new discovery.", whether or not a worker runs, and the New run screen shows that without a reload; (2) cancelling a run whose worker is gone (its heartbeat `worker.stalled_after_s` old, or its worker row deleted) ends it at once, closes its job, and a worker that was taken for dead can never write over that ending; (3) a backend `base_url` with a query string or a fragment is refused when the configuration loads, so `corelata doctor` fails its config check; doctor's model suggestions ignore case; the run list gets the `(project_id, created_at DESC, id DESC)` index (migration 0006), which the measurement supports; (4) the New run screen keeps the chosen sources in the URL, a request cancelled by leaving a page is not shown as a network error, the evidence panel says it is loading, the Suggest request leaves out an empty `audience_hint`; (5) the M16 test leftovers: `received_until`'s deadline branch, the return-race lock poll and the `NewRunPage` race test wait for what they mean.

**Architecture:** Engine: `store/discoveries.expire` is one conditional `UPDATE … WHERE state IN ('created','running') AND created_at <= now() - make_interval(secs => :deadline_s)`; `service.get_discovery` runs it for the discovery it reads (so the deadline holds whenever anyone looks, with no worker), `worker/sweep.expire_discoveries` runs it for all of them every minute, and `execute_discovery` checks the deadline at its claim, bounds the model work with `asyncio.timeout`, and decides its ending under the row lock on the database's clock, never overwriting an ended discovery. `DiscoveryView` gains `deadline_at` (a schema change), which the web uses to keep polling until the deadline plus 15 s. `service.cancel_run` asks `store/runs.close_abandoned_job` (procrastinate's own stalled-worker test, under `FOR UPDATE`) and ends the run like a cancel of a queued run when it finds one; `DbObserver.locked` raises `RunEnded` for a run that ended, and `execute_run` stops. `BackendConfig` validates `base_url`; `doctor._similar` casefolds. Migration 0006 creates `ix_run_project_created`. Web: `NewRunPage` reads and writes `?sources=`; every query passes TanStack Query's `signal` and `unwrap`/`unwrapText` let an `AbortError` through; `ProvenanceTab` shows "Loading evidence…". Docs: README, spec §7.5/§8.3/§10.1/§10.3/§11/§12, operator guide §5, §7, §10, §11, follow-ups.

**Tech Stack:** Python 3.12, SQLAlchemy 2 async + psycopg 3.3, procrastinate 3.10, Alembic, FastAPI, pydantic 2, httpx; React 19, React Router 8, TanStack Query 5, openapi-fetch 0.17, Vitest 4, msw 2.15, Playwright; Postgres 16; Markdown docs.

**Spec:** `docs/superpowers/specs/2026-10-12-corelata-v1-design.md` — §7.5 (worker, stalled jobs, orphan sweep; the brief's "§8" for these is §7.5 in the spec), §8.3 (tables and indexes), §10.1 (discovery and cancel routes), §10.3 (New run screen, discovery), §11 (configuration), §12 (packaging, migrations, upgrade). Ticket texts: Jira CRL-38, CRL-39, CRL-40 (restated in the brief and below). Context: `docs/m16-followups.md` ("Later"), `docs/m3-followups.md` (the orphaned cancel), `docs/m4b-followups.md` (evidence loading, `audience_hint`, `AbortError`), `docs/m12-followups.md` (`_similar`), `docs/m14-followups.md` (the run list index), `docs/superpowers/plans/2026-10-19-m16-review-discovery-decisions-and-minors.md` (R-M16-1 to R-M16-24, the discovery ceiling this plan builds on).

## Global Constraints

- 95% branch coverage for `engine` and `api` (`--cov-fail-under=95`), `filterwarnings = ["error"]`; `ruff check` and `ruff format --check` clean (line length 100). Vitest 95% on lines, branches, functions and statements (web branches were 95.87% at the baseline: every new branch gets its test); `pnpm lint` (eslint, prettier, `tsc --noEmit`) clean; `pnpm build` clean. Playwright journeys stay green (`make e2e`: 6, no journey change). `ci-status` is the required check. `make deploy-check` clean.
- Python tests that touch Postgres run against the dev database (`make db-up`; `CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres`). A single test file: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/x.py --no-cov -q` (and the same from `api/`). Full gates: `make test-engine`, `make test-api`, `make test-web`, `make lint`, `make e2e`, `make deploy-check`. Do not run the full pytest and Vitest suites concurrently. Never stop the dev Postgres container; drop any database you create.
- **One schema change, one migration, one config field.** `DiscoveryView.deadline_at` (Task 1): `make schema` changes `schema/discovery-view.schema.json`, `schema/openapi.json` and `web/src/api/schema.d.ts`, committed with Task 1; a second `make schema` changes nothing. Migration `0006` (Task 5); Alembic head becomes `0006`. Config field `worker.discovery_deadline_s` (Task 1). No new API route, so `api/tests/test_openapi.py` is untouched. Do not edit the docstring of `POST /api/runs/{id}/cancel` (`api/corelata_api/routes/runs.py`): it is a description in `schema/openapi.json`.
- Web tests mock every request with msw; `web/src/test/setup.ts` fails a test that makes an unmocked request. Poll intervals are read through `web/src/test/poll.ts`, never fake timers. Fixtures live in `web/src/test/fixtures.ts`.
- Commit messages end with exactly these two lines, nothing after them (R-M17-9):
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`
  `Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK`
  (implementer subagents may use their own harness's model line instead). Write the message to a uniquely named scratchpad file and `git commit -F FILE`. Never `git stash`. Never `git add .`.
- Version stays `0.1.5` (`engine/pyproject.toml`, `tests/test_version.py`); the controller cuts 0.1.6 after the live rehearsal.
- Rulings (record in the SDD ledger, carried here). R-M9-1 to R-M9-12, R-M10-1 to R-M10-10, R-M11-1 to R-M11-8, R-M12-1 to R-M12-10, R-M13-1 to R-M13-12, R-M14-1 to R-M14-15, R-M15-1 to R-M15-22 and R-M16-1 to R-M16-24 stay in force, except where R-M17-1 and R-M17-12 move R-M16-2's ceiling.
  - **R-M17-1 (CRL-38, the discovery deadline).** A config field for a discovery's deadline, `worker.discovery_deadline_s`, default 600 s (the screen's 10 minutes), at least 60 s, documented in the operator guide and in both `corelata.example.yaml` files. Once a discovery is older than the deadline (from `created_at`, on the database's clock) and not terminal, it **always** ends as failed, with the error `Discovery did not finish within 10 minutes and was stopped. Start a new discovery.` (the time rendered from the config: `1 minute`, `N minutes`, or `N seconds` when it is not whole minutes). This holds whether or not a worker runs (mechanism: R-M17-10). A worker that picks the job up after the deadline does not run it; one running at the deadline is stopped; one that finishes after it does not resurrect the discovery (R-M17-11). The procrastinate job of a failed discovery is a no-op when delivered (it was already: `execute_discovery` returns on an ended discovery; now pinned). The screen shows the server's failure when the deadline passes without a reload (R-M17-12). M16's message stays, exactly `Discovery has not finished after 10 minutes. It may still be running, or its worker may have stopped. Reload this page to check again, or start a new discovery.`, as the fallback for a server that did not end the discovery (a clock that is off).
  - **R-M17-2 (CRL-38, cancelling an orphaned run).** A run whose job belongs to a worker that is provably gone ends as cancelled at once, by the same terminal path as every other cancel (`reruns_ended` for a rerun, the run-channel notification), and its job cannot resume (R-M17-15). Two workers never both think they own a run, and a live slow worker's run is never cancelled under it (R-M17-15, R-M17-16).
  - **R-M17-3 (CRL-39, `base_url`).** Config validation rejects a backend `base_url` with a query string or a fragment; the message names the field, says why (the request path would land inside the query) and what to write instead (the address and path only; a key goes in the environment variable `api_key_env` names). Pinned by config tests; `corelata doctor` reports it as the config check's FAIL through the existing path.
  - **R-M17-4 (CRL-39, doctor suggestions).** `doctor._similar` matches the prefix case-insensitively and keeps its ranking (sorted, at most five); pinned.
  - **R-M17-5 (CRL-39, runs index, evidence first).** Measured (R-M17-20); the index changes the plan materially, so it lands as migration **0006**, with its downgrade, the air-gap upgrade path, the guide's upgrade note and the restore of a 0.1.5 backup checked (R-M17-20).
  - **R-M17-6 (CRL-40, web).** The chosen sources live in the URL beside `project` and `discovery`, written with replace navigation; ids that are not the project's are dropped silently; no parameter means every source; another project drops it (R-M17-21). The API client lets an `AbortError` through, so a query cancelled on navigation is a cancellation, not the network error (R-M17-22). `ProvenanceTab` shows "Loading evidence…" in a polite live region while a selected claim's evidence loads. The Suggest request leaves out an empty `audience_hint` (R-M17-23).
  - **R-M17-7 (CRL-40, M16 test leftovers).** `RunChannel.received_until`'s deadline branch has a test of its own; the return-race lock poll counts only sessions the holder's backend blocks; the `NewRunPage` race test waits for the held POST to answer and the mutation to settle, not 300 ms.
  - **R-M17-8 (scope, gates, docs, release).** As in the first constraint above. Docs: a README M17 section; spec amendments (§7.5 deadline and cancel, §8.3 index, §10.1, §10.3, §11 config, §12 migration 0006); the operator guide (the config field, the base URL rule, what the screen shows, cancelling a run whose worker died, a 0.1.5 upgrade note); the follow-up items struck "— **closed in M17** (CRL-nn)"; a new `docs/m17-followups.md`. The version stays 0.1.5.
  - **R-M17-9 (attribution).** Every commit message ends with exactly the two lines above.
  - Rulings this plan adds (from reading the code at 284b0fb and applying Tasks 1-7 to a scratch copy of the repository: engine 941 passed (908 at the baseline), coverage 98.41%; api 171 (169), 99.69%; web 204 Vitest (194), 98.44/96.23/99.59/99.5%; e2e 6 passed; ruff, `pnpm lint` and `pnpm build` clean; `make schema` changed the three files named above and was stable on a second run; `make deploy-check` clean; the new tests of Tasks 1, 2, 3 and 6 seen failing against today's code where they pin a change):
    - **R-M17-10 (CRL-38, the mechanism).** Three places enforce one statement, `discoveries.expire` (a conditional `UPDATE`, idempotent): (a) `service.get_discovery` runs it for the discovery it reads before it builds the view, so `GET /api/discoveries/{id}`, the POST's answer and `corelata status` all fail a discovery past its deadline; (b) the worker's minute task (`sweep_orphans_task`) runs it for every discovery (`sweep.expire_discoveries`), so rows nobody reads end too; (c) `execute_discovery` checks at its claim and at its finish. Why not the alternatives: a periodic task in the API runs in every API process, needs its own lifespan task (M16 spent a ruling on the listener's shutdown), and does nothing for `corelata status` against a database with no API; a check only at the worker's claim needs a worker, which is exactly what is missing when a discovery is stuck. The read-time statement holds the deadline at the moment anyone can observe it, needs no process, and costs one primary-key `UPDATE` that matches no row on every poll before the deadline (it takes no lock when its `WHERE` does not match).
    - **R-M17-11 (CRL-38, the boundary).** Every decision is taken under the discovery's row lock and on the database's clock (`now()`), so whichever transaction commits first decides: an expiry that commits first leaves `failed`, and the worker's finish then sees an ended discovery and writes only its model calls and usage (never state, error, candidates or `finished_at`; logged "ended while it ran"); a worker finish that commits first in time leaves `completed`, and an expiry waiting for the lock then matches nothing. The worker's own finish fails the discovery with the deadline error when its transaction finds the discovery `deadline_s` or more old, or when its `asyncio.timeout` budget (the time left at the claim) expired: an answer that arrives after the deadline is not kept, even when nobody read in between. A claim at or after the deadline fails it without a model call. Pinned in Task 1, including the lock race with `pg_blocking_pids`.
    - **R-M17-12 (CRL-38, the screen; the schema change).** `DiscoveryView.deadline_at` (`created_at` + `worker.discovery_deadline_s`) tells the screen the server's deadline. The screen keeps polling until the discovery is `max(10 minutes, deadline + 15 s)` old by the server's clock (`discoveryCeiling`), so at least one read lands after the server failed it and the screen shows the server's error, and the fallback message ("after 10 minutes") is never shown sooner than 10 minutes. With the default 600 s, the read that crosses 10 minutes already returns `failed`. A `deadline_at` that does not parse falls back to 10 minutes. Without `deadline_at` a deadline above 10 minutes would leave the screen stopped before the server; capping the config at 600 s instead would take away the only remedy for a slow air-gapped model server.
    - **R-M17-13 (CRL-38, which clock).** The deadline is compared with the database's `now()`; `discovery.created_at` is written by the API process's clock (`models.utcnow`). In the Compose stack both run on one host, so they agree; a separate database host with a skewed clock moves the deadline by the skew (recorded in `docs/m17-followups.md`, "Later"). `engine/tests/worker/test_sweep.py` backdates its discoveries 5 minutes instead of 10 (past the 120 s orphan grace, inside the deadline), because a read 10 minutes old now fails them.
    - **R-M17-14 (CRL-38, the field).** `worker.discovery_deadline_s: float = Field(600.0, ge=60)`, in the operational `worker` section (not part of `config_hash`). `service.get_discovery(..., deadline_s=)` and `service.cancel_run(..., stalled_after_s=)` take the values as keyword arguments that default to the configuration's defaults (`service.DISCOVERY_DEADLINE_S`, `service.STALLED_AFTER_S`), so the existing tests need no change; the API and the CLI pass their configuration's values, pinned by tests with non-default values (60 s, 30 s).
    - **R-M17-15 (CRL-38, "provably gone").** Decided, not deferred: a worker is gone when the run's job is `doing` and its worker row is deleted (`worker_id` NULL; procrastinate prunes rows older than `stalled_worker_timeout`) or its `last_heartbeat` is older than `worker.stalled_after_s`. That is procrastinate's own stalled-worker query (`select_stalled_jobs_by_heartbeat`), which the requeue already uses to start such a run over on another worker, so the cancel claims nothing the requeue does not. A live worker heartbeats every 10 s from its own task (procrastinate's `update_heartbeat_interval`), however long a model call takes, so a slow live worker's run keeps today's behaviour: the flag, then the next stage boundary. A run has at most one `doing` job (every job carries the lock `run:<id>`, and procrastinate never starts a job whose lock a `doing` job holds). Only a `doing` job counts: a job back in `todo` (re-queued, or a retry scheduled) or no job at all keeps today's behaviour (the next worker ends the run at its claim; the orphan sweep fails a run with no job). Under the run's row lock, `close_abandoned_job` selects that job `FOR UPDATE OF j` and closes it with `procrastinate_finish_job_v1(id, 'aborted', false)` in the cancel's transaction, so the requeue can never move it back to `todo`; lock order run row, then job row, and no path holds a job row while it waits for a run row. A job delivered anyway finds a terminal run at `_begin` and does nothing (pinned).
    - **R-M17-16 (CRL-38, the fence).** `DbObserver.locked(s)` reads the run under its row lock and raises `RunEnded` when the run is terminal; `state_changed`, `stage_recorded` and `execute_run`'s save transaction use it, and `execute_run` catches `RunEnded` before anything else, logs `run <id> ended while this worker ran it (...); stopping without writing` and returns. Without it, a worker that was taken for dead but is alive wrote `drafting` over `cancelled` (seen on the scratch copy). A run's state only becomes terminal through its own ending paths, so the fence never fires for a live worker's own run. The wider fence (a re-queued run whose first worker is still alive: compare `attempts`) is a follow-up.
    - **R-M17-17 (CRL-38, the threshold's source).** The API and the CLI read `worker.stalled_after_s` from their own configuration; the worker uses the same field for its requeue and procrastinate's `stalled_worker_timeout`. In the bundle all three read one file. The web's **Cancel run** still turns into "Stopping after the current stage…" after the first press; a run whose worker died less than `stalled_after_s` ago keeps that until it is cancelled again (`corelata cancel`, or `POST /api/runs/{id}/cancel`) after the threshold, which the guide says; a second button on the screen is a follow-up.
    - **R-M17-18 (CRL-39, `base_url`).** Any `?` or `#` is refused (an empty query, `http://h/v1?`, breaks the same way). The message, after load_config's `<path>: backends.<name>.base_url: Value error, `: `must not contain a query string (?...) or a fragment (#...): Corelata adds the request path (/chat/completions, /models) to base_url, so it would land inside the query. Write the server's address and path only, such as http://models:8000/v1, and give a key with api_key_env (the name of an environment variable that holds it)`. Credentials in the authority (`https://u:p@h/v1`) stay allowed. A 0.1.5 configuration with such a URL never worked; under 0.1.6 it stops `migrate` (the guide's upgrade note says so). `integrations.coglossa.base_url` has the same join and is left as it is (follow-up).
    - **R-M17-19 (CRL-39, `_similar`).** The prefix is compared with `str.casefold()` on both sides; the result is still `sorted()` (code-point order, so `QWEN/…` sorts before `Qwen/…` before `qwen/…`) and cut to five.
    - **R-M17-20 (CRL-39, the measurement and 0006).** A scratch database at head 0005 with 50,000 completed runs in five projects (10,000 each, `pack_snapshot` the real 12 kB resolved pack), physically ordered by time so projects interleave as in use (`CLUSTER` on `created_at`), `VACUUM ANALYZE`. The `GET /api/runs` query as `store.runs.list_runs` sends it (`SELECT *`, `ORDER BY created_at DESC, id DESC LIMIT 101`), each run twice. Without the index: Bitmap Index Scan on `ix_run_project_id` → Bitmap Heap Scan (10,000 rows, 2,000 heap blocks) → top-N heapsort; first page 6.9 ms and 2,011 shared buffers; a keyset page 5,000 runs in (`(created_at, id) < (…)` as a filter, 5,001 rows removed) 7.5 ms and 2,011 buffers. With `(project_id, created_at DESC, id DESC)`: Index Scan on it, no sort, the keyset condition in the index condition; first page 0.08–0.11 ms and 25 buffers, keyset page 0.09–0.19 ms and 24 buffers. The sort's cost grows with the project, the index scan's does not: the index lands as 0006. The model declares it (`Run.__table_args__`, `text("created_at DESC")`), so `test_models_match_the_migrations` stays green (checked). `ix_run_project_id` stays (the project cascade uses it; the new index would serve too; dropping it is a follow-up). A plain `CREATE INDEX` in `migrate`, which runs before `api` and `worker`. The air-gap test installs the same bundle as a second site, so 0006 runs at the first site's install and the "upgrade" step is a no-op for it: no change there; the live rehearsal upgrades a real 0.1.5 install (D). `restore.sh` ends with `docker compose up -d --wait`, which runs `migrate` again, so a 0.1.5 backup restored into 0.1.6 is migrated to 0006 (the rehearsal checks it).
    - **R-M17-21 (CRL-40, the sources parameter).** `?sources=<id>,<id>` (one parameter, comma-separated, written by `URLSearchParams`, so the comma shows as `%2C`). Absent: every source, new ones too. Present: the listed ids that belong to the project, in the project's order; empty or only stale ids: none selected ("Choose at least one source."). Toggling a source writes it with replace navigation and keeps `discovery`; **Suggest value** keeps `sources` (its functional update copies the current parameters); another project drops both (`changeProject` sets `{project}` only, as in M16). An upload adds the new ids to an explicit list and leaves an absent one absent. The state that keyed a choice to its project goes: the URL is the key.
    - **R-M17-22 (CRL-40, aborts).** No query passes TanStack Query's `signal` today, so a query is never aborted on navigation; the `AbortError` the ticket names could come only from the browser. Every `useQuery`/`useInfiniteQuery` read now passes `signal` to `client.GET` (or `unwrapText(url, signal)`), so leaving a page cancels what it was still loading and TanStack Query reverts the query (status `pending`, fetch `idle`, no error); `unwrap` and `unwrapText` rethrow an error named `AbortError` unchanged instead of the network error. Mutations pass no signal (unchanged).
    - **R-M17-23 (CRL-40, `audience_hint`).** Today the API treats `""` and an absent field the same: `CreateDiscovery.audience_hint` defaults to `""`, `service.start_discovery` strips it, the row stores `""`, and the gate's discovery prompt receives `""`. The web now leaves the field out (the screen has no hint field). openapi-typescript marks a field with a server default as required, so `useStartDiscovery` casts its body to `Required<StartDiscovery>` with a comment.
    - **R-M17-24 (CRL-40, the leftovers).** `received_until`'s deadline test sends 40 notifications 20 ms apart and asks for a payload that never comes with a 0.3 s timeout: every read returns one, so the loop ends on the deadline; it returns within 0.5 s while the sender still runs, and the next call gets the rest, nothing lost. The return-race helper records the holding session's `pg_backend_pid()` and polls `count(*) … WHERE :holder = ANY(pg_blocking_pids(pid))`. The `NewRunPage` race test marks the POST answered after the held promise resolves and then waits for `queryClient.isMutating() == 0`.
    - **R-M17-25 (docs).** The README's M16 section and the spec's M16 sentences stay as written; M17 adds its own section and amendments. The brief's "spec §8 (worker, sweep, stalled jobs)" is §7.5 in the spec; the index goes in §8.3.

## Review Focus

1. **A worker finishing a discovery at the deadline boundary: whichever transaction commits first under the row lock decides; a discovery the read or the sweep failed is never brought back, and an answer that commits after the deadline is not kept.** Pinned in Task 1 (`test_a_worker_that_finishes_after_the_read_failed_it_does_not_bring_it_back`, `test_an_answer_whose_commit_finds_the_deadline_passed_is_not_kept`, `test_a_finish_that_commits_first_stands_against_a_read_that_waited`).
2. **The deadline with no worker running: a read past the deadline fails the discovery, the screen shows the server's reason without a reload (also for a deadline longer than 10 minutes), and the job delivered later does nothing.** Pinned in Task 1 (`test_a_read_past_the_deadline_fails_it_with_no_worker_running`, `test_the_job_of_a_discovery_the_read_failed_does_nothing`, `test_a_job_claimed_after_the_deadline_makes_no_model_call`), Task 3 (`test_a_discovery_past_the_configured_deadline_is_failed_by_the_read`, `a discovery the server fails at its deadline shows the server's reason, without a reload (R-M17-1)`) and the live rehearsal (A).
3. **A cancel racing a worker that is alive but slow: its heartbeat is fresh, so the cancel only sets the flag, the job stays `doing`, and the run stops at its next stage boundary with the stage it was in recorded; a worker taken for dead stops at its next write.** Pinned in Task 2 (`test_a_live_slow_worker_keeps_its_run`, `test_a_cancel_racing_a_live_slow_worker_waits_for_it`, `test_a_worker_taken_for_dead_stops_at_its_next_write`).
4. **A stale `?sources=` after sources were removed (or a link from another project): the stale ids are dropped without a word, the rest are selected and sent, and a list of only stale ids selects nothing.** Pinned in Task 6 (`drops ids in the URL that are not the project's, and starts with the rest`, `a URL that names none of the project's sources selects none`).
5. **Migration 0006 on a 0.1.5 database: the index is added to a database with runs, the page query uses it without a sort, and the downgrade removes it.** Pinned in Task 5 (`test_0006_adds_the_run_list_index_to_a_0005_database_and_the_downgrade_drops_it`) and the live rehearsal (D: a real 0.1.5 install upgraded, and a 0.1.5 backup restored).

---

## File structure

| Path | Responsibility |
|---|---|
| `engine/corelata/config.py` | `WorkerConfig.discovery_deadline_s` (Task 1); `BackendConfig` base URL validator (Task 4). |
| `engine/corelata/schema/progress.py` | `DiscoveryView.deadline_at` (Task 1). |
| `engine/corelata/store/discoveries.py` | `expire`, `age_s`, `view(..., deadline_s=)` (Task 1). |
| `engine/corelata/service.py` | `DISCOVERY_DEADLINE_S`, `discovery_deadline_error`, `get_discovery(..., deadline_s=)` (Task 1); `STALLED_AFTER_S`, `cancel_run(..., stalled_after_s=)` (Task 2). |
| `engine/corelata/worker/execute.py` | `execute_discovery`'s deadline (Task 1); `RunEnded`, `DbObserver.locked` (Task 2). |
| `engine/corelata/worker/sweep.py`, `engine/corelata/worker/app.py` | `expire_discoveries` and the minute task (Task 1). |
| `engine/corelata/cli_ops.py` | `status` passes the deadline (Task 1); `cancel` passes the threshold (Task 2). |
| `engine/corelata/store/runs.py`, `engine/corelata/testing/postgres.py` | `close_abandoned_job`; the test helpers `take_job`, `job_status` (Task 2). |
| `engine/corelata.example.yaml`, `deploy/config/corelata.example.yaml` | the new field (Task 1). |
| `schema/discovery-view.schema.json`, `schema/openapi.json`, `web/src/api/schema.d.ts`, `web/src/test/fixtures.ts` | the regenerated schema and the fixture's `deadline_at` (Task 1). |
| `api/corelata_api/routes/runs.py` | cancel passes the threshold (Task 2). |
| `api/corelata_api/routes/discoveries.py`, `web/src/api/discoveries.ts` | the deadline in the API and on the screen (Task 3). |
| `engine/corelata/doctor.py` | `_similar` (Task 4). |
| `engine/corelata/store/migrations/versions/0006_run_list_index.py` (new), `engine/corelata/store/models.py`, `engine/corelata/store/migrate.py` | the run list index (Task 5). |
| `web/src/api/client.ts`, `web/src/api/{runs,projects,reports,packs,system,discoveries}.ts`, `web/src/pages/new/NewRunPage.tsx`, `web/src/pages/new/ValueStatement.tsx`, `web/src/pages/review/ProvenanceTab.tsx`, `web/src/test/render.tsx` | web fixes (Task 6). |
| `engine/testing` tests, `engine/tests/test_return.py` | test leftovers (Task 7). |
| `README.md`, the spec, `docs/operator-guide.md`, `docs/m3-followups.md`, `docs/m4b-followups.md`, `docs/m12-followups.md`, `docs/m14-followups.md`, `docs/m16-followups.md`, `docs/m17-followups.md` (new) | docs (Task 8). |

Order: Task 1 first (the schema change and the fixture), then Task 2 (it edits `service.py` and `execute.py` after Task 1) and Task 3 (it needs `deadline_at`). Tasks 4, 5 and 7 are independent of the others. Task 6 edits `web/src/api/discoveries.ts` after Task 3 and `web/src/test/render.tsx`. Task 8 documents all seven.

---

### Task 1: A discovery has a deadline (CRL-38: config, store, service, worker, sweep, CLI, schema)

**Files:**
- Modify: `engine/corelata/config.py` (`WorkerConfig`), `engine/corelata/schema/progress.py` (`DiscoveryView`), `engine/corelata/store/discoveries.py`, `engine/corelata/service.py` (constants, discovery section), `engine/corelata/worker/execute.py` (imports, `execute_discovery`), `engine/corelata/worker/sweep.py`, `engine/corelata/worker/app.py` (`sweep_orphans_task`), `engine/corelata/cli_ops.py` (`_status`), `engine/corelata.example.yaml`, `deploy/config/corelata.example.yaml`, `web/src/test/fixtures.ts` (`discoveryView`)
- Regenerate: `schema/discovery-view.schema.json`, `schema/openapi.json`, `web/src/api/schema.d.ts` (`make schema`)
- Create: `engine/tests/worker/test_deadline.py`
- Test: `engine/tests/test_config.py`, `engine/tests/store/test_discoveries.py`, `engine/tests/worker/test_sweep.py` (`_backdate`), `engine/tests/worker/test_app.py` (the sweep task test), `engine/tests/test_cli_ops.py`

**Interfaces:**
- Consumes: `tests.worker.conftest.make_services(db, fake_backend, tmp_path, **cfg_overrides)`, `drain(svc)`, the `services`/`fake_backend`/`make_config` fixtures; `discoveries.get(s, id, lock=True)`; `RecordingQueue.pop()`.
- Produces: `WorkerConfig.discovery_deadline_s: float` (600, ≥ 60); `DiscoveryView.deadline_at: datetime`; `discoveries.expire(s, *, deadline_s: float, error: str, discovery_id: uuid.UUID | None = None) -> list[uuid.UUID]`; `discoveries.age_s(s, discovery_id) -> float`; `discoveries.view(s, discovery_id, *, deadline_s: float)`; `service.DISCOVERY_DEADLINE_S: float`; `service.discovery_deadline_error(deadline_s: float) -> str`; `service.get_discovery(db, discovery_id, *, deadline_s: float = DISCOVERY_DEADLINE_S)`; `sweep.expire_discoveries(db, *, deadline_s: float) -> list[uuid.UUID]`; web fixtures `DEADLINE_MS`, `deadlineFor(createdAt: string, ms = DEADLINE_MS): string`.

- [ ] **Step 1: The failing tests**

Create `engine/tests/worker/test_deadline.py`:

```python
"""A discovery has a deadline (CRL-38, R-M17-1): once it is that old and not ended it is failed,
by whoever looks first (the API's read, the worker, its sweep), with or without a worker, and
nothing brings it back."""

import asyncio
import logging
import uuid
from datetime import timedelta

from sqlalchemy import text

from corelata import service
from corelata.schema import DiscoveryState
from corelata.store import discoveries
from corelata.worker import execute
from corelata.worker.execute import run_job
from corelata.worker.sweep import expire_discoveries
from tests.stages.conftest import PORT
from tests.worker.conftest import drain, make_services

TEN_MINUTES = "Discovery did not finish within 10 minutes and was stopped. Start a new discovery."
ONE_MINUTE = "Discovery did not finish within 1 minute and was stopped. Start a new discovery."


async def _queued(svc) -> uuid.UUID:
    pid = await service.create_project(svc.db, f"p-{uuid.uuid4().hex[:6]}")
    ids = await service.add_source(svc.db, svc.storage, pid, "d.txt", "\n\n".join(PORT).encode())
    return await service.start_discovery(svc.db, svc.queue, pid, ids)


_AGED = text("UPDATE discovery SET created_at = now() - make_interval(secs => :s) WHERE id = :id")


async def _age(db, discovery_id: uuid.UUID, seconds: float) -> None:
    """Make the discovery `seconds` old by the database's clock."""
    async with db.session() as s, s.begin():
        await s.execute(_AGED, {"s": seconds, "id": discovery_id})


def test_the_message_renders_the_configured_time():
    assert service.discovery_deadline_error(600) == TEN_MINUTES
    assert service.discovery_deadline_error(60) == ONE_MINUTE
    assert service.discovery_deadline_error(90) == (
        "Discovery did not finish within 90 seconds and was stopped. Start a new discovery."
    )


async def test_a_read_past_the_deadline_fails_it_with_no_worker_running(services):
    did = await _queued(services)  # RecordingQueue: no worker will ever take it
    await _age(services.db, did, 601)
    view = await service.get_discovery(services.db, did)
    assert view.state is DiscoveryState.FAILED and view.error == TEN_MINUTES
    assert view.finished_at is not None and view.candidates == []
    assert view.deadline_at == view.created_at + timedelta(seconds=600)
    again = await service.get_discovery(services.db, did)
    assert again == view  # idempotent: the second read changes nothing


async def test_a_read_before_the_deadline_or_of_an_ended_discovery_changes_nothing(services):
    young = await _queued(services)
    await _age(services.db, young, 590)
    assert (await service.get_discovery(services.db, young)).state is DiscoveryState.CREATED
    done = await _queued(services)
    await drain(services)
    await _age(services.db, done, 3600)
    [young_after, done_after] = [await service.get_discovery(services.db, d) for d in (young, done)]
    assert young_after.state is DiscoveryState.COMPLETED  # drain ran it too
    assert done_after.state is DiscoveryState.COMPLETED and done_after.error is None


async def test_a_job_claimed_after_the_deadline_makes_no_model_call(services, fake_backend):
    did = await _queued(services)
    await _age(services.db, did, 601)  # nobody read it: the worker is the first to look
    await drain(services)
    assert fake_backend.requests == []
    view = await service.get_discovery(services.db, did)
    assert view.state is DiscoveryState.FAILED and view.error == TEN_MINUTES


async def test_the_job_of_a_discovery_the_read_failed_does_nothing(services, fake_backend):
    did = await _queued(services)
    await _age(services.db, did, 601)
    failed = await service.get_discovery(services.db, did)
    await drain(services)  # the queued job is delivered later
    assert fake_backend.requests == []
    assert await service.get_discovery(services.db, did) == failed


async def test_the_work_stops_at_the_deadline(db, fake_backend, tmp_path, monkeypatch, caplog):
    svc = make_services(db, fake_backend, tmp_path, worker={"discovery_deadline_s": 60})
    did = await _queued(svc)
    await _age(svc.db, did, 59.7)  # 0.3 s left

    async def hangs(*args, **kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(execute, "discover", hangs)
    job = svc.queue.pop()
    await asyncio.wait_for(run_job(svc, job.task, job.kwargs), timeout=10)
    view = await service.get_discovery(svc.db, did, deadline_s=60)
    assert view.state is DiscoveryState.FAILED and view.error == ONE_MINUTE
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]  # not an internal error


async def test_a_worker_that_finishes_after_the_read_failed_it_does_not_bring_it_back(
    services, monkeypatch, caplog
):
    did = await _queued(services)
    real = execute.discover

    async def read_fails_it_meanwhile(*args, **kwargs):
        result = await real(*args, **kwargs)
        await _age(services.db, did, 601)
        assert (await service.get_discovery(services.db, did)).state is DiscoveryState.FAILED
        return result  # the worker answers just after the deadline

    monkeypatch.setattr(execute, "discover", read_fails_it_meanwhile)
    await drain(services)
    view = await service.get_discovery(services.db, did)
    assert view.state is DiscoveryState.FAILED and view.error == TEN_MINUTES
    assert view.candidates == []
    assert "ended while it ran" in caplog.text
    async with services.db.session() as s:
        assert len((await discoveries.get(s, did)).llm_calls) == 1  # its model call is on record


async def test_an_answer_whose_commit_finds_the_deadline_passed_is_not_kept(services, monkeypatch):
    did = await _queued(services)
    real = execute.discover

    async def late(*args, **kwargs):
        result = await real(*args, **kwargs)
        await _age(services.db, did, 601)  # nobody read it: the worker's own finish decides
        return result

    monkeypatch.setattr(execute, "discover", late)
    await drain(services)
    view = await service.get_discovery(services.db, did)
    assert view.state is DiscoveryState.FAILED and view.error == TEN_MINUTES
    assert view.candidates == []


_BLOCKED_BY = text("SELECT count(*) FROM pg_stat_activity WHERE :pid = ANY(pg_blocking_pids(pid))")


async def _until_blocked_by(db, pid: int) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 10
    while True:
        async with db.session() as s:
            if await s.scalar(_BLOCKED_BY, {"pid": pid}):
                return
        assert loop.time() < deadline, "no session waited for the discovery's row lock"
        await asyncio.sleep(0.02)


async def test_a_finish_that_commits_first_stands_against_a_read_that_waited(services, monkeypatch):
    """The boundary under the row lock: the worker decided "in time" and holds the lock; a read
    that would fail it waits, then finds it completed."""
    did = await _queued(services)
    reached, release, holder = asyncio.Event(), asyncio.Event(), []
    real = discoveries.set_candidates

    async def held(s, discovery_id, result):
        holder.append(await s.scalar(text("SELECT pg_backend_pid()")))
        reached.set()
        await release.wait()
        await real(s, discovery_id, result)

    monkeypatch.setattr(discoveries, "set_candidates", held)
    worker = asyncio.create_task(drain(services))
    await reached.wait()
    # a read with a deadline already passed (as a read a moment later would find it)
    read = asyncio.create_task(service.get_discovery(services.db, did, deadline_s=0.001))
    await _until_blocked_by(services.db, holder[0])
    release.set()
    await worker
    view = await read
    assert view.state is DiscoveryState.COMPLETED and view.error is None


async def test_the_sweep_fails_unread_discoveries_past_the_deadline(services, caplog):
    old, young = await _queued(services), await _queued(services)
    done = await _queued(services)
    await drain(services)  # all three completed
    async with services.db.session() as s, s.begin():
        await s.execute(
            text("UPDATE discovery SET state = 'running' WHERE id IN (:a, :b)"),
            {"a": old, "b": young},
        )
    await _age(services.db, old, 601)
    await _age(services.db, young, 30)
    await _age(services.db, done, 3600)
    assert await expire_discoveries(services.db, deadline_s=600) == [old]
    assert await expire_discoveries(services.db, deadline_s=600) == []  # idempotent
    assert f"discovery {old} passed its deadline; marked failed" in caplog.text
    states = {d: (await service.get_discovery(services.db, d)).state for d in (old, young, done)}
    assert states == {
        old: DiscoveryState.FAILED,
        young: DiscoveryState.RUNNING,
        done: DiscoveryState.COMPLETED,
    }
```

In `engine/tests/test_config.py`, after `test_job_retention_days_defaults_to_30_and_must_be_positive`, add:

```python
def test_discovery_deadline_defaults_to_ten_minutes_and_is_at_least_one():
    from corelata.config import WorkerConfig

    assert WorkerConfig().discovery_deadline_s == 600
    assert WorkerConfig(discovery_deadline_s=60).discovery_deadline_s == 60
    with pytest.raises(ValidationError, match="greater than or equal to 60"):
        WorkerConfig(discovery_deadline_s=59.9)
```

In `engine/tests/store/test_discoveries.py`: add `from datetime import timedelta` after `import uuid`; in `test_create_get_and_view` replace `view = await discoveries.view(s, row.id)` with `view = await discoveries.view(s, row.id, deadline_s=90)`, add after the `created_at.tzinfo` assertion

```python
    assert view.deadline_at == view.created_at + timedelta(seconds=90)
```

and replace `await discoveries.view(s, uuid.uuid4())` with `await discoveries.view(s, uuid.uuid4(), deadline_s=90)`; in `test_candidates_replace_earlier_ones` replace `view = await discoveries.view(s, row.id)` with `view = await discoveries.view(s, row.id, deadline_s=600)`.

In `engine/tests/worker/test_sweep.py`, `_backdate`, replace the statement line with:

```python
            # past the grace period, inside a discovery's 10-minute deadline (R-M17-13)
            text(f"UPDATE {table} SET created_at = now() - interval '5 minutes' WHERE id = :id"),
```

In `engine/tests/worker/test_app.py` replace `test_sweep_orphans_task_uses_the_grace_period` with:

```python
async def test_sweep_orphans_task_uses_the_grace_period_and_the_discovery_deadline(
    db, fake_backend, tmp_path, monkeypatch
):
    services = make_services(db, fake_backend, tmp_path, worker={"discovery_deadline_s": 90})
    seen = {}

    async def fake_sweep(database, *, grace_s):
        seen["sweep"] = (database, grace_s)
        return [], []

    async def fake_expire(database, *, deadline_s):
        seen["expire"] = (database, deadline_s)
        return []

    monkeypatch.setattr(worker_app, "sweep_orphans", fake_sweep)
    monkeypatch.setattr(worker_app, "expire_discoveries", fake_expire)
    context = SimpleNamespace(additional_context={worker_app.SERVICES_KEY: services})
    await worker_app.sweep_orphans_task(context, timestamp=0)
    assert seen == {
        "sweep": (services.db, worker_app.ORPHAN_GRACE_S),
        "expire": (services.db, 90),
    }
```

In `engine/tests/test_cli_ops.py`, after `test_discover_through_the_queue`, add:

```python
def test_status_fails_a_discovery_past_the_configured_deadline(setup, capsys, pg_url):
    config, doc = setup
    data = yaml.safe_load(config.read_text(encoding="utf-8"))
    data["worker"]["discovery_deadline_s"] = 60
    config.write_text(yaml.safe_dump(data), encoding="utf-8")
    args = ["--config", str(config)]
    out = _cli(capsys, "discover", str(doc), "--project", "p", *args)[1]
    did = re.search(r"discovery (\S+) queued", out).group(1)
    with psycopg.connect(pg_url) as conn:  # no worker runs; a minute passes
        conn.execute(
            "UPDATE discovery SET created_at = now() - interval '61 seconds' WHERE id = %s", (did,)
        )
    code, out, _ = _cli(capsys, "status", did, *args)
    assert code == 0 and out.startswith(f"discovery {did}: failed")
    assert (
        "error: Discovery did not finish within 1 minute and was stopped. Start a new discovery."
        in out
    )
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/worker/test_deadline.py tests/test_config.py tests/store/test_discoveries.py tests/worker/test_app.py --no-cov -q`
Expected: collection errors or failures: `ImportError: cannot import name 'expire_discoveries'`, `AttributeError: module 'corelata.service' has no attribute 'discovery_deadline_error'`, `ValidationError` for `discovery_deadline_s` (extra field), `TypeError: view() got an unexpected keyword argument 'deadline_s'`.

- [ ] **Step 3: The field, the view and the store**

In `engine/corelata/config.py`, `WorkerConfig`, after `job_retention_days`:

```python
    # a discovery not ended this long after it was created is failed, by the API's read, the
    # worker or its sweep, whichever comes first (CRL-38, R-M17-1)
    discovery_deadline_s: float = Field(600.0, ge=60)
```

In `engine/corelata/schema/progress.py`, `DiscoveryView`, after `created_at: datetime`:

```python
    deadline_at: datetime = Field(
        description=(
            "When the discovery is failed if it has not ended: `created_at` plus "
            "`worker.discovery_deadline_s` (CRL-38)."
        )
    )
```

In `engine/corelata/store/discoveries.py`: the imports become

```python
import uuid
from datetime import timedelta

from sqlalchemy import delete, select, text
```

insert before `async def source_ids(`:

```python
# A discovery not ended `deadline_s` after it was created, by the database's clock, is failed
# (CRL-38, R-M17-1). One conditional statement: idempotent, and the row lock it takes serialises
# it with the worker's claim and finish, so whichever commits first decides.
_EXPIRE = (
    "UPDATE discovery SET state = 'failed', error = :error, finished_at = now() "
    "WHERE state IN ('created', 'running') "
    "AND created_at <= now() - make_interval(secs => :deadline_s)"
)
_EXPIRE_ALL = text(_EXPIRE + " RETURNING id")
_EXPIRE_ONE = text(_EXPIRE + " AND id = :id RETURNING id")
_AGE = text("SELECT extract(epoch FROM now() - created_at) FROM discovery WHERE id = :id")


async def expire(
    s: AsyncSession, *, deadline_s: float, error: str, discovery_id: uuid.UUID | None = None
) -> list[uuid.UUID]:
    """Fail every discovery past its deadline (only `discovery_id`, when given) with `error`;
    returns the ids it failed. An ended discovery is never touched."""
    params: dict[str, object] = {"deadline_s": deadline_s, "error": error}
    if discovery_id is None:
        return list(await s.scalars(_EXPIRE_ALL, params))
    return list(await s.scalars(_EXPIRE_ONE, {**params, "id": discovery_id}))


async def age_s(s: AsyncSession, discovery_id: uuid.UUID) -> float:
    """Seconds since the discovery was created, by the database's clock."""
    return float(await s.scalar(_AGE, {"id": discovery_id}))
```

and in `view`: the signature becomes `async def view(s: AsyncSession, discovery_id: uuid.UUID, *, deadline_s: float) -> DiscoveryView:` and, after `created_at=row.created_at,`, add `deadline_at=row.created_at + timedelta(seconds=deadline_s),`.

- [ ] **Step 4: The service**

In `engine/corelata/service.py`: the config import becomes `from corelata.config import CorelataConfig, WorkerConfig, config_hash`; after `_MAX_FILENAME = 255` add

```python
# The configuration's defaults, for callers without one (tests); the API and the CLI pass theirs.
DISCOVERY_DEADLINE_S = WorkerConfig().discovery_deadline_s
```

and replace `get_discovery` with:

```python
def _duration(seconds: float) -> str:
    if seconds % 60 == 0:
        minutes = int(seconds // 60)
        return f"{minutes} minute{'' if minutes == 1 else 's'}"
    return f"{seconds:g} seconds"


def discovery_deadline_error(deadline_s: float) -> str:
    """What a discovery past its deadline records as its error; the New run screen shows it."""
    return (
        f"Discovery did not finish within {_duration(deadline_s)} and was stopped. "
        "Start a new discovery."
    )


async def get_discovery(
    db: Database, discovery_id: uuid.UUID, *, deadline_s: float = DISCOVERY_DEADLINE_S
) -> DiscoveryView:
    """The discovery as stored, after failing it if it is past its deadline (`created_at` +
    `deadline_s` on the database's clock) and not ended (R-M17-1): the deadline holds whenever
    anyone reads, with or without a worker. Callers with a configuration pass
    `worker.discovery_deadline_s`."""
    async with db.session() as s:
        async with s.begin():
            await discoveries.expire(
                s,
                deadline_s=deadline_s,
                error=discovery_deadline_error(deadline_s),
                discovery_id=discovery_id,
            )
        return await discoveries.view(s, discovery_id, deadline_s=deadline_s)
```

- [ ] **Step 5: The worker, its sweep and the CLI**

In `engine/corelata/worker/execute.py`: add `import asyncio` before `import contextlib`; the service import becomes

```python
from corelata.service import (
    TASK_DISCOVER,
    TASK_RUN,
    JobQueue,
    discovery_deadline_error,
    reruns_ended,
)
```

and replace `execute_discovery` with:

```python
_ENDED = (DiscoveryState.COMPLETED, DiscoveryState.FAILED)


async def execute_discovery(svc: WorkerServices, discovery_id: uuid.UUID) -> None:
    """One discovery job (spec §7.1). Finished discoveries are left alone; one a dead worker
    left `running` is done again. A discovery has `worker.discovery_deadline_s` from its creation
    (R-M17-1): claimed after that, it is failed without a model call; the work is stopped when the
    time is up; and an answer whose transaction finds the deadline passed, or the discovery
    already failed by the API's read or the sweep, records the deadline's failure, never a result.
    Every decision is taken under the discovery's row lock on the database's clock."""
    deadline_s = svc.cfg.worker.discovery_deadline_s
    too_late = discovery_deadline_error(deadline_s)
    async with svc.db.session() as s, s.begin():
        row = await discoveries.get(s, discovery_id, lock=True)
        state = DiscoveryState(row.state)
        if state in _ENDED:
            return
        left = deadline_s - await discoveries.age_s(s, discovery_id)
        if left <= 0:
            row.state, row.error, row.finished_at = DiscoveryState.FAILED.value, too_late, utcnow()
            log.warning("discovery %s was past its deadline when claimed; failed", discovery_id)
            return
        if state is DiscoveryState.RUNNING:
            log.warning(
                "discovery %s restarted: its earlier execution did not finish", discovery_id
            )
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
    budget = asyncio.timeout(left)  # the work stops at the deadline
    try:
        async with budget:
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
        if not budget.expired():  # the deadline's TimeoutError is recorded below
            log.exception("discovery %s failed", discovery_id)
        error = _internal(e)
    async with svc.db.session() as s, s.begin():
        row = await discoveries.get(s, discovery_id, lock=True)
        row.llm_calls = [r.model_dump(mode="json") for r in calls.records]
        row.token_usage = calls.usage().model_dump()
        if DiscoveryState(row.state) in _ENDED:
            # failed at its deadline by the API's read or the sweep while this worked: it stays so
            log.warning("discovery %s ended while it ran; its result is not kept", discovery_id)
            return
        row.finished_at = utcnow()
        if budget.expired() or await discoveries.age_s(s, discovery_id) >= deadline_s:
            row.state, row.error = DiscoveryState.FAILED.value, too_late
        elif result is not None:
            await discoveries.set_candidates(s, discovery_id, result)
            row.state = DiscoveryState.COMPLETED.value
        else:
            row.state, row.error = DiscoveryState.FAILED.value, error
```

In `engine/corelata/worker/sweep.py`: the imports become `from corelata.service import discovery_deadline_error, reruns_ended` and `from corelata.store import discoveries, runs`; insert after `sweep_orphans` (before the `# The operator guide's housekeeping statement` comment):

```python
async def expire_discoveries(db: Database, *, deadline_s: float) -> list[uuid.UUID]:
    """Fail every discovery past its deadline that nobody has read since (R-M17-1); returns the
    ids it failed. The API's read does the same for the one it reads."""
    async with db.session() as s, s.begin():
        expired = await discoveries.expire(
            s, deadline_s=deadline_s, error=discovery_deadline_error(deadline_s)
        )
    for discovery_id in expired:
        log.warning(
            "discovery %s passed its deadline; marked failed",
            discovery_id,
            extra={"discovery_id": str(discovery_id)},
        )
    return expired
```

In `engine/corelata/worker/app.py`: the sweep import becomes

```python
from corelata.worker.sweep import (
    ORPHAN_GRACE_S,
    expire_discoveries,
    purge_closed_jobs,
    sweep_orphans,
)
```

and `sweep_orphans_task`'s body becomes:

```python
    svc = _services(context)
    await sweep_orphans(svc.db, grace_s=ORPHAN_GRACE_S)
    await expire_discoveries(svc.db, deadline_s=svc.cfg.worker.discovery_deadline_s)
```

In `engine/corelata/cli_ops.py`, `_status`, replace `return await service.get_discovery(db, some_id)` with:

```python
                return await service.get_discovery(
                    db, some_id, deadline_s=cfg.worker.discovery_deadline_s
                )
```

In `engine/corelata.example.yaml` replace the `worker:` line with:

```yaml
worker: { concurrency: 2, stalled_after_s: 900, job_retention_days: 30, discovery_deadline_s: 600 } # runs at once; requeue after this silence; days failed/cancelled jobs are kept; seconds before an unfinished discovery is failed
```

and in `deploy/config/corelata.example.yaml`:

```yaml
worker: { concurrency: 2, stalled_after_s: 900, job_retention_days: 30, discovery_deadline_s: 600 } # days failed/cancelled jobs are kept; seconds before an unfinished discovery is failed
```

- [ ] **Step 6: Regenerate the schema; the web fixture**

Run: `make schema && git status --short schema web/src/api/schema.d.ts`
Expected: ` M schema/discovery-view.schema.json`, ` M schema/openapi.json`, ` M web/src/api/schema.d.ts` (each gains `deadline_at`, required, `format: date-time`, with the description).

In `web/src/test/fixtures.ts` replace `discoveryView` with:

```ts
/** The server's default deadline, `worker.discovery_deadline_s` (R-M17-1). */
export const DEADLINE_MS = 10 * 60_000;

/** `created_at` plus `ms`, as the server computes `deadline_at`. */
export function deadlineFor(createdAt: string, ms = DEADLINE_MS): string {
  return new Date(Date.parse(createdAt) + ms).toISOString();
}

export function discoveryView(overrides: Partial<DiscoveryView> = {}): DiscoveryView {
  // just created, by the clock the page reads its age with (no `Date` header in tests): a
  // fixed past date would be past the 10-minute ceiling (R-M16-2)
  const createdAt = overrides.created_at ?? new Date().toISOString();
  return {
    discovery_id: DISCOVERY_ID,
    project_id: project.id,
    state: "created",
    audience_hint: "",
    source_ids: [source.id],
    candidates: [],
    usage: null,
    error: null,
    created_at: createdAt,
    deadline_at: deadlineFor(createdAt),
    started_at: null,
    finished_at: null,
    ...overrides,
  };
}
```

- [ ] **Step 7: Run the tests**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/worker tests/store tests/test_config.py tests/test_cli_ops.py tests/test_service.py tests/schema --no-cov -q && uv run ruff check . && uv run ruff format --check .`
Expected: all pass (against today's `execute.py`, the four worker tests `test_a_job_claimed_after_the_deadline_makes_no_model_call`, `test_the_work_stops_at_the_deadline`, `test_a_worker_that_finishes_after_the_read_failed_it_does_not_bring_it_back` and `test_an_answer_whose_commit_finds_the_deadline_passed_is_not_kept` fail: checked on the scratch copy).

Run: `cd web && pnpm lint && pnpm vitest run src/api src/pages/new`
Expected: clean; all pass (the screen does not read `deadline_at` until Task 3).

- [ ] **Step 8: Commit**

```bash
cat > "$SCRATCH/m17-task1-commit.txt" <<'EOF'
feat: a discovery has a deadline, enforced by the read, the worker and its sweep (CRL-38)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git add engine/corelata/config.py engine/corelata/schema/progress.py engine/corelata/store/discoveries.py engine/corelata/service.py engine/corelata/worker/execute.py engine/corelata/worker/sweep.py engine/corelata/worker/app.py engine/corelata/cli_ops.py engine/corelata.example.yaml deploy/config/corelata.example.yaml engine/tests/worker/test_deadline.py engine/tests/test_config.py engine/tests/store/test_discoveries.py engine/tests/worker/test_sweep.py engine/tests/worker/test_app.py engine/tests/test_cli_ops.py schema/discovery-view.schema.json schema/openapi.json web/src/api/schema.d.ts web/src/test/fixtures.ts
git commit -F "$SCRATCH/m17-task1-commit.txt"
```

(`$SCRATCH` is the session's scratchpad directory.)

---

### Task 2: Cancelling a run whose worker is gone ends it at once (CRL-38: service, store, worker fence, CLI, API)

**Files:**
- Modify: `engine/corelata/store/runs.py` (after `cancel_flag`), `engine/corelata/service.py` (constants, `cancel_run`), `engine/corelata/worker/execute.py` (imports, `RunEnded`, `DbObserver`, `execute_run`), `engine/corelata/cli_ops.py` (`_cancel`), `engine/corelata/testing/postgres.py` (after `truncate_all`), `api/corelata_api/routes/runs.py` (`cancel_run`'s body only, not its docstring)
- Create: `engine/tests/worker/test_orphan_cancel.py`
- Test: `engine/tests/worker/test_rerun_end.py`, `engine/tests/test_cli_ops.py`, `api/tests/test_runs.py`

**Interfaces:**
- Consumes: Task 1's `service.py` (constants block); `execute._begin(svc, run_id)`; `tests.worker.conftest.submit`, `drain`, `make_services`, `tasks_sent`; `tests.worker.test_rerun_end._returned`, `_review`; the `run_channel` fixture (`received`, `received_until`); `api/tests/conftest.py`'s `make_api(**overrides)`, `start_run`, `set_run_state`.
- Produces: `runs.close_abandoned_job(s, run_id, *, stalled_after_s: float) -> bool`; `service.STALLED_AFTER_S: float`; `service.cancel_run(db, run_id, *, stalled_after_s: float = STALLED_AFTER_S) -> RunState`; `execute.RunEnded(Exception)`; `DbObserver.locked(s: AsyncSession) -> Run`; test helpers `corelata.testing.postgres.take_job(db, run_id, *, silent_s: float | None) -> int` and `job_status(db, job_id) -> str`.

- [ ] **Step 1: The test helpers**

In `engine/corelata/testing/postgres.py`, after `truncate_all`:

```python
_WORKER = text(
    "INSERT INTO procrastinate_workers (last_heartbeat) "
    "VALUES (now() - make_interval(secs => :silent_s)) RETURNING id"
)
_TAKEN_JOB = text(
    "INSERT INTO procrastinate_jobs (queue_name, task_name, lock, queueing_lock, args, status, "
    "worker_id) VALUES ('corelata', 'corelata.run', :lock, :lock, CAST(:args AS jsonb), "
    "'doing', :worker_id) RETURNING id"
)
_JOB_STATUS = text("SELECT status::text FROM procrastinate_jobs WHERE id = :id")


async def take_job(db: Database, run_id: uuid.UUID, *, silent_s: float | None) -> int:
    """Make the run's job one a worker has taken ('doing'), as procrastinate leaves it: the
    worker last sent a heartbeat `silent_s` ago, or (None) its row is gone. Returns the job id
    (R-M17-2 tests)."""
    async with db.session() as s, s.begin():
        worker_id = None
        if silent_s is not None:
            worker_id = await s.scalar(_WORKER, {"silent_s": silent_s})
        return await s.scalar(
            _TAKEN_JOB,
            {
                "lock": f"run:{run_id}",
                "args": f'{{"run_id": "{run_id}"}}',
                "worker_id": worker_id,
            },
        )


async def job_status(db: Database, job_id: int) -> str:
    async with db.session() as s:
        return await s.scalar(_JOB_STATUS, {"id": job_id})
```

- [ ] **Step 2: The failing tests**

Create `engine/tests/worker/test_orphan_cancel.py`:

```python
"""Cancelling a run whose worker is gone ends it at once (CRL-38, R-M17-2). "Gone" is what the
stalled-job requeue already means: the job is 'doing' and its worker's heartbeat is
`worker.stalled_after_s` old, or its worker row was deleted. A live worker, however slow, keeps
its run and stops at its next stage boundary, as before."""

import pytest

from corelata import service
from corelata.llm.payload import parse_input
from corelata.schema import RunState
from corelata.testing.fake_backend import FakeBackend
from corelata.testing.postgres import job_status, take_job
from corelata.worker import execute
from corelata.worker.execute import run_job
from tests.worker.conftest import drain, make_services, submit, tasks_sent

STALLED = service.STALLED_AFTER_S  # 900 s, the configuration's default


async def _claimed(svc):
    """A run a worker claimed (state ingesting, attempts 1); the queue holds no copy of it."""
    run_id = await submit(svc)
    svc.queue.jobs.clear()
    assert await execute._begin(svc, run_id) is not None
    return run_id


@pytest.mark.parametrize("silent_s", [STALLED + 1, None], ids=["stale heartbeat", "no worker row"])
async def test_a_run_whose_worker_is_gone_is_cancelled_at_once(services, run_channel, silent_s):
    run_id = await _claimed(services)
    job = await take_job(services.db, run_id, silent_s=silent_s)
    await run_channel.received_until(str(run_id))  # the claim's announcement
    assert await service.cancel_run(services.db, run_id) is RunState.CANCELLED
    progress = await service.run_progress(services.db, run_id)
    assert progress.state is RunState.CANCELLED and progress.cancel_requested
    assert progress.finished_at is not None and progress.error is None
    assert await job_status(services.db, job) == "aborted"  # it can never be re-queued
    assert await run_channel.received(1) == [str(run_id)]


async def test_a_live_slow_worker_keeps_its_run(services):
    run_id = await _claimed(services)
    # in the middle of a long model call: its heartbeat is still inside the threshold
    job = await take_job(services.db, run_id, silent_s=STALLED - 5)
    assert await service.cancel_run(services.db, run_id) is RunState.INGESTING
    progress = await service.run_progress(services.db, run_id)
    assert progress.cancel_requested and progress.finished_at is None
    assert await job_status(services.db, job) == "doing"


async def test_the_threshold_is_the_one_passed(services):
    run_id = await _claimed(services)
    job = await take_job(services.db, run_id, silent_s=31)
    assert await service.cancel_run(services.db, run_id) is RunState.INGESTING  # 900 s default
    assert await job_status(services.db, job) == "doing"
    assert await service.cancel_run(services.db, run_id, stalled_after_s=30) is RunState.CANCELLED
    assert await job_status(services.db, job) == "aborted"


async def test_a_run_whose_job_waits_for_a_worker_keeps_todays_behaviour(services):
    """A job back in the queue (re-queued, or a retry scheduled) is not held by a dead worker:
    the next worker to take it ends the run at its claim, as before M17."""
    run_id = await _claimed(services)
    assert await service.cancel_run(services.db, run_id) is RunState.INGESTING
    progress = await service.run_progress(services.db, run_id)
    assert progress.cancel_requested and progress.finished_at is None


async def test_a_redelivered_job_of_a_cancelled_run_does_nothing(services, fake_backend):
    run_id = await _claimed(services)
    await take_job(services.db, run_id, silent_s=None)
    await service.cancel_run(services.db, run_id)
    await run_job(services, service.TASK_RUN, {"run_id": str(run_id)})
    assert fake_backend.requests == []
    progress = await service.run_progress(services.db, run_id)
    assert progress.state is RunState.CANCELLED and progress.attempts == 1


class _TakenForDead(FakeBackend):
    """While the writer is called, the worker's heartbeat goes stale (taken for dead) and the run
    is cancelled; the worker itself goes on."""

    def __init__(self, *, silent_s: float | None) -> None:
        super().__init__(name="fake")
        self.db = None
        self.run_id = None
        self.silent_s = silent_s
        self.cancelled_to: RunState | None = None

    async def chat(self, request):
        payload = parse_input([m.model_dump() for m in request.messages])
        if payload["task"] == "writer" and self.cancelled_to is None:
            await take_job(self.db, self.run_id, silent_s=self.silent_s)
            self.cancelled_to = await service.cancel_run(self.db, self.run_id)
        return await super().chat(request)


async def test_a_worker_taken_for_dead_stops_at_its_next_write(db, tmp_path, caplog):
    spy = _TakenForDead(silent_s=None)
    svc = make_services(db, spy, tmp_path)
    run_id = await submit(svc)
    spy.db, spy.run_id = db, run_id
    await drain(svc)
    assert spy.cancelled_to is RunState.CANCELLED
    assert tasks_sent(spy) == ["gate", "writer"]  # nothing after the stage it was in
    progress = await service.run_progress(db, run_id)
    assert progress.state is RunState.CANCELLED and progress.error is None
    assert [s.stage for s in progress.stages] == ["ingesting", "gating"]  # no drafting row
    record = await service.get_run_record(db, run_id)
    assert record.report is None and record.drafts == [] and len(record.llm_calls) == 1
    assert f"run {run_id} ended while this worker ran it" in caplog.text


async def test_a_cancel_racing_a_live_slow_worker_waits_for_it(db, tmp_path):
    """The same cancel while the worker answers its heartbeat: the run stops at the next stage
    boundary, with the writer's draft recorded."""
    spy = _TakenForDead(silent_s=0)
    svc = make_services(db, spy, tmp_path)
    run_id = await submit(svc)
    spy.db, spy.run_id = db, run_id
    await drain(svc)
    assert spy.cancelled_to is RunState.DRAFTING  # only the flag
    progress = await service.run_progress(db, run_id)
    assert progress.state is RunState.CANCELLED and progress.cancel_requested
    assert [s.stage for s in progress.stages] == ["ingesting", "gating", "drafting"]
```

In `engine/tests/worker/test_rerun_end.py`: add `from corelata.testing.postgres import take_job` after `from corelata.store import runs`, and before `test_a_rerun_the_sweep_fails_frees_the_parent` add:

```python
async def test_cancelling_a_rerun_whose_worker_is_gone_frees_the_parent(services, run_channel):
    parent, child = await _returned(services)
    assert await execute._begin(services, child) is not None  # a worker claimed the rerun
    await take_job(services.db, child, silent_s=None)  # and died
    await run_channel.received_until(str(child))
    assert await service.cancel_run(services.db, child) is RunState.CANCELLED  # at once (R-M17-2)
    review = await _review(services, parent)
    assert review.child_state is RunState.CANCELLED  # the same ending path (R-M15-2)
    assert sorted(await run_channel.received(2)) == sorted([str(child), str(parent)])
```

In `engine/tests/test_cli_ops.py`, before `test_review_accept_and_return`, add:

```python
def test_cancel_a_run_whose_worker_is_gone_uses_the_configured_threshold(setup, capsys, pg_url):
    config, doc = setup  # worker.stalled_after_s: 60
    args = ["--config", str(config)]
    run_id = _run_id(
        _cli(capsys, "run", str(doc), "--project", "p", "--statement", STATEMENT, *args)[1]
    )
    with psycopg.connect(pg_url) as conn:  # a worker took it, then went silent 61 s ago
        conn.execute("UPDATE run SET state = 'drafting', attempts = 1 WHERE id = %s", (run_id,))
        conn.execute("DELETE FROM procrastinate_jobs")
        worker = conn.execute(
            "INSERT INTO procrastinate_workers (last_heartbeat) "
            "VALUES (now() - interval '61 seconds') RETURNING id"
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO procrastinate_jobs (queue_name, task_name, lock, args, status, "
            "worker_id) VALUES ('corelata', 'corelata.run', %s, %s, 'doing', %s)",
            (f"run:{run_id}", json.dumps({"run_id": run_id}), worker),
        )
    code, out, _ = _cli(capsys, "cancel", run_id, *args)
    assert code == 0 and out.strip() == f"run {run_id} cancelled"
```

In `api/tests/test_runs.py`: add `from corelata.testing.postgres import job_status, take_job` after `from corelata.store.models import ReviewEvent`, and before `test_review_needs_a_completed_run` add:

```python
async def test_cancel_a_run_whose_worker_is_gone_uses_the_configured_threshold(make_api):
    async with make_api(worker={"stalled_after_s": 30}) as api:
        run = await start_run(api)
        await set_run_state(api.db, run["run_id"], "drafting")
        job = await take_job(api.db, uuid.UUID(run["run_id"]), silent_s=31)
        response = await api.client.post(f"/api/runs/{run['run_id']}/cancel")
        assert response.status_code == 200
        assert response.json()["state"] == "cancelled" and response.json()["finished_at"]
        assert await job_status(api.db, job) == "aborted"
```

- [ ] **Step 3: Run them to see them fail**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/worker/test_orphan_cancel.py tests/worker/test_rerun_end.py --no-cov -q`
Expected: `AttributeError: module 'corelata.service' has no attribute 'STALLED_AFTER_S'` at collection. With only the constant added (Step 4's first line), 5 failures: both `test_a_run_whose_worker_is_gone_is_cancelled_at_once` cases, `test_the_threshold_is_the_one_passed`, `test_a_worker_taken_for_dead_stops_at_its_next_write` and `test_cancelling_a_rerun_whose_worker_is_gone_frees_the_parent`; the others pin behaviour that stays (seen on the scratch copy).

- [ ] **Step 4: The store and the service**

In `engine/corelata/service.py`, after `DISCOVERY_DEADLINE_S = …` (Task 1):

```python
STALLED_AFTER_S = WorkerConfig().stalled_after_s
```

In `engine/corelata/store/runs.py`, after `cancel_flag`:

```python
# The run's job that a worker took ('doing') and whose worker is gone: its row deleted
# (worker_id NULL) or its heartbeat older than `stalled_after_s`. That is procrastinate's own
# stalled-job test, the one the requeue uses (R-M17-2). A run has at most one 'doing' job: every
# job carries the lock run:<id>, and procrastinate never starts a job whose lock a 'doing' job
# holds. FOR UPDATE OF j: the requeue cannot move the job while this transaction closes it.
_ABANDONED_JOB = text(
    "SELECT j.id FROM procrastinate_jobs j "
    "LEFT JOIN procrastinate_workers w ON w.id = j.worker_id "
    "WHERE j.args->>'run_id' = :run_id AND j.status = 'doing' "
    "AND (w.id IS NULL OR w.last_heartbeat < now() - make_interval(secs => :stalled_after_s)) "
    "FOR UPDATE OF j"
)
_ABORT_JOB = text(
    "SELECT procrastinate_finish_job_v1(:job_id, CAST('aborted' AS procrastinate_job_status), "
    "false)"
)


async def close_abandoned_job(
    s: AsyncSession, run_id: uuid.UUID, *, stalled_after_s: float
) -> bool:
    """Close the run's job as `aborted` if the worker that took it is gone; True if it was.
    Call it with the run's row lock held."""
    job_id = await s.scalar(
        _ABANDONED_JOB, {"run_id": str(run_id), "stalled_after_s": stalled_after_s}
    )
    if job_id is None:
        return False
    await s.execute(_ABORT_JOB, {"job_id": job_id})
    return True
```

In `engine/corelata/service.py` replace `cancel_run` with:

```python
async def cancel_run(
    db: Database, run_id: uuid.UUID, *, stalled_after_s: float = STALLED_AFTER_S
) -> RunState:
    """Ask a run to stop. A run nothing is executing yet ends at once. So does a run whose job
    was taken by a worker that is gone, its heartbeat `stalled_after_s` old or its worker row
    deleted (R-M17-2): the job is closed as aborted in the same transaction, so it never runs
    again, and should that worker still be alive it stops at its next write (`RunEnded` in the
    worker). A run a live worker holds stops at its next stage boundary (the pipeline polls the
    flag). Returns the state after the call. Callers with a configuration pass
    `worker.stalled_after_s`."""
    async with db.session() as s, s.begin():
        run = await runs.get_run(s, run_id, lock=True)
        state = RunState(run.state)
        if state in TERMINAL_STATES:
            raise InvalidRunStateError(f"run {run_id} is already {state.value}")
        run.cancel_requested = True
        ends_now = state is RunState.CREATED or await runs.close_abandoned_job(
            s, run_id, stalled_after_s=stalled_after_s
        )
        if ends_now:
            run.state = RunState.CANCELLED.value
            run.finished_at = utcnow()
        await runs.notify_run(s, run_id)  # the flag shows on the progress page at once
        if ends_now:
            await reruns_ended(s, [run_id])
        return RunState(run.state)
```

- [ ] **Step 5: The fence in the worker**

In `engine/corelata/worker/execute.py`: add `from sqlalchemy.ext.asyncio import AsyncSession` after the `sqlalchemy.exc` import; `from corelata.store.models import utcnow` becomes `from corelata.store.models import Run, utcnow`. Before `class DbObserver:` add

```python
class RunEnded(Exception):
    """The run ended while this execution still held it: a cancel found its worker gone and
    ended it (R-M17-2). The execution stops and writes nothing more."""
```

replace `DbObserver`'s docstring and its first two methods with:

```python
    """The pipeline's observer for a queued run: short transactions between model calls, each
    announcing the change on the run channel when it commits (CRL-22). Every write first checks,
    under the run's row lock, that the run has not ended (`RunEnded`), so a worker that was taken
    for dead can never write over the ending it was given."""

    def __init__(self, db: Database, run_id: uuid.UUID, calls: CallLog) -> None:
        self.db = db
        self.run_id = run_id
        self.calls = calls
        self.stages_saved = 0
        self.calls_saved = 0

    async def locked(self, s: AsyncSession) -> Run:
        """The run under its row lock, while it has not ended."""
        run = await runs.get_run(s, self.run_id, lock=True)
        if RunState(run.state) in TERMINAL_STATES:
            raise RunEnded(f"run {self.run_id} is already {run.state}")
        return run

    async def state_changed(self, record: RunRecord) -> None:
        async with self.db.session() as s, s.begin():
            run = await self.locked(s)
            run.state = record.state.value
            await runs.notify_run(s, self.run_id)
```

in `stage_recorded` replace `run = await runs.get_run(s, self.run_id, lock=True)` with `run = await self.locked(s)`; in `execute_run`'s save transaction (after `phase = "failed while saving"`) replace `run = await runs.get_run(s, run_id, lock=True)` with `run = await observer.locked(s)`; and in `execute_run` insert before `except DB_ERRORS:`:

```python
    except RunEnded as e:
        log.warning(
            "run %s ended while this worker ran it (%s); stopping without writing",
            run_id,
            e,
            extra={"run_id": str(run_id)},
        )
        return
```

- [ ] **Step 6: The CLI and the API pass the configured threshold**

In `engine/corelata/cli_ops.py`, `_cancel`, replace `state = _with_db(cfg, lambda db: service.cancel_run(db, run_id))` with:

```python
    state = _with_db(
        cfg,
        lambda db: service.cancel_run(db, run_id, stalled_after_s=cfg.worker.stalled_after_s),
    )
```

In `api/corelata_api/routes/runs.py`, `cancel_run`, replace `await service.cancel_run(ctx.db, run_id)` with `await service.cancel_run(ctx.db, run_id, stalled_after_s=ctx.cfg.worker.stalled_after_s)` (the docstring stays).

- [ ] **Step 7: Run the tests**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/worker tests/test_service.py tests/test_cli_ops.py --no-cov -q && uv run ruff check . && uv run ruff format --check .`
Expected: all pass. With the fence removed (`locked` not raising), `test_a_worker_taken_for_dead_stops_at_its_next_write` fails with `['ingesting', 'gating', 'drafting'] == ['ingesting', 'gating']`: the worker wrote over the cancel (seen on the scratch copy).

Run: `cd api && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/test_runs.py --no-cov -q && uv run ruff check . && uv run ruff format --check .`
Expected: all pass.

Run: `make schema && git status --short schema web/src/api/schema.d.ts`
Expected: no output (the route's docstring did not change).

- [ ] **Step 8: Commit**

```bash
cat > "$SCRATCH/m17-task2-commit.txt" <<'EOF'
feat: cancelling a run whose worker is gone ends it at once; a worker taken for dead stops (CRL-38)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git add engine/corelata/store/runs.py engine/corelata/service.py engine/corelata/worker/execute.py engine/corelata/cli_ops.py engine/corelata/testing/postgres.py api/corelata_api/routes/runs.py engine/tests/worker/test_orphan_cancel.py engine/tests/worker/test_rerun_end.py engine/tests/test_cli_ops.py api/tests/test_runs.py
git commit -F "$SCRATCH/m17-task2-commit.txt"
```

---

### Task 3: The API passes the configured deadline; the screen waits for the server's ending (CRL-38: API, web)

**Files:**
- Modify: `api/corelata_api/routes/discoveries.py`, `web/src/api/discoveries.ts` (constants, `discoveryCeiling`, `discoveryStalled`, `discoveryPollInterval`'s comment)
- Test: `api/tests/test_discoveries.py`, `web/src/api/discoveries.test.tsx`, `web/src/pages/new/Suggestions.test.tsx`

**Interfaces:**
- Consumes: Task 1's `service.get_discovery(..., deadline_s=)`, `DiscoveryView.deadline_at`, the web fixtures `DEADLINE_MS`, `deadlineFor`; `api/tests/conftest.py`'s `make_api`, `project_with_source`.
- Produces: `DISCOVERY_GRACE_MS = 15_000`, `discoveryCeiling(view: DiscoveryView): number` in `web/src/api/discoveries.ts`; `DISCOVERY_CEILING_MS` and `DISCOVERY_STALLED` unchanged.

- [ ] **Step 1: The failing tests**

In `api/tests/test_discoveries.py`: the imports become

```python
import uuid
from datetime import datetime, timedelta

from sqlalchemy import text

from tests.conftest import project_with_source
```

and append:

```python
_AGED = text("UPDATE discovery SET created_at = now() - interval '61 seconds' WHERE id = :id")


async def test_a_discovery_past_the_configured_deadline_is_failed_by_the_read(make_api):
    async with make_api(worker={"discovery_deadline_s": 60}) as api:
        pid, sid = await project_with_source(api)
        created = await api.client.post(
            "/api/discoveries", json={"project_id": pid, "source_ids": [sid]}
        )
        view = created.json()
        started = datetime.fromisoformat(view["created_at"])
        assert datetime.fromisoformat(view["deadline_at"]) == started + timedelta(seconds=60)
        async with api.db.session() as s, s.begin():  # no worker runs; a minute passes
            await s.execute(_AGED, {"id": uuid.UUID(view["discovery_id"])})
        read = (await api.client.get(f"/api/discoveries/{view['discovery_id']}")).json()
        assert read["state"] == "failed" and read["finished_at"] is not None
        assert read["error"] == (
            "Discovery did not finish within 1 minute and was stopped. Start a new discovery."
        )
```

In `web/src/api/discoveries.test.tsx`: add `deadlineFor,` to the fixtures import (after `candidates,`) and `DISCOVERY_GRACE_MS,` and `discoveryCeiling,` to the `./discoveries` import (after `DISCOVERY_CEILING_MS,` and after `discoveryAge,`); replace the test `stops polling once the discovery has run 10 minutes, and only while it runs (R-M16-2)` with:

```tsx
it("stops polling at the server's deadline plus the grace, and only while it runs (R-M17-1)", () => {
  const ceiling = DISCOVERY_CEILING_MS + DISCOVERY_GRACE_MS; // the default 10-minute deadline
  const justUnder = read({ state: "running" }, ceiling - 1);
  const atCeiling = read({ state: "running" }, ceiling);
  expect(discoveryCeiling(justUnder)).toBe(ceiling);
  expect(discoveryStalled(justUnder)).toBe(false);
  expect(discoveryPollInterval(justUnder, null, 9)).toBe(DISCOVERY_POLL_MAX_MS);
  expect(discoveryStalled(atCeiling)).toBe(true);
  expect(discoveryPollInterval(atCeiling, null, 9)).toBe(false);
  expect(discoveryStalled(read({ state: "created" }, ceiling))).toBe(true);
  // an ended discovery is shown as it ended, however old
  expect(discoveryStalled(read({ state: "completed" }, 2 * ceiling))).toBe(false);
  expect(discoveryStalled(read({ state: "failed" }, 2 * ceiling))).toBe(false);
  expect(discoveryStalled(undefined)).toBe(false);
});

it("follows the configured deadline, but never stops asking sooner than 10 minutes", () => {
  const created = minutesAgo(0);
  const longer = discoveryView({
    created_at: created,
    deadline_at: deadlineFor(created, 1_200_000),
  });
  expect(discoveryCeiling(longer)).toBe(1_200_000 + DISCOVERY_GRACE_MS);
  const shorter = discoveryView({ created_at: created, deadline_at: deadlineFor(created, 60_000) });
  expect(discoveryCeiling(shorter)).toBe(DISCOVERY_CEILING_MS); // the fallback text stays true
  expect(discoveryCeiling(discoveryView({ deadline_at: "not a date" }))).toBe(DISCOVERY_CEILING_MS);
});
```

In `web/src/pages/new/Suggestions.test.tsx`: the fixtures import becomes

```tsx
import {
  candidates,
  DEADLINE_MS,
  deadlineFor,
  DISCOVERY_ID,
  discoveryView,
  minutesAgo,
  source,
} from "../../test/fixtures";
```

replace `serveSequence` with:

```tsx
/** Answers each read with the next [view, seconds] pair: the view, created at `created` with a
 * deadline `deadlineMs` later (the server's default, 10 minutes), and a `Date` header that many
 * seconds after `created` (the server's clock). The last pair repeats. */
function serveSequence(
  created: string,
  answers: [DiscoveryView, number][],
  deadlineMs = DEADLINE_MS,
): () => number {
  let served = 0;
  server.use(
    http.get(`*/api/discoveries/${DISCOVERY_ID}`, () => {
      const [view, seconds] = answers[Math.min(served, answers.length - 1)]!;
      served += 1;
      const date = new Date(Date.parse(created) + seconds * 1000).toUTCString();
      return HttpResponse.json(
        { ...view, created_at: created, deadline_at: deadlineFor(created, deadlineMs) },
        { headers: { Date: date } },
      );
    }),
  );
  return () => served;
}
```

insert before `stops at the read that crosses the ceiling, and a later reload shows how it ended`:

```tsx
it("a discovery the server fails at its deadline shows the server's reason, without a reload (R-M17-1)", async () => {
  const created = new Date(Date.now() - 3_600_000).toISOString(); // only the server's Date matters
  const reason =
    "Discovery did not finish within 20 minutes and was stopped. Start a new discovery.";
  // a 20-minute deadline: past 10 minutes the screen keeps asking, and shows the server's ending
  serveSequence(
    created,
    [
      [discoveryView({ state: "running" }), 19 * 60 + 59],
      [discoveryView({ state: "failed", error: reason }), 20 * 60 + 1], // the read that failed it
    ],
    20 * 60_000,
  );
  const { queryClient } = renderWithClient(
    <Suggestions discoveryId={DISCOVERY_ID} onPick={() => {}} />,
  );
  expect(await screen.findByRole("alert", {}, { timeout: 5000 })).toHaveTextContent(reason);
  expect(screen.queryByText(DISCOVERY_STALLED)).not.toBeInTheDocument();
  expect(discoveryRefetchInterval(queryClient, DISCOVERY_ID)).toBe(false);
});
```

and in `stops at the read that crosses the ceiling, …` replace the two `serveSequence` pairs with

```tsx
    // the server did not end it at its deadline (a clock that is off): 1 s under the ceiling
    [discoveryView({ state: "running" }), 10 * 60 + 14],
    [discoveryView({ state: "running" }), 10 * 60 + 16],
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd api && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/test_discoveries.py --no-cov -q`
Expected: 1 failure at `read["state"] == "failed"`: the route reads with the default 600 s, so a discovery 61 s old is still `created`.

Run: `cd web && pnpm vitest run src/api/discoveries.test.tsx src/pages/new/Suggestions.test.tsx`
Expected: `discoveryCeiling` and `DISCOVERY_GRACE_MS` are not exported (type errors in vitest are not fatal: the two new `discoveries.test.tsx` tests fail with `discoveryCeiling is not a function`); in `Suggestions.test.tsx`, `a discovery the server fails at its deadline …` and `stops at the read that crosses the ceiling …` time out (the screen stops at 10 minutes; seen on the scratch copy).

- [ ] **Step 3: The API route**

Replace the two routes' bodies in `api/corelata_api/routes/discoveries.py` and add the helper; the context import becomes `from corelata_api.context import ApiContext, Ctx`:

```python
@router.post("/discoveries", status_code=202)
async def create_discovery(body: CreateDiscovery, ctx: Ctx) -> DiscoveryView:
    discovery_id = await service.start_discovery(
        ctx.db, ctx.queue, body.project_id, body.source_ids, body.audience_hint
    )
    return await _read(ctx, discovery_id)


@router.get("/discoveries/{discovery_id}")
async def get_discovery(discovery_id: uuid.UUID, ctx: Ctx) -> DiscoveryView:
    return await _read(ctx, discovery_id)


async def _read(ctx: ApiContext, discovery_id: uuid.UUID) -> DiscoveryView:
    # past its deadline, the read fails it: the deadline holds with no worker running (R-M17-1)
    return await service.get_discovery(
        ctx.db, discovery_id, deadline_s=ctx.cfg.worker.discovery_deadline_s
    )
```

- [ ] **Step 4: The screen's ceiling**

In `web/src/api/discoveries.ts` replace the `DISCOVERY_CEILING_MS` comment and add the grace and the fallback's comment:

```ts
/** The screen never stops asking sooner than this (CRL-21, R-M16-2), so the fallback message
 * below is always true. */
export const DISCOVERY_CEILING_MS = 10 * 60_000;
/** How long past the server's deadline the screen keeps asking, so that at least one read lands
 * after the server failed the discovery and the screen shows the server's reason (R-M17-1). */
export const DISCOVERY_GRACE_MS = 15_000;
/** Shown only when the server did not end a discovery by its deadline (a clock that is off, or a
 * server that does not enforce one). */
export const DISCOVERY_STALLED =
```

(the message's text stays exactly as it is), replace `discoveryStalled` and its comment with:

```ts
/** How old a discovery may be, by the server's clock, before the screen stops asking: its
 * deadline (`deadline_at` - `created_at`, both the server's) plus DISCOVERY_GRACE_MS, and never
 * less than DISCOVERY_CEILING_MS (R-M17-1). */
export function discoveryCeiling(view: DiscoveryView): number {
  const deadline = Date.parse(view.deadline_at) - Date.parse(view.created_at);
  if (Number.isNaN(deadline)) return DISCOVERY_CEILING_MS;
  return Math.max(DISCOVERY_CEILING_MS, deadline + DISCOVERY_GRACE_MS);
}

/** Still running past its ceiling, as of the latest read (R-M16-2, R-M17-1). */
export function discoveryStalled(view: DiscoveryRead | undefined): boolean {
  return view !== undefined && !ended(view) && view.age_ms >= discoveryCeiling(view);
}
```

and `discoveryPollInterval`'s comment becomes:

```ts
/** 1 s, 2 s, 4 s, then every 5 s (R-M9-9, R-M16-3), until the discovery ends or passes its
 * ceiling (R-M17-1). `polls` is how many answers (or failures) the query has had so far. */
```

`Suggestions.tsx` needs no change: a failed discovery shows its `error` in its alert, as before.

- [ ] **Step 5: Run the tests**

Run: `cd api && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/test_discoveries.py --no-cov -q && uv run ruff check . && uv run ruff format --check .`
Expected: 3 passed; clean.

Run: `cd web && pnpm lint && pnpm vitest run src/api src/pages/new`
Expected: clean; all pass.

- [ ] **Step 6: Commit**

```bash
cat > "$SCRATCH/m17-task3-commit.txt" <<'EOF'
feat: the discovery routes enforce the configured deadline; the screen waits for the server's ending (CRL-38)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git add api/corelata_api/routes/discoveries.py api/tests/test_discoveries.py web/src/api/discoveries.ts web/src/api/discoveries.test.tsx web/src/pages/new/Suggestions.test.tsx
git commit -F "$SCRATCH/m17-task3-commit.txt"
```

---

### Task 4: A `base_url` with a query or a fragment is refused; doctor's suggestions ignore case (CRL-39: config, doctor)

**Files:**
- Modify: `engine/corelata/config.py` (`BackendConfig`), `engine/corelata/doctor.py` (`_similar`)
- Test: `engine/tests/test_config.py`, `engine/tests/test_doctor.py`

**Interfaces:**
- Consumes: `tests/test_config.py`'s `_write(tmp_path, data)`, `BASE_CONFIG` (backend `fake`); `tests/test_doctor.py`'s `_config(tmp_path, server_url, **extra)` (backend `local`), `_one_model(tmp_path, server, name)`, `_by_name(report)`, `FakeBackend(models=...)`, the `server` fixture.
- Produces: `BackendConfig._no_query_or_fragment` (a `field_validator` on `base_url`); `_similar` unchanged in signature.

- [ ] **Step 1: The failing tests**

In `engine/tests/test_config.py`, before `test_auth_header_must_be_http_token`:

```python
BASE_URL_REFUSED = (
    "backends.fake.base_url: Value error, must not contain a query string (?...) or a fragment "
    "(#...): Corelata adds the request path (/chat/completions, /models) to base_url, so it "
    "would land inside the query. Write the server's address and path only, such as "
    "http://models:8000/v1, and give a key with api_key_env (the name of an environment "
    "variable that holds it)"
)


@pytest.mark.parametrize(
    "base_url",
    [
        "http://h/v1?key=abc",
        "http://h/v1?",
        "http://h/v1#models",
        "http://h:8000/v1/?api-version=1",
    ],
)
def test_a_base_url_with_a_query_or_a_fragment_is_refused(tmp_path, base_url):
    path = _write(tmp_path, {**BASE_CONFIG, "backends": {"fake": {"base_url": base_url}}})
    with pytest.raises(ConfigError) as refused:
        load_config(path)
    assert str(refused.value) == f"{path}: {BASE_URL_REFUSED}"


@pytest.mark.parametrize("base_url", ["http://h/v1", "http://h:8000/v1/", "https://u:p@h/v1"])
def test_a_plain_base_url_is_accepted(make_config, base_url):
    assert make_config(backends={"fake": {"base_url": base_url}}).backends["fake"].base_url == (
        base_url
    )
```

In `engine/tests/test_doctor.py`, after `test_a_missing_model_suggests_at_most_five_served_ids_with_its_prefix`:

```python
async def test_the_suggestions_ignore_case_and_keep_their_order(tmp_path, server, monkeypatch):
    monkeypatch.delenv("CORELATA_DATABASE_URL", raising=False)
    served = ("Qwen/Qwen3-32B-Instruct", "qwen/qwen3-8b", "QWEN/qwq-32b", "openai/gpt-4o")

    async def fix_for(name):
        report = await run_doctor(
            _one_model(tmp_path, server, name),
            probe=False,
            backends_factory=lambda cfg: {"local": FakeBackend(models=served)},
        )
        return _by_name(report)["model m"].fix

    expected = (
        "set models.m.name to a served id, such as: QWEN/qwq-32b, Qwen/Qwen3-32B-Instruct, "
        "qwen/qwen3-8b"  # sorted as before (R-M12-2): by code point, so capitals first
    )
    assert await fix_for("qwen/qwen3-32b") == expected
    assert await fix_for("QWEN/Qwen3-32b") == expected
    assert await fix_for("OpenAI/gpt-4.1") == (
        "set models.m.name to a served id, such as: openai/gpt-4o"
    )


async def test_a_base_url_with_a_query_fails_the_config_check(tmp_path, server):
    path = _config(tmp_path, server.base_url + "?key=abc")
    report = await run_doctor(path)
    [check] = report.checks
    assert check.name == "config" and check.status is CheckStatus.FAIL and not report.ok
    assert "backends.local.base_url: Value error, must not contain a query string" in check.message
    assert "give a key with api_key_env" in check.message
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/test_config.py tests/test_doctor.py --no-cov -q`
Expected: the four `test_a_base_url_with_a_query_or_a_fragment_is_refused` cases fail (`DID NOT RAISE`), `test_a_base_url_with_a_query_fails_the_config_check` fails (the config check passes and doctor goes on), and `test_the_suggestions_ignore_case_and_keep_their_order` fails (`set models.m.name to a served id; see the server's model list` for the lower-case and the mixed-case names).

- [ ] **Step 3: The validator and the case-insensitive prefix**

In `engine/corelata/config.py`, `BackendConfig`, after `timeout_s`:

```python

    @field_validator("base_url")
    @classmethod
    def _no_query_or_fragment(cls, value: str) -> str:
        # httpx joins the request path after the query: http://h/v1?key=abc/chat/completions
        # (CRL-39, R-M17-3)
        if "?" in value or "#" in value:
            raise ValueError(
                "must not contain a query string (?...) or a fragment (#...): Corelata adds the "
                "request path (/chat/completions, /models) to base_url, so it would land inside "
                "the query. Write the server's address and path only, such as "
                "http://models:8000/v1, and give a key with api_key_env (the name of an "
                "environment variable that holds it)"
            )
        return value
```

In `engine/corelata/doctor.py` replace `_similar` with:

```python
def _similar(model_id: str, served: list[str]) -> list[str]:
    """Up to SIMILAR_MAX served ids with the same prefix as `model_id`, ignoring case (R-M17-4),
    sorted (R-M12-2)."""
    prefix = _prefix(model_id).casefold()
    return sorted({s for s in served if _prefix(s).casefold() == prefix})[:SIMILAR_MAX]
```

- [ ] **Step 4: Run the tests**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/test_config.py tests/test_doctor.py tests/llm --no-cov -q && uv run ruff check . && uv run ruff format --check .`
Expected: all pass; clean.

- [ ] **Step 5: Commit**

```bash
cat > "$SCRATCH/m17-task4-commit.txt" <<'EOF'
fix: refuse a base_url with a query or a fragment; doctor's suggestions ignore case (CRL-39)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git add engine/corelata/config.py engine/corelata/doctor.py engine/tests/test_config.py engine/tests/test_doctor.py
git commit -F "$SCRATCH/m17-task4-commit.txt"
```

---

### Task 5: The run list index, migration 0006 (CRL-39: migration, model)

**Files:**
- Create: `engine/corelata/store/migrations/versions/0006_run_list_index.py`
- Modify: `engine/corelata/store/models.py` (imports, `Run.__table_args__`), `engine/corelata/store/migrate.py` (module docstring)
- Test: `engine/tests/store/test_migrations.py` (`HEAD`, append), `engine/tests/test_cli_ops.py` (`test_migrate_is_idempotent_and_redacts_the_url`), `engine/tests/test_doctor.py` (the database check's revision)

**Interfaces:**
- Consumes: `tests/store/test_migrations.py`'s `_RUN_AT_0003`, `create_test_database`, `drop_test_database`, `upgrade`, `downgrade`, the `pg_admin` fixture.
- Produces: the index `ix_run_project_created` on `run (project_id, created_at DESC, id DESC)`; Alembic head `0006`.

- [ ] **Step 1: The failing tests**

In `engine/tests/store/test_migrations.py` set `HEAD = "0006"` and append:

```python


_RUN_INDEX = text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_run_project_created'")
_FIRST_PAGE = text(
    "EXPLAIN (FORMAT JSON) SELECT * FROM run WHERE project_id = :project "
    "ORDER BY created_at DESC, id DESC LIMIT 101"
)


def _plan_nodes(plan: dict) -> list[str]:
    nodes = [f"{plan['Node Type']}:{plan.get('Index Name', '')}"]
    for child in plan.get("Plans", []):
        nodes += _plan_nodes(child)
    return nodes


def test_0006_adds_the_run_list_index_to_a_0005_database_and_the_downgrade_drops_it(pg_admin):
    """A 0.1.5 database (head 0005) with runs in it: the upgrade adds the index the run list
    reads by, the page query uses it, and the downgrade removes it again (CRL-39, R-M17-5)."""
    url = create_test_database(pg_admin)
    engine = create_engine(to_sqlalchemy_url(url), poolclass=NullPool)
    try:
        upgrade(url, "0005")
        project = uuid.uuid4()
        at = datetime(2026, 10, 19, 9, tzinfo=UTC)
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO project (id, name, created_at) VALUES (:id, 'p', :at)"),
                {"id": project, "at": at},
            )
            for _ in range(3):
                conn.execute(text(_RUN_AT_0003), {"id": uuid.uuid4(), "project": project, "at": at})
            assert conn.execute(_RUN_INDEX).scalar() is None
        upgrade(url, "0006")
        with engine.begin() as conn:
            assert conn.execute(_RUN_INDEX).scalar_one() == (
                "CREATE INDEX ix_run_project_created ON public.run USING btree "
                "(project_id, created_at DESC, id DESC)"
            )
            assert conn.execute(text("SELECT count(*) FROM run")).scalar_one() == 3
            conn.execute(text("SET LOCAL enable_seqscan = off"))  # three rows: force the choice
            conn.execute(text("SET LOCAL enable_bitmapscan = off"))
            [[explained]] = conn.execute(_FIRST_PAGE, {"project": project}).all()
            nodes = _plan_nodes(explained[0]["Plan"])
            assert "Index Scan:ix_run_project_created" in nodes
            assert not any(n.startswith("Sort:") for n in nodes)  # no sort: the index's order
        downgrade(url, "0005")
        with engine.connect() as conn:
            assert conn.execute(_RUN_INDEX).scalar() is None
            assert conn.execute(text("SELECT count(*) FROM run")).scalar_one() == 3
    finally:
        engine.dispose()
        drop_test_database(pg_admin, url)
```

In `engine/tests/test_cli_ops.py`, `test_migrate_is_idempotent_and_redacts_the_url`, replace `"at revision 0005"` with `"at revision 0006"`; in `engine/tests/test_doctor.py` replace `assert "0005" in checks["database"].message` with `assert "0006" in checks["database"].message`.

- [ ] **Step 2: Run them to see them fail**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/store/test_migrations.py --no-cov -q`
Expected: `test_migration_state_is_current` fails (`'0005' == '0006'`) and the new test fails (`Can't locate revision identified by '0006'`).

- [ ] **Step 3: The migration and the model**

Create `engine/corelata/store/migrations/versions/0006_run_list_index.py`:

```python
"""run list index: (project_id, created_at DESC, id DESC) (CRL-39)

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-20 10:00:00.000000

`GET /api/runs` pages a project's runs newest first by `(created_at, id)` (R-M14-1). With only
`ix_run_project_id`, Postgres reads every run of the project and sorts them for each page; this
index matches the query's order exactly, so a page is an index scan that stops after `limit`
rows. Measured on 50,000 runs in five projects (R-M17-5): the first page went from 6.9 ms and
2,011 buffers (bitmap heap scan and top-N sort over 10,000 rows) to 0.08 ms and 25 buffers, a
keyset page 5,000 runs in from 7.5 ms to 0.09 ms. A plain CREATE INDEX: `migrate` runs before
`api` and `worker` start, and it takes about a second per 100,000 runs.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_run_project_created",
        "run",
        ["project_id", sa.text("created_at DESC"), sa.text("id DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_run_project_created", table_name="run")
```

In `engine/corelata/store/models.py`: add `Index,` after `Identity,` and `text,` after `UniqueConstraint,` in the `sqlalchemy` import; in `class Run`, after `__tablename__ = "run"`:

```python
    # the run list's order, newest first by (created_at, id) (CRL-39, migration 0006)
    __table_args__ = (
        Index("ix_run_project_created", "project_id", text("created_at DESC"), text("id DESC")),
    )
```

In `engine/corelata/store/migrate.py` the module docstring's second and third lines become:

```python
`run.review_state`, 0005 the rerun's fate in it, 0006 the run list's index; a procrastinate
upgrade needs a new revision that applies its migration SQL. Copied from Coglossa."""
```

- [ ] **Step 4: Run the tests**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/store tests/test_doctor.py tests/test_cli_ops.py::test_migrate_is_idempotent_and_redacts_the_url --no-cov -q && uv run ruff check . && uv run ruff format --check .`
Expected: all pass, `test_models_match_the_migrations` included (the model's index matches the migration's); clean.

- [ ] **Step 5: Commit**

```bash
cat > "$SCRATCH/m17-task5-commit.txt" <<'EOF'
feat: index the run list by (project_id, created_at DESC, id DESC), migration 0006 (CRL-39)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git add engine/corelata/store/migrations/versions/0006_run_list_index.py engine/corelata/store/models.py engine/corelata/store/migrate.py engine/tests/store/test_migrations.py engine/tests/test_cli_ops.py engine/tests/test_doctor.py
git commit -F "$SCRATCH/m17-task5-commit.txt"
```

---

### Task 6: Chosen sources in the URL, cancellations are not network errors, evidence says it loads, no empty hint; the race test waits for a signal (CRL-40: web)

**Files:**
- Modify: `web/src/pages/new/NewRunPage.tsx`, `web/src/pages/new/ValueStatement.tsx` (`suggest`), `web/src/api/client.ts` (`unwrap`, `unwrapText`), `web/src/api/discoveries.ts` (`StartDiscovery`, `useStartDiscovery`, `useDiscovery`'s `queryFn`), `web/src/api/runs.ts` (`useRun`), `web/src/api/projects.ts` (`useProjects`, `useProject`, `useSources`, `useRuns`), `web/src/api/reports.ts` (every hook), `web/src/api/packs.ts` (both hooks), `web/src/api/system.ts` (`useInfo`), `web/src/pages/review/ProvenanceTab.tsx`, `web/src/test/render.tsx` (`renderWithClient`)
- Test: `web/src/pages/new/NewRunPage.test.tsx`, `web/src/pages/new/SourcesPanel.test.tsx`, `web/src/pages/new/ValueStatement.test.tsx`, `web/src/api/client.test.ts`, `web/src/pages/review/ProvenanceTab.test.tsx`

**Interfaces:**
- Consumes: `web/src/test/deferred.ts` (`deferred()`), `renderApp(path)` (returns `router`, `user`, `queryClient`), fixtures `sources`, `source`, `project`, `noRuns`, `packs`, `runProgress`, `discoveryView`, `candidates`, `DISCOVERY_ID`, `claimProvenance`, `RUN_ID`; `reportKeys.claim(runId, claimId)`.
- Produces: `SOURCES_PARAM = "sources"` (exported from `NewRunPage.tsx`); `unwrapText(url: string, signal?: AbortSignal)`; `StartDiscovery.audience_hint?: string`; `renderWithClient(ui)` returns `{ user, queryClient, unmount }`.

- [ ] **Step 1: The failing tests**

In `web/src/pages/new/NewRunPage.test.tsx`: the first imports become

```tsx
import { cleanup, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import type { SourceView } from "../../api/types";
import { deferred } from "../../test/deferred";
```

(the fixtures import stays); after `serveTwoProjects` add:

```tsx
function chosenIn(search: string): string | null {
  return new URLSearchParams(search).get("sources");
}

const [PORT, LETTER] = sources as [SourceView, SourceView];
const GONE = "99999999-9999-9999-9999-999999999999"; // not a source of the project (any more)

it("keeps the chosen sources in the URL, so a reload selects them again (R-M17-6)", async () => {
  serve();
  server.use(
    http.post("*/api/discoveries", () => HttpResponse.json(discoveryView(), { status: 202 })),
    http.get(`*/api/discoveries/${DISCOVERY_ID}`, () =>
      HttpResponse.json(discoveryView({ state: "completed", candidates })),
    ),
  );
  const first = renderApp(`/new?project=${project.id}`);
  const letter = await screen.findByRole("checkbox", { name: `Use ${LETTER.name} in this run` });
  expect(letter).toBeChecked(); // no parameter: every source
  expect(chosenIn(first.router.state.location.search)).toBeNull();
  await first.user.click(letter);
  await waitFor(() => expect(chosenIn(first.router.state.location.search)).toBe(PORT.id));
  expect(first.router.state.historyAction).toBe("REPLACE");
  // a discovery keeps the choice beside it, and the choice keeps the discovery
  await first.user.click(screen.getByRole("button", { name: "Suggest value" }));
  await waitFor(() =>
    expect(new URLSearchParams(first.router.state.location.search).get("discovery")).toBe(
      DISCOVERY_ID,
    ),
  );
  expect(chosenIn(first.router.state.location.search)).toBe(PORT.id);
  const url = `/new${first.router.state.location.search}`;
  cleanup(); // the reload

  renderApp(url);
  expect(
    await screen.findByRole("checkbox", { name: `Use ${PORT.name} in this run` }),
  ).toBeChecked();
  expect(
    screen.getByRole("checkbox", { name: `Use ${LETTER.name} in this run` }),
  ).not.toBeChecked();
  expect(screen.getByRole("status", { name: "Selected sources" })).toHaveTextContent(
    "1 of 2 selected",
  );
  expect(
    await screen.findByRole("list", { name: "Suggested value statements" }),
  ).toBeInTheDocument();
});

it("drops ids in the URL that are not the project's, and starts with the rest", async () => {
  serve();
  let body: { source_ids?: string[] } = {};
  server.use(
    http.post("*/api/runs", async ({ request }) => {
      body = (await request.json()) as typeof body;
      return HttpResponse.json(runProgress(), { status: 202 });
    }),
    http.get(`*/api/runs/${runProgress().run_id}`, () => HttpResponse.json(runProgress())),
  );
  const { router, user } = renderApp(`/new?project=${project.id}&sources=${GONE},${PORT.id}`);
  expect(
    await screen.findByRole("checkbox", { name: `Use ${PORT.name} in this run` }),
  ).toBeChecked();
  expect(
    screen.getByRole("checkbox", { name: `Use ${LETTER.name} in this run` }),
  ).not.toBeChecked();
  expect(screen.getByRole("status", { name: "Selected sources" })).toHaveTextContent(
    "1 of 2 selected",
  );
  await user.type(screen.getByRole("textbox", { name: "Value statement" }), "x");
  await user.click(screen.getByRole("button", { name: "Start" }));
  await waitFor(() => expect(router.state.location.pathname).toBe(`/runs/${runProgress().run_id}`));
  expect(body.source_ids).toEqual([PORT.id]); // the stale id is not sent
});

it("a URL that names none of the project's sources selects none", async () => {
  serve();
  renderApp(`/new?project=${project.id}&sources=${GONE}`);
  expect(
    await screen.findByRole("checkbox", { name: `Use ${PORT.name} in this run` }),
  ).not.toBeChecked();
  expect(screen.getByRole("button", { name: "Start" })).toBeDisabled();
  expect(screen.getByText("Choose at least one source.")).toBeInTheDocument();
});
```

rename `choosing another project drops the discovery from the URL (R-M16-14)` to `choosing another project drops the discovery and the chosen sources from the URL (R-M16-14, R-M17-6)` and render it at

```tsx
  const { router, user } = renderApp(
    `/new?project=${project.id}&sources=${PORT.id}&discovery=${DISCOVERY_ID}`,
  );
```

(its expectation `?project=${OTHER.id}` stays); and in `a discovery that starts for the old project does not write itself into the new project's URL` replace everything from `let release!` to the end of the test with:

```tsx
  const held = deferred();
  let posted = false;
  let answered = false;
  server.use(
    http.post("*/api/discoveries", async () => {
      posted = true;
      await held.promise;
      answered = true;
      return HttpResponse.json(discoveryView(), { status: 202 });
    }),
  );
  const { router, user, queryClient } = renderApp(`/new?project=${project.id}`);
  await user.click(await screen.findByRole("button", { name: "Suggest value" }));
  await waitFor(() => expect(posted).toBe(true));
  await user.selectOptions(screen.getByRole("combobox", { name: "Project" }), OTHER.id);
  await waitFor(() => expect(router.state.location.search).toBe(`?project=${OTHER.id}`));
  held.resolve();
  // the answer arrived and the mutation settled: whatever it would write, it has written
  await waitFor(() => expect(answered).toBe(true));
  await waitFor(() => expect(queryClient.isMutating()).toBe(0));
  expect(router.state.location.search).toBe(`?project=${OTHER.id}`);
});
```

In `web/src/pages/new/SourcesPanel.test.tsx`, `uploads a file, adds and selects it …`: `const { user } = renderApp(…)` becomes `const { router, user } = renderApp(…)`, and append to the test, after the input's value assertion:

```tsx
  // the choice in the URL gained the new source (R-M17-6)
  expect(new URLSearchParams(router.state.location.search).get("sources")).toBe(
    "55555555-5555-5555-5555-555555555555",
  );
```

then add after that test:

```tsx
it("an upload while every source is selected keeps every source selected, and the URL bare", async () => {
  vi.stubGlobal("FormData", await nodeFormData());
  vi.stubGlobal("File", NodeFileClass);
  const added = { ...source, id: "55555555-5555-5555-5555-555555555555", name: "more.md" };
  const list = [source];
  server.use(
    http.get("*/api/projects", () => HttpResponse.json([project])),
    http.get(`*/api/projects/${project.id}/sources`, () => HttpResponse.json(list)),
    http.get("*/api/runs", () => HttpResponse.json(noRuns)),
    http.post(`*/api/projects/${project.id}/sources`, () => {
      list.push(added);
      return HttpResponse.json([added], { status: 201 });
    }),
  );
  const { router, user } = renderApp(`/new?project=${project.id}`);
  await user.upload(
    await screen.findByLabelText("Add a file"),
    new File(["# Notes"], "more.md", { type: "text/markdown" }),
  );
  await user.click(screen.getByRole("button", { name: "Upload" }));
  expect(await screen.findByRole("checkbox", { name: "Use more.md in this run" })).toBeChecked();
  expect(screen.getByRole("checkbox", { name: "Use port.txt in this run" })).toBeChecked();
  expect(router.state.location.search).toBe(`?project=${project.id}`);
});
```

In `web/src/pages/new/ValueStatement.test.tsx`, the first test's POST handler becomes:

```tsx
    http.post("*/api/discoveries", async ({ request }) => {
      // no audience hint is left out, not sent as "" (R-M17-6)
      expect(await request.text()).toBe(
        JSON.stringify({ project_id: project.id, source_ids: [source.id] }),
      );
      return HttpResponse.json(discoveryView(), { status: 202 });
    }),
```

In `web/src/api/client.test.ts`: add `import { deferred } from "../test/deferred";` before the `server` import, and before `describe("urls", …)`:

```ts
describe("a cancelled request (CRL-40)", () => {
  function held(path: string) {
    const gate = deferred();
    server.use(
      http.get(path, async () => {
        await gate.promise;
        return HttpResponse.json([]);
      }),
    );
    return gate;
  }

  it("rejects with its AbortError, not the network error", async () => {
    const gate = held("*/api/projects");
    const controller = new AbortController();
    const call = unwrap(client.GET("/api/projects", { signal: controller.signal }));
    controller.abort();
    const error = await call.catch((e: unknown) => e);
    expect(error).not.toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ name: "AbortError" });
    gate.resolve();
  });

  it("does the same for a text route", async () => {
    const gate = held("*/api/runs/r/report");
    const controller = new AbortController();
    const call = unwrapText("/api/runs/r/report", controller.signal);
    controller.abort();
    await expect(call).rejects.toMatchObject({ name: "AbortError" });
    gate.resolve();
  });
});
```

In `web/src/test/render.tsx` replace `renderWithClient` with:

```tsx
/** A component outside the router, with a query client. `unmount` is leaving the page. */
export function renderWithClient(ui: ReactNode) {
  const queryClient = makeQueryClient({ retry: false });
  const user = userEvent.setup();
  const { unmount } = render(<Providers client={queryClient}>{ui}</Providers>);
  return { user, queryClient, unmount };
}
```

In `web/src/pages/review/ProvenanceTab.test.tsx`: the imports become

```tsx
import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { useState } from "react";
import { reportKeys } from "../../api/reports";
import { deferred } from "../../test/deferred";
import { claimProvenance, reportJson, RUN_ID } from "../../test/fixtures";
```

and before `asks for a selection when none is made` add:

```tsx
it("says the evidence is loading while a selected claim's evidence loads (CRL-40)", async () => {
  const held = deferred();
  server.use(
    http.get(`*/api/runs/${RUN_ID}/claims/c3`, async () => {
      await held.promise;
      return HttpResponse.json(claimProvenance);
    }),
  );
  const { user } = renderWithClient(<Host />);
  const list = await screen.findByRole("list", { name: "Claims" });
  expect(screen.queryByText("Loading evidence…")).not.toBeInTheDocument(); // nothing selected
  await user.click(within(within(list).getAllByRole("listitem")[1]!).getByRole("button"));
  expect(await screen.findByText("Loading evidence…")).toHaveAttribute("role", "status");
  held.resolve();
  expect(await screen.findByRole("list", { name: "Evidence for c3" })).toBeInTheDocument();
  expect(screen.queryByText("Loading evidence…")).not.toBeInTheDocument();
});

it("leaving the page while evidence loads cancels it, and that is not an error (CRL-40)", async () => {
  const held = deferred();
  let request: Request | undefined;
  server.use(
    http.get(`*/api/runs/${RUN_ID}/claims/c1`, async ({ request: seen }) => {
      request = seen;
      await held.promise;
      return HttpResponse.json(claimProvenance);
    }),
  );
  const { queryClient, unmount } = renderWithClient(<Host initial="c1" />);
  expect(await screen.findByText("Loading evidence…")).toBeInTheDocument();
  await waitFor(() => expect(request).toBeDefined());
  unmount(); // the reviewer goes to another page
  await waitFor(() => expect(request!.signal.aborted).toBe(true));
  const state = queryClient.getQueryState(reportKeys.claim(RUN_ID, "c1"))!;
  expect(state.error).toBeNull(); // cancelled, not the network error
  expect(state.status).toBe("pending");
  expect(state.fetchStatus).toBe("idle");
  held.resolve();
});
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd web && pnpm vitest run src/pages/new src/api/client.test.ts src/pages/review/ProvenanceTab.test.tsx`
Expected: failures in the three new `NewRunPage` tests (no `sources` in the URL; the stale-id cases select every source), both `SourcesPanel` URL assertions, the `ValueStatement` body (`…"audience_hint":""}`), both `client.test.ts` cancellation tests (`ApiError` with the network error), and both `ProvenanceTab` tests (no "Loading evidence…"; and, with only the loading state added, `request.signal.aborted` never becomes true: seen on the scratch copy). The rewritten race test passes before and after (it pins behaviour that stays).

- [ ] **Step 3: The sources in the URL**

In `web/src/pages/new/NewRunPage.tsx` replace everything from the component's doc comment to the end of `const selected … );` with:

```tsx
/** The chosen sources' URL parameter: `sources=<id>,<id>` (CRL-40, R-M17-6). */
export const SOURCES_PARAM = "sources";

/** Spec §10.3 screen 1. The project, the discovery (R-M16-14) and the chosen sources live in the
 * URL, so a reload keeps them; the statement and options live here until Start. */
export function NewRunPage() {
  const [params, setParams] = useSearchParams();
  const projectId = params.get("project");
  const sources = useSources(projectId);
  // Without the parameter every source is selected, new ones too. Ids that are not the
  // project's (removed, or a link from another project) are dropped without a word.
  const listed = params.get(SOURCES_PARAM);
  const selected: ReadonlySet<string> = useMemo(() => {
    const ids = (sources.data ?? []).map((s) => s.id);
    if (listed === null) return new Set(ids);
    const chosen = new Set(listed.split(","));
    return new Set(ids.filter((id) => chosen.has(id)));
  }, [listed, sources.data]);
  const choose = useCallback(
    (next: ReadonlySet<string>) =>
      // replace, as for the discovery: Back does not step through every tick of a checkbox
      setParams(
        (current) => {
          const updated = new URLSearchParams(current);
          updated.set(SOURCES_PARAM, [...next].join(","));
          return updated;
        },
        { replace: true },
      ),
    [setParams],
  );
```

and replace `changeProject`, `toggle` and `added` with:

```tsx
  // another project drops the discovery and the chosen sources (R-M16-14, R-M17-6)
  const changeProject = useCallback(
    (id: string) => setParams(id ? { project: id } : {}),
    [setParams],
  );
  const toggle = useCallback(
    (sourceId: string, on: boolean) => {
      const next = new Set(selected);
      if (on) next.add(sourceId);
      else next.delete(sourceId);
      choose(next);
    },
    [selected, choose],
  );
  const added = useCallback(
    (list: SourceView[]) => {
      if (listed === null) return; // every source is selected already, the new ones too
      choose(new Set([...selected, ...list.map((s) => s.id)]));
    },
    [listed, selected, choose],
  );
```

(`useState` stays imported: the statement and the options use it.)

- [ ] **Step 4: No empty hint**

In `web/src/pages/new/ValueStatement.tsx`, `suggest`, the mutation's body becomes:

```tsx
      // no audience hint: the screen has no field for one, so the field is left out (R-M17-6)
      { project_id: projectId, source_ids: sourceIds },
```

In `web/src/api/discoveries.ts` replace `StartDiscovery` and `useStartDiscovery` with:

```ts
/** No audience hint: leave the field out rather than send "" (R-M17-6); the server's default is
 * "" either way. */
export type StartDiscovery = { project_id: string; source_ids: string[]; audience_hint?: string };

export function useStartDiscovery() {
  return useMutation({
    mutationFn: (body: StartDiscovery) =>
      unwrap<DiscoveryView>(
        // the generated type marks a field with a server default as required
        client.POST("/api/discoveries", { body: body as Required<StartDiscovery> }),
      ),
  });
}
```

- [ ] **Step 5: Cancellations are not network errors**

In `web/src/api/client.ts` replace `unwrap`'s comment and `catch`, and `unwrapText`'s signature and `catch`:

```ts
/** A request its caller cancelled: TanStack Query aborts a query nobody watches any more, when
 * the page it was for is left. That is not a network failure (CRL-40). */
function cancelled(error: unknown): boolean {
  return (error as { name?: unknown } | null)?.name === "AbortError";
}

/** The data of an API call, or an ApiError with the message to show. A cancelled request
 * rejects with its AbortError, which TanStack Query treats as a cancellation, not an error. */
export async function unwrap<T>(
  call: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  let result: { data?: T; error?: unknown; response: Response };
  try {
    result = await call;
  } catch (error) {
    if (cancelled(error)) throw error;
    throw new ApiError(0, NETWORK_ERROR);
  }
```

```ts
/** Text or bytes from a route the typed client types as a file: the report and the exports. */
export async function unwrapText(url: string, signal?: AbortSignal): Promise<string> {
  let response: Response;
  try {
    response = await globalThis.fetch(url, { signal });
  } catch (error) {
    if (cancelled(error)) throw error;
    throw new ApiError(0, NETWORK_ERROR);
  }
```

Every read passes TanStack Query's `signal` (R-M17-22):

`web/src/api/reports.ts`, everything after `reportKeys`:

```ts
// Every query passes TanStack Query's `signal`, so leaving the page cancels what it was still
// loading instead of finishing it for nobody (CRL-40).

/** The rendered report with claim ids on (spec §9: default on for HTML in the review UI). */
export function useReportHtml(runId: string, enabled = true) {
  return useQuery({
    queryKey: reportKeys.html(runId),
    queryFn: ({ signal }) => unwrapText(reportUrl(runId, "html", { claimIds: true }), signal),
    staleTime: Infinity,
    enabled,
  });
}

export function useReportJson(runId: string, enabled = true) {
  return useQuery({
    queryKey: reportKeys.json(runId),
    queryFn: async ({ signal }) =>
      JSON.parse(await unwrapText(exportUrl(runId, "report.json"), signal)) as ReportJson,
    staleTime: Infinity,
    enabled,
  });
}

export function useTrace(runId: string) {
  return useQuery({
    queryKey: reportKeys.trace(runId),
    queryFn: ({ signal }) =>
      unwrap<RunTrace>(
        client.GET("/api/runs/{run_id}/trace", { params: { path: { run_id: runId } }, signal }),
      ),
    staleTime: Infinity,
  });
}

export function useFindings(runId: string) {
  return useQuery({
    queryKey: reportKeys.findings(runId),
    queryFn: ({ signal }) =>
      unwrap<Finding[]>(
        client.GET("/api/runs/{run_id}/findings", {
          params: { path: { run_id: runId } },
          signal,
        }),
      ),
    staleTime: Infinity,
  });
}

export function useClaim(runId: string, claimId: string | null) {
  return useQuery({
    queryKey: reportKeys.claim(runId, claimId ?? ""),
    queryFn: ({ signal }) =>
      unwrap<ClaimProvenance>(
        client.GET("/api/runs/{run_id}/claims/{claim_id}", {
          params: { path: { run_id: runId, claim_id: claimId! } },
          signal,
        }),
      ),
    enabled: claimId !== null,
    staleTime: Infinity,
  });
}
```

`web/src/api/runs.ts`, `useRun`'s `queryFn`:

```ts
    queryFn: ({ signal }) =>
      unwrap<RunProgress>(
        client.GET("/api/runs/{run_id}", { params: { path: { run_id: runId } }, signal }),
      ),
```

`web/src/api/projects.ts`, the four `queryFn`s:

```ts
    // useProjects
    queryFn: ({ signal }) => unwrap<ProjectView[]>(client.GET("/api/projects", { signal })),

    // useProject
    queryFn: ({ signal }) =>
      unwrap<ProjectView>(
        client.GET("/api/projects/{project_id}", {
          params: { path: { project_id: projectId! } },
          signal,
        }),
      ),

    // useSources
    queryFn: ({ signal }) =>
      unwrap<SourceView[]>(
        client.GET("/api/projects/{project_id}/sources", {
          params: { path: { project_id: projectId! } },
          signal,
        }),
      ),

    // useRuns
    queryFn: ({ pageParam, signal }) =>
      unwrap<RunPage>(
        client.GET("/api/runs", {
          params: {
            query: {
              project_id: projectId!,
              limit: RUN_PAGE,
              ...(pageParam === null ? {} : { before: pageParam }),
            },
          },
          signal,
        }),
      ),
```

`web/src/api/packs.ts`:

```ts
    // usePacks
    queryFn: ({ signal }) => unwrap<PackSummary[]>(client.GET("/api/packs", { signal })),

    // useResolvedPack
    queryFn: ({ signal }) =>
      unwrap<ResolvedPack>(
        client.GET("/api/packs/{name}/resolved", {
          params: { path: { name: name! }, query: profile ? { profile } : {} },
          signal,
        }),
      ),
```

`web/src/api/system.ts`, `useInfo`:

```ts
    queryFn: ({ signal }) => unwrap<SystemInfo>(client.GET("/api/system/info", { signal })),
```

`web/src/api/discoveries.ts`, `useDiscovery`: the `queryFn` line becomes `queryFn: async ({ signal }): Promise<DiscoveryRead> => {` and the `GET`'s options gain `signal,`:

```ts
          .GET("/api/discoveries/{discovery_id}", {
            params: { path: { discovery_id: discoveryId! } },
            signal,
          })
```

- [ ] **Step 6: The evidence's loading state**

In `web/src/pages/review/ProvenanceTab.tsx`, before `{claim.error ? <ErrorMessage error={claim.error} /> : null}`:

```tsx
      {selectedClaim !== null && claim.isPending ? <Loading what="Loading evidence" /> : null}
```

(`Loading` renders `<p role="status" className="muted">Loading evidence…</p>`; a query that is not enabled is also pending, hence the `selectedClaim` check.)

- [ ] **Step 7: Run the tests**

Run: `cd web && pnpm fmt && pnpm lint && pnpm test`
Expected: lint clean; all pass (204 on the scratch copy), coverage at or above 95% on all four measures (`NewRunPage.tsx` keeps its two uncovered lines from before, 55 and 118); no "intercepted a request" line.

Run: `make e2e`
Expected: 6 passed (the journey's discovery reload still works with no `sources` parameter).

- [ ] **Step 8: Commit**

```bash
cat > "$SCRATCH/m17-task6-commit.txt" <<'EOF'
feat: chosen sources survive a reload; a cancelled request is not a network error; evidence shows a loading state (CRL-40)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git add web/src/pages/new/NewRunPage.tsx web/src/pages/new/ValueStatement.tsx web/src/api/client.ts web/src/api/discoveries.ts web/src/api/runs.ts web/src/api/projects.ts web/src/api/reports.ts web/src/api/packs.ts web/src/api/system.ts web/src/pages/review/ProvenanceTab.tsx web/src/test/render.tsx web/src/pages/new/NewRunPage.test.tsx web/src/pages/new/SourcesPanel.test.tsx web/src/pages/new/ValueStatement.test.tsx web/src/api/client.test.ts web/src/pages/review/ProvenanceTab.test.tsx
git commit -F "$SCRATCH/m17-task6-commit.txt"
```

---

### Task 7: The engine's M16 test leftovers (CRL-40: tests only)

**Files:**
- Test: `engine/tests/testing/test_run_channel.py` (append), `engine/tests/test_return.py` (the lock helpers and the two race tests)

**Interfaces:**
- Consumes: `RunChannel.received_until(payload, *, timeout_s)`; `test_run_channel.py`'s imports (`asyncio`, `psycopg`, `sql`, `to_libpq_url`, `RUN_CHANNEL`); `test_return.py`'s `_completed`, `_review`, `_children`, `_events`, `ACCEPTED`, `Svc`.
- Produces: tests only.

- [ ] **Step 1: `received_until`'s deadline branch**

Append to `engine/tests/testing/test_run_channel.py`:

```python


async def _trickle(pg_url: str, count: int, every_s: float) -> None:
    """One notification every `every_s`, on one connection: never a quiet gap of that length."""
    async with await psycopg.AsyncConnection.connect(to_libpq_url(pg_url), autocommit=True) as c:
        for i in range(count):
            await c.execute(
                sql.SQL("SELECT pg_notify({}, {})").format(
                    sql.Literal(RUN_CHANNEL), sql.Literal(f"n{i}")
                )
            )
            await asyncio.sleep(every_s)


async def test_received_until_ends_at_its_deadline_while_notifications_keep_coming(
    pg_url, run_channel
):
    """The deadline branch (CRL-40): every read returns a notification, so the loop ends because
    the time is up, not because a read came back empty."""
    loop = asyncio.get_running_loop()
    sender = asyncio.create_task(_trickle(pg_url, 40, 0.02))  # 0.8 s of notifications
    started = loop.time()
    got = await run_channel.received_until("never", timeout_s=0.3)
    elapsed = loop.time() - started
    assert got and "never" not in got and got == [f"n{i}" for i in range(len(got))]
    assert 0.3 <= elapsed < 0.3 + 0.2  # it stopped at the deadline, not after the sender
    assert not sender.done()  # notifications were still coming when it returned
    await sender
    rest = await run_channel.received_until("n39")
    assert got + rest == [f"n{i}" for i in range(40)]  # nothing lost across the two calls
```

- [ ] **Step 2: The return-race poll counts only what the holder blocks**

In `engine/tests/test_return.py` replace `_LOCK_WAITERS`, `_until_a_session_waits_for_a_lock` and `_hold` with:

```python
# Sessions that the holder's backend blocks: a waiter on another test's lock in the same
# database does not count (CRL-40).
_BLOCKED_BY = text(
    "SELECT count(*) FROM pg_stat_activity "
    "WHERE datname = current_database() AND :holder = ANY(pg_blocking_pids(pid))"
)


class _Held:
    """The review recording `action` stops inside its transaction, the run's row lock held,
    until `release` is set; `holder` is that session's backend pid."""

    def __init__(self) -> None:
        self.reached, self.release = asyncio.Event(), asyncio.Event()
        self.holder: int | None = None

    async def until_another_session_waits(self, svc: Svc) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 10
        while True:
            async with svc.db.session() as s:
                if await s.scalar(_BLOCKED_BY, {"holder": self.holder}):
                    return
            assert loop.time() < deadline, "no session waited for the run's row lock"
            await asyncio.sleep(0.02)


def _hold(monkeypatch, action: ReviewAction) -> _Held:
    held = _Held()
    real = runs.add_review_event

    async def holding(s, rid, recorded, *args):
        if recorded == action.value:
            held.holder = await s.scalar(text("SELECT pg_backend_pid()"))
            held.reached.set()
            await held.release.wait()
        return await real(s, rid, recorded, *args)

    monkeypatch.setattr(runs, "add_review_event", holding)
    return held
```

and in the two race tests replace `reached, release = _hold(…)` with `held = _hold(…)`, `await reached.wait()` with `await held.reached.wait()`, `await _until_a_session_waits_for_a_lock(svc)` with `await held.until_another_session_waits(svc)` and `release.set()` with `held.release.set()`:

```python
async def test_a_return_that_waits_for_an_accepts_lock_is_refused(svc, monkeypatch):
    pid, run_id = await _completed(svc)
    held = _hold(monkeypatch, ReviewAction.ACCEPT)
    accept = asyncio.create_task(_review(svc, run_id, ReviewAction.ACCEPT, actor="ana"))
    await held.reached.wait()  # the accept holds the row lock and has not committed
    returning = asyncio.create_task(_review(svc, run_id, ReviewAction.RETURN, note="x"))
    await held.until_another_session_waits(svc)  # the return waits for that lock
    held.release.set()
    assert await accept is None
    with pytest.raises(service.ConflictError, match=ACCEPTED):
        await returning  # it decided on the decision committed while it waited
    assert await _children(svc, pid, run_id) == []
    assert await _events(svc, run_id) == [("accept", "ana")]


async def test_an_accept_that_waits_for_a_returns_lock_leaves_the_report_returned(svc, monkeypatch):
    pid, run_id = await _completed(svc)
    held = _hold(monkeypatch, ReviewAction.RETURN)
    returning = asyncio.create_task(_review(svc, run_id, ReviewAction.RETURN, note="x"))
    await held.reached.wait()
    accept = asyncio.create_task(_review(svc, run_id, ReviewAction.ACCEPT, actor="bob"))
    await held.until_another_session_waits(svc)
    held.release.set()
    child = await returning
    assert await accept is None
    assert await _children(svc, pid, run_id) == [str(child)]
    review = (await service.run_progress(svc.db, run_id)).review
    assert review is not None and review.decision == "returned"
    assert review.child_run_id == str(child)
```

- [ ] **Step 3: Run the tests**

Run: `cd engine && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/test_return.py tests/testing/test_run_channel.py --no-cov -q && uv run ruff check . && uv run ruff format --check .`
Expected: all pass; clean. Both changes pin behaviour that stays (R-M17-7), so nothing fails first. Run the timing-dependent file five times to see it is stable (it was, five of five, on the scratch copy):

Run: `cd engine && for i in 1 2 3 4 5; do CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/testing/test_run_channel.py --no-cov -q -p no:cacheprovider | tail -1; done`
Expected: five lines `4 passed`.

- [ ] **Step 4: Commit**

```bash
cat > "$SCRATCH/m17-task7-commit.txt" <<'EOF'
test: received_until's deadline branch; the return-race poll counts only the holder's waiters (CRL-40)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git add engine/tests/testing/test_run_channel.py engine/tests/test_return.py
git commit -F "$SCRATCH/m17-task7-commit.txt"
```

---

### Task 8: Docs

**Files:**
- Modify: `README.md` (a new M17 section before `## Development`), `docs/superpowers/specs/2026-10-12-corelata-v1-design.md` (§7.5, §8.3, §10.1, §10.3, §11, §12), `docs/operator-guide.md` (§5 "Model servers" and "Uploads and the API", §7, §10, §11), `docs/m3-followups.md`, `docs/m4b-followups.md`, `docs/m12-followups.md`, `docs/m14-followups.md`, `docs/m16-followups.md`
- Create: `docs/m17-followups.md`

**Interfaces:**
- Consumes: the behaviour of Tasks 1-7 as their tests pin it (message texts, ruling numbers).
- Produces: documentation only.

- [ ] **Step 1: README**

Insert before `## Development`:

```markdown
## M17: stuck work ends on its own, operator mistakes caught early

CRL-38 to 40, from the 2026-10-19 follow-up triage. A discovery has a deadline,
`worker.discovery_deadline_s` (default 600 s, at least 60): once it is that old and not finished
it is failed with "Discovery did not finish within 10 minutes and was stopped. Start a new
discovery.", whether or not a worker is running. Whoever looks first ends it: the API when the
discovery is read, the worker when it takes the job or finishes, or the worker's minute sweep; a
worker that answers after the deadline does not bring it back. `GET /api/discoveries/{id}`
carries `deadline_at`, and the New run screen keeps asking until 15 s past it, so it shows the
server's reason without a reload; M16's "has not finished after 10 minutes" message remains for
a server that did not end it. Cancelling a run whose worker is gone (its heartbeat
`worker.stalled_after_s` old, or its worker row deleted) ends the run at once and closes its
job; a live worker, however slow, still stops at its next stage, and a worker that was taken for
dead stops at its next write instead of overwriting the cancel (CRL-38). A backend `base_url`
with a query string or a fragment is refused when the configuration loads, so `corelata doctor`
fails its config check with the reason; doctor's suggestions for a missing model ignore case;
migration 0006 indexes the run list by `(project_id, created_at DESC, id DESC)`, which made a
page of a 10,000-run project 70 times faster (CRL-39). The New run screen keeps the chosen
sources in its URL (`?sources=`), so a reload keeps them; leaving a page cancels what it was
loading without showing a network error; the evidence panel says it is loading; the Suggest
request leaves out an empty audience hint; three M16 tests wait for what they mean (CRL-40).
```

- [ ] **Step 2: Spec amendments**

§7.5, after the paragraph that starts `M11 amendment (CRL-25): a conveyor or auditor failure no longer fails the run.`:

```markdown
M17 amendments (CRL-38): a discovery has a deadline, `worker.discovery_deadline_s` (§11) after
its `created_at`, measured on the database's clock. Once a discovery is that old and not
completed or failed, it is failed with `Discovery did not finish within <N minutes> and was
stopped. Start a new discovery.`, by whichever looks first: the API's read
(`GET /discoveries/{id}`, the POST's answer, `corelata status`), the worker's minute sweep, or the
worker itself (a job taken after the deadline makes no model call; the model work stops when the
time is up). Every decision is taken under the discovery's row lock, so whichever transaction
commits first decides, and nothing turns a failed discovery back. A cancel of a run whose job is
`doing` on a worker that is gone (its heartbeat `worker.stalled_after_s` old, or its worker row
deleted: the stalled-job requeue's own test) ends the run as cancelled at once, with the
ending every cancel has, and closes the job as `aborted`; a run a live worker holds still stops at
its next stage boundary. A worker that writes to a run that has ended (it was taken for dead)
stops without writing.
```

§8.3, after the paragraph that starts `M15 amendment: \`review_state\` also holds`:

```markdown
M17 amendment: `run` has the index `ix_run_project_created` on `(project_id, created_at DESC, id
DESC)`, the run list's order (migration 0006, CRL-39).
```

§10.1, after the paragraph that starts `M16 amendment: an accept is final.`:

```markdown
M17 amendments (CRL-38): `GET /discoveries/{id}` (and `POST /discoveries`' answer) carries
`deadline_at` (`created_at` + `worker.discovery_deadline_s`) and fails a discovery past it before
answering (§7.5). `POST /runs/{id}/cancel` ends a run whose worker is gone at once (§7.5).
```

§10.3, after the paragraph that starts `M16 amendments: the New run screen keeps the discovery in its URL`:

```markdown
M17 amendments: the New run screen keeps the chosen sources in its URL as well
(`?project=<id>&sources=<id>,<id>&discovery=<id>`, replace navigation; no `sources` means every
source; ids that are not the project's are dropped; another project drops both), so a reload
keeps them (CRL-40). Discovery polling stops once the discovery is `max(10 minutes,
deadline_at - created_at + 15 s)` old by the server's clock, so the screen shows the server's
failure at the deadline without a reload; the 10-minute message is the fallback for a server that
did not end it (CRL-38). Leaving a page cancels its pending reads, which is not shown as an
error; the Provenance tab says "Loading evidence…" while a claim's evidence loads; the Suggest
request leaves out an empty `audience_hint` (CRL-40).
```

§11: in the YAML block replace `worker: {concurrency: 2, stalled_after_s: 900}` with `worker: {concurrency: 2, stalled_after_s: 900, job_retention_days: 30, discovery_deadline_s: 600}`, and after the paragraph that starts `M14 amendment (CRL-22): \`api.progress_poll_s\``:

```markdown
M17 amendments: `worker.discovery_deadline_s` (default 600, at least 60) is a discovery's deadline
(§7.5, CRL-38). A backend `base_url` with a query string or a fragment is a configuration error
(the request path would land inside the query; keys go in the variable `api_key_env` names), so
`corelata doctor` fails its config check (CRL-39).
```

§12, at the end of the section (after the M5 amendments paragraph):

```markdown
M17 amendment: migration 0006 adds an index (§8.3) and runs inside `migrate` like every other;
a restore of an older backup is migrated by the restore's final `docker compose up -d --wait`.
```

- [ ] **Step 3: Operator guide**

§5 "Model servers": replace the first bullet (`- \`base_url\` ends in \`/v1\`. …`) with:

```markdown
- `base_url` ends in `/v1`, with no query string (`?…`) and no fragment (`#…`): Corelata adds
  `/chat/completions` and `/models` to it, which would land inside a query, so such a URL is a
  configuration error. From inside a container, a server running on the host itself is at
  `host.docker.internal` (the compose file maps it); a server elsewhere is at its own address.
```

§5 "Uploads and the API": replace the paragraph that starts `` `worker.concurrency` (default 2) is how many runs `` with:

```markdown
`worker.concurrency` (default 2) is how many runs one worker executes at once;
`worker.stalled_after_s` (default 900) is how long a worker may be silent before its jobs are
started over, and after which a cancel ends its run at once (section 7);
`worker.job_retention_days` (default 30) is how long failed and cancelled jobs are kept;
`worker.discovery_deadline_s` (default 600, at least 60) is how long a discovery (**Suggest
value**) may take: one not finished by then is failed with "Discovery did not finish within 10
minutes and was stopped. Start a new discovery." (the time it names is this setting), whether or
not a worker is running, and the New run screen shows that. Raise it for a slow model server.
```

§7: after the paragraph that starts `An accept is final:` add:

```markdown
**Cancelling a run whose worker died.** A cancel (`corelata cancel <run-id>`, or **Cancel run**)
stops a running run at its next stage. If the worker running it was killed or its host went
down, the run's job is still marked as taken by that worker: the first cancel only records the
request ("Stopping after the current stage…"). Once the worker has been silent for
`worker.stalled_after_s` (default 900 s), a cancel ends the run at once and closes its job, so it
never runs again: run `docker compose exec api corelata cancel <run-id>` again then (it prints
`run <id> cancelled`). A worker that comes back, or is still alive after all, stops at its next
write and leaves the run cancelled. A worker that is merely slow keeps sending its heartbeat and
is never cancelled under its run.
```

and in **Housekeeping.** replace `it re-queues the jobs of a worker that
stopped responding (after \`worker.stalled_after_s\`) and marks runs whose job was lost as failed.` with `it re-queues the jobs of a worker that
stopped responding (after \`worker.stalled_after_s\`), marks runs whose job was lost as failed, and
fails discoveries older than \`worker.discovery_deadline_s\`.`

§10: after the `**From 0.1.4.**` paragraph add:

```markdown
**From 0.1.5.** Migration 0006 runs inside `migrate` and adds one index to the run table (about a
second per 100,000 runs). A restore of a 0.1.5 backup into 0.1.6 runs it too. A backend
`base_url` with a query string or a fragment, which never worked, now stops `migrate` with the
reason (`docker compose logs migrate`): remove the query and put any key in the variable
`api_key_env` names (section 5). Discoveries older than 10 minutes that are still queued or
running are failed when they are next read, or by the worker's next sweep.
```

§11: replace the row that starts `| The New run screen says "Discovery has not finished after 10 minutes"` with:

```markdown
| The New run screen says "Discovery did not finish within 10 minutes and was stopped" | The discovery passed `worker.discovery_deadline_s`. Check `docker compose ps worker` and `docker compose logs worker` (a stopped worker never took it; a slow model server took too long), then start a new discovery; raise `worker.discovery_deadline_s` for a slow server (section 5). |
| The New run screen says "Discovery has not finished after 10 minutes" | The server did not end the discovery at its deadline, which happens when the database's clock and the API's differ (a separate database host). Reload the page to read it again, or start a new discovery; check both hosts' clocks. |
| A run says "Stopping after the current stage…" and does not move | Its worker died while running it. After `worker.stalled_after_s`, cancel it again: `docker compose exec api corelata cancel <run-id>` (section 7). |
| `migrate` or `doctor` says `base_url: … must not contain a query string` | Write the server's address and path only (`http://models:8000/v1`) and put a key in the variable `api_key_env` names (section 5). |
```

- [ ] **Step 4: Follow-up files**

Append to the end of each item's last line:

- `docs/m3-followups.md`, the item ending `requeue; the restarted execution then sees the flag at once.`: ` — **closed in M17** (CRL-38: a cancel ends such a run at once once its worker has been silent \`worker.stalled_after_s\`; R-M17-2).`
- `docs/m4b-followups.md`, `No loading state while a selected claim's evidence loads.`: ` — **closed in M17** (CRL-40).`
- `docs/m4b-followups.md`, the item ending `the form has no field for it yet.`: ` — **closed in M17** (CRL-40: an empty hint is left out of the request).`
- `docs/m4b-followups.md`, the item ending `maps \`AbortError\` to the network error.`: ` — **closed in M17** (CRL-40).`
- `docs/m12-followups.md`, the item ending `(\`OpenAI/…\` would not suggest \`openai/…\`).`: ` — **closed in M17** (CRL-39).`
- `docs/m14-followups.md`, the item ending `thousands of runs.` (the `GET /api/runs` index): ` — **closed in M17** (CRL-39, migration 0006).`
- `docs/m16-followups.md`, the item ending `deadline in the worker would let the screen say how a stuck discovery will end.`: ` — **closed in M17** (CRL-38: \`worker.discovery_deadline_s\`; R-M17-1).`
- `docs/m16-followups.md`, the item ending `a discovery made on a subset shows next to a full\n  selection.`: ` — **closed in M17** (CRL-40).`
- `docs/m16-followups.md`, the item ending `the timeout case is covered by an empty read.`: ` — **closed in M17** (CRL-40).`
- `docs/m16-followups.md`, the item ending `` `base_url` with a query or a fragment.``: ` — **closed in M17** (CRL-39).`
- `docs/m16-followups.md`, the item ending `pid if tests ever run in parallel against one database.`: ` — **closed in M17** (CRL-40).`
- `docs/m16-followups.md`, `The \`NewRunPage\` race test waits a fixed 300 ms for a write that must not happen.`: ` — **closed in M17** (CRL-40).`

Create `docs/m17-followups.md`:

```markdown
# M17 follow-ups

## Divergences from Coglossa

- The discovery deadline (`worker.discovery_deadline_s`, the read-time expiry, `deadline_at`) —
  Corelata only (Coglossa has no discovery).
- `store.runs.close_abandoned_job`, `service.cancel_run`'s immediate ending and the worker's
  `RunEnded` fence — **backport candidate**: Coglossa's worker uses the same procrastinate
  requeue and the same flag-only cancel.
- `BackendConfig`'s `base_url` validator — **backport candidate**: Coglossa's adapter joins paths
  the same way.
- `doctor._similar` ignoring case — **backport candidate** if Coglossa's doctor suggests models.
- The web client letting an `AbortError` through and every query passing `signal` — **backport
  candidate** for Coglossa's web app.

## Spec deviations

- None. §7.5, §8.3, §10.1, §10.3, §11 and §12 carry M17 amendments.

## Rulings during execution

- How the plan applied R-M17-1 to R-M17-9, and the rulings it added (R-M17-10 to R-M17-25), are
  in its Global Constraints. Number new ones from R-M17-26.

## Should fix soon

- After the first **Cancel run** the screen says "Stopping after the current stage…" and offers no
  second cancel, so a run whose worker died less than `worker.stalled_after_s` before the first
  press needs `corelata cancel` (or the API) again after the threshold (R-M17-17). The screen
  could offer the cancel again once the run has not moved for that long.

## Later

- The fence covers a run that ended (R-M17-16). A run the requeue started over on a second worker
  while the first is still alive (a stalled heartbeat that was not a death) has two executions
  until the first one's next write; comparing `run.attempts` with the execution's own attempt in
  `DbObserver.locked` would stop the first.
- `discovery.created_at` is written by the API process's clock and the deadline is compared with
  the database's `now()` (R-M17-13); a separate database host with a skewed clock moves the
  deadline by the skew. Writing `created_at` from the database (`SELECT now()` in
  `discoveries.create`) would remove it.
- `integrations.coglossa.base_url` is joined with request paths the same way as a backend's
  (R-M17-18) and is not validated.
- `ix_run_project_id` is now redundant with `ix_run_project_created` (R-M17-20); dropping it needs
  the model's `index=True` removed and a migration.
- A run flagged for cancel whose worker dies afterwards still waits for a second cancel or a
  worker; the read-time expiry discoveries have (R-M17-10) has no run counterpart.
```

- [ ] **Step 5: Check nothing else moved**

Run: `make lint && git diff --stat main -- docs/m1-followups.md docs/m2-followups.md docs/m5-followups.md docs/m6-followups.md docs/m7-followups.md docs/m8-followups.md docs/m9-followups.md docs/m10-followups.md docs/m11-followups.md docs/m13-followups.md docs/m15-followups.md engine/corelata/bench`
Expected: lint clean; the diff prints nothing.

Run: `cd api && uv run pytest tests/test_csp_proxy.py::test_the_proxy_sets_the_operator_guides_sample_policy_word_for_word --no-cov -q`
Expected: 1 passed (the guide's nginx sample is untouched).

- [ ] **Step 6: Commit**

```bash
cat > "$SCRATCH/m17-task8-commit.txt" <<'EOF'
docs: M17 README section, spec amendments, operator guide, follow-ups (CRL-38, CRL-39, CRL-40)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UnzFF6M2tdoRX1z8HS5cPK
EOF
git add README.md docs/superpowers/specs/2026-10-12-corelata-v1-design.md docs/operator-guide.md docs/m3-followups.md docs/m4b-followups.md docs/m12-followups.md docs/m14-followups.md docs/m16-followups.md docs/m17-followups.md
git commit -F "$SCRATCH/m17-task8-commit.txt"
```

---

## Final verification (after the whole-branch review)

```bash
make lint
make test-engine    # 941 passed (908 before), coverage >= 95%
make test-api       # 171 passed (169)
make test-web       # 204 passed (194), no "intercepted a request" in the output
make e2e            # 6 passed
make deploy-check
make schema && git status --short schema web/src/api/schema.d.ts   # no output (Task 1 committed it)
grep -n '^version' engine/pyproject.toml                            # still 0.1.5
```

CI must be green on all six jobs (engine, api, web, e2e, deploy, airgap) and `ci-status` before the merge. The airgap job installs the bundle with 0006 at its first site (R-M17-20).

## Live rehearsal (the controller runs this after the merge; not a task)

The host has no `psql`: every SQL step below runs in the dev database's container, `docker exec corelata-dev-postgres-1 psql -U corelata -d <database> -c "…"`.

**A. A discovery whose worker is stopped ends at its deadline, on screen.** A stack by hand, so the worker and the model can be stopped under a running API. From the repository root, `make db-up` and `cd web && pnpm build`. Write `$SCRATCH/m17.yaml` (the deadline and the stall threshold are set low for the rehearsal: configuration, not a product change):

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
storage: {path: $SCRATCH/m17-files}
worker: {concurrency: 2, stalled_after_s: 30, discovery_deadline_s: 60}
```

(write the scratchpad's absolute path for `$SCRATCH` in the file)

```sh
docker exec corelata-dev-postgres-1 psql -U corelata -d postgres -c 'CREATE DATABASE corelata_m17'
export CORELATA_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/corelata_m17
CFG=$SCRATCH/m17.yaml
(cd engine && uv run corelata migrate --config $CFG)            # "... is at revision 0006"
# three terminals, each with CORELATA_DATABASE_URL exported:
cd engine && uv run corelata fake-openai --port 8000                            # A: the model
cd engine && uv run corelata worker --config $CFG                               # B: the worker
cd api && uv run corelata-api --config $CFG --port 8080 --web-dir ../web/dist   # C: the API
```

- [ ] Stop terminal B (Ctrl-C). Open http://127.0.0.1:8080, create a project, upload `docs/examples/varna-port.txt`, **Suggest value**: "Looking for value in the selected sources…". Leave the tab alone. About 60 s after the click, and without a reload, the tab shows the alert "Discovery did not finish within 1 minute and was stopped. Start a new discovery." (the read past the deadline failed it), and the network tab shows no further `GET /api/discoveries/<id>`. `docker exec corelata-dev-postgres-1 psql -U corelata -d corelata_m17 -c "SELECT state, error FROM discovery ORDER BY created_at DESC LIMIT 1"` shows `failed` and the same text.
- [ ] Start terminal B again and watch its log: the discovery's job is taken and does nothing (the row stays `failed`; terminal A logs no model call for it). A second **Suggest value** with the worker running completes as usual.

**B. A run cancelled after its worker was killed.**

- [ ] Start a run on the same source (statement "Varna port capacity expansion matters to shippers"); while it is in `gating` or `drafting`, kill the worker hard: `kill -9 <pid of terminal B's corelata worker>` (`pgrep -f "corelata worker"`). The progress page stops moving. **Cancel run** at once: "Stopping after the current stage…" (the worker's heartbeat is younger than 30 s). `docker exec corelata-dev-postgres-1 psql -U corelata -d corelata_m17 -c "SELECT j.status, now() - w.last_heartbeat AS silent FROM procrastinate_jobs j LEFT JOIN procrastinate_workers w ON w.id = j.worker_id WHERE j.args->>'run_id' = '<run-id>'"` shows `doing` and the silence growing.
- [ ] After 30 s: `(cd engine && uv run corelata cancel <run-id> --config $CFG)` prints `run <run-id> cancelled`; the open progress page shows the run cancelled; the job query shows `aborted`. Start the worker again: the run stays `cancelled`, terminal A logs no call for it.

**C. A bad `base_url` caught by doctor, and sources surviving a reload.**

- [ ] Copy `$CFG` to `$SCRATCH/m17-bad.yaml` with `base_url: "http://127.0.0.1:8000/v1?key=abc"`; `(cd engine && uv run corelata doctor --config $SCRATCH/m17-bad.yaml); echo "exit=$?"` prints one FAIL line for `config` naming `backends.local.base_url` and "must not contain a query string", and a non-zero exit.
- [ ] Upload a second source, untick the first: the URL gains `&sources=<id>`; reload: only the second is ticked; **Suggest value**: the URL has both `sources` and `discovery`; reload again: both survive. Choose another project: both go.
- [ ] Open a completed run's review, select a claim and, while its evidence loads, go back: no "could not be reached" message flashes.
- [ ] Drop the rehearsal database: `docker exec corelata-dev-postgres-1 psql -U corelata -d postgres -c 'DROP DATABASE corelata_m17 WITH (FORCE)'`.

**D. An upgrade of a 0.1.5 install, and a 0.1.5 backup restored (0006).** On a host with Docker (the CRL-1 VM, or locally): download the published v0.1.5 bundle (`gh release download v0.1.5 -R Bonham-Technologies/corelata -p 'corelata-0.1.5-linux-amd64.tar*'`), check it (`sha256sum -c corelata-0.1.5-linux-amd64.tar.sha256`), unpack, `./install.sh`, add `COMPOSE_FILE=compose.yaml:compose.demo.yaml` to `.env`, `docker compose up -d --wait`, start two runs with the guide's demo command and wait for them; `./backup.sh /srv/backups/corelata`. Then follow the guide's section 10 to the M17 bundle (`make bundle`): after `docker compose up -d --wait`, `docker compose exec api corelata migrate` says "at revision 0006", `docker compose exec -T postgres psql -U corelata -d corelata -c "SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_run_project_created'"` shows the index, the two runs list on the New run screen, doctor is all PASS. Then `./restore.sh --yes /srv/backups/corelata/corelata-db-*.dump /srv/backups/corelata/corelata-files-*.tar.gz` (the 0.1.5 backup) in the M17 directory: it ends healthy, the revision is `0006` again, the index exists, the runs are there. Tear down with `docker compose down -v` and remove both images.

**E. Gates and the OpenRouter regression.**

- [ ] `make e2e`: 6 passed.
- [ ] `corelata doctor --config <openrouter.yaml>`: every line PASS.
- [ ] `corelata bench --config <openrouter.yaml> --scenarios real --out bench-m17-real/`: compare with the M16 baseline below; M17 changes nothing a run sends, so a difference is model variance.
- [ ] Fill in the table, add it to Jira CRL-38, CRL-39 and CRL-40 and close them with the rehearsal evidence; then cut 0.1.6.

| Measure | M16 baseline (2026-10-19) | M17 |
|---|---|---|
| `doctor` (OpenRouter) | all PASS | |
| Real set: full agreement | 6/8 | |
| Gate agreement | 7/8 | |
| Rule-failure agreement | 3/3 | |
| Duration | 70 s | |
| Discovery with the worker stopped: failed at 60 s, shown without a reload | n/a | |
| Run cancelled 30 s after its worker was killed: cancelled at once, job aborted | n/a | |
| `doctor` FAIL on a `base_url` with a query | n/a | |
| Chosen sources survive a reload | n/a | |
| 0.1.5 install upgraded, 0.1.5 backup restored: revision 0006, index present | n/a | |

