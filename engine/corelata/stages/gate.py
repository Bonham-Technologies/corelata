"""The value gate (spec §7.1, §7.2): verify the analyst's statement, or propose statements."""

from corelata.schema import DiscoveryResult, GateVerdict
from corelata.stages.context import StageContext, estimate_tokens
from corelata.text import key_terms


def select_units(ctx: StageContext, budget_tokens: int) -> list[str]:
    """Refs of units from non-digested sources (or digested only for the writer's budget),
    ranked by overlap with the statement's key terms (then document order), cut when the
    budget is spent."""
    terms = key_terms(ctx.value_statement)
    ranked: list[tuple[int, int, str]] = []
    position = 0
    for source in ctx.sources:
        if source.id in ctx.digests and source.id not in ctx.forced_digests:
            continue
        for ref, unit in zip(source.refs(), source.units, strict=True):
            folded = unit.text.casefold()
            overlap = sum(1 for t in terms if t in folded)
            ranked.append((-overlap, position, ref))
            position += 1
    ranked.sort()
    chosen: list[str] = []
    spent = 0
    bpt = ctx.bytes_per_token("gate")
    for _, _, ref in ranked:
        cost = estimate_tokens(ctx.index.text(ref), bpt)
        if chosen and spent + cost > budget_tokens:
            break
        chosen.append(ref)
        spent += cost
    return chosen


async def run_gate(ctx: StageContext) -> GateVerdict:
    refs = select_units(ctx, ctx.cfg.pipeline.gate_unit_budget_tokens)
    return await ctx.runner.run(
        role="gate",
        model_key=ctx.model_key("gate"),
        prompt_id="gate",
        prompt_vars={"mode": "verify", "tone": ctx.pack.tone},
        payload={
            "task": "gate",
            "value_statement": ctx.value_statement,
            "digests": ctx.digest_payload(),
            "units": ctx.unit_payload(refs),
        },
        output_type=GateVerdict,
        validate=lambda v: ctx.check_refs(v.evidence),
    )


async def run_discovery(ctx: StageContext, audience_hint: str = "") -> DiscoveryResult:
    refs = select_units(ctx, ctx.cfg.pipeline.gate_unit_budget_tokens)
    return await ctx.runner.run(
        role="gate",
        model_key=ctx.model_key("gate"),
        prompt_id="discover",
        prompt_vars={"audience_hint": audience_hint, "tone": ctx.pack.tone},
        payload={
            "task": "discover",
            "audience_hint": audience_hint,
            "digests": ctx.digest_payload(),
            "units": ctx.unit_payload(refs),
        },
        output_type=DiscoveryResult,
        validate=lambda r: ctx.check_refs([e for c in r.candidates for e in c.evidence]),
    )
