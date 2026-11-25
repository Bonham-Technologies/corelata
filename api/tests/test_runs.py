import json
import logging
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from corelata import service
from corelata.service import QueueUnavailableError
from corelata.store import runs
from corelata.store.models import ReviewEvent
from corelata.testing.postgres import job_status, take_job
from corelata.testing.queue import RecordingQueue
from sqlalchemy import select

from tests.conftest import STATEMENT, project_with_source, set_run_state, start_run


async def test_start_run_queues_one_job(api):
    run = await start_run(api, max_iterations=1, profile=None)
    assert run["state"] == "created" and run["max_iterations"] == 1 and run["stages"] == []
    assert run["attempts"] == 0 and run["started_at"] is None and run["review"] is None
    assert [(j.task, j.lock, j.kwargs) for j in api.queue.jobs] == [
        ("corelata.run", f"run:{run['run_id']}", {"run_id": run["run_id"]})
    ]
    assert (await api.client.get(f"/api/runs/{run['run_id']}")).json() == run
    # what the run was asked, so a new report can start from it (CRL-84)
    [source] = (await api.client.get(f"/api/projects/{run['project_id']}/sources")).json()
    assert run["source_ids"] == [source["id"]]
    assert (run["value_statement"], run["profile"]) == (STATEMENT, None)
    assert run["extra_guidance"] == ""  # none given (CRL-132)
    listed = await api.client.get("/api/runs", params={"project_id": run["project_id"]})
    assert listed.status_code == 200
    assert listed.json()["next_before"] is None
    [summary] = listed.json()["runs"]
    assert summary["run_id"] == run["run_id"] and summary["value_statement"] == STATEMENT
    assert summary["state"] == "created" and summary["parent_run_id"] is None


async def test_start_run_rejections(api):
    pid, sid = await project_with_source(api)
    base = {"project_id": pid, "source_ids": [sid], "value_statement": STATEMENT}

    async def post(**changes):
        return await api.client.post("/api/runs", json={**base, **changes})

    assert (await post(value_statement="   ")).status_code == 422
    assert (await post(source_ids=[])).status_code == 422
    assert (await post(source_ids=[sid, sid])).status_code == 422
    assert (await post(max_iterations=11)).status_code == 422
    other = await post(source_ids=[str(uuid.uuid4())])
    assert other.status_code == 404 and "not in project" in other.json()["detail"]
    assert (await post(project_id=str(uuid.uuid4()))).status_code == 404
    profile = await post(profile="nope")
    assert profile.status_code == 422 and "profile 'nope' not found" in profile.json()["detail"]
    parent = await post(parent_run_id=str(uuid.uuid4()))
    assert parent.status_code == 404
    assert api.queue.jobs == []


async def test_free_text_is_bounded(api):
    """CRL-83: the statement and the guidance are repeated in every prompt and in the trace, so
    a pasted document is refused with the limit named, not stored and sent to the models."""
    pid, sid = await project_with_source(api)
    base = {"project_id": pid, "source_ids": [sid], "value_statement": STATEMENT}

    async def post(**changes):
        return await api.client.post("/api/runs", json={**base, **changes})

    for field, limit in (("value_statement", 4000), ("extra_guidance", 8000)):
        over = await post(**{field: "x" * (limit + 1)})
        assert over.status_code == 422
        [error] = over.json()["detail"]
        assert error["loc"] == ["body", field] and f"at most {limit} characters" in error["msg"]
    assert api.queue.jobs == []
    at_limit = await post(value_statement="x" * 4000, extra_guidance="y" * 8000)
    assert at_limit.status_code == 202, at_limit.text
    run = at_limit.json()
    await set_run_state(api.db, run["run_id"], "completed")
    review = f"/api/runs/{run['run_id']}/review"
    over = await api.client.post(review, json={"action": "return", "note": "n" * 8001})
    assert over.status_code == 422 and "at most 8000 characters" in over.json()["detail"][0]["msg"]
    returned = await api.client.post(review, json={"action": "return", "note": "n" * 8000})
    assert returned.status_code == 200, returned.text


async def test_a_return_past_the_guidance_cap_is_refused_in_one_line(api):
    """CRL-111: a return appends its note to the run's guidance; once the chain would pass the
    service's cap the return answers 422 with one line that says to start a new report."""
    pid, sid = await project_with_source(api)
    body = {"project_id": pid, "source_ids": [sid], "value_statement": STATEMENT}
    started = await api.client.post("/api/runs", json={**body, "extra_guidance": "g" * 8000})
    run_id = started.json()["run_id"]
    label = len("\nReviewer note: ")
    for note in ("a" * 8000, "b" * (service.RUN_GUIDANCE_MAX_LENGTH - 2 * (8000 + label))):
        await set_run_state(api.db, run_id, "completed")
        returned = await api.client.post(
            f"/api/runs/{run_id}/review", json={"action": "return", "note": note}
        )
        assert returned.status_code == 200, returned.text
        run_id = returned.json()["child"]["run_id"]
    await set_run_state(api.db, run_id, "completed")
    jobs = len(api.queue.jobs)
    over = await api.client.post(
        f"/api/runs/{run_id}/review", json={"action": "return", "note": "x"}
    )
    assert over.status_code == 422
    assert over.json() == {"detail": service.GUIDANCE_CAP_MESSAGE}
    assert "start a new report" in over.json()["detail"]
    assert len(api.queue.jobs) == jobs


async def test_list_runs_validates_its_parameters(api):
    assert (await api.client.get("/api/runs")).status_code == 422
    assert (await api.client.get("/api/runs", params={"project_id": "x"})).status_code == 422
    unknown = await api.client.get("/api/runs", params={"project_id": str(uuid.uuid4())})
    assert unknown.status_code == 404
    pid, _ = await project_with_source(api)
    assert (
        await api.client.get("/api/runs", params={"project_id": pid, "limit": 0})
    ).status_code == 422
    assert (
        await api.client.get("/api/runs", params={"project_id": pid, "limit": 501})
    ).status_code == 422
    assert (await api.client.get("/api/runs", params={"project_id": pid})).json() == {
        "runs": [],
        "next_before": None,
    }
    for before in ("yesterday", "2026-10-17T06:30:01Z|run-1", "x" * 101):
        bad = await api.client.get("/api/runs", params={"project_id": pid, "before": before})
        assert bad.status_code == 422, before
    bad = await api.client.get("/api/runs", params={"project_id": pid, "before": "yesterday"})
    assert bad.json() == {
        "detail": "invalid cursor 'before': pass the next_before of the previous page"
    }


async def _runs_created_at(api, pid: str, sid: str, stamps: list[datetime]) -> list[str]:
    """One run per stamp, with that creation time."""
    body = {"project_id": pid, "source_ids": [sid], "value_statement": STATEMENT}
    ids = [(await api.client.post("/api/runs", json=body)).json()["run_id"] for _ in stamps]
    async with api.db.session() as s, s.begin():
        for run_id, stamp in zip(ids, stamps, strict=True):
            (await runs.get_run(s, uuid.UUID(run_id))).created_at = stamp
    return ids


async def _pages(api, pid: str, limit: int) -> list[dict]:
    pages, before = [], None
    while True:
        params = {"project_id": pid, "limit": limit, **({"before": before} if before else {})}
        response = await api.client.get("/api/runs", params=params)
        assert response.status_code == 200, response.text
        pages.append(response.json())
        before = pages[-1]["next_before"]
        if before is None:
            return pages


async def test_list_runs_pages_by_cursor_through_ties_without_gaps(api):
    pid, sid = await project_with_source(api)
    t0 = datetime(2026, 10, 17, 6, 30, 1, 120000, tzinfo=UTC)
    stamps = [t0 - timedelta(seconds=i // 2) for i in range(7)]  # pairs share a microsecond
    ids = await _runs_created_at(api, pid, sid, stamps)
    pages = await _pages(api, pid, limit=2)
    assert [len(p["runs"]) for p in pages] == [2, 2, 2, 1]
    shown = [r["run_id"] for p in pages for r in p["runs"]]
    newest_first = sorted(zip(stamps, ids, strict=True), reverse=True)  # by time, then id
    assert shown == [run_id for _, run_id in newest_first]  # every run once, in one order
    last = pages[0]["runs"][-1]["run_id"]  # one of the two runs created at t0
    assert pages[0]["next_before"] == f"2026-10-17T06:30:01.120000Z|{last}"


async def test_a_full_last_page_has_no_next_cursor(api):
    pid, sid = await project_with_source(api)
    t0 = datetime(2026, 10, 17, 6, 30, tzinfo=UTC)
    await _runs_created_at(api, pid, sid, [t0 - timedelta(seconds=i) for i in range(4)])
    pages = await _pages(api, pid, limit=2)
    assert [len(p["runs"]) for p in pages] == [2, 2]  # no empty third page
    assert pages[-1]["next_before"] is None


async def test_a_run_created_while_paging_does_not_shift_the_next_page(api):
    pid, sid = await project_with_source(api)
    t0 = datetime(2026, 10, 17, 6, 30, tzinfo=UTC)
    ids = await _runs_created_at(api, pid, sid, [t0 - timedelta(seconds=i) for i in range(4)])
    first = (await api.client.get("/api/runs", params={"project_id": pid, "limit": 2})).json()
    await _runs_created_at(api, pid, sid, [t0 + timedelta(seconds=1)])  # newer than all
    params = {"project_id": pid, "limit": 2, "before": first["next_before"]}
    second = (await api.client.get("/api/runs", params=params)).json()
    assert [r["run_id"] for r in first["runs"] + second["runs"]] == ids


async def test_get_run_404s(api):
    assert (await api.client.get(f"/api/runs/{uuid.uuid4()}")).status_code == 404
    assert (await api.client.get("/api/runs/nope")).status_code == 422


async def test_cancel_a_created_run_ends_it_at_once(api):
    run = await start_run(api)
    response = await api.client.post(f"/api/runs/{run['run_id']}/cancel")
    assert response.status_code == 200
    assert response.json()["state"] == "cancelled" and response.json()["cancel_requested"]
    again = await api.client.post(f"/api/runs/{run['run_id']}/cancel")
    assert again.status_code == 409 and "already cancelled" in again.json()["detail"]
    assert (await api.client.post(f"/api/runs/{uuid.uuid4()}/cancel")).status_code == 404


async def test_cancel_a_running_run_only_requests_it(api):
    run = await start_run(api)
    await set_run_state(api.db, run["run_id"], "drafting")
    response = await api.client.post(f"/api/runs/{run['run_id']}/cancel")
    assert response.json()["state"] == "drafting" and response.json()["cancel_requested"]


async def test_cancel_a_run_whose_worker_is_gone_uses_the_configured_threshold(make_api):
    async with make_api(worker={"stalled_after_s": 30}) as api:
        run = await start_run(api)
        await set_run_state(api.db, run["run_id"], "drafting")
        job = await take_job(api.db, uuid.UUID(run["run_id"]), silent_s=31)
        response = await api.client.post(f"/api/runs/{run['run_id']}/cancel")
        assert response.status_code == 200
        assert response.json()["state"] == "cancelled" and response.json()["finished_at"]
        assert await job_status(api.db, job) == "aborted"


async def test_a_stuck_cancel_is_reported_with_the_configured_threshold(make_api):
    """CRL-49: the run page offers the cancel again when the progress says the worker is gone."""
    async with make_api(worker={"stalled_after_s": 30}) as api:
        run = await start_run(api)
        await set_run_state(api.db, run["run_id"], "drafting")
        async with api.db.session() as s, s.begin():  # asked while its worker was alive
            (await runs.get_run(s, uuid.UUID(run["run_id"]), lock=True)).cancel_requested = True
        await take_job(api.db, uuid.UUID(run["run_id"]), silent_s=31)
        shown = (await api.client.get(f"/api/runs/{run['run_id']}")).json()
        assert shown["cancel_requested"] and shown["worker_gone"]


@pytest.mark.parametrize("route", ["project", "run", "review"])
async def test_an_unpaired_surrogate_is_a_one_line_422_not_a_500(api, caplog, route):
    """CRL-128: text pasted from a broken export can carry a lone UTF-16 surrogate. The default
    validation answer echoed the input back and could not encode it, so the analyst got
    "internal error" and the operator a stack trace."""
    if route == "project":
        path, body, field = "/api/projects", '{"name": "a\\ud800b"}', "name"
    elif route == "run":
        pid, sid = await project_with_source(api)
        path, field = "/api/runs", "value_statement"
        body = json.dumps({"project_id": pid, "source_ids": [sid], "value_statement": "x"})
        body = body.replace('"x"', '"a\\ud800b"')
    else:
        run = await start_run(api)
        await set_run_state(api.db, run["run_id"], "completed")
        path, field = f"/api/runs/{run['run_id']}/review", "note"
        body = '{"action": "return", "note": "a\\ud800b"}'
    queued = len(api.queue.jobs)
    with caplog.at_level(logging.WARNING):
        response = await api.client.post(
            path, content=body.encode(), headers={"content-type": "application/json"}
        )
    assert response.status_code == 422, response.text
    [error] = response.json()["detail"]
    assert error["loc"] == ["body", field] and error["msg"]
    assert "\n" not in error["msg"]
    # the input is not echoed back, so nothing the client sent has to be encoded again
    assert set(error) == {"type", "loc", "msg"}
    assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []
    assert len(api.queue.jobs) == queued


async def test_an_unpaired_surrogate_an_error_repeats_is_a_422_not_a_500(api, caplog):
    """CRL-128: `profile` has no length limit, so a lone surrogate passes validation and reaches
    the pack loader, whose message repeats it; the answer spells it out instead of failing."""
    pid, sid = await project_with_source(api)
    body = json.dumps({"project_id": pid, "source_ids": [sid], "value_statement": "x"})
    body = body[:-1] + ', "profile": "a\\ud800b"}'
    with caplog.at_level(logging.WARNING):
        response = await api.client.post(
            "/api/runs", content=body.encode(), headers={"content-type": "application/json"}
        )
    assert response.status_code == 422, response.text
    assert "profile" in response.json()["detail"]
    assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []


async def test_review_needs_a_completed_run(api):
    run = await start_run(api)
    response = await api.client.post(f"/api/runs/{run['run_id']}/review", json={"action": "accept"})
    assert response.status_code == 409 and "only a completed run" in response.json()["detail"]
    bad = await api.client.post(f"/api/runs/{run['run_id']}/review", json={"action": "redo"})
    assert bad.status_code == 422


async def test_review_accept_and_return(make_api):
    async with make_api(auth={"mode": "trusted_header"}) as api:
        headers = {"X-Remote-User": " ana "}
        api.client.headers.update(headers)
        run = await start_run(api)
        await set_run_state(api.db, run["run_id"], "completed")
        review = f"/api/runs/{run['run_id']}/review"
        empty = await api.client.post(review, json={"action": "return", "note": "  "})
        assert empty.status_code == 422 and "needs a note" in empty.json()["detail"]
        returned = await api.client.post(review, json={"action": "return", "note": "Tighten it"})
        assert returned.status_code == 200, returned.text
        child = returned.json()["child"]
        assert child["parent_run_id"] == run["run_id"] and child["state"] == "created"
        assert [j.kwargs["run_id"] for j in api.queue.jobs] == [run["run_id"], child["run_id"]]
        listed = (
            await api.client.get("/api/runs", params={"project_id": run["project_id"]})
        ).json()["runs"]
        assert {r["run_id"]: r["parent_run_id"] for r in listed} == {
            run["run_id"]: None,
            child["run_id"]: run["run_id"],
        }
        shown = (await api.client.get(f"/api/runs/{run['run_id']}")).json()["review"]
        assert shown["decision"] == "returned" and shown["child_run_id"] == child["run_id"]
        assert shown["actor"] == "ana"
        assert child["review"] is None
        again = await api.client.post(review, json={"action": "return", "note": "Once more"})
        assert again.status_code == 409 and "already returned" in again.json()["detail"]

        # the rerun's report is accepted, which is final (CRL-21, R-M16-1)
        await set_run_state(api.db, child["run_id"], "completed")
        child_review = f"/api/runs/{child['run_id']}/review"
        accept = await api.client.post(child_review, json={"action": "accept"})
        assert accept.status_code == 200 and accept.json() == {"action": "accept", "child": None}
        shown = (await api.client.get(f"/api/runs/{child['run_id']}")).json()["review"]
        assert shown["decision"] == "accepted" and shown["actor"] == "ana"
        assert shown["child_run_id"] is None
        refused = await api.client.post(child_review, json={"action": "return", "note": "Redo"})
        assert refused.status_code == 409
        assert refused.json() == {
            "detail": f"run {child['run_id']} was accepted; start a new run to change it"
        }
        assert len(api.queue.jobs) == 2  # nothing more was queued
        async with api.db.session() as s:
            events = (await s.scalars(select(ReviewEvent).order_by(ReviewEvent.at))).all()
        assert [(e.run_id, e.action, e.note, e.actor) for e in events] == [
            (uuid.UUID(run["run_id"]), "return", "Tighten it", "ana"),
            (uuid.UUID(child["run_id"]), "accept", "", "ana"),
        ]
        assert events[0].child_run_id == uuid.UUID(child["run_id"])


class _DownQueue(RecordingQueue):
    async def defer(
        self, task: str, *, lock: str | None = None, priority: int = 0, **kwargs: str
    ) -> None:
        raise QueueUnavailableError("cannot reach the job queue: connection refused")


async def test_a_queue_outage_answers_503_and_the_run_is_failed(make_api):
    async with make_api(queue=_DownQueue()) as api:
        pid, sid = await project_with_source(api)
        body = {"project_id": pid, "source_ids": [sid], "value_statement": STATEMENT}
        response = await api.client.post("/api/runs", json=body)
        assert response.status_code == 503
        assert response.json() == {
            "detail": "the job queue is unavailable; the operator's log has the reason"
        }
        [summary] = (await api.client.get("/api/runs", params={"project_id": pid})).json()["runs"]
        assert summary["state"] == "failed"


async def test_a_run_whose_rerun_was_cancelled_can_be_returned_again(api):
    run = await start_run(api)
    await set_run_state(api.db, run["run_id"], "completed")
    review = f"/api/runs/{run['run_id']}/review"
    first = (await api.client.post(review, json={"action": "return", "note": "Tighten it"})).json()
    cancelled = await api.client.post(f"/api/runs/{first['child']['run_id']}/cancel")
    assert cancelled.json()["state"] == "cancelled"
    shown = (await api.client.get(f"/api/runs/{run['run_id']}")).json()["review"]
    assert shown == {
        "decision": "returned",
        "at": shown["at"],
        "actor": None,
        "child_run_id": first["child"]["run_id"],
        "child_state": "cancelled",
        "child_error": None,
        "note": "Tighten it",
    }
    again = await api.client.post(review, json={"action": "return", "note": "Tighten it more"})
    assert again.status_code == 200, again.text
    second = again.json()["child"]
    assert second["run_id"] != first["child"]["run_id"]
    shown = (await api.client.get(f"/api/runs/{run['run_id']}")).json()["review"]
    assert shown["child_run_id"] == second["run_id"] and shown["child_state"] is None
    assert shown["note"] == "Tighten it more"
    third = await api.client.post(review, json={"action": "return", "note": "Once more"})
    assert third.status_code == 409 and second["run_id"] in third.json()["detail"]


async def test_a_run_carries_the_guidance_it_was_given(api):
    """CRL-132: GET /runs/{id} returns `extra_guidance`, so a new report can start from it."""
    run = await start_run(api, extra_guidance="Lead with the port's capacity.")
    assert run["extra_guidance"] == "Lead with the port's capacity."
    again = await api.client.get(f"/api/runs/{run['run_id']}")
    assert again.json()["extra_guidance"] == "Lead with the port's capacity."
