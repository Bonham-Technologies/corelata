"""DOCX ingestion in true document order (paragraphs and tables interleaved).
Footnotes, headers and text boxes are not read in M1."""

from pathlib import Path

import docx
from docx.table import Table

from corelata.ingest.base import IngestError, file_sha256, is_scene_break, make_blocks
from corelata.schema import BlockKind, SourceDocument

Item = tuple[BlockKind, str, str | None]


def _paragraph_kind(style_name: str, text: str) -> BlockKind:
    style = style_name.lower()
    if style.startswith(("heading", "title")):
        return BlockKind.HEADING
    if is_scene_break(text):
        return BlockKind.BREAK
    if style.startswith("list"):
        return BlockKind.LIST_ITEM
    return BlockKind.PARAGRAPH


def _table_items(table: Table, table_no: int) -> list[Item]:
    items: list[Item] = []
    seen: list[object] = []  # keep references: lxml proxies are only stable while referenced
    for r, row in enumerate(table.rows, start=1):
        for c, cell in enumerate(row.cells, start=1):
            tc = cell._tc
            if any(tc is s for s in seen):  # merged cells repeat the same underlying element
                continue
            seen.append(tc)
            text = cell.text.strip()
            if text:
                items.append((BlockKind.TABLE_CELL, text, f"table {table_no} row {r} col {c}"))
    return items


class DocxIngestor:
    format = "docx"
    extensions = (".docx",)

    def ingest(self, path: Path) -> SourceDocument:
        try:
            document = docx.Document(str(path))
        except Exception as e:  # python-docx raises several unrelated types for bad files
            raise IngestError(f"{path.name} is not a readable DOCX file ({e})") from e
        items: list[Item] = []
        table_no = 0
        for part in document.iter_inner_content():
            if isinstance(part, Table):
                table_no += 1
                items.extend(_table_items(part, table_no))
                continue
            text = part.text.strip()
            if text:
                style = part.style.name if part.style is not None else ""
                items.append((_paragraph_kind(style, text), text, None))
        return SourceDocument(
            source_path=str(path),
            format=self.format,
            sha256=file_sha256(path),
            blocks=make_blocks(str(path), items),
        )
