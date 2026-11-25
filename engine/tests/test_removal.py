"""CRL-125: removing a source added by mistake, or a whole project, from the command line."""

import asyncio
import json
import logging
import uuid

import boto3
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from corelata import removal, service
from corelata.config import S3StorageConfig
from corelata.schema import DiscoveryState, RunKind, RunState, StageResult
from corelata.storage import S3Storage, StorageError
from corelata.store import runs
from corelata.store.models import (
    ClaimRow,
    Discovery,
    DiscoverySource,
    ExportRow,
    LLMCall,
    Project,
    ReviewEvent,
    Run,
    RunSource,
    SourceRow,
    SourceUnitRow,
    StageResultRow,
)
from tests.ingest.test_coglossa import export as coglossa_export
from tests.test_service import PORT_TEXT, Svc
from tests.test_storage_s3 import BUCKET, s3  # noqa: F401 - the fixture


@pytest.fixture
def svc(db, tmp_path, make_config):
    return Svc(db, tmp_path, make_config())


async def _set_state(db, run_id, state: str = "completed") -> None:
    async with db.session() as s, s.begin():
        run = await runs.get_run(s, run_id, lock=True)
        run.state = state


async def _completed_run(svc, pid, source_ids, **kw) -> uuid.UUID:
    """A completed run with something in every table a run owns, and an export on storage."""
    run_id = await svc.run(pid, source_ids, **kw)
    await _set_state(svc.db, run_id)
    key = f"runs/{run_id}/report.md"
    svc.storage.put(key, b"# report")
    async with svc.db.session() as s, s.begin():
        await runs.add_export(s, run_id, "report.md", key, b"# report")
        s.add(ClaimRow(run_id=run_id, claim_id="c1", text="t", kind="judgment"))
        await runs.add_review_event(s, run_id, "accept", "", None, None)
    return run_id


async def _count(db, model, *where) -> int:
    async with db.session() as s:
        return await s.scalar(select(func.count()).select_from(model).where(*where))


async def _discovery(svc, pid, source_ids, state=DiscoveryState.COMPLETED) -> uuid.UUID:
    did = await service.start_discovery(svc.db, svc.queue, pid, source_ids)
    async with svc.db.session() as s, s.begin():
        (await s.get(Discovery, did)).state = state.value
    return did


async def test_a_source_nothing_used_goes_with_its_units_and_its_file(svc, tmp_path):
    pid = await svc.project()
    sid = await svc.source(pid)
    keep = await svc.source(pid, text="Another text entirely.", name="other.txt")
    plan = await removal.plan_source(svc.db, sid)
    assert plan.prefixes == (f"projects/{pid}/sources/{sid}/",) and not plan.runs
    done = await removal.delete_source(svc.db, svc.storage, sid, expected=plan)
    assert done == plan
    assert removal.summary(done) == (
        f"source {sid} (port.txt) of project 'p': 1 source, 0 runs, 0 discoveries"
    )
    assert await _count(svc.db, SourceRow, SourceRow.id == sid) == 0
    assert await _count(svc.db, SourceUnitRow, SourceUnitRow.source_id == sid) == 0
    sources = tmp_path / "files" / "projects" / str(pid) / "sources"
    assert [p.name for p in sources.iterdir()] == [str(keep)]
    assert await _count(svc.db, SourceRow, SourceRow.id == keep) == 1
    with pytest.raises(runs.NotFoundError, match=f"source {sid} not found"):
        await removal.delete_source(svc.db, svc.storage, sid)
    with pytest.raises(runs.NotFoundError, match=f"source {sid} not found"):
        await removal.plan_source(svc.db, sid)


async def test_a_coglossa_export_and_its_guide_go_together(svc, tmp_path):
    pid = await svc.project()
    data = json.dumps(coglossa_export()).encode("utf-8")
    main, guide = await service.add_source(
        svc.db, svc.storage, pid, "letter.coglossa.json", data, coglossa_export=True
    )
    done = await removal.delete_source(svc.db, svc.storage, guide)
    assert [i.id for i in done.sources] == [guide, main]  # the one asked for first
    assert await _count(svc.db, SourceRow, SourceRow.project_id == pid) == 0
    assert not (tmp_path / "files" / "projects").exists()  # emptied directories go too


async def test_a_source_a_run_used_is_refused_without_with_runs(svc, tmp_path):
    pid = await svc.project()
    sid = await svc.source(pid)
    run_ids = [await _completed_run(svc, pid, [sid]) for _ in range(6)]
    with pytest.raises(service.ConflictError) as refused:
        await removal.delete_source(svc.db, svc.storage, sid)
    message = str(refused.value)
    assert message.startswith(f"source {sid} (port.txt) was used by 6 runs: {run_ids[0]}, ")
    assert message.endswith(
        " and 1 more; add --with-runs to delete those runs and their reports too"
    )
    assert await _count(svc.db, SourceRow, SourceRow.id == sid) == 1
    assert await _count(svc.db, Run, Run.project_id == pid) == 6
    assert (tmp_path / "files" / "projects" / str(pid) / "sources" / str(sid)).is_dir()
    assert (tmp_path / "files" / "runs" / str(run_ids[0]) / "report.md").is_file()


async def test_the_report_a_check_run_audited_counts_as_used(svc, tmp_path):
    """CRL-94: a check run's report is not one of its sources (`run_source`) but its own column;
    deleting it alone is refused like a used source, and `--with-runs` takes the check run."""
    pid = await svc.project()
    report = await svc.source(pid, text="The port will very likely close. " * 3, name="r.txt")
    sid = await svc.source(pid)
    check = await _completed_run(svc, pid, [sid], kind=RunKind.CHECK, report_source_id=report)
    with pytest.raises(service.ConflictError, match=f"was used by 1 run: {check};"):
        await removal.delete_source(svc.db, svc.storage, report)
    assert await _count(svc.db, Run, Run.id == check) == 1
    assert [(i.name, i.runs) for i in await removal.list_sources(svc.db, "p")] == [
        ("r.txt", 1),
        ("port.txt", 1),
    ]
    done = await removal.delete_source(svc.db, svc.storage, report, with_runs=True)
    assert [r.id for r in done.runs] == [check]
    assert await _count(svc.db, Run, Run.project_id == pid) == 0
    assert await _count(svc.db, SourceRow, SourceRow.id == sid) == 1
    assert not (tmp_path / "files" / "runs" / str(check)).exists()


async def test_with_runs_takes_the_runs_everything_they_own_and_the_discoveries(svc, tmp_path):
    pid = await svc.project()
    sid = await svc.source(pid)
    other = await svc.source(pid, text="Another text entirely.", name="other.txt")
    used = await _completed_run(svc, pid, [sid, other])
    child = await svc.run(pid, [other], parent_run_id=used)  # did not use the source: stays
    await _set_state(svc.db, child, "failed")
    untouched = await _completed_run(svc, pid, [other])
    gone_discovery = await _discovery(svc, pid, [other, sid])
    kept_discovery = await _discovery(svc, pid, [other])
    async with svc.db.session() as s, s.begin():
        await runs.add_stage(
            s,
            used,
            0,
            StageResult(
                stage="ingesting",
                iteration=0,
                ok=True,
                started_at=await runs.db_now(s),
                finished_at=await runs.db_now(s),
            ),
        )
    done = await removal.delete_source(svc.db, svc.storage, sid, with_runs=True)
    assert [r.id for r in done.runs] == [used]
    assert [d.id for d in done.discoveries] == [gone_discovery]
    assert done.prefixes == (f"projects/{pid}/sources/{sid}/", f"runs/{used}/")
    for model in (StageResultRow, ExportRow, ClaimRow, ReviewEvent, RunSource, LLMCall):
        assert await _count(svc.db, model, model.run_id == used) == 0
    assert await _count(svc.db, Run, Run.id == used) == 0
    assert not (tmp_path / "files" / "runs" / str(used)).exists()
    assert (tmp_path / "files" / "runs" / str(untouched) / "report.md").is_file()
    async with svc.db.session() as s:
        assert (await runs.get_run(s, child)).parent_run_id is None
        assert {r.id for r in await runs.list_sources(s, pid)} == {other}
        assert await s.get(Discovery, gone_discovery) is None
        assert await s.get(Discovery, kept_discovery) is not None
    assert await _count(svc.db, DiscoverySource, DiscoverySource.source_id == sid) == 0


@pytest.mark.parametrize("state", ["created", "drafting"])
async def test_a_run_that_has_not_ended_is_refused_even_with_runs(svc, state):
    pid = await svc.project()
    sid = await svc.source(pid)
    run_id = await svc.run(pid, [sid])
    await _set_state(svc.db, run_id, state)
    with pytest.raises(service.ConflictError, match=f"1 run not ended yet: {run_id}; cancel"):
        await removal.delete_source(svc.db, svc.storage, sid, with_runs=True)
    with pytest.raises(service.ConflictError, match="1 run not ended yet"):
        await removal.delete_project(svc.db, svc.storage, "p")
    assert await _count(svc.db, Run, Run.id == run_id) == 1


async def test_a_discovery_that_has_not_ended_is_refused(svc):
    pid = await svc.project()
    sid = await svc.source(pid)
    did = await _discovery(svc, pid, [sid], DiscoveryState.RUNNING)
    with pytest.raises(service.ConflictError, match=f"1 discovery not ended yet: {did}"):
        await removal.delete_source(svc.db, svc.storage, sid)
    other = await _discovery(svc, pid, [sid], DiscoveryState.CREATED)
    with pytest.raises(service.ConflictError, match="2 discoveries not ended yet"):
        await removal.delete_project(svc.db, svc.storage, "p")
    assert await _count(svc.db, Discovery, Discovery.id.in_([did, other])) == 2


async def test_a_project_goes_with_everything_in_it(svc, tmp_path, caplog):
    pid = await svc.project()
    sid = await svc.source(pid)
    run_id = await _completed_run(svc, pid, [sid])
    did = await _discovery(svc, pid, [sid])
    other = await svc.project("other")
    kept = await svc.source(other)  # the same file in another project is its own
    kept_run = await _completed_run(svc, other, [kept])
    plan = await removal.plan_project(svc.db, "p")
    with caplog.at_level(logging.INFO, logger="corelata.removal"):
        done = await removal.delete_project(svc.db, svc.storage, "p", expected=plan)
    assert done == plan and done.prefixes == (f"projects/{pid}/", f"runs/{run_id}/")
    assert removal.summary(done) == f"project 'p' ({pid}): 1 source, 1 run, 1 discovery"
    for model, where in (
        (Project, Project.id == pid),
        (SourceRow, SourceRow.project_id == pid),
        (Run, Run.project_id == pid),
        (Discovery, Discovery.id == did),
        (ExportRow, ExportRow.run_id == run_id),
    ):
        assert await _count(svc.db, model, where) == 0
    files = tmp_path / "files"
    assert not (files / "projects" / str(pid)).exists()
    assert not (files / "runs" / str(run_id)).exists()
    assert (files / "projects" / str(other) / "sources" / str(kept)).is_dir()
    assert (files / "runs" / str(kept_run) / "report.md").is_file()
    assert await _count(svc.db, Run, Run.project_id == other) == 1
    assert await _count(svc.db, ExportRow, ExportRow.run_id == kept_run) == 1
    [line] = [r.getMessage() for r in caplog.records if r.name == "corelata.removal"]
    assert line == (
        f"deleted project 'p' ({pid}): 1 source, 1 run, 1 discovery; sources [{sid}]; "
        f"runs [{run_id}]; discoveries [{did}]; stored files [projects/{pid}/, runs/{run_id}/]"
    )
    with pytest.raises(runs.NotFoundError, match="project 'p' not found"):
        await removal.delete_project(svc.db, svc.storage, "p")


async def test_every_removed_run_is_announced_on_the_run_channel(svc, run_channel):
    """An open progress page's poller reads the run, finds it gone and sends `event: deleted`
    (CRL-22); the announcement comes when the removal commits."""
    pid = await svc.project()
    sid = await svc.source(pid)
    first = await _completed_run(svc, pid, [sid])
    second = await _completed_run(svc, pid, [sid])
    assert await run_channel.received() == []
    await removal.delete_source(svc.db, svc.storage, sid, with_runs=True)
    assert sorted(await run_channel.received(2)) == sorted([str(first), str(second)])
    other = await _completed_run(svc, pid, [await svc.source(pid, name="b.txt", text="Other.")])
    await removal.delete_project(svc.db, svc.storage, "p")
    assert await run_channel.received(1) == [str(other)]


async def test_what_changed_since_it_was_listed_is_not_deleted(svc):
    pid = await svc.project()
    sid = await svc.source(pid)
    plan = await removal.plan_source(svc.db, sid)
    run_id = await _completed_run(svc, pid, [sid])
    with pytest.raises(service.ConflictError, match="changed since it was listed"):
        await removal.delete_source(svc.db, svc.storage, sid, with_runs=True, expected=plan)
    project_plan = await removal.plan_project(svc.db, "p")
    await svc.source(pid, name="b.txt", text="Other.")
    with pytest.raises(service.ConflictError, match="changed since it was listed"):
        await removal.delete_project(svc.db, svc.storage, "p", expected=project_plan)
    assert await _count(svc.db, Run, Run.id == run_id) == 1


async def test_a_storage_failure_deletes_no_row_and_running_it_again_finishes(svc, monkeypatch):
    pid = await svc.project()
    sid = await svc.source(pid)
    run_id = await _completed_run(svc, pid, [sid])
    real = svc.storage.delete_prefix
    calls: list[str] = []

    def flaky(prefix: str) -> None:
        calls.append(prefix)
        if prefix.startswith("runs/"):
            raise StorageError(f"cannot delete {prefix}: disk on fire")
        real(prefix)

    monkeypatch.setattr(svc.storage, "delete_prefix", flaky)
    with pytest.raises(StorageError, match="disk on fire"):
        await removal.delete_project(svc.db, svc.storage, "p")
    assert calls == [f"projects/{pid}/", f"runs/{run_id}/"]
    assert await _count(svc.db, Run, Run.id == run_id) == 1
    assert await _count(svc.db, SourceRow, SourceRow.id == sid) == 1  # its file is gone already
    monkeypatch.setattr(svc.storage, "delete_prefix", real)
    await removal.delete_project(svc.db, svc.storage, "p")
    assert await _count(svc.db, Project, Project.id == pid) == 0


_BLOCKED_BY = text(
    "SELECT count(*) FROM pg_stat_activity "
    "WHERE datname = current_database() AND :holder = ANY(pg_blocking_pids(pid))"
)


async def _until_blocked_by(db, holder: int) -> None:
    """Until another session in this database waits for a lock `holder`'s backend holds."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 10
    while True:
        async with db.session() as watch:
            if await watch.scalar(_BLOCKED_BY, {"holder": holder}):
                return
        assert loop.time() < deadline, "the removal never waited for the lock"
        await asyncio.sleep(0.02)


async def test_a_removal_that_loses_a_deadlock_deletes_no_file(svc, tmp_path):
    """A return locks its run, then inserts the rerun into the project (KEY SHARE); a removal
    locks the project, then deletes the run. When the two meet, Postgres aborts the one that
    waited first, the removal: its rows stay, and so must every stored file; the operator is
    told to try again (status 2)."""
    pid = await svc.project()
    sid = await svc.source(pid)
    run_id = await _completed_run(svc, pid, [sid])
    files = tmp_path / "files"
    async with svc.db.session() as s, s.begin():
        holder = await s.scalar(text("SELECT pg_backend_pid()"))
        await runs.get_run(s, run_id, lock=True)  # as review_run does
        removing = asyncio.create_task(removal.delete_project(svc.db, svc.storage, "p"))
        await _until_blocked_by(svc.db, holder)  # it holds the project, waits for the run
        s.add(Discovery(project_id=pid))  # the rerun's insert into the project
        await s.flush()
    with pytest.raises(
        service.ConflictError, match=r"\(deadlock\); nothing was deleted, try again"
    ):
        await removing
    assert await _count(svc.db, Run, Run.id == run_id) == 1
    assert (files / "runs" / str(run_id) / "report.md").is_file()
    assert (files / "projects" / str(pid) / "sources" / str(sid)).is_dir()


async def test_another_database_error_is_not_called_a_lost_lock():
    with pytest.raises(DBAPIError):
        async with removal._lost_a_lock():
            raise DBAPIError("DELETE", {}, Exception("connection reset"))


async def test_an_insert_into_the_project_holds_the_removal_until_it_commits(svc, tmp_path):
    """The project's row lock: a run, a source or a discovery being added when the removal
    starts makes it wait; once it commits, the removal sees it and deletes nothing."""
    pid = await svc.project()
    sid = await svc.source(pid)
    plan = await removal.plan_project(svc.db, "p")
    async with svc.db.session() as s, s.begin():
        holder = await s.scalar(text("SELECT pg_backend_pid()"))
        s.add(Discovery(project_id=pid, state="completed"))  # KEY SHARE on the project
        await s.flush()
        removing = asyncio.create_task(
            removal.delete_project(svc.db, svc.storage, "p", expected=plan)
        )
        await _until_blocked_by(svc.db, holder)
    with pytest.raises(service.ConflictError, match="changed since it was listed"):
        await removing
    assert await _count(svc.db, Project, Project.id == pid) == 1
    assert (tmp_path / "files" / "projects" / str(pid) / "sources" / str(sid)).is_dir()


async def test_s3_storage_loses_the_objects_too(svc, s3):  # noqa: F811 - the fixture
    svc.storage = S3Storage(S3StorageConfig.model_validate({"kind": "s3", "bucket": BUCKET}))
    pid = await svc.project()
    sid = await svc.source(pid)
    other = await svc.source(pid, text="Another text entirely.", name="other.txt")
    run_id = await _completed_run(svc, pid, [sid])
    await removal.delete_source(svc.db, svc.storage, sid, with_runs=True)
    assert svc.storage.list_keys("runs") == []
    assert svc.storage.list_keys("projects") == [
        f"projects/{pid}/sources/{other}/other.txt",
    ]
    await removal.delete_project(svc.db, svc.storage, "p")
    listed = boto3.client("s3", region_name="us-east-1").list_objects_v2(Bucket=BUCKET)
    assert listed.get("Contents", []) == [] and run_id


async def test_list_sources_counts_the_runs_that_used_each(svc):
    pid = await svc.project()
    sid = await svc.source(pid)
    other = await svc.source(pid, text=PORT_TEXT + "\n\nMore.", name="more.txt")
    await _completed_run(svc, pid, [sid, other])
    await _completed_run(svc, pid, [sid])
    listed = await removal.list_sources(svc.db, "p")
    assert [(i.id, i.name, i.runs) for i in listed] == [
        (sid, "port.txt", 2),
        (other, "more.txt", 1),
    ]
    with pytest.raises(runs.NotFoundError):
        await removal.list_sources(svc.db, "nope")


def test_check_names_the_run_state_rules():
    """A removal is refused only for work in flight; every ended state may go."""
    pid = uuid.uuid4()
    for state in RunState:
        item = removal.Item(uuid.uuid4(), state.value)
        plan = removal.Removal(pid, "p", True, (), (item,), (), ())
        if state.value in {"completed", "gate_rejected", "failed", "cancelled"}:
            removal.check(plan)
        else:
            with pytest.raises(service.ConflictError):
                removal.check(plan)


def test_a_stored_key_of_another_shape_is_deleted_alone():
    pid = uuid.uuid4()
    sid = uuid.uuid4()
    assert removal._source_prefix(f"projects/{pid}/sources/{sid}/a.txt", pid) == (
        f"projects/{pid}/sources/{sid}/"
    )
    for key in (f"projects/{pid}/sources/a.txt", f"elsewhere/{sid}/a.txt", "a.txt"):
        assert removal._source_prefix(key, pid) == key
