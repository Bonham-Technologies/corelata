import os
import shutil

import pytest
from pdfminer.pdfdocument import PDFPasswordIncorrect

from corelata.ingest import ocr
from corelata.ingest import pdf as pdf_module
from corelata.ingest.base import IngestError
from corelata.ingest.ocr import OcrSettings
from corelata.ingest.pdf import NeedsOCRError, OcrMissingError, PdfIngestor
from corelata.ingest.registry import check_supported, ingest_file
from corelata.schema import BlockKind
from corelata.testing.pdf import Scan, make_pdf
from tests.ingest.test_ocr import _word, tsv


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


# ---------------------------------------------------------------- OCR (CRL-95)

SCANNED_AND_TEXT = [
    Scan(("The port of Varna handled more containers in 2026.", "A second paragraph.", "7")),
    ["Page two has a text layer."],
]
SCANNED_TSV = tsv(
    _word(1, 1, 1, 1, "90", "The"),
    _word(1, 1, 1, 2, "80", "conti-"),
    _word(1, 1, 2, 1, "70", "nue"),
    _word(2, 1, 1, 1, "99", "7"),  # a bare page number is dropped, as on a text page
)


def _ocr_stub(monkeypatch, tsv_text=SCANNED_TSV):
    calls = []

    def read(image, languages):
        calls.append(languages)
        return tsv_text

    monkeypatch.setattr(ocr, "tesseract_path", lambda: "/usr/bin/tesseract")
    monkeypatch.setattr(ocr, "DPI", 20)
    monkeypatch.setattr(ocr, "read_image", read)
    return calls


def test_scanned_pages_are_read_by_ocr_and_marked_in_provenance(tmp_path, monkeypatch):
    """AC1: one scanned page and one text page, under ocr: auto."""
    calls = _ocr_stub(monkeypatch)
    path = _write(tmp_path, SCANNED_AND_TEXT, name="scan.pdf")
    doc = PdfIngestor(OcrSettings(languages=("eng", "fra"))).ingest(path)
    assert [(b.text, b.provenance.page, b.provenance.ocr) for b in doc.blocks] == [
        ("The continue", 1, True),
        ("Page two has a text layer.", 2, False),
    ]
    assert doc.blocks[0].provenance.ocr_confidence == 80.0
    assert doc.blocks[1].provenance.ocr_confidence is None
    assert [b.provenance.index for b in doc.blocks] == [0, 1]
    assert doc.blocks[0].provenance.locator == "page 1"
    assert calls == [("eng", "fra")]  # only the scanned page


def test_ocr_off_still_stops_with_needs_ocr(tmp_path):
    path = _write(tmp_path, SCANNED_AND_TEXT, name="scan.pdf")
    for ingestor in (PdfIngestor(), PdfIngestor(None)):
        with pytest.raises(NeedsOCRError) as e:
            ingestor.ingest(path)
        assert str(e.value) == (
            "scan.pdf needs OCR (needs_ocr): page(s) 1 have no text layer; scanned pages are "
            "not supported yet, use a PDF with a text layer"
        )


def test_ocr_without_tesseract_says_the_server_lacks_it(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr, "tesseract_path", lambda: None)
    path = _write(tmp_path, SCANNED_AND_TEXT, name="scan.pdf")
    with pytest.raises(OcrMissingError) as e:
        PdfIngestor(OcrSettings()).ingest(path)
    assert e.value.pages == [1] and isinstance(e.value, NeedsOCRError)
    assert str(e.value) == (
        "scan.pdf needs OCR (needs_ocr): page(s) 1 have no text layer, and the text recognition "
        "program (tesseract) is not installed on the server; ask your administrator to run "
        "corelata doctor"
    )


def test_an_ocr_failure_is_an_ingest_error_naming_the_page(tmp_path, monkeypatch):
    _ocr_stub(monkeypatch)

    def read(image, languages):
        raise ocr.OcrError("tesseract failed: Failed loading language 'xx'")

    monkeypatch.setattr(ocr, "read_image", read)
    path = _write(tmp_path, SCANNED_AND_TEXT, name="scan.pdf")
    with pytest.raises(IngestError) as e:
        PdfIngestor(OcrSettings(languages=("xx",))).ingest(path)
    assert str(e.value) == (
        "scan.pdf: text recognition failed on page 1: tesseract failed: Failed loading "
        "language 'xx'"
    )


def test_a_scan_ocr_finds_nothing_in_is_skipped_like_a_blank_page(tmp_path, monkeypatch):
    _ocr_stub(monkeypatch, tsv())
    path = _write(tmp_path, SCANNED_AND_TEXT)
    doc = PdfIngestor(OcrSettings()).ingest(path)
    assert [b.text for b in doc.blocks] == ["Page two has a text layer."]
    only_scan = _write(tmp_path, [SCANNED_AND_TEXT[0]], name="blank-scan.pdf")
    with pytest.raises(IngestError, match="blank-scan.pdf contains no usable text"):
        ingest_file(only_scan, ocr=OcrSettings())


# CI installs tesseract-ocr (ci.yml, engine job), so this never skips there.
_NO_TESSERACT = shutil.which("tesseract") is None and not os.environ.get("CI")


@pytest.mark.skipif(_NO_TESSERACT, reason="tesseract is not installed (CI installs it)")
def test_real_tesseract_reads_the_scanned_page(tmp_path):
    path = _write(tmp_path, SCANNED_AND_TEXT, name="scan.pdf")
    doc = ingest_file(path, ocr=OcrSettings())
    ocr_blocks = [b for b in doc.blocks if b.provenance.ocr]
    assert [b.text for b in ocr_blocks] == [
        "The port of Varna handled more containers in 2026.",
        "A second paragraph.",
    ]
    assert all(b.provenance.page == 1 and b.provenance.ocr_confidence > 80 for b in ocr_blocks)
    assert doc.blocks[-1].text == "Page two has a text layer."
    assert not doc.blocks[-1].provenance.ocr
