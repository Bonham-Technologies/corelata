"""A small LRU for the re-rendered reports `GET /runs/{id}/report?with_claim_ids=1` serves. A
completed run's record never changes, so a render keyed on (run, format) stays valid for the life
of the process (CRL-9, R-M9-5). It is bounded twice: by entry count and by the bytes it holds
(`api.render_cache_mb`, CRL-19, R-M10-5); a render larger than the whole budget is served but
never stored, so one huge report cannot empty the cache."""

from collections import OrderedDict


class RenderCache:
    def __init__(self, capacity: int = 64, max_bytes: int = 64 * 1024 * 1024) -> None:
        if capacity < 1:
            raise ValueError("capacity must be at least 1")
        if max_bytes < 0:
            raise ValueError("max_bytes must not be negative")
        self._capacity = capacity
        self._max_bytes = max_bytes
        self._items: OrderedDict[tuple[str, str], bytes] = OrderedDict()
        self._bytes = 0

    @property
    def max_bytes(self) -> int:
        return self._max_bytes

    @property
    def total_bytes(self) -> int:
        return self._bytes

    def get(self, run_id: str, fmt: str) -> bytes | None:
        key = (run_id, fmt)
        value = self._items.get(key)
        if value is not None:
            self._items.move_to_end(key)
        return value

    def put(self, run_id: str, fmt: str, content: bytes) -> None:
        key = (run_id, fmt)
        old = self._items.pop(key, None)
        if old is not None:
            self._bytes -= len(old)
        if self._max_bytes == 0 or len(content) > self._max_bytes:
            return
        while self._items and (
            len(self._items) >= self._capacity or self._bytes + len(content) > self._max_bytes
        ):
            _, evicted = self._items.popitem(last=False)
            self._bytes -= len(evicted)
        self._items[key] = content
        self._bytes += len(content)

    def __len__(self) -> int:
        return len(self._items)
