"""Source documents after ingestion (copied from Coglossa; segmentation dropped)."""

from enum import StrEnum

from pydantic import BaseModel, Field


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
    ocr: bool = False  # the text was recovered by OCR from a scanned page (CRL-95)
    ocr_confidence: float | None = None  # mean Tesseract word confidence, 0 to 100


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
    # CRL-96: what the file says about itself, as hints for the report's source entry: "date"
    # (when it was issued, ISO 8601 where the file gives one) and "origin" (its author or
    # publisher). They become the source's provenance.
    meta: dict[str, str] = Field(default_factory=dict)
