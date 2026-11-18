import io
import json
import uuid
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace

import psycopg
import pytest
from docx import Document
from procrastinate.exceptions import ConnectorException
from sqlalchemy import select, text

from corelata import service
from corelata.config import CorelataConfig
from corelata.ingest.base import IngestError
from corelata.prompts.library import PromptLibrary
from corelata.schema import DiscoveryState, ReviewAction, RunState, RunSummary
from corelata.service import QueueUnavailableError
from corelata.standards.loader import PackError, load_pack, pack_hash
from corelata.storage import LocalStorage
from corelata.store import runs
from corelata.store.models import Discovery, ReviewEvent, utcnow
from corelata.testing.queue import RecordingQueue
from corelata.worker.app import ProcrastinateQueue
from tests.conftest import db_now, on_db_clock, skew_clock
from tests.ingest.test_coglossa import export as coglossa_export
from tests.stages.conftest import PORT
from tests.standards.test_loader import write_pack

PORT_TEXT = "\n\n".join(PORT)
STATEMENT = "Varna port capacity expansion matters to shippers"


class Svc:
    """The handles every service call takes, bundled for the tests."""

    def __init__(self, db, tmp_path, cfg: CorelataConfig) -> None:
        self.db = db
        self.storage = LocalStorage(tmp_path / "files")
        self.queue = RecordingQueue()
        self.cfg = cfg
        self.prompts = PromptLibrary(cfg.prompts_dir)

    async def project(self, name="p") -> uuid.UUID:
        return await service.create_project(self.db, name)

    async def source(self, project_id, text=PORT_TEXT, name="port.txt") -> uuid.UUID:
        [sid] = await service.add_source(
            self.db, self.storage, project_id, name, text.encode("utf-8")
        )
        return sid

    async def run(self, project_id, source_ids, **kw) -> uuid.UUID:
        req = service.RunRequest(
            project_id=project_id, source_ids=source_ids, value_statement=STATEMENT, **kw
        )
        return await service.start_run(
            self.db, self.storage, self.queue, self.cfg, self.prompts, req
        )


@pytest.fixture
def svc(db, tmp_path, make_config):
    return Svc(db, tmp_path, make_config())


async def _set_state(db, run_id, state: str):
    async with db.session() as s, s.begin():
        run = await runs.get_run(s, run_id, lock=True)
        run.state = state
        run.started_at = utcnow()


async def test_projects(svc):
    pid = await svc.project("novel")
    assert await svc.project("novel") == pid
    assert [(p.id, p.name) for p in await service.list_projects(svc.db)] == [(pid, "novel")]


async def test_add_source_stores_the_file_and_the_units(svc):
    pid = await svc.project()
    sid = await svc.source(pid, name="Mon rapport (v2).txt")
    async with svc.db.session() as s:
        [row] = await runs.list_sources(s, pid)
        assert row.id == sid and row.name == "Mon rapport (v2).txt" and row.format == "txt"
        assert row.storage_key == f"projects/{pid}/sources/{sid}/Mon_rapport__v2_.txt"
        loaded = await runs.load_source(s, row, as_id="src1")
    assert [u.text for u in loaded.units] == PORT
    assert svc.storage.get(row.storage_key).decode() == "\n\n".join(PORT)
    assert [r.id for r in await service.list_sources(svc.db, pid)] == [sid]


async def test_add_source_rejects_bad_uploads_and_leaves_no_file(svc, tmp_path):
    pid = await svc.project()
    with pytest.raises(IngestError, match="unsupported file type"):
        await service.add_source(svc.db, svc.storage, pid, "x.png", b"\x89PNG")
    with pytest.raises(IngestError, match="is empty"):
        await service.add_source(svc.db, svc.storage, pid, "x.txt", b"")
    with pytest.raises(service.InvalidRequestError, match="no file name"):
        await service.add_source(svc.db, svc.storage, pid, "", b"x")
    with pytest.raises(IngestError, match="no usable text"):
        await service.add_source(svc.db, svc.storage, pid, "blank.txt", b"\n\n  \n")
    with pytest.raises(runs.NotFoundError):
        await service.add_source(svc.db, svc.storage, uuid.uuid4(), "a.txt", b"hello")
    assert not list((tmp_path / "files").rglob("*.txt"))
    assert not list((tmp_path / "files").rglob("sources"))
    async with svc.db.session() as s:
        assert await runs.list_sources(s, pid) == []


async def test_add_source_from_a_file_stores_it_without_reading_it_whole(svc, tmp_path):
    """CRL-73: the API hands over the file an upload was spooled to; it goes to the store as a
    file, and an empty one is refused like empty bytes."""
    pid = await svc.project()
    text = "\n\n".join(PORT).encode()
    f = io.BytesIO(text)
    [sid] = await service.add_source(svc.db, svc.storage, pid, "port.txt", f)
    async with svc.db.session() as s:
        [row] = await runs.list_sources(s, pid)
        loaded = await runs.load_source(s, row, as_id="src1")
    assert row.id == sid and [u.text for u in loaded.units] == PORT
    assert svc.storage.get(row.storage_key) == text
    with pytest.raises(IngestError, match="x.txt is empty"):
        await service.add_source(svc.db, svc.storage, pid, "x.txt", io.BytesIO())
    spent = io.BytesIO(b"read already")
    spent.seek(0, io.SEEK_END)
    with pytest.raises(IngestError, match="y.txt is empty"):
        await service.add_source(svc.db, svc.storage, pid, "y.txt", spent)
    assert spent.tell() == len(b"read already")
    assert not list((tmp_path / "files").rglob("x.txt"))


async def test_add_coglossa_export_gives_the_translation_and_its_guide(svc):
    pid = await svc.project()
    data = json.dumps(coglossa_export()).encode("utf-8")
    ids = await service.add_source(
        svc.db, svc.storage, pid, "letter.coglossa.json", data, coglossa_export=True
    )
    assert len(ids) == 2
    async with svc.db.session() as s:
        rows = {r.id: r for r in await runs.list_sources(s, pid)}
    main, guide = (rows[i] for i in ids)
    assert main.kind == "coglossa_export" and main.provenance["coglossa_run_id"] == "run-42"
    assert main.name == "letter.coglossa.json" and guide.storage_key == main.storage_key
    assert guide.format == "coglossa-guide"


async def test_start_run_queues_one_job_and_snapshots_the_pack(svc):
    pid = await svc.project()
    sid = await svc.source(pid)
    run_id = await svc.run(pid, [sid], extra_guidance="Keep it short")
    assert [(j.task, j.lock, j.kwargs) for j in svc.queue.jobs] == [
        (service.TASK_RUN, f"run:{run_id}", {"run_id": str(run_id)})
    ]
    pack = load_pack("icd203-base")
    async with svc.db.session() as s:
        run = await runs.get_run(s, run_id)
        assert await runs.run_source_ids(s, run_id) == [sid]
    assert run.state == "created" and run.max_iterations == svc.cfg.pipeline.max_iterations
    assert run.pack_hash == pack_hash(pack) and run.pack_snapshot == pack.model_dump(mode="json")
    assert run.pack_name == "icd203-base" and run.profile is None
    assert run.config_snapshot["pipeline"]["max_iterations"] == 2
    assert run.prompt_versions["writer"] >= 1 and run.corelata_version
    assert run.extra_guidance == "Keep it short" and run.docx_reference_key is None
    progress = await service.run_progress(svc.db, run_id)
    assert progress.state is RunState.CREATED and progress.stages == [] and progress.usage is None
    assert progress.project_id == str(pid) and progress.created_at.tzinfo is not None
    # what the run was asked, so the new-report page can start from it (CRL-84)
    assert (progress.value_statement, progress.profile) == (STATEMENT, None)
    assert progress.source_ids == [str(sid)]


async def test_start_run_validates_its_request(svc):
    pid = await svc.project()
    sid = await svc.source(pid)
    other = await svc.project("other")
    foreign = await svc.source(other)
    with pytest.raises(service.InvalidRequestError, match="value statement"):
        await service.start_run(
            svc.db,
            svc.storage,
            svc.queue,
            svc.cfg,
            svc.prompts,
            service.RunRequest(project_id=pid, source_ids=[sid], value_statement="  "),
        )
    with pytest.raises(service.InvalidRequestError, match="at least one source"):
        await svc.run(pid, [])
    with pytest.raises(service.InvalidRequestError, match="between 0 and 10"):
        await svc.run(pid, [sid], max_iterations=11)
    with pytest.raises(service.InvalidRequestError, match="only once"):
        await svc.run(pid, [sid, sid])
    with pytest.raises(runs.NotFoundError, match="not in project"):
        await svc.run(pid, [sid, foreign])
    with pytest.raises(PackError, match="profile 'nope' not found"):
        await svc.run(pid, [sid], profile="nope")
    with pytest.raises(runs.NotFoundError, match="not found"):
        await svc.run(pid, [sid], parent_run_id=uuid.uuid4())
    assert svc.queue.jobs == []
    async with svc.db.session() as s:
        assert (await s.execute(text("SELECT count(*) FROM run"))).scalar() == 0


async def test_start_run_stores_the_profile_reference_document(db, tmp_path, make_config):
    pack = write_pack(
        tmp_path / "packs",
        "house",
        rules=[],
        extends="icd203-base",
        template=None,
        lexicon=None,
        profiles={
            "east": {
                "name": "east",
                "extends": "house",
                "format": {"docx_reference": "templates/east.docx"},
            }
        },
    )
    (pack / "templates").mkdir()
    Document().save(str(pack / "templates" / "east.docx"))
    cfg = make_config(standards={"packs_dir": str(tmp_path / "packs"), "default_pack": "house"})
    svc = Svc(db, tmp_path, cfg)
    pid = await svc.project()
    sid = await svc.source(pid)
    run_id = await svc.run(pid, [sid], profile="east")
    async with svc.db.session() as s:
        run = await runs.get_run(s, run_id)
    assert run.profile == "east" and run.docx_reference_key == f"runs/{run_id}/reference.docx"
    stored = svc.storage.get(run.docx_reference_key)
    assert stored == (pack / "templates" / "east.docx").read_bytes()
    assert await service.reference_document(svc.db, svc.storage, run_id) == stored
    (pack / "templates" / "east.docx").unlink()  # Review Focus 4: the run keeps its copy
    assert await service.reference_document(svc.db, svc.storage, run_id) == stored


async def test_a_failed_start_run_removes_the_stored_reference(db, tmp_path, make_config):
    pack = write_pack(
        tmp_path / "packs",
        "house",
        rules=[],
        extends="icd203-base",
        template=None,
        lexicon=None,
        profiles={
            "east": {
                "name": "east",
                "extends": "house",
                "format": {"docx_reference": "templates/east.docx"},
            }
        },
    )
    (pack / "templates").mkdir()
    Document().save(str(pack / "templates" / "east.docx"))
    cfg = make_config(standards={"packs_dir": str(tmp_path / "packs"), "default_pack": "house"})
    svc = Svc(db, tmp_path, cfg)
    pid = await svc.project()
    sid = await svc.source(pid)
    with pytest.raises(runs.NotFoundError):
        await svc.run(pid, [sid], profile="east", parent_run_id=uuid.uuid4())
    assert svc.queue.jobs == []
    assert not list((tmp_path / "files").rglob("reference.docx"))
    async with svc.db.session() as s:
        assert (await s.execute(text("SELECT count(*) FROM run"))).scalar() == 0


async def test_cancel_a_created_run_ends_it_at_once(svc):
    pid = await svc.project()
    run_id = await svc.run(pid, [await svc.source(pid)])
    assert await service.cancel_run(svc.db, run_id) is RunState.CANCELLED
    progress = await service.run_progress(svc.db, run_id)
    assert progress.cancel_requested and progress.finished_at is not None
    with pytest.raises(service.InvalidRunStateError, match="already cancelled"):
        await service.cancel_run(svc.db, run_id)


async def test_cancel_a_running_run_only_sets_the_flag(svc):
    pid = await svc.project()
    run_id = await svc.run(pid, [await svc.source(pid)])
    await _set_state(svc.db, run_id, "drafting")
    assert await service.cancel_run(svc.db, run_id) is RunState.DRAFTING
    progress = await service.run_progress(svc.db, run_id)
    assert progress.cancel_requested and progress.state is RunState.DRAFTING
    assert progress.finished_at is None
    with pytest.raises(runs.NotFoundError):
        await service.cancel_run(svc.db, uuid.uuid4())


async def test_review_needs_a_completed_run(svc):
    pid = await svc.project()
    run_id = await svc.run(pid, [await svc.source(pid)])
    with pytest.raises(service.InvalidRunStateError, match="only a completed run"):
        await service.review_run(
            svc.db, svc.storage, svc.queue, svc.cfg, svc.prompts, run_id, ReviewAction.ACCEPT
        )


async def test_accept_records_an_event_and_queues_nothing(svc):
    pid = await svc.project()
    run_id = await svc.run(pid, [await svc.source(pid)])
    await _set_state(svc.db, run_id, "completed")
    svc.queue.jobs.clear()
    child = await service.review_run(
        svc.db,
        svc.storage,
        svc.queue,
        svc.cfg,
        svc.prompts,
        run_id,
        ReviewAction.ACCEPT,
        note="good",
        actor="alice",
    )
    assert child is None and svc.queue.jobs == []
    async with svc.db.session() as s:
        [event] = (await s.scalars(select(ReviewEvent))).all()
    assert (event.run_id, event.action, event.note, event.actor, event.child_run_id) == (
        run_id,
        "accept",
        "good",
        "alice",
        None,
    )


async def test_return_creates_a_linked_run_seeded_with_the_note(db, tmp_path, make_config):
    pack = write_pack(
        tmp_path / "packs",
        "house",
        rules=[],
        extends="icd203-base",
        template=None,
        lexicon=None,
        profiles={
            "east": {
                "name": "east",
                "extends": "house",
                "format": {"docx_reference": "templates/east.docx"},
            }
        },
    )
    (pack / "templates").mkdir()
    Document().save(str(pack / "templates" / "east.docx"))
    cfg = make_config(standards={"packs_dir": str(tmp_path / "packs"), "default_pack": "house"})
    svc = Svc(db, tmp_path, cfg)
    pid = await svc.project()
    a, b = (
        await svc.source(pid),
        await svc.source(pid, text="Shippers welcomed Varna.", name="b.md"),
    )
    run_id = await svc.run(pid, [b, a], profile="east", max_iterations=1, extra_guidance="Brief")
    await _set_state(svc.db, run_id, "completed")
    svc.queue.jobs.clear()
    with pytest.raises(service.InvalidRequestError, match="needs a note"):
        await service.review_run(
            svc.db, svc.storage, svc.queue, svc.cfg, svc.prompts, run_id, ReviewAction.RETURN
        )
    child = await service.review_run(
        svc.db,
        svc.storage,
        svc.queue,
        svc.cfg,
        svc.prompts,
        run_id,
        ReviewAction.RETURN,
        note="Tighten the scope.",
        actor="alice",
    )
    assert child is not None and child != run_id
    assert [(j.task, j.lock) for j in svc.queue.jobs] == [(service.TASK_RUN, f"run:{child}")]
    async with svc.db.session() as s:
        parent, kid = await runs.get_run(s, run_id), await runs.get_run(s, child)
        assert await runs.run_source_ids(s, child) == [b, a]
        [event] = (await s.scalars(select(ReviewEvent))).all()
    assert kid.parent_run_id == run_id and kid.state == "created"
    assert kid.extra_guidance == "Brief\nReviewer note: Tighten the scope."
    assert (kid.value_statement, kid.profile, kid.max_iterations) == (STATEMENT, "east", 1)
    assert (kid.pack_snapshot, kid.pack_hash) == (parent.pack_snapshot, parent.pack_hash)
    assert kid.docx_reference_key == f"runs/{child}/reference.docx"
    assert svc.storage.get(kid.docx_reference_key) == svc.storage.get(parent.docx_reference_key)
    assert (event.action, event.child_run_id) == ("return", child)
    progress = await service.run_progress(svc.db, child)
    assert progress.parent_run_id == str(run_id)
    # the project's sources in the run's own order (CRL-84)
    assert progress.source_ids == [str(b), str(a)]
    assert (progress.value_statement, progress.profile, progress.max_iterations) == (
        STATEMENT,
        "east",
        1,
    )


async def test_get_run_record_rebuilds_the_trace(svc):
    pid = await svc.project()
    run_id = await svc.run(pid, [await svc.source(pid)])
    record = await service.get_run_record(svc.db, run_id)
    assert record.run_id == str(run_id) and record.state is RunState.CREATED
    assert [s.id for s in record.sources] == ["src1"] and record.report is None


async def test_new_project_rejects_duplicates_and_blank_names(svc):
    project = await service.new_project(svc.db, "  Black Sea  ")
    assert project.name == "Black Sea" and project.created_at is not None
    assert (await service.get_project(svc.db, project.id)).id == project.id
    with pytest.raises(service.ConflictError, match="already exists"):
        await service.new_project(svc.db, "Black Sea")
    with pytest.raises(service.InvalidRequestError, match="needs a name"):
        await service.new_project(svc.db, "   ")
    with pytest.raises(runs.NotFoundError):
        await service.get_project(svc.db, uuid.uuid4())
    with pytest.raises(service.InvalidRequestError, match="at most 200"):
        await service.new_project(svc.db, "x" * 201)


async def test_list_runs_returns_summaries(svc):
    pid = await svc.project()
    sid = await svc.source(pid)
    run_id = await svc.run(pid, [sid])
    [summary] = await service.list_runs(svc.db, pid)
    assert isinstance(summary, RunSummary)
    assert summary.run_id == str(run_id) and summary.project_id == str(pid)
    assert summary.state is RunState.CREATED and summary.value_statement == STATEMENT
    assert summary.max_iterations == svc.cfg.pipeline.max_iterations
    with pytest.raises(runs.NotFoundError):
        await service.list_runs(svc.db, uuid.uuid4())


async def test_list_runs_continues_after_a_cursor(svc):
    pid = await svc.project()
    sid = await svc.source(pid)
    for _ in range(3):
        await svc.run(pid, [sid])
    first = await service.list_runs(svc.db, pid, limit=2)
    before = service.parse_run_cursor(service.run_cursor(first[-1]))
    rest = await service.list_runs(svc.db, pid, limit=2, before=before)
    everything = await service.list_runs(svc.db, pid)
    assert [r.run_id for r in first + rest] == [r.run_id for r in everything]
    assert len(rest) == 1


def test_a_run_cursor_is_the_utc_time_to_the_microsecond_and_the_id():
    run_id = "6f1c2a9e-0000-4000-8000-000000000001"
    summary = RunSummary(
        run_id=run_id,
        project_id=str(uuid.uuid4()),
        state=RunState.COMPLETED,
        value_statement="v",
        iteration=0,
        max_iterations=2,
        created_at=datetime(2026, 10, 17, 9, 30, 1, 120000, tzinfo=timezone(timedelta(hours=3))),
    )
    cursor = service.run_cursor(summary)
    assert cursor == f"2026-10-17T06:30:01.120000Z|{run_id}"
    assert service.parse_run_cursor(cursor) == (
        datetime(2026, 10, 17, 6, 30, 1, 120000, tzinfo=UTC),
        uuid.UUID(run_id),
    )


@pytest.mark.parametrize(
    "cursor",
    [
        "",
        "2026-10-17T06:30:01.120000Z",  # no run id
        "|6f1c2a9e-0000-4000-8000-000000000001",  # no time
        "2026-10-17T06:30:01.120000|6f1c2a9e-0000-4000-8000-000000000001",  # no time zone
        "yesterday|6f1c2a9e-0000-4000-8000-000000000001",
        "2026-10-17T06:30:01.120000Z|run-1",
    ],
)
def test_a_malformed_cursor_is_an_invalid_request(cursor):
    with pytest.raises(service.InvalidRequestError) as raised:
        service.parse_run_cursor(cursor)
    assert str(raised.value) == "invalid cursor 'before': pass the next_before of the previous page"


async def test_add_source_parses_off_the_event_loop(svc, monkeypatch):
    seen: list[str] = []

    async def spy(fn, *args):
        seen.append(fn.__name__)
        return fn(*args)

    monkeypatch.setattr(service.asyncio, "to_thread", spy)
    pid = await svc.project()
    await svc.source(pid)
    assert seen == ["_parse_stored"]


class _DownApp:
    """A procrastinate app whose database is gone: its deferrer fails as the real one does,
    with a message-less ConnectorException and the driver error in __cause__."""

    def configure_task(self, task, **options):
        async def defer_async(**kwargs):
            raise ConnectorException() from psycopg.OperationalError("connection refused")

        return SimpleNamespace(defer_async=defer_async)


class _DownQueue(ProcrastinateQueue):
    def __init__(self):
        super().__init__(_DownApp())


async def test_a_queue_failure_marks_the_run_failed(svc):
    pid = await svc.project()
    sid = await svc.source(pid)
    req = service.RunRequest(project_id=pid, source_ids=[sid], value_statement=STATEMENT)
    with pytest.raises(QueueUnavailableError):
        await service.start_run(svc.db, svc.storage, _DownQueue(), svc.cfg, svc.prompts, req)
    [summary] = await service.list_runs(svc.db, pid)
    progress = await service.run_progress(svc.db, uuid.UUID(summary.run_id))
    assert progress.state is RunState.FAILED and progress.finished_at is not None
    assert progress.error == "could not queue the run: connection refused"


async def test_a_queue_failure_marks_the_discovery_failed(svc):
    pid = await svc.project()
    sid = await svc.source(pid)
    with pytest.raises(QueueUnavailableError):
        await service.start_discovery(svc.db, _DownQueue(), pid, [sid])
    async with svc.db.session() as s:
        [row] = (await s.scalars(select(Discovery))).all()
    view = await service.get_discovery(svc.db, row.id)
    assert view.state is DiscoveryState.FAILED and view.finished_at is not None
    assert view.error == "could not queue the discovery: connection refused"


async def test_runs_and_discoveries_are_timed_by_the_database(svc, monkeypatch):
    """CRL-87: an API host whose clock runs ten minutes ahead writes the database's `now()` as
    a run's created_at and as every finished_at it writes on runs and discoveries."""
    skew_clock(monkeypatch, timedelta(minutes=10))
    pid = await svc.project()
    sid = await svc.source(pid)
    cancelled = await svc.run(pid, [sid])
    await service.cancel_run(svc.db, cancelled)
    req = service.RunRequest(project_id=pid, source_ids=[sid], value_statement=STATEMENT)
    with pytest.raises(QueueUnavailableError):
        await service.start_run(svc.db, svc.storage, _DownQueue(), svc.cfg, svc.prompts, req)
    with pytest.raises(QueueUnavailableError):
        await service.start_discovery(svc.db, _DownQueue(), pid, [sid])
    now = await db_now(svc.db)
    for summary in await service.list_runs(svc.db, pid):
        progress = await service.run_progress(svc.db, uuid.UUID(summary.run_id))
        assert on_db_clock(progress.created_at, now) and on_db_clock(progress.finished_at, now)
    async with svc.db.session() as s:
        [row] = (await s.scalars(select(Discovery))).all()
    assert on_db_clock(row.created_at, now) and on_db_clock(row.finished_at, now)


async def test_a_queue_failure_on_return_marks_the_child_failed(svc):
    pid = await svc.project()
    sid = await svc.source(pid)
    run_id = await svc.run(pid, [sid])
    await _set_state(svc.db, run_id, "completed")
    with pytest.raises(QueueUnavailableError):
        await service.review_run(
            svc.db,
            svc.storage,
            _DownQueue(),
            svc.cfg,
            svc.prompts,
            run_id,
            ReviewAction.RETURN,
            note="tighter",
        )
    children = [r for r in await service.list_runs(svc.db, pid) if r.parent_run_id == str(run_id)]
    assert len(children) == 1 and children[0].state is RunState.FAILED


async def test_stored_export_reads_the_worker_file_or_none(svc):
    pid = await svc.project()
    sid = await svc.source(pid)
    run_id = await svc.run(pid, [sid])
    assert await service.stored_export(svc.db, svc.storage, run_id, "report.docx") is None
    svc.storage.put(f"runs/{run_id}/trace.json", b"{}")
    async with svc.db.session() as s, s.begin():
        await runs.add_export(s, run_id, "trace.json", f"runs/{run_id}/trace.json", b"{}")
    assert await service.stored_export(svc.db, svc.storage, run_id, "trace.json") == b"{}"
    with pytest.raises(runs.NotFoundError):
        await service.stored_export(svc.db, svc.storage, uuid.uuid4(), "trace.json")


@pytest.mark.parametrize("kind", ["run", "discovery"])
async def test_a_failure_to_mark_after_a_queue_failure_is_logged(svc, monkeypatch, caplog, kind):
    async def broken(*args):
        raise RuntimeError("db gone")

    pid = await svc.project()
    sid = await svc.source(pid)
    monkeypatch.setattr(service, f"_mark_{kind}_failed", broken)
    with (
        caplog.at_level("WARNING", logger="corelata.service"),
        pytest.raises(QueueUnavailableError),
    ):
        if kind == "run":
            req = service.RunRequest(project_id=pid, source_ids=[sid], value_statement=STATEMENT)
            await service.start_run(svc.db, svc.storage, _DownQueue(), svc.cfg, svc.prompts, req)
        else:
            await service.start_discovery(svc.db, _DownQueue(), pid, [sid])
    assert "could not mark" in caplog.text and "db gone" in caplog.text


async def test_parent_run_must_be_in_the_same_project(svc):
    pid, other = await svc.project(), await svc.project("other")
    parent = await svc.run(pid, [await svc.source(pid)])
    with pytest.raises(service.InvalidRequestError, match="another project"):
        await svc.run(other, [await svc.source(other)], parent_run_id=parent)
    assert await service.list_runs(svc.db, other) == []


async def test_a_run_can_be_returned_once(svc):
    pid = await svc.project()
    run_id = await svc.run(pid, [await svc.source(pid)])
    await _set_state(svc.db, run_id, "completed")
    child = await service.review_run(
        svc.db,
        svc.storage,
        svc.queue,
        svc.cfg,
        svc.prompts,
        run_id,
        ReviewAction.RETURN,
        note="Tighten the scope",
        actor="alice",
    )
    with pytest.raises(service.ConflictError, match=str(child)):
        await service.review_run(
            svc.db,
            svc.storage,
            svc.queue,
            svc.cfg,
            svc.prompts,
            run_id,
            ReviewAction.RETURN,
            note="Again",
            actor="bob",
        )
    children = [r for r in await service.list_runs(svc.db, pid) if r.parent_run_id == str(run_id)]
    assert len(children) == 1


async def test_a_failed_return_leaves_no_placeholder_event(svc, monkeypatch):
    pid = await svc.project()
    run_id = await svc.run(pid, [await svc.source(pid)])
    await _set_state(svc.db, run_id, "completed")

    async def boom(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(service, "_create_run", boom)
    with pytest.raises(RuntimeError):
        await service.review_run(
            svc.db,
            svc.storage,
            svc.queue,
            svc.cfg,
            svc.prompts,
            run_id,
            ReviewAction.RETURN,
            note="x",
        )
    async with svc.db.session() as s:
        assert await runs.load_review_events(s, run_id) == []
    assert [r.run_id for r in await service.list_runs(svc.db, pid)] == [str(run_id)]


async def test_an_unreadable_reference_leaves_no_placeholder_and_can_be_retried(svc, monkeypatch):
    pid = await svc.project()
    run_id = await svc.run(pid, [await svc.source(pid)])
    await _set_state(svc.db, run_id, "completed")
    async with svc.db.session() as s, s.begin():
        (await runs.get_run(s, run_id)).docx_reference_key = "reference/missing.docx"
    real_get = svc.storage.get

    def get(key):
        if key == "reference/missing.docx":
            raise OSError("unreadable")
        return real_get(key)

    monkeypatch.setattr(svc.storage, "get", get)
    args = (svc.db, svc.storage, svc.queue, svc.cfg, svc.prompts, run_id, ReviewAction.RETURN)
    with pytest.raises(OSError):
        await service.review_run(*args, note="x")
    async with svc.db.session() as s:
        assert await runs.load_review_events(s, run_id) == []
    monkeypatch.undo()
    async with svc.db.session() as s, s.begin():
        (await runs.get_run(s, run_id)).docx_reference_key = None
    assert await service.review_run(*args, note="again") is not None


async def test_a_return_in_flight_is_worded_as_such(svc):
    pid = await svc.project()
    run_id = await svc.run(pid, [await svc.source(pid)])
    await _set_state(svc.db, run_id, "completed")
    async with svc.db.session() as s, s.begin():
        await runs.add_review_event(s, run_id, "return", "x", None, None)
    with pytest.raises(service.ConflictError, match="being returned; its rerun is not ready"):
        await service.review_run(
            svc.db,
            svc.storage,
            svc.queue,
            svc.cfg,
            svc.prompts,
            run_id,
            ReviewAction.RETURN,
            note="y",
        )


async def test_run_progress_carries_the_review_decision(svc):
    pid = await svc.project()
    run_id = await svc.run(pid, [await svc.source(pid)])
    assert (await service.run_progress(svc.db, run_id)).review is None
    await _set_state(svc.db, run_id, "completed")
    assert (await service.run_progress(svc.db, run_id)).review is None  # completed, not reviewed
    args = (svc.db, svc.storage, svc.queue, svc.cfg, svc.prompts, run_id)
    child = await service.review_run(*args, ReviewAction.RETURN, note="tighten", actor="bob")
    returned = (await service.run_progress(svc.db, run_id)).review
    assert returned is not None
    assert (returned.decision, returned.actor, returned.child_run_id) == (
        "returned",
        "bob",
        str(child),
    )
    assert (await service.run_progress(svc.db, child)).review is None
    await _set_state(svc.db, child, "completed")
    child_args = (svc.db, svc.storage, svc.queue, svc.cfg, svc.prompts, child)
    await service.review_run(*child_args, ReviewAction.ACCEPT, actor="alice")
    accepted = (await service.run_progress(svc.db, child)).review
    assert accepted is not None
    assert (accepted.decision, accepted.actor, accepted.child_run_id) == ("accepted", "alice", None)
    assert accepted.at >= returned.at


def test_review_state_prefers_the_return_and_the_latest_accept():
    t = [utcnow() for _ in range(3)]
    accept_a = ReviewEvent(action="accept", note="", actor="a", child_run_id=None, at=t[0])
    accept_b = ReviewEvent(action="accept", note="", actor="b", child_run_id=None, at=t[1])
    pending = ReviewEvent(action="return", note="x", actor="c", child_run_id=None, at=t[2])
    assert service._review_state([], {}) is None
    latest = service._review_state([accept_a, accept_b], {})
    assert latest is not None and latest.actor == "b"
    placeholder = service._review_state([accept_a, pending], {})
    assert placeholder is not None
    assert placeholder.decision == "returned" and placeholder.child_run_id is None


async def test_review_run_stores_the_decision_on_the_run_row(svc, monkeypatch):
    pid = await svc.project()
    run_id = await svc.run(pid, [await svc.source(pid)])
    await _set_state(svc.db, run_id, "completed")
    args = (svc.db, svc.storage, svc.queue, svc.cfg, svc.prompts, run_id)

    async def stored():
        async with svc.db.session() as s:
            return (await runs.get_run(s, run_id)).review_state

    assert await stored() is None
    seen = {}

    async def boom(*a, **kw):
        seen["during"] = await stored()  # another session: the return has not committed
        raise RuntimeError("disk full")

    monkeypatch.setattr(service, "_create_run", boom)
    with pytest.raises(RuntimeError):
        await service.review_run(*args, ReviewAction.RETURN, note="x", actor="bob")
    assert seen == {"during": None}  # nothing of the return is visible before it commits
    assert await stored() is None  # and nothing of it stays (R-M15-3)
    monkeypatch.undo()
    child = await service.review_run(*args, ReviewAction.RETURN, note="tighten", actor="bob")
    returned = await stored()
    assert returned["decision"] == "returned" and returned["child_run_id"] == str(child)
    async with svc.db.session() as s:
        events = await runs.load_review_events(s, run_id)
        reruns = await runs.rerun_states(s, [child])
    assert returned == service._review_state(events, reruns).model_dump(mode="json")
    await _set_state(svc.db, child, "failed")  # the rerun failed, so an accept decides
    async with svc.db.session() as s, s.begin():
        await service._store_review_state(s, run_id)
    await service.review_run(*args, ReviewAction.ACCEPT, actor="alice")
    accepted = await stored()
    assert accepted["decision"] == "accepted" and accepted["actor"] == "alice"


async def test_run_progress_reads_the_stored_decision_not_the_events(svc, monkeypatch):
    pid = await svc.project()
    run_id = await svc.run(pid, [await svc.source(pid)])
    await _set_state(svc.db, run_id, "completed")
    args = (svc.db, svc.storage, svc.queue, svc.cfg, svc.prompts, run_id)
    await service.review_run(*args, ReviewAction.ACCEPT, actor="alice")

    async def forbidden(s, run_id):
        raise AssertionError("run_progress must not read review_event")

    monkeypatch.setattr(runs, "load_review_events", forbidden)
    review = (await service.run_progress(svc.db, run_id)).review
    assert review is not None and (review.decision, review.actor) == ("accepted", "alice")


async def test_run_text_is_bounded_in_the_service(svc):
    """CRL-111: the CRL-83 limits live in the service, so the CLI is held to what the API is."""
    pid = await svc.project()
    sid = await svc.source(pid)
    over = {
        "value_statement": "x" * (service.VALUE_STATEMENT_MAX_LENGTH + 1),
        "extra_guidance": "",
    }
    with pytest.raises(service.InvalidRequestError, match="statement is at most 4000 characters"):
        await service.start_run(
            svc.db,
            svc.storage,
            svc.queue,
            svc.cfg,
            svc.prompts,
            service.RunRequest(project_id=pid, source_ids=[sid], **over),
        )
    with pytest.raises(service.InvalidRequestError, match="guidance is at most 8000 characters"):
        await svc.run(pid, [sid], extra_guidance="g" * (service.GUIDANCE_MAX_LENGTH + 1))
    assert svc.queue.jobs == []
    run_id = await svc.run(pid, [sid], extra_guidance="g" * service.GUIDANCE_MAX_LENGTH)
    await _set_state(svc.db, run_id, "completed")
    args = (svc.db, svc.storage, svc.queue, svc.cfg, svc.prompts, run_id)
    for action in ReviewAction:
        with pytest.raises(service.InvalidRequestError, match="note is at most 8000 characters"):
            await service.review_run(*args, action, note="n" * (service.GUIDANCE_MAX_LENGTH + 1))


async def test_chained_returns_stop_at_the_guidance_cap(svc):
    """CRL-111: each return appends its note to the parent's guidance, so a chain of returns is
    refused once the guidance would pass RUN_GUIDANCE_MAX_LENGTH, with a one-line message that
    says to start a new report; the refusal leaves no run, event or job behind."""
    pid = await svc.project()
    run_id = await svc.run(
        pid, [await svc.source(pid)], extra_guidance="g" * service.GUIDANCE_MAX_LENGTH
    )
    label = len("\nReviewer note: ")
    # the full starting guidance and a full-length note fit; the third note lands on the cap
    notes = ["a" * service.GUIDANCE_MAX_LENGTH]
    notes.append(
        "b" * (service.RUN_GUIDANCE_MAX_LENGTH - 2 * (service.GUIDANCE_MAX_LENGTH + label))
    )
    for note in notes:
        await _set_state(svc.db, run_id, "completed")
        run_id = await service.review_run(
            svc.db,
            svc.storage,
            svc.queue,
            svc.cfg,
            svc.prompts,
            run_id,
            ReviewAction.RETURN,
            note=note,
        )
    async with svc.db.session() as s:
        assert len((await runs.get_run(s, run_id)).extra_guidance) == (
            service.RUN_GUIDANCE_MAX_LENGTH
        )
    await _set_state(svc.db, run_id, "completed")
    svc.queue.jobs.clear()
    with pytest.raises(service.InvalidRequestError) as refused:
        await service.review_run(
            svc.db,
            svc.storage,
            svc.queue,
            svc.cfg,
            svc.prompts,
            run_id,
            ReviewAction.RETURN,
            note="x",
        )
    assert str(refused.value) == service.GUIDANCE_CAP_MESSAGE
    assert "\n" not in service.GUIDANCE_CAP_MESSAGE and "start a new report" in str(refused.value)
    assert svc.queue.jobs == []
    async with svc.db.session() as s:
        assert len(await runs.load_review_events(s, run_id)) == 0
        assert (await runs.get_run(s, run_id)).review_state is None
