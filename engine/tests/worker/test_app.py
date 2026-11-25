import asyncio
import dataclasses
import logging
import os
import signal
from types import SimpleNamespace

import procrastinate
import pytest
from sqlalchemy import text

from corelata import service
from corelata.config import ConfigError
from corelata.schema import RunState
from corelata.store import migrate
from corelata.store.db import Database
from corelata.store.migrate import MigrationState
from corelata.worker import app as worker_app
from corelata.worker.app import ProcrastinateQueue, open_app, requeue_stalled, run_worker
from tests.worker.conftest import make_services, state, submit


@pytest.fixture
def worker_env(db, fake_backend, tmp_path, monkeypatch, pg_url):
    monkeypatch.setenv("CORELATA_DATABASE_URL", pg_url)
    svc = make_services(db, fake_backend, tmp_path)

    async def factory(cfg, queue):
        # its own Database: run_worker closes the services when it stops
        return dataclasses.replace(svc, db=Database(pg_url), queue=queue)

    return svc, factory


async def _submit(svc, pg_url, **opts):
    async with open_app(pg_url) as opened:
        return await submit(dataclasses.replace(svc, queue=ProcrastinateQueue(opened)), **opts)


async def _jobs(db, task=service.TASK_RUN):
    async with db.engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT status, lock, queueing_lock FROM procrastinate_jobs WHERE task_name = :t"),
            {"t": task},
        )
        return [tuple(r) for r in rows]


def _record_jobs(monkeypatch):
    seen = []

    async def fake_run_job(svc, task, kwargs):
        seen.append((task, kwargs))

    monkeypatch.setattr(worker_app, "run_job", fake_run_job)
    return seen


async def _burst(svc, factory, **kw):
    await run_worker(
        svc.cfg, burst=True, install_signal_handlers=False, services_factory=factory, **kw
    )


async def test_the_worker_completes_a_queued_run(worker_env, pg_url):
    svc, factory = worker_env
    run_id = await _submit(svc, pg_url)
    await _burst(svc, factory)
    assert await state(svc.db, run_id) is RunState.COMPLETED
    assert await _jobs(svc.db) == []  # successful jobs are deleted


async def test_the_worker_runs_a_discovery(worker_env, pg_url):
    svc, factory = worker_env
    pid = await service.create_project(svc.db, "p")
    ids = await service.add_source(svc.db, svc.storage, pid, "a.txt", b"Varna port grew.")
    async with open_app(pg_url) as opened:
        did = await service.start_discovery(svc.db, ProcrastinateQueue(opened), pid, ids)
    await _burst(svc, factory)
    assert (await service.get_discovery(svc.db, did)).state.value == "completed"


async def test_a_discovery_takes_the_next_free_slot_ahead_of_a_waiting_run(
    worker_env, pg_url, monkeypatch
):
    """Runs and discoveries share the worker's slots; a discovery is deferred with a higher
    priority, so it is fetched before a run queued earlier (R-M17-29)."""
    svc, factory = worker_env
    one_slot = svc.cfg.model_copy(
        update={"worker": svc.cfg.worker.model_copy(update={"concurrency": 1})}
    )
    seen = _record_jobs(monkeypatch)
    monkeypatch.setattr(worker_app.app.periodic_registry, "periodic_tasks", {})
    pid = await service.create_project(svc.db, "p")
    ids = await service.add_source(svc.db, svc.storage, pid, "a.txt", b"Varna port grew.")
    async with open_app(pg_url) as opened:
        queue = ProcrastinateQueue(opened)
        await queue.defer(service.TASK_RUN, lock="run:r", run_id="r")
        did = await service.start_discovery(svc.db, queue, pid, ids)
    async with svc.db.engine.connect() as conn:
        priorities = dict(
            (await conn.execute(text("SELECT task_name, priority FROM procrastinate_jobs"))).all()
        )
    assert priorities == {service.TASK_RUN: 0, service.TASK_DISCOVER: service.DISCOVERY_PRIORITY}
    await asyncio.wait_for(_burst(dataclasses.replace(svc, cfg=one_slot), factory), timeout=30)
    assert seen == [
        (service.TASK_DISCOVER, {"discovery_id": str(did)}),
        (service.TASK_RUN, {"run_id": "r"}),
    ]


async def test_queueing_lock_deduplicates_and_serialises(db, pg_url):
    async with open_app(pg_url) as opened:
        queue = ProcrastinateQueue(opened)
        await queue.defer(service.TASK_RUN, lock="run:r", run_id="r")
        await queue.defer(service.TASK_RUN, lock="run:r", run_id="r")
    # one waiting job; its lock also stops two copies from running at the same time
    assert await _jobs(db) == [("todo", "run:r", "run:r")]


async def test_burst_requeues_the_jobs_of_a_crashed_worker(worker_env, pg_url, monkeypatch):
    svc, factory = worker_env
    seen = _record_jobs(monkeypatch)
    monkeypatch.setattr(worker_app, "_BURST_POLL_S", 0.05)
    # a short pass may end before the periodic re-queue job is deferred: burst mode can't rely on it
    monkeypatch.setattr(worker_app.app.periodic_registry, "periodic_tasks", {})
    async with open_app(pg_url) as opened:
        await ProcrastinateQueue(opened).defer(service.TASK_RUN, lock="run:k", run_id="k")
    async with svc.db.engine.begin() as conn:  # its worker died and was pruned
        await conn.execute(text("UPDATE procrastinate_jobs SET status = 'doing'"))
    await asyncio.wait_for(_burst(svc, factory), timeout=30)
    assert (service.TASK_RUN, {"run_id": "k"}) in seen


async def _stalled_copy_with_a_waiting_copy(db, pg_url, lock, run_id):
    """A copy of a job left 'doing' by a crashed worker, and a second copy waiting behind it
    (queueing locks only dedupe waiting jobs)."""
    async with open_app(pg_url) as opened:
        queue = ProcrastinateQueue(opened)
        await queue.defer(service.TASK_RUN, lock=lock, run_id=run_id)
        async with db.engine.begin() as conn:
            await conn.execute(
                text("UPDATE procrastinate_jobs SET status = 'doing' WHERE lock = :l"),
                {"l": lock},
            )
        await queue.defer(service.TASK_RUN, lock=lock, run_id=run_id)


async def test_burst_does_not_spin_on_a_job_whose_lock_is_held(worker_env, pg_url, monkeypatch):
    svc, factory = worker_env
    seen = _record_jobs(monkeypatch)
    monkeypatch.setattr(worker_app, "_BURST_POLL_S", 0.05)
    monkeypatch.setattr(worker_app.app.periodic_registry, "periodic_tasks", {})
    await _stalled_copy_with_a_waiting_copy(svc.db, pg_url, "run:h", "h")
    await asyncio.wait_for(_burst(svc, factory), timeout=30)
    assert seen == [(service.TASK_RUN, {"run_id": "h"})]  # the waiting copy ran
    assert await _jobs(svc.db) == [("failed", "run:h", "run:h")]  # the stalled copy


async def test_requeue_stalled_closes_a_copy_that_has_a_waiting_twin(db, pg_url, caplog):
    await _stalled_copy_with_a_waiting_copy(db, pg_url, "run:t", "t")
    async with open_app(pg_url) as opened:
        queue = ProcrastinateQueue(opened)
        await queue.defer(service.TASK_DISCOVER, lock="discovery:u", discovery_id="u")
        async with db.engine.begin() as conn:
            await conn.execute(
                text("UPDATE procrastinate_jobs SET status = 'doing' WHERE lock = 'discovery:u'")
            )
        with caplog.at_level(logging.WARNING, logger="corelata.worker"):
            assert await requeue_stalled(opened.job_manager, 60) == 1
    assert "a copy is waiting" in caplog.text
    assert sorted(await _jobs(db)) == [
        ("failed", "run:t", "run:t"),
        ("todo", "run:t", "run:t"),
    ]
    assert await _jobs(db, service.TASK_DISCOVER) == [("todo", "discovery:u", "discovery:u")]


async def test_requeue_stalled_raises_other_constraint_errors():
    from procrastinate.exceptions import UniqueViolation

    class Manager:
        async def get_stalled_jobs(self, *, seconds_since_heartbeat):
            return ["job-1"]

        async def retry_job(self, job):
            raise UniqueViolation(constraint_name="other", queueing_lock=None)

    with pytest.raises(UniqueViolation):
        await requeue_stalled(Manager(), 60)


async def test_workers_use_the_configured_stalled_timeout(worker_env, monkeypatch):
    svc, factory = worker_env
    calls = []

    async def spy(self, **options):
        calls.append(options)

    monkeypatch.setattr(procrastinate.App, "run_worker_async", spy)
    worker = svc.cfg.worker.model_copy(update={"stalled_after_s": 45})
    cfg = svc.cfg.model_copy(update={"worker": worker})
    await run_worker(cfg, burst=True, install_signal_handlers=False, services_factory=factory)
    await run_worker(cfg, install_signal_handlers=False, services_factory=factory)
    assert [c["stalled_worker_timeout"] for c in calls] == [45, 45]
    assert all(c["queues"] == ["corelata"] and c["name"] == "corelata-worker" for c in calls)


async def test_a_stop_signal_ends_burst_mode(worker_env, pg_url, monkeypatch):
    svc, factory = worker_env

    async def stop_then_queue_more(services, task, kwargs):
        os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.sleep(0.1)  # the signal handler runs
        await services.queue.defer(service.TASK_RUN, lock="run:s2", run_id="s2")

    monkeypatch.setattr(worker_app, "run_job", stop_then_queue_more)
    async with open_app(pg_url) as opened:
        await ProcrastinateQueue(opened).defer(service.TASK_RUN, lock="run:s", run_id="s")
    await asyncio.wait_for(
        run_worker(svc.cfg, burst=True, install_signal_handlers=True, services_factory=factory),
        timeout=30,
    )
    assert await _jobs(svc.db) == [("todo", "run:s2", "run:s2")]  # not run: stopped


async def test_the_long_running_worker_runs_jobs_until_cancelled(worker_env, pg_url):
    svc, factory = worker_env
    closed = []

    async def tracking_factory(cfg, queue):
        services = await factory(cfg, queue)
        original = services.aclose

        async def aclose():
            closed.append(True)
            await original()

        services.aclose = aclose
        return services

    run_id = await _submit(svc, pg_url)
    task = asyncio.create_task(
        run_worker(svc.cfg, install_signal_handlers=False, services_factory=tracking_factory)
    )
    for _ in range(300):
        if await state(svc.db, run_id) is RunState.COMPLETED:
            break
        await asyncio.sleep(0.05)
    assert not task.done()  # still waiting for more jobs
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await state(svc.db, run_id) is RunState.COMPLETED
    assert closed == [True]


async def test_cancelling_burst_mode_propagates(worker_env, pg_url, monkeypatch):
    svc, factory = worker_env
    started = asyncio.Event()

    async def slow_job(services, task, kwargs):
        started.set()
        await asyncio.sleep(0.2)

    monkeypatch.setattr(worker_app, "run_job", slow_job)
    async with open_app(pg_url) as opened:
        await ProcrastinateQueue(opened).defer(service.TASK_RUN, lock="run:c", run_id="c")
    task = asyncio.create_task(_burst(svc, factory))
    await asyncio.wait_for(started.wait(), timeout=30)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_requeue_stalled():
    jobs = [SimpleNamespace(id=1), SimpleNamespace(id=2)]

    class Connector:
        async def execute_query_all_async(self, query, *, job_id):
            return [{"status": "todo", "attempts": 1}]  # re-queued

    class Manager:
        connector = Connector()

        def __init__(self):
            self.retried = []

        async def get_stalled_jobs(self, *, seconds_since_heartbeat):
            assert seconds_since_heartbeat == 60
            return jobs

        async def retry_job(self, job):
            self.retried.append(job)

    manager = Manager()
    assert await requeue_stalled(manager, 60) == 2
    assert manager.retried == jobs


async def test_requeue_stalled_task_uses_the_configured_threshold(make_config):
    seen = []

    class Manager:
        async def get_stalled_jobs(self, *, seconds_since_heartbeat):
            seen.append(seconds_since_heartbeat)
            return []

    cfg = make_config(worker={"stalled_after_s": 90})
    context = SimpleNamespace(
        app=SimpleNamespace(job_manager=Manager()),
        additional_context={worker_app.SERVICES_KEY: SimpleNamespace(cfg=cfg)},
    )
    await worker_app.requeue_stalled_task(context, timestamp=0)
    assert seen == [90]


def test_the_periodic_tasks_are_registered():
    registered = set(worker_app.app.periodic_registry.periodic_tasks)
    assert (worker_app.TASK_SWEEP_ORPHANS, "sweep-orphans") in registered
    assert (worker_app.TASK_REQUEUE_STALLED, "requeue-stalled") in registered
    assert (worker_app.TASK_PURGE_JOBS, "purge-jobs") in registered


async def test_purge_jobs_task_uses_the_configured_retention(services, monkeypatch):
    seen = {}

    async def fake_purge(database, *, retention_days):
        seen["db"], seen["days"] = database, retention_days
        return 0

    monkeypatch.setattr(worker_app, "purge_closed_jobs", fake_purge)
    context = SimpleNamespace(additional_context={worker_app.SERVICES_KEY: services})
    await worker_app.purge_jobs_task(context, timestamp=0)
    assert seen == {"db": services.db, "days": services.cfg.worker.job_retention_days}


async def test_sweep_orphans_task_uses_the_grace_period_and_the_discovery_deadline(
    db, fake_backend, tmp_path, monkeypatch
):
    services = make_services(
        db,
        fake_backend,
        tmp_path,
        worker={"discovery_deadline_s": 90, "discovery_start_deadline_s": 120},
    )
    seen = {}

    async def fake_sweep(database, *, grace_s):
        seen["sweep"] = (database, grace_s)
        return [], []

    async def fake_expire(database, *, start_deadline_s, deadline_s):
        seen["expire"] = (database, start_deadline_s, deadline_s)
        return []

    monkeypatch.setattr(worker_app, "sweep_orphans", fake_sweep)
    monkeypatch.setattr(worker_app, "expire_discoveries", fake_expire)
    context = SimpleNamespace(additional_context={worker_app.SERVICES_KEY: services})
    await worker_app.sweep_orphans_task(context, timestamp=0)
    assert seen == {
        "sweep": (services.db, worker_app.ORPHAN_GRACE_S),
        "expire": (services.db, 120, 90),
    }


async def test_worker_refuses_an_unmigrated_database(worker_env, monkeypatch):
    svc, factory = worker_env
    monkeypatch.setattr(migrate, "migration_state", lambda url: MigrationState(None, "0002"))
    with pytest.raises(ConfigError, match="corelata migrate"):
        await _burst(svc, factory)


async def test_worker_refuses_an_unreachable_database(worker_env, monkeypatch):
    svc, factory = worker_env
    monkeypatch.setenv("CORELATA_DATABASE_URL", "postgresql://u:secret@127.0.0.1:9/x")
    with pytest.raises(ConfigError, match="cannot connect") as info:
        await _burst(svc, factory)
    assert "secret" not in str(info.value)


async def test_build_services(tmp_path, monkeypatch, pg_url, make_config):
    monkeypatch.setenv("CORELATA_DATABASE_URL", pg_url)
    cfg = make_config(storage={"path": str(tmp_path / "files")})
    svc = await worker_app.build_services(cfg, queue=None)
    try:
        assert set(svc.backends) == {"fake"} and (tmp_path / "files").is_dir()
    finally:
        await svc.aclose()


async def test_build_services_carries_on_past_a_stuck_check_probe(
    tmp_path, monkeypatch, pg_url, make_config, caplog
):
    """The bucket took the probe but would not delete it: the worker starts and logs the key,
    as doctor warns (CRL-59)."""
    from corelata.storage import LocalStorage, ProbeLeftover

    def stuck(self):
        raise ProbeLeftover(".corelata-check-abc", "AccessDenied: no")

    monkeypatch.setattr(LocalStorage, "check_writable", stuck)
    monkeypatch.setenv("CORELATA_DATABASE_URL", pg_url)
    cfg = make_config(storage={"path": str(tmp_path / "files")})
    svc = await worker_app.build_services(cfg, queue=None)
    try:
        assert ".corelata-check-abc was written but not deleted" in caplog.text
    finally:
        await svc.aclose()


async def test_the_queue_connection_has_a_connect_timeout(pg_url, monkeypatch):
    real = procrastinate.PsycopgConnector
    seen: dict = {}

    def spy(**kwargs):
        seen.update(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(procrastinate, "PsycopgConnector", spy)
    async with open_app(pg_url):
        pass
    assert seen["kwargs"] == {"connect_timeout": 10}


async def test_a_connector_failure_becomes_queue_unavailable():
    class Down:
        def configure_task(self, task, **options):
            async def defer_async(**kwargs):
                raise procrastinate.exceptions.ConnectorException() from OSError("refused")

            return SimpleNamespace(defer_async=defer_async)

    queue = ProcrastinateQueue(Down())
    with pytest.raises(service.QueueUnavailableError, match="cannot reach the job queue: refused"):
        await queue.defer(service.TASK_RUN, lock="run:x", run_id="x")
