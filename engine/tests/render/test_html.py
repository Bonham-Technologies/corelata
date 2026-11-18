import re
from pathlib import Path

from lxml import html as lxml_html

from corelata.render import html as html_module
from corelata.render.html import REPORT_CSS, render_html
from corelata.render.outline import DEGRADATION_TITLE
from tests.render.fixtures import (
    NUMBERED,
    PACK,
    SOURCES,
    empty_lists_report,
    make_finding,
    make_report,
)
from tests.render.test_outline import check_golden


def _doc(text: str):
    return lxml_html.fromstring(text)


def test_html_structure_and_provenance_attributes():
    out = render_html(make_report(run_id="r1", status="clean"), PACK, SOURCES)
    assert out.startswith("<!DOCTYPE html>")
    doc = _doc(out)
    assert doc.xpath("//title/text()") == ["Varna port"]
    assert doc.xpath("//h1/text()") == ["Varna port"]
    assert doc.xpath("//article/section/h2/text()") == [
        "Key judgments",
        "Scope note",
        "Sources",
        "Capacity",
        "Alternatives considered",
        "Gaps and indicators",
    ]
    markings = doc.xpath("//article/p[contains(@class, 'marking')]")
    assert [m.text for m in markings] == ["UNCLASSIFIED", "UNCLASSIFIED"]
    assert markings[0].get("class") == "marking" and markings[1].get("class") == "marking bottom"
    assert doc.xpath("//ul[@class='key_judgments']/li/@data-claim-ids") == ["c1"]
    assert doc.xpath("//ul[@class='key_judgments']/li/strong/text()") == ["Moderate confidence."]
    assert doc.xpath("//section[h2='Capacity']/p/@data-claim-ids") == ["c1"]
    assert doc.xpath("//section[h2='Scope note']/p/@data-claim-ids") == [""]
    assert doc.xpath("//ul[@class='sources']/li/text()") == [
        "a.txt — open-source report; Current. (sha256 abcdef01)",
        "b.json — translated document; Tier B. (sha256 ffffffff; Coglossa run run-42)",
    ]
    assert doc.xpath("//sup") == []
    assert doc.xpath("//section[@class='appendix']") == []
    footer = doc.xpath("//footer[@class='meta']")[0].text_content()
    assert "run r1" in footer and "icd203-base" in footer and "clean" in footer


def test_html_claim_ids_numbering_and_appendix():
    out = render_html(
        make_report(status="findings_open", open_findings=["icd203.tc.8@2"]),
        NUMBERED,
        SOURCES,
        with_claim_ids=True,
        open_findings=[make_finding()],
    )
    doc = _doc(out)
    h2 = doc.xpath("//h2/text()")
    assert h2[0] == "1. Key judgments" and h2[3] == "4. Capacity"
    assert h2[-1] == "Audit findings open at delivery"
    assert doc.xpath("//sup[@class='claim-ids']/text()") == ["c1", "c1"]
    assert doc.xpath("//section[@class='appendix']/ul[@class='findings']/li/text()") == [
        "icd203.tc.8 (blocking): c9 has no evidence — Cite or remove."
    ]
    check_golden("varna.html", out)


def test_html_is_self_contained():
    out = render_html(make_report(), PACK, SOURCES)
    assert not re.search(r"https?://|<link|<script|@import|url\(", out)
    assert "<style>" in out


def test_the_one_style_element_is_report_css_byte_for_byte_and_nothing_else_is_inline():
    css = (Path(html_module.__file__).parent / "templates" / "report.css").read_bytes()
    assert b"\r" not in css  # the browser parses CRLF as LF in the srcdoc: .gitattributes pins LF
    assert REPORT_CSS.encode("utf-8") == css  # what the web build hashes (CRL-23)
    for with_claim_ids in (False, True):
        out = render_html(
            make_report(), PACK, SOURCES, with_claim_ids=with_claim_ids, open_findings=[]
        )
        assert out.count("<style") == 1 and f"<style>{REPORT_CSS}</style>" in out
        assert '"Times New Roman"' in out  # not escaped
        doc = _doc(out)
        assert doc.xpath("//*[@style]") == []  # no inline style attributes to allow


def test_html_escapes_report_text():
    nasty = make_report().model_copy(
        update={"title": '<script>alert(1)</script> & "co"', "scope_note": "a < b & c"}
    )
    out = render_html(nasty, PACK, SOURCES)
    assert "<script>alert(1)</script>" not in out
    assert "&lt;script&gt;alert(1)&lt;/script&gt; &amp; " in out
    assert "a &lt; b &amp; c" in out
    doc = _doc(out)
    assert doc.xpath("//h1/text()") == ['<script>alert(1)</script> & "co"']


def test_html_empty_lists_keep_headings():
    doc = _doc(render_html(empty_lists_report(), PACK, SOURCES))
    assert (
        doc.xpath("//ul[@class='alternatives']")
        and doc.xpath("//ul[@class='alternatives']/li") == []
    )
    assert doc.xpath("//ul[@class='gaps']/li") == []
    assert "Capacity" not in doc.xpath("//h2/text()")


def test_html_escapes_a_degradation_line():
    report = make_report(status="findings_open", degradations=["audit incomplete: <b>&"])
    out = render_html(report, PACK, SOURCES)
    assert "audit incomplete: &lt;b&gt;&amp;" in out and "<b>&" not in out
    assert _doc(out).xpath("//ul[@class='degradations']/li/text()") == ["audit incomplete: <b>&"]


def test_html_is_deterministic():
    a = render_html(make_report(), PACK, SOURCES)
    assert a == render_html(make_report(), PACK, SOURCES)


def test_html_puts_degradations_in_an_appendix_section():
    report = make_report(status="findings_open", degradations=["conveyance skipped: boom"])
    out = render_html(report, PACK, SOURCES)
    doc = _doc(out)
    assert doc.xpath("//section[@class='appendix']/h2/text()") == [DEGRADATION_TITLE]
    assert doc.xpath("//ul[@class='degradations']/li/text()") == ["conveyance skipped: boom"]
    assert "status findings_open" in out
