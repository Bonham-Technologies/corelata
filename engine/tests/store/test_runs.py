import re
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, event, select
from sqlalchemy.exc import IntegrityError

from corelata import service
from corelata.schema import (
    Claim,
    ClaimKind,
    DraftRecord,
    Finding,
    LLMCallRecord,
    Report,
    ReportBody,
    ReportMetadata,
    ReportStatus,
    StageResult,
    Verdict,
)
from corelata.storage import LocalStorage
from corelata.store import runs
from corelata.store.models import ClaimEvidenceRow, ClaimRow, LLMCall, Run, SourceRow, utcnow
from corelata.testing.queue import RecordingQueue
from corelata.testing.sources import text_source
from tests.conftest import build_config
from tests.render.fixtures import make_report
from tests.stages.conftest import PORT

T0 = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


async def _project_with_source(s, name="p"):
    project = await runs.get_or_create_project(s, name)
    source = text_source("src1", *PORT, name="port.txt")
    row = await runs.add_source(s, project.id, source, storage_key=f"projects/{project.id}/x")
    return project, row


async def _run(s, project, source_rows, **extra):
    base = dict(
        project_id=project.id,
        value_statement="Varna port capacity expansion matters to shippers",
        profile=None,
        max_iterations=2,
        extra_guidance="",
        config_hash="h",
        config_snapshot={},
        pack_name="icd203-base",
        pack_hash="ph",
        pack_snapshot={"name": "icd203-base"},
        prompt_versions={"gate": 1},
        corelata_version="0.1.0",
        docx_reference_key=None,
        parent_run_id=None,
        source_ids=[r.id for r in source_rows],
    )
    return await runs.create_run(s, **{**base, **extra})


async def test_get_or_create_project_is_idempotent(db):
    async with db.session() as s, s.begin():
        a = await runs.get_or_create_project(s, "novel")
        b = await runs.get_or_create_project(s, "novel")
        assert a.id == b.id
        assert [p.name for p in await runs.list_projects(s)] == ["novel"]
        assert (await runs.find_project(s, "novel")).id == a.id
        assert (await runs.get_project(s, a.id)).name == "novel"
        with pytest.raises(runs.NotFoundError, match="not found"):
            await runs.get_project(s, uuid.uuid4())
        with pytest.raises(runs.NotFoundError, match="not found"):
            await runs.find_project(s, "missing")


async def test_source_round_trip_strips_nul(db):
    async with db.session() as s, s.begin():
        project = await runs.get_or_create_project(s, "p")
        source = text_source("src1", "clean", "has\x00nul", name="n.txt")
        row = await runs.add_source(s, project.id, source, storage_key="k")
    async with db.session() as s:
        rows = await runs.list_sources(s, project.id)
        assert [r.id for r in rows] == [row.id]
        loaded = await runs.load_source(s, rows[0], as_id="src7")
        assert loaded.id == "src7" and loaded.name == "n.txt" and loaded.sha256 == source.sha256
        assert [u.text for u in loaded.units] == ["clean", "hasnul"]
        assert [u.id for u in loaded.units] == ["u1", "u2"]
        assert (await runs.get_source(s, row.id)).name == "n.txt"
        with pytest.raises(runs.NotFoundError):
            await runs.get_source(s, uuid.uuid4())


async def test_create_and_get_run_with_sources_in_order(db):
    async with db.session() as s, s.begin():
        project, a = await _project_with_source(s)
        b = await runs.add_source(s, project.id, text_source("x", "b"), storage_key="kb")
        run = await _run(s, project, [b, a])
    async with db.session() as s, s.begin():
        got = await runs.get_run(s, run.id, lock=True)
        assert got.state == "created" and got.attempts == 0 and got.cancel_requested is False
        assert await runs.run_source_ids(s, run.id) == [b.id, a.id]
        assert await runs.cancel_flag(s, run.id) is False
        with pytest.raises(runs.NotFoundError, match="not found"):
            await runs.get_run(s, uuid.uuid4())


async def test_create_run_rejects_a_source_from_another_project(db):
    async with db.session() as s, s.begin():
        project, a = await _project_with_source(s, "p1")
        other, b = await _project_with_source(s, "p2")
        with pytest.raises(runs.NotFoundError, match="not in project"):
            await _run(s, project, [a, b])


async def test_stage_draft_finding_and_call_round_trips(db):
    stage = StageResult(
        stage="gating", iteration=0, ok=False, error="boom", started_at=T0, finished_at=T0
    )
    body = ReportBody.model_validate(make_report().model_dump(exclude={"metadata"}))
    draft = DraftRecord(role="writer", iteration=0, report=body)
    finding = Finding(
        rule_id="icd203.tc.8",
        verdict=Verdict.FAIL,
        evidence="e",
        cited_units=["src1/u1"],
        claim_ids=["c1"],
        recommendation="fix",
        severity="blocking",
        route_to="writer",
        iteration=1,
    )
    call = LLMCallRecord(
        role="gate",
        backend="fake",
        model="m",
        prompt_id="gate",
        prompt_version=1,
        attempt=1,
        ok=True,
        latency_ms=3,
        tokens_in=10,
        tokens_out=5,
        request={"messages": []},
        response="{}",
    )
    async with db.session() as s, s.begin():
        project, src = await _project_with_source(s)
        run = await _run(s, project, [src])
        await runs.add_stage(s, run.id, 0, stage)
        await runs.add_drafts(s, run.id, 0, [draft])
        await runs.add_findings(s, run.id, 0, [finding])
        await runs.add_llm_calls(s, run.id, 0, [call], stage="gating")
        await runs.add_llm_calls(
            s, run.id, 1, [call.model_copy(update={"attempt": 2})], stage="gating"
        )
    async with db.session() as s:
        assert await runs.load_stages(s, run.id) == [stage]
        assert await runs.load_drafts(s, run.id) == [draft]
        assert await runs.load_findings(s, run.id) == [finding]
        calls = await runs.load_llm_calls(s, run.id)
        assert [c.attempt for c in calls] == [1, 2] and calls[0] == call


async def test_stage_output_and_call_request_with_non_json_native_values(db):
    stage = StageResult(
        stage="gating",
        iteration=0,
        ok=True,
        output={"status": ReportStatus.CLEAN, "when": T0, "nested": [{"id": uuid.UUID(int=7)}]},
        started_at=T0,
        finished_at=T0,
    )
    call = LLMCallRecord(
        role="gate",
        backend="b",
        model="m",
        prompt_id="gate",
        prompt_version=1,
        attempt=1,
        ok=True,
        request={"messages": [{"sent": T0, "kind": ReportStatus.FINDINGS_OPEN}]},
    )
    async with db.session() as s, s.begin():
        project, src = await _project_with_source(s)
        run = await _run(s, project, [src])
        await runs.add_stage(s, run.id, 0, stage)
        await runs.add_llm_calls(s, run.id, 0, [call], stage="gating")
    async with db.session() as s:
        [loaded_stage] = await runs.load_stages(s, run.id)
        [loaded_call] = await runs.load_llm_calls(s, run.id)
    assert loaded_stage.model_dump(mode="json") == stage.model_dump(mode="json")
    assert loaded_stage.output["status"] == "clean"
    assert loaded_call.model_dump(mode="json") == call.model_dump(mode="json")


async def test_a_calls_reasoning_round_trips_in_its_request_column(db):
    """CRL-140: no column of its own; the trace view's lean read leaves it unread."""
    base = dict(role="gate", backend="b", model="m", prompt_id="gate", prompt_version=1, ok=True)
    thought = LLMCallRecord(
        **base,
        attempt=1,
        request={"messages": [{"role": "user", "content": "hi"}]},
        response="{}",
        reasoning="because",
        reasoning_chars=40,
    )
    bare = LLMCallRecord(**base, attempt=2, request={"messages": []}, response="{}")
    async with db.session() as s, s.begin():
        project, src = await _project_with_source(s)
        run = await _run(s, project, [src])
        await runs.add_llm_calls(s, run.id, 0, [thought, bare], stage="gating")
    async with db.session() as s:
        assert await runs.load_llm_calls(s, run.id) == [thought, bare]
        lean = await runs.load_llm_calls(s, run.id, with_io=False)
        stored = await s.scalar(
            select(LLMCall).where(LLMCall.run_id == run.id, LLMCall.ordinal == 0)
        )
    assert stored.request["reasoning"] == "because" and stored.request["reasoning_chars"] == 40
    assert lean[0].reasoning is None and lean[0].request is None


async def test_replace_claims_resolves_sources(db):
    report = make_report()  # one claim, evidence ["src1/u1"]
    async with db.session() as s, s.begin():
        project, src = await _project_with_source(s)
        run = await _run(s, project, [src])
        await runs.replace_claims(s, run.id, report, [src.id])
        await runs.replace_claims(s, run.id, report, [src.id])  # idempotent
    async with db.session() as s:
        claims = (await s.scalars(select(ClaimRow))).all()
        assert sorted(c.claim_id for c in claims) == sorted(c.id for c in report.claims)
        evidence = (await s.scalars(select(ClaimEvidenceRow))).all()
        assert all(e.source_id == src.id for e in evidence)
        assert {e.unit_ref for e in evidence} == {ref for c in report.claims for ref in c.evidence}


async def test_claim_evidence_for_an_unknown_source_has_no_source_id(db):
    report = Report(
        title="t",
        handling_marking="UNCLASSIFIED",
        key_judgments=[],
        scope_note="",
        sources=[],
        analysis=[],
        alternatives=[],
        gaps_and_indicators=[],
        claims=[Claim(id="c1", text="x", kind=ClaimKind.FACT, evidence=["src9/u1"])],
        metadata=ReportMetadata(pack_name="p", pack_hash="h"),
    )
    async with db.session() as s, s.begin():
        project, src = await _project_with_source(s)
        run = await _run(s, project, [src])
        await runs.replace_claims(s, run.id, report, [src.id])
    async with db.session() as s:
        [e] = (await s.scalars(select(ClaimEvidenceRow))).all()
        assert e.source_id is None and e.unit_ref == "src9/u1" and e.unit_id == "u1"


async def test_exports_review_events_and_clear_trace(db):
    async with db.session() as s, s.begin():
        project, src = await _project_with_source(s)
        run = await _run(s, project, [src])
        child = await _run(s, project, [src], parent_run_id=run.id)
        export = await runs.add_export(s, run.id, "report.md", "runs/x/report.md", b"# hi")
        assert export.size == 4 and len(export.sha256) == 64
        event = await runs.add_review_event(s, run.id, "return", "tighten", "alice", child.id)
        assert event.child_run_id == child.id and event.at.tzinfo is not None
        await runs.add_stage(
            s,
            run.id,
            0,
            StageResult(stage="ingesting", iteration=0, ok=True, started_at=T0, finished_at=T0),
        )
        await runs.add_llm_calls(
            s,
            run.id,
            0,
            [
                LLMCallRecord(
                    role="gate",
                    backend="b",
                    model="m",
                    prompt_id="gate",
                    prompt_version=1,
                    attempt=1,
                    ok=True,
                )
            ],
            stage="gating",
        )
    async with db.session() as s, s.begin():
        assert [e.name for e in await runs.list_exports(s, run.id)] == ["report.md"]
        await runs.clear_trace(s, run.id)
    async with db.session() as s:
        assert await runs.load_stages(s, run.id) == []
        assert await runs.load_llm_calls(s, run.id) == []
        assert await runs.list_exports(s, run.id) == []
        assert (await runs.get_run(s, child.id)).parent_run_id == run.id


async def test_delete_project_removes_its_runs(db):
    async with db.session() as s, s.begin():
        project, src = await _project_with_source(s)
        run = await _run(s, project, [src])
    async with db.session() as s, s.begin():
        await runs.delete_project(s, project.id)
    async with db.session() as s:
        with pytest.raises(runs.NotFoundError):
            await runs.get_run(s, run.id)


async def test_a_check_runs_report_source_cannot_be_deleted_alone(db):
    """CRL-94: `run.report_source_id` has no ON DELETE action, so deleting the report a check
    run audits is refused instead of silently deleting the run; deleting the project removes
    the run and the source together."""
    async with db.session() as s, s.begin():
        project, src = await _project_with_source(s)
        report = await runs.add_source(
            s,
            project.id,
            text_source("report", "The port expanded.", name="report.txt"),
            storage_key=f"projects/{project.id}/r",
        )
        run = await _run(s, project, [src], kind="check", report_source_id=report.id)
    with pytest.raises(IntegrityError, match="run_report_source_id_fkey"):
        async with db.session() as s, s.begin():
            await s.execute(delete(SourceRow).where(SourceRow.id == report.id))
    async with db.session() as s:
        assert (await runs.get_run(s, run.id)).report_source_id == report.id
    async with db.session() as s, s.begin():
        await runs.delete_project(s, project.id)
    async with db.session() as s:
        with pytest.raises(runs.NotFoundError):
            await runs.get_run(s, run.id)


async def test_list_runs_is_newest_first_and_bounded(db, tmp_path):
    cfg = build_config()
    storage = LocalStorage(tmp_path / "files")
    prompts = service.PromptLibrary(cfg.prompts_dir)
    pid = await service.create_project(db, "p")
    [sid] = await service.add_source(db, storage, pid, "a.txt", b"Varna port handles grain.")
    ids = []
    for i in range(3):
        req = service.RunRequest(project_id=pid, source_ids=[sid], value_statement=f"v{i}")
        ids.append(await service.start_run(db, storage, RecordingQueue(), cfg, prompts, req))
    async with db.session() as s, s.begin():
        for i, run_id in enumerate(ids):  # distinct, increasing creation times
            (await runs.get_run(s, run_id)).created_at = utcnow() + timedelta(seconds=i)
    async with db.session() as s:
        assert [r.id for r in await runs.list_runs(s, pid, limit=10)] == ids[::-1]
        assert [r.id for r in await runs.list_runs(s, pid, limit=2)] == ids[::-1][:2]


async def test_list_runs_pages_through_a_tie_without_skipping_or_repeating(db, tmp_path):
    cfg = build_config()
    storage = LocalStorage(tmp_path / "files")
    prompts = service.PromptLibrary(cfg.prompts_dir)
    pid = await service.create_project(db, "p")
    [sid] = await service.add_source(db, storage, pid, "a.txt", b"Varna port handles grain.")
    ids = []
    for i in range(5):
        req = service.RunRequest(project_id=pid, source_ids=[sid], value_statement=f"v{i}")
        ids.append(await service.start_run(db, storage, RecordingQueue(), cfg, prompts, req))
    async with db.session() as s, s.begin():
        for run_id in ids[1:]:  # four runs created in the same microsecond, one before them
            (await runs.get_run(s, run_id)).created_at = T0
        (await runs.get_run(s, ids[0])).created_at = T0 - timedelta(microseconds=1)
    pages: list[list[uuid.UUID]] = []
    before = None
    async with db.session() as s:
        while page := await runs.list_runs(s, pid, limit=2, before=before):
            pages.append([r.id for r in page])
            before = (page[-1].created_at, page[-1].id)
    # newest first; within the tie, the larger id first (Postgres orders uuids as Python does)
    assert [run_id for page in pages for run_id in page] == [*sorted(ids[1:], reverse=True), ids[0]]
    assert [len(page) for page in pages] == [2, 2, 1]


async def test_list_runs_leaves_the_heavy_columns_unloaded(db):
    """CRL-51: the Reports list and the sidebar poll this; a summary never needs the report or
    the snapshots. In an async session a lazy load raises, so building one proves it reads none."""
    from sqlalchemy import inspect

    async with db.session() as s, s.begin():
        project, row = await _project_with_source(s)
        run_id = (await _run(s, project, [row])).id
    async with db.session() as s:
        [run] = await runs.list_runs(s, project.id, limit=10)
        unloaded = inspect(run).unloaded
        assert {"report", "pack_snapshot", "config_snapshot", "digests", "gate"} <= unloaded
        assert "review_state" not in unloaded  # small, and the summary reads it
        summary = service._summary(run)
        assert summary.run_id == str(run_id) and summary.max_iterations == 2
        assert summary.review_decision is None


def _index_names(plan: dict) -> set[str]:
    names = {plan["Index Name"]} if "Index Name" in plan else set()
    for child in plan.get("Plans", []):
        names |= _index_names(child)
    return names


async def test_the_project_scoped_run_queries_use_the_run_list_index(db):
    """CRL-58: with `ix_run_project_id` gone, every lookup of a project's runs can still use an
    index, `ix_run_project_created`: the run list's pages, the project summary's two statements
    over `run` and the delete the project cascade issues. The table is tiny, so sequential scans
    are switched off for the EXPLAIN: a query no index serves would still plan a Seq Scan."""
    async with db.session() as s, s.begin():
        project, row = await _project_with_source(s)
        last = None
        for _ in range(3):
            last = await _run(s, project, [row])
    statements: list[tuple[str, object]] = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if re.search(r"\bFROM run\b", statement):
            statements.append((statement, parameters))

    event.listen(db.engine.sync_engine, "before_cursor_execute", capture)
    try:
        async with db.session() as s:
            await runs.list_runs(s, project.id, limit=101)
            await runs.list_runs(s, project.id, limit=101, before=(last.created_at, last.id))
            await runs.project_summaries(s, project.id)
    finally:
        event.remove(db.engine.sync_engine, "before_cursor_execute", capture)
    assert len(statements) == 4, statements  # two pages, the summary's count and newest run
    # what the FK's ON DELETE CASCADE runs when a project is deleted
    statements.append(("DELETE FROM run WHERE project_id = %(p)s", {"p": project.id}))
    async with db.engine.connect() as conn, conn.begin():
        await conn.exec_driver_sql("SET LOCAL enable_seqscan = off")
        for statement, parameters in statements:
            explained = await conn.exec_driver_sql(f"EXPLAIN (FORMAT JSON) {statement}", parameters)
            plan = explained.scalar_one()[0]["Plan"]
            assert _index_names(plan) == {"ix_run_project_created"}, (statement, plan)


async def test_get_run_brief_leaves_the_heavy_columns_unloaded(db):
    from sqlalchemy import inspect

    async with db.session() as s, s.begin():
        project, row = await _project_with_source(s)
        run_id = (await _run(s, project, [row])).id
    async with db.session() as s:
        run = await runs.get_run_brief(s, run_id)
        unloaded = inspect(run).unloaded
        assert {"report", "pack_snapshot", "config_snapshot", "digests", "gate"} <= unloaded
        assert "review_state" not in unloaded  # small, and the progress read needs it
        assert run.state == "created" and run.max_iterations == 2 and run.pack_name == "icd203-base"
        progress = service._progress(run, [], [])
        assert progress.run_id == str(run_id) and progress.stages == []
        assert progress.review is None
        with pytest.raises(runs.NotFoundError):
            await runs.get_run_brief(s, uuid.uuid4())


async def test_set_review_state_writes_and_clears_the_column(db):
    state = {
        "decision": "accepted",
        "at": "2026-10-15T10:00:00Z",
        "actor": "alice",
        "child_run_id": None,
    }
    async with db.session() as s, s.begin():
        project, src = await _project_with_source(s)
        run_id = (await _run(s, project, [src])).id
        assert (await runs.get_run(s, run_id)).review_state is None
        await runs.lock_run(s, run_id)
        await runs.set_review_state(s, run_id, state)
    async with db.session() as s, s.begin():
        assert (await runs.get_run_brief(s, run_id)).review_state == state
        await runs.set_review_state(s, run_id, None)
    async with db.session() as s:
        is_null = await s.scalar(select(Run.review_state.is_(None)).where(Run.id == run_id))
        assert is_null is True  # SQL NULL, not the JSON value null
