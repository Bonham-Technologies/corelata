"""The conveyance reviewer (spec §4.4): edits for the reader, may not touch evidence."""

from collections.abc import Callable

from corelata.config import EvidenceQuotes
from corelata.schema import Finding, ReportBody
from corelata.stages.context import StageContext
from corelata.stages.write import report_schema, report_validator, without_unasked


def conveyor_validator(ctx: StageContext, draft: ReportBody) -> Callable[[ReportBody], list[str]]:
    base = report_validator(ctx)
    before = {c.id: c for c in draft.claims}
    quoting = ctx.evidence_quotes is not EvidenceQuotes.OFF

    def validate(body: ReportBody) -> list[str]:
        errors = base(body)
        after = {c.id: c for c in body.claims}
        if set(after) != set(before):
            errors.append(
                "claim set changed: the reviewer may reword claims, not add or remove them"
            )
        for cid, c in after.items():
            prev = before.get(cid)
            if prev is None:
                continue
            if set(prev.evidence) != set(c.evidence):
                errors.append(f"claim '{cid}' changed evidence")
            if prev.likelihood_term != c.likelihood_term:
                errors.append(f"claim '{cid}' changed likelihood term")
            if prev.kind is not c.kind:
                errors.append(f"claim '{cid}' changed kind")
            if quoting and prev.quotes != c.quotes:
                errors.append(f"claim '{cid}' changed quotes: keep every quote exactly as given")
        if ctx.prior_reports and _change_keys(body) != _change_keys(draft):
            errors.append(
                "changes_from_previous changed: the reviewer may reword an entry's explanation, "
                "not add, remove or reorder entries or change their prior_run_id, "
                "prior_judgment or change"
            )
        return errors

    return validate


def _change_keys(body: ReportBody) -> list[tuple[str, str, str]]:
    """What the conveyor may not change in `changes_from_previous` (CRL-97)."""
    return [
        (ch.prior_run_id, ch.prior_judgment, ch.change.value) for ch in body.changes_from_previous
    ]


async def run_conveyor(
    ctx: StageContext, *, iteration: int, draft: ReportBody, findings: list[Finding]
) -> ReportBody:
    check = conveyor_validator(ctx, draft)
    parsed = await ctx.runner.run(
        role="conveyor",
        model_key=ctx.model_key("conveyor"),
        prompt_id="conveyor",
        prompt_vars={
            "tone": ctx.pack.tone,
            "heading_style": ctx.pack.format.heading_style,
            "findings": [f.model_dump() for f in findings],
            "evidence_quotes": ctx.evidence_quotes.value,
        },
        payload={
            "task": "conveyor",
            "draft": draft.model_dump(),
            "template": ctx.pack.template.model_dump(),
            "rules": [r.model_dump() for r in ctx.pack.rules_for("conveyor")],
            "tone": ctx.pack.tone,
            "findings": [f.model_dump() for f in findings],
            "iteration": iteration,
        },
        output_type=ReportBody,
        schema=report_schema(ctx),
        validate=check,
    )
    return without_unasked(ctx, parsed)
