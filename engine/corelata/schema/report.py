"""The report is structured, never free prose, so every assertion is addressable (spec §8.1)."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class Confidence(StrEnum):
    HIGH = "high"
    MODERATE = "moderate"
    LOW = "low"


class ClaimKind(StrEnum):
    FACT = "fact"
    JUDGMENT = "judgment"
    ASSUMPTION = "assumption"


class Quote(BaseModel):
    """Words copied verbatim from one of the units a claim cites."""

    # CRL-93: the engine checks that the words appear in that unit (`corelata.quotes`).
    ref: str = Field(
        description="The unit ref the words are copied from, one of the claim's evidence"
    )
    text: str = Field(
        description="Words copied verbatim from that unit: one contiguous span, no ellipses"
    )


def _no_quotes(quotes: list[Quote]) -> bool:
    return not quotes


class ClaimCore(BaseModel):
    """`Claim` without its quotes: the per-call schema a run with `pipeline.evidence_quotes: off`
    sends is built on it (`stages/report_schema.py`), so that schema is the one a run sent before
    quotes existed."""

    id: str = Field(description="Short id such as c1; unique within the report")
    text: str
    kind: ClaimKind
    evidence: list[str] = Field(
        default_factory=list, description="Unit refs (<source_id>/<unit_id>) the claim rests on"
    )
    likelihood_term: str | None = Field(
        None, description="For judgments: the estimative term used, from the lexicon"
    )


class Claim(ClaimCore):
    # An empty list is left out of every dump, so a draft without quotes serialises exactly as
    # it did before quotes existed (a trace, a payload, report.json).
    quotes: list[Quote] = Field(
        default_factory=list,
        description="Verbatim spans of the cited units that support the claim",
        exclude_if=_no_quotes,
    )


class KeyJudgment(BaseModel):
    text: str
    confidence: Confidence
    claim_ids: list[str]


def _blank(value: str) -> bool:
    return not value


class SourceEntryCore(BaseModel):
    """`SourceEntry` without the CRL-96 details: the per-call schema a pack whose lexicon has no
    `source_access` list sends is built on it, so that schema is the one sent before them."""

    source_id: str
    descriptor: str = Field(description="A source descriptor phrase from the lexicon")
    reliability_note: str = ""


class SourceEntry(SourceEntryCore):
    # CRL-96 (ICD 206 D.3.a(6), D.3.c): what a source reference citation says about the source
    # besides its descriptor. A blank value is left out of every dump, so an entry without them
    # serialises exactly as it did before they existed.
    date_of_information: str = Field(
        "",
        description="When the source's information was issued or current, as precisely as the "
        "source says (2026-08-10, July 2026); empty when unknown",
        exclude_if=_blank,
    )
    origin: str = Field(
        "",
        description="Who originated, authored or published the information; empty when unknown",
        exclude_if=_blank,
    )
    access: str = Field(
        "",
        description="The source's access to what it reports, a term from the lexicon's "
        "source_access",
        exclude_if=_blank,
    )

    def details(self) -> tuple[str, str, str]:
        return (self.date_of_information, self.origin, self.access)


class SourceSummaryStatement(BaseModel):
    """ICD 206 D.3.d: the sources considered together (CRL-96)."""

    strengths_and_weaknesses: str = Field(
        description="Strengths and weaknesses of the source base as a whole"
    )
    key_sources: list[str] = Field(
        default_factory=list, description="Ids of the sources the key judgments depend on most"
    )
    corroboration: str = Field(
        description="Which sources corroborate one another and which conflict, naming them; "
        "say so when none conflict"
    )
    conflicting_sources: list[str] = Field(
        default_factory=list,
        description="Ids of the sources whose reporting conflicts with another source's; empty "
        "when none conflict",
    )


class Paragraph(BaseModel):
    text: str
    claim_ids: list[str] = Field(default_factory=list)


class Section(BaseModel):
    heading: str
    paragraphs: list[Paragraph]


class Alternative(BaseModel):
    hypothesis: str
    assessment: str
    claim_ids: list[str] = Field(default_factory=list)


class ChangeKind(StrEnum):
    CONSISTENT = "consistent"
    CHANGED = "changed"


class JudgmentChange(BaseModel):
    """How the report stands against one key judgment of an earlier accepted report of its
    project (CRL-97, ICD 203 D.6.e(7))."""

    prior_run_id: str = Field(description="The earlier report's run_id in INPUT_JSON.prior_reports")
    prior_judgment: str = Field(description="The earlier key judgment, as it was stated")
    change: ChangeKind
    explanation: str = Field(
        description="What in this report agrees with the earlier judgment or departs from it, "
        "and why"
    )
    claim_ids: list[str] = Field(default_factory=list)


def _empty(items: list) -> bool:
    return not items


class ReportBodyCore(BaseModel):
    """`ReportBody` without `changes_from_previous` (CRL-97) or `source_summary` (CRL-96): the
    per-call schema (`stages/report_schema.py`) is built on it, or on `ReportBodyWithChanges`,
    and adds a source summary only when the template has that section, so a run without earlier
    reports or a source summary sends the schema a run sent before either existed."""

    title: str
    handling_marking: str
    key_judgments: list[KeyJudgment]
    scope_note: str
    sources: list[SourceEntry]
    analysis: list[Section]
    alternatives: list[Alternative]
    gaps_and_indicators: list[str]
    claims: list[Claim]

    @model_validator(mode="after")
    def _claim_ids_resolve(self) -> "ReportBodyCore":
        seen: set[str] = set()
        for c in self.claims:
            if c.id in seen:
                raise ValueError(f"duplicate claim id '{c.id}'")
            seen.add(c.id)
        for cid in sorted(self.referenced_claim_ids()):
            if cid not in seen:
                raise ValueError(f"unknown claim id '{cid}'")
        return self

    def referenced_claim_ids(self) -> set[str]:
        ids: set[str] = set()
        for kj in self.key_judgments:
            ids.update(kj.claim_ids)
        for section in self.analysis:
            for p in section.paragraphs:
                ids.update(p.claim_ids)
        for alt in self.alternatives:
            ids.update(alt.claim_ids)
        return ids

    def unsourced_claims(self) -> list[Claim]:
        return [c for c in self.claims if not c.evidence]


class ReportBodyWithChanges(ReportBodyCore):
    """`ReportBody` without `source_summary`: the per-call schema a run with earlier reports
    sends is built on it."""

    # CRL-97: asked for only when the run read earlier accepted reports; an empty list is left
    # out of every dump, so a report without it serialises as it did before.
    changes_from_previous: list[JudgmentChange] = Field(
        default_factory=list,
        description="How the key judgments stand against those of the project's earlier reports",
        exclude_if=_empty,
    )

    def referenced_claim_ids(self) -> set[str]:
        ids = super().referenced_claim_ids()
        for change in self.changes_from_previous:
            ids.update(change.claim_ids)
        return ids


def _no_summary(summary: SourceSummaryStatement | None) -> bool:
    return summary is None


class ReportBody(ReportBodyWithChanges):
    """What the writer and conveyor produce. `Report` adds engine-owned metadata."""

    # CRL-96: present when the template has a `source_summary` section; None is left out of every
    # dump, so a report without one serialises exactly as it did before the section existed.
    source_summary: SourceSummaryStatement | None = Field(None, exclude_if=_no_summary)


class ReportStatus(StrEnum):
    CLEAN = "clean"
    FINDINGS_OPEN = "findings_open"


class PriorReportRef(BaseModel):
    """An earlier accepted report of the run's project (CRL-97): its run id, title and when it
    was accepted."""

    run_id: str
    title: str
    accepted_at: datetime


class PriorJudgment(BaseModel):
    text: str
    confidence: Confidence


class PriorReport(PriorReportRef):
    """An earlier accepted report as a run was given it (CRL-97): its key judgments, and whether
    `pipeline.prior_judgments.budget_tokens` left it out (`cut`, oldest first)."""

    key_judgments: list[PriorJudgment]
    cut: bool = False


class ReportMetadata(BaseModel):
    run_id: str | None = None
    pack_name: str
    pack_hash: str
    profile: str | None = None
    iteration: int = 0
    status: ReportStatus | None = None
    open_findings: list[str] = Field(default_factory=list)  # Finding ids
    # Stages the report was delivered without (R-M11-2), for example
    # "audit incomplete after 2 attempts: <error>"; any entry makes the status findings_open.
    degradations: list[str] = Field(default_factory=list)
    # CRL-97: the earlier accepted reports the writer read, so `changes_from_previous` can name
    # them in the renders; left out when there are none.
    prior_reports: list[PriorReportRef] = Field(default_factory=list, exclude_if=_empty)


class Report(ReportBody):
    metadata: ReportMetadata
