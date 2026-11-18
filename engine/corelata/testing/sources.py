"""Build sources from strings for tests and demos, without touching the file system."""

from corelata.ingest.units import source_from_paragraphs
from corelata.schema import BlockKind, Source, SourceKind, SourceUnit


def text_source(source_id: str, *paragraphs: str, name: str | None = None) -> Source:
    return source_from_paragraphs(source_id, list(paragraphs), name=name)


def coglossa_source(source_id: str, *tiers: str) -> Source:
    """A Coglossa export as ingest stores it, one span per reliability tier given."""
    return Source(
        id=source_id,
        kind=SourceKind.COGLOSSA_EXPORT,
        name="report.json",
        format="coglossa",
        sha256="c" * 64,
        provenance={"coglossa_run_id": "run-42"},
        units=[
            SourceUnit(
                id=f"u{i}",
                text=f"Translated span {i} on Varna port capacity.",
                locator=f"coglossa:run-42/span:p{i}",
                kind=BlockKind.PARAGRAPH,
                meta={"reliability": tier},
            )
            for i, tier in enumerate(tiers or ("A",), start=1)
        ],
    )
