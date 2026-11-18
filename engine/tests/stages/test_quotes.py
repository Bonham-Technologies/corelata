"""CRL-93: quote-anchored claim evidence through the writer, the conveyor and the auditor."""

import json

import pytest

from corelata.llm.agent import StructuredOutputError
from corelata.schema import Digest, Verdict
from corelata.stages.audit import (
    BOTH_FIX,
    ENGINE_CHECK,
    QUOTE_FIX,
    UNSOURCED_FIX,
    apply_engine_checks,
    cited_unit_payload,
    engine_only_findings,
    open_findings,
    run_auditor,
)
from corelata.stages.convey import run_conveyor
from corelata.stages.write import run_writer
from corelata.testing.sources import text_source
from tests.stages.conftest import PORT
from tests.stages.test_audit import lenient_reply

FABRICATED = "will close to all tankers by March"


@pytest.fixture
def quoting_ctx(make_ctx, make_config):
    def _make(*sources, mode="required", **kw):
        return make_ctx(*sources, cfg=make_config(pipeline={"evidence_quotes": mode}), **kw)

    return _make


def _sent(ctx, index=-1) -> dict:
    return json.loads(
        ctx.runner.log.records[index].request["messages"][1]["content"].split("\n", 1)[1]
    )


def _misquote(draft, claim_id="c1", text=FABRICATED):
    data = draft.model_dump()
    claim = next(c for c in data["claims"] if c["id"] == claim_id)
    claim["quotes"][0]["text"] = text
    return type(draft).model_validate(data)


async def test_the_writer_quotes_and_sends_the_mode_only_when_quoting(quoting_ctx, fake_backend):
    ctx = quoting_ctx()
    draft = await run_writer(ctx, iteration=0, prior=None, findings=[])
    assert all(q.ref in c.evidence for c in draft.claims for q in c.quotes)
    assert all(c.quotes for c in draft.claims if c.evidence)
    assert _sent(ctx)["evidence_quotes"] == "required"
    assert "Quote" in fake_backend.requests[-1].json_schema["$defs"]
    assert '"quotes": for every ref' in fake_backend.requests[-1].messages[0].content

    off = quoting_ctx(mode="off")
    plain = await run_writer(off, iteration=0, prior=None, findings=[])
    assert "evidence_quotes" not in _sent(off) and all(not c.quotes for c in plain.claims)
    assert "Quote" not in fake_backend.requests[-1].json_schema["$defs"]
    assert "quotes" not in fake_backend.requests[-1].messages[0].content


async def test_optional_mode_asks_for_quotes_without_requiring_them(quoting_ctx, fake_backend):
    ctx = quoting_ctx(mode="optional")
    await run_writer(ctx, iteration=0, prior=None, findings=[])
    system = fake_backend.requests[-1].messages[0].content
    assert '"quotes": optionally' in system and "left unquoted" not in system


async def test_off_drops_quotes_a_reply_carries_anyway(quoting_ctx, fake_backend):
    quoted = await run_writer(quoting_ctx(), iteration=0, prior=None, findings=[])
    ctx = quoting_ctx(mode="off")
    fake_backend.script("writer", quoted.model_dump_json())
    body = await run_writer(ctx, iteration=0, prior=None, findings=[])
    assert body.claims and all(not c.quotes for c in body.claims)
    fake_backend.script("conveyor", quoted.model_dump_json())
    conveyed = await run_conveyor(ctx, iteration=0, draft=body, findings=[])
    assert all(not c.quotes for c in conveyed.claims)


async def test_a_quote_must_name_a_unit_its_claim_cites(quoting_ctx, fake_backend):
    ctx = quoting_ctx()
    good = (await run_writer(ctx, iteration=0, prior=None, findings=[])).model_dump()
    good["claims"][1]["quotes"] = [
        {"ref": "src1/u3", "text": "Container traffic"},
        {"ref": "src9/u1", "text": "x"},
    ]
    bad = json.dumps(good)
    fake_backend.script("writer", bad, bad)
    with pytest.raises(StructuredOutputError):
        await run_writer(ctx, iteration=0, prior=None, findings=[])
    repair = fake_backend.requests[-1].messages[-1].content
    assert "'src9/u1' is not a unit id" in repair
    assert "claim 'c1' quotes 'src1/u3', which is not in its evidence" in repair


async def test_the_conveyor_keeps_quotes_and_sends_them(quoting_ctx, fake_backend):
    ctx = quoting_ctx()
    draft = await run_writer(ctx, iteration=0, prior=None, findings=[])
    assert "Quote" in fake_backend.requests[-1].json_schema["$defs"]
    conveyed = await run_conveyor(ctx, iteration=0, draft=draft, findings=[])
    assert [c.quotes for c in conveyed.claims] == [c.quotes for c in draft.claims]
    assert "Quote" in fake_backend.requests[-1].json_schema["$defs"]
    assert "quotes" in fake_backend.requests[-1].messages[0].content
    edited = _misquote(draft)
    fake_backend.script("conveyor", edited.model_dump_json(), edited.model_dump_json())
    with pytest.raises(StructuredOutputError):
        await run_conveyor(ctx, iteration=0, draft=draft, findings=[])
    assert "claim 'c1' changed quotes" in fake_backend.requests[-1].messages[-1].content


async def test_the_auditor_reads_each_quote_next_to_its_unit(quoting_ctx, fake_backend):
    ctx = quoting_ctx()
    draft = await run_writer(ctx, iteration=0, prior=None, findings=[])
    await run_auditor(ctx, iteration=0, draft=draft)
    units = _sent(ctx)["cited_units"]
    assert units == cited_unit_payload(ctx, draft)
    c1 = next(c for c in draft.claims if c.id == "c1")
    unit = next(u for u in units if u["ref"] == c1.evidence[0])
    assert {"claim_id": "c1", "text": c1.quotes[0].text} in unit["quotes"]
    assert '"quotes": the words each claim' in fake_backend.requests[-1].messages[0].content
    off = quoting_ctx(mode="off")
    plain = await run_writer(off, iteration=0, prior=None, findings=[])
    assert all(set(u) == {"ref", "text"} for u in cited_unit_payload(off, plain))


async def test_a_fabricated_quote_fails_tc8_and_src2_by_engine_check(quoting_ctx, fake_backend):
    ctx = quoting_ctx()
    draft = _misquote(await run_writer(ctx, iteration=0, prior=None, findings=[]), "c0")
    ref = draft.claims[0].quotes[0].ref
    fake_backend.script("auditor", lenient_reply(ctx.pack))
    outcome = await run_auditor(ctx, iteration=0, draft=draft)
    by_rule = {f.rule_id: f for f in outcome.findings}
    for rule in ("icd203.tc.8", "icd206.src.2"):  # c0 is the key judgment's claim
        f = by_rule[rule]
        assert f.verdict is Verdict.FAIL and f.route_to == "writer"
        assert f.evidence == f"{ENGINE_CHECK}quote not found in {ref} (c0)"
        assert f.claim_ids == ["c0"] and f.recommendation == QUOTE_FIX
    assert {"icd203.tc.8", "icd206.src.2"} <= {f.rule_id for f in open_findings(outcome.findings)}


async def test_src2_fails_only_for_a_claim_a_key_judgment_cites(quoting_ctx, fake_backend):
    ctx = quoting_ctx()
    draft = _misquote(await run_writer(ctx, iteration=0, prior=None, findings=[]), "c2")
    fake_backend.script("auditor", lenient_reply(ctx.pack))
    by_rule = {f.rule_id: f for f in (await run_auditor(ctx, iteration=0, draft=draft)).findings}
    assert by_rule["icd203.tc.8"].verdict is Verdict.FAIL
    assert by_rule["icd206.src.2"].verdict is Verdict.PASS


async def test_required_mode_fails_an_unquoted_unit_unless_its_source_was_digested(quoting_ctx):
    ctx = quoting_ctx()
    draft = await run_writer(ctx, iteration=0, prior=None, findings=[])
    data = draft.model_dump()
    data["claims"][2].pop("quotes")
    unquoted = type(draft).model_validate(data)
    ref = unquoted.claims[2].evidence[0]
    [tc8] = engine_only_findings(unquoted, ctx.pack, 0, ctx.quote_check())
    assert tc8.evidence == f"{ENGINE_CHECK}no quote from {ref} (c2)" and tc8.claim_ids == ["c2"]
    optional = quoting_ctx(mode="optional")
    assert engine_only_findings(unquoted, ctx.pack, 0, optional.quote_check()) == []
    digest = Digest(source_id="src1", sections=[])
    digested = quoting_ctx(digests={"src1": digest})
    assert engine_only_findings(unquoted, ctx.pack, 0, digested.quote_check()) == []


async def test_unsourced_and_misquoted_claims_share_one_finding(quoting_ctx):
    ctx = quoting_ctx(text_source("src1", *PORT, "UNSOURCED detail on Varna."))
    draft = _misquote(await run_writer(ctx, iteration=0, prior=None, findings=[]), "c1")
    tc8, *_ = engine_only_findings(draft, ctx.pack, 0, ctx.quote_check())
    ref = draft.claims[1].quotes[0].ref
    assert tc8.evidence == (
        f"{ENGINE_CHECK}claims without evidence: c99; quote not found in {ref} (c1)"
    )
    assert tc8.claim_ids == ["c1", "c99"] and tc8.recommendation == BOTH_FIX
    off = engine_only_findings(draft, ctx.pack, 0)  # no quote check: the unsourced claim alone
    assert off[0].evidence == f"{ENGINE_CHECK}claims without evidence: c99"
    assert off[0].recommendation == UNSOURCED_FIX


async def test_an_auditor_fail_keeps_its_own_words(quoting_ctx):
    ctx = quoting_ctx()
    draft = _misquote(await run_writer(ctx, iteration=0, prior=None, findings=[]))
    [seed] = engine_only_findings(draft, ctx.pack, 0, ctx.quote_check())
    own = seed.model_copy(update={"evidence": "c1 overstates the unit.", "claim_ids": []})
    [kept] = apply_engine_checks(draft, [own], ctx.pack, ctx.quote_check())
    ref = draft.claims[0].quotes[0].ref
    # The auditor's words, verdict and recommendation stand; the misquote is added, not hidden.
    assert kept.evidence == f"c1 overstates the unit.; {ENGINE_CHECK}quote not found in {ref} (c1)"
    assert kept.claim_ids == ["c1"] and kept.recommendation == own.recommendation
    blank = own.model_copy(update={"evidence": ""})
    [kept] = apply_engine_checks(draft, [blank], ctx.pack, ctx.quote_check())
    assert kept.evidence == f"{ENGINE_CHECK}quote not found in {ref} (c1)"
    # Unsourced claims alone keep the earlier rule: the auditor's own finding is left as it is.
    plain = engine_only_findings(draft, ctx.pack, 0)
    assert apply_engine_checks(draft, [own], ctx.pack) == [own] and plain == []
