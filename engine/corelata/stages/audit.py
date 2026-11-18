"""The compliance auditor (spec §8.2) and the engine-owned loop decision (spec §6.2, §7.3).
The auditor returns findings only; severity and routing come from the rule, never the model."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from corelata.config import EvidenceQuotes
from corelata.quotes import QuoteCheck, quote_problems
from corelata.schema import AuditOutput, Finding, ReportBody, Verdict
from corelata.stages.audit_schema import audit_output_type, to_audit_output
from corelata.stages.context import StageContext
from corelata.stages.write import prior_reports_payload
from corelata.standards.schema import Checkability, ResolvedPack, Severity

# How an engine-owned finding's evidence starts (R-M11-6); the bench reads it to recognise an
# iteration whose only findings are the engine's, a degraded audit (R-M12-5).
ENGINE_CHECK = "engine check: "

LOOPING = {Severity.BLOCKING.value, Severity.MAJOR.value}
Next = Literal["drafting", "conveying", "rendering"]


def audit_validator(ctx: StageContext) -> Callable[[AuditOutput], list[str]]:
    """The backstop for servers that do not enforce the schema (R-M11-1); every message tells the
    model what to write (R-M11-3)."""
    rules = {r.id: r for r in ctx.pack.rules}
    known = ", ".join(rules)

    def validate(out: AuditOutput) -> list[str]:
        errors: list[str] = []
        seen: set[str] = set()
        for f in out.findings:
            rule = rules.get(f.rule_id)
            if rule is None:
                errors.append(
                    f"'{f.rule_id}' is not a rule in this pack; the rule ids are: {known}"
                )
                continue
            if f.rule_id in seen:
                errors.append(f"give exactly one finding for rule '{f.rule_id}'")
            seen.add(f.rule_id)
            if rule.checkability is Checkability.VERIFIABLE and f.verdict is Verdict.ATTESTED:
                errors.append(
                    f"rule '{f.rule_id}' is verifiable: set its verdict to 'pass', 'fail' or "
                    "'not_applicable', not 'attested'"
                )
            advisory = rule.checkability is Checkability.ADVISORY
            if advisory and f.verdict in (Verdict.PASS, Verdict.FAIL):
                errors.append(
                    f"rule '{f.rule_id}' is advisory: set its verdict to 'attested' (or "
                    f"'not_applicable'), not '{f.verdict.value}'"
                )
            errors += ctx.check_refs(f.cited_units)
        errors += [f"missing a finding for rule '{rid}'" for rid in rules if rid not in seen]
        return errors

    return validate


@dataclass
class AuditOutcome:
    findings: list[Finding]
    summary: str


UNSOURCED_FIX = "Cite a source unit for each claim or remove it."
QUOTE_FIX = (
    "Copy each quote word for word from the unit it cites, quoting every unit the claim cites, "
    "or cite the unit that says it."
)
BOTH_FIX = (
    "Cite a source unit for each claim and copy each quote word for word from the unit it "
    "cites, or remove the claim."
)


def _engine_evidence(unsourced: list[str], quoted: dict[str, list[str]]) -> tuple[str, str]:
    """A failing engine finding's evidence and recommendation. Unsourced claims alone read as
    they did before quotes existed (R-M11-6)."""
    parts = [f"claims without evidence: {', '.join(unsourced)}"] if unsourced else []
    parts += [p for problems in quoted.values() for p in problems]
    fix = BOTH_FIX if unsourced and quoted else QUOTE_FIX if quoted else UNSOURCED_FIX
    return f"{ENGINE_CHECK}{'; '.join(parts)}", fix


def apply_engine_checks(
    draft: ReportBody,
    findings: list[Finding],
    pack: ResolvedPack,
    quotes: QuoteCheck | None = None,
) -> list[Finding]:
    """Engine-owned checks that a lenient model cannot waive (spec §8.4 invariant 1): any
    unsourced claim fails icd203.tc.8, and one cited by a key judgment fails icd206.src.2. With
    `quotes` (CRL-93, `pipeline.evidence_quotes` not `off`) a quote missing from the unit it
    cites, or with `required` a cited unit the claim does not quote, fails them the same way.
    A rule the auditor already failed keeps the auditor's finding, with any quote problems
    added to its evidence."""
    unsourced = [c.id for c in draft.unsourced_claims()]
    quoted = quote_problems(draft, quotes) if quotes is not None else {}
    in_judgments = {cid for kj in draft.key_judgments for cid in kj.claim_ids}
    order = [c.id for c in draft.claims]
    overrides = {
        "icd203.tc.8": (unsourced, quoted),
        "icd206.src.2": (
            [cid for cid in unsourced if cid in in_judgments],
            {cid: p for cid, p in quoted.items() if cid in in_judgments},
        ),
    }
    known = set(pack.rule_ids())
    out: list[Finding] = []
    for f in findings:
        bad_unsourced, bad_quotes = overrides.get(f.rule_id, ([], {}))
        if (bad_unsourced or bad_quotes) and f.rule_id in known and f.verdict is not Verdict.FAIL:
            evidence, fix = _engine_evidence(bad_unsourced, bad_quotes)
            ids = set(bad_unsourced) | set(bad_quotes)
            f = f.model_copy(
                update={
                    "verdict": Verdict.FAIL,
                    "evidence": evidence,
                    "claim_ids": [cid for cid in order if cid in ids],
                    "recommendation": fix,
                }
            )
        elif bad_quotes and f.rule_id in known:
            # The auditor failed the rule too: its finding stands, and the engine's quote
            # problems are added to it so a misquote is never hidden behind the auditor's text.
            ids = set(f.claim_ids) | set(bad_quotes)
            problems = "; ".join(p for found in bad_quotes.values() for p in found)
            f = f.model_copy(
                update={
                    "evidence": f"{f.evidence}; {ENGINE_CHECK}{problems}"
                    if f.evidence
                    else f"{ENGINE_CHECK}{problems}",
                    "claim_ids": [cid for cid in order if cid in ids],
                }
            )
        out.append(f)
    return out


def engine_only_findings(
    draft: ReportBody, pack: ResolvedPack, iteration: int, quotes: QuoteCheck | None = None
) -> list[Finding]:
    """Spec §8.4 invariant 1 without an auditor (R-M11-6): the engine fails icd203.tc.8 on every
    unsourced or misquoted claim and icd206.src.2 on one a key judgment cites; it asserts
    nothing else."""
    rules = {r.id: r for r in pack.rules}
    seeds = [
        Finding(
            rule_id=rid,
            verdict=Verdict.PASS,
            evidence="",
            severity=rules[rid].severity.value,
            route_to=rules[rid].route_to.value,
            iteration=iteration,
        )
        for rid in ("icd203.tc.8", "icd206.src.2")
        if rid in rules
    ]
    return [f for f in apply_engine_checks(draft, seeds, pack, quotes) if f.verdict is Verdict.FAIL]


def merge_engine_findings(previous: list[Finding], engine: list[Finding]) -> list[Finding]:
    """The findings a report delivered without its last audit carries (R-M11-6, CRL-30): the
    last completed audit's findings, with the engine's rules replaced by the engine's results on
    the delivered draft. An earlier iteration's engine-check failure the engine no longer
    reproduces is dropped: the revision fixed the claim. The auditor's own findings stay, on the
    engine's two rules as well; they are the best information available about the draft."""
    replaced = {f.rule_id for f in engine}
    kept = [
        f for f in previous if f.rule_id not in replaced and not f.evidence.startswith(ENGINE_CHECK)
    ]
    return kept + engine


def auditor_payload(
    pack: ResolvedPack,
    draft: ReportBody,
    cited_units: list[dict[str, Any]],
    value_statement: str,
    prior: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The auditor's input: the draft, every rule of the pack, the lexicon and the units the
    draft cites (`cited_unit_payload`), and with `prior` (`write.prior_reports_payload`, CRL-97)
    the earlier accepted reports the writer read. `corelata doctor`'s auditor probe sends the
    same shape (R-M13-1)."""
    return {
        "task": "auditor",
        "draft": draft.model_dump(),
        "rules": [
            {
                "id": r.id,
                "title": r.title,
                "text": r.text,
                "severity": r.severity.value,
                "checkability": r.checkability.value,
                "evidence_required": r.evidence_required,
            }
            for r in pack.rules
        ],
        "lexicon": pack.lexicon.model_dump(),
        "cited_units": cited_units,
        "value_statement": value_statement,
        **(prior or {}),
    }


INITIAL_COVERAGE = (
    "initial coverage: this project has no earlier accepted report whose judgments this report "
    "could be consistent with or change"
)


def apply_initial_coverage(findings: list[Finding], rule_ids: list[str]) -> list[Finding]:
    """CRL-97: a rule that judges a report against the project's earlier accepted reports
    (`with_prior_reports`) is `not_applicable` when the project has none. The engine records it,
    whatever the auditor said, which was asked the rule as written."""
    return [
        f.model_copy(
            update={
                "verdict": Verdict.NOT_APPLICABLE,
                "evidence": INITIAL_COVERAGE,
                "cited_units": [],
                "claim_ids": [],
                "recommendation": "",
            }
        )
        if f.rule_id in rule_ids
        else f
        for f in findings
    ]


def cited_unit_payload(ctx: StageContext, draft: ReportBody) -> list[dict[str, Any]]:
    """The units the draft cites, `{"ref", "text"}` each. With `evidence_quotes` on (CRL-93)
    each also carries `quotes`: what the draft's claims quote from it, `{"claim_id", "text"}`,
    so the auditor reads a quote next to its unit."""
    cited = sorted({r for c in draft.claims for r in c.evidence if ctx.index.has(r)})
    units: list[dict[str, Any]] = [{"ref": r, "text": ctx.index.text(r)} for r in cited]
    if ctx.evidence_quotes is EvidenceQuotes.OFF:
        return units
    for unit in units:
        unit["quotes"] = [
            {"claim_id": c.id, "text": q.text}
            for c in draft.claims
            for q in c.quotes
            if q.ref == unit["ref"]
        ]
    return units


async def run_auditor(ctx: StageContext, *, iteration: int, draft: ReportBody) -> AuditOutcome:
    units = cited_unit_payload(ctx, draft)
    cited = [u["ref"] for u in units]
    output_type = audit_output_type(ctx.pack, cited, [c.id for c in draft.claims])
    backstop = audit_validator(ctx)
    parsed = await ctx.runner.run(
        role="auditor",
        model_key=ctx.model_key("auditor"),
        prompt_id="auditor",
        prompt_vars={
            "evidence_quotes": ctx.evidence_quotes.value,
            "prior_reports": bool(ctx.prior_reports),
        },
        payload=auditor_payload(
            ctx.pack, draft, units, ctx.value_statement, prior_reports_payload(ctx)
        ),
        output_type=output_type,
        validate=lambda o: backstop(to_audit_output(o, ctx.pack)),
    )
    out = to_audit_output(parsed, ctx.pack)
    by_id = {f.rule_id: f for f in out.findings}
    findings = [
        Finding(
            **by_id[r.id].model_dump(),
            severity=r.severity.value,
            route_to=r.route_to.value,
            iteration=iteration,
        )
        for r in ctx.pack.rules
    ]
    findings = apply_initial_coverage(findings, ctx.initial_coverage)
    return AuditOutcome(
        apply_engine_checks(draft, findings, ctx.pack, ctx.quote_check()), out.summary
    )


def open_findings(findings: list[Finding]) -> list[Finding]:
    return [f for f in findings if f.verdict is Verdict.FAIL and f.severity in LOOPING]


def decide_next(findings: list[Finding], iteration: int, max_iterations: int) -> Next:
    """Spec §6.2 and §7.3: blocking and major failures loop while budget remains; the writer
    is re-run if any failure is routed to it, else only the conveyor."""
    open_ = open_findings(findings)
    if not open_ or iteration >= max_iterations:
        return "rendering"
    if any(f.route_to == "writer" for f in open_):
        return "drafting"
    return "conveying"
