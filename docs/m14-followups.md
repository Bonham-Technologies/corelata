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
  in its Global Constraints. Number new ones from R-M14-17.
- **R-M14-14 (Task 2 review).** The cancel and shutdown stream tests in
  `api/tests/test_progress.py` wait on observable conditions (`feed.active`, a read that carries
  `cancel_requested`, the LISTEN count in `pg_stat_activity` polled with a bound) instead of fixed
  sleeps, because a fixed sleep on a stalled CI host collapses the asserted event sequence. Cost
  if wrong: two tests a little longer.
- **R-M14-15 (whole-branch review; corrects R-M14-6).** A connection lost inside the savepoint
  is re-raised; only statement errors are swallowed. Before this fix the loss surfaced as
  `PendingRollbackError` at the caller's commit, outside `DB_ERRORS`, and failed the run (the
  worker), answered 500 for `cancel_run` and logged a spurious sweep warning. Now
  `DBAPIError.connection_invalidated` re-raises the `OperationalError`, the job is retried and
  `cancel_run` answers 503.
- **R-M14-16 (air-gap CI on PR #49).** `deploy/tests/smoke.py` read `GET /api/runs` as a list and
  failed the air-gap test once the route answered a page. The plan and the whole-branch review
  named the web app as the route's only in-repo client; the deploy smoke test was the other.
  Fixed by reading `page["runs"]`; `grep -rn "/api/runs"` across the repo finds no further
  consumer outside `web/` and the API tests. Cost if wrong: none; the test now mirrors the client.

## Should fix soon

- ~~The API's LISTEN connection has no keepalive. A half-open socket leaves `ProgressFeed.listening`
  true and the listener blocked in `notifies()` until the OS keepalive (about two hours); streams
  stay correct at heartbeat latency (at most 30 s) and never reconnect. libpq `keepalives_idle`
  on the connection, or `notifies(timeout=)` plus a periodic probe, would detect it.~~ -- **closed in the M14 fix wave**

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
- ~~`GET /api/runs` sorts a project's runs after the `project_id` index; a `(project_id,
  created_at, id)` index would make each page an index range scan once a project holds tens of
  thousands of runs.~~ — **closed in M17** (CRL-39, migration 0006). — CRL-39
- `RunList.test.tsx` renders 520 rows in jsdom to page past 500 (about 1 s); `docs/m10-followups.md`'s
  note on the old ceiling test applies to it.
- A pre-M14 run's stored `report.html` differs from its claim-id re-render by the newline that
  followed `<style>` (R-M14-11); nothing compares them.
- ~~`app.py`'s lifespan wraps `await listener` in `contextlib.suppress(asyncio.CancelledError)`,
  which would also swallow a cancellation of the lifespan task itself, and a listener that died
  with a non-cancel exception would skip `feed.close()` and `db.dispose()`; neither is reachable
  with uvicorn's lifespan protocol and `run()` catching `Exception`.~~ — **closed in M16** (CRL-37). — CRL-37
- The listener's `finally: set_listening(False)` wakes every poller to read just before
  `feed.close()` cancels them; harmless, avoidable by skipping the wake on cancellation.
- ~~`test_an_unreachable_database_is_retried_with_backoff` lets the loop spin on `sleep(0)` and
  floods caplog with WARNING records; the injected sleep could stop after eight calls.~~ — **closed in M16** (CRL-37). — CRL-37
- ~~`RunChannel.received` waits a fixed 0.3 s and returns only after it; `test_notify.py`
  hard-codes 14 announcements for a completed run, coupling the test to the stage count.~~ — **closed in M16** (CRL-37). — CRL-37
- `RunList.test.tsx` has no test for a failed invalidation refetch with rows already loaded (same
  branch as the failed next page); its paging handler restarts from page 1 on an unknown cursor
  instead of failing clearly.
- `service.parse_run_cursor` accepts the looser forms `datetime.fromisoformat` and `uuid.UUID`
  allow (compact ISO, brace or no-hyphen UUIDs); any parsed aware datetime compares correctly, so
  harmless.
- ~~`frameBridge.test.ts` resolves `report.css` from the process cwd rather than `import.meta.url`;~~
  `installFrameBridge` skips the nonce attribute on an empty nonce (unreachable through
  `withBridge`). — **closed in M16** (CRL-37), the stylesheet path; the empty-nonce branch stays unreachable. — CRL-37
- ~~`api/csp_proxy.py` (development only): an upstream connection error propagates as a bare 500
  instead of a 502; no test pins the streaming (a buffered read would pass the suite);~~ the
  forwarding loop does not stop when the client disconnects; the request body is read into memory
  without a cap. — **closed in M16** (CRL-37), the 502 and the streaming test; the disconnect and the body cap stay (development only). — CRL-37
- ~~The full `pnpm test` run prints msw "unhandled request" notices from the Layout, AuditTab,
  ReviewPage and NewRunPage tests; they pre-date M14 (the same notices appear in main's CI logs)
  and should be silenced or mocked.~~ — **closed in M16** (CRL-37: mocked, and an unmocked request now fails its test). — CRL-37
