import pytest
from pdfminer.pdfdocument import PDFPasswordIncorrect

from corelata.ingest import pdf as pdf_module
from corelata.ingest.base import IngestError
from corelata.ingest.pdf import NeedsOCRError, PdfIngestor
from corelata.ingest.registry import check_supported, ingest_file
from corelata.schema import BlockKind
from corelata.testing.pdf import make_pdf


def _write(tmp_path, pages, name="doc.pdf"):
    path = tmp_path / name
    path.write_bytes(make_pdf(pages))
    return path


def test_text_boxes_become_paragraphs_with_pages(tmp_path):
    path = _write(
        tmp_path,
        [
            ["Premier paragraphe.", "Une ligne qui conti-\nnue ici et\nse termine.", "Été (oui)."],
            [],
            ["12", "Page trois, bien-\nEntendu."],
        ],
    )
    doc = PdfIngestor().ingest(path)
    assert [(b.kind, b.text, b.provenance.page) for b in doc.blocks] == [
        (BlockKind.PARAGRAPH, "Premier paragraphe.", 1),
        (BlockKind.PARAGRAPH, "Une ligne qui continue ici et se termine.", 1),
        (BlockKind.PARAGRAPH, "Été (oui).", 1),
        (BlockKind.PARAGRAPH, "Page trois, bien- Entendu.", 3),
    ]
    assert [b.id for b in doc.blocks] == ["b1", "b2", "b3", "b4"]
    assert [b.provenance.index for b in doc.blocks] == [0, 1, 2, 3]
    assert doc.blocks[3].provenance.locator == "page 3"
    assert doc.format == "pdf"


def test_scanned_pages_stop_ingest_with_needs_ocr(tmp_path):
    path = _write(tmp_path, [["Du texte."], "image", ["Encore."], "image"], name="scan.pdf")
    with pytest.raises(NeedsOCRError) as e:
        PdfIngestor().ingest(path)
    assert e.value.pages == [2, 4]
    assert str(e.value) == (
        "scan.pdf needs OCR (needs_ocr): page(s) 2, 4 have no text layer; scanned pages are "
        "not supported yet, use a PDF with a text layer"
    )
    assert isinstance(e.value, IngestError)


@pytest.mark.parametrize("data", [b"this is not a pdf", b"%PDF-1.4\n%%EOF\n"])
def test_damaged_files_name_the_problem(tmp_path, data):
    path = tmp_path / "bad.pdf"
    path.write_bytes(data)
    with pytest.raises(IngestError, match=r"bad.pdf is not a readable PDF file \(\w+"):
        PdfIngestor().ingest(path)


def test_unreadable_reasons_are_one_line(tmp_path, monkeypatch):
    def damaged(*args, **kwargs):
        raise ValueError("bad xref\n   at   offset 9")

    monkeypatch.setattr(pdf_module, "extract_pages", damaged)
    with pytest.raises(IngestError) as e:
        PdfIngestor().ingest(_write(tmp_path, [["x"]], name="bad.pdf"))
    assert str(e.value) == "bad.pdf is not a readable PDF file (ValueError: bad xref at offset 9)"


def test_a_pdf_without_pages_is_unreadable(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_module, "extract_pages", lambda *a, **kw: iter(()))
    with pytest.raises(IngestError, match=r"not a readable PDF file \(it has no pages\)"):
        PdfIngestor().ingest(_write(tmp_path, [["x"]]))


def test_password_protected_pdfs_say_so(tmp_path, monkeypatch):
    def locked(*args, **kwargs):
        raise PDFPasswordIncorrect

    monkeypatch.setattr(pdf_module, "extract_pages", locked)
    with pytest.raises(IngestError, match="doc.pdf is password-protected"):
        PdfIngestor().ingest(_write(tmp_path, [["x"]]))


def test_registry_reads_pdf_and_lists_every_format(tmp_path):
    assert ingest_file(_write(tmp_path, [["Bonjour."]])).format == "pdf"
    bad = tmp_path / "a.odt"
    bad.write_text("x", encoding="utf-8")
    with pytest.raises(IngestError) as e:
        check_supported(bad)
    for ext in (".docx", ".htm", ".html", ".md", ".pdf", ".txt", ".xhtml"):
        assert ext in str(e.value)
