"""CRL-138: what the analyst states about a source, through the API: set at upload or with
PATCH, carried verbatim into a run's report, labelled in its trace and kept by the run."""

import json
import uuid

from tests.conftest import PORT_TEXT, STATEMENT, complete_queued, project_with_source


async def _patch(api, pid, sid, **body):
    return await api.client.patch(f"/api/projects/{pid}/sources/{sid}", json=body)


async def test_patch_sets_clears_and_checks_the_statement(api):
    pid, sid = await project_with_source(api)
    [before] = (await api.client.get(f"/api/projects/{pid}/sources")).json()
    assert "stated" not in before  # nothing stated: the payload reads as before
    edited = await _patch(api, pid, sid, origin="Varna Daily", access="direct")
    assert edited.status_code == 200, edited.text
    assert edited.json() == {**before, "stated": {"origin": "Varna Daily", "access": "direct"}}
    again = await _patch(api, pid, sid, origin="", descriptor="open-source report")
    assert again.json()["stated"] == {"descriptor": "open-source report", "access": "direct"}
    [listed] = (await api.client.get(f"/api/projects/{pid}/sources")).json()
    assert listed == again.json()
    bad = await _patch(api, pid, sid, access="rumour")
    assert bad.status_code == 422 and "access 'rumour' is not in the lexicon" in bad.text
    long = await _patch(api, pid, sid, origin="x" * 501)
    assert long.status_code == 422
    assert (await _patch(api, pid, uuid.uuid4(), origin="x")).status_code == 404
    other = (await api.client.post("/api/projects", json={"name": "other"})).json()["id"]
    assert (await _patch(api, other, sid, origin="x")).status_code == 404
    cleared = await _patch(api, pid, sid, descriptor="", access="")
    assert cleared.json() == before


async def test_upload_takes_the_statement_as_form_fields(api):
    pid = (await api.client.post("/api/projects", json={"name": "p"})).json()["id"]

    async def upload(data: bytes, **form):
        return await api.client.post(
            f"/api/projects/{pid}/sources",
            files={"file": ("port.txt", data, "text/plain")},
            data=form,
        )

    refused = await upload(PORT_TEXT.encode(), descriptor="gossip")
    assert refused.status_code == 422 and "descriptor 'gossip'" in refused.text
    assert (await api.client.get(f"/api/projects/{pid}/sources")).json() == []
    added = await upload(PORT_TEXT.encode(), origin="Varna Daily", date_of_information="2026")
    assert added.status_code == 201, added.text
    assert added.json()[0]["stated"] == {"date_of_information": "2026", "origin": "Varna Daily"}
    again = await upload(PORT_TEXT.encode(), reliability_note="Checked.")
    assert again.status_code == 200 and again.json()[0]["stated"] == {
        "reliability_note": "Checked.",
        "date_of_information": "2026",
        "origin": "Varna Daily",
    }


async def test_a_run_carries_the_statement_and_keeps_it_after_an_edit(api):
    pid, sid = await project_with_source(api)
    await _patch(api, pid, sid, origin="Varna Daily", descriptor="open-source media article")
    started = await api.client.post(
        "/api/runs",
        json={"project_id": pid, "source_ids": [sid], "value_statement": STATEMENT},
    )
    assert started.status_code == 202, started.text
    run_id = started.json()["run_id"]
    await _patch(api, pid, sid, origin="Port press office")  # after queueing: not this run's
    assert await complete_queued(api) == 1
    report = json.loads((await api.client.get(f"/api/runs/{run_id}/exports/report.json")).content)
    [entry] = report["sources"]
    assert (entry["origin"], entry["descriptor"]) == ("Varna Daily", "open-source media article")
    summary = (await api.client.get(f"/api/runs/{run_id}/trace")).json()["summary"]
    assert summary["sources"][0]["stated"] == {
        "descriptor": "open-source media article",
        "origin": "Varna Daily",
    }
    trace = json.loads((await api.client.get(f"/api/runs/{run_id}/exports/trace.json")).content)
    drafting = next(s for s in trace["stages"] if s["stage"] == "drafting")
    assert {o["field"] for o in drafting["output"]["stated_overrides"]} == {
        "descriptor",
        "origin",
    }
    assert trace["sources"][0]["stated"]["origin"] == "Varna Daily"
