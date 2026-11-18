"""Throwaway Postgres databases for tests. A test session creates one database from the admin
URL in CORELATA_TEST_DATABASE_URL, migrates it and drops it at the end; `truncate_all` empties
it between tests. Copied from Coglossa."""

import asyncio
import contextlib
import uuid
from collections.abc import AsyncIterator

import psycopg
from psycopg import sql
from sqlalchemy import text
from sqlalchemy.engine import make_url

from corelata.store.db import Database, to_libpq_url
from corelata.store.models import Base
from corelata.store.runs import RUN_CHANNEL

TEST_DB_ENV = "CORELATA_TEST_DATABASE_URL"
PROCRASTINATE_TABLES = (
    "procrastinate_events",
    "procrastinate_periodic_defers",
    "procrastinate_jobs",
    "procrastinate_workers",
)


def create_test_database(admin: str) -> str:
    name = f"corelata_test_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(to_libpq_url(admin), autocommit=True, connect_timeout=10) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    return make_url(admin).set(database=name).render_as_string(hide_password=False)


def drop_test_database(admin: str, url: str) -> None:
    name = make_url(url).database
    with psycopg.connect(to_libpq_url(admin), autocommit=True, connect_timeout=10) as conn:
        conn.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
        )


async def truncate_all(db: Database) -> None:
    tables = [t.name for t in Base.metadata.sorted_tables] + list(PROCRASTINATE_TABLES)
    async with db.engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"))


_WORKER = text(
    "INSERT INTO procrastinate_workers (last_heartbeat) "
    "VALUES (now() - make_interval(secs => :silent_s)) RETURNING id"
)
_TAKEN_JOB = text(
    "INSERT INTO procrastinate_jobs (queue_name, task_name, lock, queueing_lock, args, status, "
    "worker_id) VALUES ('corelata', 'corelata.run', :lock, :lock, CAST(:args AS jsonb), "
    "'doing', :worker_id) RETURNING id"
)
_JOB_STATUS = text("SELECT status::text FROM procrastinate_jobs WHERE id = :id")


async def take_job(db: Database, run_id: uuid.UUID, *, silent_s: float | None) -> int:
    """Make the run's job one a worker has taken ('doing'), as procrastinate leaves it: the
    worker last sent a heartbeat `silent_s` ago, or (None) its row is gone. Returns the job id
    (R-M17-2 tests)."""
    async with db.session() as s, s.begin():
        worker_id = None
        if silent_s is not None:
            worker_id = await s.scalar(_WORKER, {"silent_s": silent_s})
        return await s.scalar(
            _TAKEN_JOB,
            {
                "lock": f"run:{run_id}",
                "args": f'{{"run_id": "{run_id}"}}',
                "worker_id": worker_id,
            },
        )


async def job_status(db: Database, job_id: int) -> str:
    async with db.session() as s:
        return await s.scalar(_JOB_STATUS, {"id": job_id})


class RunChannel:
    """A LISTEN connection on the run channel (CRL-22): what the worker and the service
    announced, in commit order. `open_run_channel` makes one. Each call waits for what the test
    expects rather than a fixed time (CRL-37)."""

    QUIET_S = 0.3  # how long "nothing was announced" waits for a late notification
    SETTLE_S = 0.05  # how long, after the expected ones, it waits for one too many

    def __init__(self, conn: psycopg.AsyncConnection) -> None:
        self._conn = conn
        self._pending: list[str] = []  # read from the connection, not yet returned

    async def _read(self, timeout_s: float, stop_after: int | None = None) -> None:
        # psycopg stops after the batch that reaches `stop_after`, so this may read more
        async for n in self._conn.notifies(timeout=timeout_s, stop_after=stop_after):
            self._pending.append(n.payload)

    async def received(self, count: int = 0, *, timeout_s: float = 10.0) -> list[str]:
        """The run ids notified since the last call. With `count`, it returns as soon as that
        many have arrived (waiting at most `timeout_s`, then returning what came, so the test's
        assertion shows what is missing) plus any that follow within SETTLE_S, so one too many
        still shows. With no count, nothing is expected: it waits QUIET_S for a late one."""
        if count > len(self._pending):
            await self._read(timeout_s, count - len(self._pending))
        await self._read(self.SETTLE_S if count else self.QUIET_S)
        got, self._pending = self._pending, []
        return got

    async def received_until(self, payload: str, *, timeout_s: float = 10.0) -> list[str]:
        """The run ids notified since the last call, up to and including the first `payload`
        (or all that came within `timeout_s`, without it); later ones wait for the next call."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s
        while payload not in self._pending and (left := deadline - loop.time()) > 0:
            seen = len(self._pending)
            await self._read(left, 1)
            if len(self._pending) == seen:
                break  # timed out
        cut = self._pending.index(payload) + 1 if payload in self._pending else None
        got = self._pending[:cut]
        self._pending = self._pending[len(got) :]
        return got


@contextlib.asynccontextmanager
async def open_run_channel(url: str) -> AsyncIterator[RunChannel]:
    async with await psycopg.AsyncConnection.connect(
        to_libpq_url(url), autocommit=True, connect_timeout=10
    ) as conn:
        await conn.execute(sql.SQL("LISTEN {}").format(sql.Identifier(RUN_CHANNEL)))
        yield RunChannel(conn)
