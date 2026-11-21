import asyncio
import contextlib
import gc
import hashlib
import io
import json
import re
import uuid
from collections.abc import Iterator

import httpx
import yaml
from corelata import service
from corelata.exports import OUTPUT_FILES
from corelata.schema import Finding
from corelata.storage import LocalStorage
from corelata.store import records, runs
from corelata.trace import ClaimProvenance, RunTrace, claim_provenance, run_trace
from docx import Document
from pydantic import TypeAdapter
from sqlalchemy import event, text

from corelata_api.headers import REPORT_CSP
from corelata_api.routes import reports
from tests.conftest import (
    STATEMENT,
    complete_queued,
    project_with_source,
    set_run_state,
    start_run,
)

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


async def _completed(api) -> dict:
    run = await start_run(api)
    assert await complete_queued(api) == 1
    progress = (await api.client.get(f"/api/runs/{run['run_id']}")).json()
    assert progress["state"] == "completed", progress
    return progress


async def _second_run(api) -> dict:
    """A queued, unexecuted run in a second project (start_run's project name is taken)."""
    pid, sid = await project_with_source(api, "second")
    response = await api.client.post(
        "/api/runs", json={"project_id": pid, "source_ids": [sid], "value_statement": STATEMENT}
    )
    assert response.status_code == 202, response.text
    return response.json()


async def _export_rows(api, run_id: str) -> dict[str, str]:
    async with api.db.session() as s:
        return {r.name: r.sha256 for r in await runs.list_exports(s, uuid.UUID(run_id))}


async def test_stored_report_bytes_match_the_export_row(api):
    run = await _completed(api)
    rows = await _export_rows(api, run["run_id"])
    assert set(rows) == {
        "trace.json",
        "gate.json",
        "report.json",
        "report.md",
        "report.html",
        "report.docx",
    }
    for fmt, media in (
        ("json", "application/json"),
        ("md", "text/markdown; charset=utf-8"),
        ("html", "text/html; charset=utf-8"),
        ("docx", DOCX),
    ):
        response = await api.client.get(f"/api/runs/{run['run_id']}/report", params={"format": fmt})
        assert response.status_code == 200, (fmt, response.text)
        assert response.headers["content-type"] == media
        assert hashlib.sha256(response.content).hexdigest() == rows[f"report.{fmt}"]
        disposition = response.headers["content-disposition"]
        assert disposition.startswith("attachment;" if fmt == "docx" else "inline;")
        assert f'filename="report-{run["run_id"][:8]}.{fmt}"' in disposition
    forced = await api.client.get(
        f"/api/runs/{run['run_id']}/report", params={"format": "html", "download": "true"}
    )
    assert forced.headers["content-disposition"].startswith("attachment;")
    default = await api.client.get(f"/api/runs/{run['run_id']}/report")
    assert default.headers["content-type"] == "text/html; charset=utf-8"
    docx = await api.client.get(f"/api/runs/{run['run_id']}/report", params={"format": "docx"})
    assert Document(io.BytesIO(docx.content)).paragraphs


async def test_html_reports_and_exports_carry_a_sandbox_policy(api):
    """CRL-68: an HTML report opened at the app's origin runs sandboxed, with no script and
    nothing loaded but its inline stylesheet; the other formats carry no policy of their own."""
    run = await _completed(api)
    base = f"/api/runs/{run['run_id']}"
    for path, params in (
        (f"{base}/report", {"format": "html"}),
        (f"{base}/report", {"format": "html", "with_claim_ids": "true"}),
        (f"{base}/report", {"format": "html", "download": "true"}),
        (f"{base}/exports/report.html", {}),
    ):
        response = await api.client.get(path, params=params)
        assert response.status_code == 200, (path, params)
        assert response.headers["content-security-policy"] == REPORT_CSP, (path, params)
    # the policy the operator guide states, word for word
    assert REPORT_CSP == (
        "sandbox; default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'"
    )
    for path, params in (
        (f"{base}/report", {"format": "md"}),
        (f"{base}/report", {"format": "json"}),
        (f"{base}/exports/trace.json", {}),
    ):
        response = await api.client.get(path, params=params)
        assert "content-security-policy" not in response.headers, (path, params)
        assert response.headers["x-content-type-options"] == "nosniff"


async def test_claim_ids_re_render(api):
    run = await _completed(api)
    plain = await api.client.get(f"/api/runs/{run['run_id']}/report", params={"format": "html"})
    marked = await api.client.get(
        f"/api/runs/{run['run_id']}/report", params={"format": "html", "with_claim_ids": "true"}
    )
    assert marked.status_code == 200 and marked.text != plain.text
    assert 'class="claim-ids"' in marked.text and 'class="claim-ids"' not in plain.text
    assert 'class="source-refs"' in plain.text  # source references show either way (CRL-96)
    docx = await api.client.get(
        f"/api/runs/{run['run_id']}/report", params={"format": "docx", "with_claim_ids": "true"}
    )
    assert docx.status_code == 200 and docx.content[:2] == b"PK"
    rows = await _export_rows(api, run["run_id"])
    assert hashlib.sha256(docx.content).hexdigest() != rows["report.docx"]


async def test_report_before_completion_is_409(api):
    run = await start_run(api)
    for state in ("created", "drafting", "gate_rejected", "failed", "cancelled"):
        await set_run_state(api.db, run["run_id"], state)
        response = await api.client.get(f"/api/runs/{run['run_id']}/report")
        assert response.status_code == 409, state
        assert response.json()["detail"] == f"run {run['run_id']} has no report (state {state})"
    assert (await api.client.get(f"/api/runs/{uuid.uuid4()}/report")).status_code == 404
    bad = await api.client.get(f"/api/runs/{run['run_id']}/report", params={"format": "pdf"})
    assert bad.status_code == 422


async def test_report_docx_export_error_is_409(api):
    run = await _completed(api)
    async with api.db.session() as s, s.begin():
        row = await runs.get_run(s, uuid.UUID(run["run_id"]), lock=True)
        row.export_error = "DOCX export failed: reference document is not a DOCX"
        for export in await runs.list_exports(s, row.id):
            if export.name == "report.docx":
                await s.delete(export)
    response = await api.client.get(f"/api/runs/{run['run_id']}/report", params={"format": "docx"})
    assert response.status_code == 409
    assert response.json()["detail"] == "DOCX export failed: reference document is not a DOCX"
    again = await api.client.get(
        f"/api/runs/{run['run_id']}/report", params={"format": "docx", "with_claim_ids": "true"}
    )
    assert again.status_code == 409
    assert again.json()["detail"] == "DOCX export failed: reference document is not a DOCX"
    html = await api.client.get(f"/api/runs/{run['run_id']}/report", params={"format": "html"})
    assert html.status_code == 200


async def test_stored_exports_by_name(api):
    run = await _completed(api)
    rows = await _export_rows(api, run["run_id"])
    for name, media in (
        ("trace.json", "application/json"),
        ("gate.json", "application/json"),
        ("report.md", "text/markdown; charset=utf-8"),
    ):
        response = await api.client.get(f"/api/runs/{run['run_id']}/exports/{name}")
        assert response.status_code == 200, name
        assert response.headers["content-type"] == media
        assert hashlib.sha256(response.content).hexdigest() == rows[name]
        assert response.headers["content-disposition"].startswith("attachment;")
    trace = json.loads(
        (await api.client.get(f"/api/runs/{run['run_id']}/exports/trace.json")).content
    )
    assert trace["run_id"] == run["run_id"] and trace["schema_version"] == "1"
    assert (await api.client.get(f"/api/runs/{run['run_id']}/exports/notes.txt")).status_code == 422
    fresh = await _second_run(api)
    missing = await api.client.get(f"/api/runs/{fresh['run_id']}/exports/trace.json")
    assert missing.status_code == 404 and "no stored export trace.json" in missing.json()["detail"]
    assert (await api.client.get(f"/api/runs/{uuid.uuid4()}/exports/trace.json")).status_code == 404


async def test_trace_findings_and_claims(api):
    run = await _completed(api)
    trace = await api.client.get(f"/api/runs/{run['run_id']}/trace")
    assert trace.status_code == 200
    body = trace.json()
    assert body["summary"]["run_id"] == run["run_id"] and body["summary"]["state"] == "completed"
    assert [(d["role"], d["iteration"]) for d in body["drafts"]] == [("writer", 0), ("conveyor", 0)]
    assert body["drafts"][0]["changes"] is None and body["drafts"][1]["changes"]["title_changed"]
    assert [c["role"] for c in body["calls"]] == ["gate", "writer", "conveyor", "auditor"]
    assert "request" not in body["calls"][0]
    findings = await api.client.get(f"/api/runs/{run['run_id']}/findings")
    assert findings.status_code == 200 and findings.json()
    assert {f["iteration"] for f in findings.json()} == {0}
    assert all(
        f["verdict"] in ("pass", "fail", "attested", "not_applicable") for f in findings.json()
    )
    report = json.loads(
        (await api.client.get(f"/api/runs/{run['run_id']}/exports/report.json")).content
    )
    claim_id = report["claims"][0]["id"]
    claim = await api.client.get(f"/api/runs/{run['run_id']}/claims/{claim_id}")
    assert claim.status_code == 200
    assert claim.json()["claim"]["id"] == claim_id and claim.json()["evidence"]
    assert claim.json()["evidence"][0]["source_name"] == "port.txt"
    unknown = await api.client.get(f"/api/runs/{run['run_id']}/claims/c999")
    assert unknown.status_code == 404
    fresh = await _second_run(api)
    assert (await api.client.get(f"/api/runs/{fresh['run_id']}/trace")).status_code == 200
    assert (await api.client.get(f"/api/runs/{fresh['run_id']}/findings")).json() == []
    no_report = await api.client.get(f"/api/runs/{fresh['run_id']}/claims/c1")
    assert no_report.status_code == 409 and "has no report" in no_report.json()["detail"]


async def test_export_names_are_the_output_files():
    assert set(reports.ExportName.__args__) == set(OUTPUT_FILES)


async def test_missing_stored_report_is_404(api):
    run = await _completed(api)
    async with api.db.session() as s, s.begin():
        for export in await runs.list_exports(s, uuid.UUID(run["run_id"])):
            if export.name == "report.html":
                await s.delete(export)
    response = await api.client.get(f"/api/runs/{run['run_id']}/report", params={"format": "html"})
    assert response.status_code == 404
    assert response.json()["detail"] == f"run {run['run_id']} has no stored export report.html"


async def test_docx_re_render_uses_the_stored_reference(make_api, tmp_path):
    team = tmp_path / "packs" / "team"
    (team / "rules").mkdir(parents=True)
    (team / "profiles").mkdir()
    (team / "pack.yaml").write_text(
        yaml.safe_dump({"name": "team", "version": "1.0", "extends": "icd203-base"}),
        encoding="utf-8",
    )
    Document().save(str(team / "ref.docx"))
    (team / "profiles" / "branded.yaml").write_text(
        yaml.safe_dump(
            {"name": "branded", "extends": "team", "format": {"docx_reference": "ref.docx"}}
        ),
        encoding="utf-8",
    )
    standards = {"packs_dir": str(tmp_path / "packs"), "default_pack": "team"}
    async with make_api(standards=standards) as api:
        run = await start_run(api, profile="branded")
        assert await complete_queued(api) == 1
        run_id = run["run_id"]
        assert (await api.client.get(f"/api/runs/{run_id}")).json()["state"] == "completed"
        storage = LocalStorage(api.cfg.storage.path)
        assert await service.reference_document(api.db, storage, uuid.UUID(run_id)) is not None
        rows = await _export_rows(api, run_id)
        docx = await api.client.get(
            f"/api/runs/{run_id}/report", params={"format": "docx", "with_claim_ids": "true"}
        )
        assert docx.status_code == 200 and docx.content[:2] == b"PK"
        assert hashlib.sha256(docx.content).hexdigest() != rows["report.docx"]


async def test_re_render_failures(api, monkeypatch):
    run = await _completed(api)

    def boom(*args, **kwargs):
        raise ValueError("")

    monkeypatch.setattr(reports, "_render", boom)
    docx = await api.client.get(
        f"/api/runs/{run['run_id']}/report", params={"format": "docx", "with_claim_ids": "true"}
    )
    assert docx.status_code == 409
    assert docx.json()["detail"] == "DOCX export failed: ValueError"
    html = await api.client.get(
        f"/api/runs/{run['run_id']}/report", params={"format": "html", "with_claim_ids": "true"}
    )
    assert html.status_code == 500 and html.json() == {"detail": "internal error"}


async def test_stored_report_does_not_load_the_record(api, monkeypatch):
    run = await _completed(api)

    async def forbidden(db, run_id):
        raise AssertionError("the stored path must not load the record")

    monkeypatch.setattr(reports.service, "get_run_record", forbidden)
    for fmt in ("json", "md", "html", "docx"):
        response = await api.client.get(f"/api/runs/{run['run_id']}/report", params={"format": fmt})
        assert response.status_code == 200, (fmt, response.text)
    exports = await api.client.get(f"/api/runs/{run['run_id']}/exports/trace.json")
    assert exports.status_code == 200


async def test_claim_ids_render_is_cached_per_run_and_format(api, monkeypatch):
    run = await _completed(api)
    real = reports._render
    calls: list[str] = []

    def counting(record, fmt, **kw):
        calls.append(fmt)
        return real(record, fmt, **kw)

    monkeypatch.setattr(reports, "_render", counting)
    url = f"/api/runs/{run['run_id']}/report"
    first = await api.client.get(url, params={"format": "html", "with_claim_ids": "1"})
    second = await api.client.get(url, params={"format": "html", "with_claim_ids": "1"})
    assert first.status_code == second.status_code == 200
    assert first.content == second.content and "data-claim-ids" in first.text
    md = await api.client.get(url, params={"format": "md", "with_claim_ids": "1"})
    assert md.status_code == 200
    assert calls == ["html", "md"]  # one render per (run, format)
    assert len(api.app.state.ctx.renders) == 2


async def test_a_deleted_run_is_not_served_from_the_cache(api):
    run = await _completed(api)
    url = f"/api/runs/{run['run_id']}/report"
    cached = await api.client.get(url, params={"format": "html", "with_claim_ids": "1"})
    assert cached.status_code == 200
    async with api.db.session() as s, s.begin():
        await runs.delete_project(s, uuid.UUID(run["project_id"]))
    gone = await api.client.get(url, params={"format": "html", "with_claim_ids": "1"})
    assert gone.status_code == 404


async def test_a_claim_id_miss_reads_the_run_twice_and_a_hit_once(api, monkeypatch):
    run = await _completed(api)
    reads: list[str] = []
    real_progress, real_record = reports.service.run_progress, reports.service.get_run_record

    async def progress(db, run_id):
        reads.append("progress")
        return await real_progress(db, run_id)

    async def record(db, run_id):
        reads.append("record")
        return await real_record(db, run_id)

    monkeypatch.setattr(reports.service, "run_progress", progress)
    monkeypatch.setattr(reports.service, "get_run_record", record)
    url = f"/api/runs/{run['run_id']}/report"
    params = {"format": "html", "with_claim_ids": "1"}
    assert (await api.client.get(url, params=params)).status_code == 200
    assert reads == ["progress", "record"]  # the state check, then the record for the render
    reads.clear()
    assert (await api.client.get(url, params=params)).status_code == 200
    assert reads == ["progress"]  # a hit: the state check only


async def test_a_failed_claim_id_render_is_not_cached_and_a_docx_one_is(api, monkeypatch):
    run = await _completed(api)
    real = reports._render
    calls: list[str] = []

    def flaky(record, fmt, **kw):
        calls.append(fmt)
        if len(calls) == 1:
            raise ValueError("renderer crashed")
        return real(record, fmt, **kw)

    monkeypatch.setattr(reports, "_render", flaky)
    renders = api.app.state.ctx.renders
    url = f"/api/runs/{run['run_id']}/report"
    failed = await api.client.get(url, params={"format": "html", "with_claim_ids": "1"})
    assert failed.status_code == 500 and len(renders) == 0
    retried = await api.client.get(url, params={"format": "html", "with_claim_ids": "1"})
    assert retried.status_code == 200 and renders.get(run["run_id"], "html") == retried.content
    for _ in range(2):
        docx = await api.client.get(url, params={"format": "docx", "with_claim_ids": "1"})
        assert docx.status_code == 200 and docx.content[:2] == b"PK"
    assert calls == ["html", "html", "docx"]  # the DOCX was rendered once, then served cached
    assert renders.get(run["run_id"], "docx") == docx.content


async def test_concurrent_claim_id_renders_for_65_runs_keep_64_entries(api, monkeypatch):
    run = await _completed(api)
    completed = await service.run_progress(api.db, uuid.UUID(run["run_id"]))
    record = await service.get_run_record(api.db, uuid.UUID(run["run_id"]))

    async def any_progress(db, run_id):
        await asyncio.sleep(0)  # let the other requests interleave
        return completed

    async def any_record(db, run_id):
        await asyncio.sleep(0)
        return record

    monkeypatch.setattr(reports.service, "run_progress", any_progress)
    monkeypatch.setattr(reports.service, "get_run_record", any_record)
    ids = [str(uuid.uuid4()) for _ in range(65)]
    params = {"format": "html", "with_claim_ids": "1"}
    responses = await asyncio.gather(
        *(api.client.get(f"/api/runs/{i}/report", params=params) for i in ids)
    )
    assert {r.status_code for r in responses} == {200}
    assert len({r.content for r in responses}) == 1
    renders = api.app.state.ctx.renders
    assert len(renders) == 64
    assert renders.total_bytes == 64 * len(responses[0].content)
    assert sum(renders.get(i, "html") is None for i in ids) == 1  # exactly one was evicted


async def test_the_render_budget_comes_from_the_config(make_api):
    async with make_api() as api:
        assert api.app.state.ctx.renders.max_bytes == 64 * 1024 * 1024
    async with make_api(api={"progress_poll_s": 0.02, "render_cache_mb": 0}) as api:
        run = await _completed(api)
        url = f"/api/runs/{run['run_id']}/report"
        served = await api.client.get(url, params={"format": "html", "with_claim_ids": "1"})
        assert served.status_code == 200 and "data-claim-ids" in served.text
        assert len(api.app.state.ctx.renders) == 0  # served, never stored


@contextlib.contextmanager
def _statements(api) -> Iterator[list[str]]:
    """Every SQL statement the app's own engine sends while the block runs."""
    seen: list[str] = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        seen.append(statement)

    engine = api.app.state.ctx.db.engine.sync_engine
    event.listen(engine, "before_cursor_execute", capture)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", capture)


@contextlib.contextmanager
def _executed(api) -> Iterator[list[tuple[str, object]]]:
    """`_statements` with each statement's bound parameters."""
    seen: list[tuple[str, object]] = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        seen.append((statement, parameters))

    engine = api.app.state.ctx.db.engine.sync_engine
    event.listen(engine, "before_cursor_execute", capture)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", capture)


def _values(parameters: object) -> list[object]:
    """Every bound value, however the driver nests them."""
    if isinstance(parameters, dict):
        return [v for p in parameters.values() for v in _values(p)]
    if isinstance(parameters, (list, tuple)):
        return [v for p in parameters for v in _values(p)]
    return [parameters]


def _tables(statements: list[str]) -> set[str]:
    return {t for st in statements for t in re.findall(r"\bFROM (\w+)", st)}


async def test_trace_findings_and_claim_reads_skip_the_stored_model_io(api):
    """CRL-103: the three review reads answer byte for byte as they did from the whole record,
    and none of them selects a model call's stored request or response."""
    run = await _completed(api)
    run_id = uuid.UUID(run["run_id"])
    async with api.db.session() as s:
        whole = await records.load_record(s, run_id)
    assert whole.llm_calls and all(c.request and c.response for c in whole.llm_calls)
    assert whole.report is not None and whole.findings
    claim_id = whole.report.claims[0].id
    expected = {
        "trace": TypeAdapter(RunTrace).dump_json(run_trace(whole)),
        "findings": TypeAdapter(list[Finding]).dump_json(whole.findings),
        f"claims/{claim_id}": TypeAdapter(ClaimProvenance).dump_json(
            claim_provenance(whole, claim_id)
        ),
    }
    read: dict[str, set[str]] = {}
    for path, body in expected.items():
        with _statements(api) as seen:
            response = await api.client.get(f"/api/runs/{run_id}/{path}")
        assert response.status_code == 200, (path, response.text)
        assert response.content == body, path
        assert not [st for st in seen if re.search(r"llm_call\.(request|response)\b", st)], path
        read[path.split("/")[0]] = _tables(seen)
    assert "llm_call" in read["trace"]
    assert read["findings"] == {"audit_finding"}
    assert read["claims"] <= {"run", "run_source", "source", "source_unit"}, read["claims"]
    assert "source_unit" in read["claims"]


async def test_trace_findings_and_claims_of_an_unknown_run_are_404(api):
    for path in ("trace", "findings", "claims/c1"):
        response = await api.client.get(f"/api/runs/{uuid.uuid4()}/{path}")
        assert response.status_code == 404, path
        assert response.json()["detail"].endswith("not found"), path


async def test_a_completed_run_without_a_stored_report_is_409_on_a_claim_id_render(api):
    run = await start_run(api)
    await set_run_state(api.db, run["run_id"], "completed")
    response = await api.client.get(
        f"/api/runs/{run['run_id']}/report", params={"with_claim_ids": "true"}
    )
    assert response.status_code == 409
    assert response.json()["detail"] == f"run {run['run_id']} has no report (state completed)"


PROBE_EVERY_S = 0.01


async def _widen_source(api, run_id: uuid.UUID, extra: int) -> None:
    """Append `extra` paragraph units (about 7.7 MB at 40,000) to the run's one source, after its
    own units, so the claims keep citing what they cited."""
    async with api.db.session() as s, s.begin():
        (source_id,) = await runs.run_source_ids(s, run_id)
        await s.execute(
            text(
                "INSERT INTO source_unit (source_id, ordinal, unit_id, text, locator, kind, meta) "
                "SELECT :sid, 1000 + n, 'w' || n, repeat('Grain moves through Varna. ', 7), "
                "'para ' || n, 'paragraph', '{}'::jsonb FROM generate_series(1, :extra) AS n"
            ),
            {"sid": source_id, "extra": extra},
        )


async def _with_health_probes(api, path: str) -> tuple[httpx.Response, float]:
    """`path`'s response, and the slowest /api/health call of those made every 10 ms while it was
    in flight (at least one). The client is in process, so a probe measures from when it was due:
    a read that holds the event loop delays it as it would delay a browser's request."""
    gc.collect()  # a full collection the test's earlier allocations owe does not land in the window
    loop = asyncio.get_running_loop()
    read = asyncio.create_task(api.client.get(path))
    slowest = 0.0
    while True:
        due = loop.time() + PROBE_EVERY_S
        await asyncio.sleep(PROBE_EVERY_S)
        health = await api.client.get("/api/health")
        slowest = max(slowest, loop.time() - due)
        assert health.status_code == 200
        if read.done():
            return await read, slowest


async def test_claim_and_trace_reads_of_a_40000_unit_source_leave_the_loop_free(api):
    """CRL-124: a claim read fetches only the units its evidence names, the trace counts units
    without reading their text, and neither holds the event loop while a large source is read."""
    run = await _completed(api)
    run_id = uuid.UUID(run["run_id"])
    async with api.db.session() as s:
        before = await records.load_record(s, run_id)
    assert before.report is not None
    claim = next(c for c in before.report.claims if c.evidence)
    expected_claim = TypeAdapter(ClaimProvenance).dump_json(claim_provenance(before, claim.id))
    own_units = len(before.sources[0].units)
    for path in (f"claims/{claim.id}", "trace"):  # first requests warm caches and the thread pool
        assert (await api.client.get(f"/api/runs/{run_id}/{path}")).status_code == 200
    await _widen_source(api, run_id, 40_000)

    with _executed(api) as seen:
        response, slowest = await _with_health_probes(api, f"/api/runs/{run_id}/claims/{claim.id}")
    assert response.status_code == 200, response.text
    assert response.content == expected_claim
    unit_reads = [(st, p) for st, p in seen if re.search(r"\bFROM source_unit\b", st)]
    assert len(unit_reads) == 1, unit_reads  # one statement, naming the evidence units alone
    bound = {v for v in _values(unit_reads[0][1]) if isinstance(v, str)}
    assert {ref.split("/")[1] for ref in claim.evidence} <= bound
    assert not any(v.startswith("w") and v[1:].isdigit() for v in bound)
    assert len(seen) <= 5, seen
    assert slowest < 0.1, f"claim read held /api/health for {slowest:.3f} s"

    with _executed(api) as seen:
        response, slowest = await _with_health_probes(api, f"/api/runs/{run_id}/trace")
    assert response.status_code == 200, response.text
    (summary_source,) = response.json()["summary"]["sources"]
    assert summary_source["units"] == own_units + 40_000
    assert not [st for st, _ in seen if re.search(r"source_unit\.text\b", st)]
    assert slowest < 0.1, f"trace read held /api/health for {slowest:.3f} s"
