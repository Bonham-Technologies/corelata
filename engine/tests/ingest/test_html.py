import pytest

from corelata.ingest.base import HINT_MAX_CHARS, IngestError, source_meta
from corelata.ingest.html import HtmlIngestor, collect_blocks, parse_html
from corelata.ingest.registry import check_supported, ingest_file
from corelata.render.docx import render_docx
from corelata.schema import BlockKind
from tests.render.fixtures import PACK, SOURCES, make_report

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


def test_meta_elements_become_date_and_origin_hints(tmp_path):
    """CRL-96: the page's own date and author win over the site's name; a timestamp is cut to
    its date."""
    doc = HtmlIngestor().ingest(
        _write(
            tmp_path,
            "<html><head>"
            '<meta property="og:site_name" content="Halden Courier">'
            '<meta property="article:published_time" content="2026-10-16T07:30:00+02:00">'
            '<meta name="Author" content="  Ina   Berg ">'
            '<meta name="date" content="">'
            "</head><body><p>Text.</p></body></html>",
        )
    )
    assert doc.meta == {"date": "2026-10-16", "origin": "Ina Berg"}
    site_only = HtmlIngestor().ingest(
        _write(
            tmp_path,
            '<html><head><meta property="og:site_name" content="Halden Courier">'
            '<meta name="dc.date" content="October 2026"></head><body><p>T.</p></body></html>',
        )
    )
    assert site_only.meta == {"date": "October 2026", "origin": "Halden Courier"}
    assert HtmlIngestor().ingest(_write(tmp_path, "<p>No head.</p>")).meta == {}
    assert HtmlIngestor().ingest(_write(tmp_path, "<!-- -->")).meta == {}


def test_meta_hints_are_capped_and_clean(tmp_path):
    """A page's metadata is anyone's writing: a hint is cut to HINT_MAX_CHARS and loses NULs."""
    long_name = "Agency " * 100
    doc = HtmlIngestor().ingest(
        _write(
            tmp_path,
            f'<html><head><meta name="author" content="{long_name}">'
            '<meta name="date" content="2026-10-16&#0;"></head><body><p>T.</p></body></html>',
        )
    )
    assert len(doc.meta["origin"]) == HINT_MAX_CHARS and doc.meta["origin"].endswith("…")
    assert "\x00" not in doc.meta["date"]
    assert source_meta("2026\x00-10-16", "A\x00B") == {"date": "2026-10-16", "origin": "AB"}


def test_meta_hints_lose_control_characters_and_still_render_as_docx(tmp_path):
    """A control character in a page's `<meta>` is not text, and python-docx refuses it: it would
    reach the source entry's origin and cost the run its DOCX export. Ordinary whitespace,
    C0 or C1, collapses to one space."""
    doc = HtmlIngestor().ingest(
        _write(
            tmp_path,
            '<html><head><meta name="author" content="Ina\x01 \x1b[31mBerg\x7f\x9b">'
            '<meta name="date" content="2026-10-16\x08"></head><body><p>T.</p></body></html>',
        )
    )
    assert doc.meta == {"date": "2026-10-16", "origin": "Ina [31mBerg"}
    assert source_meta("2026\t10\x0b16", "A\x1fB\x85C\nD\x0cE") == {
        "date": "2026 10 16",
        "origin": "A B C D E",
    }
    entry = make_report().sources[0].model_copy(update={"origin": doc.meta["origin"]})
    report = make_report().model_copy(update={"sources": [entry, *make_report().sources[1:]]})
    assert render_docx(report, PACK, SOURCES)[:2] == b"PK"
