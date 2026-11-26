import json
import shutil
from pathlib import Path

import pytest
import yaml

from corelata import __version__
from corelata.cli import _load_run, main, render_outputs
from corelata.render.docx import RenderError
from corelata.render.outline import DEGRADATION_TITLE
from corelata.standards.loader import BUILTIN_PACKS_DIR
from corelata.testing import synthetic
from corelata.testing.fake_openai import FakeOpenAIServer
from tests.conftest import BASE_CONFIG
from tests.stages.conftest import PORT


@pytest.fixture
def fake_server():
    with FakeOpenAIServer() as server:
        yield server


@pytest.fixture
def config_path(tmp_path, fake_server) -> Path:
    data = {**BASE_CONFIG, "backends": {"fake": {"base_url": fake_server.base_url}}}
    path = tmp_path / "corelata.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


@pytest.fixture
def inputs(tmp_path) -> list[str]:
    a = tmp_path / "a.txt"
    a.write_text("\n\n".join(PORT), encoding="utf-8")
    b = tmp_path / "b.md"
    b.write_text("# Note\n\nShippers welcomed the capacity at Varna.", encoding="utf-8")
    return [str(a), str(b)]


def test_version(capsys, monkeypatch):
    with pytest.raises(SystemExit) as e:
        main(["--version"])
    assert e.value.code == 0 and __version__ in capsys.readouterr().out
    monkeypatch.setenv("CORELATA_BUILD_VERSION", "9.9.9")
    with pytest.raises(SystemExit):
        main(["--version"])
    assert f"corelata {__version__} (build 9.9.9)" in capsys.readouterr().out


def test_run_clean(config_path, inputs, tmp_path, capsys):
    out = tmp_path / "out"
    code = main(
        [
            "run",
            *inputs,
            "--statement",
            "Varna port capacity expansion matters to shippers",
            "--config",
            str(config_path),
            "--out",
            str(out),
        ]
    )
    assert code == 0
    names = {p.name for p in out.iterdir()}
    assert names == {
        "report.md",
        "report.html",
        "report.docx",
        "report.json",
        "trace.json",
        "gate.json",
    }
    html = (out / "report.html").read_text()
    assert html.startswith("<!DOCTYPE html>") and 'class="claim-ids"' not in html
    assert '<sup class="source-refs">1</sup>' in html  # source references always show (CRL-96)
    assert (out / "report.docx").read_bytes()[:2] == b"PK"
    trace = json.loads((out / "trace.json").read_text())
    assert trace["state"] == "completed" and trace["status"] == "clean"
    assert [s["id"] for s in trace["sources"]] == ["src1", "src2"]
    report = json.loads((out / "report.json").read_text())
    assert report["metadata"]["status"] == "clean"
    md = (out / "report.md").read_text()
    assert md.startswith("UNCLASSIFIED\n") and "^[" not in md
    summary = capsys.readouterr().out
    assert "completed" in summary and "clean" in summary and str(out) in summary


def test_run_findings_open_exit_3(config_path, tmp_path, capsys):
    src = tmp_path / "s.txt"
    src.write_text("\n\n".join([*PORT, "UNSOURCED UNFIXABLE detail on Varna."]), encoding="utf-8")
    out = tmp_path / "out"
    statement = "Varna port capacity expansion matters to shippers"
    code = main(
        [
            "run",
            str(src),
            "--statement",
            statement,
            "--config",
            str(config_path),
            "--out",
            str(out),
            "--claim-ids",
        ]
    )
    assert code == 3
    md = (out / "report.md").read_text()
    assert "## Audit findings open at delivery" in md and "^[c0]" in md


def test_run_gate_rejected_exit_4(config_path, inputs, tmp_path, capsys):
    out = tmp_path / "out"
    code = main(
        [
            "run",
            *inputs,
            "--statement",
            "Lunar helium mining",
            "--config",
            str(config_path),
            "--out",
            str(out),
        ]
    )
    assert code == 4
    assert {p.name for p in out.iterdir()} == {"trace.json", "gate.json"}
    assert "gate rejected" in capsys.readouterr().out


def test_run_blank_statement_is_usage_error(config_path, inputs, capsys):
    assert main(["run", *inputs, "--statement", "   ", "--config", str(config_path)]) == 2
    assert "value statement" in capsys.readouterr().err


def test_run_statement_file_and_default_out(config_path, inputs, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "v.txt").write_text("Varna port capacity expansion matters to shippers")
    code = main(
        ["run", *inputs, "--statement-file", str(tmp_path / "v.txt"), "--config", str(config_path)]
    )
    assert code == 0
    runs = list((tmp_path / "corelata-out").iterdir())
    assert len(runs) == 1 and (runs[0] / "report.md").is_file()


def test_run_requires_exactly_one_statement_source(config_path, inputs, capsys):
    assert main(["run", *inputs, "--config", str(config_path)]) == 2
    both = ["--statement", "x", "--statement-file", "y", "--config", str(config_path)]
    assert main(["run", *inputs, *both]) == 2


def test_run_bad_input_file(config_path, tmp_path, capsys):
    bad = tmp_path / "x.odt"
    bad.write_bytes(b"x")
    assert main(["run", str(bad), "--statement", "s", "--config", str(config_path)]) == 2
    assert "unsupported file type" in capsys.readouterr().err


def test_run_bad_config(tmp_path, inputs, capsys):
    assert main(["run", *inputs, "--statement", "s", "--config", str(tmp_path / "nope.yaml")]) == 2
    assert "config file not found" in capsys.readouterr().err


def test_run_with_coglossa_export(config_path, tmp_path, inputs):
    export = {
        "schema_version": "1",
        "coglossa_version": "0.1.0",
        "run_id": "run-7",
        "document": {"source_path": "/in/x.docx", "format": "docx", "sha256": "00" * 32},
        "spans": [
            {
                "id": "p1",
                "text": "Varna port capacity rose for shippers.",
                "agreement": "agree",
                "chosen_from": "literal",
                "score": {"reliability": "A"},
                "flags": [],
            }
        ],
        "guide": {"summary": "", "style_guide": "", "glossary": []},
    }
    path = tmp_path / "x.coglossa.json"
    path.write_text(json.dumps(export))
    out = tmp_path / "out"
    code = main(
        [
            "run",
            inputs[0],
            "--coglossa-export",
            str(path),
            "--statement",
            "Varna port capacity expansion matters to shippers",
            "--config",
            str(config_path),
            "--out",
            str(out),
        ]
    )
    assert code == 0
    trace = json.loads((out / "trace.json").read_text())
    assert [s["id"] for s in trace["sources"]] == ["src1", "src2"]
    assert trace["sources"][1]["provenance"]["coglossa_run_id"] == "run-7"
    assert "Coglossa run run-7" in (out / "report.md").read_text()


def test_discover(config_path, inputs, capsys):
    assert main(["discover", *inputs, "--config", str(config_path), "--audience", "ops"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert len(data["candidates"]) == 2 and data["candidates"][0]["audience"] == "ops"


def test_pack_validate_and_show(capsys, tmp_path):
    assert main(["pack", "validate", "icd203-base"]) == 0
    capsys.readouterr()
    assert main(["pack", "show", "icd203-base"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["name"] == "icd203-base" and len(data["rules"]) == 17
    assert main(["pack", "show", "nope"]) == 1
    assert "not found" in capsys.readouterr().err
    (tmp_path / "p").mkdir()
    (tmp_path / "p" / "pack.yaml").write_text("name: p\nversion: '1'\n")
    assert main(["pack", "validate", str(tmp_path / "p")]) == 1
    assert "error:" in capsys.readouterr().out


def test_fake_openai_command_binds_and_stops(monkeypatch):
    def fake_serve(self):
        raise KeyboardInterrupt

    monkeypatch.setattr(FakeOpenAIServer, "serve_forever", fake_serve)
    assert main(["fake-openai", "--port", "0"]) == 0
    assert main(["fake-openai", "--port", "0", "--needs-repair"]) == 0
    seen = []
    monkeypatch.setattr(FakeOpenAIServer, "serve_forever", lambda self: seen.append(self))
    assert main(["fake-openai", "--port", "0", "--reasoning", "think"]) == 0
    assert seen[0]._server.reasoning == "think"  # CRL-140


def test_run_out_pointing_at_a_file_is_usage_error_before_any_model_call(
    config_path, inputs, tmp_path, fake_server, capsys
):
    target = tmp_path / "afile"
    target.write_text("x")
    code = main(
        ["run", *inputs, "--statement", "Varna port capacity expansion matters to shippers"]
        + ["--config", str(config_path), "--out", str(target)]
    )
    assert code == 2
    assert f"error: cannot write to {target}:" in capsys.readouterr().err
    assert fake_server.requests == []


def test_rerun_into_same_out_leaves_no_stale_files(config_path, inputs, tmp_path):
    out = tmp_path / "out"
    base = ["run", *inputs, "--config", str(config_path), "--out", str(out)]
    assert main([*base, "--statement", "Varna port capacity expansion matters to shippers"]) == 0
    all_six = {"report.md", "report.html", "report.docx", "report.json", "trace.json", "gate.json"}
    assert {p.name for p in out.iterdir()} == all_six
    assert main([*base, "--statement", "Lunar helium mining"]) == 4
    assert {p.name for p in out.iterdir()} == {"trace.json", "gate.json"}


def test_run_max_iterations_out_of_range_is_usage_error(config_path, inputs, tmp_path, capsys):
    code = main(
        ["run", *inputs, "--statement", "Varna port capacity expansion matters to shippers"]
        + ["--config", str(config_path), "--out", str(tmp_path / "o"), "--max-iterations", "25"]
    )
    assert code == 2
    assert "error: max_iterations must be between 0 and 10" in capsys.readouterr().err


def test_run_over_long_statement_or_guidance_is_usage_error_before_any_model_call(
    config_path, inputs, tmp_path, fake_server, capsys
):
    """CRL-111: `corelata run` is held to the API's limits (CRL-83), checked before the spend."""
    base = ["run", *inputs, "--config", str(config_path), "--out", str(tmp_path / "o")]
    assert main([*base, "--statement", "x" * 4001]) == 2
    assert "error: a value statement is at most 4000 characters" in capsys.readouterr().err
    statement_file = tmp_path / "v.txt"
    statement_file.write_text("x" * 4001, encoding="utf-8")
    assert main([*base, "--statement-file", str(statement_file)]) == 2
    assert "at most 4000 characters" in capsys.readouterr().err
    code = main([*base, "--statement", "Varna port", "--guidance", "g" * 8001])
    assert code == 2
    assert "error: the writer guidance is at most 8000 characters" in capsys.readouterr().err
    assert fake_server.requests == [] and not (tmp_path / "o").exists()


STATEMENT = "Varna port capacity expansion matters to shippers"


@pytest.fixture
def run_dir(config_path, inputs, tmp_path) -> Path:
    out = tmp_path / "run"
    assert (
        main(
            [
                "run",
                *inputs,
                "--statement",
                STATEMENT,
                "--config",
                str(config_path),
                "--out",
                str(out),
            ]
        )
        == 0
    )
    return out


@pytest.fixture
def rejected_dir(config_path, inputs, tmp_path) -> Path:
    out = tmp_path / "rejected"
    code = main(
        [
            "run",
            *inputs,
            "--statement",
            "Lunar helium mining",
            "--config",
            str(config_path),
            "--out",
            str(out),
        ]
    )
    assert code == 4
    return out


def test_run_claim_ids_apply_to_md_and_html_but_never_docx(config_path, inputs, tmp_path):
    out = tmp_path / "out"
    args = [
        "run",
        *inputs,
        "--statement",
        STATEMENT,
        "--config",
        str(config_path),
        "--out",
        str(out),
    ]
    assert main([*args, "--claim-ids"]) == 0
    assert "^[c0]" in (out / "report.md").read_text()
    assert '<sup class="claim-ids">c0</sup>' in (out / "report.html").read_text()
    from docx import Document

    doc = Document(str(out / "report.docx"))
    sups = [r.text for p in doc.paragraphs for r in p.runs if r.font.superscript]
    assert sups and all(s.replace(",", "").isdigit() for s in sups)  # source references only


def test_report_reproduces_the_run_outputs(run_dir, capsys, tmp_path):
    assert main(["report", str(run_dir), "--format", "md"]) == 0
    assert capsys.readouterr().out == (run_dir / "report.md").read_text()
    assert main(["report", str(run_dir), "--format", "html"]) == 0
    assert capsys.readouterr().out == (run_dir / "report.html").read_text()
    assert main(["report", str(run_dir), "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out) == json.loads((run_dir / "report.json").read_text())
    target = tmp_path / "again.docx"
    assert main(["report", str(run_dir), "--format", "docx", "--out", str(target)]) == 0
    assert target.read_bytes() == (run_dir / "report.docx").read_bytes()
    assert (
        main(
            [
                "report",
                str(run_dir),
                "--format",
                "md",
                "--claim-ids",
                "--out",
                str(tmp_path / "ids.md"),
            ]
        )
        == 0
    )
    assert "^[c0]" in (tmp_path / "ids.md").read_text()


def test_report_docx_needs_out_and_notes_unresolvable_reference(run_dir, capsys, tmp_path):
    assert main(["report", str(run_dir), "--format", "docx"]) == 2
    assert "--out" in capsys.readouterr().err
    trace = json.loads((run_dir / "trace.json").read_text())
    trace["pack_snapshot"]["format"]["docx_reference"] = "templates/east.docx"
    (run_dir / "trace.json").write_text(json.dumps(trace))
    target = tmp_path / "x.docx"
    assert main(["report", str(run_dir), "--format", "docx", "--out", str(target)]) == 0
    err = capsys.readouterr().err
    assert "docx_reference 'templates/east.docx'" in err and "--docx-reference" in err
    assert target.read_bytes()[:2] == b"PK"
    from docx import Document

    ref = tmp_path / "ref.docx"
    Document().save(str(ref))
    assert (
        main(
            [
                "report",
                str(run_dir),
                "--format",
                "docx",
                "--out",
                str(target),
                "--docx-reference",
                str(ref),
            ]
        )
        == 0
    )
    assert capsys.readouterr().err == ""
    (tmp_path / "bad.docx").write_text("nope")
    assert (
        main(
            [
                "report",
                str(run_dir),
                "--format",
                "docx",
                "--out",
                str(target),
                "--docx-reference",
                str(tmp_path / "bad.docx"),
            ]
        )
        == 2
    )
    assert "cannot open docx reference" in capsys.readouterr().err


def test_report_and_trace_usage_errors(rejected_dir, tmp_path, capsys):
    assert main(["report", str(rejected_dir), "--format", "md"]) == 2
    assert "has no report (state gate_rejected)" in capsys.readouterr().err
    assert main(["report", str(tmp_path / "nowhere"), "--format", "md"]) == 2
    assert "no trace.json in" in capsys.readouterr().err
    assert main(["trace", str(tmp_path / "nowhere")]) == 2
    assert "no trace.json in" in capsys.readouterr().err
    (tmp_path / "corrupt").mkdir()
    (tmp_path / "corrupt" / "trace.json").write_text("{")
    assert main(["trace", str(tmp_path / "corrupt")]) == 2
    assert "not valid JSON" in capsys.readouterr().err
    assert main(["trace", str(rejected_dir)]) == 0
    out = capsys.readouterr().out
    assert ": gate_rejected" in out and "gate: not supported" in out


def test_trace_text_json_and_claim(run_dir, capsys):
    assert main(["trace", str(run_dir)]) == 0
    text = capsys.readouterr().out
    assert "completed clean after 0 revision(s)" in text and "stages:" in text
    assert main(["trace", str(run_dir), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["state"] == "completed" and [s["id"] for s in data["sources"]] == ["src1", "src2"]
    assert main(["trace", str(run_dir), "--claim", "c0"]) == 0
    text = capsys.readouterr().out
    assert text.startswith("c0 (judgment):") and "src1/u1" in text and "para 1" in text
    assert "cited by: key_judgments[0], analysis[0].paragraphs[0]" in text
    assert main(["trace", str(run_dir), "--claim", "c0", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["claim"]["id"] == "c0"
    assert main(["trace", str(run_dir), "--claim", "zzz"]) == 2
    assert "unknown claim id 'zzz'" in capsys.readouterr().err


def test_report_survives_a_tampered_snapshot_and_unwritable_out(run_dir, capsys, tmp_path):
    assert main(["report", str(run_dir), "--format", "md", "--out", str(tmp_path)]) == 2
    assert "cannot write" in capsys.readouterr().err
    trace = json.loads((run_dir / "trace.json").read_text())
    del trace["pack_snapshot"]["template"]
    (run_dir / "trace.json").write_text(json.dumps(trace))
    assert main(["report", str(run_dir), "--format", "md"]) == 2
    assert "pack_snapshot" in capsys.readouterr().err


@pytest.mark.parametrize("error", [RenderError("boom"), RuntimeError("boom")])
def test_run_docx_export_failure_keeps_the_trace_and_other_exports(
    config_path, inputs, tmp_path, capsys, monkeypatch, error
):
    def broken(*args, **kwargs):
        raise error

    monkeypatch.setattr("corelata.exports.render_docx", broken)
    out = tmp_path / "out"
    code = main(
        ["run", *inputs, "--statement", STATEMENT, "--config", str(config_path), "--out", str(out)]
    )
    assert code == 1
    err = capsys.readouterr().err
    assert "completed clean after 0 revision(s), but the DOCX export failed: boom" in err
    assert str(out) in err
    assert {p.name for p in out.iterdir()} == {
        "trace.json",
        "gate.json",
        "report.json",
        "report.md",
        "report.html",
    }
    assert json.loads((out / "trace.json").read_text())["state"] == "completed"


def test_report_renders_only_the_requested_format(run_dir, tmp_path, capsys):
    bad = tmp_path / "bad.docx"
    bad.write_text("nope")
    assert main(["report", str(run_dir), "--format", "md", "--docx-reference", str(bad)]) == 0
    assert capsys.readouterr().out == (run_dir / "report.md").read_text()
    record, pack = _load_run(run_dir)
    assert set(render_outputs(record, pack, with_claim_ids=False, formats=())) == {
        "trace.json",
        "gate.json",
    }
    assert set(render_outputs(record, pack, with_claim_ids=False, formats=("html",))) == {
        "trace.json",
        "gate.json",
        "report.html",
    }
    assert set(render_outputs(record, pack, with_claim_ids=False)) == {
        "trace.json",
        "gate.json",
        "report.json",
        "report.md",
        "report.html",
        "report.docx",
    }
    with pytest.raises(ValueError, match="unknown report format 'pdf'"):
        render_outputs(record, pack, with_claim_ids=False, formats=("pdf",))


def test_render_outputs_without_a_report_is_the_trace_alone(rejected_dir):
    record, pack = _load_run(rejected_dir)
    assert set(render_outputs(record, pack, with_claim_ids=False)) == {"trace.json", "gate.json"}
    assert {p.name for p in rejected_dir.iterdir()} == {"trace.json", "gate.json"}


def test_pack_diff_names_profiles_and_directories(capsys, tmp_path):
    from tests.standards.test_diff import PROFILE, RULE2
    from tests.standards.test_loader import RULE, write_pack

    packs = tmp_path / "packs"
    write_pack(packs, "base", rules=[RULE, RULE2], profiles={"team": PROFILE})
    assert main(["pack", "diff", "icd203-base", "icd203-base"]) == 0
    assert capsys.readouterr().out == "pack diff: icd203-base -> icd203-base\nno differences\n"
    rc = main(
        ["pack", "diff", "base", "base", "--profile-right", "team", "--packs-dir", str(packs)]
    )
    out = capsys.readouterr().out
    assert rc == 3 and "profile: None -> team" in out and "team.r.1  House rule" in out
    rc = main(["pack", "diff", str(packs / "base"), "base", "--packs-dir", str(packs), "--json"])
    data = json.loads(capsys.readouterr().out)
    assert rc == 0 and data["left"] == str(packs / "base") and data["rules_added"] == []


def test_pack_diff_against_a_run_snapshot(config_path, inputs, tmp_path, capsys):
    out = tmp_path / "out"
    assert (
        main(
            [
                "run",
                *inputs,
                "--statement",
                STATEMENT,
                "--out",
                str(out),
                "--config",
                str(config_path),
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert main(["pack", "diff", str(out), "icd203-base"]) == 0
    assert "no differences" in capsys.readouterr().out
    # the snapshot is what the run used: editing a pack on disk afterwards shows as a difference
    copy = tmp_path / "packs" / "icd203-base"
    shutil.copytree(BUILTIN_PACKS_DIR / "icd203-base", copy)
    rule = copy / "rules" / "icd203.tc.5.yaml"
    rule.write_text(
        rule.read_text(encoding="utf-8").replace("severity: major", "severity: blocking"),
        encoding="utf-8",
    )
    assert main(["pack", "diff", str(out), str(copy)]) == 3
    text = capsys.readouterr().out
    assert "icd203.tc.5" in text and "severity: major -> blocking" in text
    assert main(["pack", "diff", str(out), "icd203-base"]) == 0
    capsys.readouterr()
    assert (
        main(["pack", "diff", str(out / "trace.json"), "icd203-base", "--profile-left", "x"]) == 2
    )
    assert "carries its own profile" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("argv", "text"),
    [
        (["pack", "diff", "nope", "icd203-base"], "not found"),
        (
            ["pack", "diff", "icd203-base", "icd203-base", "--profile-right", "ghost"],
            "profile 'ghost'",
        ),
    ],
)
def test_pack_diff_errors(capsys, tmp_path, argv, text):
    assert main(argv) == 1
    assert text in capsys.readouterr().err
    empty = tmp_path / "empty"
    empty.mkdir()
    assert main(["pack", "diff", str(empty), "icd203-base"]) == 1
    assert "not found" in capsys.readouterr().err


def test_run_with_an_unusable_auditor_delivers_and_exits_3(
    config_path, inputs, tmp_path, capsys, monkeypatch
):
    # the fake server answers through synthetic._HANDLERS in this process
    monkeypatch.setitem(synthetic._HANDLERS, "auditor", lambda p: {"findings": [], "summary": ""})
    out = tmp_path / "out"
    statement = "Varna port capacity expansion matters to shippers"
    code = main(
        ["run", *inputs, "--statement", statement, "--config", str(config_path), "--out", str(out)]
    )
    assert code == 3
    meta = json.loads((out / "report.json").read_text())["metadata"]
    assert meta["status"] == "findings_open" and meta["open_findings"] == []
    [note] = meta["degradations"]
    assert note.startswith("audit incomplete after 2 attempts: auditor: invalid output after")
    assert "findings: Input should be an object" in note
    md = (out / "report.md").read_text()
    assert f"## {DEGRADATION_TITLE}" in md and note in md
    captured = capsys.readouterr()
    assert "completed findings_open" in captured.out and note in captured.err
    assert main(["trace", str(out)]) == 0
    assert f"degraded: {note}" in capsys.readouterr().out.splitlines()
