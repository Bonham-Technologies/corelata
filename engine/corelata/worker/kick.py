"""Starting an on-demand worker (the hosted demo, M19 spec §12.1; copied from Coglossa). After a
job is queued the API posts to `worker.kick_url`; the POST runs in the background and a failure
is only logged, because the cron also starts workers (spec §13.5)."""

import asyncio
import logging
import os
import time
from collections.abc import Callable, Mapping

import httpx

from corelata.config import WorkerConfig, env_headers
from corelata.service import JobQueue

log = logging.getLogger("corelata.worker")


class HttpKicker:
    def __init__(
        self,
        url: str,
        token: str | None,
        *,
        min_interval_s: float = 2.0,
        timeout_s: float = 5.0,
        extra_headers: Mapping[str, str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.url = url
        self.token = token
        self._min_interval = min_interval_s
        self._clock = clock
        self._last: float | None = None
        self._pending: set[asyncio.Task[None]] = set()
        headers = dict(extra_headers or {})
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.AsyncClient(timeout=timeout_s, headers=headers, transport=transport)

    def kick(self) -> None:
        now = self._clock()
        if self._last is not None and now - self._last < self._min_interval:
            return  # one worker start covers jobs queued moments apart
        self._last = now
        task = asyncio.get_running_loop().create_task(self._post())
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def _post(self) -> None:
        try:
            response = await self._client.post(self.url)
            response.raise_for_status()
        except Exception as e:  # kick never raises: a bad URL (InvalidURL) is not an HTTPError
            log.warning("worker kick failed: %s", " ".join(f"{type(e).__name__}: {e}".split()))

    async def drain(self) -> None:
        await asyncio.gather(*self._pending, return_exceptions=True)

    async def aclose(self) -> None:
        # kicks are best-effort (the cron is the backstop): do not hold shutdown for them
        pending = list(self._pending)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        await self._client.aclose()


class KickingQueue:
    """A JobQueue that kicks a worker after each job it queues. Corelata passes `priority`
    through (a discovery is fetched ahead of waiting runs, R-M17-29)."""

    def __init__(self, inner: JobQueue, kicker: HttpKicker) -> None:
        self.inner = inner
        self.kicker = kicker

    async def defer(
        self, task: str, *, lock: str | None = None, priority: int = 0, **kwargs: str
    ) -> None:
        await self.inner.defer(task, lock=lock, priority=priority, **kwargs)
        self.kicker.kick()


def build_kicker(cfg: WorkerConfig) -> HttpKicker | None:
    if cfg.kick_url is None:
        return None
    token = os.environ.get(cfg.kick_token_env) if cfg.kick_token_env else None
    return HttpKicker(cfg.kick_url, token, extra_headers=env_headers(cfg.extra_headers_env))
