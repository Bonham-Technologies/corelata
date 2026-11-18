"""Cancelling a run whose worker is gone ends it at once (CRL-38, R-M17-2). "Gone" is what the
stalled-job requeue already means: the job is 'doing' and its worker's heartbeat is
`worker.stalled_after_s` old, or its worker row was deleted. A live worker, however slow, keeps
its run and stops at its next stage boundary, as before."""

import logging

import pytest
from procrastinate.exceptions import ConnectorException
from sqlalchemy import text

from corelata import service
from corelata.llm.payload import parse_input
from corelata.schema import RunState
from corelata.store import runs
from corelata.testing.fake_backend import FakeBackend
from corelata.testing.postgres import job_status, take_job
from corelata.worker import execute
from corelata.worker.app import open_app, requeue_stalled
from corelata.worker.execute import run_job
from tests.worker.conftest import drain, make_services, submit, tasks_sent

STALLED = service.STALLED_AFTER_S  # 900 s, the configuration's default


async def _claimed(svc, **opts):
    """A run a worker claimed (state ingesting, attempts 1); the queue holds no copy of it."""
    run_id = await submit(svc, **opts)
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


async def test_progress_says_when_a_requested_cancel_can_end_the_run(services):
    """CRL-49: a cancel the run's live worker took stays "stopping" until that worker's next stage
    boundary. Should the worker die first, the run never moves again; once its heartbeat is
    `stalled_after_s` old the progress says so, and a second cancel ends the run."""
    run_id = await _claimed(services)
    job = await take_job(services.db, run_id, silent_s=31)
    before = await service.run_progress(services.db, run_id, stalled_after_s=30)
    assert before.worker_gone and not before.cancel_requested  # CRL-69: said before any cancel
    assert await service.cancel_run(services.db, run_id) is RunState.INGESTING  # 900 s default
    moving = await service.run_progress(services.db, run_id)
    assert moving.cancel_requested and not moving.worker_gone
    stuck = await service.run_progress(services.db, run_id, stalled_after_s=30)
    assert stuck.cancel_requested and stuck.worker_gone
    assert await service.cancel_run(services.db, run_id, stalled_after_s=30) is RunState.CANCELLED
    assert await job_status(services.db, job) == "aborted"
    ended = await service.run_progress(services.db, run_id, stalled_after_s=30)
    assert ended.state is RunState.CANCELLED and not ended.worker_gone


async def test_progress_says_a_run_nobody_asked_to_stop_has_lost_its_worker(services):
    """CRL-69: a worker OOM-killed or stopped leaves its run 'writing' with nothing writing it.
    Once its heartbeat is `stalled_after_s` old the progress says so, cancel or not; a job no
    worker has taken, or one a live worker holds, is not gone."""
    queued = await submit(services)
    assert not (await service.run_progress(services.db, queued, stalled_after_s=0)).worker_gone
    run_id = await _claimed(services, project="q")
    job = await take_job(services.db, run_id, silent_s=STALLED + 1)
    gone = await service.run_progress(services.db, run_id)
    assert gone.worker_gone and not gone.cancel_requested and gone.state is RunState.INGESTING
    alive = await service.run_progress(services.db, run_id, stalled_after_s=STALLED + 60)
    assert not alive.worker_gone
    await _requeue(services.db, job)  # a running worker re-queued it: waiting, not gone
    assert not (await service.run_progress(services.db, run_id)).worker_gone
    other = await _claimed(services, project="r")
    await take_job(services.db, other, silent_s=None)  # its worker row deleted
    assert (await service.run_progress(services.db, other)).worker_gone


async def test_a_requested_cancel_waiting_in_the_queue_is_not_stuck(services):
    run_id = await _claimed(services)
    job = await take_job(services.db, run_id, silent_s=None)
    await _requeue(services.db, job)  # 'todo': the next worker to take it ends the run
    await service.cancel_run(services.db, run_id)
    progress = await service.run_progress(services.db, run_id)
    assert progress.cancel_requested and not progress.worker_gone


async def _requeue(db, job_id: int) -> None:
    """What the stalled-job requeue does to a job: procrastinate's own retry, which puts it back
    to 'todo' and keeps the dead worker's id on it."""
    async with db.session() as s, s.begin():
        await s.execute(
            text("SELECT procrastinate_retry_job_v2(:id, now(), NULL, NULL, NULL)"), {"id": job_id}
        )


async def test_a_run_whose_job_waits_for_a_worker_keeps_todays_behaviour(services):
    """A job back in the queue (re-queued, or a retry scheduled) is not held by a dead worker:
    the next worker to take it ends the run at its claim, as before M17."""
    run_id = await _claimed(services)
    job = await take_job(services.db, run_id, silent_s=STALLED + 1)
    await _requeue(services.db, job)  # 'todo', still naming the worker that died
    assert await service.cancel_run(services.db, run_id) is RunState.INGESTING
    progress = await service.run_progress(services.db, run_id)
    assert progress.cancel_requested and progress.finished_at is None
    assert await job_status(services.db, job) == "todo"  # the next worker takes it


async def test_the_requeue_leaves_a_job_the_cancel_closed_alone(services, pg_url):
    run_id = await _claimed(services)
    job = await take_job(services.db, run_id, silent_s=None)
    assert await service.cancel_run(services.db, run_id) is RunState.CANCELLED
    async with open_app(pg_url) as opened:
        assert await requeue_stalled(opened.job_manager, STALLED) == 0
    assert await job_status(services.db, job) == "aborted"


class _CancelsBetween:
    """The job manager, with a cancel committed between the requeue's read of the stalled jobs
    and its retry of them: the cancel closes the first run's job, which the read still lists."""

    def __init__(self, manager, db, run_id) -> None:
        self.manager, self.db, self.run_id = manager, db, run_id

    async def get_stalled_jobs(self, **kwargs):
        stalled = await self.manager.get_stalled_jobs(**kwargs)
        assert await service.cancel_run(self.db, self.run_id) is RunState.CANCELLED
        return stalled

    async def retry_job(self, job):
        await self.manager.retry_job(job)


async def test_the_requeue_skips_a_job_a_cancel_closed_after_it_looked(services, pg_url, caplog):
    cancelled, other = await _claimed(services), await _claimed(services, project="q")
    closed = await take_job(services.db, cancelled, silent_s=None)
    stalled = await take_job(services.db, other, silent_s=None)
    caplog.set_level(logging.INFO, logger="corelata.worker")
    async with open_app(pg_url) as opened:
        manager = _CancelsBetween(opened.job_manager, services.db, cancelled)
        assert await requeue_stalled(manager, STALLED) == 1
    assert await job_status(services.db, closed) == "aborted"
    assert await job_status(services.db, stalled) == "todo"  # the other job still moved on
    assert f"job {closed} (run:{cancelled}) was closed before it could be re-queued" in caplog.text


class _DeletesBetween(_CancelsBetween):
    """As above, with the first run's job deleted instead: its worker came back and finished it
    (successful jobs are deleted)."""

    async def get_stalled_jobs(self, **kwargs):
        stalled = await self.manager.get_stalled_jobs(**kwargs)
        async with self.db.session() as s, s.begin():
            await s.execute(
                text("DELETE FROM procrastinate_jobs WHERE args->>'run_id' = :id"),
                {"id": str(self.run_id)},
            )
        return stalled


async def test_the_requeue_skips_a_job_deleted_after_it_looked(services, pg_url, caplog):
    finished, other = await _claimed(services), await _claimed(services, project="q")
    deleted = await take_job(services.db, finished, silent_s=None)
    stalled = await take_job(services.db, other, silent_s=None)
    caplog.set_level(logging.INFO, logger="corelata.worker")
    async with open_app(pg_url) as opened:
        manager = _DeletesBetween(opened.job_manager, services.db, finished)
        assert await requeue_stalled(manager, STALLED) == 1
    assert await job_status(services.db, deleted) is None
    assert await job_status(services.db, stalled) == "todo"
    assert f"job {deleted} (run:{finished}) was closed before it could be re-queued" in caplog.text


async def test_the_requeue_still_raises_any_other_connector_error():
    class Manager:
        async def get_stalled_jobs(self, *, seconds_since_heartbeat):
            return ["job-1"]

        async def retry_job(self, job):
            raise ConnectorException("the database went away")

    with pytest.raises(ConnectorException):
        await requeue_stalled(Manager(), 60)


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

    def __init__(self, *, silent_s: float | None, then=None) -> None:
        super().__init__(name="fake")
        self.db = None
        self.run_id = None
        self.silent_s = silent_s
        self.then = then  # called after the cancel, before the writer answers
        self.cancelled_to: RunState | None = None

    async def chat(self, request):
        payload = parse_input([m.model_dump() for m in request.messages])
        if payload["task"] == "writer" and self.cancelled_to is None:
            await take_job(self.db, self.run_id, silent_s=self.silent_s)
            self.cancelled_to = await service.cancel_run(self.db, self.run_id)
            if self.then is not None:
                await self.then()
        return await super().chat(request)


async def _written(db, run_id):
    """What the run's rows hold of its execution: its model calls and its token usage."""
    record = await service.get_run_record(db, run_id)
    async with db.session() as s:
        run = await runs.get_run(s, run_id)
    return [c.model_dump() for c in record.llm_calls], run.token_usage


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


async def test_a_worker_taken_for_dead_that_then_fails_writes_nothing(
    db, tmp_path, run_channel, caplog
):
    """The cancel ends the run under the worker, and then the worker's pipeline raises with a
    model call not yet saved: its failure path finds the run ended and stops, with no calls,
    usage or announcement."""
    seen = {}

    async def snapshot():
        seen["written"] = await _written(db, spy.run_id)
        seen["announced"] = await run_channel.received()  # up to and including the cancel

    spy = _TakenForDead(silent_s=None, then=snapshot)
    spy.script("writer", "not json", RuntimeError("boom"))  # a call logged, then the repair fails
    svc = make_services(db, spy, tmp_path)
    run_id = await submit(svc)
    spy.db, spy.run_id = db, run_id
    await drain(svc)
    assert spy.cancelled_to is RunState.CANCELLED and seen["announced"][-1] == str(run_id)
    progress = await service.run_progress(db, run_id)
    assert progress.state is RunState.CANCELLED and progress.error is None
    assert await _written(db, run_id) == seen["written"]
    assert await run_channel.received() == []
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
