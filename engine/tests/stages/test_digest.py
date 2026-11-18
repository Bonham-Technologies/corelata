import json

import pytest

from corelata.llm.agent import StructuredOutputError
from corelata.stages.context import StageError
from corelata.stages.digest import (
    check_unit_sizes,
    chunk_units,
    needs_digest,
    run_digests,
    source_tokens,
    writer_overflow,
)
from corelata.testing.sources import text_source
from tests.stages.conftest import PORT


def big_source(n=40):
    return text_source(
        "src1", *[f"Paragraph {i} about Varna port traffic and finance." for i in range(n)]
    )


async def test_small_sources_need_no_digest(make_ctx):
    ctx = make_ctx()
    assert not needs_digest(ctx, ctx.sources[0])
    assert await run_digests(ctx) == {}


async def test_oversized_source_is_digested(make_ctx, make_config):
    cfg = make_config(pipeline={"digest_threshold_tokens": 500})
    ctx = make_ctx(big_source(), cfg=cfg)
    assert needs_digest(ctx, ctx.sources[0])
    digests = await run_digests(ctx)
    d = digests["src1"]
    assert d.source_id == "src1" and len(d.sections) == 8
    covered = [r for s in d.sections for r in s.unit_refs]
    assert covered == ctx.sources[0].refs()
    assert ctx.runner.log.records[0].role == "writer"


async def test_digest_validator_rejects_gaps_and_foreign_refs(make_ctx, make_config, fake_backend):
    cfg = make_config(pipeline={"digest_threshold_tokens": 500})
    ctx = make_ctx(big_source(), cfg=cfg)
    bad = json.dumps({"sections": [{"summary": "s", "unit_refs": ["src1/u1", "src9/u1"]}]})
    fake_backend.script("digest", bad, bad)
    with pytest.raises(StructuredOutputError, match="not covered|unknown"):
        await run_digests(ctx)


def test_chunk_units_packs_greedily_in_document_order():
    src = text_source("src1", "a" * 10, "b" * 10, "c" * 10, "d" * 25, "e" * 10)
    # bytes_per_token 1.0 → tokens == characters
    assert chunk_units(src, 25, 1.0) == [[0, 1], [2], [3], [4]]
    assert chunk_units(src, 1000, 1.0) == [[0, 1, 2, 3, 4]]
    assert chunk_units(text_source("src1", "x"), 1, 1.0) == [[0]]


async def test_oversized_source_is_digested_in_several_calls(make_ctx, make_config, fake_backend):
    cfg = make_config(pipeline={"digest_threshold_tokens": 500, "digest_chunk_tokens": 500})
    ctx = make_ctx(big_source(), cfg=cfg)
    digests = await run_digests(ctx)
    digest_calls = [r for r in fake_backend.requests if '"task": "digest"' in r.messages[1].content]
    assert len(digest_calls) == 2
    d = digests["src1"]
    covered = [r for s in d.sections for r in s.unit_refs]
    assert covered == ctx.sources[0].refs()
    assert all(rec.role == "writer" for rec in ctx.runner.log.records)


async def test_unit_larger_than_chunk_budget_fails_fast(make_ctx, make_config, fake_backend):
    cfg = make_config(pipeline={"digest_threshold_tokens": 500, "digest_chunk_tokens": 500})
    huge = text_source("src1", *[f"Paragraph {i} on Varna." for i in range(30)], "Z" * 5000)
    ctx = make_ctx(huge, cfg=cfg)
    with pytest.raises(
        StageError, match=r"ingesting: unit src1/u31 \(para 31\) in source 'src1.txt'"
    ) as e:
        check_unit_sizes(ctx)
    assert "exceeds pipeline.digest_chunk_tokens (500)" in str(e.value)
    with pytest.raises(StageError):
        await run_digests(ctx)
    assert fake_backend.requests == []
    small = make_ctx(text_source("src1", "Z" * 5000), cfg=make_config())  # below the threshold
    check_unit_sizes(small)  # not digested, so not checked here


def test_writer_overflow_takes_the_largest_first_and_may_take_every_source(make_ctx, make_config):
    cfg = make_config(pipeline={"digest_threshold_tokens": 2000, "writer_unit_budget_tokens": 500})
    a = text_source("src1", *["a" * 500] * 2)  # 400 tokens at 2.5 bytes/token
    b = text_source("src2", *["b" * 500] * 3)  # 600
    c = text_source("src3", *["c" * 500] * 2)  # 400, ties src1: document order breaks the tie
    ctx = make_ctx(a, b, c, cfg=cfg)
    assert source_tokens(b, ctx.bytes_per_token("writer")) == 600
    assert writer_overflow(ctx) == ["src2", "src1"]
    alone = make_ctx(b, cfg=cfg)  # one source over the budget but under the threshold
    assert writer_overflow(alone) == ["src2"]
    assert writer_overflow(make_ctx()) == []  # the default budget holds the port note


async def test_forced_sources_are_digested_and_size_checked(make_ctx, make_config, fake_backend):
    cfg = make_config(pipeline={"digest_threshold_tokens": 6000, "digest_chunk_tokens": 500})
    ctx = make_ctx(text_source("src1", *PORT), text_source("src2", "Z" * 5000), cfg=cfg)
    check_unit_sizes(ctx)  # src2 is under the threshold, so not checked unless forced
    with pytest.raises(StageError, match=r"unit src2/u1 .* exceeds pipeline.digest_chunk_tokens"):
        await run_digests(ctx, force=["src2"])
    assert fake_backend.requests == []
    digests = await run_digests(ctx, force=["src1"])
    assert list(digests) == ["src1"]
    assert [r for s in digests["src1"].sections for r in s.unit_refs] == ctx.sources[0].refs()


def test_writer_overflow_skips_undigestible_sources(make_ctx, make_config):
    cfg = make_config(
        pipeline={
            "digest_threshold_tokens": 2000,
            "digest_chunk_tokens": 500,
            "writer_unit_budget_tokens": 500,
        }
    )
    a = text_source("src1", *["a" * 500] * 2)  # 400 tokens, two units of 200
    b = text_source("src2", "b" * 1500)  # 600 tokens in ONE unit: no chunk can hold it
    c = text_source("src3", *["c" * 500] * 2)  # 400
    ctx = make_ctx(a, b, c, cfg=cfg)
    forced = writer_overflow(ctx)
    assert "src2" not in forced  # the largest, but undigestible: the writer's cut covers it
    assert forced == ["src1", "src3"]  # ties: document order
    check_unit_sizes(ctx, forced)  # and what is forced can be digested
