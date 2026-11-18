"""The pack listing `GET /api/packs` serves and the name check the other pack routes make,
re-read only when a file under the pack directories changed (CRL-8, R-M9-4), and that is checked
at most once per `min_interval_s` (CRL-18, R-M10-2): an edit can take up to a second to show.
Resolving and validating still parse on each call: a customer edits packs in place."""

import threading
import time
from collections.abc import Callable
from pathlib import Path

from corelata.standards.loader import PackSummary, list_packs, pack_dirs_signature


class PackIndex:
    def __init__(
        self,
        packs_dir: Path | None,
        min_interval_s: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._packs_dir = packs_dir
        self._min_interval_s = min_interval_s
        self._clock = clock
        self._stat_at: float | None = None
        self._signature: tuple[tuple[str, int, int], ...] | None = None
        self._listing: list[PackSummary] = []
        self._lock = threading.Lock()

    def listing(self) -> list[PackSummary]:
        """Callers run this in a worker thread (R-M10-10): the lock makes concurrent callers wait
        for the walk in progress and serve its result instead of starting their own."""
        with self._lock:
            now = self._clock()
            if self._stat_at is not None and now - self._stat_at < self._min_interval_s:
                return self._listing
            self._stat_at = now
            signature = pack_dirs_signature(self._packs_dir)
            if signature != self._signature:
                self._listing = list_packs(self._packs_dir)
                self._signature = signature
            return self._listing

    def names(self) -> set[str]:
        return {p.name for p in self.listing()}
