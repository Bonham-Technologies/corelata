"""Digests for sources too long to show a model in full (spec §5.4). The writer role
summarises each source in chunks that fit pipeline.digest_chunk_tokens; sections are
concatenated in document order and traced like any stage output. A source is digested when it
exceeds pipeline.digest_threshold_tokens, or when the writer could not otherwise see every
non-digested source in full (writer_overflow, spec §7.4)."""

from collections.abc import Callable, Collection

from corelata.schema import Digest, DigestOutput, DigestSection, Source
from corelata.stages.context import StageContext, StageError, estimate_tokens


def needs_digest(ctx: StageContext, source: Source) -> bool:
    text = "\n".join(u.text for u in source.units)
    threshold = ctx.cfg.pipeline.digest_threshold_tokens
    return estimate_tokens(text, ctx.bytes_per_token("writer")) > threshold


def source_tokens(source: Source, bytes_per_token: float) -> int:
    """What a source costs the writer in full: its units' estimates summed, exactly as
    select_writer_units counts them."""
    return sum(estimate_tokens(u.text, bytes_per_token) for u in source.units)


def _digestible(source: Source, chunk_tokens: int, bytes_per_token: float) -> bool:
    return all(estimate_tokens(u.text, bytes_per_token) <= chunk_tokens for u in source.units)


def writer_overflow(ctx: StageContext) -> list[str]:
    """Spec §7.4: ids of sources under the digest threshold that must be digested anyway so the
    rest fit pipeline.writer_unit_budget_tokens. The largest goes first (document order breaks
    a tie), until the remaining non-digested sources fit or none remain. A source with a unit no
    digest request can hold is never forced: the writer's safety cut handles it (R-M8-4)."""
    per_token = ctx.bytes_per_token("writer")
    budget = ctx.cfg.pipeline.writer_unit_budget_tokens
    chunk = ctx.cfg.pipeline.digest_chunk_tokens
    full = {s.id: source_tokens(s, per_token) for s in ctx.sources if not needs_digest(ctx, s)}
    candidates = {
        sid: n for sid, n in full.items() if _digestible(ctx.source(sid), chunk, per_token)
    }
    forced: list[str] = []
    while candidates and sum(full.values()) > budget:
        largest = max(candidates, key=candidates.__getitem__)
        forced.append(largest)
        del candidates[largest], full[largest]
    return forced


def chunk_units(source: Source, budget_tokens: int, bytes_per_token: float) -> list[list[int]]:
    """Unit indexes grouped greedily in document order so each group fits the budget. A unit
    that alone exceeds the budget still gets its own group; check_unit_sizes refuses it first."""
    chunks: list[list[int]] = []
    current: list[int] = []
    spent = 0
    for i, unit in enumerate(source.units):
        cost = estimate_tokens(unit.text, bytes_per_token)
        if current and spent + cost > budget_tokens:
            chunks.append(current)
            current, spent = [], 0
        current.append(i)
        spent += cost
    if current:
        chunks.append(current)
    return chunks


def _to_digest(ctx: StageContext, force: Collection[str]) -> list[Source]:
    return [s for s in ctx.sources if s.id in force or needs_digest(ctx, s)]


def check_unit_sizes(ctx: StageContext, force: Collection[str] = ()) -> None:
    """Review Focus 6: a unit no digest request can hold fails the run before any model call."""
    budget = ctx.cfg.pipeline.digest_chunk_tokens
    per_token = ctx.bytes_per_token("writer")
    for source in _to_digest(ctx, force):
        for ref, unit in zip(source.refs(), source.units, strict=True):
            tokens = estimate_tokens(unit.text, per_token)
            if tokens > budget:
                raise StageError(
                    "ingesting",
                    f"unit {ref} ({unit.locator}) in source '{source.name}' (~{tokens} tokens) "
                    f"exceeds pipeline.digest_chunk_tokens ({budget}); split the source",
                )


def _validator(source: Source, expected: list[str]) -> Callable[[DigestOutput], list[str]]:
    def validate(out: DigestOutput) -> list[str]:
        errors: list[str] = []
        seen: list[str] = []
        for s in out.sections:
            for r in s.unit_refs:
                if r not in expected:
                    errors.append(f"unknown ref '{r}' for source {source.id}")
                elif r in seen:
                    errors.append(f"ref '{r}' appears in more than one section")
                seen.append(r)
        missing = [r for r in expected if r not in seen]
        if missing:
            errors.append(f"units not covered: {', '.join(missing[:5])}")
        return errors

    return validate


async def digest_source(ctx: StageContext, source: Source) -> Digest:
    """One source's digest: a writer request per chunk, sections kept in document order."""
    per_token = ctx.bytes_per_token("writer")
    refs = source.refs()
    sections: list[DigestSection] = []
    chunks = chunk_units(source, ctx.cfg.pipeline.digest_chunk_tokens, per_token)
    for n, chunk in enumerate(chunks, start=1):
        expected = [refs[i] for i in chunk]
        out = await ctx.runner.run(
            role="writer",
            model_key=ctx.model_key("writer"),
            prompt_id="digest",
            prompt_vars={},
            payload={
                "task": "digest",
                "source": {"id": source.id, "name": source.name},
                "part": {"index": n, "of": len(chunks)},
                "units": [{"ref": refs[i], "text": source.units[i].text} for i in chunk],
            },
            output_type=DigestOutput,
            validate=_validator(source, expected),
        )
        sections.extend(out.sections)
    return Digest(source_id=source.id, sections=sections)


async def run_digests(ctx: StageContext, *, force: Collection[str] = ()) -> dict[str, Digest]:
    """Digest every source over the threshold and every source named in `force`, in document
    order."""
    check_unit_sizes(ctx, force)
    return {s.id: await digest_source(ctx, s) for s in _to_digest(ctx, force)}
