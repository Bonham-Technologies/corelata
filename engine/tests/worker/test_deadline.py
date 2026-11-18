"""A discovery has two limits (CRL-38, R-M17-1, R-M17-26): one the worker has not claimed is failed
`discovery_start_deadline_s` after it was created, and one it is running is failed
`discovery_deadline_s` after its claim. Whoever looks first fails it (the API's read, the worker,
its sweep), with or without a worker, and nothing brings it back. A discovery that waits for a
worker busy with runs is not stuck: the work limit does not count while it waits."""

import asyncio
import logging
import re
import uuid
from datetime import timedelta

import pytest
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
NOT_STARTED = (
    "Discovery did not start within 60 minutes and was stopped: the worker was stopped or busy "
    "with runs. Start a new discovery."
)


async def _queued(svc) -> uuid.UUID:
    pid = await service.create_project(svc.db, f"p-{uuid.uuid4().hex[:6]}")
    ids = await service.add_source(svc.db, svc.storage, pid, "d.txt", "\n\n".join(PORT).encode())
    return await service.start_discovery(svc.db, svc.queue, pid, ids)


_AGED = text("UPDATE discovery SET created_at = now() - make_interval(secs => :s) WHERE id = :id")
_CLAIMED = text(
    "UPDATE discovery SET state = 'running', started_at = now() - make_interval(secs => :s) "
    "WHERE id = :id"
)


async def _age(db, discovery_id: uuid.UUID, seconds: float) -> None:
    """Make the discovery `seconds` old by the database's clock."""
    async with db.session() as s, s.begin():
        await s.execute(_AGED, {"s": seconds, "id": discovery_id})


async def _claimed(db, discovery_id: uuid.UUID, seconds: float) -> None:
    """Make the discovery `running`, claimed `seconds` ago by the database's clock."""
    async with db.session() as s, s.begin():
        await s.execute(_CLAIMED, {"s": seconds, "id": discovery_id})


def test_the_messages_render_the_configured_time():
    assert service.discovery_deadline_error(600) == TEN_MINUTES
    assert service.discovery_deadline_error(60) == ONE_MINUTE
    assert service.discovery_deadline_error(90) == (
        "Discovery did not finish within 90 seconds and was stopped. Start a new discovery."
    )
    assert service.discovery_deadline_error(90.5) == (
        "Discovery did not finish within 90.5 seconds and was stopped. Start a new discovery."
    )
    assert service.discovery_deadline_error(1_000_000) == (
        "Discovery did not finish within 1000000 seconds and was stopped. Start a new discovery."
    )
    assert service.discovery_deadline_error(6_000_000) == (
        "Discovery did not finish within 100000 minutes and was stopped. Start a new discovery."
    )
    assert service.discovery_start_error(3600) == NOT_STARTED
    assert service.discovery_start_error(60) == (
        "Discovery did not start within 1 minute and was stopped: the worker was stopped or busy "
        "with runs. Start a new discovery."
    )
    assert service.discovery_start_error(90.5) == (
        "Discovery did not start within 90.5 seconds and was stopped: the worker was stopped or "
        "busy with runs. Start a new discovery."
    )


async def test_a_discovery_waiting_for_a_busy_worker_is_not_failed_at_the_work_limit(services):
    """The M16 regression the start limit fixes: two long runs hold the worker's slots, and a
    discovery queued behind them is 10 minutes old before a slot frees up."""
    did = await _queued(services)
    await _age(services.db, did, 601)
    view = await service.get_discovery(services.db, did)
    assert view.state is DiscoveryState.CREATED and view.error is None
    assert view.deadline_at == view.created_at + timedelta(seconds=3600)  # the start limit


async def test_a_read_past_the_start_limit_fails_it_with_no_worker_running(services):
    did = await _queued(services)  # RecordingQueue: no worker will ever take it
    await _age(services.db, did, 3601)
    view = await service.get_discovery(services.db, did)
    assert view.state is DiscoveryState.FAILED and view.error == NOT_STARTED
    assert view.finished_at is not None and view.candidates == [] and view.started_at is None
    assert view.deadline_at == view.created_at + timedelta(seconds=3600)  # it never started
    again = await service.get_discovery(services.db, did)
    assert again == view  # idempotent: the second read changes nothing


async def test_a_read_past_the_work_limit_fails_a_running_one(services):
    did = await _queued(services)
    await _age(services.db, did, 3000)
    await _claimed(services.db, did, 601)  # its worker died, or hangs
    view = await service.get_discovery(services.db, did)
    assert view.state is DiscoveryState.FAILED and view.error == TEN_MINUTES
    assert view.deadline_at == view.started_at + timedelta(seconds=600)
    assert await service.get_discovery(services.db, did) == view


async def test_each_limit_applies_only_to_its_state(services):
    """A running discovery created long ago is inside its work limit; a queued one long past the
    work limit is inside its start limit. Neither is failed."""
    running = await _queued(services)
    await _age(services.db, running, 3601)
    await _claimed(services.db, running, 590)
    queued = await _queued(services)
    await _age(services.db, queued, 3590)
    late = await service.get_discovery(services.db, running)
    assert late.state is DiscoveryState.RUNNING
    assert late.deadline_at == late.started_at + timedelta(seconds=600)
    assert (await service.get_discovery(services.db, queued)).state is DiscoveryState.CREATED


async def test_a_read_of_an_ended_discovery_changes_nothing(services):
    done = await _queued(services)
    await drain(services)
    await _age(services.db, done, 7200)
    async with services.db.session() as s, s.begin():
        await s.execute(
            text("UPDATE discovery SET started_at = now() - interval '2 hours' WHERE id = :id"),
            {"id": done},
        )
    view = await service.get_discovery(services.db, done)
    assert view.state is DiscoveryState.COMPLETED and view.error is None
    assert view.deadline_at == view.started_at + timedelta(seconds=600)  # a terminal one started


async def test_a_job_claimed_after_the_start_limit_makes_no_model_call(
    services, fake_backend, caplog
):
    did = await _queued(services)
    await _age(services.db, did, 3601)  # nobody read it: the worker is the first to look
    await drain(services)
    assert fake_backend.requests == []
    assert f"discovery {did} was past its start limit when claimed; failed" in caplog.text
    view = await service.get_discovery(services.db, did)
    assert view.state is DiscoveryState.FAILED and view.error == NOT_STARTED
    assert view.started_at is None


async def test_a_job_redelivered_after_the_work_limit_makes_no_model_call(services, fake_backend):
    did = await _queued(services)
    await _claimed(services.db, did, 601)  # a dead worker left it running; nobody read it
    await drain(services)  # the requeued job is delivered
    assert fake_backend.requests == []
    view = await service.get_discovery(services.db, did)
    assert view.state is DiscoveryState.FAILED and view.error == TEN_MINUTES


def _record_budgets(monkeypatch) -> list[float]:
    """The seconds each `asyncio.timeout_at` budget had left when it was made."""
    budgets: list[float] = []
    real = asyncio.timeout_at

    def recording(when):
        budgets.append(when - asyncio.get_running_loop().time())
        return real(when)

    monkeypatch.setattr(asyncio, "timeout_at", recording)
    return budgets


async def test_a_redelivered_discovery_keeps_its_claim_and_gets_what_is_left(
    services, monkeypatch, caplog
):
    """The work limit counts from the first claim: a worker that dies after each start cannot
    keep a discovery alive by having its job delivered again."""
    did = await _queued(services)
    await _claimed(services.db, did, 300)  # a dead worker started it five minutes ago
    before = await service.get_discovery(services.db, did)
    budgets = _record_budgets(monkeypatch)
    await drain(services)  # the requeued job is delivered
    [budget] = budgets
    assert 290 < budget <= 300  # what is left of the work limit, not a fresh one
    assert "restarted: its earlier execution did not finish" in caplog.text
    view = await service.get_discovery(services.db, did)
    assert view.state is DiscoveryState.COMPLETED
    assert view.started_at == before.started_at
    assert view.deadline_at == before.deadline_at == before.started_at + timedelta(seconds=600)


async def test_a_claim_late_in_the_queue_gets_the_whole_work_budget(services, monkeypatch):
    did = await _queued(services)
    await _age(services.db, did, 3590)  # 10 s inside the start limit, long past the work limit
    budgets: list[float] = []
    real = asyncio.timeout_at

    def recording(when):
        budgets.append(when - asyncio.get_running_loop().time())
        return real(when)

    monkeypatch.setattr(asyncio, "timeout_at", recording)
    await drain(services)
    [budget] = budgets
    assert 590 < budget <= 600  # the work limit from the claim, not what is left of the start's
    view = await service.get_discovery(services.db, did)
    assert view.state is DiscoveryState.COMPLETED and view.error is None
    assert view.deadline_at == view.started_at + timedelta(seconds=600)
    assert view.started_at - view.created_at > timedelta(seconds=3500)


async def test_the_work_stops_at_the_deadline(db, fake_backend, tmp_path, monkeypatch, caplog):
    svc = make_services(db, fake_backend, tmp_path)
    # below the configuration's 60 s floor, so the test does not wait a minute
    svc.cfg.worker = svc.cfg.worker.model_copy(update={"discovery_deadline_s": 1.5})
    did = await _queued(svc)
    await _age(svc.db, did, 3000)  # queued a long time: the budget still starts at the claim

    async def hangs(*args, **kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(execute, "discover", hangs)
    job = svc.queue.pop()
    await asyncio.wait_for(run_job(svc, job.task, job.kwargs), timeout=10)
    view = await service.get_discovery(svc.db, did, deadline_s=1.5)
    assert view.state is DiscoveryState.FAILED
    assert view.error == service.discovery_deadline_error(1.5)
    # the claim found it in time and started it; the running work was stopped
    assert view.started_at is not None
    assert "when claimed" not in caplog.text
    [stop] = [r for r in caplog.records if "stopped at its deadline" in r.getMessage()]
    assert stop.levelno == logging.WARNING
    assert re.fullmatch(rf"discovery {did} stopped at its deadline after \d+ s", stop.getMessage())
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]  # not an internal error


async def test_a_worker_that_finishes_after_the_read_failed_it_does_not_bring_it_back(
    services, monkeypatch, caplog
):
    did = await _queued(services)
    real = execute.discover

    async def read_fails_it_meanwhile(*args, **kwargs):
        result = await real(*args, **kwargs)
        await _claimed(services.db, did, 601)
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


async def test_an_answer_whose_commit_finds_the_work_limit_passed_is_not_kept(
    services, monkeypatch
):
    did = await _queued(services)
    real = execute.discover

    async def late(*args, **kwargs):
        result = await real(*args, **kwargs)
        await _claimed(services.db, did, 601)  # nobody read it: the worker's own finish decides
        return result

    monkeypatch.setattr(execute, "discover", late)
    await drain(services)
    view = await service.get_discovery(services.db, did)
    assert view.state is DiscoveryState.FAILED and view.error == TEN_MINUTES
    assert view.candidates == []


async def test_an_error_whose_commit_finds_the_work_limit_passed_is_kept(services, monkeypatch):
    """The agent's own failure says more than the deadline: only an expired budget, or an answer
    that came too late, records the deadline (R-M17-30)."""
    did = await _queued(services)

    async def refuses(*args, **kwargs):
        await _age(services.db, did, 3000)
        await _claimed(services.db, did, 601)
        raise ValueError("the model refused the request")

    monkeypatch.setattr(execute, "discover", refuses)
    await drain(services)
    view = await service.get_discovery(services.db, did)
    assert view.state is DiscoveryState.FAILED and view.error == "the model refused the request"


_BLOCKED_BY = text("SELECT count(*) FROM pg_stat_activity WHERE :pid = ANY(pg_blocking_pids(pid))")
_PID = text("SELECT pg_backend_pid()")


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
        holder.append(await s.scalar(_PID))
        reached.set()
        await release.wait()
        await real(s, discovery_id, result)

    monkeypatch.setattr(discoveries, "set_candidates", held)
    worker = asyncio.create_task(drain(services))
    await reached.wait()
    # a read with both limits already passed (as a read a moment later would find them)
    read = asyncio.create_task(
        service.get_discovery(services.db, did, deadline_s=0.001, start_deadline_s=0.001)
    )
    await _until_blocked_by(services.db, holder[0])
    release.set()
    await worker
    view = await read
    assert view.state is DiscoveryState.COMPLETED and view.error is None


async def test_a_claim_that_commits_first_stands_against_a_read_that_waited(services, monkeypatch):
    """The start limit's boundary: the claim decided "in time" and holds the lock; a read past the
    start limit waits, then finds the discovery running inside its work limit."""
    did = await _queued(services)
    reached, release, holder = asyncio.Event(), asyncio.Event(), []
    real = discoveries.source_ids

    async def held(s, discovery_id):
        holder.append(await s.scalar(_PID))
        reached.set()
        await release.wait()
        return await real(s, discovery_id)

    monkeypatch.setattr(discoveries, "source_ids", held)
    worker = asyncio.create_task(drain(services))
    await reached.wait()
    read = asyncio.create_task(service.get_discovery(services.db, did, start_deadline_s=0.001))
    await _until_blocked_by(services.db, holder[0])
    release.set()
    view = await read
    assert view.state is DiscoveryState.RUNNING and view.error is None
    await worker
    assert (await service.get_discovery(services.db, did)).state is DiscoveryState.COMPLETED


async def test_a_read_that_commits_first_stands_against_a_claim_that_waited(services, fake_backend):
    """A read that failed the discovery at its start limit holds the lock; the worker's claim
    waits, then finds it ended and makes no model call."""
    did = await _queued(services)
    await _age(services.db, did, 3601)
    async with services.db.session() as s, s.begin():
        pid = await s.scalar(_PID)
        assert await discoveries.expire(
            s,
            start_deadline_s=3600,
            deadline_s=600,
            start_error=NOT_STARTED,
            error=TEN_MINUTES,
            discovery_id=did,
        ) == [did]
        worker = asyncio.create_task(drain(services))
        await _until_blocked_by(services.db, pid)
    await worker
    assert fake_backend.requests == []
    view = await service.get_discovery(services.db, did)
    assert view.state is DiscoveryState.FAILED and view.error == NOT_STARTED


async def test_the_sweep_fails_unread_discoveries_past_their_limits(services, caplog):
    queued_old, queued_young = await _queued(services), await _queued(services)
    running_old, running_young = await _queued(services), await _queued(services)
    done = await _queued(services)
    await drain(services)  # all five completed
    async with services.db.session() as s, s.begin():
        await s.execute(
            text("UPDATE discovery SET state = 'created', started_at = NULL WHERE id IN (:a, :b)"),
            {"a": queued_old, "b": queued_young},
        )
    await _age(services.db, queued_old, 3601)
    await _age(services.db, queued_young, 601)
    await _claimed(services.db, running_old, 601)
    await _claimed(services.db, running_young, 30)
    await _age(services.db, done, 7200)
    limits = {"start_deadline_s": 3600, "deadline_s": 600}
    assert sorted(await expire_discoveries(services.db, **limits)) == sorted(
        [queued_old, running_old]
    )
    assert await expire_discoveries(services.db, **limits) == []  # idempotent
    for did in (queued_old, running_old):
        assert f"discovery {did} passed its deadline; marked failed" in caplog.text
    views = {
        d: await service.get_discovery(services.db, d)
        for d in (queued_old, queued_young, running_old, running_young, done)
    }
    assert {d: (v.state, v.error) for d, v in views.items()} == {
        queued_old: (DiscoveryState.FAILED, NOT_STARTED),
        queued_young: (DiscoveryState.CREATED, None),
        running_old: (DiscoveryState.FAILED, TEN_MINUTES),
        running_young: (DiscoveryState.RUNNING, None),
        done: (DiscoveryState.COMPLETED, None),
    }


def _skew_app_clock(monkeypatch, by: timedelta) -> None:
    """Move the Python clock every `utcnow()` reads by `by`; the database's clock stays put."""
    from datetime import datetime as real

    from corelata.store import models

    class Skewed(real):
        @classmethod
        def now(cls, tz=None):
            return real.now(tz) + by

    monkeypatch.setattr(models, "datetime", Skewed)


async def _db_now(db):
    async with db.session() as s:
        return await s.scalar(text("SELECT now()"))


async def test_a_discovery_from_an_app_whose_clock_is_slow_is_not_expired_early(
    services, monkeypatch
):
    """`created_at` comes from the database (CRL-53): the start limit is compared with its `now()`,
    so an API host an hour behind the database must not move the limit by the skew."""
    _skew_app_clock(monkeypatch, -timedelta(minutes=61))
    did = await _queued(services)
    view = await service.get_discovery(services.db, did)
    assert view.state is DiscoveryState.CREATED and view.error is None
    assert abs(view.created_at - await _db_now(services.db)) < timedelta(seconds=30)


async def test_a_discovery_from_an_app_whose_clock_is_fast_still_expires_on_time(
    services, monkeypatch
):
    _skew_app_clock(monkeypatch, timedelta(minutes=61))
    did = await _queued(services)
    # an hour and a second older than it was written: with an app-clock created_at an hour
    # ahead, this would still be inside the start limit
    async with services.db.session() as s, s.begin():
        await s.execute(
            text(
                "UPDATE discovery SET created_at = created_at - make_interval(secs => 3601) "
                "WHERE id = :id"
            ),
            {"id": did},
        )
    view = await service.get_discovery(services.db, did)
    assert view.state is DiscoveryState.FAILED and view.error == NOT_STARTED


@pytest.mark.parametrize("skew", [timedelta(minutes=-30), timedelta(minutes=30)])
async def test_the_workers_deadline_failures_are_timed_by_the_database(
    services, fake_backend, monkeypatch, skew
):
    """`finished_at` on the worker's own limit failures is the database's `now()`, like the
    expiry's (CRL-53), whatever the worker host's clock says."""
    not_started, not_finished = await _queued(services), await _queued(services)
    await _age(services.db, not_started, 3601)
    await _claimed(services.db, not_finished, 601)
    _skew_app_clock(monkeypatch, skew)
    await drain(services)
    assert fake_backend.requests == []
    now = await _db_now(services.db)
    for did, error in ((not_started, NOT_STARTED), (not_finished, TEN_MINUTES)):
        view = await service.get_discovery(services.db, did)
        assert view.state is DiscoveryState.FAILED and view.error == error
        assert abs(view.finished_at - now) < timedelta(seconds=30)


@pytest.mark.parametrize("skew", [timedelta(minutes=-30), timedelta(minutes=30)])
async def test_a_finished_discovery_is_timed_by_the_database(
    services, fake_backend, monkeypatch, skew
):
    did = await _queued(services)
    _skew_app_clock(monkeypatch, skew)
    await drain(services)
    view = await service.get_discovery(services.db, did)
    assert view.state is DiscoveryState.COMPLETED
    assert view.started_at <= view.finished_at
    assert abs(view.finished_at - await _db_now(services.db)) < timedelta(seconds=30)
