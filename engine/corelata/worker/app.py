"""procrastinate wiring (spec §4.1, §7.5). Queue jobs call corelata.worker.execute; a periodic
job re-queues jobs whose worker stopped sending heartbeats (a crashed or killed worker), and
execute_run starts such a run over. Copied from Coglossa without the scorer."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import procrastinate
import psycopg
from procrastinate import JobContext, RetryStrategy, signals
from procrastinate.exceptions import AlreadyEnqueued, ConnectorException, UniqueViolation
from procrastinate.jobs import Job, Status
from procrastinate.manager import QUEUEING_LOCK_CONSTRAINT, JobManager
from sqlalchemy.exc import InterfaceError, OperationalError

from corelata.config import CorelataConfig
from corelata.llm.registry import build_backends
from corelata.prompts.check import validate_prompts
from corelata.prompts.library import PromptLibrary
from corelata.service import TASK_DISCOVER, TASK_RUN, JobQueue, QueueUnavailableError
from corelata.storage import ProbeLeftover, build_storage
from corelata.store.db import CONNECT_ARGS, Database, database_url, error_reason, to_libpq_url
from corelata.store.migrate import ensure_migrated
from corelata.worker.execute import WorkerServices, run_job
from corelata.worker.sweep import (
    ORPHAN_GRACE_S,
    expire_discoveries,
    purge_closed_jobs,
    sweep_orphans,
)

log = logging.getLogger("corelata.worker")

QUEUE = "corelata"
WORKER_NAME = "corelata-worker"
SERVICES_KEY = "corelata_services"
TASK_REQUEUE_STALLED = "corelata.requeue_stalled"
TASK_SWEEP_ORPHANS = "corelata.sweep_orphans"
TASK_PURGE_JOBS = "corelata.purge_jobs"
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


_JOB_NOW = "SELECT status::text AS status, attempts FROM procrastinate_jobs WHERE id = %(job_id)s"


async def _not_ours(manager: JobManager, job: Job, *, closed_too: bool) -> str | None:
    """Why this worker must leave the job alone, or None. procrastinate acknowledges and retries
    a job by its id alone, and the stalled-job requeue gives the same job (same id, attempts + 1)
    to another worker (CRL-56). A job 'doing' under another attempt count is that worker's: an
    acknowledgement would delete it under the later attempt of its run (and the orphan sweep
    would then fail the run), a retry would start the run over a third time. With `closed_too`,
    a job already closed or deleted (a cancel that found this worker gone, R-M17-2) is left too:
    acknowledging it can only fail."""
    # all, not one: procrastinate's execute_query_one raises NoResult for a deleted job
    rows = await manager.connector.execute_query_all_async(_JOB_NOW, job_id=job.id)
    row = rows[0] if rows else None
    if row is None or row["status"] not in ("todo", "doing"):
        return "it was closed meanwhile" if closed_too else None
    if row["status"] == "doing" and row["attempts"] != job.attempts:
        return "another worker holds it"
    return None


def _fence_acks(manager: JobManager) -> None:
    """The worker's acknowledgement (`finish_job`) and database-error retry (`retry_job`) of a job
    check first that the job is still this worker's (`_not_ours`). The check and the write are
    two statements; the gap is milliseconds against `worker.stalled_after_s`."""
    finish, retry = manager.finish_job, manager.retry_job

    def skipped(job: Job, why: str) -> None:
        log.info("job %s (%s) left as it is: %s", job.id, job.queueing_lock, why)

    async def finish_job(job: Job, status: Status, delete_job: bool) -> None:
        if why := await _not_ours(manager, job, closed_too=True):
            skipped(job, why)
            return
        await finish(job=job, status=status, delete_job=delete_job)

    async def retry_job(
        job: Job,
        retry_at: datetime | None = None,
        priority: int | None = None,
        queue: str | None = None,
        lock: str | None = None,
    ) -> None:
        # the requeue lists jobs with their current attempts, so it passes; a closed job still
        # raises, which the requeue reads as "closed before it could be re-queued"
        if why := await _not_ours(manager, job, closed_too=False):
            skipped(job, why)
            return
        await retry(job=job, retry_at=retry_at, priority=priority, queue=queue, lock=lock)

    manager.finish_job = finish_job  # type: ignore[method-assign]
    manager.retry_job = retry_job  # type: ignore[method-assign]


_fence_acks(app.job_manager)  # replace_connector keeps the app and its job manager


@app.task(name=TASK_DISCOVER, queue=QUEUE, pass_context=True, retry=_DB_RETRY)
async def discover_task(context: JobContext, discovery_id: str) -> None:
    await run_job(_services(context), TASK_DISCOVER, {"discovery_id": discovery_id})


# What procrastinate_retry_job_v2 raises (procrastinate 3.10) for a job that is not 'doing'
_RETRY_REFUSED = "invalid status to retry"


def _closed_meanwhile(e: ConnectorException) -> bool:
    """procrastinate's retry refused the job because it is no longer 'doing': something closed
    it after the requeue listed it, such as a cancel that found its worker gone (R-M17-2)."""
    cause = e.__cause__
    return isinstance(cause, psycopg.errors.RaiseException) and _RETRY_REFUSED in str(cause)


async def requeue_stalled(manager: Any, seconds: float) -> int:
    """Re-queue the jobs of workers silent for `seconds`; returns how many were re-queued.
    A stalled job whose copy is already waiting (same queueing lock) can't be re-queued: it
    is closed as failed instead, and the waiting copy does the work. A job closed between the
    listing and its retry is skipped."""
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
        except ConnectorException as e:
            if not _closed_meanwhile(e):
                raise
            log.info(
                "job %s (%s) was closed before it could be re-queued; skipped",
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


@app.periodic(cron="* * * * *", periodic_id="sweep-orphans")
@app.task(name=TASK_SWEEP_ORPHANS, queue=QUEUE, pass_context=True)
async def sweep_orphans_task(context: JobContext, timestamp: int) -> None:
    svc = _services(context)
    await sweep_orphans(svc.db, grace_s=ORPHAN_GRACE_S)
    await expire_discoveries(
        svc.db,
        start_deadline_s=svc.cfg.worker.discovery_start_deadline_s,
        deadline_s=svc.cfg.worker.discovery_deadline_s,
    )


@app.periodic(cron="17 3 * * *", periodic_id="purge-jobs")
@app.task(name=TASK_PURGE_JOBS, queue=QUEUE, pass_context=True)
async def purge_jobs_task(context: JobContext, timestamp: int) -> None:
    svc = _services(context)
    await purge_closed_jobs(svc.db, retention_days=svc.cfg.worker.job_retention_days)


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

    async def defer(
        self, task: str, *, lock: str | None = None, priority: int = 0, **kwargs: str
    ) -> None:
        # queueing_lock: one waiting copy of a job; lock: copies never run at the same time;
        # priority: procrastinate fetches the highest first, then the oldest (R-M17-29)
        deferrer = self._app.configure_task(
            task, queue=QUEUE, queueing_lock=lock, lock=lock, priority=priority
        )
        try:
            with contextlib.suppress(AlreadyEnqueued):  # already waiting: idempotent by design
                await deferrer.defer_async(**kwargs)
        except ConnectorException as e:  # procrastinate hides the driver error in __cause__
            reason = error_reason(e.__cause__ or e)
            raise QueueUnavailableError(f"cannot reach the job queue: {reason}") from e


async def build_services(cfg: CorelataConfig, queue: JobQueue) -> WorkerServices:
    prompts = PromptLibrary(cfg.prompts_dir)
    validate_prompts(cfg, prompts)
    storage = build_storage(cfg.storage)
    try:
        storage.check_writable()
    except ProbeLeftover as e:  # writable; a stray empty file is no reason to stop (doctor warns)
        log.warning("%s", e)
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


@dataclass(frozen=True)
class QueueStatus:
    """What an on-demand worker would find (the hosted demo, copied from Coglossa): jobs it could
    run now, jobs left 'doing' by a worker that stopped sending heartbeats, and whether a worker
    is alive."""

    due: bool
    stalled: bool
    live_worker: bool

    @property
    def has_work(self) -> bool:
        return self.due or self.stalled

    @property
    def needs_worker(self) -> bool:
        # a live worker fetches due jobs itself; stalled jobs need a pass that re-queues them
        return self.stalled or (self.due and not self.live_worker)


# procrastinate's own heartbeat table; every worker registers there while it runs
_LIVE_WORKERS_SQL = """
SELECT count(*) AS live
  FROM procrastinate_workers
 WHERE last_heartbeat >= now() - make_interval(secs => %(seconds)s)
"""


async def queue_status(url: str, stalled_after_s: float) -> QueueStatus:
    async with open_app(url) as opened:
        pending = await opened.connector.execute_query_one_async(_PENDING_SQL, queue=QUEUE)
        live = await opened.connector.execute_query_one_async(
            _LIVE_WORKERS_SQL, seconds=stalled_after_s
        )
        stalled = await opened.job_manager.get_stalled_jobs(
            queue=QUEUE, seconds_since_heartbeat=stalled_after_s
        )
    return QueueStatus(
        due=bool(pending["due"]), stalled=bool(stalled), live_worker=bool(live["live"])
    )


async def needs_worker(url: str, stalled_after_s: float) -> bool:
    """Whether the on-demand cron should start a worker: jobs are due and no worker is alive
    to fetch them, or a dead worker left jobs stalled."""
    return (await queue_status(url, stalled_after_s)).needs_worker


async def cron_pass(cfg: CorelataConfig) -> bool:
    """The hosted demo's cron, every 5 minutes (spec §13.5): the minute tasks a long-running
    worker would run (fail orphaned runs and discoveries, then the discoveries past a deadline),
    run directly against the database, since a burst worker is rarely alive at those minutes;
    then whether to start a worker (`needs_worker`). Returns that answer (R-M19-9)."""
    url = database_url(cfg)
    db = Database(url)
    try:
        await sweep_orphans(db, grace_s=ORPHAN_GRACE_S)
        await expire_discoveries(
            db,
            start_deadline_s=cfg.worker.discovery_start_deadline_s,
            deadline_s=cfg.worker.discovery_deadline_s,
        )
    finally:
        await db.dispose()
    return await needs_worker(url, cfg.worker.stalled_after_s)


async def purge_pass(cfg: CorelataConfig) -> int:
    """The hosted demo's daily purge (spec §13.5): closed jobs older than the retention."""
    db = Database(database_url(cfg))
    try:
        return await purge_closed_jobs(db, retention_days=cfg.worker.job_retention_days)
    finally:
        await db.dispose()


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
