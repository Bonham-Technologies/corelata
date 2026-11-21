"""Single-flight and a short reuse window for `GET /api/system/doctor?probe=true` (CRL-112).

A probe sends a test completion to every model server, the auditor's included, so repeated or
concurrent calls load the servers the runs use and, on the hosted demo, spend money. Concurrent
callers share one run, and a finished report is served again for `ttl_s` seconds. A run that
raises is not kept, so the next call tries again. The shared run is shielded: a caller that
disconnects does not cancel it for the others. The cache is per process; each API worker
probes at most once per window.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable

from corelata.schema import DoctorReport

DOCTOR_PROBE_TTL_S = 30.0


class DoctorCache:
    def __init__(
        self, ttl_s: float = DOCTOR_PROBE_TTL_S, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._ttl_s = ttl_s
        self._clock = clock
        self._report: DoctorReport | None = None
        self._finished_at = 0.0
        self._running: asyncio.Task[DoctorReport] | None = None

    async def get(self, run: Callable[[], Awaitable[DoctorReport]]) -> DoctorReport:
        """The report from a run that finished within the window, else the one in flight, else
        a new run of `run`."""
        if self._report is not None and self._clock() - self._finished_at < self._ttl_s:
            return self._report
        if self._running is None:
            self._running = asyncio.create_task(self._run(run))
            # every caller may have gone by the time a run fails: retrieve its exception so it
            # is never reported as unretrieved
            self._running.add_done_callback(lambda t: t.cancelled() or t.exception())
        return await asyncio.shield(self._running)

    async def _run(self, run: Callable[[], Awaitable[DoctorReport]]) -> DoctorReport:
        try:
            report = await run()
        finally:
            self._running = None
        self._report = report
        self._finished_at = self._clock()
        return report
