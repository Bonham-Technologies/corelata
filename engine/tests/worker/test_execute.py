import io
import logging
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from docx import Document
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from corelata import __version__, service
from corelata.config import config_hash
from corelata.exports import render_outputs
from corelata.llm.payload import parse_input
from corelata.llm.types import PermanentBackendError
from corelata.prompts.check import run_prompt_ids
from corelata.schema import ReportStatus, RunState
from corelata.standards.schema import ResolvedPack
from corelata.store import records, runs
from corelata.store.models import DraftRow, LLMCall, StageResultRow
from corelata.testing.fake_backend import FakeBackend
from corelata.worker import execute
from corelata.worker.execute import run_job
from tests.conftest import db_now, on_db_clock, skew_clock
from tests.standards.test_loader import write_pack
from tests.worker.conftest import drain, make_services, state, submit, tasks_sent

EXPORTS = {"trace.json", "gate.json", "report.json", "report.md", "report.html", "report.docx"}


def _as_bytes(value: str | bytes) -> bytes:
    return value if isinstance(value, bytes) else value.encode("utf-8")


async def _exports(svc, run_id) -> dict[str, bytes]:
    async with svc.db.session() as s:
        rows = await runs.list_exports(s, run_id)
    return {r.name: svc.storage.get(r.storage_key) for r in rows}


async def test_a_queued_run_completes_and_its_exports_are_reproducible(services):
    run_id = await submit(services)
    assert await drain(services) == 1
    progress = await service.run_progress(services.db, run_id)
    assert progress.state is RunState.COMPLETED and progress.status is ReportStatus.CLEAN
    assert progress.attempts == 1 and progress.finished_at is not None
    assert [s.stage for s in progress.stages] == [
        "ingesting",
        "gating",
        "drafting",
        "conveying",
        "auditing",
        "rendering",
    ]
    assert progress.usage is not None and progress.usage.calls == 4
    stored = await _exports(services, run_id)
    assert set(stored) == EXPORTS and stored["report.docx"][:2] == b"PK"
    record = await service.get_run_record(services.db, run_id)
    pack = ResolvedPack.model_validate(record.pack_snapshot)
    again = render_outputs(record, pack, with_claim_ids=False)
    assert {k: _as_bytes(v) for k, v in again.items()} == stored  # spec §8.4 invariant 5
    assert record.report is not None and record.report.metadata.run_id == str(run_id)
    async with services.db.session() as s:
        rows = (await s.scalars(select(LLMCall).order_by(LLMCall.ordinal))).all()
        assert [r.stage for r in rows] == ["gating", "drafting", "conveying", "auditing"]
        assert all(r.request is not None for r in rows)


class _Spy(FakeBackend):
    """Looks at the run from outside while the writer is being called."""

    def __init__(self) -> None:
        super().__init__(name="fake")
        self.db = None
        self.run_id = None
        self.seen = None
        self.cancel = False

    async def chat(self, request):
        payload = parse_input([m.model_dump() for m in request.messages])
        if payload["task"] == "writer" and self.seen is None:
            self.seen = await service.run_progress(self.db, self.run_id)
            if self.cancel:
                await service.cancel_run(self.db, self.run_id)
        return await super().chat(request)


async def test_progress_is_visible_while_the_run_executes(db, tmp_path):
    spy = _Spy()
    svc = make_services(db, spy, tmp_path)
    run_id = await submit(svc)
    spy.db, spy.run_id = db, run_id
    await drain(svc)
    assert spy.seen is not None
    assert spy.seen.state is RunState.DRAFTING and spy.seen.attempts == 1
    assert [s.stage for s in spy.seen.stages] == ["ingesting", "gating"]
    assert spy.seen.usage is not None and spy.seen.usage.calls == 1
    assert spy.seen.started_at is not None and spy.seen.finished_at is None


async def test_cancel_during_drafting_stops_before_the_conveyor(db, tmp_path):
    spy = _Spy()
    spy.cancel = True
    svc = make_services(db, spy, tmp_path)
    run_id = await submit(svc)
    spy.db, spy.run_id = db, run_id
    await drain(svc)
    assert tasks_sent(spy) == ["gate", "writer"]
    progress = await service.run_progress(db, run_id)
    assert progress.state is RunState.CANCELLED and progress.cancel_requested
    assert progress.status is None and progress.error is None and progress.finished_at
    assert [s.stage for s in progress.stages] == ["ingesting", "gating", "drafting"]
    record = await service.get_run_record(db, run_id)
    assert record.report is None and [d.role for d in record.drafts] == ["writer"]
    assert len(record.llm_calls) == 2
    assert set(await _exports(svc, run_id)) == {"trace.json", "gate.json"}


async def test_cancel_before_the_worker_starts_leaves_the_job_a_no_op(services, fake_backend):
    run_id = await submit(services)
    await service.cancel_run(services.db, run_id)
    await drain(services)
    assert fake_backend.requests == []
    progress = await service.run_progress(services.db, run_id)
    assert progress.state is RunState.CANCELLED and progress.attempts == 0


async def test_a_cancel_after_the_claim_only_sets_the_flag(services):
    run_id = await submit(services)
    assert await execute._begin(services, run_id) is not None
    assert await state(services.db, run_id) is RunState.INGESTING
    assert await service.cancel_run(services.db, run_id) is RunState.INGESTING
    progress = await service.run_progress(services.db, run_id)
    assert progress.cancel_requested and progress.finished_at is None


async def test_a_cancel_flag_seen_at_job_start_ends_the_run(services, fake_backend):
    run_id = await submit(services)
    async with services.db.session() as s, s.begin():
        (await runs.get_run(s, run_id, lock=True)).cancel_requested = True  # state still created
    await drain(services)
    assert fake_backend.requests == []
    assert await state(services.db, run_id) is RunState.CANCELLED


async def test_a_redelivered_job_for_a_finished_run_does_nothing(services, fake_backend):
    run_id = await submit(services)
    await drain(services)
    calls = len(fake_backend.requests)
    await run_job(services, service.TASK_RUN, {"run_id": str(run_id)})
    assert len(fake_backend.requests) == calls
    assert (await service.run_progress(services.db, run_id)).attempts == 1


async def test_a_crashed_execution_is_started_over(services, fake_backend, caplog):
    run_id = await submit(services)
    async with services.db.session() as s, s.begin():  # what a worker that died mid-run leaves
        run = await runs.get_run(s, run_id, lock=True)
        run.state, run.attempts, run.iteration = "drafting", 1, 0
        t = datetime(2026, 10, 13, tzinfo=UTC)
        s.add(
            StageResultRow(
                run_id=run_id,
                ordinal=0,
                stage="ingesting",
                iteration=0,
                ok=True,
                started_at=t,
                finished_at=t,
            )
        )
        s.add(
            StageResultRow(
                run_id=run_id,
                ordinal=1,
                stage="gating",
                iteration=0,
                ok=True,
                started_at=t,
                finished_at=t,
            )
        )
        s.add(
            LLMCall(
                run_id=run_id,
                ordinal=0,
                stage="gating",
                role="gate",
                backend="fake",
                model="m",
                prompt_id="gate",
                prompt_version=1,
                attempt=1,
                ok=True,
                latency_ms=1,
            )
        )
    await drain(services)
    progress = await service.run_progress(services.db, run_id)
    assert progress.state is RunState.COMPLETED and progress.attempts == 2
    assert [s.stage for s in progress.stages].count("ingesting") == 1
    record = await service.get_run_record(services.db, run_id)
    assert len(record.llm_calls) == 4 == record.usage.calls
    assert "restarted" in caplog.text


async def test_an_unexpected_error_fails_the_run_without_a_traceback_in_the_row(
    services, monkeypatch
):
    async def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(execute, "run_report", boom)
    run_id = await submit(services)
    await drain(services)
    progress = await service.run_progress(services.db, run_id)
    assert progress.state is RunState.FAILED
    assert progress.error == "internal error: RuntimeError: boom"
    assert progress.finished_at is not None and progress.attempts == 1
    assert await _exports(services, run_id) == {}


async def test_the_worker_times_runs_by_the_database(services, monkeypatch):
    """CRL-87: a worker host whose clock runs ten minutes ahead writes the database's `now()` as
    every started_at and finished_at on a run: a completed run, one cancelled before its claim,
    and one that failed."""
    completed = await submit(services)
    cancelled = await submit(services, project="q")
    async with services.db.session() as s, s.begin():
        (await runs.get_run(s, cancelled, lock=True)).cancel_requested = True
    skew_clock(monkeypatch, timedelta(minutes=10))
    await drain(services)

    async def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(execute, "run_report", boom)
    failed = await submit(services, project="r")
    await drain(services)
    now = await db_now(services.db)
    for run_id, ended in ((completed, "completed"), (cancelled, "cancelled"), (failed, "failed")):
        progress = await service.run_progress(services.db, run_id)
        assert progress.state.value == ended and on_db_clock(progress.finished_at, now)
        assert run_id == cancelled or on_db_clock(progress.started_at, now)


async def test_a_model_failure_ends_failed_with_the_calls_on_record(services, fake_backend):
    fake_backend.script("gate", PermanentBackendError("down"), PermanentBackendError("down"))
    run_id = await submit(services)
    await drain(services)
    progress = await service.run_progress(services.db, run_id)
    assert progress.state is RunState.FAILED and "down" in (progress.error or "")
    assert [s.ok for s in progress.stages] == [True, False, False]
    record = await service.get_run_record(services.db, run_id)
    assert len(record.llm_calls) == 2 and not any(c.ok for c in record.llm_calls)
    assert set(await _exports(services, run_id)) == {"trace.json"}


async def test_a_missing_reference_document_fails_the_run(services):
    run_id = await submit(services)
    async with services.db.session() as s, s.begin():
        (await runs.get_run(s, run_id, lock=True)).docx_reference_key = "runs/x/reference.docx"
    await drain(services)
    progress = await service.run_progress(services.db, run_id)
    assert progress.state is RunState.FAILED
    assert progress.error.startswith("internal error: StorageError: stored file not found")


def _house_pack(tmp_path):
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
    doc = Document()
    doc.sections[0].header.paragraphs[0].text = "HOUSE STYLE"
    doc.save(str(pack / "templates" / "east.docx"))
    return {"packs_dir": str(tmp_path / "packs"), "default_pack": "house"}


async def test_the_run_renders_with_the_stored_reference_even_after_it_changed(
    db, fake_backend, tmp_path
):
    svc = make_services(db, fake_backend, tmp_path, standards=_house_pack(tmp_path))
    run_id = await submit(svc, profile="east")
    (tmp_path / "packs" / "house" / "templates" / "east.docx").unlink()  # Review Focus 4
    await drain(svc)
    progress = await service.run_progress(db, run_id)
    assert progress.state is RunState.COMPLETED and progress.export_error is None
    docx = (await _exports(svc, run_id))["report.docx"]
    rendered = Document(io.BytesIO(docx))
    assert any("UNCLASSIFIED" in p.text for p in rendered.sections[0].header.paragraphs)
    assert rendered.sections[0].page_width == Document().sections[0].page_width


async def test_a_broken_reference_document_fails_only_the_docx_export(db, fake_backend, tmp_path):
    svc = make_services(db, fake_backend, tmp_path, standards=_house_pack(tmp_path))
    run_id = await submit(svc, profile="east")
    svc.storage.put(f"runs/{run_id}/reference.docx", b"not a docx at all")
    await drain(svc)
    progress = await service.run_progress(db, run_id)
    assert progress.state is RunState.COMPLETED and progress.status is ReportStatus.CLEAN
    assert progress.export_error is not None and progress.export_error.startswith(
        "DOCX export failed"
    )
    assert set(await _exports(svc, run_id)) == EXPORTS - {"report.docx"}


async def test_a_configuration_change_since_submit_is_recorded(services, caplog):
    run_id = await submit(services)
    old = config_hash(services.cfg)
    pipeline = services.cfg.pipeline.model_copy(update={"max_iterations": 3})
    services.cfg = services.cfg.model_copy(update={"pipeline": pipeline})
    await drain(services)
    record = await service.get_run_record(services.db, run_id)
    assert record.config_hash == config_hash(services.cfg) != old
    assert record.max_iterations == 2  # the run's own bound, chosen at submit, is kept
    assert "configuration changed" in caplog.text


async def test_store_llm_io_off_keeps_no_prompts_or_replies(db, fake_backend, tmp_path):
    svc = make_services(db, fake_backend, tmp_path, audit={"store_llm_io": False})
    await submit(svc)
    await drain(svc)
    async with db.session() as s:
        rows = (await s.scalars(select(LLMCall))).all()
    assert rows and all(r.request is None and r.response is None for r in rows)


async def test_drafts_and_findings_are_stored_once(services):
    run_id = await submit(services, "\n\n".join(["Varna port capacity grew.", "UNSOURCED claim"]))
    await drain(services)
    record = await service.get_run_record(services.db, run_id)
    async with services.db.session() as s:
        drafts = (await s.scalars(select(DraftRow))).all()
    assert len(drafts) == len(record.drafts) >= 2
    assert record.findings and record.iterations >= 1


async def test_run_job_rejects_unknown_tasks_and_closes_cleanly(services, fake_backend):
    with pytest.raises(ValueError, match="unknown job"):
        await run_job(services, "corelata.nope", {"run_id": str(uuid.uuid4())})
    await services.aclose()
    assert fake_backend.closed


async def test_a_job_for_an_unknown_run_is_skipped(services, caplog):
    caplog.set_level(logging.INFO, logger="corelata.worker")
    await run_job(services, service.TASK_RUN, {"run_id": str(uuid.uuid4())})
    assert "skipped" in caplog.text


async def test_the_trace_reports_the_versions_the_run_executed_with(services):
    run_id = await submit(services)
    async with services.db.session() as s, s.begin():
        run = await runs.get_run(s, run_id, lock=True)
        run.prompt_versions, run.corelata_version = {"gate": 99}, "0.0.0-old"
    await drain(services)
    record = await service.get_run_record(services.db, run_id)
    assert record.prompt_versions == services.prompts.versions(run_prompt_ids())
    assert record.corelata_version == __version__


async def test_an_unreadable_pack_snapshot_fails_the_run(services):
    run_id = await submit(services)
    async with services.db.session() as s, s.begin():
        (await runs.get_run(s, run_id, lock=True)).pack_snapshot = {"name": "x"}
    await drain(services)
    progress = await service.run_progress(services.db, run_id)
    assert progress.state is RunState.FAILED
    assert (progress.error or "").startswith("internal error: ValidationError")
    assert progress.attempts == 1 and progress.finished_at is not None


async def test_a_failing_leftover_write_still_marks_the_run_failed(services, monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(execute, "run_report", boom)
    real = runs.add_llm_calls
    calls = []

    async def flaky(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("write failed")
        return await real(*args, **kwargs)

    monkeypatch.setattr(runs, "add_llm_calls", flaky)
    run_id = await submit(services)
    await drain(services)
    progress = await service.run_progress(services.db, run_id)
    assert progress.state is RunState.FAILED
    assert progress.error == "internal error: RuntimeError: boom"
    assert progress.finished_at is not None


_BLIP = OperationalError("x", {}, Exception("blip"))


@pytest.mark.parametrize("where", ["stage_recorded", "save_outcome"])
async def test_a_database_blip_is_retried_not_recorded_as_a_failure(services, monkeypatch, where):
    target = execute.DbObserver if where == "stage_recorded" else records
    real = getattr(target, where)
    calls = []

    async def blip_once(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise _BLIP
        return await real(*args, **kwargs)

    monkeypatch.setattr(target, where, blip_once)
    run_id = await submit(services)
    job = services.queue.pop()
    with pytest.raises(OperationalError):
        await run_job(services, job.task, job.kwargs)
    progress = await service.run_progress(services.db, run_id)
    assert progress.state is not RunState.FAILED and progress.attempts == 1
    assert progress.error is None
    await run_job(services, job.task, job.kwargs)
    progress = await service.run_progress(services.db, run_id)
    assert progress.state is RunState.COMPLETED and progress.attempts == 2
    assert [s.stage for s in progress.stages].count("ingesting") == 1


async def test_a_crashed_execution_removes_the_dead_attempts_exports(services, fake_backend):
    run_id = await submit(services)
    stale = f"runs/{run_id}/report.md"
    async with services.db.session() as s, s.begin():
        run = await runs.get_run(s, run_id, lock=True)
        run.state, run.attempts = "drafting", 1
        services.storage.put(stale, b"from the attempt that died")
        await runs.add_export(s, run_id, "report.md", stale, b"from the attempt that died")
        services.storage.put(f"runs/{run_id}/leftover.bin", b"no row points at me")
    await drain(services)
    progress = await service.run_progress(services.db, run_id)
    assert progress.state is RunState.COMPLETED and progress.attempts == 2
    files = sorted(p.name for p in (services.storage.root / "runs" / str(run_id)).iterdir())
    async with services.db.session() as s:
        rows = sorted(e.name for e in await runs.list_exports(s, run_id))
    assert files == rows  # exactly the second attempt's exports, nothing from the first
    assert services.storage.get(stale) != b"from the attempt that died"


async def test_a_restart_keeps_the_reference_document(db, fake_backend, tmp_path):
    svc = make_services(db, fake_backend, tmp_path, standards=_house_pack(tmp_path))
    run_id = await submit(svc, profile="east")
    reference = f"runs/{run_id}/reference.docx"
    original = svc.storage.get(reference)
    async with svc.db.session() as s, s.begin():
        run = await runs.get_run(s, run_id, lock=True)
        run.state, run.attempts = "drafting", 1
        svc.storage.put(f"runs/{run_id}/leftover.bin", b"stray")
    await drain(svc)
    progress = await service.run_progress(db, run_id)
    assert progress.state is RunState.COMPLETED and progress.attempts == 2
    assert svc.storage.get(reference) == original
    assert f"runs/{run_id}/leftover.bin" not in svc.storage.list_keys(f"runs/{run_id}/")
