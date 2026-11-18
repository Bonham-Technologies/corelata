"""Build sources from strings for tests and demos, without touching the file system."""

from corelata.ingest.units import source_from_paragraphs
from corelata.schema import Source


def text_source(source_id: str, *paragraphs: str, name: str | None = None) -> Source:
    return source_from_paragraphs(source_id, list(paragraphs), name=name)
