"""DOCX ingestion in true document order (paragraphs and tables interleaved).
Footnotes, headers and text boxes are not read in M1. Text hidden from the reader (`w:vanish`,
set on the run, its character style or its paragraph's style) becomes a block of its own marked
hidden, after the paragraph or cell it sits in (CRL-137): the trace keeps it and no model reads
it."""

from pathlib import Path
from typing import Any

import docx
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.table import Table
from docx.text.paragraph import Paragraph
from docx.text.run import Run

from corelata.ingest.base import IngestError, file_sha256, is_scene_break, make_blocks, source_meta
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


def _style_hidden(style: Any) -> bool | None:
    """The `w:vanish` a style sets, directly or through the styles it is based on."""
    while style is not None:
        hidden = style.font.hidden
        if hidden is not None:
            return hidden
        style = style.base_style
    return None


def _split(paragraph: Paragraph) -> tuple[str, str]:
    """The paragraph's visible text, as `Paragraph.text` reads it, and its hidden text: each run
    of consecutive hidden runs, joined by spaces."""
    by_style = _style_hidden(paragraph.style)
    visible: list[str] = []
    hidden: list[list[str]] = []
    was_hidden = False
    for r in paragraph._p.xpath("w:r | w:hyperlink/w:r"):
        run = Run(r, paragraph)
        flag = run.font.hidden
        if flag is None and r.rPr is not None and r.rPr.rStyle is not None:
            flag = _style_hidden(run.style)
        if flag is None:
            flag = by_style
        if flag:
            if not was_hidden:
                hidden.append([])
            hidden[-1].append(r.text)
        else:
            visible.append(r.text)
        was_hidden = bool(flag)
    groups = ("".join(h).strip() for h in hidden)
    return "".join(visible), " ".join(g for g in groups if g)


class _Items:
    """Items in order, with the indexes of the hidden ones."""

    def __init__(self) -> None:
        self.items: list[Item] = []
        self.hidden: set[int] = set()

    def add(self, kind: BlockKind, text: str, locator: str | None, hidden_text: str) -> None:
        if text:
            self.items.append((kind, text, locator))
        if hidden_text:
            self.hidden.add(len(self.items))
            self.items.append((BlockKind.PARAGRAPH, hidden_text, locator))


def _table_items(table: Table, table_no: int, out: _Items) -> None:
    seen: list[object] = []  # keep references: lxml proxies are only stable while referenced
    for r, row in enumerate(table.rows, start=1):
        for c, cell in enumerate(row.cells, start=1):
            tc = cell._tc
            if any(tc is s for s in seen):  # merged cells repeat the same underlying element
                continue
            seen.append(tc)
            parts = [_split(p) for p in cell.paragraphs]
            text = "\n".join(v for v, _ in parts).strip()
            hidden = " ".join(h for _, h in parts if h)
            out.add(BlockKind.TABLE_CELL, text, f"table {table_no} row {r} col {c}", hidden)


# python-docx's own template says it wrote the file; its dates are the template's, not the
# document's, so a file that still carries them gives no hints.
_LIBRARY_AUTHOR = "python-docx"


def _read(props: Any, name: str) -> Any:
    """One core property, or None when the file's value is one python-docx cannot read (an
    empty date element raises TypeError, a date at the calendar's edge OverflowError): a hint is
    never worth refusing the file over."""
    try:
        return getattr(props, name)
    except Exception:  # python-docx raises several unrelated types for bad values
        return None


def core_meta(props: Any) -> dict[str, str]:
    """The last-saved (or created) date and the author from core properties, as ingest hints."""
    author = _read(props, "author")
    if author == _LIBRARY_AUTHOR:
        return {}
    when = _read(props, "modified") or _read(props, "created")
    return source_meta(
        when.date().isoformat() if when else None, author if isinstance(author, str) else None
    )


def docx_meta(document: Any) -> dict[str, str]:
    """The file's last-saved (or created) date and its author, from the core properties, as
    ingest hints (CRL-96). A file without a core-properties part gives none: python-docx would
    make up a default one dated now."""
    try:
        document.part.package.part_related_by(RT.CORE_PROPERTIES)
    except (KeyError, ValueError):
        return {}
    return core_meta(document.core_properties)


class DocxIngestor:
    format = "docx"
    extensions = (".docx",)

    def ingest(self, path: Path) -> SourceDocument:
        try:
            document = docx.Document(str(path))
        except Exception as e:  # python-docx raises several unrelated types for bad files
            raise IngestError(f"{path.name} is not a readable DOCX file ({e})") from e
        out = _Items()
        table_no = 0
        for part in document.iter_inner_content():
            if isinstance(part, Table):
                table_no += 1
                _table_items(part, table_no, out)
                continue
            visible, hidden = _split(part)
            text = visible.strip()
            style = part.style.name if part.style is not None and text else ""
            out.add(_paragraph_kind(style, text), text, None, hidden)
        return SourceDocument(
            source_path=str(path),
            format=self.format,
            sha256=file_sha256(path),
            blocks=make_blocks(str(path), out.items, out.hidden),
            meta=docx_meta(document),
        )
