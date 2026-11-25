"""CRL-138: what the analyst states about a source is written over the writer's and conveyor's
source entries, and what the engine overwrote is reported."""

import json

from corelata.schema import SourceStatement
from corelata.stages.convey import run_conveyor
from corelata.stages.stated import applied_values, apply_stated, statement_errors
from corelata.stages.write import run_writer
from corelata.testing.sources import coglossa_source, text_source
from tests.stages.conftest import PORT
from tests.stages.test_source_references import _without

STATED = SourceStatement(
    descriptor="official government publication",
    reliability_note="Analyst: the authority's own figures, not independently checked.",
    date_of_information="August 2026",
    origin="Varna Port Authority press office",
    access="direct",
)


def _stated_source(stated: SourceStatement = STATED, *, source_id: str = "src1"):
    source = text_source(source_id, *PORT)
    return source.model_copy(update={"stated": stated})


async def test_the_writer_report_carries_stated_values_verbatim(make_ctx, fake_backend):
    ctx = make_ctx(_stated_source(), text_source("src2", "Rail link."))
    body = await run_writer(ctx, iteration=0, prior=None, findings=[])
    first, second = body.sources
    for name, value in STATED.values().items():
        assert getattr(first, name) == value
    assert second.origin != STATED.origin  # a source with nothing stated keeps the model's
    fields = {(o["source_id"], o["field"]) for o in ctx.stated_overrides}
    assert fields == {("src1", name) for name in STATED.values()}
    descriptor = next(o for o in ctx.stated_overrides if o["field"] == "descriptor")
    assert descriptor["stated_value"] == STATED.descriptor
    assert descriptor["model_value"] != STATED.descriptor


async def test_a_conveyor_change_to_a_stated_value_is_written_over(make_ctx, fake_backend):
    ctx = make_ctx(_stated_source(SourceStatement(descriptor="open-source media article")))
    draft = await run_writer(ctx, iteration=0, prior=None, findings=[])
    assert draft.sources[0].descriptor == "open-source media article"
    data = draft.model_dump()
    data["sources"][0]["descriptor"] = "open-source report"
    data["sources"][0]["reliability_note"] = "Reworded by the conveyor."
    fake_backend.script("conveyor", json.dumps(data))
    out = await run_conveyor(ctx, iteration=0, draft=draft, findings=[])
    assert out.sources[0].descriptor == "open-source media article"
    assert out.sources[0].reliability_note == "Reworded by the conveyor."  # not stated
    assert ctx.stated_overrides == [
        {
            "source_id": "src1",
            "field": "descriptor",
            "model_value": "open-source report",
            "stated_value": "open-source media article",
        }
    ]


async def test_nothing_stated_leaves_the_reply_and_overrides_alone(make_ctx):
    ctx = make_ctx()
    body = await run_writer(ctx, iteration=0, prior=None, findings=[])
    assert ctx.stated_overrides == []
    again, overrides = apply_stated(ctx.sources, ctx.pack, body)
    assert again is body and overrides == []


async def test_a_stated_note_is_kept_verbatim_on_a_coglossa_source(make_ctx):
    """A Coglossa source's note normally names its tier (CRL-96); a stated one is the
    analyst's words, as given."""
    source = coglossa_source("src1").model_copy(
        update={"stated": SourceStatement(reliability_note="Checked by a linguist.")}
    )
    ctx = make_ctx(source)
    body = await run_writer(ctx, iteration=0, prior=None, findings=[])
    assert body.sources[0].reliability_note == "Checked by a linguist."


async def test_without_source_details_only_the_descriptor_and_note_apply(make_ctx, pack):
    ctx = make_ctx(_stated_source())
    ctx.pack = _without(pack)
    body = await run_writer(ctx, iteration=0, prior=None, findings=[])
    entry = body.sources[0]
    assert entry.descriptor == STATED.descriptor
    assert entry.reliability_note == STATED.reliability_note
    assert entry.details() == ("", "", "")
    assert {o["field"] for o in ctx.stated_overrides} <= {"descriptor", "reliability_note"}
    assert applied_values(STATED, ctx.pack) == {
        "descriptor": STATED.descriptor,
        "reliability_note": STATED.reliability_note,
    }


def test_statement_errors_check_the_lexicon(pack):
    lexicon = pack.lexicon
    assert statement_errors(STATED, lexicon, "source a.txt") == []
    bad = SourceStatement(descriptor="Gossip", access="rumour", origin="anyone")
    errors = statement_errors(bad, lexicon, "source a.txt")
    assert len(errors) == 2
    assert errors[0].startswith("source a.txt: descriptor 'Gossip' is not in the lexicon")
    assert errors[1].startswith("source a.txt: access 'rumour' is not in the lexicon")
    open_lexicon = lexicon.model_copy(update={"source_descriptors": [], "source_access": []})
    assert statement_errors(bad, open_lexicon, "source a.txt") == []


def test_a_statement_strips_values_and_dumps_only_what_is_stated():
    stated = SourceStatement(origin="  Reuters  ", access=" ")
    assert stated.values() == {"origin": "Reuters"}
    # a pasted vertical tab or control character would stop the DOCX export
    pasted = SourceStatement(reliability_note="Checked.\x0bTwice.\x01", access="\x00")
    assert pasted.values() == {"reliability_note": "Checked.\nTwice."}
    assert stated.model_dump() == {"origin": "Reuters"}
    source = text_source("src1", "x")
    assert "stated" not in source.model_dump()
    assert source.model_copy(update={"stated": stated}).model_dump()["stated"] == {
        "origin": "Reuters"
    }
