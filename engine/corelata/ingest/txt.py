from pathlib import Path

from corelata.ingest.base import (
    file_sha256,
    is_scene_break,
    make_blocks,
    read_utf8,
    split_paragraphs,
)
from corelata.schema import BlockKind, SourceDocument


class TextIngestor:
    format = "txt"
    extensions = (".txt",)

    def ingest(self, path: Path) -> SourceDocument:
        items = [
            (BlockKind.BREAK if is_scene_break(p) else BlockKind.PARAGRAPH, p, None)
            for p in split_paragraphs(read_utf8(path))
        ]
        return SourceDocument(
            source_path=str(path),
            format=self.format,
            sha256=file_sha256(path),
            blocks=make_blocks(str(path), items),
        )
