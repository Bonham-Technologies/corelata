import json

import pytest

from corelata.llm.agent import StructuredOutputError
from corelata.schema import Digest, DigestSection, Substance
from corelata.stages.gate import run_discovery, run_gate, select_units
from corelata.testing.sources import text_source


def test_select_units_ranks_by_overlap_then_order(make_ctx):
    ctx = make_ctx(
        text_source("src1", "Nothing relevant here.", "Varna port capacity doubled.", "Weather."),
        text_source("src2", "Shippers welcomed the capacity at Varna."),
    )
    assert select_units(ctx, budget_tokens=10_000) == ["src1/u2", "src2/u1", "src1/u1", "src1/u3"]
    assert select_units(ctx, budget_tokens=12) == ["src1/u2"]


def test_select_units_skips_digested_sources(make_ctx):
    ctx = make_ctx(text_source("src1", "Varna port."), text_source("src2", "Varna capacity."))
    section = DigestSection(summary="s", unit_refs=["src2/u1"])
    ctx.digests = {"src2": Digest(source_id="src2", sections=[section])}
    assert select_units(ctx, 10_000) == ["src1/u1"]


async def test_run_gate_supported(make_ctx):
    ctx = make_ctx()
    verdict = await run_gate(ctx)
    assert verdict.supported and verdict.substance is Substance.SUFFICIENT
    assert verdict.evidence and all(ctx.index.has(r) for r in verdict.evidence)
    rec = ctx.runner.log.records[0]
    assert rec.role == "gate" and rec.prompt_id == "gate"
    assert "supported" in rec.request["messages"][0]["content"]


async def test_run_gate_rejects_unrelated_statement(make_ctx):
    verdict = await run_gate(make_ctx(statement="Lunar helium mining"))
    assert not verdict.supported and verdict.substance is Substance.INSUFFICIENT


async def test_run_gate_validator_rejects_unknown_evidence(make_ctx, fake_backend):
    bad = json.dumps(
        {
            "supported": True,
            "substance": "sufficient",
            "reasons": ["r"],
            "evidence": ["src7/u1"],
            "suggested_scope": "",
        }
    )
    fake_backend.script("gate", bad, bad)
    with pytest.raises(StructuredOutputError, match="'src7/u1' is not a unit id"):
        await run_gate(make_ctx())


async def test_run_discovery(make_ctx):
    ctx = make_ctx(
        text_source("src1", "Varna port grew."), text_source("src2", "Rail link opened.")
    )
    result = await run_discovery(ctx, audience_hint="logistics planners")
    assert len(result.candidates) == 2
    assert result.candidates[0].audience == "logistics planners"
    assert ctx.runner.log.records[0].prompt_id == "discover"


def test_select_units_keeps_sources_digested_only_for_the_writer(make_ctx):
    ctx = make_ctx(text_source("src1", "Varna port."), text_source("src2", "Varna capacity."))
    section = DigestSection(summary="s", unit_refs=["src2/u1"])
    ctx.digests = {"src2": Digest(source_id="src2", sections=[section])}
    ctx.forced_digests = {"src2"}  # under the threshold; digested for the writer's budget only
    assert select_units(ctx, 10_000) == ["src1/u1", "src2/u1"]
