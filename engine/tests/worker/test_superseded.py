"""A run started over while its first execution is still alive (CRL-56). The requeue gives a job
whose worker's heartbeat stalled to another worker, and that worker's claim starts the run over
as the next attempt. If the first worker was slow rather than dead, the fence stops it at its
next write: it compares the run's attempts with its own, so the run never has two executions
writing to it, and the new attempt's trace is left as that attempt made it."""

import dataclasses
import logging

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from corelata import service
from corelata.llm.payload import parse_input
from corelata.schema import RunState
from corelata.store import runs
from corelata.testing.fake_backend import FakeBackend
from corelata.testing.postgres import job_status
from corelata.worker import execute, sweep
from corelata.worker.app import QUEUE, SERVICES_KEY, WORKER_NAME, ProcrastinateQueue, open_app
from tests.worker.conftest import drain, make_services, submit, tasks_sent


class _StartedOverElsewhere(FakeBackend):
    """While the writer is called, a second worker claims the run (attempt 2); this worker goes
    on and the writer answers it."""

    def __init__(self) -> None:
        super().__init__(name="fake")
        self.svc = None
        self.run_id = None
        self.claimed = False

    async def chat(self, request):
        payload = parse_input([m.model_dump() for m in request.messages])
        if payload["task"] == "writer" and not self.claimed:
            self.claimed = True
            assert await execute._begin(self.svc, self.run_id) is not None  # attempt 2's claim
            self.after = await _snapshot(self.svc.db, self.run_id)
        return await super().chat(request)


async def _snapshot(db, run_id):
    """Everything an execution writes to the run: its row and its trace."""
    async with db.session() as s:
        run = await runs.get_run(s, run_id)
        row = (run.state, run.attempts, run.iteration, run.token_usage, run.error, run.report)
    record = await service.get_run_record(db, run_id)
    return (
        row,
        [st.model_dump() for st in record.stages],
        [c.model_dump() for c in record.llm_calls],
    )


async def _run(db, tmp_path, spy):
    svc = make_services(db, spy, tmp_path)
    run_id = await submit(svc)
    spy.svc, spy.run_id = svc, run_id
    await drain(svc)
    assert spy.claimed
    return run_id


async def test_a_superseded_attempt_stops_at_its_next_write(db, tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="corelata.worker")
    spy = _StartedOverElsewhere()
    run_id = await _run(db, tmp_path, spy)
    assert tasks_sent(spy) == ["gate", "writer"]  # nothing after the stage it was in
    assert await _snapshot(db, run_id) == spy.after  # the run is as attempt 2 left it
    row, stages, calls = spy.after
    assert row[:2] == (RunState.INGESTING.value, 2) and stages == [] and calls == []
    stopped = [r for r in caplog.records if "was started over elsewhere" in r.getMessage()]
    assert [r.levelno for r in stopped] == [logging.INFO]
    assert "attempt 2; this execution was attempt 1" in stopped[0].getMessage()
    assert "2 model calls" in stopped[0].getMessage()  # the gate's and the writer's, dropped
    # attempt 2's claim warns that it restarted the run; nothing else is worse than info
    noisy = [r for r in caplog.records if r.levelno >= logging.WARNING]
    restarted = f"run {run_id} restarted: its earlier execution did not finish"
    assert [r.getMessage() for r in noisy] == [restarted]


async def test_a_superseded_attempt_that_then_fails_writes_nothing(db, tmp_path, caplog):
    """The writer's repair fails after the claim: the failure path is fenced too, so the run is
    not failed under the attempt that now holds it."""
    caplog.set_level(logging.INFO, logger="corelata.worker")
    spy = _StartedOverElsewhere()
    spy.script("writer", "not json", RuntimeError("boom"))
    run_id = await _run(db, tmp_path, spy)
    assert await _snapshot(db, run_id) == spy.after
    assert (await service.run_progress(db, run_id)).state is RunState.INGESTING
    assert any("was started over elsewhere" in r.getMessage() for r in caplog.records)


# The requeue (`procrastinate_retry_job`) and a second worker's fetch, in one step: the job keeps
# its id, and a live worker holds it.
_HANDED_OVER = text(
    "WITH w AS (INSERT INTO procrastinate_workers (last_heartbeat) VALUES (now()) RETURNING id) "
    "UPDATE procrastinate_jobs SET attempts = attempts + 1, worker_id = (SELECT id FROM w) "
    "WHERE args->>'run_id' = :run_id AND status = 'doing' RETURNING id"
)


class _HandedToAnotherWorker(_StartedOverElsewhere):
    """As above, with the queue's side of it: the job this worker holds is given to a second,
    live worker, which then claims the run."""

    async def chat(self, request):
        payload = parse_input([m.model_dump() for m in request.messages])
        if payload["task"] == "writer" and not self.claimed:
            async with self.svc.db.session() as s, s.begin():
                self.job_id = await s.scalar(_HANDED_OVER, {"run_id": str(self.run_id)})
        return await super().chat(request)


async def _one_pass(opened, svc) -> None:
    """One procrastinate worker pass: the job, then nothing it can fetch."""
    await opened.run_worker_async(
        wait=False,
        install_signal_handlers=False,
        queues=[QUEUE],
        name=WORKER_NAME,
        additional_context={SERVICES_KEY: svc},
        delete_jobs="successful",
    )


async def _worker_run(db, tmp_path, pg_url, spy):
    svc = make_services(db, spy, tmp_path)
    async with open_app(pg_url) as opened:
        svc = dataclasses.replace(svc, queue=ProcrastinateQueue(opened))
        run_id = await submit(svc)
        spy.svc, spy.run_id = svc, run_id
        await _one_pass(opened, svc)
    return run_id


async def test_a_superseded_worker_leaves_the_job_to_the_attempt_that_holds_it(
    db, tmp_path, pg_url, caplog
):
    """procrastinate acknowledges a job when its task returns, by the job's id alone. The
    superseded execution's acknowledgement would delete the job the second worker holds, and the
    orphan sweep would then fail the run under it; it is skipped, so the job stays 'doing'."""
    caplog.set_level(logging.INFO, logger="corelata.worker")
    spy = _HandedToAnotherWorker()
    run_id = await _worker_run(db, tmp_path, pg_url, spy)
    assert spy.claimed and await job_status(db, spy.job_id) == "doing"
    assert await _snapshot(db, run_id) == spy.after
    assert f"job {spy.job_id} (run:{run_id}) left as it is: another worker holds it" in caplog.text
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    # the run has its job, so the sweep leaves it to the attempt that holds it
    assert await sweep.sweep_orphans(db, grace_s=0) == ([], [])


async def test_a_database_error_on_the_stale_write_does_not_requeue_the_job(
    db, tmp_path, pg_url, caplog, monkeypatch
):
    """A live worker taken for dead has most likely lost its database for a while, so its next
    write can fail before the fence answers. The task's retry on a database error would put the
    job the second worker holds back in the queue (a third attempt, paid again); it is skipped."""
    caplog.set_level(logging.INFO, logger="corelata.worker")
    spy = _HandedToAnotherWorker()
    write = execute.DbObserver.stage_recorded

    async def lost_connection(self, record, result):
        if spy.claimed:
            raise OperationalError("UPDATE run", {}, Exception("server closed the connection"))
        await write(self, record, result)

    monkeypatch.setattr(execute.DbObserver, "stage_recorded", lost_connection)
    await _worker_run(db, tmp_path, pg_url, spy)
    async with db.session() as s:
        row = (await s.execute(_JOB, {"id": spy.job_id})).one()
    assert tuple(row) == ("doing", 1)  # as the handover left it: not 'todo', no extra attempt
    assert f"job {spy.job_id} (run:{spy.run_id}) left as it is: another worker holds it" in (
        caplog.text
    )


class _ClosedUnderIt(_StartedOverElsewhere):
    """While the writer is called, a cancel that found this worker gone ends the run and closes
    its job (R-M17-2), as `service.cancel_run` does; the worker goes on."""

    async def chat(self, request):
        payload = parse_input([m.model_dump() for m in request.messages])
        if payload["task"] == "writer" and not self.claimed:
            self.claimed = True
            async with self.svc.db.session() as s, s.begin():
                self.job_id = await s.scalar(_CLOSED, {"run_id": str(self.run_id)})
                await s.execute(_CANCELLED, {"id": self.run_id})
        return await FakeBackend.chat(self, request)


_CLOSED = text(
    "UPDATE procrastinate_jobs SET status = 'aborted' WHERE args->>'run_id' = :run_id "
    "AND status = 'doing' RETURNING id"
)
_CANCELLED = text("UPDATE run SET state = 'cancelled', finished_at = now() WHERE id = :id")
_JOB = text("SELECT status::text, attempts FROM procrastinate_jobs WHERE id = :id")


async def test_a_job_closed_under_its_worker_is_left_quietly(db, tmp_path, pg_url, caplog):
    """The acknowledgement of a job the cancel closed used to fail, and procrastinate and asyncio
    logged an error ("Task exception was never retrieved"); it is skipped instead."""
    caplog.set_level(logging.INFO, logger="corelata.worker")
    spy = _ClosedUnderIt()
    run_id = await _worker_run(db, tmp_path, pg_url, spy)
    assert await job_status(db, spy.job_id) == "aborted"
    assert (await service.run_progress(db, run_id)).state is RunState.CANCELLED
    assert f"job {spy.job_id} (run:{run_id}) left as it is: it was closed meanwhile" in caplog.text
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


class _FinishedElsewhere(_HandedToAnotherWorker):
    """As above, and the second worker finishes the run before this one writes again: its job
    is deleted (successful jobs are)."""

    async def chat(self, request):
        answer = await super().chat(request)
        if self.claimed and not getattr(self, "deleted", False):
            self.deleted = True
            async with self.svc.db.session() as s, s.begin():
                await s.execute(
                    text("DELETE FROM procrastinate_jobs WHERE id = :id"), {"id": self.job_id}
                )
        return answer


async def test_a_superseded_worker_whose_job_is_gone_leaves_it_quietly(
    db, tmp_path, pg_url, caplog
):
    caplog.set_level(logging.INFO, logger="corelata.worker")
    spy = _FinishedElsewhere()
    run_id = await _worker_run(db, tmp_path, pg_url, spy)
    assert await job_status(db, spy.job_id) is None
    assert f"job {spy.job_id} (run:{run_id}) left as it is: it was closed meanwhile" in caplog.text
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


async def test_every_other_job_is_acknowledged(db, tmp_path, pg_url):
    """A run job whose execution was not superseded is acknowledged as before."""
    svc = make_services(db, FakeBackend(name="fake"), tmp_path)
    async with open_app(pg_url) as opened:
        svc = dataclasses.replace(svc, queue=ProcrastinateQueue(opened))
        run_id = await submit(svc)
        await _one_pass(opened, svc)
        async with db.session() as s:
            assert await s.scalar(text("SELECT count(*) FROM procrastinate_jobs")) == 0
    assert (await service.run_progress(db, run_id)).state is RunState.COMPLETED
