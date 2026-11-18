# M3 follow-ups

## Divergences from Coglossa

- Product name parameterised (spec §4.3): env `CORELATA_DATABASE_URL`,
  `CORELATA_TEST_DATABASE_URL`, queue `corelata`, tasks `corelata.run`, `corelata.discover`, `corelata.requeue_stalled`, worker
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
- `store/migrate.py`: `connect_error` returns `DatabaseUnavailable(ConfigError)` (new class) so
  `cli_ops.run_command` can exit 1 for an unreachable database and 2 for a configuration error
  through one mechanism (**backport** candidate: Coglossa's `db upgrade` special-cases nothing
  and exits 1 for both).

## Spec deviations

- §8.3 tables: `run_source` (run ↔ source order) and `discovery_source` added; `digests` is a
  JSON column on `run` (spec §5.4 says stage_result rows; the ingesting stage row still lists
  what was digested); a discovery's model calls are a JSON column on `discovery`; `run` gains
  `extra_guidance`, `docx_reference_key`, `gate`, `digests`, `report`, `cancel_requested`,
  `attempts`, `export_error`, `started_at`, `finished_at`; `export` rows record the worker's
  stored renders. Recorded in the spec (§8.3) by Task 11.
- §7.2 `ingesting`: sources are parsed into units when they are uploaded (`ingest`,
  `run --project FILES`), so a bad file is refused immediately; the run's ingesting stage does
  the budget check and the digests, as in M1/M2. Recorded in the spec (§7.2) by Task 11.
- The worker executes with the live configuration; when it differs from the submit-time
  snapshot the run's `config_hash`/`config_snapshot` are replaced and a warning logged, so the
  trace tells the truth about what produced the report.
- `RunRecord.created_at` of a queued run is the submit time (the run row's `created_at`), not
  the time the worker started; `started_at` on the row carries the latter.
- Exports are rendered inside the worker's save transaction from the *stored* record
  (`records.load_record` after flush), not from the in-memory record: JSONB does not preserve
  object key order, so this is the only way the stored files equal a later `corelata export`
  re-render byte for byte (spec §8.4 invariant 5). The row lock is held for the render (local
  CPU work, milliseconds); no model call happens inside it.

## Should fix soon

- ~~`corelata status` and `run_progress` read the run row and every stage row on each call; the
  M4a SSE stream polls it every `api.progress_poll_s`. Fine for one analyst; LISTEN/NOTIFY later.~~ — **closed in M9** (CRL-8) — CRL-8
- ~~Stalled job copies closed as `failed` accumulate in `procrastinate_jobs` (Coglossa has the same
  note); the cleanup SQL is in `docs/operator-guide.md` (Housekeeping) and `docs/m5-followups.md`; nothing runs it automatically.~~ — **closed in M8** (CRL-10) — CRL-10
- `clear_trace` on a restart deletes the dead attempt's rows. If a crashed attempt's partial
  trace turns out to matter for incident analysis, keep the rows with an `attempt` column
  instead of deleting.
- ~~A bad `--source-id` or a missing input file in `corelata run --project` is detected after the
  project was created and earlier files ingested, so a failed command can leave a project and
  sources behind.~~ — **closed in M8** (CRL-12) — CRL-12
- ~~`cancel_run` on a run whose worker died between stage boundaries waits for the stalled-job
  requeue; the restarted execution then sees the flag at once.~~ — **closed in M17** (CRL-38: a cancel ends such a run at once once its worker has been silent `worker.stalled_after_s`; R-M17-2). — CRL-38
- Done in M4a: `add_source` parses in a thread (`asyncio.to_thread`); a `queue.defer` failure in
  `start_run`, `review_run` and `start_discovery` marks the row `failed`
  (`could not queue the …`); the worker's periodic `corelata.sweep_orphans` fails any
  non-terminal run or discovery older than 120 s whose job is neither `todo` nor `doing`.
  ~~Two concurrent returns on one completed run still create two children (no lock across the return).~~ — **closed in M8** (CRL-12) — CRL-12
- ~~A cancel requested after the pipeline's last poll (during the final audit or rendering) is
  not honoured: the run completes with `cancel_requested=true`. Finishing already-complete work
  is the intended behaviour; the Progress screen should show both flags.~~ — CRL-15
- `cli_ops._queue_run` and `_queue_discover` repeat the gather-sources block (still open). ~~`--parent-run`
  without `--project` was silently ignored (unlike `--source-id`).~~ — **closed in M8** (CRL-12) — CRL-12
- A source deleted before the worker runs (no delete path exists in v1) would leave its
  discovery `created` forever.
- `store/runs.py`: `replace_claims` raises a raw `IntegrityError` on duplicate claim ids
  (prevented upstream by `ReportBody` validation); it flushes once per claim; `add_source`
  strips NUL by hand although `SafeText` already does; `add_llm_calls` dumps the whole record in
  JSON mode (fragile if a datetime field is ever added to `LLMCallRecord`).
- `doctor`: an empty served-model list yields the fix text `set models.X.name to one of: ` with
  nothing after the colon. — **closed**, verified 2026-10-18: `doctor.py` `_model` says "set models.<key>.name to a served id; see the server's model list" when nothing is similar.
- Test gaps noted by reviewers: the cascade test omits the claim, export, review_event and
  discovery tables; the invariant-5 byte comparison is tested only for a run without a
  reference document; `run_command`'s raw `DB_ERRORS` branch, the `DocxExportError` branch,
  `export --out` pointing at a file, non-UUID ids, and several doctor branches (factory errors,
  `OutputTruncatedError`, structured-probe `BackendError`, prompts FAIL, database
  `ConfigError`) are untested; three doctor tests do not clear `CORELATA_DATABASE_URL`.
- `run_source.source_id` cascades on source delete and `load_sources` numbers sources by
  position; use `ON DELETE RESTRICT` (migration) and `src{ordinal}` later. No delete path exists
  in v1.
- ~~A parent run may belong to a different project (`--parent-run` is not checked against the
  project).~~ — **closed in M8** (CRL-12) — CRL-12
- ~~Export files are orphaned in storage after a restart (`clear_trace` deletes rows, not files).~~ — **closed in M8** (CRL-6) — CRL-6
- Surrogate sanitising in `strip_nul` is a backport candidate for Coglossa.

## Later

- M4a: delivered; the mapping is in `api/corelata_api/routes/`.
- M5: delivered (deploy/).
