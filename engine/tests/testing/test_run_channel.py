"""The test helper that listens on the run channel waits for what a test expects, not a fixed
time (CRL-37)."""

import asyncio

import psycopg
from psycopg import sql

from corelata.store.db import to_libpq_url
from corelata.store.runs import RUN_CHANNEL
from corelata.testing.postgres import RunChannel


async def _notify(pg_url: str, *payloads: str, delay_s: float = 0.0) -> None:
    await asyncio.sleep(delay_s)
    async with await psycopg.AsyncConnection.connect(to_libpq_url(pg_url), autocommit=True) as c:
        for payload in payloads:
            await c.execute(
                sql.SQL("SELECT pg_notify({}, {})").format(
                    sql.Literal(RUN_CHANNEL), sql.Literal(payload)
                )
            )


async def test_it_returns_as_soon_as_the_expected_notifications_arrive(pg_url, run_channel):
    loop = asyncio.get_running_loop()
    late = asyncio.create_task(_notify(pg_url, "a", "b", delay_s=0.5))  # later than QUIET_S
    started = loop.time()
    assert await run_channel.received(2) == ["a", "b"]
    assert loop.time() - started < 0.5 + RunChannel.QUIET_S  # no fixed wait after them
    await late


async def test_one_too_many_and_one_missing_both_show(pg_url, run_channel):
    await _notify(pg_url, "a", "b")
    assert await run_channel.received(1) == ["a", "b"]  # the extra one is not hidden
    assert await run_channel.received(1, timeout_s=0.2) == []  # a missing one: what came
    assert await run_channel.received() == []


async def test_received_until_stops_at_the_payload_or_the_timeout(pg_url, run_channel):
    await _notify(pg_url, "a", "b", "c")
    assert await run_channel.received_until("b") == ["a", "b"]
    assert await run_channel.received_until("z", timeout_s=0.2) == ["c"]


async def _trickle(pg_url: str, count: int, every_s: float) -> None:
    """One notification every `every_s`, on one connection: never a quiet gap of that length."""
    async with await psycopg.AsyncConnection.connect(to_libpq_url(pg_url), autocommit=True) as c:
        for i in range(count):
            await c.execute(
                sql.SQL("SELECT pg_notify({}, {})").format(
                    sql.Literal(RUN_CHANNEL), sql.Literal(f"n{i}")
                )
            )
            await asyncio.sleep(every_s)


async def test_received_until_ends_at_its_deadline_while_notifications_keep_coming(
    pg_url, run_channel
):
    """The deadline branch (CRL-40): every read returns a notification, so the loop ends because
    the time is up, not because a read came back empty."""
    loop = asyncio.get_running_loop()
    sender = asyncio.create_task(_trickle(pg_url, 40, 0.02))  # 0.8 s of notifications
    started = loop.time()
    got = await run_channel.received_until("never", timeout_s=0.3)
    elapsed = loop.time() - started
    assert got and "never" not in got and got == [f"n{i}" for i in range(len(got))]
    assert 0.3 <= elapsed < 0.3 + 0.2  # it stopped at the deadline, not after the sender
    assert not sender.done()  # notifications were still coming when it returned
    await sender
    rest = await run_channel.received_until("n39")
    assert got + rest == [f"n{i}" for i in range(40)]  # nothing lost across the two calls
