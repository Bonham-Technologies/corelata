import io
import json
import logging
import re
import uuid

import psycopg
import pytest
import yaml
from docx import Document

from corelata.cli import main
from corelata.exports import FINDINGS_SHEET, OUTPUT_FILES
from corelata.testing.fake_openai import FakeOpenAIServer
from corelata.testing.postgres import create_test_database, drop_test_database
from tests.conftest import BASE_CONFIG
from tests.standards.test_loader import write_pack


@pytest.fixture
def server():
    with FakeOpenAIServer() as srv:
        yield srv


@pytest.fixture
def setup(db, tmp_path, server, monkeypatch, pg_url):
    """A config file pointing at the fake model, the test database and a storage directory."""
    monkeypatch.setenv("CORELATA_DATABASE_URL", pg_url)
    data = {
        **BASE_CONFIG,
        "backends": {"fake": {"base_url": server.base_url}},
        "storage": {"path": str(tmp_path / "files")},
        "worker": {"concurrency": 2, "stalled_after_s": 60},
    }
    config = tmp_path / "corelata.yaml"
    config.write_text(yaml.safe_dump(data), encoding="utf-8")
    doc = tmp_path / "port.txt"
    doc.write_text(
        "The port of Varna expanded its container capacity in 2025.\n\n"
        "Capacity expansion was financed by a state bank.\n\n"
        "Container traffic through Varna rose 40 percent.",
        encoding="utf-8",
    )
    return config, doc


def _cli(capsys, *argv) -> tuple[int, str, str]:
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_migrate_is_idempotent_and_redacts_the_url(setup, capsys):
    config, _ = setup
    code, out, _ = _cli(capsys, "migrate", "--config", str(config))
    assert code == 0 and "at revision 0011" in out and "corelata:corelata@" not in out


def test_migrate_unreachable_database(setup, capsys, monkeypatch):
    config, _ = setup
    monkeypatch.setenv("CORELATA_DATABASE_URL", "postgresql://u:secret@127.0.0.1:9/x")
    code, _, err = _cli(capsys, "migrate", "--config", str(config))
    assert code == 1 and "error: cannot connect to the database at postgresql://u:***@" in err
    assert "secret" not in err and len(err.strip().splitlines()) == 1


def test_missing_database_configuration_is_a_usage_error(setup, capsys, monkeypatch):
    config, _ = setup
    monkeypatch.delenv("CORELATA_DATABASE_URL")
    code, _, err = _cli(capsys, "worker", "--burst", "--config", str(config))
    assert code == 2 and "set CORELATA_DATABASE_URL" in err


def test_worker_burst_on_an_empty_queue_exits_and_removes_its_log_handler(setup, capsys):
    config, _ = setup
    before = list(logging.getLogger("corelata").handlers)
    code, _, _ = _cli(capsys, "worker", "--burst", "--config", str(config))
    assert code == 0 and logging.getLogger("corelata").handlers == before


def test_internal_errors_have_no_traceback(setup, capsys, monkeypatch):
    import corelata.cli_ops as ops

    config, _ = setup

    def boom(args):
        raise RuntimeError("kaput")

    monkeypatch.setitem(ops.COMMANDS, "migrate", boom)
    code, _, err = _cli(capsys, "migrate", "--config", str(config))
    assert code == 1 and err.strip() == "error: internal error: RuntimeError: kaput"


def test_ctrl_c_is_reported(setup, capsys, monkeypatch):
    import corelata.cli_ops as ops

    config, _ = setup

    def interrupt(args):
        raise KeyboardInterrupt

    monkeypatch.setitem(ops.COMMANDS, "worker", interrupt)
    code, _, err = _cli(capsys, "worker", "--config", str(config))
    assert code == 130 and err.strip() == "interrupted"


def test_unreachable_database_through_the_queued_commands_exits_1(setup, capsys, monkeypatch):
    config, _ = setup
    monkeypatch.setenv("CORELATA_DATABASE_URL", "postgresql://u:secret@127.0.0.1:9/x")
    code, _, err = _cli(capsys, "worker", "--burst", "--config", str(config))
    assert code == 1 and "cannot connect to the database at postgresql://u:***@" in err
    assert "secret" not in err and len(err.strip().splitlines()) == 1


STATEMENT = "Varna port capacity expansion matters to shippers"


def _run_id(out: str) -> str:
    return re.search(r"run (\S+) queued", out).group(1)


def test_queued_run_lifecycle(setup, capsys, tmp_path):
    config, doc = setup
    args = ["--config", str(config)]
    code, out, _ = _cli(capsys, "run", str(doc), "--project", "p", "--statement", STATEMENT, *args)
    assert code == 0 and "queued in project 'p'" in out
    run_id = _run_id(out)
    code, out, _ = _cli(capsys, "status", run_id, *args)
    assert code == 0 and out.startswith(f"run {run_id}: created")
    assert _cli(capsys, "worker", "--burst", *args)[0] == 0
    code, out, _ = _cli(capsys, "status", run_id, *args)
    assert code == 0 and "completed (clean)" in out and "stages: ingesting@0 ok" in out
    assert "usage: 4 calls" in out and "attempts 1" in out
    code, out, _ = _cli(capsys, "status", run_id, "--json", *args)
    assert code == 0 and json.loads(out)["state"] == "completed"
    out_dir = tmp_path / "export"
    code, out, _ = _cli(capsys, "export", run_id, "--out", str(out_dir), *args)
    assert code == 0 and str(out_dir) in out
    # a report run writes every output but the check run's findings sheet (CRL-94)
    assert {p.name for p in out_dir.iterdir()} == set(OUTPUT_FILES) - {FINDINGS_SHEET}
    code, out, _ = _cli(capsys, "report", str(out_dir), "--format", "md")
    assert code == 0 and out.startswith("UNCLASSIFIED\n")
    assert _cli(capsys, "trace", str(out_dir))[0] == 0
    trace = json.loads((out_dir / "trace.json").read_text(encoding="utf-8"))
    assert trace["run_id"] == run_id and trace["state"] == "completed"


def test_ingest_then_run_by_source_id(setup, capsys):
    config, doc = setup
    args = ["--config", str(config)]
    code, out, _ = _cli(capsys, "ingest", str(doc), "--project", "p", *args)
    assert code == 0
    [sid] = out.split()
    uuid.UUID(sid)
    # the same file again is that source (CRL-126), so the run lists it once
    code, out, _ = _cli(
        capsys,
        "run",
        str(doc),
        "--project",
        "p",
        "--source-id",
        sid,
        "--statement",
        STATEMENT,
        *args,
    )
    assert code == 0
    run_id = _run_id(out)
    assert _cli(capsys, "worker", "--burst", *args)[0] == 0
    assert "completed" in _cli(capsys, "status", run_id, *args)[1]


def test_ingest_and_source_set_state_a_source(setup, capsys):
    """CRL-138: `ingest` takes the statement for each file it adds, and `source set` changes
    it; an empty value clears a field, and a term outside the lexicon is refused."""
    config, doc = setup
    args = ["--config", str(config)]
    code, out, _ = _cli(
        capsys, "ingest", str(doc), "--project", "p", "--origin", "Varna Daily", *args
    )
    assert code == 0
    [sid] = out.split()
    code, out, _ = _cli(capsys, "source", "set", sid, "--project", "p", "--access", "direct", *args)
    assert code == 0
    assert out == f"source {sid}: stated\n  origin: Varna Daily\n  access: direct\n"
    code, _, err = _cli(
        capsys, "source", "set", sid, "--project", "p", "--descriptor", "gossip", *args
    )
    assert code == 2 and "descriptor 'gossip' is not in the lexicon" in err
    code, _, err = _cli(capsys, "source", "set", sid, "--project", "p", *args)
    assert code == 2 and "give at least one of --descriptor" in err
    code, out, _ = _cli(
        capsys,
        "source",
        "set",
        sid,
        "--project",
        "p",
        "--origin",
        "",
        "--access",
        "",
        *args,
    )
    assert code == 0 and out == f"source {sid}: nothing stated\n"
    code, _, err = _cli(capsys, "source", "set", sid, "--project", "nope", "--origin", "x", *args)
    assert code == 2 and "project 'nope' not found" in err


def test_source_id_needs_project(setup, capsys):
    config, _ = setup
    code, _, err = _cli(
        capsys,
        "run",
        "--source-id",
        str(uuid.uuid4()),
        "--statement",
        "x",
        "--config",
        str(config),
    )
    assert code == 2 and "--source-id needs --project" in err


def test_discover_through_the_queue(setup, capsys):
    config, doc = setup
    args = ["--config", str(config)]
    code, out, _ = _cli(
        capsys, "discover", str(doc), "--project", "p", "--audience", "shippers", *args
    )
    assert code == 0
    did = re.search(r"discovery (\S+) queued", out).group(1)
    code, out, _ = _cli(capsys, "status", did, *args)
    assert code == 0 and out.startswith(f"discovery {did}: created")
    assert _cli(capsys, "worker", "--burst", *args)[0] == 0
    code, out, _ = _cli(capsys, "status", did, *args)
    assert code == 0 and "completed" in out and "\n  1. " in out and "shippers" in out
    code, out, _ = _cli(capsys, "status", did, "--json", *args)
    assert json.loads(out)["candidates"]


def test_status_fails_a_discovery_past_the_configured_limits(setup, capsys, pg_url):
    config, doc = setup
    data = yaml.safe_load(config.read_text(encoding="utf-8"))
    data["worker"]["discovery_start_deadline_s"] = 60
    data["worker"]["discovery_deadline_s"] = 90
    config.write_text(yaml.safe_dump(data), encoding="utf-8")
    args = ["--config", str(config)]
    queued, running = (
        re.search(
            r"discovery (\S+) queued",
            _cli(capsys, "discover", str(doc), "--project", "p", *args)[1],
        ).group(1)
        for _ in range(2)
    )
    with psycopg.connect(pg_url) as conn:  # no worker runs; a minute and a half passes
        conn.execute(
            "UPDATE discovery SET created_at = now() - interval '61 seconds' WHERE id = %s",
            (queued,),
        )
        conn.execute(
            "UPDATE discovery SET state = 'running', started_at = now() - interval '91 seconds' "
            "WHERE id = %s",
            (running,),
        )
    code, out, _ = _cli(capsys, "status", queued, *args)
    assert code == 0 and out.startswith(f"discovery {queued}: failed")
    assert (
        "error: Discovery did not start within 1 minute and was stopped: the worker was stopped "
        "or busy with runs. Start a new discovery." in out
    )
    code, out, _ = _cli(capsys, "status", running, *args)
    assert code == 0 and out.startswith(f"discovery {running}: failed")
    assert (
        "error: Discovery did not finish within 90 seconds and was stopped. Start a new discovery."
        in out
    )


def test_cancel_a_queued_run(setup, capsys):
    config, doc = setup
    args = ["--config", str(config)]
    run_id = _run_id(
        _cli(capsys, "run", str(doc), "--project", "p", "--statement", STATEMENT, *args)[1]
    )
    code, out, _ = _cli(capsys, "cancel", run_id, *args)
    assert code == 0 and out.strip() == f"run {run_id} cancelled"
    assert _cli(capsys, "worker", "--burst", *args)[0] == 0
    assert "cancelled" in _cli(capsys, "status", run_id, *args)[1]
    code, _, err = _cli(capsys, "cancel", run_id, *args)
    assert code == 2 and "already cancelled" in err


def test_cancel_a_run_whose_worker_is_gone_uses_the_configured_threshold(setup, capsys, pg_url):
    config, doc = setup  # worker.stalled_after_s: 60
    args = ["--config", str(config)]
    run_id = _run_id(
        _cli(capsys, "run", str(doc), "--project", "p", "--statement", STATEMENT, *args)[1]
    )
    with psycopg.connect(pg_url) as conn:  # a worker took it, then went silent 61 s ago
        conn.execute("UPDATE run SET state = 'drafting', attempts = 1 WHERE id = %s", (run_id,))
        conn.execute("DELETE FROM procrastinate_jobs")
        worker = conn.execute(
            "INSERT INTO procrastinate_workers (last_heartbeat) "
            "VALUES (now() - interval '61 seconds') RETURNING id"
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO procrastinate_jobs (queue_name, task_name, lock, args, status, "
            "worker_id) VALUES ('corelata', 'corelata.run', %s, %s, 'doing', %s)",
            (f"run:{run_id}", json.dumps({"run_id": run_id}), worker),
        )
    code, out, _ = _cli(capsys, "status", run_id, *args)  # CRL-69: said before any cancel
    assert "its worker stopped responding; it starts over when a worker is running again" in out
    with psycopg.connect(pg_url) as conn:
        # a first cancel reached it while it was alive (CRL-49)
        conn.execute("UPDATE run SET cancel_requested = true WHERE id = %s", (run_id,))
    code, out, _ = _cli(capsys, "status", run_id, *args)
    assert "its worker is gone; cancel it again to end it now" in out
    code, out, _ = _cli(capsys, "cancel", run_id, *args)
    assert code == 0 and out.strip() == f"run {run_id} cancelled"


def test_review_accept_and_return(setup, capsys):
    config, doc = setup
    args = ["--config", str(config)]
    run_id = _run_id(
        _cli(capsys, "run", str(doc), "--project", "p", "--statement", STATEMENT, *args)[1]
    )
    code, _, err = _cli(capsys, "review", run_id, "--accept", *args)
    assert code == 2 and "only a completed run" in err
    assert _cli(capsys, "worker", "--burst", *args)[0] == 0
    code, _, err = _cli(capsys, "review", run_id, "--return", *args)
    assert code == 2 and "needs a note" in err
    # the API's note limit holds here too (CRL-111)
    code, _, err = _cli(capsys, "review", run_id, "--return", "--note", "n" * 8001, *args)
    assert code == 2 and "note is at most 8000 characters" in err
    code, out, _ = _cli(capsys, "review", run_id, "--return", "--note", "Tighten the scope.", *args)
    assert code == 0
    child = re.search(r"new run (\S+) queued", out).group(1)
    code, out, _ = _cli(capsys, "status", child, *args)
    assert code == 0 and f"parent: {run_id}" in out
    assert _cli(capsys, "worker", "--burst", *args)[0] == 0
    assert "completed" in _cli(capsys, "status", child, *args)[1]
    code, out, _ = _cli(capsys, "review", child, "--accept", "--actor", "alice", *args)
    assert code == 0 and out.strip() == f"run {child} accepted"
    # an accepted report is final (CRL-21, R-M16-1): the CLI says so as the API does
    code, out, err = _cli(capsys, "review", child, "--return", "--note", "One more pass.", *args)
    assert (code, out) == (2, "")
    assert err.strip() == f"error: run {child} was accepted; start a new run to change it"


def test_export_carries_the_reference_document_and_report_uses_it(setup, capsys, tmp_path):
    config, doc = setup
    pack = write_pack(
        tmp_path / "packs",
        "house",
        rules=[],
        extends="icd203-base",
        template=None,
        lexicon=None,
        profiles={
            "east": {
                "name": "east",
                "extends": "house",
                "format": {"docx_reference": "templates/east.docx"},
            }
        },
    )
    (pack / "templates").mkdir()
    Document().save(str(pack / "templates" / "east.docx"))
    data = yaml.safe_load(config.read_text(encoding="utf-8"))
    data["standards"] = {"packs_dir": str(tmp_path / "packs"), "default_pack": "house"}
    config.write_text(yaml.safe_dump(data), encoding="utf-8")
    args = ["--config", str(config)]
    run_id = _run_id(
        _cli(
            capsys,
            "run",
            str(doc),
            "--project",
            "p",
            "--profile",
            "east",
            "--statement",
            STATEMENT,
            *args,
        )[1]
    )
    assert _cli(capsys, "worker", "--burst", *args)[0] == 0
    out_dir = tmp_path / "export"
    assert _cli(capsys, "export", run_id, "--out", str(out_dir), *args)[0] == 0
    assert (out_dir / "reference.docx").is_file()
    code, _, err = _cli(
        capsys, "report", str(out_dir), "--format", "docx", "--out", str(tmp_path / "again.docx")
    )
    assert code == 0 and err == ""  # no "neutral template" note: the reference was found
    assert (tmp_path / "again.docx").read_bytes() == (out_dir / "report.docx").read_bytes()


def test_unknown_and_malformed_ids(setup, capsys):
    config, _ = setup
    args = ["--config", str(config)]
    code, _, err = _cli(capsys, "status", str(uuid.uuid4()), *args)
    assert code == 2 and "no run or discovery" in err
    code, _, err = _cli(capsys, "status", "nope", *args)
    assert code == 2 and "not a run or discovery id" in err
    code, _, err = _cli(capsys, "cancel", str(uuid.uuid4()), *args)
    assert code == 2 and "not found" in err


def test_unsupported_input_and_missing_file(setup, capsys, tmp_path):
    config, _ = setup
    bad = tmp_path / "x.png"
    bad.write_bytes(b"\x89PNG")
    code, _, err = _cli(capsys, "ingest", str(bad), "--project", "p", "--config", str(config))
    assert code == 2 and "unsupported file type" in err
    code, _, err = _cli(
        capsys, "ingest", str(tmp_path / "missing.txt"), "--project", "p", "--config", str(config)
    )
    assert code == 2 and "input file not found" in err
    code, _, err = _cli(capsys, "ingest", "--project", "p", "--config", str(config))
    assert code == 2 and "at least one input file" in err


def test_an_unmigrated_database_is_refused(setup, capsys, pg_admin, monkeypatch):
    config, doc = setup
    url = create_test_database(pg_admin)
    try:
        monkeypatch.setenv("CORELATA_DATABASE_URL", url)
        code, _, err = _cli(
            capsys,
            "run",
            str(doc),
            "--project",
            "p",
            "--statement",
            STATEMENT,
            "--config",
            str(config),
        )
        assert code == 2 and "run `corelata migrate`" in err
    finally:
        drop_test_database(pg_admin, url)


def test_parent_run_needs_project(setup, capsys):
    config, _ = setup
    code, _, err = _cli(
        capsys,
        "run",
        "--parent-run",
        str(uuid.uuid4()),
        "--statement",
        "x",
        "--config",
        str(config),
    )
    assert code == 2 and "--parent-run needs --project" in err


def test_a_bad_source_id_or_file_creates_no_project(setup, capsys, pg_url):
    config, _ = setup
    args = ["--config", str(config)]
    assert _cli(capsys, "migrate", *args)[0] == 0
    code, _, err = _cli(
        capsys, "run", "--project", "fresh", "--source-id", "not-a-uuid", "--statement", "x", *args
    )
    assert code == 2 and "not a source id" in err
    code, _, err = _cli(capsys, "run", "nope.txt", "--project", "fresh", "--statement", "x", *args)
    assert code != 0 and "not found" in err
    with psycopg.connect(pg_url) as conn:
        assert conn.execute("SELECT count(*) FROM project WHERE name = 'fresh'").fetchone() == (0,)


def test_a_bad_parent_run_creates_no_project(setup, capsys, pg_url):
    config, doc = setup
    args = ["--config", str(config)]
    assert _cli(capsys, "migrate", *args)[0] == 0
    run_id = _run_id(
        _cli(capsys, "run", str(doc), "--project", "first", "--statement", STATEMENT, *args)[1]
    )
    for parent in (str(uuid.uuid4()), run_id):
        code, _, err = _cli(
            capsys,
            *("run", str(doc), "--project", "second", "--statement", "x", "--parent-run", parent),
            *args,
        )
        assert code == 2 and ("not found" in err or "another project" in err)
    with psycopg.connect(pg_url) as conn:
        assert conn.execute("SELECT count(*) FROM project WHERE name = 'second'").fetchone() == (0,)
        assert conn.execute("SELECT count(*) FROM source").fetchone() == (1,)


class _Terminal(io.StringIO):
    """Standard input as an operator's terminal that types `answer`."""

    def isatty(self) -> bool:
        return True


def _typing(monkeypatch, answer: str) -> None:
    monkeypatch.setattr("sys.stdin", _Terminal(answer + "\n" if answer else ""))


def test_delete_source_refuses_a_used_one_then_takes_its_runs_with_with_runs(
    setup, capsys, tmp_path, pg_url
):
    """CRL-125: the operator finds the source's id, is refused while runs used it, and with
    --with-runs it goes with its run, its rows and its files; the audit line is on stderr."""
    config, doc = setup
    args = ["--config", str(config)]
    run_id = _run_id(
        _cli(capsys, "run", str(doc), "--project", "p", "--statement", STATEMENT, *args)[1]
    )
    code, _, err = _cli(capsys, "delete-project", "p", "--yes", *args)
    assert code == 2 and f"1 run not ended yet: {run_id}; cancel" in err
    assert _cli(capsys, "worker", "--burst", *args)[0] == 0
    code, out, _ = _cli(capsys, "sources", "--project", "p", *args)
    [line] = out.splitlines()
    source_id = line.split()[0]
    assert code == 0 and line.endswith("used by 1 run     port.txt")
    code, out, err = _cli(capsys, "delete-source", source_id, "--yes", *args)
    assert code == 2 and out == ""
    assert err.strip() == (
        f"error: source {source_id} (port.txt) was used by 1 run: {run_id}; add --with-runs "
        "to delete those runs and their reports too"
    )
    code, out, err = _cli(capsys, "delete-source", source_id, "--with-runs", "--yes", *args)
    assert code == 0
    assert f"  run {run_id}  completed" in out
    assert out.splitlines()[-1] == (
        f"deleted source {source_id} (port.txt) of project 'p': 1 source, 1 run, 0 discoveries"
    )
    audit = json.loads(err.strip().splitlines()[-1])
    assert audit["logger"] == "corelata.removal" and run_id in audit["message"]
    code, _, err = _cli(capsys, "status", run_id, *args)
    assert code == 2 and f"no run or discovery {run_id}" in err
    files = tmp_path / "files"
    assert not (files / "runs").exists() and not list((files / "projects").rglob("port.txt"))
    with psycopg.connect(pg_url) as conn:
        for table in ("source", "source_unit", "run", "llm_call", "export", "stage_result"):
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,)
        assert conn.execute("SELECT count(*) FROM project").fetchone() == (1,)
    code, _, err = _cli(capsys, "delete-source", source_id, "--yes", *args)
    assert code == 2 and f"source {source_id} not found" in err
    code, _, err = _cli(capsys, "delete-source", "nope", "--yes", *args)
    assert code == 2 and "'nope' is not a source id" in err


def test_delete_asks_at_a_terminal_and_never_without_one(setup, capsys, monkeypatch, pg_url):
    config, doc = setup
    args = ["--config", str(config)]
    assert _cli(capsys, "ingest", str(doc), "--project", "p", *args)[0] == 0
    monkeypatch.setattr("sys.stdin", io.StringIO(""))  # not a terminal: a script or cron
    code, _, err = _cli(capsys, "delete-project", "p", *args)
    assert code == 2 and "needs a terminal to confirm; add --yes" in err
    for answer in ("yes", ""):  # a wrong word, or end of input
        _typing(monkeypatch, answer)
        code, out, err = _cli(capsys, "delete-project", "p", *args)
        assert code == 1 and err.strip() == "not confirmed; nothing was deleted"
        assert "This deletes project 'p' (" in out and "Type 'p' to go on" in out
    with psycopg.connect(pg_url) as conn:
        assert conn.execute("SELECT count(*) FROM source").fetchone() == (1,)
    _typing(monkeypatch, "p")
    code, out, _ = _cli(capsys, "delete-project", "p", *args)
    # the answer is not echoed here as a terminal would, so the result follows the prompt
    assert code == 0 and "go on: deleted project 'p' (" in out.splitlines()[-1]
    with psycopg.connect(pg_url) as conn:
        assert conn.execute("SELECT count(*) FROM project").fetchone() == (0,)
    code, _, err = _cli(capsys, "delete-project", "p", "--yes", *args)
    assert code == 2 and "project 'p' not found" in err
    code, _, err = _cli(capsys, "sources", "--project", "p", *args)
    assert code == 2 and "project 'p' not found" in err


def test_delete_source_asks_for_the_word_delete(setup, capsys, monkeypatch):
    config, doc = setup
    args = ["--config", str(config)]
    [source_id] = _cli(capsys, "ingest", str(doc), "--project", "p", *args)[1].split()
    _typing(monkeypatch, "delete")
    code, out, _ = _cli(capsys, "delete-source", source_id, *args)
    assert code == 0 and "Type 'delete' to go on" in out
    assert _cli(capsys, "sources", "--project", "p", *args)[1] == ""
