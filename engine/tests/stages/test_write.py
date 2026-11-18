import json

import pytest

from corelata.llm.agent import StructuredOutputError
from corelata.schema import Finding, FindingOut, ReportBody, Verdict
from corelata.stages import audit_schema
from corelata.stages.write import run_writer, select_writer_units
from corelata.testing.sources import text_source
from corelata.testing.synthetic import synthetic_response
from tests.stages.conftest import PORT


def _writer_payload(ctx):
    return {
        "task": "writer",
        "value_statement": ctx.value_statement,
        "template": {},
        "rules": [],
        "lexicon": ctx.pack.lexicon.model_dump(),
        "digests": [],
        "units": ctx.unit_payload(ctx.index.refs()),
        "sources": ctx.source_payload(),
        "prior_draft": None,
        "findings": [],
        "extra_guidance": "",
        "iteration": 0,
    }


async def test_writer_first_draft(make_ctx):
    ctx = make_ctx()
    ctx.gate_evidence = ["src1/u1", "src1/u3"]
    body = await run_writer(ctx, iteration=0, prior=None, findings=[])
    assert body.title.startswith("Synthetic assessment")
    facts = {c.evidence[0] for c in body.claims if c.kind.value == "fact"}
    assert facts == {"src1/u1", "src1/u3"}
    assert [s.source_id for s in body.sources] == ["src1"]
    rec = ctx.runner.log.records[0]
    assert rec.role == "writer" and rec.prompt_id == "writer"
    payload = json.loads(rec.request["messages"][1]["content"].split("\n", 1)[1])
    assert payload["iteration"] == 0 and payload["prior_draft"] is None
    assert [r["id"] for r in payload["rules"]] == [r.id for r in ctx.pack.rules_for("writer")]
    assert payload["gate_evidence"] == ["src1/u1", "src1/u3"]


async def test_writer_revision_receives_prior_and_findings(make_ctx):
    ctx = make_ctx(text_source("src1", *PORT, "UNSOURCED detail."))
    first = await run_writer(ctx, iteration=0, prior=None, findings=[])
    assert first.unsourced_claims()
    finding = Finding(
        **FindingOut(rule_id="icd203.tc.8", verdict=Verdict.FAIL, evidence="c99").model_dump(),
        severity="blocking",
        route_to="writer",
        iteration=0,
    )
    second = await run_writer(ctx, iteration=1, prior=first, findings=[finding])
    assert second.unsourced_claims() == []
    rec = ctx.runner.log.records[1]
    payload = json.loads(rec.request["messages"][1]["content"].split("\n", 1)[1])
    assert payload["prior_draft"]["title"] == first.title
    assert payload["findings"][0]["rule_id"] == "icd203.tc.8"
    assert "prior_draft" in rec.request["messages"][0]["content"]


async def test_the_writer_sends_the_enum_but_parses_the_canonical_body(make_ctx, fake_backend):
    ctx = make_ctx()
    good = json.loads(json.dumps(synthetic_response(_writer_payload(ctx))))
    good["claims"][0]["evidence"] = ["src1"]  # the CRL-1 failure: a source id where a unit goes
    bad = json.dumps(good)
    fake_backend.script("writer", bad, bad)
    with pytest.raises(StructuredOutputError, match="'src1' is not a unit id"):
        await run_writer(ctx, iteration=0, prior=None, findings=[])
    assert fake_backend.requests[0].json_schema["$defs"]["UnitRef"]["enum"] == ctx.index.refs()
    assert "'src1' is not a unit id" in fake_backend.requests[1].messages[3].content
    assert [r.ok for r in ctx.runner.log.records] == [False, False]


async def test_a_bad_ref_and_another_error_share_one_repair_message(make_ctx, fake_backend):
    ctx = make_ctx()
    good = json.loads(json.dumps(synthetic_response(_writer_payload(ctx))))
    bad = json.loads(json.dumps(good))
    bad["claims"][0]["evidence"] = ["src1"]
    bad["claims"][-1]["likelihood_term"] = "sort of likely"
    fake_backend.script("writer", json.dumps(bad), json.dumps(good))
    body = await run_writer(ctx, iteration=0, prior=None, findings=[])
    repair = fake_backend.requests[1].messages[3].content
    assert "'src1' is not a unit id; cite unit ids exactly as given in the input, such as" in repair
    assert "likelihood term 'sort of likely' is not in the lexicon" in repair
    assert len(fake_backend.requests) == 2 and type(body) is ReportBody


async def test_the_backstop_validator_still_checks_writer_refs(make_ctx, fake_backend, monkeypatch):
    monkeypatch.setattr(audit_schema, "ENUM_LIMIT", 0)  # every ref list is "too long": strings
    ctx = make_ctx()
    good = json.loads(json.dumps(synthetic_response(_writer_payload(ctx))))
    good["claims"][0]["evidence"] = ["src9/u1"]
    bad = json.dumps(good)
    fake_backend.script("writer", bad, bad)
    with pytest.raises(StructuredOutputError, match="'src9/u1' is not a unit id"):
        await run_writer(ctx, iteration=0, prior=None, findings=[])
    assert [r.ok for r in ctx.runner.log.records] == [False, False]
    assert "SourceId" not in fake_backend.requests[0].json_schema["$defs"]  # a plain string too


async def test_a_json_object_writer_sees_the_source_enum_and_gets_the_validator_message(
    make_ctx, make_config, fake_backend
):
    models = {
        key: {"backend": "fake", "context_window": 32768, "structured_output": "json_object"}
        for key in ("model-a", "model-b")
    }
    cfg = make_config(models=models)
    ctx = make_ctx(text_source("src1", *PORT), text_source("src2", "Rail link."), cfg=cfg)
    good = json.loads(json.dumps(synthetic_response(_writer_payload(ctx))))
    bad = json.loads(json.dumps(good))
    bad["sources"][1]["source_id"] = "src9"  # an invented source id where src2 belongs
    fake_backend.script("writer", json.dumps(bad), json.dumps(good))
    body = await run_writer(ctx, iteration=0, prior=None, findings=[])
    first, second = fake_backend.requests
    assert first.json_schema["$defs"]["SourceId"]["enum"] == ["src1", "src2"]
    assert '"SourceId": {"enum": ["src1", "src2"]' in first.messages[0].content  # in the prompt
    repair = second.messages[3].content
    assert "unknown source id 'src9' in sources" in repair  # the validator's message, unchanged
    assert "source 'src2' has no entry in sources" in repair
    assert [s.source_id for s in body.sources] == ["src1", "src2"] and type(body) is ReportBody


async def test_writer_validator_checks_marking_sources_and_limits(make_ctx, fake_backend):
    ctx = make_ctx(text_source("src1", *PORT), text_source("src2", "Rail link."))
    base = synthetic_response(_writer_payload(ctx))
    wrong = dict(base)
    wrong["handling_marking"] = "SECRET"
    wrong["sources"] = base["sources"][:1]
    wrong["key_judgments"] = base["key_judgments"] * 6
    fake_backend.script("writer", json.dumps(wrong))
    body = await run_writer(ctx, iteration=0, prior=None, findings=[])
    repair = fake_backend.requests[1].messages[3].content
    assert "handling marking 'SECRET'" in repair
    assert "source 'src2' has no entry" in repair
    assert "key judgments: 6 (allowed 1-5)" in repair
    assert body.handling_marking == "UNCLASSIFIED"


async def _repair_text(make_ctx, fake_backend, mutate):
    ctx = make_ctx()
    good = json.loads(json.dumps(synthetic_response(_writer_payload(ctx))))
    mutate(good)
    fake_backend.script("writer", json.dumps(good))
    await run_writer(ctx, iteration=0, prior=None, findings=[])
    return fake_backend.requests[1].messages[3].content


async def test_writer_validator_rejects_bad_likelihood_term(make_ctx, fake_backend):
    def mutate(d):
        d["claims"][-1]["likelihood_term"] = "sort of likely"

    repair = await _repair_text(make_ctx, fake_backend, mutate)
    assert "likelihood term 'sort of likely' is not in the lexicon (allowed: almost" in repair


async def test_writer_validator_rejects_unknown_and_duplicate_source_ids(make_ctx, fake_backend):
    def mutate(d):
        d["sources"] = [*d["sources"], d["sources"][0], {**d["sources"][0], "source_id": "src9"}]

    repair = await _repair_text(make_ctx, fake_backend, mutate)
    assert "unknown source id 'src9' in sources" in repair
    assert "duplicate source entry 'src1'" in repair


def test_select_writer_units_cited_first_then_rest_within_budget(make_ctx, make_config):
    ctx = make_ctx(text_source("src1", *PORT), text_source("src2", "Rail link.", "Grain silo."))
    ctx.gate_evidence = ["src1/u3", "src2/u1", "src9/u1"]
    assert select_writer_units(ctx) == ["src1/u3", "src2/u1", "src1/u1", "src1/u2", "src2/u2"]
    tight = make_config(pipeline={"writer_unit_budget_tokens": 500})
    ctx = make_ctx(
        text_source("src1", *PORT), text_source("src2", "Rail link.", "Grain silo."), cfg=tight
    )
    ctx.gate_evidence = ["src1/u3", "src2/u1"]
    # 500 tokens at 2.5 bytes/token is 1250 bytes: enough for every unit here, so the budget
    # does not bite; shrink the model's bytes_per_token to make it bite deterministically
    ctx.cfg = ctx.cfg.model_copy(
        update={
            "models": {
                k: m.model_copy(update={"bytes_per_token": 0.01}) for k, m in ctx.cfg.models.items()
            }
        }
    )
    ctx.runner.cfg = ctx.cfg
    # every unit now costs thousands of tokens: cited refs are always included, nothing else fits
    assert select_writer_units(ctx) == ["src1/u3", "src2/u1"]


async def test_writer_sees_uncited_units_of_non_digested_sources(make_ctx):
    ctx = make_ctx(text_source("src1", *PORT), text_source("src2", "Rail link."))
    ctx.gate_evidence = ["src1/u1"]
    await run_writer(ctx, iteration=0, prior=None, findings=[])
    rec = ctx.runner.log.records[0]
    payload = json.loads(rec.request["messages"][1]["content"].split("\n", 1)[1])
    assert [u["ref"] for u in payload["units"]] == ["src1/u1", "src1/u2", "src1/u3", "src2/u1"]


async def test_writer_never_sees_units_of_digested_sources(make_ctx, make_config):
    from corelata.stages.digest import run_digests

    cfg = make_config(pipeline={"digest_threshold_tokens": 500})
    long = text_source("src2", *[f"Paragraph {i} about Varna port finance." for i in range(40)])
    ctx = make_ctx(text_source("src1", *PORT), long, cfg=cfg)
    ctx.digests = await run_digests(ctx)
    ctx.gate_evidence = ["src1/u2", "src2/u5"]
    assert select_writer_units(ctx) == ["src1/u2", "src2/u5", "src1/u1", "src1/u3"]


def _with_bytes_per_token(ctx, bpt: float) -> None:
    ctx.cfg = ctx.cfg.model_copy(
        update={
            "models": {
                k: m.model_copy(update={"bytes_per_token": bpt}) for k, m in ctx.cfg.models.items()
            }
        }
    )
    ctx.runner.cfg = ctx.cfg


def test_select_writer_units_lists_a_repeated_gate_ref_once(make_ctx):
    ctx = make_ctx(text_source("src1", *PORT), text_source("src2", "Rail link.", "Grain silo."))
    ctx.gate_evidence = ["src1/u3", "src1/u3", "src2/u1", "src1/u3"]
    assert select_writer_units(ctx) == ["src1/u3", "src2/u1", "src1/u1", "src1/u2", "src2/u2"]
    assert ctx.withheld_refs == []


def test_select_writer_units_records_what_the_safety_cut_withholds(make_ctx, make_config):
    tight = make_config(pipeline={"writer_unit_budget_tokens": 500})
    ctx = make_ctx(
        text_source("src1", *PORT), text_source("src2", "Rail link.", "Grain silo."), cfg=tight
    )
    ctx.gate_evidence = ["src1/u3", "src2/u1"]
    # at 0.3 bytes/token: src1/u3 160 + src2/u1 34 = 194 cited; src1/u1 (197) fits (391);
    # src1/u2 (160) does not, and once cut nothing after it is added, not even src2/u2 (37)
    _with_bytes_per_token(ctx, 0.3)
    assert select_writer_units(ctx) == ["src1/u3", "src2/u1", "src1/u1"]
    assert ctx.withheld_refs == ["src1/u2", "src2/u2"]
    _with_bytes_per_token(ctx, 0.01)
    assert select_writer_units(ctx) == ["src1/u3", "src2/u1"]
    assert ctx.withheld_refs == ["src1/u1", "src1/u2", "src2/u2"]


async def test_run_writer_enumerates_every_indexed_unit_including_digested_sources(
    make_ctx, make_config, fake_backend
):
    from corelata.stages.digest import run_digests

    cfg = make_config(pipeline={"digest_threshold_tokens": 500})
    long = text_source("src2", *[f"Paragraph {i} about Varna port finance." for i in range(40)])
    ctx = make_ctx(text_source("src1", *PORT), long, cfg=cfg)
    ctx.digests = await run_digests(ctx)
    assert "src2" in ctx.digests  # the writer sees src2 only through its digest
    body = await run_writer(ctx, iteration=0, prior=None, findings=[])
    request = fake_backend.requests[-1]
    assert request.schema_name == "ReportBody"
    enum = request.json_schema["$defs"]["UnitRef"]["enum"]
    assert enum == ctx.index.refs() and "src2/u40" in enum  # what check_refs accepts
    assert type(body) is ReportBody
