"""The structurer of a check run (CRL-94): a finished report someone else wrote, mapped onto
`ReportBody` word for word so the auditor can check it rule by rule.

The engine, not the model, decides what the report says. It splits the report into sentences
(`report_sentences`); every claim's text must be one of them, each sentence the text of exactly
one claim, and every other text the structurer writes (title, marking, key judgments, headings,
paragraphs, scope note, alternatives, gaps) must be the report's own words or empty
(`structure_errors`). The per-call schema makes `Claim.text` an enum of the sentences, so a
`json_schema` server cannot write anything else; the validator is the backstop and its message
goes back in the repair turn. The parsed reply is then put in the report's order with each
claim's text exactly as the engine split it (`canonical`), so the trace's claims are the
report's sentences apart from whitespace whatever the server. A sentence the structurer cannot
source keeps an empty evidence list, and the engine's own check fails it at audit (spec §8.4
invariant 1)."""

import re
from collections import Counter
from collections.abc import Callable
from typing import Any

from corelata.config import EvidenceQuotes
from corelata.schema import BlockKind, ReportBody, Source
from corelata.stages.context import StageContext, StageError
from corelata.stages.report_schema import report_output_type
from corelata.stages.write import quote_errors, quotes_mode, select_writer_units, shape_reply

# The source id a check run gives the report it checks, in the trace and in its unit refs.
REPORT_ID = "report"
# A sentence ends at ., ! or ? (and any closing quotes or brackets) before whitespace and an
# opening quote, bracket, capital or digit. "U.S. Navy" splits after "U.S."; R-CRL94-3.
_END = re.compile(r"[.!?][\"'”’)\]]*(?=\s+[\"'“‘(\[]?[A-Z0-9])")
# How much of a text a repair message quotes.
_SHOWN = 80


def norm(text: str) -> str:
    """`text` with its whitespace collapsed: what "the report's own words" compares."""
    return " ".join(text.split())


def split_sentences(text: str) -> list[str]:
    text = norm(text)
    out: list[str] = []
    start = 0
    for m in _END.finditer(text):
        out.append(text[start : m.end()].strip())
        start = m.end()
    out.append(text[start:].strip())
    return [s for s in out if s]


def report_sentences(report: Source, markings: list[str]) -> list[str]:
    """The sentences a check run's claims must be (R-CRL94-2): every unit's text but headings
    and a line that is only one of the pack's handling markings, split into sentences, in
    order."""
    marking = {norm(m) for m in markings}
    out: list[str] = []
    for unit in report.units:
        if unit.kind is BlockKind.HEADING or norm(unit.text) in marking:
            continue
        out.extend(split_sentences(unit.text))
    return out


def _short(text: str) -> str:
    text = norm(text)
    return text if len(text) <= _SHOWN else text[: _SHOWN - 1] + "…"


def _spans(body: ReportBody) -> list[tuple[str, str]]:
    """Every text of `body` besides the claims and the source entries, with where it is."""
    out = [("title", body.title), ("handling_marking", body.handling_marking)]
    out.append(("scope_note", body.scope_note))
    out += [(f"key_judgments[{i}].text", kj.text) for i, kj in enumerate(body.key_judgments)]
    for i, section in enumerate(body.analysis):
        out.append((f"analysis[{i}].heading", section.heading))
        out += [
            (f"analysis[{i}].paragraphs[{j}].text", p.text)
            for j, p in enumerate(section.paragraphs)
        ]
    for i, alt in enumerate(body.alternatives):
        out += [
            (f"alternatives[{i}].hypothesis", alt.hypothesis),
            (f"alternatives[{i}].assessment", alt.assessment),
        ]
    out += [(f"gaps_and_indicators[{i}]", g) for i, g in enumerate(body.gaps_and_indicators)]
    return out


def structure_errors(body: ReportBody, report: Source, sentences: list[str]) -> list[str]:
    """How `body` departs from the report (R-CRL94-2), each worded as what to write instead.
    Empty when every claim is one sentence, each sentence one claim, and every other text is the
    report's own words or empty."""
    errors: list[str] = []
    full = " ".join(norm(u.text) for u in report.units)
    for where, text in _spans(body):
        if norm(text) and norm(text) not in full:
            errors.append(
                f"{where}: '{_short(text)}' is not in the report; copy the report's own words "
                "exactly, or leave it empty"
            )
    wanted = Counter(sentences)
    given = Counter(norm(c.text) for c in body.claims)
    for c in body.claims:
        if norm(c.text) not in wanted:
            errors.append(
                f"claim '{c.id}': '{_short(c.text)}' is not one of INPUT_JSON.sentences; give "
                "each claim the text of one sentence, copied exactly"
            )
    for sentence, n in given.items():
        if sentence in wanted and n > wanted[sentence]:
            errors.append(
                f"'{_short(sentence)}' is the text of {n} claims; give each sentence exactly "
                "one claim"
            )
    missing = [s for s in wanted if given[s] < wanted[s]]
    if missing:
        shown = "; ".join(f"'{_short(s)}'" for s in missing[:5])
        more = f" and {len(missing) - 5} more" if len(missing) > 5 else ""
        errors.append(
            f"{len(missing)} sentence{'' if len(missing) == 1 else 's'} of the report "
            f"{'has' if len(missing) == 1 else 'have'} no claim: {shown}{more}; add one claim "
            "for every entry of INPUT_JSON.sentences"
        )
    return errors


def canonical(body: ReportBody, sentences: list[str]) -> ReportBody:
    """`body` with its claims in the report's order and each claim's text exactly the sentence
    the engine split (R-CRL94-2): whitespace and claim order are the only differences a reply
    `structure_errors` accepted can have from the report, and this removes both."""
    slots: dict[str, list[int]] = {}
    for i, s in enumerate(sentences):
        slots.setdefault(s, []).append(i)
    placed: list[tuple[int, Any]] = []
    for c in body.claims:
        i = slots[norm(c.text)].pop(0)
        placed.append((i, c.model_copy(update={"text": sentences[i]})))
    claims = [c for _, c in sorted(placed, key=lambda p: p[0])]
    return body.model_copy(update={"claims": claims})


def _source_errors(ctx: StageContext, body: ReportBody) -> list[str]:
    known = [s.id for s in ctx.sources]
    errors: list[str] = []
    seen: set[str] = set()
    for entry in body.sources:
        if entry.source_id not in known:
            errors.append(f"unknown source id '{entry.source_id}' in sources")
        elif entry.source_id in seen:
            errors.append(f"duplicate source entry '{entry.source_id}'")
        seen.add(entry.source_id)
    errors += [f"source '{sid}' has no entry in sources" for sid in known if sid not in seen]
    terms = ctx.pack.lexicon.source_access
    errors += [
        f"source '{e.source_id}': access '{e.access}' is not in the lexicon "
        f"(allowed: {', '.join(terms)})"
        for e in body.sources
        if terms and e.access not in terms
    ]
    return errors


def structure_validator(
    ctx: StageContext, report: Source, sentences: list[str]
) -> Callable[[ReportBody], list[str]]:
    def validate(body: ReportBody) -> list[str]:
        errors = ctx.check_refs([r for c in body.claims for r in c.evidence])
        errors += quote_errors(ctx, body)
        errors += _source_errors(ctx, body)
        errors += structure_errors(body, report, sentences)
        return errors

    return validate


def structure_schema(ctx: StageContext, sentences: list[str]) -> dict[str, Any]:
    """The writer's per-call schema with `Claim.text` drawn from the report's sentences. No
    source summary and no earlier reports: the structurer copies, and a summary the report does
    not have is for the auditor to miss, not for the structurer to write (R-CRL94-4)."""
    return report_output_type(
        ctx.index.refs(),
        [s.id for s in ctx.sources],
        quotes=ctx.evidence_quotes is not EvidenceQuotes.OFF,
        access_terms=ctx.pack.lexicon.source_access,
        claim_texts=sentences,
    ).model_json_schema()


def report_payload(report: Source) -> dict[str, Any]:
    return {
        "name": report.name,
        "blocks": [{"kind": u.kind.value, "text": u.text} for u in report.units],
    }


async def run_structurer(ctx: StageContext, report: Source) -> ReportBody:
    sentences = report_sentences(report, ctx.pack.lexicon.handling_markings)
    if not sentences:
        raise StageError("structuring", f"{report.name} has no sentences to check")
    parsed = await ctx.runner.run(
        role="structurer",
        model_key=ctx.model_key("structurer"),
        prompt_id="structurer",
        prompt_vars={
            "section_order": ctx.pack.template.section_order,
            "evidence_quotes": ctx.evidence_quotes.value,
        },
        payload={
            "task": "structurer",
            "report": report_payload(report),
            "sentences": sentences,
            "template": ctx.pack.template.model_dump(),
            "lexicon": ctx.pack.lexicon.model_dump(),
            "digests": ctx.digest_payload(),
            "units": ctx.unit_payload(select_writer_units(ctx)),
            "sources": ctx.source_payload(),
            "value_statement": ctx.value_statement,
            **quotes_mode(ctx),
        },
        output_type=ReportBody,
        schema=structure_schema(ctx, sentences),
        validate=structure_validator(ctx, report, sentences),
    )
    return canonical(shape_reply(ctx, parsed), sentences)
