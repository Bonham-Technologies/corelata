"""The API's one LISTEN connection (CRL-22, R-M14-3). The worker and the service announce every
committed change to a run on `corelata_run` with the run id; this task hands each one to the
progress feed, which reads that run at once. While the connection is down the feed polls at
`api.progress_poll_s`, and the task reconnects after 1, 2, 4, 8, 16, then every 30 s."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable, Sequence

import psycopg
from corelata.store.db import CONNECT_TIMEOUT_S, error_reason, to_libpq_url
from corelata.store.runs import RUN_CHANNEL
from psycopg import sql

from corelata_api.progress_feed import ProgressFeed

log = logging.getLogger("corelata.api")

# TCP keepalives: a half-open socket (a firewall that dropped the idle session) is detected after
# 60 + 3 * 10 s instead of the OS default of about two hours.
KEEPALIVES = {
    "keepalives": 1,
    "keepalives_idle": 60,
    "keepalives_interval": 10,
    "keepalives_count": 3,
}
APPLICATION_NAME = "corelata-api-listen"  # how the connection shows in pg_stat_activity
BACKOFF_S: tuple[float, ...] = (1.0, 2.0, 4.0, 8.0, 16.0, 30.0)

Connect = Callable[[], Awaitable[psycopg.AsyncConnection]]
Sleep = Callable[[float], Awaitable[None]]


def listen_connection(url: str) -> Connect:
    """Opens the listener's connection: autocommit, so it never holds a transaction open (an open
    transaction on a listening session stops Postgres from trimming its notification queue)."""

    async def connect() -> psycopg.AsyncConnection:
        return await psycopg.AsyncConnection.connect(
            to_libpq_url(url),
            autocommit=True,
            connect_timeout=CONNECT_TIMEOUT_S,
            application_name=APPLICATION_NAME,
            **KEEPALIVES,
        )

    return connect


class RunListener:
    def __init__(
        self,
        connect: Connect,
        feed: ProgressFeed,
        *,
        backoff: Sequence[float] = BACKOFF_S,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._connect = connect
        self._feed = feed
        self._backoff = backoff
        self._sleep = sleep

    async def run(self) -> None:
        """Until cancelled: connect, LISTEN, hand notifications to the feed; on any failure tell
        the feed, wait the next backoff step and start again."""
        failures = 0
        while True:
            try:
                async with await self._connect() as conn:
                    await conn.execute(sql.SQL("LISTEN {}").format(sql.Identifier(RUN_CHANNEL)))
                    failures = 0
                    self._feed.set_listening(True)
                    log.info("progress listener connected")
                    async for note in conn.notifies():
                        self._handle(note.payload)
                    raise psycopg.OperationalError("the notification stream ended")
            except (psycopg.Error, OSError) as e:
                reason = error_reason(e)
            except Exception as e:  # noqa: BLE001 - the listener must outlive any one failure
                log.exception("progress listener failed")
                reason = type(e).__name__
            finally:
                self._feed.set_listening(False)
            delay = self._backoff[min(failures, len(self._backoff) - 1)]
            failures += 1
            log.warning(
                "progress listener lost the database: %s; polling every %s s, reconnecting in %s s",
                reason,
                self._feed.poll_s,
                delay,
            )
            await self._sleep(delay)

    def _handle(self, payload: str) -> None:
        try:
            run_id = uuid.UUID(payload)
        except ValueError:
            log.warning("progress listener ignored a notification that is not a run id")
            return
        self._feed.notify(run_id)
