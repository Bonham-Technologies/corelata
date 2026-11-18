import pytest

from corelata.ingest.base import IngestError, is_scene_break, split_paragraphs
from corelata.ingest.markdown import MarkdownIngestor
from corelata.ingest.txt import TextIngestor
from corelata.schema import BlockKind


@pytest.mark.parametrize("line", ["***", "* * *", "---", "___", "#", "~~~", "§", "  * * *  "])
def test_scene_breaks(line):
    assert is_scene_break(line)


@pytest.mark.parametrize("line", ["# Title", "Hello", "**bold**", "--", "- item"])
def test_not_scene_breaks(line):
    assert not is_scene_break(line)


def test_split_paragraphs_keeps_inner_line_breaks():
    text = "Roses are red,\r\nviolets are blue.\r\n\r\n\n  Second para.  \n\n\n"
    assert split_paragraphs(text) == ["Roses are red,\nviolets are blue.", "Second para."]


def test_txt_ingest(tmp_path):
    path = tmp_path / "story.txt"
    path.write_text("﻿First paragraph.\n\n* * *\n\nSecond, after a break.\n", encoding="utf-8")
    doc = TextIngestor().ingest(path)
    assert doc.format == "txt"
    assert len(doc.sha256) == 64
    assert [(b.id, b.kind, b.text) for b in doc.blocks] == [
        ("b1", BlockKind.PARAGRAPH, "First paragraph."),
        ("b2", BlockKind.BREAK, "* * *"),
        ("b3", BlockKind.PARAGRAPH, "Second, after a break."),
    ]
    assert doc.blocks[2].provenance.index == 2
    assert doc.blocks[0].provenance.source_path == str(path)


def test_txt_rejects_non_utf8(tmp_path):
    path = tmp_path / "latin1.txt"
    path.write_bytes("café".encode("latin-1"))
    with pytest.raises(IngestError, match=r"latin1\.txt is not valid UTF-8"):
        TextIngestor().ingest(path)


def test_markdown_ingest(tmp_path):
    path = tmp_path / "doc.md"
    path.write_text(
        "# Chapter One\n\nIt was night.\n\n- milk\n- 2. bread\n\n1. first\n2. second\n\n"
        "---\n\n## Part Two\nThe heading has a body.\n\n* * *\n",
        encoding="utf-8",
    )
    doc = MarkdownIngestor().ingest(path)
    assert [(b.kind, b.text) for b in doc.blocks] == [
        (BlockKind.HEADING, "Chapter One"),
        (BlockKind.PARAGRAPH, "It was night."),
        (BlockKind.LIST_ITEM, "milk"),
        (BlockKind.LIST_ITEM, "2. bread"),
        (BlockKind.LIST_ITEM, "first"),
        (BlockKind.LIST_ITEM, "second"),
        (BlockKind.BREAK, "---"),
        (BlockKind.HEADING, "Part Two"),
        (BlockKind.PARAGRAPH, "The heading has a body."),
        (BlockKind.BREAK, "* * *"),
    ]
    assert doc.format == "md"
