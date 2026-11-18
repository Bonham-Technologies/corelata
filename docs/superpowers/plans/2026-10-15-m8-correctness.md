# M8 Correctness and Operations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the seven correctness and operator tickets from the follow-up triage (Jira CRL-6, CRL-7, CRL-10, CRL-11, CRL-12, CRL-13, CRL-14): no orphaned files on a long-lived volume, a restore that refuses to destroy what it does not know, automatic job-history cleanup with an indexed orphan sweep, a Coglossa integration that fails clearly and is checked by the doctor, runs that cannot name a parent in another project or be returned twice, DOCX header logos that survive the marking rebuild, and a digest ladder that never forces an undigestible source, never starves the gate, and always records its own failure.

**Architecture:** Seven independent changes in the engine and `deploy/`, each small, each with its own tests. One new alembic migration (`0003`) adds two expression indexes on `procrastinate_jobs`. No API route shapes change, no schema export changes, no web changes. Nothing changes the trace format.

**Tech Stack:** Python 3.12, pydantic 2, SQLAlchemy 2 async, alembic, procrastinate, httpx, python-docx + lxml, pytest with a real Postgres; bash for `deploy/`.

**Spec:** `docs/superpowers/specs/2026-10-12-corelata-v1-design.md` — §5.3 (Coglossa adapter), §5.4 (digests), §7.2 (state machine, review return), §7.4 (writer budget), §7.5 (error handling, ladder), §8.3 (tables), §10.1 (review), §12 (backup, restore). The tickets' text is in Jira CRL-6/7/10/11/12/13/14 and the triage report they came from.

## Global Constraints

- 95% branch coverage for the engine package (`--cov-fail-under=95`), `filterwarnings = ["error"]`; `ruff check` and `ruff format --check` clean (line length 100). The API suite (`make test-api`) must stay green where a task touches `service.py` or the Coglossa client.
- Engine tests that touch Postgres run against the dev database (`make db-up`; `CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres`); the test database is built by running the real migrations, so a new revision is applied automatically.
- The vendored procrastinate schema `0001_procrastinate_3_10_0.sql` is never edited; `env.py`'s autogenerate filter never touches procrastinate tables. New indexes on `procrastinate_jobs` live in a new revision and are dropped by its downgrade.
- `deploy/` changes are limited to `restore.sh`, `backup.sh` (one comment), `tests/test-restore.sh`, `tests/airgap-test.sh` (step 6b wording) and the operator guide; shellcheck via `make deploy-check` must pass.
- CLI exit codes unchanged: user errors (`ConfigError`, `IngestError`, `PackError`, `StorageError`, `NotFoundError`, `ConflictError`, `InvalidRequestError`, `OSError`) exit 2.
- Commit messages end with the two attribution lines the session uses; write them to a uniquely named scratchpad file and `git commit -F FILE`. Never `git stash`.
- Rulings (record in the SDD ledger, carried here):
  - R-M8-1: a completed run can be **returned once**; a second return is a 409 `ConflictError` that names the existing child. To iterate again, return the child.
  - R-M8-2: job history is purged daily (cron `17 3 * * *`) with `worker.job_retention_days` (default 30); the guide keeps the manual SQL for operators who want it now.
  - R-M8-3: the Coglossa client caps the export body at 50 MB; a configured but unset `api_key_env` is a 409 at request time and a FAIL in the doctor; the doctor's `coglossa` check probes `GET {base}/api/health` when probing is on.
  - R-M8-4: the writer-overflow rule never forces a source whose largest unit exceeds `digest_chunk_tokens` (the writer's safety cut covers it); forced-digest sources stay in the gate's full-text pool; a `StageError` from the ladder's re-digest is recorded on the overflowing stage. New scenario fixtures for conveyor-routed findings stay parked (the synthetic auditor cannot be steered to fail a conveyor-routed rule).
  - R-M8-5: `restore.sh` refuses to run when the database holds schemas other than `public` and the system ones, naming them; there is no override flag in this version.

## Review Focus

1. **A worker restart must leave exactly one set of export files** in storage for the run and keep `runs/<id>/reference.docx`. Pinned in Task 1 (`test_a_crashed_execution_removes_the_dead_attempts_exports`).
2. **A restore against a database with an extra schema must stop before anything is stopped or dropped**, naming the schema. Pinned in Task 2 (`restore.sh: a foreign schema is refused before anything is stopped`).
3. **A second return of the same completed run must be a 409**, and a parent in another project must be a 422, with nothing created. Pinned in Task 5 (`test_a_run_can_be_returned_once`, `test_parent_run_must_be_in_the_same_project`).
4. **A header logo wrapped in `mc:AlternateContent` must survive the marking rebuild while every old word in the header goes.** Pinned in Task 6 (`test_docx_alternate_content_logo_survives_the_marking`).
5. **When the only way to fit the writer's budget is to digest a source with a unit larger than the chunk size, the run must still complete** (the writer withholds the tail) rather than fail at ingest; and a re-digest that fails after an overflow must appear in the trace as a failed stage. Pinned in Task 7 (`test_writer_overflow_skips_undigestible_sources`, `test_a_failed_redigest_after_overflow_is_recorded`).

---

## File structure

| Path | Responsibility |
|---|---|
| `engine/corelata/storage.py` | `LocalStorage.delete_prefix` also removes emptied parent directories. |
| `engine/corelata/worker/execute.py` | `_begin` returns the dead attempt's export keys; `execute` deletes them after the claim commits. |
| `engine/corelata/store/runs.py` | `export_keys(s, run_id)`, `return_event(s, run_id)`. |
| `engine/corelata/service.py` | parent-project check, one-return rule, `_create_run_in(s, ...)` used inside the review transaction. |
| `engine/corelata/cli_ops.py`, `engine/corelata/cli.py` | validate ids and input files before creating the project; `--parent-run` needs `--project`. |
| `deploy/restore.sh`, `deploy/tests/test-restore.sh`, `deploy/backup.sh` | foreign-schema refusal, tighter stub tests, a comment on streaming. |
| `engine/corelata/store/migrations/versions/0003_job_args_indexes.py` | expression indexes on `procrastinate_jobs (args->>'run_id')` and `(args->>'discovery_id')`. |
| `engine/corelata/worker/sweep.py`, `engine/corelata/worker/app.py`, `engine/corelata/config.py` | `purge_closed_jobs`, the daily periodic task, `WorkerConfig.job_retention_days`. |
| `engine/corelata/integrations/coglossa.py`, `engine/corelata/doctor.py` | `InvalidURL`, missing key, body cap, the `coglossa` doctor check. |
| `engine/corelata/render/docx.py` | keep any run child that holds a picture. |
| `engine/corelata/stages/digest.py`, `stages/context.py`, `stages/gate.py`, `pipeline.py` | undigestible sources, `forced_digests`, recorded re-digest failure. |
| `docs/operator-guide.md`, `docs/m8-followups.md`, README, earlier follow-up files | docs. |

---

### Task 1: Orphaned storage files (CRL-6)

`runs.clear_trace` deletes the dead attempt's export rows but not its files, and `LocalStorage.delete_prefix` leaves empty parent directories behind.

**Files:**
- Modify: `engine/corelata/storage.py` (`LocalStorage.delete_prefix`)
- Modify: `engine/corelata/store/runs.py` (new `export_keys`)
- Modify: `engine/corelata/worker/execute.py` (`_Inputs`, `_begin`, the caller)
- Test: `engine/tests/test_storage.py`, `engine/tests/worker/test_execute.py`, `engine/tests/test_service.py`

**Interfaces:**
- Produces: `runs.export_keys(s, run_id) -> list[str]`; `_Inputs.stale_export_keys: list[str]`.

- [ ] **Step 1: Failing storage test**

Append to `engine/tests/test_storage.py`:

```python
def test_delete_prefix_removes_emptied_parent_directories(tmp_path):
    storage = LocalStorage(tmp_path / "files")
    storage.put("projects/p1/sources/s1/a.txt", b"a")
    storage.put("projects/p1/sources/s2/b.txt", b"b")
    storage.delete_prefix("projects/p1/sources/s1/")
    assert (tmp_path / "files/projects/p1/sources/s2/b.txt").is_file()
    assert not (tmp_path / "files/projects/p1/sources/s1").exists()
    storage.delete_prefix("projects/p1/sources/s2/")
    assert not (tmp_path / "files/projects").exists()  # every emptied parent went too
    assert (tmp_path / "files").is_dir()  # never the root
    storage.put("runs/r1/report.md", b"r")
    storage.delete_prefix("runs/r1/report.md")  # a single file: its directory goes when empty
    assert not (tmp_path / "files/runs").exists()
```

Run: `cd engine && uv run pytest tests/test_storage.py -q -k emptied`
Expected: FAIL (`projects/p1/sources/s1`'s parents still exist).

- [ ] **Step 2: Prune emptied parents**

`engine/corelata/storage.py`, replace `delete_prefix`:

```python
    def delete_prefix(self, prefix: str) -> None:
        """Remove a stored file or a whole key prefix, then every directory that is left empty
        above it (never the root): a rejected upload or a restarted run leaves nothing behind."""
        target = self._path(prefix.rstrip("/"))
        try:
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
            parent = target.parent
            while parent != self.root and parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
                parent = parent.parent
        except OSError as e:
            raise StorageError(f"cannot delete {prefix}: {e.strerror or e}") from e
```

Run: `cd engine && uv run pytest tests/test_storage.py -q`
Expected: PASS. The existing `test_add_source_rejects_bad_uploads_and_leaves_no_file` in `tests/test_service.py` now also sees no empty `projects/<id>/sources` directory; add to it: `assert not list((tmp_path / "files").rglob("sources"))`.

- [ ] **Step 3: Failing worker test**

Append to `engine/tests/worker/test_execute.py` (imports `runs`, `datetime`, `UTC`, `StageResultRow` already exist there):

```python
async def test_a_crashed_execution_removes_the_dead_attempts_exports(services, fake_backend):
    run_id = await submit(services)
    stale = f"runs/{run_id}/report.md"
    async with services.db.session() as s, s.begin():
        run = await runs.get_run(s, run_id, lock=True)
        run.state, run.attempts = "drafting", 1
        services.storage.put(stale, b"from the attempt that died")
        await runs.add_export(s, run_id, "report.md", stale, b"from the attempt that died")
        services.storage.put(f"runs/{run_id}/leftover.bin", b"no row points at me")
    await drain(services)
    progress = await service.run_progress(services.db, run_id)
    assert progress.state is RunState.COMPLETED and progress.attempts == 2
    files = sorted(p.name for p in (services.storage.root / "runs" / str(run_id)).iterdir())
    async with services.db.session() as s:
        rows = sorted(e.name for e in await runs.list_exports(s, run_id))
    assert files == rows  # exactly the second attempt's exports, nothing from the first
    assert services.storage.get(stale) != b"from the attempt that died"
```

Run: `cd engine && uv run pytest tests/worker/test_execute.py -q -k dead_attempts`
Expected: FAIL (`leftover.bin` survives).

- [ ] **Step 4: Delete the dead attempt's files after the claim commits**

`engine/corelata/store/runs.py`, next to `list_exports`:

```python
async def export_keys(s: AsyncSession, run_id: uuid.UUID) -> list[str]:
    """Storage keys of the run's export files (what clear_trace forgets on disk)."""
    return list(await s.scalars(select(ExportRow.storage_key).where(ExportRow.run_id == run_id)))
```

`engine/corelata/worker/execute.py`: add `stale_export_keys: list[str]` to `_Inputs` (after `created_at`); in `_begin`, before `await runs.clear_trace(s, run_id)` add `stale = await runs.export_keys(s, run_id)` (and `stale: list[str] = []` before the `if run.attempts:` block), and pass `stale_export_keys=stale` where `_Inputs(...)` is built. In the caller, right after `_begin` returns a non-`None` `inputs` (the claim has committed), add:

```python
    # The dead attempt's files: its rows are gone (clear_trace), its directory must follow, but
    # never the reference document, which the new attempt renders with.
    prefix = f"runs/{run_id}/"
    keep = {inputs.docx_reference_key} if inputs.docx_reference_key else set()
    for key in inputs.stale_export_keys:
        if key not in keep:
            with contextlib.suppress(StorageError):
                svc.storage.delete_prefix(key)
    for path in _stray_files(svc.storage, prefix, keep):
        with contextlib.suppress(StorageError):
            svc.storage.delete_prefix(path)
```

`_stray_files` needs a listing the `Storage` protocol does not have. Add to the protocol and to `LocalStorage`:

```python
    def list_keys(self, prefix: str) -> list[str]: ...
```

```python
    def list_keys(self, prefix: str) -> list[str]:
        """Keys under a prefix, sorted; [] when nothing is stored there."""
        target = self._path(prefix.rstrip("/"))
        if not target.is_dir():
            return []
        return sorted(
            str(p.relative_to(self.root)).replace("\\", "/")
            for p in target.rglob("*")
            if p.is_file()
        )
```

and in `execute.py`:

```python
def _stray_files(storage: Storage, prefix: str, keep: set[str]) -> list[str]:
    return [k for k in storage.list_keys(prefix) if k not in keep]
```

(With `list_keys`, `stale_export_keys` becomes redundant: every file under `runs/<id>/` except the reference is stray after `clear_trace`. Keep the field out and delete `_stray_files(...)` only; drop `export_keys` from Step 4 if unused. Pick one and remove the other; the test must pass either way.) Add `test_list_keys` to `tests/test_storage.py`: two files under `runs/r1/`, one elsewhere; `list_keys("runs/r1/") == ["runs/r1/a.md", "runs/r1/b.md"]`; `list_keys("nope/") == []`.

Run: `cd engine && uv run pytest tests/worker tests/test_storage.py tests/test_service.py -q`
Expected: PASS.

- [ ] **Step 5: Full suite, lint, commit**

```bash
cd engine && uv run pytest -q && uv run ruff check . && uv run ruff format --check .
git add engine/corelata/storage.py engine/corelata/store/runs.py engine/corelata/worker/execute.py engine/tests/test_storage.py engine/tests/worker/test_execute.py engine/tests/test_service.py
git commit -F FILE   # "fix: a restarted run and a rejected upload leave no files behind (CRL-6)"
```

---

### Task 2: restore.sh refuses foreign schemas; tighter stub tests (CRL-7)

**Files:**
- Modify: `deploy/restore.sh`, `deploy/backup.sh`, `deploy/tests/test-restore.sh`, `docs/operator-guide.md` (sections 8 and 9)

- [ ] **Step 1: Failing stub tests**

In `deploy/tests/test-restore.sh`, extend the stub's `case` with two lines before the `pg_restore -l` line:

```bash
  *"pg_namespace"*) printf '%s\n' ${STUB_SCHEMAS:-} ;;
  *"compose stop api worker"*) exit "${STUB_STOP_RC:-0}" ;;
```

Append these tests before the final `echo "restore.sh: all tests passed"`:

```bash
if STUB_SCHEMAS="analytics audit" restore "$work/db.dump" "$work/files.tar.gz"; then fail "foreign schemas were accepted"; fi
grep -q "^error: the database holds schemas restore.sh does not manage: analytics audit" "$work/out" || fail "schemas: $(cat "$work/out")"
! grep -q "stop" "$work/log" || fail "schemas: services were stopped"
echo "ok - a foreign schema is refused before anything is stopped"

if STUB_FILES_RC=3 restore "$work/db.dump" "$work/files.tar.gz"; then fail "a clear failure was ignored"; fi
grep -q "^error: the old files could not be cleared" "$work/out" || fail "clear fail: $(cat "$work/out")"
[ "$(tail -n1 "$work/log")" = "compose up -d" ] || fail "clear fail: not restarted: $(cat "$work/log")"
echo "ok - a failure to clear the old files says so and restarts Corelata"

if STUB_STOP_RC=1 restore "$work/db.dump" "$work/files.tar.gz"; then fail "a stop failure was ignored"; fi
grep -q "^error: could not stop Corelata; nothing was changed" "$work/out" || fail "stop fail: $(cat "$work/out")"
! grep -q "DROP SCHEMA" "$work/log" || fail "stop fail: the database was touched"
echo "ok - a stop failure changes nothing"

restore "$work/db.dump" "$work/files.tar.gz" || fail "ordering: $(cat "$work/out")"
order=$(grep -n -e "^compose stop api worker" -e "^compose exec -T postgres sh -c" -e "^compose run --rm --no-deps -T --entrypoint sh worker" -e "^compose up -d --wait$" "$work/log" | cut -d: -f1 | tr '\n' ' ')
sorted=$(printf '%s\n' $order | sort -n | tr '\n' ' ')
[ "$order" = "$sorted" ] || fail "ordering: stop, database, files, up are not in order: $order"
[ "$(grep -c "^compose exec -T postgres sh -c" "$work/log")" = 1 ] || fail "ordering: the database restore ran more than once"
echo "ok - stop, database, files, up happen once and in that order"
```

Run: `deploy/tests/test-restore.sh`
Expected: FAIL at "foreign schemas were accepted".

- [ ] **Step 2: The refusal and the comment**

`deploy/restore.sh`, after the `pg_restore -l` validation and before the confirmation prompt, add:

```bash
# restore.sh empties and refills `public` only. Anything else in the database (an extension's
# schema, a reporting schema someone added) would be left out of step with the restored data,
# so it is refused here, before anything is stopped.
foreign=$(docker compose exec -T postgres psql -X -q -t -A -U corelata -d corelata -c \
  "SELECT nspname FROM pg_namespace WHERE nspname NOT IN ('public', 'pg_catalog', 'information_schema') AND nspname NOT LIKE 'pg_%' ORDER BY 1" 2>/dev/null | tr '\n' ' ' | sed 's/ *$//')
[ -z "$foreign" ] || die "the database holds schemas restore.sh does not manage: $foreign; move or drop them, then run the restore again"
```

`deploy/backup.sh`: after the `docker compose run ... tar ... >"$files.partial"` line add the comment `# The files volume streams through a one-shot container; a very large volume is slow on some hosts (a bind mount read directly would be faster but ties the script to the volume's location).`

`docs/operator-guide.md` section 9, after the paragraph starting "The database dump comes first": add `restore.sh works on the `public` schema only, which is where everything Corelata and its job queue create lives. If the database holds other schemas (an extension you added, a reporting schema), the script refuses before stopping anything and names them; move or drop them first.` Section 8, after the crontab paragraph: `The files backup streams the volume through a one-shot container, which is slow for very large volumes (many gigabytes); run it off-hours.`

Run: `deploy/tests/test-restore.sh && make deploy-check` (from the repo root)
Expected: all `ok -` lines and shellcheck clean. If shellcheck objects to the unquoted `$order` word-splitting in the test, use `printf '%s\n' "$order"` with `tr ' ' '\n'` instead.

- [ ] **Step 3: Commit**

```bash
git add deploy/restore.sh deploy/backup.sh deploy/tests/test-restore.sh docs/operator-guide.md
git commit -F FILE   # "fix: restore.sh refuses foreign schemas; restore stub tests pin ordering and failures (CRL-7)"
```

---

### Task 3: Job-history purge and the orphan-sweep indexes (CRL-10)

**Files:**
- Create: `engine/corelata/store/migrations/versions/0003_job_args_indexes.py`
- Modify: `engine/corelata/config.py` (`WorkerConfig`), `engine/corelata/worker/sweep.py`, `engine/corelata/worker/app.py`
- Modify: `docs/operator-guide.md` (Housekeeping), `deploy/tests/airgap-test.sh` (step 6b comment), `engine/corelata.example.yaml` (worker section, if it lists worker keys)
- Test: `engine/tests/worker/test_sweep.py`, `engine/tests/worker/test_app.py`, `engine/tests/store/test_migrations.py`, `engine/tests/test_config.py`

**Interfaces:**
- Produces: `sweep.purge_closed_jobs(db, *, retention_days: int) -> int`; `app.TASK_PURGE_JOBS = "corelata.purge_jobs"`, periodic id `purge-jobs`; `WorkerConfig.job_retention_days: int = Field(30, ge=1)`.

- [ ] **Step 1: Failing tests**

Append to `engine/tests/worker/test_sweep.py`:

```python
async def _insert_closed_job(db, *, task: str, status: str, age_days: int) -> None:
    async with db.session() as s, s.begin():
        await s.execute(
            text(
                "INSERT INTO procrastinate_jobs (queue_name, task_name, args, status, scheduled_at) "
                "VALUES ('corelata', :task, '{}'::jsonb, CAST(:status AS procrastinate_job_status), "
                "now() - make_interval(days => :age))"
            ),
            {"task": task, "status": status, "age": age_days},
        )


async def _job_count(db, task: str) -> int:
    async with db.session() as s:
        return await s.scalar(
            text("SELECT count(*) FROM procrastinate_jobs WHERE task_name = :task"), {"task": task}
        )


async def test_purge_removes_old_closed_jobs_and_nothing_else(services):
    db = services.db
    await _insert_closed_job(db, task="old.failed", status="failed", age_days=60)
    await _insert_closed_job(db, task="old.cancelled", status="cancelled", age_days=31)
    await _insert_closed_job(db, task="recent.failed", status="failed", age_days=1)
    await _insert_closed_job(db, task="old.todo", status="todo", age_days=60)  # still waiting
    removed = await purge_closed_jobs(db, retention_days=30)
    assert removed == 2
    assert await _job_count(db, "old.failed") == 0 and await _job_count(db, "old.cancelled") == 0
    assert await _job_count(db, "recent.failed") == 1 and await _job_count(db, "old.todo") == 1
    assert await purge_closed_jobs(db, retention_days=30) == 0  # idempotent


async def test_purge_ages_an_unscheduled_job_by_its_last_event(services):
    db = services.db
    await _insert_job(db, task="eventful", args={}, status="failed")
    async with db.session() as s, s.begin():
        await s.execute(
            text(
                "INSERT INTO procrastinate_events (job_id, type, at) SELECT id, 'failed', "
                "now() - interval '45 days' FROM procrastinate_jobs WHERE task_name = 'eventful'"
            )
        )
    assert await purge_closed_jobs(db, retention_days=30) == 1
```

Add `from corelata.worker.sweep import purge_closed_jobs, sweep_orphans` to the imports. In `engine/tests/worker/test_app.py`, rename `test_both_periodic_tasks_are_registered` to `test_the_periodic_tasks_are_registered` and add `assert (worker_app.TASK_PURGE_JOBS, "purge-jobs") in registered`; add:

```python
async def test_purge_jobs_task_uses_the_configured_retention(services, monkeypatch):
    seen = {}

    async def fake_purge(database, *, retention_days):
        seen["db"], seen["days"] = database, retention_days
        return 0

    monkeypatch.setattr(worker_app, "purge_closed_jobs", fake_purge)
    context = SimpleNamespace(additional_context={worker_app.SERVICES_KEY: services})
    await worker_app.purge_jobs_task(context, timestamp=0)
    assert seen == {"db": services.db, "days": services.cfg.worker.job_retention_days}
```

In `engine/tests/store/test_migrations.py` add a test that the two indexes exist after upgrade (use the `db` fixture and `SELECT indexname FROM pg_indexes WHERE tablename = 'procrastinate_jobs'`; assert `ix_procrastinate_jobs_run_id` and `ix_procrastinate_jobs_discovery_id` are present), and in `engine/tests/test_config.py` that `WorkerConfig().job_retention_days == 30` and `job_retention_days: 0` is rejected.

Run: `cd engine && uv run pytest tests/worker/test_sweep.py tests/worker/test_app.py tests/store tests/test_config.py -q`
Expected: FAIL (import error, missing indexes, unknown field).

- [ ] **Step 2: Config, purge, task, migration**

`engine/corelata/config.py`, `WorkerConfig`:

```python
class WorkerConfig(_Strict):
    concurrency: int = Field(2, ge=1)  # runs one worker process executes at the same time
    # re-queue jobs of a worker silent this long; a run is minutes, not hours (spec §16)
    stalled_after_s: float = Field(900.0, ge=30)
    # closed jobs (failed, cancelled, aborted) older than this are deleted daily; the worker
    # deletes succeeded ones itself (CRL-10)
    job_retention_days: int = Field(30, ge=1)
```

`engine/corelata/worker/sweep.py`, append:

```python
# The operator guide's housekeeping statement (CRL-10): closed jobs older than the retention,
# aged by scheduled_at or, when a job was never scheduled, by its last event. Periodic defers
# reference jobs, so they go first.
_PURGE = text(
    "WITH old AS ("
    "  SELECT j.id FROM procrastinate_jobs j"
    "  WHERE j.status IN ('succeeded', 'failed', 'cancelled', 'aborted')"
    "    AND COALESCE(j.scheduled_at,"
    "          (SELECT max(e.at) FROM procrastinate_events e WHERE e.job_id = j.id))"
    "        < now() - make_interval(days => :days)),"
    "gone AS (DELETE FROM procrastinate_periodic_defers WHERE job_id IN (SELECT id FROM old)) "
    "DELETE FROM procrastinate_jobs WHERE id IN (SELECT id FROM old) RETURNING id"
)


async def purge_closed_jobs(db: Database, *, retention_days: int) -> int:
    """Delete closed jobs older than `retention_days`; returns how many went."""
    async with db.session() as s, s.begin():
        removed = len(list(await s.scalars(_PURGE, {"days": retention_days})))
    if removed:
        log.info("purged %d closed job(s) older than %d days", removed, retention_days)
    return removed
```

`engine/corelata/worker/app.py`: add `TASK_PURGE_JOBS = "corelata.purge_jobs"` beside the other task names, import `purge_closed_jobs`, and after `sweep_orphans_task`:

```python
@app.periodic(cron="17 3 * * *", periodic_id="purge-jobs")
@app.task(name=TASK_PURGE_JOBS, queue=QUEUE, pass_context=True)
async def purge_jobs_task(context: JobContext, timestamp: int) -> None:
    svc = _services(context)
    await purge_closed_jobs(svc.db, retention_days=svc.cfg.worker.job_retention_days)
```

New `engine/corelata/store/migrations/versions/0003_job_args_indexes.py`:

```python
"""expression indexes for the orphan sweep (CRL-10)

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-15 12:00:00.000000

The sweep matches procrastinate_jobs.args->>'run_id' and ->>'discovery_id' against run and
discovery ids every minute; without an index that is a scan of the job table per candidate row.
procrastinate's own schema (revision 0001) is never edited; these indexes live here and go with
this revision's downgrade.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_procrastinate_jobs_run_id ON procrastinate_jobs ((args->>'run_id'))"
    )
    op.execute(
        "CREATE INDEX ix_procrastinate_jobs_discovery_id "
        "ON procrastinate_jobs ((args->>'discovery_id'))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_procrastinate_jobs_discovery_id")
    op.execute("DROP INDEX IF EXISTS ix_procrastinate_jobs_run_id")
```

Check `engine/tests/store/test_migrations.py` and `engine/corelata/store/migrate.py` for anything that pins the head revision string (`"0002"`); `test_app.py::test_worker_refuses_an_unmigrated_database` monkeypatches `MigrationState(None, "0002")` as a stale state and still passes. Update any head literal to `"0003"`.

Docs: `docs/operator-guide.md` Housekeeping: replace "Clear old ones now and then, for example monthly from cron:" with "The worker deletes closed jobs older than `worker.job_retention_days` (default 30) every night; to clear them by hand, or with a different window, run:" and keep the SQL. `deploy/tests/airgap-test.sh` step 6b comment: add "(the worker runs the same statement nightly; this step proves the statement itself)". `engine/corelata.example.yaml`: add `job_retention_days: 30` under `worker:` with a comment, if the file has a `worker:` section; otherwise skip.

Run: `cd engine && uv run pytest tests/worker tests/store tests/test_config.py -q`
Expected: PASS.

- [ ] **Step 3: Full suite, lint, commit**

```bash
cd engine && uv run pytest -q && uv run ruff check . && uv run ruff format --check .
git add engine/corelata/config.py engine/corelata/worker/sweep.py engine/corelata/worker/app.py engine/corelata/store/migrations/versions/0003_job_args_indexes.py engine/tests/worker/test_sweep.py engine/tests/worker/test_app.py engine/tests/store/test_migrations.py engine/tests/test_config.py docs/operator-guide.md deploy/tests/airgap-test.sh engine/corelata.example.yaml
git commit -F FILE   # "feat: purge closed jobs nightly and index the orphan sweep (CRL-10)"
```

---

### Task 4: Coglossa integration hardening (CRL-11)

**Files:**
- Modify: `engine/corelata/integrations/coglossa.py`, `engine/corelata/doctor.py`
- Modify: `docs/operator-guide.md` (Coglossa section), spec §5.3 one sentence
- Test: `engine/tests/integrations/test_coglossa.py`, `engine/tests/test_doctor.py`, `api/tests/test_coglossa.py`

**Interfaces:**
- Produces: `CoglossaClient(cfg, *, transport=None, timeout_s=30.0, max_bytes=MAX_EXPORT_BYTES)`; `MAX_EXPORT_BYTES = 50 * 1024 * 1024`; `run_doctor(..., coglossa_transport: httpx.AsyncBaseTransport | None = None)`; a doctor check named `coglossa`.

- [ ] **Step 1: Failing client tests**

Append to `engine/tests/integrations/test_coglossa.py`:

```python
async def test_fetch_export_fails_clearly_when_the_key_variable_is_unset(monkeypatch):
    monkeypatch.delenv("COGLOSSA_KEY", raising=False)
    client = _client(lambda request: httpx.Response(200, json={}), api_key_env="COGLOSSA_KEY")
    with pytest.raises(CoglossaFetchError) as e:
        await client.fetch_export("run-1", user=None)
    assert e.value.status == 409
    assert "COGLOSSA_KEY is not set" in str(e.value)


async def test_fetch_export_reports_an_invalid_base_url():
    integration = CoglossaIntegration(base_url="http://[bad")
    client = CoglossaClient(integration, transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    with pytest.raises(CoglossaFetchError) as e:
        await client.fetch_export("run-1", user=None)
    assert e.value.status == 502 and "cannot reach Coglossa" in str(e.value)


async def test_fetch_export_refuses_an_oversized_body():
    body = b"x" * 2048

    def handler(request):
        return httpx.Response(200, content=body, headers={"content-type": "application/json"})

    client = _client(handler)
    client.max_bytes = 1024
    with pytest.raises(CoglossaFetchError) as e:
        await client.fetch_export("run-1", user=None)
    assert e.value.status == 502 and "larger than 1024 bytes" in str(e.value)
```

Run: `cd engine && uv run pytest tests/integrations -q`
Expected: FAIL (no 409, `InvalidURL` escapes, no cap).

- [ ] **Step 2: The client**

`engine/corelata/integrations/coglossa.py`: add `MAX_EXPORT_BYTES = 50 * 1024 * 1024` after `USER_HEADER`; give `__init__` a `max_bytes: int = MAX_EXPORT_BYTES` parameter stored as `self.max_bytes`; change `_headers`:

```python
    def _headers(self, user: str | None) -> dict[str, str | bytes]:
        headers: dict[str, str | bytes] = {"Accept": "application/json"}
        if self.cfg.api_key_env:
            key = os.environ.get(self.cfg.api_key_env)
            if not key:
                raise CoglossaFetchError(
                    f"integrations.coglossa.api_key_env {self.cfg.api_key_env} is not set in the "
                    "API's environment",
                    status=409,
                )
            headers["Authorization"] = f"Bearer {key}"
        ...
```

and the fetch:

```python
        try:
            async with (
                httpx.AsyncClient(transport=self.transport, timeout=self.timeout_s) as c,
                c.stream("GET", url, headers=self._headers(user)) as response,
            ):
                if response.status_code == 200:
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > self.max_bytes:
                            raise CoglossaFetchError(
                                f"Coglossa run {run_id}: the export is larger than "
                                f"{self.max_bytes} bytes; export it by hand and upload it",
                                status=502,
                            )
                        chunks.append(chunk)
                    return b"".join(chunks)
                await response.aread()
        except (httpx.HTTPError, httpx.InvalidURL) as e:
            raise CoglossaFetchError(
                f"cannot reach Coglossa at {self.cfg.base_url}: {str(e) or type(e).__name__}",
                status=502,
            ) from e
        if response.status_code == 404: ...   # unchanged from here
```

(`_headers` is called inside the `try`, so its 409 must not be swallowed: `CoglossaFetchError` is not an `httpx` error, so it passes through.) `_detail(response)` still works after `aread()`.

Run: `cd engine && uv run pytest tests/integrations -q && cd ../api && CORELATA_TEST_DATABASE_URL=postgresql://corelata:corelata@127.0.0.1:55433/postgres uv run pytest tests/test_coglossa.py -q`
Expected: PASS.

- [ ] **Step 3: Failing doctor tests**

Append to `engine/tests/test_doctor.py`:

```python
async def test_coglossa_not_configured_is_a_pass(tmp_path, server, monkeypatch):
    monkeypatch.delenv("CORELATA_DATABASE_URL", raising=False)
    report = await run_doctor(_config(tmp_path, server.base_url), probe=False)
    check = _by_name(report)["coglossa"]
    assert check.status is CheckStatus.PASS and "not configured" in check.message


async def test_coglossa_reachable_and_unreachable(tmp_path, server, monkeypatch):
    monkeypatch.delenv("CORELATA_DATABASE_URL", raising=False)
    path = _config(tmp_path, server.base_url, integrations={"coglossa": {"base_url": "http://coglossa.test"}})
    ok = httpx.MockTransport(lambda r: httpx.Response(200, json={"status": "ok", "version": "1"}))
    report = await run_doctor(path, probe=True, coglossa_transport=ok)
    assert _by_name(report)["coglossa"].status is CheckStatus.PASS

    def down(request):
        raise httpx.ConnectError("refused")

    report = await run_doctor(path, probe=True, coglossa_transport=httpx.MockTransport(down))
    check = _by_name(report)["coglossa"]
    assert check.status is CheckStatus.FAIL and "cannot reach" in check.message
    report = await run_doctor(path, probe=False, coglossa_transport=httpx.MockTransport(down))
    assert _by_name(report)["coglossa"].status is CheckStatus.PASS  # no probe: configured only


async def test_coglossa_missing_key_variable_fails(tmp_path, server, monkeypatch):
    monkeypatch.delenv("CORELATA_DATABASE_URL", raising=False)
    monkeypatch.delenv("COGLOSSA_KEY", raising=False)
    path = _config(
        tmp_path, server.base_url,
        integrations={"coglossa": {"base_url": "http://coglossa.test", "api_key_env": "COGLOSSA_KEY"}},
    )
    report = await run_doctor(path, probe=False)
    check = _by_name(report)["coglossa"]
    assert check.status is CheckStatus.FAIL and "COGLOSSA_KEY" in check.fix
```

Add `import httpx` to the test imports. Check first whether `load_config` turns an unset `api_key_env` into a `ConfigError` (then `run_doctor` returns the single FAIL `config` check and the test must assert that instead): read `validate_config`'s "error" handling in `config.py`; if errors raise, change the third test to assert `report.checks[0].name == "config"` and `"COGLOSSA_KEY" in report.checks[0].message`, and have the doctor check cover only the reachability case.

Run: `cd engine && uv run pytest tests/test_doctor.py -q -k coglossa`
Expected: FAIL (no `coglossa` check; unknown kwarg).

- [ ] **Step 4: The doctor check**

`engine/corelata/doctor.py`: `run_doctor` gains `coglossa_transport: httpx.AsyncBaseTransport | None = None`; after the storage check append `checks.append(await _aguard("coglossa", lambda: _coglossa(cfg, probe, coglossa_transport)))`; add:

```python
async def _coglossa(
    cfg: CorelataConfig, probe: bool, transport: httpx.AsyncBaseTransport | None
) -> DoctorCheck:
    integration = cfg.integrations.coglossa
    if integration is None:
        return _check("coglossa", CheckStatus.PASS, "integrations.coglossa not configured")
    if integration.api_key_env and not os.environ.get(integration.api_key_env):
        return _check(
            "coglossa",
            CheckStatus.FAIL,
            f"environment variable {integration.api_key_env} is not set",
            f"set {integration.api_key_env} in the API's environment (.env) or remove api_key_env",
        )
    if not probe:
        return _check("coglossa", CheckStatus.PASS, f"configured: {integration.base_url}")
    url = integration.base_url.rstrip("/") + "/api/health"
    try:
        async with httpx.AsyncClient(transport=transport, timeout=10.0) as c:
            response = await c.get(url)
    except (httpx.HTTPError, httpx.InvalidURL) as e:
        return _check(
            "coglossa",
            CheckStatus.FAIL,
            f"cannot reach Coglossa at {integration.base_url}: {str(e) or type(e).__name__}",
            "check integrations.coglossa.base_url and that Coglossa is up",
        )
    if response.status_code != 200:
        return _check(
            "coglossa", CheckStatus.FAIL, f"{url} answered {response.status_code}",
            "check integrations.coglossa.base_url: it should be Coglossa's root URL",
        )
    return _check("coglossa", CheckStatus.PASS, f"Coglossa at {integration.base_url} answers")
```

Add `import os` and `import httpx` to the doctor's imports. Docs: operator guide Coglossa section, add `corelata doctor` reports the integration: unset key variable, unreachable or wrong URL.` Spec §5.3: append `The client caps an export at 50 MB and refuses to send a request when the configured key variable is unset (M8).`

Run: `cd engine && uv run pytest tests/test_doctor.py tests/integrations -q && uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/corelata/integrations/coglossa.py engine/corelata/doctor.py engine/tests/integrations/test_coglossa.py engine/tests/test_doctor.py docs/operator-guide.md docs/superpowers/specs/2026-10-12-corelata-v1-design.md
git commit -F FILE   # "fix: Coglossa fetch fails clearly on a bad URL, an unset key or an oversized export; doctor checks it (CRL-11)"
```

---

### Task 5: Parent project, one return, validated CLI inputs (CRL-12)

**Files:**
- Modify: `engine/corelata/service.py` (`_create_run`, `review_run`), `engine/corelata/store/runs.py` (`return_event`), `engine/corelata/cli_ops.py` (`_queue_run`, `_queue_discover`), `engine/corelata/cli.py` (`_run`)
- Test: `engine/tests/test_service.py`, `engine/tests/test_cli_ops.py`, `api/tests/test_reviews.py` (or wherever the review route tests live; grep `ReviewAction.RETURN` under `api/tests`)

- [ ] **Step 1: Failing service tests**

Append to `engine/tests/test_service.py` (reuse the `svc` fixture and `_set_state`):

```python
async def test_parent_run_must_be_in_the_same_project(svc, tmp_path):
    pid, other = await svc.project(), await svc.project(name="other")
    sid = await svc.source(pid)
    parent = await svc.run(pid, [sid])
    with pytest.raises(service.InvalidRequestError, match="another project"):
        await svc.run(other, [await svc.source(other)], parent_run_id=parent)
    async with svc.db.session() as s:
        assert len(await runs.list_runs(s, other)) == 0


async def test_a_run_can_be_returned_once(svc):
    pid = await svc.project()
    sid = await svc.source(pid)
    run_id = await svc.run(pid, [sid])
    await _set_state(svc.db, run_id, "completed")
    child = await service.review_run(
        svc.db, svc.storage, svc.queue, svc.cfg, svc.prompts, run_id, ReviewAction.RETURN,
        note="Tighten the scope", actor="alice",
    )
    with pytest.raises(service.ConflictError, match=str(child)):
        await service.review_run(
            svc.db, svc.storage, svc.queue, svc.cfg, svc.prompts, run_id, ReviewAction.RETURN,
            note="Again", actor="bob",
        )
    async with svc.db.session() as s:
        children = [r for r in await runs.list_runs(s, pid) if r.parent_run_id == run_id]
    assert len(children) == 1
```

Check the `Svc.project` signature for a name argument and `runs.list_runs`' name (the existing tests at ~line 461 list runs by project; use the same call). Run: `cd engine && uv run pytest tests/test_service.py -q -k "same_project or returned_once"`
Expected: FAIL.

- [ ] **Step 2: Service**

`engine/corelata/store/runs.py`, after `add_review_event`:

```python
async def return_event(s: AsyncSession, run_id: uuid.UUID) -> ReviewEvent | None:
    """The run's `return` event, if it was returned already (R-M8-1: one return per run)."""
    return await s.scalar(
        select(ReviewEvent)
        .where(ReviewEvent.run_id == run_id, ReviewEvent.action == ReviewAction.RETURN.value)
        .order_by(ReviewEvent.at)
        .limit(1)
    )
```

(import `ReviewAction` from `corelata.schema` if not already imported there; otherwise compare with the literal `"return"`.)

`engine/corelata/service.py`, `_create_run`: replace the parent check with

```python
            if req.parent_run_id is not None:
                parent = await runs.get_run(s, req.parent_run_id)
                if parent.project_id != req.project_id:
                    raise InvalidRequestError(
                        f"parent run {req.parent_run_id} belongs to another project"
                    )
```

`review_run`: inside the first (locked) transaction, after the `COMPLETED` check and before the `ACCEPT` branch, add

```python
        if action is ReviewAction.RETURN:
            earlier = await runs.return_event(s, run_id)
            if earlier is not None:
                raise ConflictError(
                    f"run {run_id} was already returned; its rerun is {earlier.child_run_id}. "
                    "Return that run to iterate again"
                )
```

The row lock makes two concurrent returns serialise: the second sees the first's event once the first commits... except the first's event is written in a later transaction. Move the event write into the same flow as the child: after `_create_run` returns `child`, the second `async with db.session()` block writes the event; a concurrent second return that passed the check before that commit would still create a second child. Close that window by writing a placeholder event inside the locked transaction (`child_run_id=None`) and updating it after the child exists:

```python
        event = await runs.add_review_event(s, run_id, action.value, note, actor, None)
        event_id = event.id
    ...child = await _create_run(...)
    async with db.session() as s, s.begin():
        await runs.set_review_child(s, event_id, child)
```

with `runs.set_review_child(s, event_id, child_run_id)` doing `UPDATE review_event SET child_run_id = :child WHERE id = :id`. If `_create_run` raises, delete the placeholder in an `except BaseException` block (`runs.delete_review_event(s, event_id)`) and re-raise. `return_event` then finds the placeholder and refuses the second return even mid-flight.

`engine/corelata/cli.py` `_run`: after the `--source-id needs --project` check add `if args.parent_run and args.project is None: return _usage("--parent-run needs --project")`. `engine/corelata/cli_ops.py` `_queue_run` and `_queue_discover`: move `ids = [_id(s, "source") for s in args.source_id]` and a new `for path in [*args.inputs, *args.coglossa_export]: _read(path)` (existence check; `_read` raises `IngestError` for a missing file) before `async def go`, so a bad id or path fails before `create_project`. Keep `go` using the precomputed `ids`.

Run: `cd engine && uv run pytest tests/test_service.py tests/test_cli_ops.py tests/test_cli.py -q`
Expected: PASS. Add to `tests/test_cli_ops.py`: `test_parent_run_needs_project` (exit 2, message) and `test_a_bad_source_id_creates_no_project` (`run --project fresh --source-id not-a-uuid` exits 2 and `SELECT count(*) FROM project WHERE name = 'fresh'` is 0, via the test file's existing DB access pattern).

- [ ] **Step 3: API suite, lint, commit**

Run `make test-api` (the review route tests); add one API test where a second return answers 409 if a review route test file exists. Then:

```bash
cd engine && uv run pytest -q && uv run ruff check . && uv run ruff format --check .
git add engine/corelata/service.py engine/corelata/store/runs.py engine/corelata/cli_ops.py engine/corelata/cli.py engine/tests/test_service.py engine/tests/test_cli_ops.py api/tests
git commit -F FILE   # "fix: a parent run must share the project, a run is returned once, CLI inputs are checked before anything is created (CRL-12)"
```

---

### Task 6: Header logos inside AlternateContent (CRL-13)

**Files:**
- Modify: `engine/corelata/render/docx.py` (`_logo_runs`)
- Test: `engine/tests/render/test_docx.py`
- Modify: `docs/m2-followups.md` (close the item)

- [ ] **Step 1: Failing test**

Append to `engine/tests/render/test_docx.py`:

```python
MC = 'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"'
ALTERNATE_LOGO = (
    f"<w:p {nsdecls('w', 'wp', 'a', 'pic', 'r', 'v')} {MC}>"
    "<w:r><w:rPr><w:b/></w:rPr><w:t>OLD MARKING</w:t>"
    '<mc:AlternateContent><mc:Choice Requires="wps"><w:drawing><wp:inline>'
    '<wp:extent cx="914400" cy="228600"/><wp:docPr id="7" name="Logo"/><a:graphic>'
    '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
    '<pic:pic><pic:blipFill><a:blip r:embed="rId9"/></pic:blipFill></pic:pic>'
    "</a:graphicData></a:graphic></wp:inline></w:drawing></mc:Choice>"
    '<mc:Fallback><w:pict><v:shape><v:imagedata r:id="rId9"/></v:shape></w:pict></mc:Fallback>'
    "</mc:AlternateContent></w:r></w:p>"
)


def test_docx_alternate_content_logo_survives_the_marking(tmp_path):
    path = _reference_with_header(tmp_path, ALTERNATE_LOGO)
    header = _open(render_docx(make_report(), PACK, SOURCES, reference=path)).sections[0].header
    xml = header._element.xml
    assert "OLD MARKING" not in xml and _header_text(header) == "UNCLASSIFIED"
    assert "mc:AlternateContent" in xml and "<pic:pic" in xml and "<w:drawing" in xml
    assert [p.text for p in header.paragraphs] == ["UNCLASSIFIED"]
```

Run: `cd engine && uv run pytest tests/render/test_docx.py -q -k alternate`
Expected: FAIL (`mc:AlternateContent` is stripped from the run).

- [ ] **Step 2: Keep whatever holds a picture**

`engine/corelata/render/docx.py`, replace `_KEEP_IN_RUN` and `_logo_runs`:

```python
def _logo_runs(root: etree._Element) -> list[etree._Element]:
    """The part's picture runs (logos), stripped of any text; text boxes are never logos. A run
    child stays when it is the run's properties or when it holds a picture, whatever wraps it
    (`w:drawing`, `w:pict`, `mc:AlternateContent`, `w:object`)."""
    runs = [r for r in _RUNS(root) if _IMAGE(r) and not _TEXT_BOX(r)]
    for run in runs:
        for child in list(run):
            if child.tag != qn("w:rPr") and not _IMAGE(child):
                run.remove(child)
    return runs
```

Run: `cd engine && uv run pytest tests/render -q && uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
Expected: PASS (the existing logo and text-box tests still hold: `_IMAGE(child)` on a `w:t` is empty; a text-box run is excluded before the loop).

- [ ] **Step 3: Docs and commit**

`docs/m2-followups.md`, the AlternateContent item: append ` — **closed in M8** (a run child stays when it holds a picture; CRL-13).`

```bash
git add engine/corelata/render/docx.py engine/tests/render/test_docx.py docs/m2-followups.md
git commit -F FILE   # "fix: header logos wrapped in AlternateContent or an object survive the marking rebuild (CRL-13)"
```

---

### Task 7: Digest overflow: undigestible sources, the gate's pool, the recorded re-digest (CRL-14)

**Files:**
- Modify: `engine/corelata/stages/digest.py` (`writer_overflow`), `engine/corelata/stages/context.py` (`forced_digests`), `engine/corelata/stages/gate.py` (`select_units`), `engine/corelata/pipeline.py` (`_digest`, the overflow handler)
- Test: `engine/tests/stages/test_digest.py`, `engine/tests/stages/test_gate.py`, `engine/tests/test_pipeline.py`
- Modify: `docs/m2-followups.md` (close three items), spec §7.4 one sentence

**Interfaces:**
- Produces: `StageContext.forced_digests: set[str]` (sources digested for the writer's budget only); `writer_overflow(ctx)` never returns a source with a unit over `digest_chunk_tokens`.

- [ ] **Step 1: Failing tests**

Append to `engine/tests/stages/test_digest.py`:

```python
def test_writer_overflow_skips_undigestible_sources(make_ctx, make_config):
    cfg = make_config(
        pipeline={"digest_threshold_tokens": 2000, "digest_chunk_tokens": 500, "writer_unit_budget_tokens": 500}
    )
    a = text_source("src1", *["a" * 500] * 2)  # 400 tokens, two units of 200
    b = text_source("src2", "b" * 1500)  # 600 tokens in ONE unit: no chunk can hold it
    c = text_source("src3", *["c" * 500] * 2)  # 400
    ctx = make_ctx(a, b, c, cfg=cfg)
    forced = writer_overflow(ctx)
    assert "src2" not in forced  # the largest, but undigestible: the writer's cut covers it
    assert forced == ["src1", "src3"]  # ties: document order
    check_unit_sizes(ctx, forced)  # and what is forced can be digested
```

Append to `engine/tests/stages/test_gate.py`:

```python
def test_select_units_keeps_sources_digested_only_for_the_writer(make_ctx):
    ctx = make_ctx(text_source("src1", "Varna port."), text_source("src2", "Varna capacity."))
    section = DigestSection(summary="s", unit_refs=["src2/u1"])
    ctx.digests = {"src2": Digest(source_id="src2", sections=[section])}
    ctx.forced_digests = {"src2"}  # under the threshold; digested for the writer's budget only
    assert select_units(ctx, 10_000) == ["src1/u1", "src2/u1"]
```

Append to `engine/tests/test_pipeline.py`:

```python
async def test_a_failed_redigest_after_overflow_is_recorded(run, make_config, fake_backend):
    # after the halving, digest_chunk_tokens is 500 and this 1500-byte unit (600 tokens) can no
    # longer be digested: the re-digest's StageError must show in the trace as the gating
    # stage's second failure, not vanish
    cfg = make_config(pipeline={"digest_threshold_tokens": 1000, "digest_chunk_tokens": 1000})
    big = text_source("src1", "b" * 1500, *[f"Paragraph {i} on Varna port." for i in range(30)])
    fake_backend.script("gate", ContextOverflowError("too long"))
    rec = await run(big, cfg=cfg)
    assert rec.state is RunState.FAILED and "digest_chunk_tokens" in (rec.error or "")
    gating = [s for s in rec.stages if s.stage == "gating"]
    assert [s.ok for s in gating] == [False, False]
    assert "digest_chunk_tokens" in (gating[-1].error or "")


async def test_forced_digest_sources_still_feed_the_gate(run, make_config, fake_backend):
    cfg = make_config(pipeline={"digest_threshold_tokens": 2000, "writer_unit_budget_tokens": 500})
    a = text_source("src1", *[f"Varna port capacity note {i} for shippers." for i in range(12)])
    b = text_source("src2", *[f"Rail brief {i} says Varna port matters to shippers." for i in range(12)])
    rec = await run(a, b, cfg=cfg)
    assert rec.state is RunState.COMPLETED
    gate_calls = [r for r in fake_backend.requests if '"task": "gate"' in r.messages[1].content]
    assert any("src2/u" in r.messages[1].content for r in gate_calls)  # full text, not only the digest
```

Check the arithmetic against `_paragraphs`-style sizes in that file (a 44-byte line is 18 tokens; 12 lines are 216; two sources are 432 under a 500 budget: raise the line count until `rec.digests` is non-empty in a quick local run and assert `rec.digests` too). Run: `cd engine && uv run pytest tests/stages/test_digest.py tests/stages/test_gate.py tests/test_pipeline.py -q -k "undigestible or only_for_the_writer or redigest or forced_digest"`
Expected: FAIL.

- [ ] **Step 2: The three fixes**

`engine/corelata/stages/digest.py`:

```python
def _digestible(source: Source, chunk_tokens: int, bytes_per_token: float) -> bool:
    return all(estimate_tokens(u.text, bytes_per_token) <= chunk_tokens for u in source.units)


def writer_overflow(ctx: StageContext) -> list[str]:
    """Spec §7.4: ids of sources under the digest threshold that must be digested anyway so the
    rest fit pipeline.writer_unit_budget_tokens. The largest goes first (document order breaks
    a tie), until the remaining non-digested sources fit or none remain. A source with a unit no
    digest request can hold is never forced: the writer's safety cut handles it (R-M8-4)."""
    per_token = ctx.bytes_per_token("writer")
    budget = ctx.cfg.pipeline.writer_unit_budget_tokens
    chunk = ctx.cfg.pipeline.digest_chunk_tokens
    full = {s.id: source_tokens(s, per_token) for s in ctx.sources if not needs_digest(ctx, s)}
    candidates = {sid: n for sid, n in full.items() if _digestible(ctx.index_source(sid), chunk, per_token)}
    forced: list[str] = []
    while candidates and sum(full.values()) > budget:
        largest = max(candidates, key=candidates.__getitem__)
        forced.append(largest)
        del candidates[largest], full[largest]
    return forced
```

`StageContext` has no `index_source`; add to `context.py`:

```python
    def source(self, source_id: str) -> Source:
        return next(s for s in self.sources if s.id == source_id)
```

and use `ctx.source(sid)`; also add the field `forced_digests: set[str] = field(default_factory=set)` with the comment `# sources under the threshold digested only so the writer's budget holds (spec §7.4); the gate still reads their full text`.

`engine/corelata/stages/gate.py` `select_units`: replace `if source.id in ctx.digests: continue` with `if source.id in ctx.digests and source.id not in ctx.forced_digests: continue`.

`engine/corelata/pipeline.py` `_digest`:

```python
    async def _digest(self) -> None:
        forced = writer_overflow(self.ctx)
        self.ctx.forced_digests = set(forced)
        self.ctx.digests = await run_digests(self.ctx, force=forced)
        self.record.digests = list(self.ctx.digests.values())
```

and in `stage()`'s overflow handler, replace `await self._digest()` with:

```python
                try:
                    await self._digest()
                except StageError as redigest:
                    await self._record_stage(state, iteration, self.now(), error=str(redigest))
                    raise
```

Run: `cd engine && uv run pytest tests/stages tests/test_pipeline.py tests/test_scenarios.py tests/bench -q`
Expected: PASS, including the shipped scenario `many-sources-writer-budget` (its digested set is unchanged: both forced sources are digestible).

- [ ] **Step 3: Docs, full suite, commit**

`docs/m2-followups.md`: mark the three items (`writer_overflow picks the largest...`, `Writer-budget forced digests ... gate's full-text pool`, `Pre-existing ... bypasses the stage's own recording`) ` — **closed in M8** (CRL-14)`; leave the scenario-fixtures item with ` — parked: the synthetic auditor cannot be steered to fail a conveyor-routed rule`. Spec §7.4 writer row: append `A source whose largest unit exceeds digest_chunk_tokens is never forced into a digest; the writer's unit cut covers it, and the gate keeps reading forced-digest sources in full (M8).`

```bash
cd engine && uv run pytest -q && uv run ruff check . && uv run ruff format --check .
git add engine/corelata/stages/digest.py engine/corelata/stages/context.py engine/corelata/stages/gate.py engine/corelata/pipeline.py engine/tests/stages/test_digest.py engine/tests/stages/test_gate.py engine/tests/test_pipeline.py docs/m2-followups.md docs/superpowers/specs/2026-10-12-corelata-v1-design.md
git commit -F FILE   # "fix: never force an undigestible source, keep forced digests in the gate's pool, record a failed re-digest (CRL-14)"
```

---

### Task 8: README, follow-ups

**Files:**
- Modify: `README.md` (new section before `## Development`), `docs/m3-followups.md`, `docs/m4a-followups.md`, `docs/m5-followups.md`
- Create: `docs/m8-followups.md`

- [ ] **Step 1: README**

Insert before `## Development`:

```markdown
## M8: correctness and operations

Seven tickets from the follow-up triage (CRL-6, 7, 10, 11, 12, 13, 14): a restarted run and a
rejected upload leave no files behind; `restore.sh` refuses a database with schemas it does not
manage; the worker purges closed jobs nightly (`worker.job_retention_days`, default 30) and the
orphan sweep is indexed (migration 0003); the Coglossa fetch fails clearly on a bad URL, an unset
key variable (409) or an export over 50 MB, and `corelata doctor` checks the integration; a parent
run must be in the same project and a completed run can be returned once (409 after that); header
logos inside `mc:AlternateContent` or a `w:object` survive the marking; the digest ladder never
forces a source no chunk can hold, keeps forced-digest sources in the gate's pool, and records a
failed re-digest in the trace.
```

- [ ] **Step 2: Follow-up files**

Mark closed: `docs/m3-followups.md` items on orphaned export files, a parent run in another project, two concurrent returns, bad `--source-id`/missing input leaving a project, `--parent-run` without `--project`, stalled job copies accumulating; `docs/m4a-followups.md` items on the rejected `add_source` directory, the five Coglossa items, the sweep index; `docs/m5-followups.md` items on `restore.sh` schema, the restore stub tests, the one-exec-call assertion, closed job copies, `backup.sh` streaming (documented). Each with ` — **closed in M8** (CRL-n)`.

Create `docs/m8-followups.md`:

```markdown
# M8 follow-ups

## Divergences from Coglossa

- `LocalStorage.delete_prefix` prunes emptied parents and `list_keys` lists a prefix — **backport** (CGL-18).
- The worker's nightly `purge_closed_jobs` task and the `(args->>'run_id')` index — **backport** (Coglossa has the same sweep and the same accumulation).
- `_logo_runs` keeps any run child that holds a picture — Coglossa has no header marking.

## Spec deviations

- §7.2/§10.1: a completed run can be returned once (R-M8-1); the spec said only that a return creates a linked run.
- §12: `restore.sh` refuses foreign schemas without an override flag (R-M8-5).

## Should fix soon

- `review_run` writes a placeholder event before the child exists; a crash between the two leaves a `return` event with `child_run_id` null. The orphan sweep could clear such events.
- The Coglossa fetch still runs inside the request (30 s); a slow Coglossa holds the API worker.
- `restore.sh` could offer `--allow-schemas` for sites that knowingly keep an extra schema.
- Scenario fixtures for conveyor-routed findings and added-rule profiles still need a steerable synthetic auditor.

## Later

- Pin `postgres:16-alpine` by digest across `bundle.sh`, `check-bundle.sh` and the compose files.
```

- [ ] **Step 3: Commit**

```bash
git add README.md docs/m8-followups.md docs/m3-followups.md docs/m4a-followups.md docs/m5-followups.md
git commit -F FILE   # "docs: README M8 section and follow-ups"
```

---

## Self-review

- **Spec coverage:** CRL-6 → Task 1; CRL-7 → Task 2; CRL-10 → Task 3; CRL-11 → Task 4; CRL-12 → Task 5; CRL-13 → Task 6; CRL-14 → Task 7; docs → Task 8.
- **Placeholders:** Task 1 Step 4 offers two equivalent mechanisms and tells the implementer to keep one; Task 4 Step 3 and Task 5 Step 1 name the file checks the implementer must make before asserting; Task 7 Step 1 asks for one arithmetic check against the real token sizes. Everything else carries its code.
- **Type consistency:** `Storage.list_keys` (Task 1) matches `_stray_files`; `purge_closed_jobs(db, *, retention_days)` (Task 3) matches the task and tests; `CoglossaClient.max_bytes` and `run_doctor(coglossa_transport=)` (Task 4) match the tests; `runs.return_event` / `set_review_child` (Task 5) match `review_run`; `StageContext.forced_digests` and `ctx.source()` (Task 7) match `select_units` and `writer_overflow`.
- **Review Focus:** each line names its test.
