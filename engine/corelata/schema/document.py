"""Source documents after ingestion (copied from Coglossa; segmentation dropped)."""

from enum import StrEnum

from pydantic import BaseModel


class BlockKind(StrEnum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    BREAK = "break"  # scene/section break marker; carries no translatable text
    LIST_ITEM = "list_item"
    TABLE_CELL = "table_cell"
    FOOTNOTE = "footnote"


class Provenance(BaseModel):
    source_path: str
    index: int  # ordinal of the block within the source file
    page: int | None = None
    locator: str | None = None  # format-specific, e.g. "table 2 row 1 col 3"


class Block(BaseModel):
    id: str  # "b1", "b2", … in reading order
    kind: BlockKind
    text: str
    provenance: Provenance


class SourceDocument(BaseModel):
    source_path: str
    format: str
    sha256: str
    blocks: list[Block]
