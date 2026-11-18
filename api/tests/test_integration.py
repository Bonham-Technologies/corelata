"""The analyst's path through the API: upload, start, watch, read, return, rerun — with the
in-test worker executing each queued job against the fake model."""

import json

from tests.conftest import PORT_TEXT, STATEMENT, complete_queued, project_with_source


def _events(body: str) -> list[dict]:
    out = []
    for block in body.split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if lines.get("event") == "progress":
            out.append(json.loads(lines["data"]))
    return out


async def test_upload_run_review_and_rerun(api):
    pid, sid = await project_with_source(api, "Black Sea")
    second = await api.client.post(
        f"/api/projects/{pid}/sources",
        files={"file": ("more.md", f"# Notes\n\n{PORT_TEXT}".encode(), "text/markdown")},
    )
    assert second.status_code == 201
    discovery = await api.client.post(
        "/api/discoveries", json={"project_id": pid, "source_ids": [sid, second.json()[0]["id"]]}
    )
    assert discovery.status_code == 202
    assert await complete_queued(api) == 1
    found = (await api.client.get(f"/api/discoveries/{discovery.json()['discovery_id']}")).json()
    assert found["state"] == "completed" and len(found["candidates"]) == 2
    assert found["usage"]["calls"] == 1

    started = await api.client.post(
        "/api/runs",
        json={
            "project_id": pid,
            "source_ids": [sid],
            "value_statement": found["candidates"][0]["text"] or STATEMENT,
            "max_iterations": 1,
        },
    )
    assert started.status_code == 202
    run_id = started.json()["run_id"]
    assert await complete_queued(api) == 1
    events = _events((await api.client.get(f"/api/runs/{run_id}/events")).text)
    assert [e["state"] for e in events] == ["completed"]
    assert [s["stage"] for s in events[0]["stages"]] == [
        "ingesting",
        "gating",
        "drafting",
        "conveying",
        "auditing",
        "rendering",
    ]
    assert events[0]["status"] == "clean" and events[0]["usage"]["calls"] == 4

    html = await api.client.get(f"/api/runs/{run_id}/report")
    assert html.status_code == 200 and "<h1" in html.text.lower()
    trace = (await api.client.get(f"/api/runs/{run_id}/trace")).json()
    assert trace["summary"]["sources"][0]["name"] == "port.txt"
    assert trace["summary"]["findings"][0]["failed"] == []
    assert (await api.client.get(f"/api/runs/{run_id}/exports/trace.json")).status_code == 200

    returned = await api.client.post(
        f"/api/runs/{run_id}/review", json={"action": "return", "note": "Add the 2027 date"}
    )
    assert returned.status_code == 200
    child_id = returned.json()["child"]["run_id"]
    assert await complete_queued(api) == 1
    child = (await api.client.get(f"/api/runs/{child_id}")).json()
    assert child["state"] == "completed" and child["parent_run_id"] == run_id
    child_trace = json.loads(
        (await api.client.get(f"/api/runs/{child_id}/exports/trace.json")).content
    )
    assert child_trace["parent_run_id"] == run_id
    assert child_trace["extra_guidance"] == "Reviewer note: Add the 2027 date"
    listed = (await api.client.get("/api/runs", params={"project_id": pid})).json()["runs"]
    assert [r["run_id"] for r in listed] == [child_id, run_id]  # newest first
