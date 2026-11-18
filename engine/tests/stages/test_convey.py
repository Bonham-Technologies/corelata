import json

import pytest

from corelata.llm.agent import StructuredOutputError
from corelata.schema import ReportBody
from corelata.stages.convey import run_conveyor
from corelata.stages.write import run_writer


async def test_conveyor_edits_and_keeps_claims(make_ctx):
    ctx = make_ctx()
    draft = await run_writer(ctx, iteration=0, prior=None, findings=[])
    out = await run_conveyor(ctx, iteration=0, draft=draft, findings=[])
    assert out.title == "Conveyed: " + draft.title
    assert out.claims == draft.claims
    rec = ctx.runner.log.records[1]
    assert rec.role == "conveyor" and rec.prompt_id == "conveyor"
    payload = json.loads(rec.request["messages"][1]["content"].split("\n", 1)[1])
    assert [r["id"] for r in payload["rules"]] == [r.id for r in ctx.pack.rules_for("conveyor")]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d["claims"].pop(), "claim set changed"),
        (lambda d: d["claims"][1].__setitem__("evidence", []), "claim 'c1' changed evidence"),
        (
            lambda d: d["claims"][1]["evidence"].append("src1/u3"),
            "claim 'c1' changed evidence",
        ),
        (
            lambda d: d["claims"][1].__setitem__("likelihood_term", "almost certain"),
            "claim 'c1' changed likelihood term",
        ),
        (lambda d: d["claims"][1].__setitem__("kind", "judgment"), "claim 'c1' changed kind"),
    ],
)
async def test_conveyor_validator_guards_claims(make_ctx, fake_backend, mutate, message):
    ctx = make_ctx()
    draft = await run_writer(ctx, iteration=0, prior=None, findings=[])
    data = draft.model_dump()
    mutate(data)
    if message == "claim set changed":
        last = [draft.claims[-1].id]
        for section in data["analysis"]:
            section["paragraphs"] = [p for p in section["paragraphs"] if p["claim_ids"] != last]
    bad = json.dumps(data)
    fake_backend.script("conveyor", bad, bad)
    with pytest.raises(StructuredOutputError, match=message):
        await run_conveyor(ctx, iteration=0, draft=draft, findings=[])


async def test_run_conveyor_sends_the_unit_and_source_enums_and_returns_a_report_body(
    make_ctx, fake_backend
):
    ctx = make_ctx()
    draft = await run_writer(ctx, iteration=0, prior=None, findings=[])
    out = await run_conveyor(ctx, iteration=0, draft=draft, findings=[])
    request = fake_backend.requests[-1]
    assert request.schema_name == "ReportBody"
    assert request.json_schema["$defs"]["UnitRef"]["enum"] == ctx.index.refs()
    assert request.json_schema["$defs"]["SourceId"]["enum"] == ["src1"]
    assert all(type(s.source_id) is str for s in out.sources)
    assert type(out) is ReportBody and out.claims == draft.claims
    assert all(type(r) is str for c in out.claims for r in c.evidence)
