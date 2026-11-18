from corelata.render.markdown import render_markdown
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


def _report(**md) -> Report:
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
        metadata=ReportMetadata(pack_name="icd203-base", pack_hash="h", **md),
    )


SOURCES = [
    Source(
        id="src1",
        kind=SourceKind.FILE,
        name="a.txt",
        format="txt",
        sha256="abcdef0123456789" * 4,
        units=[SourceUnit(id="u1", text="x", locator="para 1", kind=BlockKind.PARAGRAPH)],
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


def test_sections_in_template_order_with_marking_top_and_bottom():
    pack = load_pack("icd203-base")
    md = render_markdown(_report(), pack, SOURCES)
    lines = md.strip().splitlines()
    assert lines[0] == "UNCLASSIFIED" and lines[-1] == "UNCLASSIFIED"
    headings = [ln for ln in lines if ln.startswith("## ")]
    assert headings == [
        "## Key judgments",
        "## Scope note",
        "## Sources",
        "## Capacity",
        "## Alternatives considered",
        "## Gaps and indicators",
    ]
    assert "# Varna port" in md
    assert "**Moderate confidence.** Capacity grew." in md
    assert "- a.txt — open-source report; Current. (sha256 abcdef01)" in md
    assert "- b.json — translated document; Tier B. (sha256 ffffffff; Coglossa run run-42)" in md
    assert "^[c1]" not in md


def test_claim_ids_and_numbered_headings_and_open_findings():
    base = load_pack("icd203-base")
    pack = base.model_copy(
        update={"format": base.format.model_copy(update={"heading_style": "numbered"})}
    )
    finding = Finding(
        **FindingOut(
            rule_id="icd203.tc.8",
            verdict=Verdict.FAIL,
            evidence="c9 has no evidence",
            recommendation="Cite or remove.",
        ).model_dump(),
        severity="blocking",
        route_to="writer",
        iteration=2,
    )
    md = render_markdown(
        _report(status="findings_open", open_findings=["icd203.tc.8@2"]),
        pack,
        SOURCES,
        with_claim_ids=True,
        open_findings=[finding],
    )
    assert "## 1. Key judgments" in md and "## 4. Capacity" in md
    assert "Grew 40 percent. ^[c1]" in md
    assert "## Audit findings open at delivery" in md
    assert "- icd203.tc.8 (blocking): c9 has no evidence — Cite or remove." in md
