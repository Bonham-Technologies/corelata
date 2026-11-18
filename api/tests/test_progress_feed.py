import asyncio
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from corelata.schema import RunProgress
from corelata.store.runs import NotFoundError
from sqlalchemy.exc import OperationalError

from corelata_api.progress_feed import DELETED, ENDED, ProgressFeed
from corelata_api.routes.progress import _stream

RUN = uuid.uuid4()
PROJECT = str(uuid.uuid4())


def progress(state: str) -> RunProgress:
    return RunProgress(
        run_id=str(RUN),
        project_id=PROJECT,
        state=state,
        value_statement="Varna matters",
        source_ids=[],
        iteration=0,
        max_iterations=2,
        created_at=datetime(2026, 10, 15, tzinfo=UTC),
    )


def scripted(*states):
    """A fetch that answers the given states in order (the last one repeats), counting calls; an
    exception in the script is raised."""
    queue = list(states)
    calls = {"n": 0}

    async def fetch(run_id):
        calls["n"] += 1
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return progress(item)

    return fetch, calls


async def drain(queue, n):
    return [await asyncio.wait_for(queue.get(), 1.0) for _ in range(n)]


async def test_two_subscribers_share_one_poller_and_see_the_same_updates():
    fetch, calls = scripted("gating", "drafting", "drafting", "completed")
    feed = ProgressFeed(fetch, poll_s=0.01)
    first = progress("created")
    q1 = feed.subscribe(RUN, first)
    q2 = feed.subscribe(RUN, first)
    assert feed.active == 1
    seen1, seen2 = await drain(q1, 3), await drain(q2, 3)
    assert [u.state for u in seen1] == ["gating", "drafting", "completed"]
    assert [u.state for u in seen2] == ["gating", "drafting", "completed"]
    await asyncio.sleep(0.05)
    assert calls["n"] == 4 and feed.active == 0  # one read per tick, stopped at the terminal state
    feed.unsubscribe(RUN, q1)
    feed.unsubscribe(RUN, q2)


async def test_a_late_subscriber_gets_the_next_change_and_nothing_stale():
    fetch, _ = scripted("gating", "drafting", *(["drafting"] * 20), "completed")
    feed = ProgressFeed(fetch, poll_s=0.01)
    q1 = feed.subscribe(RUN, progress("created"))
    await drain(q1, 2)
    q2 = feed.subscribe(RUN, progress("drafting"))  # what a fresh read by the route returns
    assert q2.empty() and feed.active == 1
    [done] = await drain(q2, 1)
    assert done.state == "completed"
    await feed.close()


async def test_a_subscriber_joining_after_a_change_still_receives_it():
    fetch, _ = scripted("gating", *(["gating"] * 20), "completed")
    feed = ProgressFeed(fetch, poll_s=0.01)
    q1 = feed.subscribe(RUN, progress("created"))
    assert [u.state for u in await drain(q1, 1)] == ["gating"]
    q2 = feed.subscribe(RUN, progress("created"))  # its own read predates "gating"
    assert [u.state for u in await drain(q2, 1)] == ["gating"]  # a shared `last` never repeats it
    assert [u.state for u in await drain(q1, 1)] == ["completed"]  # q1 gets no second "gating"
    await feed.close()


async def test_a_stream_joining_during_the_final_read_still_gets_the_terminal_state():
    release = asyncio.Event()
    started = asyncio.Event()

    async def fetch(run_id):
        started.set()
        await release.wait()
        return progress("completed")

    feed = ProgressFeed(fetch, poll_s=0.01)
    q1 = feed.subscribe(RUN, progress("drafting"))
    await asyncio.wait_for(started.wait(), 1.0)  # the final read is in flight
    q2 = feed.subscribe(RUN, progress("drafting"))
    release.set()
    assert [u.state for u in await drain(q2, 1)] == ["completed"]
    assert [u.state for u in await drain(q1, 1)] == ["completed"]
    await asyncio.sleep(0.02)
    assert feed.active == 0


async def test_a_subscriber_is_not_shown_what_it_already_has():
    fetch, _ = scripted(*(["drafting"] * 5), "completed")
    feed = ProgressFeed(fetch, poll_s=0.01)
    q = feed.subscribe(RUN, progress("drafting"))
    assert [u.state for u in await drain(q, 1)] == ["completed"]
    await feed.close()


async def test_resubscribing_in_the_turn_the_last_stream_left_keeps_the_new_poller():
    fetch, calls = scripted(*(["gating"] * 100))
    feed = ProgressFeed(fetch, poll_s=0.01)
    q1 = feed.subscribe(RUN, progress("created"))
    await drain(q1, 1)
    feed.unsubscribe(RUN, q1)
    q2 = feed.subscribe(RUN, progress("created"))  # before the first poller has unwound
    assert feed.active == 1
    assert [u.state for u in await drain(q2, 1)] == ["gating"]
    await asyncio.sleep(0.03)
    assert feed.active == 1  # the old poller's cleanup did not drop the new entry
    feed.unsubscribe(RUN, q2)
    assert feed.active == 0
    await asyncio.sleep(0.05)
    n = calls["n"]
    await asyncio.sleep(0.05)
    assert calls["n"] == n


async def test_the_poller_stops_when_the_last_subscriber_leaves():
    fetch, calls = scripted(*(["gating"] * 100))
    feed = ProgressFeed(fetch, poll_s=0.01)
    q1 = feed.subscribe(RUN, progress("created"))
    q2 = feed.subscribe(RUN, progress("created"))
    await drain(q1, 1)
    feed.unsubscribe(RUN, q1)
    assert feed.active == 1
    feed.unsubscribe(RUN, q2)
    assert feed.active == 0
    await asyncio.sleep(0.05)
    n = calls["n"]
    await asyncio.sleep(0.05)
    assert calls["n"] == n  # nothing polls an unwatched run


async def test_a_deleted_run_and_a_database_error_end_the_feed():
    fetch, _ = scripted(NotFoundError("gone"))
    feed = ProgressFeed(fetch, poll_s=0.01)
    q = feed.subscribe(RUN, progress("created"))
    assert (await drain(q, 1)) == [DELETED]
    await asyncio.sleep(0.02)
    assert feed.active == 0

    fetch, _ = scripted(OperationalError("SELECT", {}, ConnectionResetError("gone")))
    feed = ProgressFeed(fetch, poll_s=0.01)
    q = feed.subscribe(RUN, progress("created"))
    assert (await drain(q, 1)) == [ENDED]
    await asyncio.sleep(0.02)
    assert feed.active == 0


async def test_an_unexpected_error_ends_the_feed(caplog):
    fetch, _ = scripted(RuntimeError("pool exhausted"))
    feed = ProgressFeed(fetch, poll_s=0.01)
    q = feed.subscribe(RUN, progress("created"))
    assert (await drain(q, 1)) == [ENDED]
    await asyncio.sleep(0.02)
    assert feed.active == 0
    assert "progress poller failed" in caplog.text


async def test_close_ends_open_streams_and_cancels_every_poller():
    fetch, _ = scripted(*(["gating"] * 100))
    feed = ProgressFeed(fetch, poll_s=0.01)
    q1 = feed.subscribe(RUN, progress("created"))
    q2 = feed.subscribe(uuid.uuid4(), progress("created"))
    assert feed.active == 2
    await feed.close()
    assert feed.active == 0
    assert q1.get_nowait() is ENDED and q2.get_nowait() is ENDED
    await feed.close()  # idempotent


async def test_a_stream_cancelled_mid_wait_unsubscribes_and_stops_the_poller():
    fetch, calls = scripted(*(["gating"] * 1000))  # never a change: the stream sits in wait_for
    feed = ProgressFeed(fetch, poll_s=0.01)
    stream = _stream(SimpleNamespace(progress=feed), RUN, progress("gating"))
    chunks: list[str] = []

    async def read() -> None:
        async for chunk in stream:
            chunks.append(chunk)

    reader = asyncio.create_task(read())
    for _ in range(100):  # bounded wait: two reads and two chunks
        if calls["n"] >= 2 and len(chunks) == 2:
            break
        await asyncio.sleep(0.01)
    assert feed.active == 1 and calls["n"] >= 2
    assert len(chunks) == 2 and chunks[0] == "retry: 3000\n\n"  # retry, then the first event
    reader.cancel()  # the browser tab closed
    with pytest.raises(asyncio.CancelledError):
        await reader
    assert feed.active == 0  # the stream's finally unsubscribed the last listener
    n = calls["n"]
    await asyncio.sleep(0.05)
    assert calls["n"] == n  # and its poller is gone


# --- notifications (CRL-22, R-M14-3)


def test_the_heartbeat_is_ten_polls_capped_at_thirty_seconds():
    fetch, _ = scripted("gating")
    assert ProgressFeed(fetch, poll_s=1.0).heartbeat_s == 10.0
    assert ProgressFeed(fetch, poll_s=5.0).heartbeat_s == 30.0
    assert ProgressFeed(fetch, poll_s=5.0).poll_s == 5.0


async def test_a_notification_reads_the_run_at_once():
    fetch, calls = scripted("gating", "drafting", "completed")
    feed = ProgressFeed(fetch, poll_s=1.0)  # a 10 s heartbeat: every read below is a wake-up
    feed.set_listening(True)
    q = feed.subscribe(RUN, progress("created"))  # a subscription reads at once
    assert [u.state for u in await drain(q, 1)] == ["gating"]
    feed.notify(RUN)
    assert [u.state for u in await drain(q, 1)] == ["drafting"]
    feed.notify(RUN)
    assert [u.state for u in await drain(q, 1)] == ["completed"]
    await asyncio.sleep(0.02)
    assert calls["n"] == 3 and feed.active == 0


async def test_notifications_during_a_read_cost_one_more_read():
    release = asyncio.Event()
    reads: list[int] = []

    async def fetch(run_id):
        reads.append(1)
        if len(reads) == 1:
            await release.wait()
            return progress("gating")
        return progress("completed")

    feed = ProgressFeed(fetch, poll_s=1.0)
    feed.set_listening(True)
    q = feed.subscribe(RUN, progress("created"))
    while not reads:
        await asyncio.sleep(0)
    for _ in range(5):
        feed.notify(RUN)  # the run changes five times while the first read is in flight
    release.set()
    assert [u.state for u in await drain(q, 2)] == ["gating", "completed"]
    assert len(reads) == 2


async def test_a_stream_joining_after_the_notification_was_spent_still_gets_the_change():
    fetch, calls = scripted("gating", "drafting", "drafting", "completed")
    feed = ProgressFeed(fetch, poll_s=1.0)
    feed.set_listening(True)
    q1 = feed.subscribe(RUN, progress("created"))
    assert [u.state for u in await drain(q1, 1)] == ["gating"]
    feed.notify(RUN)  # the run moved to drafting; only q1 was watching
    assert [u.state for u in await drain(q1, 1)] == ["drafting"]
    q2 = feed.subscribe(RUN, progress("gating"))  # its own read predates the change
    assert [u.state for u in await drain(q2, 1)] == ["drafting"]  # well before the heartbeat
    assert q1.empty()  # q1 is not shown drafting twice
    feed.notify(RUN)
    assert [u.state for u in await drain(q1, 1)] == ["completed"]  # every stream gets the end
    assert [u.state for u in await drain(q2, 1)] == ["completed"]
    assert calls["n"] == 4


async def test_with_the_listener_up_a_lost_notification_costs_one_heartbeat():
    fetch, calls = scripted("gating", "completed")
    feed = ProgressFeed(fetch, poll_s=0.05)  # heartbeat 0.5 s
    feed.set_listening(True)
    q = feed.subscribe(RUN, progress("created"))
    assert [u.state for u in await drain(q, 1)] == ["gating"]
    await asyncio.sleep(0.15)
    assert calls["n"] == 1  # no read at poll_s while the listener is up
    assert [u.state for u in await drain(q, 1)] == ["completed"]  # the heartbeat read


async def test_when_the_listener_drops_the_feed_polls_at_poll_s_again():
    fetch, calls = scripted(*(["gating"] * 1000))
    feed = ProgressFeed(fetch, poll_s=0.02)  # heartbeat 0.2 s
    feed.set_listening(True)
    q = feed.subscribe(RUN, progress("created"))
    await drain(q, 1)
    feed.set_listening(False)  # reads once at once, then every poll_s
    await asyncio.sleep(0.3)
    assert calls["n"] >= 5  # about 15; the heartbeat alone would have read once
    await feed.close()


async def test_a_reconnect_reads_every_watched_run_once():
    fetch, calls = scripted("gating", "completed")
    feed = ProgressFeed(fetch, poll_s=5.0)  # neither the poll nor the heartbeat comes soon
    q1 = feed.subscribe(RUN, progress("created"))
    q2 = feed.subscribe(uuid.uuid4(), progress("created"))
    await asyncio.sleep(0.02)
    assert calls["n"] == 0  # listener down: the first read waits for poll_s, as before
    feed.set_listening(True)  # changes made while nobody listened are read now
    assert [u.state for u in await drain(q1, 1)] == ["gating"]
    assert [u.state for u in await drain(q2, 1)] == ["completed"]
    feed.set_listening(True)  # no change, no read
    await asyncio.sleep(0.02)
    assert calls["n"] == 2
    await feed.close()


def test_a_notification_for_an_unwatched_run_and_a_repeated_state_change_nothing():
    fetch, calls = scripted("gating")
    feed = ProgressFeed(fetch, poll_s=1.0)
    feed.notify(uuid.uuid4())
    feed.set_listening(False)
    assert not feed.listening and feed.active == 0 and calls["n"] == 0


@pytest.mark.parametrize(("poll_s", "heartbeat_s"), [(1.0, 10.0), (5.0, 30.0), (45.0, 45.0)])
def test_the_heartbeat_is_ten_polls_capped_at_30_s_and_never_below_one_poll(poll_s, heartbeat_s):
    assert ProgressFeed(scripted("gating")[0], poll_s=poll_s).heartbeat_s == heartbeat_s
