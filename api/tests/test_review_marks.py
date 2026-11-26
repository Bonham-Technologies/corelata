"""Review marks over the API (CRL-139): mark a claim, read the counts, the trace download carries
the marks, Accept freezes them, a return hands the disputed claims to the rerun, and a profile's
"How this report was produced" counts them in the served report."""

import io
import json
import shutil
import uuid

import yaml
from corelata.standards.loader import BUILTIN_PACKS_DIR
from corelata.store import runs
from docx import Document

from tests.conftest import complete_queued, set_run_state, start_run


async def _completed(api, **overrides) -> dict:
    run = await start_run(api, **overrides)
    assert await complete_queued(api) == 1
    progress = (await api.client.get(f"/api/runs/{run['run_id']}")).json()
    assert progress["state"] == "completed", progress
    return progress


async def _claims(api, run_id: str) -> list[str]:
    report = (await api.client.get(f"/api/runs/{run_id}/exports/report.json")).json()
    return [c["id"] for c in report["claims"]]


def _put(api, run_id: str, claim: str, mark: str, comment: str = ""):
    return api.client.put(
        f"/api/runs/{run_id}/marks/{claim}", json={"mark": mark, "comment": comment}
    )


async def test_marks_persist_with_actor_and_time_and_reach_the_trace_download(make_api):
    async with make_api(auth={"mode": "trusted_header"}) as api:
        api.client.headers.update({"X-Remote-User": "ana"})
        run = await _completed(api)
        run_id = run["run_id"]
        claims = await _claims(api, run_id)
        first = (await api.client.get(f"/api/runs/{run_id}/marks")).json()
        assert first["marks"] == [] and first["claims"] == len(claims) and first["editable"]
        assert first["require_key_judgments_checked"] is False
        stored = (await api.client.get(f"/api/runs/{run_id}/exports/trace.json")).content
        assert b"review_marks" not in stored
        marked = await _put(api, run_id, claims[0], "checked", "Matches the notice")
        assert marked.status_code == 200, marked.text
        body = marked.json()
        assert body["checked"] == 1 and body["reviewers"] == ["ana"]
        [mark] = body["marks"]
        assert (mark["claim_id"], mark["mark"], mark["comment"], mark["actor"]) == (
            claims[0],
            "checked",
            "Matches the notice",
            "ana",
        )
        assert mark["at"]
        trace = (await api.client.get(f"/api/runs/{run_id}/exports/trace.json")).json()
        assert [m["claim_id"] for m in trace["review_marks"]] == [claims[0]]
        before = json.loads(stored)
        assert {k: v for k, v in trace.items() if k != "review_marks"} == before


async def test_bad_marks_are_refused(api):
    run = await _completed(api)
    url = f"/api/runs/{run['run_id']}/marks"
    assert (await _put(api, run["run_id"], "c999", "checked")).status_code == 404
    bad = await api.client.put(f"{url}/c1", json={"mark": "maybe"})
    assert bad.status_code == 422
    long = await api.client.put(f"{url}/c1", json={"mark": "checked", "comment": "x" * 9000})
    assert long.status_code == 422
    missing = await api.client.get(f"/api/runs/{uuid.uuid4()}/marks")
    assert missing.status_code == 404
    await set_run_state(api.db, run["run_id"], "failed")  # a run without a report
    assert (await api.client.get(url)).status_code == 409


async def test_marks_are_refused_after_accept(api):
    run = await _completed(api)
    run_id = run["run_id"]
    [first, *_] = await _claims(api, run_id)
    assert (await _put(api, run_id, first, "disputed")).status_code == 200
    accepted = await api.client.post(f"/api/runs/{run_id}/review", json={"action": "accept"})
    assert accepted.status_code == 200
    refused = await _put(api, run_id, first, "checked")
    assert refused.status_code == 409 and "accepted" in refused.json()["detail"]
    assert (await api.client.get(f"/api/runs/{run_id}/marks")).json()["editable"] is False


async def test_a_return_with_a_disputed_claim_and_no_note_queues_the_rerun(api):
    run = await _completed(api)
    run_id = run["run_id"]
    [first, *_] = await _claims(api, run_id)
    empty = await api.client.post(f"/api/runs/{run_id}/review", json={"action": "return"})
    assert empty.status_code == 422 and "or a claim marked disputed" in empty.json()["detail"]
    await _put(api, run_id, first, "disputed", "Which year?")
    returned = await api.client.post(f"/api/runs/{run_id}/review", json={"action": "return"})
    assert returned.status_code == 200, returned.text
    child = returned.json()["child"]
    assert child["extra_guidance"] == ""
    assert await complete_queued(api) == 1
    trace = (await api.client.get(f"/api/runs/{child['run_id']}/exports/trace.json")).json()
    [finding] = trace["reviewer_findings"]
    assert finding["claim_ids"] == [first] and finding["recommendation"] == "Which year?"
    assert trace["prompt_versions"]["writer"] == 7


def _packs_with_profile(tmp_path) -> str:
    packs = tmp_path / "packs"
    shutil.copytree(BUILTIN_PACKS_DIR / "icd203-base", packs / "icd203-base")
    (packs / "icd203-base" / "profiles").mkdir()
    profile = {
        "name": "team",
        "extends": "icd203-base",
        "format": {"production_statement": True},
        "review": {"require_key_judgments_checked": True},
    }
    (packs / "icd203-base" / "profiles" / "team.yaml").write_text(
        yaml.safe_dump(profile), encoding="utf-8"
    )
    return str(packs)


async def test_the_profile_adds_the_production_statement_and_gates_accept(make_api, tmp_path):
    packs = _packs_with_profile(tmp_path)
    async with make_api(standards={"packs_dir": packs}) as api:
        run = await _completed(api, profile="team")
        run_id = run["run_id"]
        url = f"/api/runs/{run_id}/report"
        stored = (await api.client.get(url, params={"format": "md"})).text
        claims = await _claims(api, run_id)
        assert "## How this report was produced" in stored
        assert f"Review: 0 of {len(claims)} claims checked." in stored
        assert "Standards pack: icd203-base 1.2.0, profile team (hash " in stored
        marks = (await api.client.get(f"/api/runs/{run_id}/marks")).json()
        assert marks["require_key_judgments_checked"] is True
        key = marks["key_judgment_claim_ids"]
        assert key
        refused = await api.client.post(f"/api/runs/{run_id}/review", json={"action": "accept"})
        assert refused.status_code == 409 and "not checked" in refused.json()["detail"]
        for claim in key:
            assert (await _put(api, run_id, claim, "checked")).status_code == 200
        md = (await api.client.get(url, params={"format": "md"})).text
        assert f"Review: {len(key)} of {len(claims)} claims checked." in md
        again = (await api.client.get(url, params={"format": "md"})).text
        assert again == md  # served from the cache
        ids = (await api.client.get(url, params={"format": "md", "with_claim_ids": "1"})).text
        assert f"Review: {len(key)} of {len(claims)} claims checked." in ids and "^[" in ids
        docx = (await api.client.get(url, params={"format": "docx"})).content
        texts = [p.text for p in Document(io.BytesIO(docx)).paragraphs]
        assert any(f"{len(key)} of {len(claims)} claims checked" in t for t in texts)
        accepted = await api.client.post(f"/api/runs/{run_id}/review", json={"action": "accept"})
        assert accepted.status_code == 200, accepted.text


async def test_without_the_profile_the_stored_report_is_served_as_stored(api):
    run = await _completed(api)
    run_id = run["run_id"]
    url = f"/api/runs/{run_id}/report"
    before = (await api.client.get(url, params={"format": "html"})).content
    [first, *_] = await _claims(api, run_id)
    await _put(api, run_id, first, "checked")
    after = (await api.client.get(url, params={"format": "html"})).content
    assert after == before and b"How this report was produced" not in after
    async with api.db.session() as s:
        assert await runs.production_marks(s, uuid.UUID(run_id)) == 0
