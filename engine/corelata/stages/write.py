"""The writer (spec §4.4): structured report from template, rules and cited units."""

from collections.abc import Callable
from typing import Any

from corelata.config import EvidenceQuotes
from corelata.schema import Finding, ReportBody
from corelata.stages.context import StageContext, estimate_tokens
from corelata.stages.prior import prior_report_entry
from corelata.stages.report_schema import report_output_type


def report_schema(ctx: StageContext) -> dict[str, Any]:
    """The writer's and conveyor's per-call schema (R-M12-1), with `Claim.quotes` unless
    `pipeline.evidence_quotes` is `off` (CRL-93), and `changes_from_previous` when the run read
    earlier accepted reports (CRL-97)."""
    return report_output_type(
        ctx.index.refs(),
        [s.id for s in ctx.sources],
        quotes=ctx.evidence_quotes is not EvidenceQuotes.OFF,
        prior_run_ids=[r.run_id for r in ctx.prior_reports],
    ).model_json_schema()


def without_unasked(ctx: StageContext, body: ReportBody) -> ReportBody:
    """A reply's stray elements the run did not ask for are dropped, as the parser ignored the
    unknown keys before they existed: quotes with `evidence_quotes: off` (CRL-93), and
    `changes_from_previous` when the run read no earlier report (CRL-97). Otherwise `body`
    unchanged."""
    update: dict[str, Any] = {}
    if ctx.evidence_quotes is EvidenceQuotes.OFF and any(c.quotes for c in body.claims):
        update["claims"] = [c.model_copy(update={"quotes": []}) for c in body.claims]
    if not ctx.prior_reports and body.changes_from_previous:
        update["changes_from_previous"] = []
    return body.model_copy(update=update) if update else body


def change_errors(ctx: StageContext, body: ReportBody) -> list[str]:
    """CRL-97: each entry of `changes_from_previous` names an earlier report the run read."""
    if not ctx.prior_reports:
        return []
    known = [r.run_id for r in ctx.prior_reports]
    return [
        f"changes_from_previous: '{ch.prior_run_id}' is not the run_id of an earlier report; "
        f"use one of {', '.join(known)}"
        for ch in body.changes_from_previous
        if ch.prior_run_id not in known
    ]


def quote_errors(ctx: StageContext, body: ReportBody) -> list[str]:
    """CRL-93: a quote names a unit of the run that its claim cites. Whether the words are in
    the unit is the engine's check at audit (icd203.tc.8), not a repair."""
    if ctx.evidence_quotes is EvidenceQuotes.OFF:
        return []
    errors = ctx.check_refs([q.ref for c in body.claims for q in c.quotes])
    for c in body.claims:
        for q in c.quotes:
            if ctx.index.has(q.ref) and q.ref not in c.evidence:
                errors.append(
                    f"claim '{c.id}' quotes '{q.ref}', which is not in its evidence; quote only "
                    "units the claim cites, or add the unit to its evidence"
                )
    return errors


def report_validator(ctx: StageContext) -> Callable[[ReportBody], list[str]]:
    allowed_markings = set(ctx.pack.lexicon.handling_markings)
    limits = ctx.pack.template.key_judgments
    source_ids = [s.id for s in ctx.sources]
    known_sources = set(source_ids)
    lexicon_terms = ctx.pack.lexicon.terms()

    def validate(body: ReportBody) -> list[str]:
        errors = ctx.check_refs([r for c in body.claims for r in c.evidence])
        errors += quote_errors(ctx, body)
        errors += change_errors(ctx, body)
        if body.handling_marking not in allowed_markings:
            errors.append(
                f"handling marking '{body.handling_marking}' is not allowed "
                f"(allowed: {', '.join(sorted(allowed_markings))})"
            )
        for c in body.claims:
            if c.likelihood_term is not None and c.likelihood_term not in lexicon_terms:
                errors.append(
                    f"likelihood term '{c.likelihood_term}' is not in the lexicon "
                    f"(allowed: {', '.join(sorted(lexicon_terms))})"
                )
        listed = {s.source_id for s in body.sources}
        counted: set[str] = set()
        for entry in body.sources:
            if entry.source_id not in known_sources:
                errors.append(f"unknown source id '{entry.source_id}' in sources")
            elif entry.source_id in counted:
                errors.append(f"duplicate source entry '{entry.source_id}'")
            counted.add(entry.source_id)
        errors += [
            f"source '{sid}' has no entry in sources" for sid in source_ids if sid not in listed
        ]
        n = len(body.key_judgments)
        if not limits.min <= n <= limits.max:
            errors.append(f"key judgments: {n} (allowed {limits.min}-{limits.max})")
        return errors

    return validate


def select_writer_units(ctx: StageContext) -> list[str]:
    """Spec §7.4 (amended in M2): the gate's evidence first (each ref once), then every other
    unit of every non-digested source in document order. Ingest digests sources until the rest
    fit pipeline.writer_unit_budget_tokens, so normally nothing is cut; the budget stays as a
    safety cut, and the refs it leaves out are recorded on ctx.withheld_refs. Digested sources
    are represented by their digests, never by their units."""
    chosen = list(dict.fromkeys(r for r in ctx.gate_evidence if ctx.index.has(r)))
    seen = set(chosen)
    bpt = ctx.bytes_per_token("writer")
    spent = sum(estimate_tokens(ctx.index.text(r), bpt) for r in chosen)
    budget = ctx.cfg.pipeline.writer_unit_budget_tokens
    withheld: list[str] = []
    for source in ctx.sources:
        if source.id in ctx.digests:
            continue
        for ref in source.refs():
            if ref in seen:
                continue
            cost = estimate_tokens(ctx.index.text(ref), bpt)
            if withheld or spent + cost > budget:  # once cut, the rest of the order is cut too
                withheld.append(ref)
                continue
            chosen.append(ref)
            seen.add(ref)
            spent += cost
    ctx.withheld_refs = withheld
    return chosen


async def run_writer(
    ctx: StageContext, *, iteration: int, prior: ReportBody | None, findings: list[Finding]
) -> ReportBody:
    check = report_validator(ctx)
    parsed = await ctx.runner.run(
        role="writer",
        model_key=ctx.model_key("writer"),
        prompt_id="writer",
        prompt_vars={
            "tone": ctx.pack.tone,
            "section_order": ctx.pack.template.section_order,
            "iteration": iteration,
            "extra_guidance": ctx.extra_guidance,
            "evidence_quotes": ctx.evidence_quotes.value,
            "prior_reports": bool(ctx.prior_reports),
        },
        payload={
            "task": "writer",
            "value_statement": ctx.value_statement,
            "template": ctx.pack.template.model_dump(),
            "rules": [r.model_dump() for r in ctx.pack.rules_for("writer")],
            "lexicon": ctx.pack.lexicon.model_dump(),
            "digests": ctx.digest_payload(),
            "units": ctx.unit_payload(select_writer_units(ctx)),
            "gate_evidence": list(ctx.gate_evidence),
            "sources": ctx.source_payload(),
            **prior_reports_payload(ctx),
            "prior_draft": None if prior is None else prior.model_dump(),
            "findings": [f.model_dump() for f in findings],
            "extra_guidance": ctx.extra_guidance,
            "iteration": iteration,
            **_quotes_mode(ctx),
        },
        output_type=ReportBody,
        schema=report_schema(ctx),
        validate=check,
    )
    return without_unasked(ctx, parsed)


def prior_reports_payload(ctx: StageContext) -> dict[str, Any]:
    """The payload's `prior_reports` key (CRL-97), absent when the run read no earlier report so
    that payload is unchanged. The auditor's payload carries the same key."""
    if not ctx.prior_reports:
        return {}
    return {"prior_reports": [prior_report_entry(r) for r in ctx.prior_reports]}


def _quotes_mode(ctx: StageContext) -> dict[str, str]:
    """The payload's `evidence_quotes` key, absent with `off` so that payload is unchanged."""
    if ctx.evidence_quotes is EvidenceQuotes.OFF:
        return {}
    return {"evidence_quotes": ctx.evidence_quotes.value}
