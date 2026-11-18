"""Every path that ends a rerun records its fate on the parent and announces the parent
(CRL-34, R-M15-2), so an open Review page of the parent sees it."""

import json
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from corelata import service
from corelata.llm.types import PermanentBackendError
from corelata.schema import ReviewAction, ReviewState, RunState
from corelata.store import runs
from corelata.testing.postgres import take_job
from corelata.worker import execute
from corelata.worker.sweep import ORPHAN_ERROR, sweep_orphans
from tests.worker.conftest import drain, submit


async def _returned(services) -> tuple[uuid.UUID, uuid.UUID]:
    """A completed run, returned once: (parent, rerun). The rerun's job is queued, not run."""
    parent = await submit(services)
    await drain(services)
    child = await service.review_run(
        services.db,
        services.storage,
        services.queue,
        services.cfg,
        services.prompts,
        parent,
        ReviewAction.RETURN,
        note="Say more about the tariffs",
    )
    assert child is not None
    return parent, child


async def _returned_in(services, project: str) -> tuple[uuid.UUID, uuid.UUID]:
    """As `_returned`, in another project, the parent completed without a worker; only the
    rerun's job stays queued."""
    parent = await submit(services, project=project)
    async with services.db.session() as s, s.begin():
        (await runs.get_run(s, parent, lock=True)).state = RunState.COMPLETED.value
    child = await service.review_run(
        services.db,
        services.storage,
        services.queue,
        services.cfg,
        services.prompts,
        parent,
        ReviewAction.RETURN,
        note="x",
    )
    services.queue.jobs = [j for j in services.queue.jobs if j.kwargs["run_id"] == str(child)]
    assert child is not None
    return parent, child


async def _review(services, run_id) -> ReviewState:
    review = (await service.run_progress(services.db, run_id)).review
    assert review is not None
    return review


async def test_a_rerun_that_fails_frees_its_parent_and_announces_it(
    services, fake_backend, run_channel
):
    parent, child = await _returned(services)
    assert (await _review(services, parent)).child_state is None  # queued: still live
    await run_channel.received()  # forget what the run and the return announced
    fake_backend.script("gate", PermanentBackendError("down"), PermanentBackendError("down"))
    await drain(services)
    review = await _review(services, parent)
    assert review.child_run_id == str(child) and review.child_state is RunState.FAILED
    assert review.child_error and "down" in review.child_error
    assert review.note == "Say more about the tariffs"
    # the Review page's run is announced, after the rerun's own changes
    announced = await run_channel.received_until(str(parent))
    assert announced[-1] == str(parent) and set(announced[:-1]) == {str(child)}


async def test_a_completed_rerun_is_recorded_too(services):
    parent, child = await _returned(services)
    await drain(services)
    review = await _review(services, parent)
    assert review.child_state is RunState.COMPLETED and review.child_error is None
    with pytest.raises(service.ConflictError, match=str(child)):  # and it spends the return
        await service.review_run(
            services.db,
            services.storage,
            services.queue,
            services.cfg,
            services.prompts,
            parent,
            ReviewAction.RETURN,
            note="again",
        )


async def test_an_internal_error_on_either_failure_path_frees_the_parent(
    services, monkeypatch, caplog
):
    async def boom(*args, **kwargs):
        raise RuntimeError("boom")

    parent, _ = await _returned(services)
    monkeypatch.setattr(execute, "run_report", boom)
    await drain(services)
    review = await _review(services, parent)
    assert review.child_state is RunState.FAILED and "boom" in (review.child_error or "")

    other, rerun = await _returned_in(services, "q")

    async def broken(*args, **kwargs):  # _fail_run cannot write the leftover calls
        raise RuntimeError("write failed")

    # run_report is still `boom`, so nothing but _fail_run writes calls: its fallback ends the run
    monkeypatch.setattr(runs, "add_llm_calls", broken)
    await drain(services)
    assert (await _review(services, other)).child_state is RunState.FAILED
    assert f"run {rerun}: leftover calls not saved" in caplog.text


async def test_cancelling_a_rerun_frees_the_parent_on_both_paths(services):
    parent, child = await _returned(services)
    assert await service.cancel_run(services.db, child) is RunState.CANCELLED  # still queued
    assert (await _review(services, parent)).child_state is RunState.CANCELLED

    other, flagged = await _returned_in(services, "q")
    async with services.db.session() as s, s.begin():
        (await runs.get_run(s, flagged, lock=True)).cancel_requested = True  # still created
    await execute.execute_run(services, flagged)  # the worker ends it at job start
    assert (await _review(services, other)).child_state is RunState.CANCELLED


async def test_cancelling_a_rerun_whose_worker_is_gone_frees_the_parent(services, run_channel):
    parent, child = await _returned(services)
    assert await execute._begin(services, child) is not None  # a worker claimed the rerun
    await take_job(services.db, child, silent_s=None)  # and died
    await run_channel.received_until(str(child))
    assert await service.cancel_run(services.db, child) is RunState.CANCELLED  # at once (R-M17-2)
    review = await _review(services, parent)
    assert review.child_state is RunState.CANCELLED  # the same ending path (R-M15-2)
    assert sorted(await run_channel.received(2)) == sorted([str(child), str(parent)])


async def test_a_rerun_the_sweep_fails_frees_the_parent(services, run_channel):
    parent, child = await _returned(services)
    services.queue.jobs.clear()  # the rerun's job never reached the queue
    async with services.db.session() as s, s.begin():
        await s.execute(
            text("UPDATE run SET created_at = now() - interval '10 minutes' WHERE id = :id"),
            {"id": child},
        )
    await run_channel.received()
    failed, _ = await sweep_orphans(services.db, grace_s=120)
    assert failed == [child]
    review = await _review(services, parent)
    assert review.child_state is RunState.FAILED
    assert review.child_error == ORPHAN_ERROR.format(what="run")
    assert sorted(await run_channel.received(2)) == sorted([str(child), str(parent)])


async def test_one_parent_that_cannot_be_recomputed_does_not_stall_the_sweep(
    services, run_channel, monkeypatch, caplog
):
    broken, broken_child = await _returned(services)
    healthy, healthy_child = await _returned_in(services, "q")
    services.queue.jobs.clear()  # neither rerun's job reached the queue
    async with services.db.session() as s, s.begin():
        await s.execute(text("UPDATE run SET created_at = now() - interval '10 minutes'"))
    real = service._store_review_state

    async def store(s, run_id):
        if run_id == broken:
            raise ValueError("unparseable stored decision")
        await real(s, run_id)

    monkeypatch.setattr(service, "_store_review_state", store)
    caplog.set_level("WARNING", logger="corelata.service")
    failed, _ = await sweep_orphans(services.db, grace_s=120)
    assert sorted(failed) == sorted([broken_child, healthy_child])
    assert await state_of(services, broken_child) is RunState.FAILED
    assert await state_of(services, healthy_child) is RunState.FAILED
    assert (await _review(services, healthy)).child_state is RunState.FAILED
    warnings = [r.getMessage() for r in caplog.records if "could not record" in r.getMessage()]
    assert warnings == [
        f"sweep: could not record a rerun's end on run {broken}: unparseable stored decision"
    ]


async def test_a_lost_connection_still_fails_the_sweep(services, monkeypatch):
    await _returned(services)
    services.queue.jobs.clear()
    async with services.db.session() as s, s.begin():
        await s.execute(text("UPDATE run SET created_at = now() - interval '10 minutes'"))

    async def gone(s, run_id):
        raise DBAPIError("SELECT 1", {}, Exception("server closed"), connection_invalidated=True)

    monkeypatch.setattr(service, "_store_review_state", gone)
    with pytest.raises(DBAPIError):
        await sweep_orphans(services.db, grace_s=120)


async def state_of(services, run_id) -> RunState:
    return (await service.run_progress(services.db, run_id)).state


async def test_a_rerun_the_gate_rejects_frees_its_parent(services, fake_backend):
    parent, child = await _returned(services)
    fake_backend.script(
        "gate",
        json.dumps(
            {
                "supported": False,
                "substance": "insufficient",
                "reasons": ["The sources do not address the statement."],
                "evidence": [],
                "suggested_scope": "",
            }
        ),
    )
    await drain(services)
    assert await state_of(services, child) is RunState.GATE_REJECTED
    review = await _review(services, parent)
    assert review.child_run_id == str(child) and review.child_state is RunState.GATE_REJECTED
    again = await service.review_run(
        services.db,
        services.storage,
        services.queue,
        services.cfg,
        services.prompts,
        parent,
        ReviewAction.RETURN,
        note="try another angle",
    )
    assert again is not None and again != child


class _DownQueue:
    async def defer(
        self, task: str, *, lock: str | None = None, priority: int = 0, **kwargs: str
    ) -> None:
        raise ConnectionRefusedError("connection refused")


async def test_a_rerun_the_queue_refused_frees_the_parent(services):
    parent = await submit(services)
    await drain(services)
    with pytest.raises(ConnectionRefusedError):
        await service.review_run(
            services.db,
            services.storage,
            _DownQueue(),
            services.cfg,
            services.prompts,
            parent,
            ReviewAction.RETURN,
            note="x",
        )
    review = await _review(services, parent)
    assert review.child_state is RunState.FAILED
    assert review.child_error == "could not queue the run: connection refused"


async def test_a_run_without_a_parent_announces_only_itself(services, run_channel):
    run_id = await submit(services)
    await drain(services)
    sent = 2 * len((await service.run_progress(services.db, run_id)).stages) + 2
    assert await run_channel.received(sent) == [str(run_id)] * sent


async def test_parent_ids_are_sorted_distinct_and_skip_runs_without_one(services):
    first, c1 = await _returned(services)
    second, c2 = await _returned_in(services, "q")
    async with services.db.session() as s, s.begin():
        assert await runs.parent_ids(s, [c1, c2, c1, first]) == sorted([first, second])
        assert await runs.parent_ids(s, [first, second]) == []
        assert await runs.parent_ids(s, []) == []
