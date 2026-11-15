"""A small time-to-live cache for read-mostly data held by long-lived services (#162, #168)."""

import time
from collections.abc import Callable, Hashable
from typing import Any


class TtlCache:
    """Values expire after `ttl` seconds. Not shared between processes: each instance reloads
    at most once per TTL per key. `get(..., refresh=True)` reloads now (use after a miss)."""

    def __init__(self, ttl: float = 60.0, clock: Callable[[], float] = time.monotonic) -> None:
        self.ttl, self._clock = ttl, clock
        self._data: dict[Hashable, tuple[float, Any]] = {}

    def get[T](self, key: Hashable, load: Callable[[], T], *, refresh: bool = False) -> T:
        now = self._clock()
        hit = self._data.get(key)
        if hit is not None and not refresh and now - hit[0] < self.ttl:
            value: T = hit[1]
            return value
        value = load()
        self._data[key] = (now, value)
        if len(self._data) > 5000:  # bounded: drop the oldest entry
            self._data.pop(min(self._data, key=lambda k: self._data[k][0]))
        return value
