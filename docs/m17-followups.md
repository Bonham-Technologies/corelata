# M17 follow-ups

## Divergences from Coglossa

- The discovery limits (`worker.discovery_deadline_s`, `worker.discovery_start_deadline_s`, the
  read-time expiry, `deadline_at`, the discovery's queue priority) — Corelata only (Coglossa has
  no discovery).
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
- R-M17-26 (two limits): `worker.discovery_deadline_s` (600) is the work limit, from
  `started_at`; the new `worker.discovery_start_deadline_s` (3600, at least 60) is the start
  limit, from `created_at` while no worker has claimed the discovery, failed with "Discovery did
  not start within 60 minutes and was stopped: the worker was stopped or busy with runs. Start a
  new discovery."; the first claim records `started_at` as the database's `now()`, and a
  redelivered job keeps it and gets only what is left of the work limit.
- R-M17-27 (`deadline_at` follows the state): `started_at` + work limit once claimed (ended or
  not), else `created_at` + start limit; the screen's ceiling is the server's clock 15 s past the
  latest read's `deadline_at`, and at least 10 minutes after `created_at`.
- R-M17-28 (waiting text): while `created`, the Suggestions panel says "Waiting for the worker to
  start the discovery…" (polite live region); once `running`, "Looking for value in the selected
  sources…".
- R-M17-29 (priority): a discovery's job is deferred with procrastinate priority 1
  (`service.DISCOVERY_PRIORITY`); runs and the periodic tasks keep 0, and procrastinate 3.10's
  `procrastinate_fetch_job_v2` orders by `priority DESC, id ASC`, so the next free slot takes a
  discovery ahead of waiting runs.
- R-M17-30 (the review's minors): the worker's budget stop logs WARNING `discovery <id> stopped
  at its deadline after <n> s`; an agent error is kept even when the finish commits after the work
  limit, and only an expired budget, or an answer whose `started_at` is past the work limit, gets
  the deadline text.

## Should fix soon

- ~~After the first **Stop writing…** (M18's name for Cancel run) the screen says "Stopping after
  the current step…" and offers no second cancel, so a run whose worker died less than
  `worker.stalled_after_s` before the first press needs `corelata cancel` (or the API) again
  after the threshold, or waits until a running worker requeues its job and the requeued job ends
  it (R-M17-17). The screen could offer the cancel again once the run has not moved for that
  long.~~ Fixed by CRL-49: the progress carries `worker_gone`, and the screen offers **Stop now…**. — CRL-49

## Later

- ~~The fence covers a run that ended (R-M17-16). A run the requeue started over on a second worker
  while the first is still alive (a stalled heartbeat that was not a death) has two executions
  until the first one's next write; comparing `run.attempts` with the execution's own attempt in
  `DbObserver.locked` would stop the first.~~
  Fixed by CRL-56: `DbObserver.locked` raises `AttemptSuperseded` when the run's attempts differ
  from the execution's own, and the stopped execution logs at info. The requeue hands the same
  job (same id) to the second worker, and procrastinate acknowledges by id alone, so the stopped
  execution's acknowledgement would have deleted the job the second worker holds and the orphan
  sweep would then have failed the run under it. `worker.app._fence_acks` wraps procrastinate's
  `finish_job` and `retry_job`: a job 'doing' under another attempt count (the requeue adds one)
  is another worker's and is left as it is, so neither the acknowledgement nor the retry on a
  database error touches it. Ruling (CRL-56): the model
  calls a fenced execution made after its last write are dropped, not recorded on the run as an
  abandoned attempt's (that would add a trace field); the stop's log line gives their count and
  tokens, and `docs/trace-format.md` says so. — CRL-56
- ~~`discovery.created_at` is written by the API process's clock and the start limit is compared
  with the database's `now()` (R-M17-13); a separate database host with a skewed clock moves the
  start limit by the skew. Writing `created_at` from the database (`SELECT now()` in
  `discoveries.create`) would remove it. The work limit has no such skew: the claim writes
  `started_at` from the database's `now()` (R-M17-26).~~ Fixed by CRL-53: `discoveries.create`
  writes `created_at` from the database's `now()`, and the sweep's grace for discoveries is
  measured by it too. — CRL-53
- ~~A long `?sources=` can exceed a reverse proxy's request-line limit on a reload: at about 200
  sources, nginx's default `large_client_header_buffers` (8 kB) answers 414. Writing the shorter
  of the chosen and the unchosen set (with a marker for which) would keep it short.~~ Fixed by
  CRL-54: the page writes `pick=i.<token>...` or `pick=x.<token>...`, whichever is shorter, with
  a 6-character token per source (`web/src/lib/selection.ts`); old `sources=` links still load.
  Ruling (CRL-54): a source the project gains after the URL was written (another tab, a
  colleague) is chosen on reload under `x` and left out under `i`, so it depends on whether more
  or fewer than half were chosen. An upload on the page itself always joins the choice. Two
  sources whose tokens collide (about one project of 500 sources in 550 000) are chosen together. — CRL-54
- ~~`finished_at` on the worker's deadline failures uses the Python clock (`utcnow()`), while the
  expiry (`discoveries.expire`) uses the database's `now()`; the two can differ by the same skew.~~
  Fixed by CRL-53: every `finished_at` the worker writes on a discovery is the database's `now()`. — CRL-53
- ~~`integrations.coglossa.base_url` is joined with request paths the same way as a backend's
  (R-M17-18) and is not validated.~~ Fixed by CRL-55: both share one validator (an http(s) URL
  with a host, no query or fragment, no path Corelata adds itself). — CRL-55
- ~~`ix_run_project_id` is now redundant with `ix_run_project_created` (R-M17-20); dropping it is a
  later schema change: remove the model's `index=True` and add a migration.~~ Fixed by CRL-58:
  migration 0007 drops it. — CRL-58
- A run flagged for cancel whose worker dies afterwards still waits for a second cancel or a
  worker; the read-time expiry discoveries have (R-M17-10) has no run counterpart.
- The requeue skips a job a cancel closed by matching procrastinate's error text "invalid status
  to retry" (`worker.app._RETRY_REFUSED`, procrastinate 3.10 to 3.12). A procrastinate upgrade
  must keep `engine/tests/worker/test_orphan_cancel.py::test_the_requeue_skips_a_job_a_cancel_closed_after_it_looked`
  green; if the text changes, the requeue raises again.
- ~~A live worker that was taken for dead stops at its next write, but its job acknowledgement then
  fails (the cancel closed the job) and procrastinate and asyncio log an error ("Task exception
  was never retrieved"). Harmless, and noisy in `docker compose logs worker`.~~ Fixed by CRL-56:
  the acknowledgement of a job already closed or deleted is skipped, with an INFO line. — CRL-56
- ~~The in-flight stage's model calls and token usage are not kept for a run that was taken for
  dead: the fence stops the worker before it writes them, so that spend is invisible in the run.~~ Ruled by CRL-56:
  they are dropped, `docs/trace-format.md` says so, and the stop's log line gives their count and
  tokens. — CRL-56
- The cancel's job lookup uses `args->>'run_id'` on `procrastinate_jobs`; procrastinate's `lock`
  column (`run:<id>`) could replace it.
- The plan's mixed-directory pytest command (`engine/tests` and `api/tests` in one invocation)
  errors with "fixture 'services' not found" in `api/tests/test_app.py`: an existing quirk of two
  packages' fixtures in one session, not caused by M17. Run each package on its own
  (`make test-engine`, `make test-api`).
