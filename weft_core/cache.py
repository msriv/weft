"""A small time-to-live cache for read-mostly data held by long-lived services (#162, #168)."""

import time
from collections.abc import Callable, Hashable
from typing import Any


class TtlCache:
    """Values expire after `ttl` seconds (or the per-entry ttl given to `put`). Not shared between
    processes: each instance reloads at most once per TTL per key. `get(..., refresh=True)`
    reloads now (use after a miss)."""

    def __init__(self, ttl: float = 60.0, clock: Callable[[], float] = time.monotonic) -> None:
        self.ttl, self._clock = ttl, clock
        self._data: dict[Hashable, tuple[float, Any, float]] = {}

    def peek(self, key: Hashable) -> Any | None:
        hit = self._data.get(key)
        if hit is None or self._clock() - hit[0] >= hit[2]:
            return None
        return hit[1]

    def put(self, key: Hashable, value: Any, ttl: float | None = None) -> None:
        self._data[key] = (self._clock(), value, self.ttl if ttl is None else ttl)
        if len(self._data) > 5000:  # bounded: drop the oldest entry
            self._data.pop(min(self._data, key=lambda k: self._data[k][0]))

    def clear(self) -> None:
        self._data.clear()

    def get[T](self, key: Hashable, load: Callable[[], T], *, refresh: bool = False) -> T:
        if not refresh and (hit := self.peek(key)) is not None:
            value: T = hit
            return value
        value = load()
        self.put(key, value)
        return value
