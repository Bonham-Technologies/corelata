"""A renderer-neutral outline of a report (spec §9): the one place that knows section order,
heading numbering, how a source line reads, how sources are numbered and cited, and how the
open-findings appendix is laid out. Markdown, HTML and DOCX walk this outline, so the three
outputs cannot drift apart.

Source reference citations (CRL-96, ICD 206 D.3.a): the sources section is a numbered list in
the report's source order, and every paragraph or item whose claims cite units carries the
numbers of those units' sources (`refs`), which each renderer shows as a superscript."""

from dataclasses import dataclass
from typing import ClassVar

from corelata.ingest.units import ocr_note, ocr_page_count
from corelata.schema import (
    ChangeKind,
    Finding,
    JudgmentChange,
    PriorReportRef,
    Report,
    Source,
    SourceEntry,
    SourceKind,
    SourceSummaryStatement,
)
from corelata.schema.source import split_ref
from corelata.standards.schema import ResolvedPack

SECTION_TITLES = {
    "key_judgments": "Key judgments",
    "scope_note": "Scope note",
    "sources": "Sources",
    "source_summary": "Source summary",
    "alternatives": "Alternatives considered",
    "gaps_and_indicators": "Gaps and indicators",
    # CRL-97: how the key judgments stand against the project's earlier accepted reports
    "changes_from_previous": "Changes from previous analysis",
}
CHANGE_LEADS = {
    ChangeKind.CONSISTENT: "Consistent with earlier analysis.",
    ChangeKind.CHANGED: "Changed from earlier analysis.",
}
QUOTES_TITLE = "Cited passages"  # CRL-93: the words each claim quotes, when any claim quotes
APPENDIX_TITLE = "Audit findings open at delivery"
DEGRADATION_TITLE = "Stages incomplete at delivery"  # R-M11-2: stages it was delivered without
# CRL-139: `format.production_statement`, the last section (`render.production`)
PRODUCTION_TITLE = "How this report was produced"


@dataclass(frozen=True)
class Marking:
    kind: ClassVar[str] = "marking"
    text: str


@dataclass(frozen=True)
class Title:
    kind: ClassVar[str] = "title"
    text: str


@dataclass(frozen=True)
class Heading:
    kind: ClassVar[str] = "heading"
    text: str
    number: int | None = None

    @property
    def label(self) -> str:
        return f"{self.number}. {self.text}" if self.number is not None else self.text


@dataclass(frozen=True)
class Para:
    kind: ClassVar[str] = "para"
    text: str
    claim_ids: tuple[str, ...] = ()
    refs: tuple[int, ...] = ()  # source reference numbers (CRL-96)


@dataclass(frozen=True)
class Item:
    text: str
    lead: str = ""  # bold lead-in: "Moderate confidence." or an alternative's hypothesis
    claim_ids: tuple[str, ...] = ()
    refs: tuple[int, ...] = ()  # source reference numbers (CRL-96)


@dataclass(frozen=True)
class Bullets:
    kind: ClassVar[str] = "bullets"
    items: tuple[Item, ...]
    # key_judgments | changes | sources | alternatives | gaps | quotes | degradations | findings
    # | production
    role: str = "list"
    numbered: bool = False  # items are numbered from 1: the sources section (CRL-96)


Block = Marking | Title | Heading | Para | Bullets


def source_line(entry: SourceEntry, source: Source | None) -> str:
    name = source.name if source else entry.source_id
    extra = f"sha256 {source.sha256[:8]}" if source else "sha256 unknown"
    if source and source.kind is SourceKind.COGLOSSA_EXPORT:
        extra += f"; Coglossa run {source.provenance.get('coglossa_run_id', 'unknown')}"
    if source and (pages := ocr_page_count(source)):
        extra += f"; {ocr_note(pages)}"
    details = [
        f"{label}: {value}"
        for label, value in (
            ("originator", entry.origin),
            ("date of information", entry.date_of_information),
            ("access", entry.access),
        )
        if value
    ]
    note = "".join(f"; {part}" for part in [*details, entry.reliability_note] if part)
    return f"{name} — {entry.descriptor}{note} ({extra})"


class SourceRefs:
    """Source reference numbers: the n-th entry of the sources section is source n, and a
    claim cites the sources of its evidence units."""

    def __init__(self, report: Report) -> None:
        self.number = {e.source_id: i for i, e in enumerate(report.sources, start=1)}
        self._claims: dict[str, set[str]] = {}
        for c in report.claims:
            ids = self._claims.setdefault(c.id, set())
            for ref in c.evidence:
                try:
                    ids.add(split_ref(ref)[0])
                except ValueError:
                    continue

    def of_sources(self, source_ids: list[str]) -> tuple[int, ...]:
        return tuple(sorted({self.number[s] for s in source_ids if s in self.number}))

    def of_claims(self, claim_ids: list[str]) -> tuple[int, ...]:
        return self.of_sources([s for cid in claim_ids for s in self._claims.get(cid, ())])


def source_names(source_ids: list[str], by_id: dict[str, Source]) -> str:
    return ", ".join(by_id[s].name if s in by_id else s for s in source_ids)


def summary_blocks(
    summary: SourceSummaryStatement, cites: SourceRefs, by_id: dict[str, Source]
) -> list[Para]:
    """The source summary statement (CRL-96, ICD 206 D.3.d): its assessment, the sources the key
    judgments depend on most, and corroboration and conflict, citing the sources it names."""
    out = [Para(summary.strengths_and_weaknesses)]
    if summary.key_sources:
        names = source_names(summary.key_sources, by_id)
        out.append(
            Para(
                f"Most important to the key judgments: {names}.",
                refs=cites.of_sources(summary.key_sources),
            )
        )
    out.append(Para(summary.corroboration))
    if summary.conflicting_sources:
        names = source_names(summary.conflicting_sources, by_id)
        out.append(
            Para(
                f"Conflicting reporting: {names}.",
                refs=cites.of_sources(summary.conflicting_sources),
            )
        )
    return [p for p in out if p.text]


def passage_lead(claim_id: str, ref: str, by_id: dict[str, Source]) -> str:
    """ "c3 · port-notice.txt, para 2": where a quoted passage is, in the reader's terms."""
    try:
        source_id, unit_id = split_ref(ref)
    except ValueError:
        return f"{claim_id} · {ref}"
    source = by_id.get(source_id)
    unit = next((u for u in source.units if u.id == unit_id), None) if source else None
    if source is None or unit is None:
        return f"{claim_id} · {ref}"
    return f"{claim_id} · {source.name}, {unit.locator}"


def change_item(
    change: JudgmentChange, by_run: dict[str, PriorReportRef], refs: tuple[int, ...] = ()
) -> Item:
    """One entry of "Changes from previous analysis" in the reader's terms: the earlier report
    by its title and acceptance date, never its run id; `refs` cite the sources of its claims."""
    prior = by_run.get(change.prior_run_id)
    where = "an earlier report"
    if prior is not None:
        at = prior.accepted_at
        where = f"\u201c{prior.title}\u201d, {at.day} {at:%B %Y}"
    text = f"{change.explanation} Earlier judgment ({where}): \u201c{change.prior_judgment}\u201d"
    return Item(text, CHANGE_LEADS[change.change], tuple(change.claim_ids), refs)


def finding_line(f: Finding) -> str:
    rec = f" — {f.recommendation}" if f.recommendation else ""
    return f"{f.rule_id} ({f.severity}): {f.evidence}{rec}"


def build_outline(
    report: Report,
    pack: ResolvedPack,
    sources: list[Source],
    *,
    open_findings: list[Finding] | None = None,
    production: list[str] | None = None,
) -> list[Block]:
    """Blocks in reading order. `handling_marking` in the template is honoured by the marking
    blocks at top and bottom; a section name this version does not know is skipped. `production`
    is the lines of "How this report was produced" (CRL-139), the last section; None leaves it
    out."""
    numbered = pack.format.heading_style == "numbered"
    by_id = {s.id: s for s in sources}
    cites = SourceRefs(report)
    out: list[Block] = [Marking(report.handling_marking)]
    counter = 0

    def heading(text: str) -> Heading:
        nonlocal counter
        counter += 1
        return Heading(text, counter if numbered else None)

    def changes() -> list[Block]:
        if not report.changes_from_previous:
            return []
        by_run = {r.run_id: r for r in report.metadata.prior_reports}
        items = tuple(
            change_item(ch, by_run, cites.of_claims(ch.claim_ids))
            for ch in report.changes_from_previous
        )
        return [heading(SECTION_TITLES["changes_from_previous"]), Bullets(items, "changes")]

    for section in pack.template.section_order:
        if section == "title":
            out.append(Title(report.title))
        elif section == "key_judgments":
            out.append(heading(SECTION_TITLES[section]))
            items = tuple(
                Item(
                    kj.text,
                    f"{kj.confidence.value.capitalize()} confidence.",
                    tuple(kj.claim_ids),
                    cites.of_claims(kj.claim_ids),
                )
                for kj in report.key_judgments
            )
            out.append(Bullets(items, "key_judgments"))
            out.extend(changes())
        elif section == "scope_note":
            out.append(heading(SECTION_TITLES[section]))
            out.append(Para(report.scope_note))
        elif section == "sources":
            out.append(heading(SECTION_TITLES[section]))
            items = tuple(Item(source_line(e, by_id.get(e.source_id))) for e in report.sources)
            out.append(Bullets(items, "sources", numbered=True))
        elif section == "source_summary" and report.source_summary is not None:
            out.append(heading(SECTION_TITLES[section]))
            out.extend(summary_blocks(report.source_summary, cites, by_id))
        elif section == "analysis":
            for sec in report.analysis:
                out.append(heading(sec.heading))
                out.extend(
                    Para(p.text, tuple(p.claim_ids), cites.of_claims(p.claim_ids))
                    for p in sec.paragraphs
                )
        elif section == "alternatives":
            out.append(heading(SECTION_TITLES[section]))
            items = tuple(
                Item(a.assessment, a.hypothesis, tuple(a.claim_ids), cites.of_claims(a.claim_ids))
                for a in report.alternatives
            )
            out.append(Bullets(items, "alternatives"))
        elif section == "gaps_and_indicators":
            out.append(heading(SECTION_TITLES[section]))
            out.append(Bullets(tuple(Item(g) for g in report.gaps_and_indicators), "gaps"))
    if "key_judgments" not in pack.template.section_order:
        out.extend(changes())  # a template without key judgments still shows the element
    quoted = [(c.id, q) for c in report.claims for q in c.quotes]
    if quoted:
        out.append(Heading(QUOTES_TITLE))
        items = tuple(
            Item(f"\u201c{q.text}\u201d", passage_lead(cid, q.ref, by_id), (cid,))
            for cid, q in quoted
        )
        out.append(Bullets(items, "quotes"))
    if report.metadata.degradations:
        out.append(Heading(DEGRADATION_TITLE))
        items = tuple(Item(d) for d in report.metadata.degradations)
        out.append(Bullets(items, "degradations"))
    if open_findings:
        out.append(Heading(APPENDIX_TITLE))
        out.append(Bullets(tuple(Item(finding_line(f)) for f in open_findings), "findings"))
    if production:
        out.append(Heading(PRODUCTION_TITLE))
        out.append(Bullets(tuple(Item(line) for line in production), "production"))
    out.append(Marking(report.handling_marking))
    return out
