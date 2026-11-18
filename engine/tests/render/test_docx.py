import io
import struct
import time
import zipfile
import zlib

import pytest
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls
from docx.shared import Pt

from corelata.render.docx import RenderError, render_docx
from corelata.render.outline import DEGRADATION_TITLE
from tests.render.fixtures import (
    NUMBERED,
    PACK,
    SOURCES,
    empty_lists_report,
    make_finding,
    make_report,
)

H2 = [
    "Key judgments",
    "Scope note",
    "Sources",
    "Capacity",
    "Alternatives considered",
    "Gaps and indicators",
]


def _open(data: bytes):
    assert data[:2] == b"PK"
    return Document(io.BytesIO(data))


def _texts(doc, style: str) -> list[str]:
    return [p.text for p in doc.paragraphs if p.style.name == style]


def test_docx_structure_with_neutral_template():
    doc = _open(render_docx(make_report(), PACK, SOURCES))
    assert _texts(doc, "Heading 1") == ["Varna port"]
    assert _texts(doc, "Heading 2") == H2
    assert doc.paragraphs[0].style.name == "Heading 1"
    bullets = [p for p in doc.paragraphs if p.style.name == "List Bullet"]
    assert bullets[0].runs[0].text == "Moderate confidence. " and bullets[0].runs[0].bold
    assert bullets[0].text == "Moderate confidence. Capacity grew."
    assert [p.text for p in bullets[1:3]] == [
        "a.txt — open-source report; Current. (sha256 abcdef01)",
        "b.json — translated document; Tier B. (sha256 ffffffff; Coglossa run run-42)",
    ]
    assert "Grew 40 percent." in _texts(doc, "Normal")
    assert not any(r.font.superscript for p in doc.paragraphs for r in p.runs)
    section = doc.sections[0]
    assert section.header.paragraphs[0].text == "UNCLASSIFIED"
    assert section.footer.paragraphs[0].text == "UNCLASSIFIED"
    assert section.header.paragraphs[0].runs[0].bold
    assert doc.core_properties.title == "Varna port"


def test_docx_claim_ids_numbering_and_appendix():
    doc = _open(
        render_docx(
            make_report(status="findings_open", open_findings=["icd203.tc.8@2"]),
            NUMBERED,
            SOURCES,
            with_claim_ids=True,
            open_findings=[make_finding()],
        )
    )
    h2 = _texts(doc, "Heading 2")
    assert h2[0] == "1. Key judgments" and h2[3] == "4. Capacity"
    assert h2[-1] == "Audit findings open at delivery"
    sups = [r.text for p in doc.paragraphs for r in p.runs if r.font.superscript]
    assert sups == [" c1", " c1"]
    assert _texts(doc, "List Bullet")[-1] == (
        "icd203.tc.8 (blocking): c9 has no evidence — Cite or remove."
    )


def test_docx_reference_supplies_styles_and_loses_its_body(tmp_path):
    ref = Document()
    ref.add_paragraph("OLD BODY TEXT")
    ref.styles["Heading 2"].font.size = Pt(20)
    ref.sections[0].header.paragraphs[0].text = "OLD HEADER"
    path = tmp_path / "ref.docx"
    ref.save(str(path))
    doc = _open(render_docx(make_report(), PACK, SOURCES, reference=path))
    assert all(p.text != "OLD BODY TEXT" for p in doc.paragraphs)
    assert doc.styles["Heading 2"].font.size == Pt(20)
    assert _texts(doc, "Heading 2") == H2
    assert doc.sections[0].header.paragraphs[0].text == "UNCLASSIFIED"


def test_docx_missing_styles_fall_back_to_normal(tmp_path):
    ref = Document()
    ref.styles["Heading 2"].delete()
    ref.styles["List Bullet"].delete()
    path = tmp_path / "bare.docx"
    ref.save(str(path))
    doc = _open(render_docx(make_report(), PACK, SOURCES, reference=path))
    assert _texts(doc, "Heading 2") == []
    normals = [p for p in doc.paragraphs if p.style.name == "Normal"]
    headings = [p for p in normals if p.text in H2]
    assert [p.text for p in headings] == H2 and all(p.runs[0].bold for p in headings)
    assert "• Moderate confidence. Capacity grew." in [p.text for p in normals]


@pytest.mark.parametrize("content", [b"not a zip", b""])
def test_docx_unreadable_reference_is_a_render_error(tmp_path, content):
    path = tmp_path / "bad.docx"
    path.write_bytes(content)
    with pytest.raises(RenderError, match="cannot open docx reference"):
        render_docx(make_report(), PACK, SOURCES, reference=path)
    with pytest.raises(RenderError, match="cannot open docx reference"):
        render_docx(make_report(), PACK, SOURCES, reference=tmp_path / "absent.docx")


def test_docx_reference_that_is_a_zip_but_not_a_docx_is_a_render_error(tmp_path):
    path = tmp_path / "zip.docx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("x.txt", "hi")
    with pytest.raises(RenderError, match="cannot open docx reference"):
        render_docx(make_report(), PACK, SOURCES, reference=path)


def test_docx_keeps_text_literal_and_handles_empty_lists():
    nasty = make_report().model_copy(update={"title": '<b>&"x"'})
    doc = _open(render_docx(nasty, PACK, SOURCES))
    assert _texts(doc, "Heading 1") == ['<b>&"x"']
    doc = _open(render_docx(empty_lists_report(), PACK, SOURCES))
    assert _texts(doc, "Heading 2") == [h for h in H2 if h != "Capacity"]


def test_docx_is_deterministic_across_time(monkeypatch):
    a = render_docx(make_report(), PACK, SOURCES)
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + 7200)  # zipfile stamps entries from this
    b = render_docx(make_report(), PACK, SOURCES)
    assert a == b
    with zipfile.ZipFile(io.BytesIO(a)) as z:
        assert {i.date_time for i in z.infolist()} == {(1980, 1, 1, 0, 0, 0)}


def test_docx_marks_first_page_and_even_page_headers(tmp_path):
    ref = Document()
    ref.settings.odd_and_even_pages_header_footer = True
    section = ref.sections[0]
    section.different_first_page_header_footer = True
    section.first_page_header.paragraphs[0].text = "OLD FIRST"
    section.even_page_footer.paragraphs[0].text = "OLD EVEN"
    path = tmp_path / "ref.docx"
    ref.save(str(path))
    section = _open(render_docx(make_report(), PACK, SOURCES, reference=path)).sections[0]
    for part in (
        section.header,
        section.footer,
        section.first_page_header,
        section.first_page_footer,
        section.even_page_header,
        section.even_page_footer,
    ):
        assert [p.text for p in part.paragraphs] == ["UNCLASSIFIED"]
        assert part.paragraphs[0].runs[0].bold


def _png() -> bytes:
    def chunk(kind: bytes, body: bytes) -> bytes:
        crc = zlib.crc32(kind + body)
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00"))
        + chunk(b"IEND", b"")
    )


def test_docx_marking_replaces_header_text_but_keeps_logos(tmp_path):
    ref = Document()
    header = ref.sections[0].header
    header.paragraphs[0].add_run("OLD LEFT")
    header.paragraphs[0].add_run().add_picture(io.BytesIO(_png()))
    header.add_paragraph("OLD SECOND LINE")
    path = tmp_path / "logo.docx"
    ref.save(str(path))
    header = _open(render_docx(make_report(), PACK, SOURCES, reference=path)).sections[0].header
    # final review I2: the header is rebuilt as one paragraph (logo, then marking), so the
    # reference's second line no longer survives as an empty paragraph
    assert [p.text for p in header.paragraphs] == ["UNCLASSIFIED"]
    runs = header.paragraphs[0].runs
    assert "<w:drawing" in runs[0]._r.xml and runs[0].text == ""
    assert runs[-1].text == "UNCLASSIFIED" and runs[-1].bold
    assert header.paragraphs[0].alignment == WD_ALIGN_PARAGRAPH.CENTER


def _header_text(header) -> str:
    return "".join(t.text or "" for t in header._element.xpath(".//w:t"))


def _reference_with_header(tmp_path, *fragments: str):
    ref = Document()
    header = ref.sections[0].header
    header.is_linked_to_previous = False
    el = header._element
    for child in list(el):
        el.remove(child)
    for fragment in fragments:
        el.append(parse_xml(fragment))
    path = tmp_path / "ref.docx"
    ref.save(str(path))
    return path


W = nsdecls("w")
TEXT_BOX = (
    f"<w:p {nsdecls('w', 'wp', 'a')} "
    'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">'
    '<w:r><w:drawing><wp:inline><wp:extent cx="914400" cy="228600"/>'
    '<wp:docPr id="9" name="Banner"/><a:graphic><a:graphicData '
    'uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape"><wps:wsp>'
    "<wps:txbx><w:txbxContent><w:p><w:r><w:t>OLD BANNER</w:t></w:r></w:p></w:txbxContent>"
    "</wps:txbx></wps:wsp></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>"
)


@pytest.mark.parametrize(
    "fragment",
    [
        f"<w:sdt {W}><w:sdtContent><w:p><w:r><w:t>SECRET//NOFORN</w:t></w:r></w:p>"
        "</w:sdtContent></w:sdt>",
        f"<w:tbl {W}><w:tr><w:tc><w:p><w:r><w:t>SECRET//NOFORN</w:t></w:r></w:p></w:tc></w:tr>"
        "</w:tbl>",
        f'<w:p {W}><w:hyperlink w:anchor="x"><w:r><w:t>SECRET//NOFORN</w:t></w:r></w:hyperlink>'
        "</w:p>",
    ],
    ids=["content-control", "table", "hyperlink"],
)
def test_docx_header_text_in_any_container_is_replaced_by_the_marking(tmp_path, fragment):
    path = _reference_with_header(tmp_path, fragment)  # block-level only: no paragraph of its own
    header = _open(render_docx(make_report(), PACK, SOURCES, reference=path)).sections[0].header
    assert _header_text(header) == "UNCLASSIFIED"
    assert [p.text for p in header.paragraphs] == ["UNCLASSIFIED"]


def test_docx_header_text_box_is_not_kept_as_a_logo(tmp_path):
    path = _reference_with_header(tmp_path, TEXT_BOX)
    header = _open(render_docx(make_report(), PACK, SOURCES, reference=path)).sections[0].header
    assert "OLD BANNER" not in header._element.xml
    assert _header_text(header) == "UNCLASSIFIED"
    assert "<w:drawing" not in header._element.xml


def test_docx_zip_entries_record_a_fixed_creator_system():
    with zipfile.ZipFile(io.BytesIO(render_docx(make_report(), PACK, SOURCES))) as z:
        assert {i.create_system for i in z.infolist()} == {3}


def test_docx_logo_run_loses_its_text_and_keeps_the_header_style(tmp_path):
    ref = Document()
    header = ref.sections[0].header
    run = header.paragraphs[0].add_run("CAPTION IN THE LOGO RUN")
    run.add_picture(io.BytesIO(_png()))
    path = tmp_path / "logo.docx"
    ref.save(str(path))
    header = _open(render_docx(make_report(), PACK, SOURCES, reference=path)).sections[0].header
    assert _header_text(header) == "UNCLASSIFIED"
    assert "<w:drawing" in header.paragraphs[0].runs[0]._r.xml
    assert header.paragraphs[0].style.name == "Header"


MC = 'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"'
VML = 'xmlns:v="urn:schemas-microsoft-com:vml"'  # python-docx's nsmap has no `v` prefix
ALTERNATE_LOGO = (
    f"<w:p {nsdecls('w', 'wp', 'a', 'pic', 'r')} {MC} {VML}>"
    "<w:r><w:rPr><w:b/></w:rPr><w:t>OLD MARKING</w:t>"
    '<mc:AlternateContent><mc:Choice Requires="wps"><w:drawing><wp:inline>'
    '<wp:extent cx="914400" cy="228600"/><wp:docPr id="7" name="Logo"/><a:graphic>'
    '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
    '<pic:pic><pic:blipFill><a:blip r:embed="rId9"/></pic:blipFill></pic:pic>'
    "</a:graphicData></a:graphic></wp:inline></w:drawing></mc:Choice>"
    '<mc:Fallback><w:pict><v:shape><v:imagedata r:id="rId9"/></v:shape></w:pict></mc:Fallback>'
    "</mc:AlternateContent></w:r></w:p>"
)


def test_docx_alternate_content_logo_survives_the_marking(tmp_path):
    path = _reference_with_header(tmp_path, ALTERNATE_LOGO)
    header = _open(render_docx(make_report(), PACK, SOURCES, reference=path)).sections[0].header
    xml = header._element.xml
    assert "OLD MARKING" not in xml and _header_text(header) == "UNCLASSIFIED"
    assert "mc:AlternateContent" in xml and "<pic:pic" in xml and "<w:drawing" in xml
    assert [p.text for p in header.paragraphs] == ["UNCLASSIFIED"]


def test_docx_lists_degradations():
    report = make_report(status="findings_open", degradations=["audit incomplete: boom"])
    doc = _open(render_docx(report, PACK, SOURCES))
    assert _texts(doc, "Heading 2")[-1] == DEGRADATION_TITLE
    assert _texts(doc, "List Bullet")[-1] == "audit incomplete: boom"
