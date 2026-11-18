import uuid
from datetime import datetime, timedelta

from sqlalchemy import text

from tests.conftest import project_with_source


async def test_start_and_get_a_discovery(api):
    pid, sid = await project_with_source(api)
    response = await api.client.post(
        "/api/discoveries",
        json={"project_id": pid, "source_ids": [sid], "audience_hint": " ministers "},
    )
    assert response.status_code == 202, response.text
    view = response.json()
    assert view["state"] == "created" and view["project_id"] == pid
    assert view["source_ids"] == [sid] and view["audience_hint"] == "ministers"
    assert view["candidates"] == [] and view["usage"] is None
    assert [(j.task, j.lock, j.kwargs) for j in api.queue.jobs] == [
        (
            "corelata.discover",
            f"discovery:{view['discovery_id']}",
            {"discovery_id": view["discovery_id"]},
        )
    ]
    assert (await api.client.get(f"/api/discoveries/{view['discovery_id']}")).json() == view


async def test_discovery_rejections(api):
    pid, sid = await project_with_source(api)
    base = {"project_id": pid, "source_ids": [sid]}
    assert (
        await api.client.post("/api/discoveries", json={**base, "source_ids": []})
    ).status_code == 422
    dup = await api.client.post("/api/discoveries", json={**base, "source_ids": [sid, sid]})
    assert dup.status_code == 422
    long_hint = await api.client.post("/api/discoveries", json={**base, "audience_hint": "a" * 501})
    assert long_hint.status_code == 422  # CRL-83
    assert "at most 500 characters" in long_hint.json()["detail"][0]["msg"]
    other = await api.client.post(
        "/api/discoveries", json={**base, "source_ids": [str(uuid.uuid4())]}
    )
    assert other.status_code == 404
    unknown = await api.client.post(
        "/api/discoveries", json={**base, "project_id": str(uuid.uuid4())}
    )
    assert unknown.status_code == 404
    assert (await api.client.get(f"/api/discoveries/{uuid.uuid4()}")).status_code == 404
    assert api.queue.jobs == []


_AGED = text("UPDATE discovery SET created_at = now() - interval '61 seconds' WHERE id = :id")
_CLAIMED = text(
    "UPDATE discovery SET state = 'running', started_at = now() - interval '91 seconds' "
    "WHERE id = :id"
)


async def test_a_discovery_past_the_configured_limits_is_failed_by_the_read(make_api):
    limits = {"discovery_start_deadline_s": 60, "discovery_deadline_s": 90}
    async with make_api(worker=limits) as api:
        pid, sid = await project_with_source(api)
        body = {"project_id": pid, "source_ids": [sid]}
        queued = (await api.client.post("/api/discoveries", json=body)).json()
        created = datetime.fromisoformat(queued["created_at"])
        # not claimed yet: the start limit applies
        assert datetime.fromisoformat(queued["deadline_at"]) == created + timedelta(seconds=60)
        running = (await api.client.post("/api/discoveries", json=body)).json()
        async with api.db.session() as s, s.begin():  # no worker runs; time passes
            await s.execute(_AGED, {"id": uuid.UUID(queued["discovery_id"])})
            await s.execute(_CLAIMED, {"id": uuid.UUID(running["discovery_id"])})
        read = (await api.client.get(f"/api/discoveries/{queued['discovery_id']}")).json()
        assert read["state"] == "failed" and read["finished_at"] is not None
        assert read["error"] == (
            "Discovery did not start within 1 minute and was stopped: the worker was stopped or "
            "busy with runs. Start a new discovery."
        )
        read = (await api.client.get(f"/api/discoveries/{running['discovery_id']}")).json()
        assert read["state"] == "failed"
        assert read["error"] == (
            "Discovery did not finish within 90 seconds and was stopped. Start a new discovery."
        )
        # claimed: the work limit applies, from the claim
        started = datetime.fromisoformat(read["started_at"])
        assert datetime.fromisoformat(read["deadline_at"]) == started + timedelta(seconds=90)
