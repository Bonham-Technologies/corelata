import uuid
from datetime import timedelta

import pytest

from corelata.schema import CandidateStatement, DiscoveryResult, DiscoveryState
from corelata.store import discoveries, runs
from corelata.testing.sources import text_source


async def _project_with_sources(s, n=2, name="p"):
    project = await runs.get_or_create_project(s, name)
    rows = [
        await runs.add_source(s, project.id, text_source(f"x{i}", f"text {i}"), storage_key=f"k{i}")
        for i in range(n)
    ]
    return project, rows


async def test_create_get_and_view(db):
    async with db.session() as s, s.begin():
        project, (a, b) = await _project_with_sources(s)
        row = await discoveries.create(
            s, project_id=project.id, source_ids=[b.id, a.id], audience_hint="shippers"
        )
    async with db.session() as s, s.begin():
        got = await discoveries.get(s, row.id, lock=True)
        assert got.state == "created" and got.audience_hint == "shippers"
        assert await discoveries.source_ids(s, row.id) == [b.id, a.id]
        view = await discoveries.view(s, row.id, deadline_s=90, start_deadline_s=120)
    assert view.state is DiscoveryState.CREATED and view.candidates == [] and view.usage is None
    assert view.source_ids == [str(b.id), str(a.id)] and view.project_id == str(project.id)
    assert view.discovery_id == str(row.id) and view.created_at.tzinfo is not None
    assert view.deadline_at == view.created_at + timedelta(seconds=120)  # not started: the start's
    async with db.session() as s:
        with pytest.raises(runs.NotFoundError, match="not found"):
            await discoveries.get(s, uuid.uuid4())
        with pytest.raises(runs.NotFoundError, match="not found"):
            await discoveries.view(s, uuid.uuid4(), deadline_s=90, start_deadline_s=120)


async def test_create_rejects_a_foreign_source(db):
    async with db.session() as s, s.begin():
        project, (a, _) = await _project_with_sources(s, name="p1")
        _, (foreign, _) = await _project_with_sources(s, name="p2")
        with pytest.raises(runs.NotFoundError, match="not in project"):
            await discoveries.create(
                s, project_id=project.id, source_ids=[a.id, foreign.id], audience_hint=""
            )


async def test_candidates_replace_earlier_ones(db):
    result = DiscoveryResult(
        candidates=[
            CandidateStatement(text="A", audience="ops", evidence=["src1/u1"], confidence_note="n"),
            CandidateStatement(text="B", audience="ops"),
        ]
    )
    async with db.session() as s, s.begin():
        project, (a, _) = await _project_with_sources(s)
        row = await discoveries.create(
            s, project_id=project.id, source_ids=[a.id], audience_hint=""
        )
        await discoveries.set_candidates(s, row.id, result)
        await discoveries.set_candidates(s, row.id, result)
    async with db.session() as s:
        view = await discoveries.view(s, row.id, deadline_s=600, start_deadline_s=3600)
    assert view.candidates == result.candidates


async def test_the_deadline_follows_the_state(db):
    """`deadline_at` is the limit that applies (R-M17-27): the start limit until the worker claims
    the discovery, the work limit from the claim on, ended or not."""
    async with db.session() as s, s.begin():
        project, (a, _) = await _project_with_sources(s)
        row = await discoveries.create(
            s, project_id=project.id, source_ids=[a.id], audience_hint=""
        )
    limits = {"deadline_s": 600, "start_deadline_s": 3600}
    async with db.session() as s, s.begin():
        got = await discoveries.get(s, row.id, lock=True)
        got.state, got.finished_at = "failed", got.created_at + timedelta(hours=1)
    async with db.session() as s:
        never_started = await discoveries.view(s, row.id, **limits)
    assert never_started.deadline_at == never_started.created_at + timedelta(seconds=3600)
    async with db.session() as s, s.begin():
        got = await discoveries.get(s, row.id, lock=True)
        got.state, got.started_at = "running", got.created_at + timedelta(minutes=9)
        got.finished_at = None
    async with db.session() as s:
        running = await discoveries.view(s, row.id, **limits)
    assert running.deadline_at == running.created_at + timedelta(minutes=19)
    async with db.session() as s, s.begin():
        got = await discoveries.get(s, row.id, lock=True)
        got.state, got.finished_at = "completed", got.created_at + timedelta(minutes=12)
    async with db.session() as s:
        ended = await discoveries.view(s, row.id, **limits)
    assert ended.deadline_at == ended.started_at + timedelta(seconds=600)
