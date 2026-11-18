"""Every committed change to a run's progress is announced on the run channel (CRL-22,
R-M14-3): `NOTIFY corelata_run, '<run_id>'` in the transaction that writes it."""

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError

from corelata import service
from corelata.llm.types import PermanentBackendError
from corelata.schema import RunState
from corelata.store import runs
from corelata.store.models import Run
from corelata.worker import execute
from corelata.worker.sweep import sweep_orphans
from tests.worker.conftest import drain, state, submit


@pytest.fixture
def announced(monkeypatch) -> list[str]:
    """The run state each `notify_run` call announces, as its own transaction sees it."""
    states: list[str] = []
    real = runs.notify_run

    async def spy(s, run_id):
        states.append(await s.scalar(select(Run.state).where(Run.id == run_id)))
        await real(s, run_id)

    monkeypatch.setattr(runs, "notify_run", spy)
    return states


async def test_a_notification_is_delivered_when_its_transaction_commits(services, run_channel):
    run_id = await submit(services)
    assert await run_channel.received() == []  # creating and queueing a run announces nothing
    async with services.db.session() as s, s.begin():
        await runs.notify_run(s, run_id)
        await runs.notify_run(s, run_id)
        assert await run_channel.received() == []  # nothing before the commit
    assert await run_channel.received(1) == [str(run_id)]  # once per transaction


async def test_a_rolled_back_transaction_announces_nothing(services, run_channel):
    run_id = await submit(services)
    with pytest.raises(RuntimeError):
        async with services.db.session() as s, s.begin():
            await runs.notify_run(s, run_id)
            raise RuntimeError("rolled back")
    assert await run_channel.received() == []


async def test_a_failed_notification_is_logged_and_the_writes_still_commit(
    services, run_channel, monkeypatch, caplog
):
    run_id = await submit(services)
    monkeypatch.setattr(runs, "RUN_CHANNEL", "")  # Postgres refuses an empty channel name
    async with services.db.session() as s, s.begin():
        (await runs.get_run(s, run_id, lock=True)).iteration = 1
        await runs.notify_run(s, run_id)
    assert (await service.run_progress(services.db, run_id)).iteration == 1
    assert await run_channel.received() == []
    assert f"run {run_id}: progress notification not sent: " in caplog.text
    assert "channel name cannot be empty" in caplog.text


async def test_a_failed_notification_never_fails_a_run(services, monkeypatch, caplog):
    monkeypatch.setattr(runs, "RUN_CHANNEL", "")
    run_id = await submit(services)
    await drain(services)
    progress = await service.run_progress(services.db, run_id)
    assert progress.state is RunState.COMPLETED
    # every one is logged: the claim, two per stage (its state, its record), the outcome, as
    # test_a_run_announces_every_change_it_commits counts them
    sent = 2 * len(progress.stages) + 2
    assert caplog.text.count("progress notification not sent") == sent


async def test_a_run_announces_every_change_it_commits(services, run_channel, announced):
    run_id = await submit(services)
    await drain(services)
    progress = await service.run_progress(services.db, run_id)
    assert progress.state is RunState.COMPLETED and len(progress.stages) == 6
    # the claim; then per stage the pipeline's state change and the stage's record; the outcome
    assert announced == [
        "ingesting",
        *[state for stage in progress.stages for state in (stage.stage, stage.stage)],
        "completed",
    ]
    assert await run_channel.received(len(announced)) == [str(run_id)] * len(announced)


async def test_a_failed_run_announces_its_failure(services, fake_backend, run_channel, announced):
    fake_backend.script("gate", PermanentBackendError("down"), PermanentBackendError("down"))
    run_id = await submit(services)
    await drain(services)
    assert (await service.run_progress(services.db, run_id)).state is RunState.FAILED
    assert announced[-1] == "failed"
    assert await run_channel.received(len(announced)) == [str(run_id)] * len(announced)


async def test_an_internal_error_announces_the_failure_on_both_paths(
    services, monkeypatch, announced, caplog
):
    async def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(execute, "run_report", boom)
    run_id = await submit(services)
    await drain(services)
    assert (await service.run_progress(services.db, run_id)).state is RunState.FAILED
    assert announced == ["ingesting", "failed"]

    announced.clear()

    async def broken(*args, **kwargs):  # _fail_run cannot write the leftover calls
        raise RuntimeError("write failed")

    # run_report is still `boom`, so nothing but _fail_run writes calls: its fallback ends the run
    monkeypatch.setattr(runs, "add_llm_calls", broken)
    other = await submit(services, project="q")
    await drain(services)
    assert (await service.run_progress(services.db, other)).state is RunState.FAILED
    assert announced == ["ingesting", "failed"]
    assert f"run {other}: leftover calls not saved" in caplog.text


async def test_cancelling_announces_the_flag_and_the_ending(services, announced):
    queued = await submit(services)
    assert await service.cancel_run(services.db, queued) is RunState.CANCELLED
    assert announced == ["cancelled"]

    announced.clear()
    running = await submit(services, project="q")
    assert await execute._begin(services, running) is not None
    assert await service.cancel_run(services.db, running) is RunState.INGESTING
    assert announced == ["ingesting", "ingesting"]  # the claim, then the flag

    announced.clear()
    flagged = await submit(services, project="r")
    async with services.db.session() as s, s.begin():
        (await runs.get_run(s, flagged, lock=True)).cancel_requested = True  # still created
    await execute.execute_run(services, flagged)
    assert announced == ["cancelled"]  # the worker ends it at job start


class _DownQueue:
    async def defer(
        self, task: str, *, lock: str | None = None, priority: int = 0, **kwargs: str
    ) -> None:
        raise ConnectionRefusedError("connection refused")


async def test_a_run_that_could_not_be_queued_announces_its_failure(services, announced):
    services.queue = _DownQueue()
    with pytest.raises(ConnectionRefusedError):
        await submit(services)
    assert announced == ["failed"]


async def test_the_sweep_announces_each_run_it_fails(services, run_channel):
    ids = [await submit(services), await submit(services, project="q")]
    async with services.db.session() as s, s.begin():
        await s.execute(text("UPDATE run SET created_at = now() - interval '10 minutes'"))
    failed, _ = await sweep_orphans(services.db, grace_s=120)
    assert sorted(failed) == sorted(ids)
    assert sorted(await run_channel.received(len(ids))) == sorted(str(i) for i in ids)


_KILL_SESSION = text("SELECT pg_terminate_backend(pg_backend_pid())")


async def test_a_connection_lost_inside_the_savepoint_surfaces_as_the_database_error(
    services, monkeypatch
):
    run_id = await submit(services)
    monkeypatch.setattr(runs, "_NOTIFY", _KILL_SESSION)
    with pytest.raises(OperationalError):  # not PendingRollbackError at the commit
        async with services.db.session() as s, s.begin():
            (await runs.get_run(s, run_id, lock=True)).iteration = 1
            await runs.notify_run(s, run_id)


async def test_a_connection_lost_while_notifying_retries_the_job_not_fails_the_run(
    services, monkeypatch
):
    run_id = await submit(services)
    real = runs.notify_run

    async def kill_after_the_claim(s, rid):
        await real(s, rid)  # the claim's own notification goes through and commits
        monkeypatch.setattr(runs, "_NOTIFY", _KILL_SESSION)  # the next one kills the session

    monkeypatch.setattr(runs, "notify_run", kill_after_the_claim)
    with pytest.raises(OperationalError):  # re-raised, so procrastinate retries the job
        await drain(services)
    assert await state(services.db, run_id) is RunState.INGESTING  # claimed, not FAILED
