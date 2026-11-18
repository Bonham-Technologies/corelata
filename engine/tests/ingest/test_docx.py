import docx
import pytest

from corelata.ingest.base import IngestError
from corelata.ingest.docx import DocxIngestor
from corelata.schema import BlockKind


def test_docx_in_document_order(tmp_path):
    d = docx.Document()
    d.add_heading("Report", level=1)
    d.add_paragraph("Intro paragraph.")
    d.add_paragraph("")  # empty paragraphs are skipped
    d.add_paragraph("A bullet", style="List Bullet")
    table = d.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Left"
    table.cell(0, 1).text = ""
    d.add_paragraph("* * *")
    d.add_paragraph("After the table.")
    path = tmp_path / "r.docx"
    d.save(path)

    doc = DocxIngestor().ingest(path)
    assert doc.format == "docx"
    assert [(b.kind, b.text) for b in doc.blocks] == [
        (BlockKind.HEADING, "Report"),
        (BlockKind.PARAGRAPH, "Intro paragraph."),
        (BlockKind.LIST_ITEM, "A bullet"),
        (BlockKind.TABLE_CELL, "Left"),
        (BlockKind.BREAK, "* * *"),
        (BlockKind.PARAGRAPH, "After the table."),
    ]
    assert doc.blocks[3].provenance.locator == "table 1 row 1 col 1"


def test_merged_cells_are_not_duplicated(tmp_path):
    d = docx.Document()
    table = d.add_table(rows=1, cols=2)
    merged = table.cell(0, 0).merge(table.cell(0, 1))
    merged.text = "Spans both"
    path = tmp_path / "m.docx"
    d.save(path)
    assert [b.text for b in DocxIngestor().ingest(path).blocks] == ["Spans both"]


def test_corrupt_docx_is_ingest_error(tmp_path):
    path = tmp_path / "broken.docx"
    path.write_bytes(b"not a zip")
    with pytest.raises(IngestError, match="broken.docx is not a readable DOCX"):
        DocxIngestor().ingest(path)
