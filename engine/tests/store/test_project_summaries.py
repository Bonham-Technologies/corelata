"""The sidebar's project summaries (M18 spec §7.1, R-M18-3) and the run list's decision (§7.2)."""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import event

from corelata import service
from corelata.store import runs
from tests.store.test_runs import T0, _project_with_source, _run


def _review(decision: str, child_state: str | None = None) -> dict:
    """A stored ReviewState (`service._review_state`'s shape)."""
    return {
        "decision": decision,
        "at": "2026-10-20T10:00:00Z",
        "actor": "ana",
        "child_run_id": str(uuid.uuid4()) if decision == "returned" else None,
        "child_state": child_state,
        "child_error": None,
        "note": "n" if decision == "returned" else None,
    }


async def _runs_in(s, project, source, rows: list[tuple[str, dict | None]]) -> list[uuid.UUID]:
    """One run per (state, review_state), created a minute apart in that order from T0; a
    terminal run finished 30 s after it was created. The project and its source are an hour
    older than the first run."""
    project.created_at = source.created_at = T0 - timedelta(hours=1)
    ids = []
    for i, (state, review) in enumerate(rows):
        run = await _run(s, project, [source], created_at=T0 + timedelta(minutes=i))
        run.state = state
        run.review_state = review
        if state in ("completed", "gate_rejected", "failed", "cancelled"):
            run.finished_at = T0 + timedelta(minutes=i, seconds=30)
        ids.append(run.id)
    await s.flush()
    return ids


async def test_the_summary_counts_writing_and_to_review_and_finds_the_newest_run(db):
    async with db.session() as s, s.begin():
        project, source = await _project_with_source(s, "mixed")
        ids = await _runs_in(
            s,
            project,
            source,
            [
                ("completed", None),  # to review
                ("completed", _review("accepted")),  # decided
                ("completed", _review("returned", "failed")),  # its revision failed: to review
                ("completed", _review("returned", "gate_rejected")),  # to review
                ("completed", _review("returned", "cancelled")),  # to review
                ("completed", _review("returned", None)),  # its revision is being written
                ("completed", _review("returned", "completed")),  # revised: nothing to review
                ("failed", None),
                ("gate_rejected", None),
                ("drafting", None),  # writing
                ("created", None),  # writing, and the newest
            ],
        )
    async with db.session() as s:
        [(found, summary)] = await runs.project_summaries(s)
    assert found.id == project.id
    assert (summary.reports_writing, summary.reports_to_review) == (2, 4)
    assert summary.latest_run is not None
    assert (summary.latest_run.run_id, summary.latest_run.state) == (str(ids[-1]), "created")
    # the newest stamp: the newest run's created_at (+10 min), after every finished_at
    assert summary.last_activity_at == T0 + timedelta(minutes=10)


async def test_a_finish_after_the_newest_creation_is_the_last_activity(db):
    async with db.session() as s, s.begin():
        project, source = await _project_with_source(s)
        await _runs_in(s, project, source, [("completed", None)])
    async with db.session() as s:
        [(_, summary)] = await runs.project_summaries(s)
    assert summary.last_activity_at == T0 + timedelta(seconds=30)


async def test_an_empty_project_and_a_project_with_sources_only(db):
    async with db.session() as s, s.begin():
        empty = await runs.get_or_create_project(s, "empty")
        sourced, source = await _project_with_source(s, "sources only")
        source.created_at = sourced.created_at + timedelta(hours=1)
        await s.flush()
    async with db.session() as s:
        summaries = {p.name: summary for p, summary in await runs.project_summaries(s)}
    assert summaries["empty"].model_dump() == {
        "last_activity_at": empty.created_at,
        "reports_writing": 0,
        "reports_to_review": 0,
        "latest_run": None,
    }
    assert summaries["sources only"].last_activity_at == source.created_at
    assert summaries["sources only"].latest_run is None
    assert service.new_project_summary(empty) == summaries["empty"]


async def test_the_latest_run_carries_its_status_and_decision_and_breaks_a_tie_by_id(db):
    async with db.session() as s, s.begin():
        project, source = await _project_with_source(s)
        ids = await _runs_in(s, project, source, [("completed", None), ("completed", None)])
        for run_id in ids:  # the same microsecond: the larger id is the newer (CRL-24)
            run = await runs.get_run(s, run_id)
            run.created_at, run.status, run.review_state = T0, "clean", _review("accepted")
    async with db.session() as s:
        [(_, summary)] = await runs.project_summaries(s)
    assert summary.latest_run is not None
    assert summary.latest_run.model_dump() == {
        "run_id": str(max(ids)),
        "state": "completed",
        "status": "clean",
        "decision": "accepted",
        "child_state": None,
    }
    assert summary.reports_to_review == 0


async def test_the_summaries_take_three_statements_however_many_projects(db):
    statements: list[str] = []

    def count(conn, cursor, statement, *args):
        statements.append(statement)

    made = 0
    for n in (1, 20):
        async with db.session() as s, s.begin():
            while made < n:
                project, source = await _project_with_source(s, f"p{made}")
                await _runs_in(s, project, source, [("completed", None), ("drafting", None)])
                made += 1
        event.listen(db.engine.sync_engine, "before_cursor_execute", count)
        try:
            async with db.session() as s:
                found = await runs.project_summaries(s)
        finally:
            event.remove(db.engine.sync_engine, "before_cursor_execute", count)
        assert len(found) == n
        assert all(summary.reports_writing == 1 for _, summary in found)
        assert len(statements) == 3, statements
        statements.clear()


async def test_one_projects_summary_and_a_missing_project(db):
    async with db.session() as s, s.begin():
        a, source = await _project_with_source(s, "a")
        await _runs_in(s, a, source, [("drafting", None)])
        await _project_with_source(s, "b")
    async with db.session() as s:
        [(found, summary)] = await runs.project_summaries(s, a.id)
        assert (found.name, summary.reports_writing) == ("a", 1)
        assert await runs.project_summaries(s, uuid.uuid4()) == []
    assert (await service.get_project_summary(db, a.id))[1].reports_writing == 1
    assert [p.name for p, _ in await service.list_project_summaries(db)] == ["a", "b"]
    with pytest.raises(runs.NotFoundError, match="not found"):
        await service.get_project_summary(db, uuid.uuid4())


def test_the_summary_frees_a_return_by_the_services_rule():
    assert runs.FREED_BY == service.FREED_BY  # R-M15-1: failed, cancelled, gate_rejected


async def test_a_run_summary_carries_the_stored_decision_and_the_revisions_end(db):
    async with db.session() as s, s.begin():
        project, source = await _project_with_source(s)
        await _runs_in(
            s, project, source, [("completed", None), ("completed", _review("returned", "failed"))]
        )
    newest, oldest = await service.list_runs(db, project.id)
    assert (newest.review_decision, newest.review_child_state) == ("returned", "failed")
    assert (oldest.review_decision, oldest.review_child_state) == (None, None)


async def test_the_latest_run_carries_its_revisions_end(db):
    async with db.session() as s, s.begin():
        project, source = await _project_with_source(s)
        await _runs_in(s, project, source, [("completed", _review("returned", "failed"))])
    async with db.session() as s:
        [(_, summary)] = await runs.project_summaries(s)
    assert summary.latest_run is not None
    assert (summary.latest_run.decision, summary.latest_run.child_state) == ("returned", "failed")
    assert summary.reports_to_review == 1
