import json
from pathlib import Path

from corelata.schema.export import EXPORTED, export, main


def test_export_writes_one_file_per_model(tmp_path):
    written = export(tmp_path)
    assert {p.name for p in written} == {f"{n}.schema.json" for n in EXPORTED}
    report = json.loads((tmp_path / "report.schema.json").read_text())
    assert "claims" in report["properties"]


def test_main_prints_paths(tmp_path, capsys):
    assert main([str(tmp_path)]) == 0
    assert "report.schema.json" in capsys.readouterr().out


REPO_SCHEMA_DIR = Path(__file__).resolve().parents[3] / "schema"


def test_committed_schema_matches_models(tmp_path):
    """`schema/` is generated; when a model changes, run `make schema` and commit the diff."""
    written = export(tmp_path)
    assert {p.name for p in written} >= {
        "run-record.schema.json",
        "trace-summary.schema.json",
        "claim-provenance.schema.json",
    }
    assert {p.name for p in REPO_SCHEMA_DIR.glob("*.schema.json")} == {p.name for p in written}
    for path in written:
        committed = REPO_SCHEMA_DIR / path.name
        assert committed.is_file(), f"{committed} missing: run `make schema` and commit"
        assert committed.read_text(encoding="utf-8") == path.read_text(encoding="utf-8"), (
            f"{committed.name} is stale: run `make schema` and commit the result"
        )


def test_bench_report_schema_is_the_serialized_shape(tmp_path):
    """BenchReport is something Corelata writes and others read: its computed `ratio` must be in
    the schema, so that one model is exported in serialization mode."""
    export(tmp_path)
    schema = json.loads((tmp_path / "bench-report.schema.json").read_text())
    assert "ratio" in schema["$defs"]["Rate"]["properties"]
    report = json.loads((tmp_path / "report.schema.json").read_text())
    assert "claims" in report["properties"]  # the validation-mode exports are unchanged
