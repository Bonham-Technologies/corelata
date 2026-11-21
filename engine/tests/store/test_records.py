import uuid

import pytest

from corelata import service
from corelata.schema import RunState
from corelata.store import records, runs
from corelata.testing.sources import coglossa_source, text_source
from corelata.trace import TraceError, UnitCount, claim_provenance, run_trace
from tests.stages.conftest import PORT

STATEMENT = "Varna port capacity expansion matters to shippers"


async def _rows_for(db, record, sources):
    """Project, source and run rows that correspond to an in-process record."""
    async with db.session() as s, s.begin():
        project = await runs.get_or_create_project(s, "p")
        source_rows = [
            await runs.add_source(s, project.id, src, storage_key=f"k/{src.id}") for src in sources
        ]
        run = await runs.create_run(
            s,
            project_id=project.id,
            value_statement=record.value_statement,
            profile=record.profile,
            max_iterations=record.max_iterations,
            extra_guidance=record.extra_guidance,
            config_hash=record.config_hash,
            config_snapshot={},
            pack_name=record.pack_name,
            pack_hash=record.pack_hash,
            pack_snapshot=record.pack_snapshot,
            prompt_versions=record.prompt_versions,
            corelata_version=record.corelata_version,
            docx_reference_key=None,
            parent_run_id=None,
            source_ids=[r.id for r in source_rows],
            run_id=uuid.UUID(record.run_id),
            created_at=record.created_at,
        )
    return run.id, [r.id for r in source_rows]


@pytest.mark.parametrize(
    ("statement", "extra", "state"),
    [
        (STATEMENT, "", RunState.COMPLETED),
        ("Antarctic penguin colonies are shrinking", "", RunState.GATE_REJECTED),
        (STATEMENT, "UNSOURCED", RunState.COMPLETED),
    ],
)
async def test_record_round_trips_through_rows(db, run, statement, extra, state):
    rid = uuid.uuid4()
    sources = [text_source("src1", *PORT), text_source("src2", "Shippers welcomed Varna.", extra)]
    record = await run(*sources, statement=statement, run_id=str(rid))
    assert record.state is state
    run_id, source_ids = await _rows_for(db, record, sources)
    async with db.session() as s, s.begin():
        row = await runs.get_run(s, run_id, lock=True)
        await records.save_outcome(s, row, record, source_ids=source_ids)
    async with db.session() as s:
        loaded = await records.load_record(s, run_id)
        row = await runs.get_run(s, run_id)
    assert loaded.model_dump() == record.model_dump()
    assert row.finished_at is not None and row.state == state.value
    assert row.token_usage == record.usage.model_dump()
    assert (row.report is None) == (record.report is None)


async def test_load_sources_keeps_the_run_order_and_names(db, run):
    rid = uuid.uuid4()
    a, b = text_source("src1", "alpha"), text_source("src2", "beta", name="b.md")
    record = await run(a, b, run_id=str(rid))
    run_id, source_ids = await _rows_for(db, record, [b, a])  # stored in the other order
    async with db.session() as s:
        loaded = await records.load_sources(s, run_id)
    assert [(x.id, x.name) for x in loaded] == [("src1", "b.md"), ("src2", "src1.txt")]
    assert loaded[0].units[0].text == "beta"


async def test_save_outcome_appends_only_what_is_not_persisted_yet(db, run):
    rid = uuid.uuid4()
    record = await run(run_id=str(rid))
    run_id, source_ids = await _rows_for(db, record, [text_source("src1", *PORT)])
    async with db.session() as s, s.begin():
        await runs.add_stage(s, run_id, 0, record.stages[0])
        await runs.add_llm_calls(s, run_id, 0, record.llm_calls[:1], stage="gating")
        row = await runs.get_run(s, run_id, lock=True)
        await records.save_outcome(
            s, row, record, source_ids=source_ids, stages_from=1, calls_from=1
        )
    async with db.session() as s:
        loaded = await records.load_record(s, run_id)
    assert loaded.stages == record.stages and loaded.llm_calls == record.llm_calls


async def test_load_record_of_an_unknown_run(db):
    async with db.session() as s:
        with pytest.raises(runs.NotFoundError):
            await records.load_record(s, uuid.uuid4())


async def test_review_reads_leave_the_stored_model_io_unread(db, run):
    """CRL-103: the trace's record without the calls' bodies, the findings and the claim's
    provenance from their own rows, each as the whole record gives them."""
    rid = uuid.uuid4()
    record = await run(run_id=str(rid))
    assert record.report is not None and record.findings
    assert all(c.request and c.response for c in record.llm_calls)
    run_id, source_ids = await _rows_for(db, record, [text_source("src1", *PORT)])
    async with db.session() as s, s.begin():
        row = await runs.get_run(s, run_id, lock=True)
        await records.save_outcome(s, row, record, source_ids=source_ids)
    lean = await service.get_run_record(db, run_id, with_io=False)
    assert all(c.request is None and c.response is None for c in lean.llm_calls)
    bare = [c.model_copy(update={"request": None, "response": None}) for c in record.llm_calls]
    assert lean.model_dump() == record.model_copy(update={"llm_calls": bare}).model_dump()
    assert await service.get_findings(db, run_id) == record.findings
    claim_id = record.report.claims[0].id
    assert await service.get_claim_provenance(db, run_id, claim_id) == claim_provenance(
        record, claim_id
    )
    with pytest.raises(TraceError, match="unknown claim id 'zzz'"):
        await service.get_claim_provenance(db, run_id, "zzz")


async def test_review_reads_of_a_run_without_a_report_or_findings(db, run):
    rid = uuid.uuid4()
    record = await run(run_id=str(rid))
    run_id, _ = await _rows_for(db, record, [text_source("src1", *PORT)])  # created, no outcome
    assert await service.get_findings(db, run_id) == []
    with pytest.raises(service.InvalidRunStateError, match=r"has no report \(state created\)"):
        await service.get_claim_provenance(db, run_id, "c0")
    unknown = uuid.uuid4()
    with pytest.raises(runs.NotFoundError, match=f"run {unknown} not found"):
        await service.get_findings(db, unknown)
    with pytest.raises(runs.NotFoundError, match=f"run {unknown} not found"):
        await service.get_claim_provenance(db, unknown, "c0")


async def test_the_trace_counts_units_and_a_claim_reads_only_its_evidence(db, run):
    """CRL-124: the trace's record leaves the units unread and the database counts them; a
    claim's sources carry the units its refs name and no others."""
    rid = uuid.uuid4()
    sources = [
        text_source("src1", *PORT),
        coglossa_source("src2", "A", "C"),
        text_source("src3", "Shippers welcomed Varna."),
    ]
    record = await run(*sources, run_id=str(rid))
    run_id, source_ids = await _rows_for(db, record, sources)
    async with db.session() as s, s.begin():
        row = await runs.get_run(s, run_id, lock=True)
        await records.save_outcome(s, row, record, source_ids=source_ids)
    whole = await service.get_run_record(db, run_id, with_io=False)
    assert await service.get_run_trace(db, run_id) == run_trace(whole)
    async with db.session() as s:
        assert await records.unit_counts(s, run_id) == {
            "src1": UnitCount(3, None),
            "src2": UnitCount(2, "C"),
            "src3": UnitCount(1, None),
        }
        bare = await records.load_record(s, run_id, with_io=False, with_units=False)
        cited = await records.load_sources(s, run_id, refs=["src1/u3", "src1/u1", "src2/u2", "x"])
    assert [(x.id, x.units) for x in bare.sources] == [("src1", []), ("src2", []), ("src3", [])]
    assert bare.model_copy(update={"sources": whole.sources}) == whole
    assert [x.units for x in cited] == [
        [whole.sources[0].units[0], whole.sources[0].units[2]],
        [whole.sources[1].units[1]],
        [],
    ]
