import csv
import json

import pytest

from corelata.ingest import tabular
from corelata.ingest.base import IngestError
from corelata.ingest.registry import ingest_file
from corelata.schema import BlockKind


def test_json_array_one_unit_per_record(tmp_path):
    path = tmp_path / "events.json"
    path.write_text(json.dumps([{"who": "A", "what": "met B"}, {"who": "C", "what": "left"}]))
    doc = ingest_file(path)
    assert doc.format == "json"
    assert [b.kind for b in doc.blocks] == [BlockKind.TABLE_CELL] * 2
    assert doc.blocks[0].text == "who: A; what: met B"
    assert doc.blocks[1].provenance.locator == "record 2"


def test_json_object_one_unit_per_key(tmp_path):
    path = tmp_path / "o.json"
    path.write_text(json.dumps({"summary": "short", "detail": {"n": 1, "tags": ["x", "y"]}}))
    doc = ingest_file(path)
    assert doc.blocks[0].text == "summary: short"
    assert doc.blocks[1].text == 'detail: {"n": 1, "tags": ["x", "y"]}'
    assert doc.blocks[1].provenance.locator == "key detail"


def test_json_scalar_is_one_unit(tmp_path):
    path = tmp_path / "s.json"
    path.write_text('"just text"')
    assert ingest_file(path).blocks[0].text == "just text"


def test_json_invalid(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{nope")
    with pytest.raises(IngestError, match=r"bad\.json is not valid JSON"):
        ingest_file(path)


def test_csv_rows_carry_header(tmp_path):
    path = tmp_path / "t.csv"
    path.write_text("name,role\nAda,lead\nBob,analyst\n", encoding="utf-8")
    doc = ingest_file(path)
    assert [b.text for b in doc.blocks] == ["name: Ada; role: lead", "name: Bob; role: analyst"]
    assert doc.blocks[1].provenance.locator == "row 3"  # header is row 1


def test_csv_header_only_has_no_usable_text(tmp_path):
    path = tmp_path / "h.csv"
    path.write_text("a,b\n", encoding="utf-8")
    with pytest.raises(IngestError, match="no usable text"):
        ingest_file(path)


def test_csv_ragged_rows_and_blank_cells(tmp_path):
    path = tmp_path / "r.csv"
    path.write_text("a,b,c\n1,,3\n4,5\n", encoding="utf-8")
    doc = ingest_file(path)
    assert [b.text for b in doc.blocks] == ["a: 1; c: 3", "a: 4; b: 5"]


# CRL-99: files the parser cannot read answer IngestError, never a bare library exception.


def test_csv_cell_over_the_default_field_limit_ingests(tmp_path):
    path = tmp_path / "long.csv"
    path.write_text("note\n" + "x" * 200_000 + "\n", encoding="utf-8")
    doc = ingest_file(path)
    assert len(doc.blocks[0].text) == len("note: ") + 200_000


@pytest.fixture
def field_limit():
    """Set the csv module's process-wide field limit for one test, then put it back."""
    previous = csv.field_size_limit()
    yield csv.field_size_limit
    csv.field_size_limit(previous)


def test_csv_error_names_the_file_and_row(tmp_path, monkeypatch, field_limit):
    field_limit(1000)
    monkeypatch.setattr(tabular, "_allow_fields_up_to", lambda chars: None)
    path = tmp_path / "huge.csv"
    path.write_text("note\nshort\n" + "x" * 5000 + "\n", encoding="utf-8")
    message = r"huge\.csv is not a readable CSV file \(row 3: field larger than field limit"
    with pytest.raises(IngestError, match=message):
        ingest_file(path)


def test_csv_field_limit_is_only_ever_raised(field_limit):
    field_limit(1000)
    tabular._allow_fields_up_to(5000)
    assert csv.field_size_limit() == 5000
    tabular._allow_fields_up_to(2000)  # a smaller file in another thread must not lower it
    assert csv.field_size_limit() == 5000


def test_a_small_csv_after_a_large_one_keeps_the_raised_limit(tmp_path, field_limit):
    field_limit(1000)
    large = tmp_path / "large.csv"
    large.write_text("note\n" + "x" * 5000 + "\n", encoding="utf-8")
    small = tmp_path / "small.csv"
    small.write_text("note\nx\n", encoding="utf-8")
    ingest_file(large)
    raised = csv.field_size_limit()
    assert raised > 5000
    ingest_file(small)
    assert csv.field_size_limit() == raised


def test_deeply_nested_json_is_an_ingest_error(tmp_path):
    path = tmp_path / "deep.json"
    path.write_text("[" * 100_000 + "]" * 100_000, encoding="utf-8")
    with pytest.raises(IngestError, match=r"deep\.json is nested too deeply"):
        ingest_file(path)
