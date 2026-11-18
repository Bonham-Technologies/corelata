"""One fixture report, source list and finding shared by every renderer test."""

from corelata.schema import (
    Alternative,
    BlockKind,
    Claim,
    ClaimKind,
    Confidence,
    Finding,
    FindingOut,
    KeyJudgment,
    Paragraph,
    Report,
    ReportMetadata,
    Section,
    Source,
    SourceEntry,
    SourceKind,
    SourceUnit,
    Verdict,
)
from corelata.standards.loader import load_pack

PACK = load_pack("icd203-base")
NUMBERED = PACK.model_copy(
    update={"format": PACK.format.model_copy(update={"heading_style": "numbered"})}
)

SOURCES = [
    Source(
        id="src1",
        kind=SourceKind.FILE,
        name="a.txt",
        format="txt",
        sha256="abcdef0123456789" * 4,
        units=[
            SourceUnit(id="u1", text="Grew 40 percent.", locator="para 1", kind=BlockKind.PARAGRAPH)
        ],
    ),
    Source(
        id="src2",
        kind=SourceKind.COGLOSSA_EXPORT,
        name="b.json",
        format="coglossa",
        sha256="ff" * 32,
        provenance={"coglossa_run_id": "run-42"},
        units=[],
    ),
]


def make_report(**metadata) -> Report:
    return Report(
        title="Varna port",
        handling_marking="UNCLASSIFIED",
        key_judgments=[
            KeyJudgment(text="Capacity grew.", confidence=Confidence.MODERATE, claim_ids=["c1"])
        ],
        scope_note="Two sources.",
        sources=[
            SourceEntry(
                source_id="src1", descriptor="open-source report", reliability_note="Current."
            ),
            SourceEntry(
                source_id="src2", descriptor="translated document", reliability_note="Tier B."
            ),
        ],
        analysis=[
            Section(
                heading="Capacity",
                paragraphs=[Paragraph(text="Grew 40 percent.", claim_ids=["c1"])],
            )
        ],
        alternatives=[Alternative(hypothesis="Flat.", assessment="Unlikely.")],
        gaps_and_indicators=["Customs data."],
        claims=[Claim(id="c1", text="Grew.", kind=ClaimKind.FACT, evidence=["src1/u1"])],
        metadata=ReportMetadata(pack_name="icd203-base", pack_hash="h", **metadata),
    )


def make_finding(recommendation: str = "Cite or remove.") -> Finding:
    return Finding(
        **FindingOut(
            rule_id="icd203.tc.8",
            verdict=Verdict.FAIL,
            evidence="c9 has no evidence",
            recommendation=recommendation,
        ).model_dump(),
        severity="blocking",
        route_to="writer",
        iteration=2,
    )


def empty_lists_report() -> Report:
    """Headings with nothing under them must not break any renderer (Review Focus 4)."""
    r = make_report()
    return r.model_copy(update={"analysis": [], "alternatives": [], "gaps_and_indicators": []})
