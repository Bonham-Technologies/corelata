import re
from pathlib import Path

from corelata.ingest.base import (
    file_sha256,
    is_scene_break,
    make_blocks,
    read_utf8,
    split_paragraphs,
)
from corelata.schema import BlockKind, SourceDocument

_HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")
_LIST_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$")

Item = tuple[BlockKind, str, str | None]


def _paragraph_items(para: str) -> list[Item]:
    if is_scene_break(para):
        return [(BlockKind.BREAK, para, None)]
    lines = para.split("\n")
    heading = _HEADING_RE.match(lines[0])
    if heading:
        rest = "\n".join(lines[1:]).strip()
        items: list[Item] = [(BlockKind.HEADING, heading.group(1), None)]
        return items + (_paragraph_items(rest) if rest else [])
    list_matches = [_LIST_RE.match(line) for line in lines]
    if all(list_matches):
        return [(BlockKind.LIST_ITEM, m.group(1), None) for m in list_matches if m]
    return [(BlockKind.PARAGRAPH, para, None)]


class MarkdownIngestor:
    format = "md"
    extensions = (".md", ".markdown")

    def ingest(self, path: Path) -> SourceDocument:
        items = [item for p in split_paragraphs(read_utf8(path)) for item in _paragraph_items(p)]
        return SourceDocument(
            source_path=str(path),
            format=self.format,
            sha256=file_sha256(path),
            blocks=make_blocks(str(path), items),
        )
