import pytest

from corelata.ingest.units import UnitIndex, make_source, make_sources, units_from_document
from corelata.schema import Block, BlockKind, Provenance, SourceDocument, SourceKind
from corelata.testing.sources import text_source


def _doc(*blocks):
    return SourceDocument(
        source_path="/x/a.txt", format="txt", sha256="ab" * 32, blocks=list(blocks)
    )


def _block(i, kind, text, page=None, locator=None):
    prov = Provenance(source_path="/x/a.txt", index=i - 1, page=page, locator=locator)
    return Block(id=f"b{i}", kind=kind, text=text, provenance=prov)


def test_units_skip_breaks_and_build_locators():
    doc = _doc(
        _block(1, BlockKind.PARAGRAPH, "one"),
        _block(2, BlockKind.BREAK, "* * *"),
        _block(3, BlockKind.PARAGRAPH, "two", page=3),
        _block(4, BlockKind.TABLE_CELL, "cell", page=3, locator="table 1 row 2 col 1"),
        _block(5, BlockKind.TABLE_CELL, "r", locator="row 7"),
    )
    units = units_from_document(doc)
    assert [u.id for u in units] == ["u1", "u2", "u3", "u4"]
    assert [u.locator for u in units] == [
        "para 1",
        "page 3",
        "page 3 / table 1 row 2 col 1",
        "row 7",
    ]
    assert units[0].kind is BlockKind.PARAGRAPH and units[2].text == "cell"


def test_make_sources_ids_in_order_and_duplicate_names_stay_distinct(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir(), b.mkdir()
    (a / "report.txt").write_text("Alpha text.", encoding="utf-8")
    (b / "report.txt").write_text("Beta text.", encoding="utf-8")
    sources = make_sources([a / "report.txt", b / "report.txt"])
    assert [s.id for s in sources] == ["src1", "src2"]
    assert [s.name for s in sources] == ["report.txt", "report.txt"]
    assert sources[0].sha256 != sources[1].sha256
    assert sources[0].kind is SourceKind.FILE and sources[0].format == "txt"
    assert make_source("srcX", a / "report.txt").id == "srcX"


def test_unit_index():
    s1 = text_source("src1", "alpha", "beta")
    s2 = text_source("src2", "gamma", name="g.txt")
    idx = UnitIndex.from_sources([s1, s2])
    assert idx.refs() == ["src1/u1", "src1/u2", "src2/u1"]
    assert idx.text("src2/u1") == "gamma"
    assert idx.has("src1/u2") and not idx.has("src1/u9") and not idx.has("garbage")
    src, unit = idx.get("src1/u2")
    assert src is s1 and unit.text == "beta"
    assert idx.source("src2").name == "g.txt"
    with pytest.raises(KeyError):
        idx.get("src3/u1")


def test_text_source_helper_defaults():
    s = text_source("src1", "a", "b")
    assert s.name == "src1.txt" and s.format == "txt" and len(s.sha256) == 64
    assert [u.locator for u in s.units] == ["para 1", "para 2"]
