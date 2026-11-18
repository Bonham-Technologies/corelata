"""A return is spent only while its rerun is live or completed (CRL-34, R-M15-1, R-M15-3); an
accepted run cannot be returned (CRL-21, R-M16-1)."""

import asyncio
import uuid

import pytest
from docx import Document
from sqlalchemy import text

from corelata import service
from corelata.schema import ReviewAction, RunState
from corelata.store import runs
from corelata.store.models import ReviewEvent, utcnow
from tests.test_service import Svc, _set_state


@pytest.fixture
def svc(db, tmp_path, make_config):
    return Svc(db, tmp_path, make_config())


async def _completed(svc: Svc) -> tuple[uuid.UUID, uuid.UUID]:
    pid = await svc.project()
    run_id = await svc.run(pid, [await svc.source(pid)])
    await _set_state(svc.db, run_id, "completed")
    return pid, run_id


def _review(svc: Svc, run_id: uuid.UUID, action: ReviewAction, **kw):
    return service.review_run(
        svc.db, svc.storage, svc.queue, svc.cfg, svc.prompts, run_id, action, **kw
    )


async def _children(svc: Svc, pid: uuid.UUID, run_id: uuid.UUID) -> list[str]:
    return [
        r.run_id for r in await service.list_runs(svc.db, pid) if r.parent_run_id == str(run_id)
    ]


@pytest.mark.parametrize("ending", ["failed", "cancelled", "gate_rejected"])
async def test_a_run_whose_rerun_ended_without_a_report_can_be_returned_again(svc, ending):
    pid, run_id = await _completed(svc)
    first = await _review(svc, run_id, ReviewAction.RETURN, note="Tighten the scope", actor="ana")
    await _set_state(svc.db, first, ending)
    second = await _review(svc, run_id, ReviewAction.RETURN, note="Tighten it", actor="bob")
    assert second is not None and second != first
    assert sorted(await _children(svc, pid, run_id)) == sorted([str(first), str(second)])
    async with svc.db.session() as s:
        events = await runs.load_review_events(s, run_id)
    assert [(e.action, e.child_run_id, e.actor) for e in events] == [
        ("return", first, "ana"),  # the old event stays as the audit trail
        ("return", second, "bob"),
    ]
    with pytest.raises(service.ConflictError, match=f"already returned; its rerun is {second}"):
        await _review(svc, run_id, ReviewAction.RETURN, note="Once more")


@pytest.mark.parametrize("live", ["created", "drafting", "completed"])
async def test_a_live_or_completed_rerun_still_spends_the_return(svc, live):
    pid, run_id = await _completed(svc)
    child = await _review(svc, run_id, ReviewAction.RETURN, note="x")
    await _set_state(svc.db, child, live)
    with pytest.raises(service.ConflictError, match=str(child)):
        await _review(svc, run_id, ReviewAction.RETURN, note="y")
    assert await _children(svc, pid, run_id) == [str(child)]


async def test_accept_after_a_failed_rerun_is_allowed_and_decides(svc):
    _, run_id = await _completed(svc)
    child = await _review(svc, run_id, ReviewAction.RETURN, note="x", actor="ana")
    await _set_state(svc.db, child, "failed")
    assert await _review(svc, run_id, ReviewAction.ACCEPT, actor="bob") is None
    review = (await service.run_progress(svc.db, run_id)).review
    assert review is not None and (review.decision, review.actor) == ("accepted", "bob")
    assert review.child_run_id is None


async def test_two_returns_at_once_after_a_failed_rerun_make_one_live_rerun(svc):
    pid, run_id = await _completed(svc)
    first = await _review(svc, run_id, ReviewAction.RETURN, note="x")
    await _set_state(svc.db, first, "failed")
    results = await asyncio.gather(
        _review(svc, run_id, ReviewAction.RETURN, note="a", actor="ana"),
        _review(svc, run_id, ReviewAction.RETURN, note="b", actor="bob"),
        return_exceptions=True,
    )
    made = [r for r in results if isinstance(r, uuid.UUID)]
    refused = [r for r in results if isinstance(r, service.ConflictError)]
    assert len(made) == 1 and len(refused) == 1, results
    assert f"its rerun is {made[0]}" in str(refused[0])
    assert sorted(await _children(svc, pid, run_id)) == sorted([str(first), str(made[0])])
    review = (await service.run_progress(svc.db, run_id)).review
    assert review is not None and review.child_run_id == str(made[0])
    assert review.child_state is None


async def test_a_return_cancelled_inside_its_transaction_leaves_nothing_behind(
    svc, monkeypatch, tmp_path
):
    pid, run_id = await _completed(svc)
    reference = tmp_path / "house.docx"
    Document().save(str(reference))
    svc.storage.put("reference/house.docx", reference.read_bytes())
    async with svc.db.session() as s, s.begin():
        (await runs.get_run(s, run_id, lock=True)).docx_reference_key = "reference/house.docx"
    reached, never = asyncio.Event(), asyncio.Event()
    real = runs.add_review_event

    async def stall(s, rid, action, *args):
        if action == ReviewAction.RETURN.value:
            reached.set()
            await never.wait()  # the request is cancelled here: the rerun row is flushed
        return await real(s, rid, action, *args)

    monkeypatch.setattr(runs, "add_review_event", stall)
    task = asyncio.create_task(_review(svc, run_id, ReviewAction.RETURN, note="x"))
    await reached.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    monkeypatch.undo()
    async with svc.db.session() as s:
        assert await runs.load_review_events(s, run_id) == []
    assert await _children(svc, pid, run_id) == []
    assert svc.storage.list_keys("runs/") == []  # the rerun's reference copy went
    assert (await service.run_progress(svc.db, run_id)).review is None
    child = await _review(svc, run_id, ReviewAction.RETURN, note="again")
    assert await _children(svc, pid, run_id) == [str(child)]


def _event(action: str, at, child=None, note="") -> ReviewEvent:
    return ReviewEvent(action=action, note=note, actor=action, child_run_id=child, at=at)


def test_review_state_follows_the_reruns_fate():
    t = [utcnow() for _ in range(4)]
    a, b = uuid.uuid4(), uuid.uuid4()
    accepted = _event("accept", t[0])
    failed = _event("return", t[1], a, note="first note")
    live = _event("return", t[2], b, note="second note")
    later_accept = _event("accept", t[3])
    gone = {a: (RunState.FAILED, "could not queue the run: refused")}

    state = service._review_state([accepted, failed], gone)
    assert state is not None and state.decision == "returned" and state.note == "first note"
    assert (state.child_run_id, state.child_state, state.child_error) == (
        str(a),
        RunState.FAILED,
        "could not queue the run: refused",
    )
    # an accept after the failed rerun decides
    state = service._review_state([accepted, failed, later_accept], gone)
    assert state is not None and state.decision == "accepted" and state.at == t[3]
    # a live return wins over any accept, before or after it
    running = {**gone, b: (RunState.DRAFTING, None)}
    state = service._review_state([accepted, failed, live, later_accept], running)
    assert state is not None and state.decision == "returned" and state.child_run_id == str(b)
    assert state.child_state is None and state.note == "second note"
    # a completed rerun is recorded as ended, and still spends the return
    done = {**gone, b: (RunState.COMPLETED, None)}
    state = service._review_state([accepted, failed, live, later_accept], done)
    assert state is not None and state.child_state is RunState.COMPLETED
    assert service._live_return([accepted, failed, live], done) is live
    assert service._live_return([accepted, failed], gone) is None


ACCEPTED = "was accepted; start a new run to change it"


async def _events(svc: Svc, run_id: uuid.UUID) -> list[tuple[str, str | None]]:
    async with svc.db.session() as s:
        return [(e.action, e.actor) for e in await runs.load_review_events(s, run_id)]


async def test_an_accepted_run_cannot_be_returned(svc):
    pid, run_id = await _completed(svc)
    assert await _review(svc, run_id, ReviewAction.ACCEPT, actor="ana") is None
    jobs = list(svc.queue.jobs)
    with pytest.raises(service.ConflictError) as refused:
        await _review(svc, run_id, ReviewAction.RETURN, note="Tighten the scope", actor="bob")
    assert str(refused.value) == f"run {run_id} {ACCEPTED}"
    assert await _children(svc, pid, run_id) == []
    assert svc.queue.jobs == jobs  # nothing queued
    assert await _events(svc, run_id) == [("accept", "ana")]  # nothing recorded
    review = (await service.run_progress(svc.db, run_id)).review
    assert review is not None and (review.decision, review.actor) == ("accepted", "ana")


async def test_a_return_needs_its_note_before_the_accept_is_considered(svc):
    _, run_id = await _completed(svc)
    await _review(svc, run_id, ReviewAction.ACCEPT)
    with pytest.raises(service.InvalidRequestError, match="needs a note"):
        await _review(svc, run_id, ReviewAction.RETURN, note="  ")


async def test_accept_after_accept_is_still_allowed_and_the_latest_decides(svc):
    _, run_id = await _completed(svc)
    await _review(svc, run_id, ReviewAction.ACCEPT, actor="ana")
    assert await _review(svc, run_id, ReviewAction.ACCEPT, actor="bob") is None
    review = (await service.run_progress(svc.db, run_id)).review
    assert review is not None and (review.decision, review.actor) == ("accepted", "bob")


@pytest.mark.parametrize("ending", ["failed", "cancelled", "gate_rejected"])
async def test_an_accept_after_a_freed_return_closes_the_run(svc, ending):
    pid, run_id = await _completed(svc)
    first = await _review(svc, run_id, ReviewAction.RETURN, note="x", actor="ana")
    await _set_state(svc.db, first, ending)
    assert await _review(svc, run_id, ReviewAction.ACCEPT, actor="bob") is None  # as in M15
    with pytest.raises(service.ConflictError, match=ACCEPTED):
        await _review(svc, run_id, ReviewAction.RETURN, note="y")
    assert await _children(svc, pid, run_id) == [str(first)]


async def test_a_live_return_still_wins_over_a_later_accept_and_refuses_by_its_own_rule(svc):
    pid, run_id = await _completed(svc)
    child = await _review(svc, run_id, ReviewAction.RETURN, note="x", actor="ana")
    assert await _review(svc, run_id, ReviewAction.ACCEPT, actor="bob") is None
    review = (await service.run_progress(svc.db, run_id)).review
    assert review is not None and review.decision == "returned"  # R-M9-1, unchanged
    with pytest.raises(service.ConflictError, match=f"already returned; its rerun is {child}"):
        await _review(svc, run_id, ReviewAction.RETURN, note="y")
    # once that rerun fails, the later accept is the decision, and it closes the run
    await _set_state(svc.db, child, "failed")
    async with svc.db.session() as s, s.begin():
        await service._store_review_state(s, run_id)  # what the worker's ending path does
    with pytest.raises(service.ConflictError, match=ACCEPTED):
        await _review(svc, run_id, ReviewAction.RETURN, note="z")
    assert await _children(svc, pid, run_id) == [str(child)]


# Sessions that the holder's backend blocks: a waiter on another test's lock in the same
# database does not count (CRL-40).
_BLOCKED_BY = text(
    "SELECT count(*) FROM pg_stat_activity "
    "WHERE datname = current_database() AND :holder = ANY(pg_blocking_pids(pid))"
)


class _Held:
    """The review recording `action` stops inside its transaction, the run's row lock held,
    until `release` is set; `holder` is that session's backend pid."""

    def __init__(self) -> None:
        self.reached, self.release = asyncio.Event(), asyncio.Event()
        self.holder: int | None = None

    async def until_another_session_waits(self, svc: Svc) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 10
        while True:
            async with svc.db.session() as s:
                if await s.scalar(_BLOCKED_BY, {"holder": self.holder}):
                    return
            assert loop.time() < deadline, "no session waited for the run's row lock"
            await asyncio.sleep(0.02)


def _hold(monkeypatch, action: ReviewAction) -> _Held:
    held = _Held()
    real = runs.add_review_event

    async def holding(s, rid, recorded, *args):
        if recorded == action.value:
            held.holder = await s.scalar(text("SELECT pg_backend_pid()"))
            held.reached.set()
            await held.release.wait()
        return await real(s, rid, recorded, *args)

    monkeypatch.setattr(runs, "add_review_event", holding)
    return held


async def test_a_return_that_waits_for_an_accepts_lock_is_refused(svc, monkeypatch):
    pid, run_id = await _completed(svc)
    held = _hold(monkeypatch, ReviewAction.ACCEPT)
    accept = asyncio.create_task(_review(svc, run_id, ReviewAction.ACCEPT, actor="ana"))
    await held.reached.wait()  # the accept holds the row lock and has not committed
    returning = asyncio.create_task(_review(svc, run_id, ReviewAction.RETURN, note="x"))
    await held.until_another_session_waits(svc)  # the return waits for that lock
    held.release.set()
    assert await accept is None
    with pytest.raises(service.ConflictError, match=ACCEPTED):
        await returning  # it decided on the decision committed while it waited
    assert await _children(svc, pid, run_id) == []
    assert await _events(svc, run_id) == [("accept", "ana")]


async def test_an_accept_that_waits_for_a_returns_lock_leaves_the_report_returned(svc, monkeypatch):
    pid, run_id = await _completed(svc)
    held = _hold(monkeypatch, ReviewAction.RETURN)
    returning = asyncio.create_task(_review(svc, run_id, ReviewAction.RETURN, note="x"))
    await held.reached.wait()
    accept = asyncio.create_task(_review(svc, run_id, ReviewAction.ACCEPT, actor="bob"))
    await held.until_another_session_waits(svc)
    held.release.set()
    child = await returning
    assert await accept is None
    assert await _children(svc, pid, run_id) == [str(child)]
    review = (await service.run_progress(svc.db, run_id)).review
    assert review is not None and review.decision == "returned"
    assert review.child_run_id == str(child)
