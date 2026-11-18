import asyncio
import contextlib
import logging
import uuid
from types import SimpleNamespace

import psycopg
from corelata.store import runs
from corelata.store.db import to_libpq_url

from corelata_api.progress_feed import ProgressFeed
from corelata_api.run_listener import (
    APPLICATION_NAME,
    BACKOFF_S,
    RunListener,
    listen_connection,
)
from tests.test_progress_feed import RUN, drain, progress, scripted


async def until(condition, timeout_s: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while not condition():
        assert asyncio.get_running_loop().time() < deadline, "condition not met in time"
        await asyncio.sleep(0.01)


class Delays:
    """A sleep that records what the listener waits and returns at once; after `stop_after`
    waits it parks until the listener is cancelled, so a listener that keeps failing does not
    spin (and log) for the rest of the test."""

    def __init__(self, stop_after: int | None = None) -> None:
        self.waited: list[float] = []
        self._stop_after = stop_after

    async def __call__(self, seconds: float) -> None:
        self.waited.append(seconds)
        if self._stop_after is not None and len(self.waited) >= self._stop_after:
            await asyncio.Event().wait()  # the test has what it asserts on
        await asyncio.sleep(0)


@contextlib.asynccontextmanager
async def listening(connect, feed, sleep=asyncio.sleep):
    task = asyncio.create_task(RunListener(connect, feed, sleep=sleep).run())
    try:
        yield task
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def announce(db, payload) -> None:
    async with db.session() as s, s.begin():
        if isinstance(payload, uuid.UUID):
            await runs.notify_run(s, payload)
        else:
            await s.execute(runs._NOTIFY, {"channel": runs.RUN_CHANNEL, "payload": payload})


async def test_a_notification_wakes_the_runs_poller(db, pg_url, caplog):
    caplog.set_level(logging.INFO, logger="corelata.api")
    fetch, calls = scripted("gating", "completed")
    feed = ProgressFeed(fetch, poll_s=5.0)  # poll 5 s, heartbeat 30 s: only a wake-up is fast
    async with listening(listen_connection(pg_url), feed):
        await until(lambda: feed.listening)
        q = feed.subscribe(RUN, progress("created"))
        assert [u.state for u in await drain(q, 1)] == ["gating"]  # the subscription's read
        await announce(db, "not-a-run-id")
        await announce(db, uuid.uuid4())  # another run: nobody watches it
        await announce(db, RUN)
        assert [u.state for u in await drain(q, 1)] == ["completed"]
    assert calls["n"] == 2
    assert "progress listener connected" in caplog.text
    assert "progress listener ignored a notification that is not a run id" in caplog.text
    assert not feed.listening  # cancelled: the feed is told


async def test_a_lost_connection_is_reported_and_reopened(db, pg_url, caplog):
    caplog.set_level(logging.INFO, logger="corelata.api")
    fetch, _ = scripted("gating")
    feed = ProgressFeed(fetch, poll_s=5.0)
    delays = Delays(stop_after=2)  # a second loss would park the listener, not spin it
    async with listening(listen_connection(pg_url), feed, sleep=delays):
        await until(lambda: feed.listening)
        async with await psycopg.AsyncConnection.connect(
            to_libpq_url(pg_url), autocommit=True
        ) as admin:
            await admin.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE application_name = %s AND datname = current_database()",
                (APPLICATION_NAME,),
            )
        await until(lambda: delays.waited == [1.0] and feed.listening)
    assert "progress listener lost the database: " in caplog.text
    assert "; polling every 5.0 s, reconnecting in 1.0 s" in caplog.text
    assert caplog.text.count("progress listener connected") == 2


async def test_an_unreachable_database_is_retried_with_backoff(caplog):
    fetch, _ = scripted("gating")
    feed = ProgressFeed(fetch, poll_s=1.0)
    delays = Delays(stop_after=8)
    attempts = []

    async def refused():
        attempts.append(1)
        if len(attempts) == 3:
            raise RuntimeError("driver bug")  # not a database error: logged with its traceback
        raise OSError("connection refused")

    async with listening(refused, feed, sleep=delays):
        await until(lambda: len(delays.waited) == 8)
    assert delays.waited == [1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0, 30.0]
    assert len(attempts) == 8  # it stopped after the asserted calls
    assert caplog.text.count("progress listener lost the database") == 8
    assert BACKOFF_S == (1.0, 2.0, 4.0, 8.0, 16.0, 30.0)
    assert not feed.listening
    assert (
        "progress listener lost the database: connection refused; polling every 1.0 s, "
        "reconnecting in 1.0 s"
    ) in caplog.text
    assert "progress listener failed" in caplog.text
    assert "progress listener lost the database: RuntimeError; " in caplog.text


class _EndingConnection:
    """A connection whose notification stream ends on its own after one notification."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def execute(self, query) -> None:
        return None

    async def notifies(self):
        yield SimpleNamespace(payload=str(RUN))


async def test_a_notification_stream_that_ends_is_a_lost_connection(caplog):
    fetch, _ = scripted("gating")
    feed = ProgressFeed(fetch, poll_s=1.0)
    delays = Delays(stop_after=2)

    async def connect():
        return _EndingConnection()

    async with listening(connect, feed, sleep=delays):
        await until(lambda: len(delays.waited) == 2)
    assert delays.waited == [1.0, 1.0]  # each connect succeeded, so no backoff builds up
    assert "progress listener lost the database: the notification stream ended" in caplog.text


async def test_the_listen_connection_asks_libpq_for_tcp_keepalives(monkeypatch):
    seen = {}

    async def connect(*args, **kwargs):
        seen.update(kwargs)
        return object()

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect)
    await listen_connection("postgresql://u:p@h/db")()
    assert seen["keepalives"] == 1
    assert (seen["keepalives_idle"], seen["keepalives_interval"], seen["keepalives_count"]) == (
        60,
        10,
        3,
    )
