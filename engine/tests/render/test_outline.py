import io
from pathlib import Path

from docx import Document

from corelata.render.docx import render_docx
from corelata.render.html import render_html
from corelata.render.markdown import render_markdown
from corelata.render.outline import (
    APPENDIX_TITLE,
    DEGRADATION_TITLE,
    Bullets,
    Heading,
    Item,
    Marking,
    Para,
    Title,
    build_outline,
    finding_line,
    source_line,
)
from corelata.schema import SourceEntry
from tests.render.fixtures import (
    NUMBERED,
    PACK,
    SOURCES,
    empty_lists_report,
    make_finding,
    make_report,
)

GOLDEN = Path(__file__).parent / "golden"


def check_golden(name: str, text: str) -> None:
    """First run writes the golden; review the file, then commit it. Later runs compare."""
    path = GOLDEN / name
    if not path.is_file():
        path.parent.mkdir(exist_ok=True)
        path.write_text(text, encoding="utf-8")
    assert text == path.read_text(encoding="utf-8")


def test_outline_follows_template_order_with_marking_top_and_bottom():
    blocks = build_outline(make_report(), PACK, SOURCES)
    assert blocks[0] == Marking("UNCLASSIFIED") and blocks[-1] == Marking("UNCLASSIFIED")
    assert [b.kind for b in blocks] == [
        "marking",
        "title",
        "heading",
        "bullets",
        "heading",
        "para",
        "heading",
        "bullets",
        "heading",
        "para",
        "heading",
        "bullets",
        "heading",
        "bullets",
        "marking",
    ]
    assert blocks[1] == Title("Varna port")
    headings = [b for b in blocks if isinstance(b, Heading)]
    assert [h.label for h in headings] == [
        "Key judgments",
        "Scope note",
        "Sources",
        "Capacity",
        "Alternatives considered",
        "Gaps and indicators",
    ]
    assert all(h.number is None for h in headings)
    kj = blocks[3]
    assert isinstance(kj, Bullets) and kj.role == "key_judgments"
    assert kj.items == (Item("Capacity grew.", "Moderate confidence.", ("c1",)),)
    assert blocks[5] == Para("Two sources.")
    assert blocks[9] == Para("Grew 40 percent.", ("c1",))
    alts = blocks[11]
    assert alts.items == (Item("Unlikely.", "Flat.", ()),) and alts.role == "alternatives"
    assert blocks[13].items == (Item("Customs data."),) and blocks[13].role == "gaps"


def test_outline_numbers_headings_and_appends_open_findings():
    blocks = build_outline(
        make_report(), NUMBERED, SOURCES, open_findings=[make_finding(), make_finding("")]
    )
    labels = [b.label for b in blocks if isinstance(b, Heading)]
    assert labels[:2] == ["1. Key judgments", "2. Scope note"]
    assert labels[3] == "4. Capacity"
    assert labels[-1] == APPENDIX_TITLE  # the appendix is never numbered
    findings = blocks[-2]
    assert isinstance(findings, Bullets) and findings.role == "findings"
    assert findings.items == (
        Item("icd203.tc.8 (blocking): c9 has no evidence — Cite or remove."),
        Item("icd203.tc.8 (blocking): c9 has no evidence"),
    )
    assert blocks[-1] == Marking("UNCLASSIFIED")


def test_outline_without_open_findings_has_no_appendix():
    blocks = build_outline(make_report(), PACK, SOURCES, open_findings=[])
    assert all(not (isinstance(b, Heading) and b.text == APPENDIX_TITLE) for b in blocks)


def test_source_lines():
    entry = SourceEntry(source_id="src1", descriptor="open-source report", reliability_note="Now.")
    assert source_line(entry, SOURCES[0]) == "a.txt — open-source report; Now. (sha256 abcdef01)"
    cog = SourceEntry(source_id="src2", descriptor="translated document")
    assert (
        source_line(cog, SOURCES[1])
        == "b.json — translated document (sha256 ffffffff; Coglossa run run-42)"
    )
    missing = SourceEntry(source_id="src9", descriptor="social media post")
    assert source_line(missing, None) == "src9 — social media post (sha256 unknown)"
    no_run = SOURCES[1].model_copy(update={"provenance": {}})
    assert source_line(cog, no_run).endswith("Coglossa run unknown)")


def test_finding_line_with_and_without_recommendation():
    assert finding_line(make_finding()) == (
        "icd203.tc.8 (blocking): c9 has no evidence — Cite or remove."
    )
    assert finding_line(make_finding("")) == "icd203.tc.8 (blocking): c9 has no evidence"


def test_empty_lists_keep_headings_with_no_items():
    blocks = build_outline(empty_lists_report(), PACK, SOURCES)
    labels = [b.label for b in blocks if isinstance(b, Heading)]
    assert labels == [
        "Key judgments",
        "Scope note",
        "Sources",
        "Alternatives considered",
        "Gaps and indicators",
    ]
    empties = [b for b in blocks if isinstance(b, Bullets) and b.items == ()]
    assert [b.role for b in empties] == ["alternatives", "gaps"]


def test_unknown_section_names_are_ignored():
    pack = PACK.model_copy(
        update={
            "template": PACK.template.model_copy(
                update={"section_order": ["title", "annex_z", "key_judgments"]}
            )
        }
    )
    blocks = build_outline(make_report(), pack, SOURCES)
    assert [b.kind for b in blocks] == ["marking", "title", "heading", "bullets", "marking"]


def test_markdown_golden_and_determinism():
    md = render_markdown(
        make_report(status="findings_open", open_findings=["icd203.tc.8@2"]),
        NUMBERED,
        SOURCES,
        with_claim_ids=True,
        open_findings=[make_finding()],
    )
    check_golden("varna.md", md)
    assert render_markdown(make_report(), PACK, SOURCES) == render_markdown(
        make_report(), PACK, SOURCES
    )


def test_markdown_keeps_title_and_scope_note_text_literal():
    nasty = make_report().model_copy(
        update={"title": '<script>alert(1)</script> & "co"', "scope_note": "a < b & c"}
    )
    md = render_markdown(nasty, PACK, SOURCES)
    assert '# <script>alert(1)</script> & "co"\n' in md
    assert "\na < b & c\n" in md
    assert "&lt;" not in md and "&amp;" not in md and "&quot;" not in md


def test_degradations_come_before_the_open_findings_appendix_unnumbered():
    report = make_report(status="findings_open", degradations=["audit incomplete: boom"])
    blocks = build_outline(report, NUMBERED, SOURCES, open_findings=[make_finding()])
    labels = [b.label for b in blocks if isinstance(b, Heading)]
    assert labels[-2:] == [DEGRADATION_TITLE, APPENDIX_TITLE]
    assert blocks[-4] == Bullets((Item("audit incomplete: boom"),), "degradations")
    plain = build_outline(make_report(), PACK, SOURCES)
    assert all(not (isinstance(b, Heading) and b.text == DEGRADATION_TITLE) for b in plain)
    md = render_markdown(report, PACK, SOURCES)
    assert f"## {DEGRADATION_TITLE}\n\n- audit incomplete: boom\n" in md


def test_a_scanned_source_says_ocr_recovered_its_text_in_every_render():
    """CRL-95 (AC4): the sources section names the pages OCR read, in all three renders."""
    scanned = SOURCES[0].model_copy(update={"provenance": {"ocr_pages": [2, 5]}})
    one_page = SOURCES[0].model_copy(update={"provenance": {"ocr_pages": [1]}})
    entry = SourceEntry(source_id="src1", descriptor="open-source report")
    assert source_line(entry, scanned) == (
        "a.txt — open-source report (sha256 abcdef01; text recovered by OCR (2 pages))"
    )
    assert source_line(entry, one_page).endswith("; text recovered by OCR (1 page))")
    sources = [scanned, *SOURCES[1:]]
    note = "text recovered by OCR (2 pages)"
    assert note in render_markdown(make_report(), PACK, sources)
    assert note in render_html(make_report(), PACK, sources)
    text = "\n".join(
        p.text for p in Document(io.BytesIO(render_docx(make_report(), PACK, sources))).paragraphs
    )
    assert note in text
    assert "OCR" not in render_markdown(make_report(), PACK, SOURCES)
