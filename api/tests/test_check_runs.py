"""CRL-94: a check run audits an uploaded report against the pack without rewriting it."""

import csv
import io
import json
import uuid

from tests.conftest import complete_queued, project_with_source

REPORT = (
    "# Varna port outlook\n\nUNCLASSIFIED\n\n## Key judgments\n\n"
    "It is likely that the Varna port capacity expansion matters to shippers.\n\n"
    "Shipping lines will very likely move their Black Sea hubs to Varna by 2027.\n\n"
    "## Analysis\n\nThe port of Varna handles grain, containers and general cargo.\n"
)


async def _report_source(api, pid: str) -> str:
    upload = await api.client.post(
        f"/api/projects/{pid}/sources",
        files={"file": ("outlook.md", REPORT.encode(), "text/markdown")},
    )
    assert upload.status_code == 201, upload.text
    return upload.json()[0]["id"]


async def test_a_check_run_audits_the_report_and_exports_a_findings_sheet(api):
    pid, sid = await project_with_source(api)
    rid = await _report_source(api, pid)
    started = await api.client.post(
        "/api/runs",
        json={"project_id": pid, "source_ids": [sid], "kind": "check", "report_source_id": rid},
    )
    assert started.status_code == 202, started.text
    run = started.json()
    assert run["kind"] == "check" and run["report_source_id"] == rid
    assert run["value_statement"] == "" and run["source_ids"] == [sid]
    assert await complete_queued(api) == 1
    done = (await api.client.get(f"/api/runs/{run['run_id']}")).json()
    assert done["state"] == "completed" and done["status"] == "findings_open"
    assert [s["stage"] for s in done["stages"]] == [
        "ingesting",
        "structuring",
        "auditing",
        "rendering",
    ]
    listed = (await api.client.get("/api/runs", params={"project_id": pid})).json()["runs"]
    assert [r["kind"] for r in listed] == ["check"]

    trace = json.loads(
        (await api.client.get(f"/api/runs/{run['run_id']}/exports/trace.json")).content
    )
    assert trace["kind"] == "check" and trace["checked_report"]["id"] == "report"
    claims = trace["report"]["claims"]
    assert [c["text"] for c in claims if not c["evidence"]] == [
        "Shipping lines will very likely move their Black Sea hubs to Varna by 2027."
    ]
    assert len(trace["findings"]) == len(trace["pack_snapshot"]["rules"])  # one per rule

    sheet = await api.client.get(f"/api/runs/{run['run_id']}/exports/findings.csv")
    assert sheet.status_code == 200 and sheet.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(sheet.text)))
    assert len(rows) == len(trace["pack_snapshot"]["rules"])
    tc8 = next(r for r in rows if r["rule_id"] == "icd203.tc.8")
    assert tc8["verdict"] == "fail" and tc8["title"]

    html = await api.client.get(f"/api/runs/{run['run_id']}/report", params={"with_claim_ids": 1})
    assert html.status_code == 200 and "Shipping lines will very likely" in html.text

    review = await api.client.post(f"/api/runs/{run['run_id']}/review", json={"action": "accept"})
    assert review.status_code == 409 and "is a check" in review.json()["detail"]
    project = (await api.client.get(f"/api/projects/{pid}")).json()
    assert project["reports_to_review"] == 0  # a check takes no decision


async def test_a_report_runs_reads_as_kind_report(api):
    pid, sid = await project_with_source(api)
    run = await api.client.post(
        "/api/runs", json={"project_id": pid, "source_ids": [sid], "value_statement": "Varna"}
    )
    assert run.json()["kind"] == "report" and run.json()["report_source_id"] is None


async def test_check_requests_are_validated(api):
    pid, sid = await project_with_source(api)
    rid = await _report_source(api, pid)
    base = {"project_id": pid, "source_ids": [sid], "kind": "check", "report_source_id": rid}

    async def post(**changes):
        body = {**base, **changes}
        return await api.client.post("/api/runs", json={k: v for k, v in body.items() if v != ...})

    missing = await post(report_source_id=...)
    assert missing.status_code == 422 and "needs report_source_id" in missing.json()["detail"]
    both = await post(source_ids=[sid, rid])
    assert both.status_code == 422 and "cannot also be one of its sources" in both.json()["detail"]
    parent = await post(parent_run_id=str(uuid.uuid4()))
    assert parent.status_code == 422 and "no parent run" in parent.json()["detail"]
    stray = await post(kind="report", value_statement="Varna")
    assert stray.status_code == 422 and "is for a check" in stray.json()["detail"]
    blank = await post(kind="report", report_source_id=..., value_statement=" ")
    assert blank.status_code == 422 and "needs a value statement" in blank.json()["detail"]
    other = await post(report_source_id=str(uuid.uuid4()))
    assert other.status_code == 404 and "not in project" in other.json()["detail"]
    assert api.queue.jobs == []
