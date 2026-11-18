"""DOCX render (spec §9) with python-docx. A profile's reference document supplies styles,
headers, footers and page setup; otherwise python-docx's neutral default does. The reference's
own body content is dropped and the report appended, so a customer's template can carry a
logo in the header and the house heading styles without any text of its own leaking in."""

import io
import zipfile
from pathlib import Path

from docx import Document
from docx.document import Document as DocxDocument
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.section import _Footer, _Header
from docx.text.paragraph import Paragraph
from lxml import etree

from corelata.render.outline import Bullets, Heading, Marking, Para, Title, build_outline
from corelata.schema import Finding, Report, Source
from corelata.standards.loader import DOCX_OPEN_ERRORS
from corelata.standards.schema import ResolvedPack


class RenderError(ValueError):
    """A render input the engine cannot use, e.g. an unreadable reference document."""


def _open(reference: Path | None) -> DocxDocument:
    if reference is None:
        return Document()
    try:
        doc = Document(str(reference))
    except DOCX_OPEN_ERRORS as e:
        raise RenderError(f"cannot open docx reference '{reference}': {e}") from e
    body = doc.element.body
    for child in list(body):
        if child.tag != qn("w:sectPr"):
            body.remove(child)
    return doc


def _styled(doc: DocxDocument, style: str) -> Paragraph:
    """A paragraph in `style`, or a Normal one when the reference lacks that style."""
    try:
        return doc.add_paragraph(style=style)
    except KeyError:
        return doc.add_paragraph()


def _heading(doc: DocxDocument, text: str, level: int) -> None:
    style = f"Heading {level}"
    p = _styled(doc, style)
    run = p.add_run(text)
    if p.style.name != style:
        run.bold = True


def _ids(p: Paragraph, claim_ids: tuple[str, ...], on: bool) -> None:
    if on and claim_ids:
        p.add_run(" " + ", ".join(claim_ids)).font.superscript = True


_NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
    "v": "urn:schemas-microsoft-com:vml",
}
_RUNS = etree.XPath(".//w:r[not(ancestor::w:txbxContent)]", namespaces=_NS)
_IMAGE = etree.XPath(".//pic:pic | .//a:blip | .//v:imagedata", namespaces=_NS)
_TEXT_BOX = etree.XPath(".//w:txbxContent", namespaces=_NS)
_FIRST_PPR = etree.XPath("./w:p[1]/w:pPr", namespaces=_NS)


def _logo_runs(root: etree._Element) -> list[etree._Element]:
    """The part's picture runs (logos), stripped of any text; text boxes are never logos. A run
    child stays when it is the run's properties or when it holds a picture, whatever wraps it
    (`w:drawing`, `w:pict`, `mc:AlternateContent`, `w:object`)."""
    runs = [r for r in _RUNS(root) if _IMAGE(r) and not _TEXT_BOX(r)]
    for run in runs:
        for child in list(run):
            if child.tag != qn("w:rPr") and not _IMAGE(child):
                run.remove(child)
    return runs


def _mark_part(part: _Header | _Footer, text: str) -> None:
    """Replace a header or footer's content with one centred paragraph: its picture runs, then
    the marking in bold. Text anywhere else (content controls, tables, hyperlinks, fields, text
    boxes) goes, so no stale banner from the reference can sit beside the marking."""
    root = part._element
    logos = _logo_runs(root)
    ppr = _FIRST_PPR(root)
    for child in list(root):  # a header or footer holds only block content: drop all of it
        root.remove(child)
    p = part.add_paragraph()
    if ppr:
        p._p.insert(0, ppr[0])  # keep the template's paragraph style for the header line
    for run in logos:
        p._p.append(run)
    p.add_run(text).bold = True
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER


def _mark(doc: DocxDocument, text: str) -> None:
    """Set the handling marking, bold and centred, in every header and footer part."""
    even = doc.settings.odd_and_even_pages_header_footer
    for section in doc.sections:
        parts = [section.header, section.footer]
        if section.different_first_page_header_footer:
            parts += [section.first_page_header, section.first_page_footer]
        if even:
            parts += [section.even_page_header, section.even_page_footer]
        for part in parts:
            part.is_linked_to_previous = False
            _mark_part(part, text)


_ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)


def _reproducible(data: bytes) -> bytes:
    """Rewrite the package with a fixed timestamp and creator system on every entry, keeping
    entry order, so the same inputs give the same bytes whenever and wherever they are rendered."""
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as src, zipfile.ZipFile(out, "w") as dst:
        for info in src.infolist():
            fixed = zipfile.ZipInfo(info.filename, _ZIP_EPOCH)
            fixed.compress_type = zipfile.ZIP_DEFLATED
            fixed.external_attr = info.external_attr
            fixed.create_system = 3  # Unix, whatever platform renders it
            dst.writestr(fixed, src.read(info))
    return out.getvalue()


def render_docx(
    report: Report,
    pack: ResolvedPack,
    sources: list[Source],
    *,
    with_claim_ids: bool = False,
    open_findings: list[Finding] | None = None,
    reference: Path | None = None,
) -> bytes:
    doc = _open(reference)
    doc.core_properties.title = report.title
    marked = False
    for block in build_outline(report, pack, sources, open_findings=open_findings):
        match block:
            case Marking(text):
                if not marked:  # the marking lives in the header and footer, set once
                    _mark(doc, text)
                    marked = True
            case Title(text):
                _heading(doc, text, 1)
            case Heading():
                _heading(doc, block.label, 2)
            case Para(text, claim_ids):
                p = doc.add_paragraph()
                p.add_run(text)
                _ids(p, claim_ids, with_claim_ids)
            case Bullets(items):
                for item in items:
                    p = _styled(doc, "List Bullet")
                    if p.style.name != "List Bullet":
                        p.add_run("• ")
                    if item.lead:
                        p.add_run(f"{item.lead} ").bold = True
                    p.add_run(item.text)
                    _ids(p, item.claim_ids, with_claim_ids)
    buf = io.BytesIO()
    doc.save(buf)
    return _reproducible(buf.getvalue())
