from datetime import UTC, datetime

from sqlalchemy import select

from corelata.schema import LLMCallRecord, StageResult
from corelata.store import runs
from corelata.store.models import DraftRow, LLMCall, StageResultRow
from tests.worker.conftest import drain, make_services, submit

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _call(**kw) -> LLMCallRecord:
    return LLMCallRecord(
        role="writer",
        backend="fake",
        model="m",
        prompt_id="writer",
        prompt_version=1,
        attempt=1,
        ok=True,
        **kw,
    )


def _stage(output: dict) -> StageResult:
    return StageResult(
        stage="x", iteration=0, ok=True, output=output, started_at=NOW, finished_at=NOW
    )


async def _finished_run(db, fake_backend, tmp_path):
    svc = make_services(db, fake_backend, tmp_path)
    run_id = await submit(svc)
    await drain(svc)
    return run_id


async def test_nul_characters_are_stripped_on_every_write_path(db, fake_backend, tmp_path):
    run_id = await _finished_run(db, fake_backend, tmp_path)
    async with db.session() as s:
        draft = (await runs.load_drafts(s, run_id))[0]
    dirty = draft.model_copy(update={"report": draft.report.model_copy(update={"title": "a\x00b"})})
    stage = _stage({"k\x00": ["v\x00w", {"n": "p\x00q"}]})
    call = _call(request={"messages": ["r\x00s"]}, response="t\x00u")
    async with db.session() as s, s.begin():
        await runs.add_stage(s, run_id, 90, stage)
        await runs.add_llm_calls(s, run_id, 90, [call], stage="x")
        await runs.add_drafts(s, run_id, 90, [dirty])
        (await runs.get_run(s, run_id, lock=True)).error = "e\x00rror"
    async with db.session() as s:
        row = await s.scalar(select(StageResultRow).where(StageResultRow.ordinal == 90))
        assert row.output == {"k": ["vw", {"n": "pq"}]}
        llm = await s.scalar(select(LLMCall).where(LLMCall.ordinal == 90))
        assert llm.request == {"messages": ["rs"]} and llm.response == "tu"
        d = await s.scalar(select(DraftRow).where(DraftRow.ordinal == 90))
        assert d.report["title"] == "ab"
        assert (await runs.get_run(s, run_id)).error == "error"


async def test_a_lone_surrogate_is_replaced_not_fatal(db, fake_backend, tmp_path):
    run_id = await _finished_run(db, fake_backend, tmp_path)
    async with db.session() as s, s.begin():
        await runs.add_stage(s, run_id, 91, _stage({"text": "bad \ud800 text"}))
        await runs.add_llm_calls(s, run_id, 91, [_call(response="bad \ud800 text")], stage="x")
    async with db.session() as s:
        row = await s.scalar(select(StageResultRow).where(StageResultRow.ordinal == 91))
        assert row.output == {"text": "bad � text"}
        llm = await s.scalar(select(LLMCall).where(LLMCall.ordinal == 91))
        assert llm.response == "bad � text"
