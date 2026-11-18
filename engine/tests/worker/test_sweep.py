import json
import uuid
from datetime import timedelta

from sqlalchemy import text

from corelata import service
from corelata.schema import DiscoveryState, RunState
from corelata.worker.sweep import ORPHAN_ERROR, purge_closed_jobs, sweep_orphans
from tests.conftest import db_now, on_db_clock, skew_clock
from tests.worker.conftest import submit


async def _insert_job(db, *, task: str, args: dict, status: str) -> None:
    async with db.session() as s, s.begin():
        await s.execute(
            text(
                "INSERT INTO procrastinate_jobs (queue_name, task_name, args, status) "
                "VALUES ('corelata', :task, CAST(:args AS jsonb), "
                "CAST(:status AS procrastinate_job_status))"
            ),
            {"task": task, "args": json.dumps(args), "status": status},
        )


async def _backdate(db, table: str, row_id: uuid.UUID) -> None:
    async with db.session() as s, s.begin():
        await s.execute(
            # past the grace period, inside a discovery's 10-minute deadline (R-M17-13)
            text(f"UPDATE {table} SET created_at = now() - interval '5 minutes' WHERE id = :id"),
            {"id": row_id},
        )


async def test_sweep_fails_runs_without_a_job(services):
    orphan = await submit(services)  # RecordingQueue: nothing lands in procrastinate_jobs
    await _backdate(services.db, "run", orphan)
    failed_job = await submit(services, project="q")
    await _backdate(services.db, "run", failed_job)
    await _insert_job(
        services.db, task="corelata.run", args={"run_id": str(failed_job)}, status="failed"
    )
    runs_failed, discoveries_failed = await sweep_orphans(services.db, grace_s=120)
    assert sorted(runs_failed) == sorted([orphan, failed_job]) and discoveries_failed == []
    for run_id in (orphan, failed_job):
        progress = await service.run_progress(services.db, run_id)
        assert progress.state is RunState.FAILED and progress.finished_at is not None
        assert progress.error == ORPHAN_ERROR.format(what="run")
    assert await sweep_orphans(services.db, grace_s=120) == ([], [])  # idempotent


async def test_sweep_leaves_queued_running_and_young_runs_alone(services):
    queued = await submit(services)
    await _backdate(services.db, "run", queued)
    await _insert_job(services.db, task="corelata.run", args={"run_id": str(queued)}, status="todo")
    running = await submit(services, project="q")
    await _backdate(services.db, "run", running)
    await _insert_job(
        services.db, task="corelata.run", args={"run_id": str(running)}, status="doing"
    )
    young = await submit(services, project="r")  # created just now: inside the grace period
    assert await sweep_orphans(services.db, grace_s=120) == ([], [])
    for run_id in (queued, running, young):
        assert (await service.run_progress(services.db, run_id)).state is RunState.CREATED


async def test_sweep_fails_discoveries_without_a_job(services):
    pid = await service.create_project(services.db, "p")
    ids = await service.add_source(services.db, services.storage, pid, "a.txt", b"Varna grain.")
    orphan = await service.start_discovery(services.db, services.queue, pid, ids)
    queued = await service.start_discovery(services.db, services.queue, pid, ids, "ministers")
    for discovery_id in (orphan, queued):
        await _backdate(services.db, "discovery", discovery_id)
    await _insert_job(
        services.db, task="corelata.discover", args={"discovery_id": str(queued)}, status="todo"
    )
    assert await sweep_orphans(services.db, grace_s=120) == ([], [orphan])
    view = await service.get_discovery(services.db, orphan)
    assert view.state is DiscoveryState.FAILED
    assert view.error == ORPHAN_ERROR.format(what="discovery")
    assert (await service.get_discovery(services.db, queued)).state is DiscoveryState.CREATED


async def _set_row_state(db, table: str, row_id: uuid.UUID, state: str) -> None:
    async with db.session() as s, s.begin():
        await s.execute(
            text(f"UPDATE {table} SET state = :state WHERE id = :id"),
            {"state": state, "id": row_id},
        )


async def _row(db, table: str, row_id: uuid.UUID):
    async with db.session() as s:
        result = await s.execute(
            text(f"SELECT state, error, finished_at FROM {table} WHERE id = :id"), {"id": row_id}
        )
        return result.one()


async def test_sweep_never_touches_old_terminal_rows(services):
    rows = []
    for i, state in enumerate(("completed", "gate_rejected", "failed", "cancelled")):
        run_id = await submit(services, project=f"t{i}")
        await _backdate(services.db, "run", run_id)
        await _set_row_state(services.db, "run", run_id, state)
        rows.append(("run", run_id))
    pid = await service.create_project(services.db, "d")
    ids = await service.add_source(services.db, services.storage, pid, "a.txt", b"Varna grain.")
    for i, state in enumerate(("completed", "failed")):
        discovery_id = await service.start_discovery(
            services.db, services.queue, pid, ids, f"hint{i}"
        )
        await _backdate(services.db, "discovery", discovery_id)
        await _set_row_state(services.db, "discovery", discovery_id, state)
        rows.append(("discovery", discovery_id))
    before = [await _row(services.db, table, row_id) for table, row_id in rows]
    assert await sweep_orphans(services.db, grace_s=120) == ([], [])
    assert [await _row(services.db, table, row_id) for table, row_id in rows] == before
    assert all(row.error is None for row in before)


async def test_sweep_leaves_a_discovery_with_a_doing_job_alone(services):
    pid = await service.create_project(services.db, "p")
    ids = await service.add_source(services.db, services.storage, pid, "a.txt", b"Varna grain.")
    created = await service.start_discovery(services.db, services.queue, pid, ids)
    running = await service.start_discovery(services.db, services.queue, pid, ids, "ministers")
    for discovery_id in (created, running):
        await _backdate(services.db, "discovery", discovery_id)
        await _insert_job(
            services.db,
            task="corelata.discover",
            args={"discovery_id": str(discovery_id)},
            status="doing",
        )
    await _set_row_state(services.db, "discovery", running, "running")
    assert await sweep_orphans(services.db, grace_s=120) == ([], [])
    assert (await service.get_discovery(services.db, created)).state is DiscoveryState.CREATED
    assert (await service.get_discovery(services.db, running)).state is DiscoveryState.RUNNING


async def _insert_closed_job(db, *, task: str, status: str, age_days: int) -> None:
    async with db.session() as s, s.begin():
        await s.execute(
            text(
                "INSERT INTO procrastinate_jobs "
                "(queue_name, task_name, args, status, scheduled_at) "
                "VALUES ('corelata', :task, '{}'::jsonb, "
                "CAST(:status AS procrastinate_job_status), "
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


async def test_the_discovery_sweep_is_timed_by_the_database(services, monkeypatch):
    """A discovery's created_at is the database's (CRL-53), so the sweep's grace is measured by the
    database too: a worker host whose clock runs fast must not sweep a young discovery, and the
    swept one's finished_at is the database's `now()`."""
    pid = await service.create_project(services.db, "p")
    ids = await service.add_source(services.db, services.storage, pid, "a.txt", b"Varna grain.")
    young = await service.start_discovery(services.db, services.queue, pid, ids)
    old = await service.start_discovery(services.db, services.queue, pid, ids, "ministers")
    await _backdate(services.db, "discovery", old)
    skew_clock(monkeypatch, timedelta(minutes=30))
    assert await sweep_orphans(services.db, grace_s=120) == ([], [old])
    assert (await service.get_discovery(services.db, young)).state is DiscoveryState.CREATED
    finished_at = (await _row(services.db, "discovery", old)).finished_at
    assert on_db_clock(finished_at, await db_now(services.db))


async def test_the_run_sweep_is_timed_by_the_database(services, monkeypatch):
    """CRL-87: a worker host whose clock runs ten minutes ahead of the API host's must not sweep a
    run created just now as orphaned; the grace and the swept run's finished_at are the
    database's."""
    young = await submit(services)
    old = await submit(services, project="q")
    await _backdate(services.db, "run", old)
    skew_clock(monkeypatch, timedelta(minutes=10))
    assert await sweep_orphans(services.db, grace_s=120) == ([old], [])
    assert (await service.run_progress(services.db, young)).state is RunState.CREATED
    finished_at = (await service.run_progress(services.db, old)).finished_at
    assert on_db_clock(finished_at, await db_now(services.db))
