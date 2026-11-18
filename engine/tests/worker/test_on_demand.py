"""M19 (spec §12.1, §13.5): what the hosted demo's on-demand worker, cron and purge read and do,
on a real Postgres. queue_status and needs_worker are copied from Coglossa with their tests;
cron_pass and purge_pass are Corelata's."""

import dataclasses
from datetime import timedelta

from sqlalchemy import text

from corelata import service
from corelata.schema import DiscoveryState, RunState
from corelata.store.db import Database
from corelata.store.models import utcnow
from corelata.worker import app as worker_app
from corelata.worker.app import (
    ORPHAN_GRACE_S,
    ProcrastinateQueue,
    QueueStatus,
    cron_pass,
    needs_worker,
    open_app,
    purge_pass,
    queue_status,
    run_worker,
)
from corelata.worker.sweep import ORPHAN_ERROR
from tests.conftest import build_config
from tests.worker.conftest import make_services, submit


async def _register_worker(db, *, heartbeat_age_s=0):
    async with db.engine.begin() as conn:
        worker_id = (
            await conn.execute(text("SELECT worker_id FROM procrastinate_register_worker_v1()"))
        ).scalar_one()
        await conn.execute(
            text(
                "UPDATE procrastinate_workers"
                " SET last_heartbeat = now() - make_interval(secs => :a) WHERE id = :w"
            ),
            {"a": heartbeat_age_s, "w": worker_id},
        )
    return worker_id


async def _defer_run(pg_url, run_id="1"):
    async with open_app(pg_url) as opened:
        await ProcrastinateQueue(opened).defer(
            service.TASK_RUN, lock=f"run:{run_id}", run_id=run_id
        )


async def test_an_empty_queue_needs_no_worker(db, pg_url):
    assert await queue_status(pg_url, 60) == QueueStatus(
        due=False, stalled=False, live_worker=False
    )
    assert not await needs_worker(pg_url, 60)


async def test_a_due_job_without_a_live_worker_needs_one(db, pg_url):
    await _defer_run(pg_url)
    await _register_worker(db, heartbeat_age_s=600)  # a dead worker's row is not a live one
    status = await queue_status(pg_url, 60)
    assert (status.due, status.live_worker, status.has_work) == (True, False, True)
    assert await needs_worker(pg_url, 60)


async def test_a_live_worker_fetches_due_jobs_itself(db, pg_url):
    await _defer_run(pg_url)
    await _register_worker(db)
    status = await queue_status(pg_url, 60)
    assert (status.due, status.live_worker, status.has_work) == (True, True, True)
    assert not await needs_worker(pg_url, 60)


async def test_a_stalled_job_needs_a_worker(db, pg_url):
    await _defer_run(pg_url)
    dead = await _register_worker(db, heartbeat_age_s=600)
    await _register_worker(db)  # even with another worker alive: someone must re-queue it
    async with db.engine.begin() as conn:
        await conn.execute(
            text("UPDATE procrastinate_jobs SET status = 'doing', worker_id = :w"), {"w": dead}
        )
    status = await queue_status(pg_url, 60)
    assert (status.due, status.stalled, status.has_work) == (False, True, True)
    assert await needs_worker(pg_url, 60)


async def test_a_job_running_on_a_live_worker_needs_none(db, pg_url):
    await _defer_run(pg_url)
    live = await _register_worker(db)
    async with db.engine.begin() as conn:
        await conn.execute(
            text("UPDATE procrastinate_jobs SET status = 'doing', worker_id = :w"), {"w": live}
        )
    status = await queue_status(pg_url, 60)
    assert not status.has_work and not status.needs_worker


def _cfg(monkeypatch, pg_url, **worker):
    monkeypatch.setenv("CORELATA_DATABASE_URL", pg_url)
    return build_config(worker={"stalled_after_s": 120, **worker})


async def test_cron_pass_starts_a_worker_for_a_run_whose_kick_was_lost(
    db, pg_url, fake_backend, tmp_path, monkeypatch
):
    """Review Focus 1: a run queued while its kick failed (the placeholder URL of the first
    deploy, a 5xx, a timeout) still gets a worker from the next cron tick."""
    cfg = _cfg(monkeypatch, pg_url)
    assert not await cron_pass(cfg)  # nothing queued: no worker, no Modal bill
    svc = make_services(db, fake_backend, tmp_path)
    async with open_app(pg_url) as opened:
        run_id = await submit(dataclasses.replace(svc, queue=ProcrastinateQueue(opened)))
    assert await cron_pass(cfg)
    assert (await service.run_progress(db, run_id)).state is RunState.CREATED  # left alone


async def test_cron_pass_ends_orphaned_runs_and_expired_discoveries(
    db, pg_url, fake_backend, tmp_path, monkeypatch
):
    cfg = _cfg(monkeypatch, pg_url, discovery_start_deadline_s=600)
    svc = make_services(db, fake_backend, tmp_path)
    orphan = await submit(svc)  # an in-memory queue: the run has no job in Postgres
    pid = (await service.run_progress(db, orphan)).project_id
    sources = [s.id for s in await service.list_sources(db, pid)]
    async with open_app(pg_url) as opened:
        waiting = await service.start_discovery(db, ProcrastinateQueue(opened), pid, sources)
    long_ago = utcnow() - timedelta(seconds=max(ORPHAN_GRACE_S, 600) + 60)
    async with db.engine.begin() as conn:
        await conn.execute(text("UPDATE run SET created_at = :t"), {"t": long_ago})
        await conn.execute(text("UPDATE discovery SET created_at = :t"), {"t": long_ago})
    assert await cron_pass(cfg)  # the discovery's job is still due, so a worker is wanted
    progress = await service.run_progress(db, orphan)
    assert progress.state is RunState.FAILED and progress.error == ORPHAN_ERROR.format(what="run")
    view = await service.get_discovery(db, waiting)
    assert view.state is DiscoveryState.FAILED
    assert view.error == service.discovery_start_error(600)


async def test_cron_pass_closes_its_database(db, pg_url, monkeypatch):
    disposed = []
    real = Database.dispose

    async def dispose(self):
        disposed.append(self.url)
        await real(self)

    monkeypatch.setattr(Database, "dispose", dispose)
    await cron_pass(_cfg(monkeypatch, pg_url))
    await purge_pass(_cfg(monkeypatch, pg_url))
    assert disposed == [pg_url, pg_url]


async def test_purge_pass_deletes_closed_jobs_older_than_the_retention(db, pg_url, monkeypatch):
    await _defer_run(pg_url, "old")
    await _defer_run(pg_url, "new")
    async with db.engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE procrastinate_jobs SET status = 'failed', scheduled_at = now() - "
                "make_interval(days => CASE WHEN lock = 'run:old' THEN 40 ELSE 1 END)"
            )
        )
    assert await purge_pass(_cfg(monkeypatch, pg_url, job_retention_days=30)) == 1
    async with db.engine.connect() as conn:
        left = (await conn.execute(text("SELECT lock FROM procrastinate_jobs"))).scalars().all()
    assert left == ["run:new"]


async def test_an_idle_burst_worker_leaves_nothing_for_the_cron(
    db, pg_url, fake_backend, tmp_path, monkeypatch
):
    """A burst worker started on an empty queue (a late kick) defers procrastinate's periodic
    jobs, runs them and exits; it leaves no due job, so the cron does not start another one
    every five minutes (spec §10.2: nobody using it, Modal bills nothing)."""
    cfg = _cfg(monkeypatch, pg_url)
    svc = make_services(db, fake_backend, tmp_path)

    async def factory(cfg, queue):
        return dataclasses.replace(svc, db=Database(pg_url), queue=queue)

    await run_worker(cfg, burst=True, install_signal_handlers=False, services_factory=factory)
    assert not await needs_worker(pg_url, cfg.worker.stalled_after_s)
    assert not await cron_pass(cfg)
    assert worker_app.QUEUE == "corelata"
