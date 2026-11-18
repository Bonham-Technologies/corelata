"""Blocks become addressable source units; a UnitIndex answers unit refs (spec §5.2)."""

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from corelata.ingest.ocr import OcrSettings
from corelata.ingest.registry import ingest_file
from corelata.schema import (
    BlockKind,
    Source,
    SourceDocument,
    SourceKind,
    SourceUnit,
    split_ref,
    unit_ref,
)


def _locator(page: int | None, locator: str | None, index: int) -> str:
    parts = []
    if page is not None:
        parts.append(f"page {page}")
    if locator:
        parts.append(locator)
    return " / ".join(parts) if parts else f"para {index + 1}"


def units_from_document(doc: SourceDocument) -> list[SourceUnit]:
    units: list[SourceUnit] = []
    for block in doc.blocks:
        if block.kind is BlockKind.BREAK:
            continue
        p = block.provenance
        units.append(
            SourceUnit(
                id=f"u{len(units) + 1}",
                text=block.text,
                locator=_locator(p.page, p.locator, p.index),
                kind=block.kind,
                meta={"ocr": True, "ocr_confidence": p.ocr_confidence} if p.ocr else {},
            )
        )
    return units


def ocr_provenance(doc: SourceDocument, ocr: OcrSettings | None) -> dict[str, Any]:
    """The source's OCR record (CRL-95): the pages whose text OCR recovered and the languages it
    read them in; empty when no text came from OCR."""
    pages = sorted({b.provenance.page for b in doc.blocks if b.provenance.ocr} - {None})
    if not pages or ocr is None:
        return {}
    return {"ocr_pages": pages, "ocr_languages": list(ocr.languages)}


def ocr_page_count(source: Source) -> int:
    """How many pages of `source` OCR read: 0 for a source with a text layer throughout."""
    pages = source.provenance.get("ocr_pages")
    return len(pages) if isinstance(pages, list) else 0


def ocr_note(pages: int) -> str:
    """What a reader is told about a source OCR read: the Sources tab, the three renders and the
    trace summary say it the same way."""
    return f"text recovered by OCR ({pages} page{'' if pages == 1 else 's'})"


def make_source(source_id: str, path: Path, *, ocr: OcrSettings | None = None) -> Source:
    """`ocr`: the settings of `ingest.ocr: auto`; None (off) refuses scanned PDF pages."""
    doc = ingest_file(path, ocr=ocr)
    return Source(
        id=source_id,
        kind=SourceKind.FILE,
        name=path.name,
        format=doc.format,
        sha256=doc.sha256,
        provenance={**doc.meta, **ocr_provenance(doc, ocr)},
        units=units_from_document(doc),
    )


def make_sources(paths: list[Path]) -> list[Source]:
    return [make_source(f"src{i}", p) for i, p in enumerate(paths, start=1)]


def source_from_paragraphs(
    source_id: str, paragraphs: list[str], *, name: str | None = None
) -> Source:
    """A plain-text source built from strings: one paragraph per unit, no file system."""
    text = "\n\n".join(paragraphs)
    return Source(
        id=source_id,
        kind=SourceKind.FILE,
        name=name or f"{source_id}.txt",
        format="txt",
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        units=[
            SourceUnit(id=f"u{i}", text=p, locator=f"para {i}", kind=BlockKind.PARAGRAPH)
            for i, p in enumerate(paragraphs, start=1)
        ],
    )


@dataclass
class UnitIndex:
    _sources: dict[str, Source] = field(default_factory=dict)
    _units: dict[str, tuple[Source, SourceUnit]] = field(default_factory=dict)

    @classmethod
    def from_sources(cls, sources: list[Source]) -> "UnitIndex":
        index = cls()
        for s in sources:
            index._sources[s.id] = s
            for u in s.units:
                index._units[unit_ref(s.id, u.id)] = (s, u)
        return index

    def refs(self) -> list[str]:
        return list(self._units)

    def has(self, ref: str) -> bool:
        try:
            split_ref(ref)
        except ValueError:
            return False
        return ref in self._units

    def get(self, ref: str) -> tuple[Source, SourceUnit]:
        return self._units[ref]

    def text(self, ref: str) -> str:
        return self._units[ref][1].text

    def source(self, source_id: str) -> Source:
        return self._sources[source_id]

    def sources(self) -> list[Source]:
        return list(self._sources.values())
