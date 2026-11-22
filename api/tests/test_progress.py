import asyncio
import json
import time
import uuid

import psycopg
from corelata.store import runs
from corelata.store.db import to_libpq_url
from sqlalchemy.exc import OperationalError

from corelata_api.routes import progress as progress_module
from corelata_api.run_listener import APPLICATION_NAME
from tests.conftest import set_run_state, start_run
from tests.test_run_listener import until


def _events(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "event" in lines:
            events.append((lines["event"], json.loads(lines["data"])))
    return events


async def test_a_finished_run_sends_one_event(api):
    run = await start_run(api)
    await set_run_state(api.db, run["run_id"], "completed")
    response = await api.client.get(f"/api/runs/{run['run_id']}/events")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    # no-cache for the proxies in between, no-store for the browser's disk cache (CRL-131)
    assert response.headers["cache-control"] == "no-cache, no-store"
    assert response.headers["x-accel-buffering"] == "no"
    assert response.text.startswith("retry: 3000\n\n")
    assert [(e, d["state"]) for e, d in _events(response.text)] == [("progress", "completed")]


async def _finish_later(db, run_id: str) -> None:
    await asyncio.sleep(0.3)
    await set_run_state(db, run_id, "gating")
    await asyncio.sleep(0.1)
    await set_run_state(db, run_id, "completed")


async def test_changes_are_streamed_until_the_run_ends(api):
    run = await start_run(api)
    finisher = asyncio.create_task(_finish_later(api.db, run["run_id"]))
    response = await api.client.get(f"/api/runs/{run['run_id']}/events")
    await finisher
    assert [d["state"] for _, d in _events(response.text)] == ["created", "gating", "completed"]


async def test_a_quiet_stream_sends_keep_alives(api, monkeypatch):
    monkeypatch.setattr(progress_module, "HEARTBEAT_S", 0.04)
    # The stream's first read is slow, as on a loaded CI runner: the run must still be live when
    # it is read, so the run ends only once the stream has subscribed (CRL-91).
    read = progress_module.service.run_progress

    async def slow_read(*args, **kwargs):
        await asyncio.sleep(0.3)
        return await read(*args, **kwargs)

    monkeypatch.setattr(progress_module.service, "run_progress", slow_read)
    run = await start_run(api)

    async def finish():
        await until(lambda: api.app.state.ctx.progress.active == 1)
        await asyncio.sleep(0.2)  # five heartbeats
        await set_run_state(api.db, run["run_id"], "completed")

    finisher = asyncio.create_task(finish())
    response = await api.client.get(f"/api/runs/{run['run_id']}/events")
    await finisher
    assert ": keep-alive\n\n" in response.text
    assert [d["state"] for _, d in _events(response.text)] == ["created", "completed"]


async def test_a_deleted_run_ends_the_stream(api):
    run = await start_run(api)

    async def delete():
        await asyncio.sleep(0.1)
        async with api.db.session() as s, s.begin():
            await runs.delete_project(s, uuid.UUID(run["project_id"]))

    deleter = asyncio.create_task(delete())
    response = await api.client.get(f"/api/runs/{run['run_id']}/events")
    await deleter
    assert _events(response.text)[-1] == ("deleted", {})


async def test_a_database_error_ends_the_stream(api, monkeypatch):
    run = await start_run(api)
    first = await progress_module.service.run_progress(api.db, uuid.UUID(run["run_id"]))
    calls = {"n": 0}

    async def flaky(db, run_id, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return first
        raise OperationalError("SELECT", {}, ConnectionResetError("gone"))

    monkeypatch.setattr(progress_module.service, "run_progress", flaky)
    response = await api.client.get(f"/api/runs/{run['run_id']}/events")
    assert [d["state"] for _, d in _events(response.text)] == ["created"]
    assert calls["n"] == 2


async def test_two_streams_on_one_run_share_one_poller_and_leave_none(api, monkeypatch):
    run = await start_run(api)
    real = progress_module.service.run_progress
    readers: list[asyncio.Task] = []

    async def counting(db, run_id, **kw):
        readers.append(asyncio.current_task())
        return await real(db, run_id, **kw)

    monkeypatch.setattr(progress_module.service, "run_progress", counting)
    finisher = asyncio.create_task(_finish_later(api.db, run["run_id"]))
    url = f"/api/runs/{run['run_id']}/events"
    first, second = await asyncio.gather(api.client.get(url), api.client.get(url))
    await finisher
    for response in (first, second):
        assert [d["state"] for _, d in _events(response.text)] == ["created", "gating", "completed"]
    polled = [t for t in readers if t.get_coro().__qualname__ == "ProgressFeed._run"]
    assert len(set(polled)) == 1  # every poll during the overlap came from one poller
    assert len(readers) - len(polled) == 2  # plus each stream's own first read
    assert api.app.state.ctx.progress.active == 0


async def test_an_unknown_run_is_a_plain_404(api):
    response = await api.client.get(f"/api/runs/{uuid.uuid4()}/events")
    assert response.status_code == 404 and response.headers["content-type"].startswith(
        "application/json"
    )


# --- event-driven streams (CRL-22, R-M14-3)


async def test_a_stream_follows_the_notifications_not_the_poll(make_api):
    async with make_api(api={"progress_poll_s": 5.0}) as api:  # poll 5 s, heartbeat 30 s
        await until(lambda: api.app.state.ctx.progress.listening)
        run = await start_run(api)
        finisher = asyncio.create_task(_finish_later(api.db, run["run_id"]))
        started = time.monotonic()
        response = await api.client.get(f"/api/runs/{run['run_id']}/events")
        await finisher
        elapsed = time.monotonic() - started
    assert [d["state"] for _, d in _events(response.text)] == ["created", "gating", "completed"]
    assert elapsed < 3.0  # a poll would have taken at least 5 s


async def test_a_cancel_shows_on_the_stream_at_once(make_api):
    async with make_api(api={"progress_poll_s": 5.0}) as api:
        await until(lambda: api.app.state.ctx.progress.listening)
        run = await start_run(api)
        await set_run_state(api.db, run["run_id"], "drafting")

        feed = api.app.state.ctx.progress
        cancel_read = asyncio.Event()
        fetch = feed._fetch

        async def watching_fetch(run_id):
            current = await fetch(run_id)
            if current.cancel_requested:
                cancel_read.set()  # the poller has the cancel; it publishes it before it awaits
            return current

        feed._fetch = watching_fetch

        async def cancel_then_stop():
            await until(lambda: feed.active == 1)  # the stream has subscribed
            response = await api.client.post(f"/api/runs/{run['run_id']}/cancel")
            assert response.json()["cancel_requested"] is True
            await asyncio.wait_for(cancel_read.wait(), timeout=3.0)
            await set_run_state(api.db, run["run_id"], "cancelled")

        canceller = asyncio.create_task(cancel_then_stop())
        response = await asyncio.wait_for(
            api.client.get(f"/api/runs/{run['run_id']}/events"), timeout=3.0
        )
        await canceller
    seen = [(d["state"], d["cancel_requested"]) for _, d in _events(response.text)]
    assert seen == [("drafting", False), ("drafting", True), ("cancelled", True)]


async def _refused():
    raise OSError("connection refused")


async def test_without_the_listener_the_stream_polls_at_progress_poll_s(make_api, caplog):
    async with make_api(listener_connect=lambda url: _refused) as api:  # poll 0.02 s
        run = await start_run(api)

        async def finish():  # changes nobody announces: only the poll can see them
            await asyncio.sleep(0.2)
            await set_run_state(api.db, run["run_id"], "gating", notify=False)
            await asyncio.sleep(0.2)
            await set_run_state(api.db, run["run_id"], "completed", notify=False)

        finisher = asyncio.create_task(finish())
        response = await asyncio.wait_for(
            api.client.get(f"/api/runs/{run['run_id']}/events"), timeout=3.0
        )
        await finisher
        assert not api.app.state.ctx.progress.listening
    assert [d["state"] for _, d in _events(response.text)] == ["created", "gating", "completed"]
    assert "progress listener lost the database: connection refused" in caplog.text


async def test_shutdown_closes_the_listen_connection(make_api, pg_url):
    async def listeners() -> int:
        async with await psycopg.AsyncConnection.connect(
            to_libpq_url(pg_url), autocommit=True
        ) as conn:
            cursor = await conn.execute(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE application_name = %s AND datname = current_database()",
                (APPLICATION_NAME,),
            )
            return (await cursor.fetchone())[0]

    async with make_api() as api:
        await until(lambda: api.app.state.ctx.progress.listening)
        assert await listeners() == 1
    deadline = time.monotonic() + 3.0
    while await listeners() != 0:  # the backend leaves pg_stat_activity a moment after the close
        assert time.monotonic() < deadline, "the LISTEN connection is still open"
        await asyncio.sleep(0.02)
