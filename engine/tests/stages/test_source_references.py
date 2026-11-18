"""CRL-96: source details (date of information, origin, access) and the source summary in the
writer's and conveyor's schema, validator and reply shaping."""

import json

import pytest

from corelata.llm.agent import StructuredOutputError
from corelata.schema import SourceEntry
from corelata.stages.convey import run_conveyor
from corelata.stages.write import filled_entry, run_writer, tier_note
from corelata.testing.sources import coglossa_source, text_source
from corelata.testing.synthetic import synthetic_response
from tests.stages.conftest import PORT


def _without(pack, *, details: bool = False, summary: bool = False):
    """The base pack as a profile turning the CRL-96 additions off would resolve it."""
    lexicon = pack.lexicon.model_copy(update={"source_access": [] if not details else ["x"]})
    order = [s for s in pack.template.section_order if summary or s != "source_summary"]
    template = pack.template.model_copy(update={"section_order": order})
    return pack.model_copy(update={"lexicon": lexicon, "template": template})


def _payload(ctx) -> dict:
    record = ctx.runner.log.records[-1]
    return json.loads(record.request["messages"][1]["content"].split("\n", 1)[1])


async def test_the_base_pack_asks_for_source_details_and_a_summary(make_ctx, fake_backend):
    source = text_source("src1", *PORT, name="port.html")
    source.provenance = {"date": "2026-08-10", "origin": "Varna Port Authority"}
    ctx = make_ctx(source)
    body = await run_writer(ctx, iteration=0, prior=None, findings=[])
    [entry] = body.sources
    assert (entry.date_of_information, entry.origin, entry.access) == (
        "2026-08-10",
        "Varna Port Authority",
        "unknown",
    )
    assert body.source_summary is not None and body.source_summary.key_sources == ["src1"]
    schema = fake_backend.requests[0].json_schema
    assert schema["$defs"]["SourceAccess"]["enum"] == ["direct", "indirect", "unknown"]
    assert schema["properties"]["source_summary"] == {"$ref": "#/$defs/SourceSummaryStatement"}
    prompt = fake_backend.requests[0].messages[0].content
    assert "date_of_information" in prompt and "conflicting_sources" in prompt
    assert ctx.runner.log.records[0].prompt_version == 5
    payload = _payload(ctx)
    assert payload["lexicon"]["source_access"] == ["direct", "indirect", "unknown"]
    assert "source_summary" in payload["template"]["section_order"]


async def test_the_writer_answer_wins_over_the_ingest_hint(make_ctx, fake_backend):
    """The writer is offered the hints and confirms them: one it leaves blank, because the
    source shows it wrong or it is unknown, stays blank in the delivered report."""
    source = text_source("src1", *PORT)
    source.provenance = {"date": "2026-08-10", "origin": "Varna Port Authority"}
    ctx = make_ctx(source)
    good = synthetic_response({**_writer_input(ctx), "sources": [{"id": "src1", "provenance": {}}]})
    good["sources"][0].update(date_of_information="", origin="Port press office", access="direct")
    fake_backend.script("writer", json.dumps(good))
    body = await run_writer(ctx, iteration=0, prior=None, findings=[])
    entry = body.sources[0]
    assert (entry.date_of_information, entry.origin, entry.access) == (
        "",  # the writer rejected the hint
        "Port press office",  # the writer's own value stands
        "direct",
    )
    assert _payload(ctx)["sources"][0]["provenance"] == source.provenance


def _writer_input(ctx) -> dict:
    return {
        "task": "writer",
        "value_statement": ctx.value_statement,
        "template": ctx.pack.template.model_dump(),
        "lexicon": ctx.pack.lexicon.model_dump(),
        "units": ctx.unit_payload(ctx.index.refs()),
        "sources": ctx.source_payload(),
    }


async def test_the_validator_wants_lexicon_access_and_a_summary_of_known_sources(
    make_ctx, fake_backend
):
    ctx = make_ctx(text_source("src1", *PORT), text_source("src2", "Rail link."))
    good = synthetic_response(_writer_input(ctx))
    bad = json.loads(json.dumps(good))
    bad["sources"][0]["access"] = "rumour"
    bad.pop("source_summary")
    fake_backend.script("writer", json.dumps(bad), json.dumps(good))
    await run_writer(ctx, iteration=0, prior=None, findings=[])
    repair = fake_backend.requests[1].messages[3].content
    assert "source 'src1': access 'rumour' is not in the lexicon" in repair
    assert "source_summary is missing" in repair
    bad = json.loads(json.dumps(good))
    bad["source_summary"]["key_sources"] = ["src9"]
    bad["source_summary"]["conflicting_sources"] = ["src8"]
    fake_backend.script("writer", json.dumps(bad), json.dumps(good))
    await run_writer(ctx, iteration=0, prior=None, findings=[])
    repair = fake_backend.requests[3].messages[3].content
    assert "unknown source id 'src9' in source_summary.key_sources" in repair
    assert "unknown source id 'src8' in source_summary.conflicting_sources" in repair


async def test_the_synthetic_writer_names_conflicting_sources(make_ctx):
    ctx = make_ctx(text_source("src1", *PORT), text_source("src2", "CONFLICT: capacity fell."))
    body = await run_writer(ctx, iteration=0, prior=None, findings=[])
    assert body.source_summary is not None
    assert body.source_summary.conflicting_sources == ["src2"]
    assert "conflict" in body.source_summary.corroboration


async def test_a_pack_without_them_sends_the_old_schema_and_drops_stray_fields(
    make_ctx, fake_backend, pack
):
    ctx = make_ctx()
    ctx.pack = _without(pack)
    stray = synthetic_response(
        {**_writer_input(make_ctx()), "sources": [{"id": "src1", "provenance": {}}]}
    )
    assert stray["source_summary"] and stray["sources"][0]["access"]
    fake_backend.script("writer", json.dumps(stray))
    body = await run_writer(ctx, iteration=0, prior=None, findings=[])
    assert body.source_summary is None
    assert body.sources[0].details() == ("", "", "")
    assert "source_summary" not in body.model_dump() and "access" not in body.model_dump_json()
    schema = fake_backend.requests[0].json_schema
    assert "SourceAccess" not in schema["$defs"] and "source_summary" not in schema["properties"]
    assert list(schema["$defs"]["SourceEntry"]["properties"]) == [
        "source_id",
        "descriptor",
        "reliability_note",
    ]
    prompt = fake_backend.requests[0].messages[0].content
    assert "date_of_information" not in prompt and "source_summary" not in prompt


async def test_without_source_details_the_writer_payload_carries_no_hints(make_ctx, pack):
    """A pack without source details sends the writer exactly the payload it sent before
    CRL-96: ingest's date and origin hints stay on the source, out of the payload."""
    hinted = text_source("src1", *PORT, name="port.html")
    hinted.provenance = {"date": "2026-08-10", "origin": "Varna Port Authority"}
    ctx = make_ctx(hinted, text_source("src3", "Rail link."), coglossa_source("src2", "B"))
    ctx.pack = _without(pack)
    await run_writer(ctx, iteration=0, prior=None, findings=[])
    sources = _payload(ctx)["sources"]
    assert [s["provenance"] for s in sources] == [
        {},
        {},
        {"coglossa_run_id": "run-42"},
    ]
    assert ctx.source_payload()[0] == {
        "id": "src1",
        "name": "port.html",
        "format": "txt",
        "provenance": {},
    }
    assert hinted.provenance == {"date": "2026-08-10", "origin": "Varna Port Authority"}


async def test_a_coglossa_source_note_names_its_lowest_tier(make_ctx):
    ctx = make_ctx(text_source("src1", *PORT), coglossa_source("src2", "A", "C", "B", "unscored"))
    body = await run_writer(ctx, iteration=0, prior=None, findings=[])
    notes = {e.source_id: e.reliability_note for e in body.sources}
    assert notes["src1"] == "Synthetic: current and complete."
    assert notes["src2"] == "Coglossa reliability tier C. Synthetic: current and complete."
    sources = _payload(ctx)["sources"]
    assert "reliability_tier" not in sources[0] and sources[1]["reliability_tier"] == "C"
    out = await run_conveyor(ctx, iteration=0, draft=body, findings=[])
    assert out.sources == body.sources  # shaping is idempotent


def test_tier_note_keeps_a_note_that_names_the_tier_and_skips_unscored_sources():
    scored = coglossa_source("src2", "B")
    assert tier_note(scored, "Translation tier B, checked.") == "Translation tier B, checked."
    assert tier_note(scored, "") == "Coglossa reliability tier B."
    assert tier_note(coglossa_source("src2", "unscored"), "") == ""
    assert tier_note(text_source("src1", "x"), "Fine.") == "Fine."


def test_filled_entry_leaves_an_unknown_source_to_the_validator(make_ctx):
    entry = SourceEntry(source_id="src9", descriptor="open-source report")
    assert filled_entry(make_ctx(), entry) is entry


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda d: d["sources"][0].__setitem__("access", "direct"),
            "source 'src1' changed date_of_information, origin or access",
        ),
        (
            lambda d: d["sources"][0].__setitem__("origin", "Someone else"),
            "source 'src1' changed date_of_information, origin or access",
        ),
        (
            lambda d: d["source_summary"].__setitem__("key_sources", []),
            "source_summary.key_sources changed",
        ),
        (
            lambda d: d["source_summary"].__setitem__("conflicting_sources", ["src1"]),
            "source_summary.conflicting_sources changed",
        ),
    ],
)
async def test_the_conveyor_keeps_source_details_and_the_summary_sources(
    make_ctx, fake_backend, mutate, message
):
    ctx = make_ctx()
    draft = await run_writer(ctx, iteration=0, prior=None, findings=[])
    data = draft.model_dump()
    mutate(data)
    bad = json.dumps(data)
    fake_backend.script("conveyor", bad, bad)
    with pytest.raises(StructuredOutputError, match=message):
        await run_conveyor(ctx, iteration=0, draft=draft, findings=[])


async def test_the_conveyor_may_reword_the_summary(make_ctx, fake_backend):
    source = text_source("src1", *PORT)
    source.provenance = {"date": "2026"}
    ctx = make_ctx(source)
    draft = await run_writer(ctx, iteration=0, prior=None, findings=[])
    data = draft.model_dump()
    data["source_summary"]["corroboration"] = "Reworded."
    blanked = json.loads(json.dumps(data))
    blanked["sources"][0]["date_of_information"] = ""  # the engine never fills it again
    fake_backend.script("conveyor", json.dumps(blanked), json.dumps(data))
    out = await run_conveyor(ctx, iteration=0, draft=draft, findings=[])
    repair = fake_backend.requests[-1].messages[3].content
    assert "source 'src1' changed date_of_information" in repair
    assert out.source_summary is not None and out.source_summary.corroboration == "Reworded."
    assert out.sources[0].date_of_information == "2026"
    prompt = fake_backend.requests[-1].messages[0].content
    assert "key_sources" in prompt and "date_of_information" in prompt


async def test_the_conveyor_check_is_off_without_details_or_summary(make_ctx, fake_backend, pack):
    ctx = make_ctx()
    ctx.pack = _without(pack)
    draft = await run_writer(ctx, iteration=0, prior=None, findings=[])
    data = draft.model_dump()
    data["sources"][0]["access"] = "direct"
    fake_backend.script("conveyor", json.dumps(data))
    out = await run_conveyor(ctx, iteration=0, draft=draft, findings=[])
    assert out.sources[0].access == ""
