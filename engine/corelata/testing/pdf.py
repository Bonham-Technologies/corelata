"""Builds small PDFs for tests: text pages (Helvetica, WinAnsi encoding), image-only
"scanned" pages and blank pages. Paragraphs are drawn 40 points apart, so pdfminer sees
each one as its own text box; "\\n" inside a paragraph starts a new line 14 points down."""


def _escape(text: str) -> bytes:
    raw = text.encode("cp1252")
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _text_stream(paragraphs: list[str]) -> bytes:
    out = [b"BT /F1 12 Tf 14 TL"]
    y = 760
    for paragraph in paragraphs:
        lines = paragraph.split("\n")
        out.append(b"1 0 0 1 72 %d Tm" % y)
        for i, line in enumerate(lines):
            if i:
                out.append(b"T*")
            out.append(b"(" + _escape(line) + b") Tj")
        y -= 14 * len(lines) + 40
    out.append(b"ET")
    return b"\n".join(out)


_IMAGE_PAGE = b"q 200 0 0 200 100 400 cm /Im1 Do Q"


def make_pdf(pages: list[list[str] | str]) -> bytes:
    """pages: per page, a list of paragraphs, [] for a blank page, or "image" for a page
    that shows a picture and has no text (a scanned page)."""
    objects: list[bytes] = [b"", b""]  # 1: catalog, 2: page tree (filled in at the end)
    objects.append(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
    )
    font = len(objects)
    objects.append(
        b"<< /Type /XObject /Subtype /Image /Width 1 /Height 1 /ColorSpace /DeviceGray "
        b"/BitsPerComponent 8 /Length 1 >>\nstream\n\x80\nendstream"
    )
    image = len(objects)
    kids = []
    for page in pages:
        content = _IMAGE_PAGE if page == "image" else _text_stream(list(page))
        objects.append(b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream")
        stream = len(objects)
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font "
            b"<< /F1 %d 0 R >> /XObject << /Im1 %d 0 R >> >> /Contents %d 0 R >>"
            % (font, image, stream)
        )
        kids.append(len(objects))
    objects[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (
        b" ".join(b"%d 0 R" % k for k in kids),
        len(kids),
    )
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)
