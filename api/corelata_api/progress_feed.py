"""One database poller per run, shared by every open `GET /runs/{id}/events` stream (CRL-8,
R-M9-2). A stream subscribes with the state it has shown and receives each change after it; the
poller runs while anyone listens and stops at the run's terminal state, when the run disappears,
when the database fails, or when the last stream leaves.

The poller reads when the run is announced on the run channel (`notify`, from the API's
`RunListener`, CRL-22) and otherwise at a slow heartbeat, `poll_s * 10` capped at 30 s, in case a
notification was lost. While the listener is down it polls every `poll_s`, as before CRL-22
(R-M14-3)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from corelata.schema import TERMINAL_STATES, RunProgress
from corelata.store.db import error_reason
from corelata.store.runs import NotFoundError
from sqlalchemy.exc import InterfaceError, OperationalError

log = logging.getLogger("corelata.api")

Fetch = Callable[[uuid.UUID], Awaitable[RunProgress]]

HEARTBEAT_FACTOR = 10
HEARTBEAT_MAX_S = 30.0


class Deleted:
    """The run no longer exists."""


class Ended:
    """The poller stopped without a terminal state (database error); the stream closes and the
    browser reconnects after `retry`."""


DELETED = Deleted()
ENDED = Ended()
Update = RunProgress | Deleted | Ended


@dataclass
class _Watcher:
    joined: int  # the poller's read sequence when the stream subscribed
    shown: RunProgress  # what that stream has displayed


@dataclass
class _Poller:
    queues: dict[asyncio.Queue[Update], _Watcher] = field(default_factory=dict)
    seq: int = 0  # reads started so far
    wake: asyncio.Event = field(default_factory=asyncio.Event)  # read now, do not wait
    task: asyncio.Task[None] = field(init=False)


class ProgressFeed:
    def __init__(self, fetch: Fetch, poll_s: float) -> None:
        self._fetch = fetch
        self._poll_s = poll_s
        self._pollers: dict[uuid.UUID, _Poller] = {}
        self._listening = False

    @property
    def active(self) -> int:
        """Runs with a live poller."""
        return len(self._pollers)

    @property
    def poll_s(self) -> float:
        """The interval while the listener is down (`api.progress_poll_s`)."""
        return self._poll_s

    @property
    def heartbeat_s(self) -> float:
        """The interval while the listener is up: a lost notification costs at most this."""
        return max(self._poll_s, min(self._poll_s * HEARTBEAT_FACTOR, HEARTBEAT_MAX_S))

    @property
    def listening(self) -> bool:
        return self._listening

    def set_listening(self, listening: bool) -> None:
        """The listener connected (True) or lost its connection (False). Either way every poller
        reads once now: a change committed while nobody listened is not left for the heartbeat,
        and after a loss the pollers go back to `poll_s` without finishing a heartbeat wait."""
        if listening == self._listening:
            return
        self._listening = listening
        for poller in self._pollers.values():
            poller.wake.set()

    def notify(self, run_id: uuid.UUID) -> None:
        """The run changed: its poller, if any, reads now. Several notifications before that
        read cost one read."""
        poller = self._pollers.get(run_id)
        if poller is not None:
            poller.wake.set()

    def subscribe(self, run_id: uuid.UUID, last: RunProgress) -> asyncio.Queue[Update]:
        """Updates for one stream. `last` is what the stream has shown. The poller publishes to
        this queue only the result of a read that started after the subscription (so it is at
        least as fresh as the caller's own read, and nothing stale is pushed) and only when it
        differs from what the stream last showed (so a change between the caller's read and its
        subscription is not missed, and nothing is repeated). While the listener is up, a
        subscription starts a read at once: the notification of a change between the caller's
        read and its subscription may already have been spent."""
        queue: asyncio.Queue[Update] = asyncio.Queue()
        poller = self._pollers.get(run_id)
        if poller is None:
            poller = _Poller()
            poller.task = asyncio.create_task(self._run(run_id, poller))
            self._pollers[run_id] = poller
        poller.queues[queue] = _Watcher(poller.seq, last)
        if self._listening:
            poller.wake.set()
        return queue

    def unsubscribe(self, run_id: uuid.UUID, queue: asyncio.Queue[Update]) -> None:
        poller = self._pollers.get(run_id)
        if poller is None:
            return
        poller.queues.pop(queue, None)
        if not poller.queues:
            poller.task.cancel()
            del self._pollers[run_id]

    async def close(self) -> None:
        pollers = list(self._pollers.values())
        self._pollers.clear()
        for poller in pollers:
            for queue in poller.queues:
                queue.put_nowait(ENDED)  # streams still open at shutdown end cleanly
            poller.task.cancel()
        for poller in pollers:
            with contextlib.suppress(asyncio.CancelledError, Exception):  # shutting down
                await poller.task

    @staticmethod
    def _publish(poller: _Poller, update: Update) -> None:
        for queue in poller.queues:
            queue.put_nowait(update)

    @staticmethod
    def _publish_progress(poller: _Poller, seq: int, current: RunProgress) -> None:
        for queue, watcher in poller.queues.items():
            # A terminal state cannot be stale, and the poller stops after it: a stream that
            # joined during the final read must still get it.
            fresh = seq > watcher.joined or current.state in TERMINAL_STATES
            if fresh and current != watcher.shown:
                queue.put_nowait(current)
                watcher.shown = current

    async def _wait(self, poller: _Poller) -> None:
        interval = self.heartbeat_s if self._listening else self._poll_s
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(poller.wake.wait(), interval)
        poller.wake.clear()  # before the read: a notification during it causes another read

    async def _run(self, run_id: uuid.UUID, poller: _Poller) -> None:
        try:
            while True:
                await self._wait(poller)
                poller.seq += 1
                seq = poller.seq
                try:
                    current = await self._fetch(run_id)
                except NotFoundError:
                    self._publish(poller, DELETED)
                    return
                except (OperationalError, InterfaceError) as e:
                    log.warning(
                        "progress poller ended: %s", error_reason(e), extra={"run_id": str(run_id)}
                    )
                    self._publish(poller, ENDED)
                    return
                except Exception:
                    log.exception("progress poller failed", extra={"run_id": str(run_id)})
                    self._publish(poller, ENDED)
                    return
                self._publish_progress(poller, seq, current)
                if current.state in TERMINAL_STATES:
                    return
        finally:
            if self._pollers.get(run_id) is poller:  # a replacement poller's entry is not ours
                del self._pollers[run_id]
