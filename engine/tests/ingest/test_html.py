import pytest

from corelata.ingest.base import IngestError
from corelata.ingest.html import HtmlIngestor, collect_blocks, parse_html
from corelata.ingest.registry import check_supported, ingest_file
from corelata.schema import BlockKind

H, P, LI, TD, FN, BR = (
    BlockKind.HEADING,
    BlockKind.PARAGRAPH,
    BlockKind.LIST_ITEM,
    BlockKind.TABLE_CELL,
    BlockKind.FOOTNOTE,
    BlockKind.BREAK,
)


def _write(tmp_path, html: str, name: str = "page.html"):
    path = tmp_path / name
    path.write_text(html, encoding="utf-8")
    return path


def _kinds(doc):
    return [(b.kind, b.text) for b in doc.blocks]


def test_blocks_in_document_order(tmp_path):
    doc = HtmlIngestor().ingest(
        _write(
            tmp_path,
            "<!doctype html><html><head><title>T</title><style>p {}</style></head><body>"
            "<h1>Le  titre</h1><p>Un <em>beau</em>\n   jour.</p>"
            "<ul><li>Pommes</li><li>Poires</li></ul>"
            "<table><tr><th>Nom</th><td>Valeur</td></tr></table>"
            "<script>var x = 1;</script></body></html>",
        )
    )
    assert _kinds(doc) == [
        (H, "Le titre"),
        (P, "Un beau jour."),
        (LI, "Pommes"),
        (LI, "Poires"),
        (TD, "Nom"),
        (TD, "Valeur"),
    ]
    assert doc.format == "html"
    assert [b.id for b in doc.blocks] == [f"b{i}" for i in range(1, 7)]
    assert [b.provenance.index for b in doc.blocks] == list(range(6))
    assert all(b.provenance.locator is None for b in doc.blocks)


def test_loose_text_around_blocks_becomes_paragraphs(tmp_path):
    doc = HtmlIngestor().ingest(
        _write(tmp_path, "<body><div>Avant<p>Milieu</p>Après <b>tout</b></div>Fin</body>")
    )
    assert _kinds(doc) == [(P, "Avant"), (P, "Milieu"), (P, "Après tout"), (P, "Fin")]


def test_line_breaks_rules_and_scene_breaks(tmp_path):
    doc = HtmlIngestor().ingest(
        _write(tmp_path, "<p>Ligne un<br>  Ligne deux<br/></p><hr><p>* * *</p><p>Suite.</p>")
    )
    assert _kinds(doc) == [
        (P, "Ligne un\nLigne deux"),
        (BR, "* * *"),
        (BR, "* * *"),
        (P, "Suite."),
    ]


def test_nesting_footnotes_and_note_references(tmp_path):
    doc = HtmlIngestor().ingest(
        _write(
            tmp_path,
            '<body><p>Texte<a epub:type="noteref" href="#n1">1</a> suite.</p>'
            '<aside epub:type="footnote" id="n1"><p>Une note.</p></aside>'
            '<div role="doc-endnote">Fin.</div>'
            '<p>Voir<sup role="doc-noteref">2</sup>.</p>'
            "<ul><li><p>Point</p><ul><li>Sous-point</li></ul></li></ul>"
            "<table><tr><td><p>Cellule</p></td></tr></table></body>",
        )
    )
    assert _kinds(doc) == [
        (P, "Texte suite."),
        (FN, "Une note."),
        (FN, "Fin."),
        (P, "Voir."),
        (LI, "Point"),
        (LI, "Sous-point"),
        (TD, "Cellule"),
    ]


def test_pre_keeps_lines_and_comments_are_skipped(tmp_path):
    doc = HtmlIngestor().ingest(
        _write(tmp_path, "<body><pre>a   b\n  c\n</pre><p>x<!-- hidden -->y</p></body>")
    )
    assert _kinds(doc) == [(P, "a b\nc"), (P, "xy")]


def test_private_use_character_in_text_does_not_split_lines(tmp_path):
    doc = HtmlIngestor().ingest(_write(tmp_path, "<p>a\ue000b</p>"))
    assert _kinds(doc) == [(P, "ab")]


def test_utf8_without_charset_and_declared_legacy_charset(tmp_path):
    plain = tmp_path / "a.html"
    plain.write_bytes("<p>café</p>".encode())
    assert HtmlIngestor().ingest(plain).blocks[0].text == "café"
    legacy = tmp_path / "b.html"
    legacy.write_bytes(
        '<html><head><meta charset="windows-1252"></head><body><p>caf\xe9</p></body></html>'.encode(
            "cp1252"
        )
    )
    assert HtmlIngestor().ingest(legacy).blocks[0].text == "café"


def test_xhtml_with_xml_declaration_and_namespace(tmp_path):
    doc = HtmlIngestor().ingest(
        _write(
            tmp_path,
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<html xmlns="http://www.w3.org/1999/xhtml"><body><h2>Titre</h2>'
            "<p>Corps.</p></body></html>",
            name="chapter.xhtml",
        )
    )
    assert _kinds(doc) == [(H, "Titre"), (P, "Corps.")]


def test_parse_html_returns_none_for_empty_documents():
    assert parse_html(b"") is None
    assert parse_html(b"   \n") is None
    assert collect_blocks(parse_html(b"<p>a</p>"), "ch1.xhtml") == [(P, "a", "ch1.xhtml")]


@pytest.mark.parametrize("html", ["", "<html><head><title>x</title></head><body>  </body></html>"])
def test_documents_without_text_are_refused(tmp_path, html):
    with pytest.raises(IngestError, match="contains no usable text"):
        ingest_file(_write(tmp_path, html))


def test_registry_reads_html(tmp_path):
    for name in ("a.html", "b.htm", "c.xhtml"):
        assert ingest_file(_write(tmp_path, "<p>Bonjour.</p>", name=name)).format == "html"
    with pytest.raises(IngestError) as e:
        check_supported(_write(tmp_path, "x", name="a.rtf"))
    assert ".html" in str(e.value)


def test_nested_blocks_keep_the_outer_kind(tmp_path):
    doc = HtmlIngestor().ingest(
        _write(
            tmp_path,
            "<body><table><tr><td><ul><li>x</li></ul></td></tr></table>"
            '<aside epub:type="footnote"><ol><li>note</li></ol></aside>'
            "<ul><li><h3>titre</h3></li></ul></body>",
        )
    )
    assert _kinds(doc) == [(TD, "x"), (FN, "note"), (LI, "titre")]
