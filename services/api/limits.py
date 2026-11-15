"""In-process rate limits for the public API (#158).

shortcut: per-instance memory, so the real ceiling is limit x instances (max_instances = 5).
Upgrade to a shared counter (Redis/Memorystore) if abuse shows up across instances. The daily
ceiling on model spend does not depend on this: it is the spend ledger (#157).
"""

import hmac
import time
from collections import defaultdict, deque
from collections.abc import Callable

DAY = 86400.0
MAX_KEYS = 20_000  # bounded memory: the oldest keys are dropped first


class Limiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._hits: dict[tuple[str, str], deque[float]] = {}

    def check(self, name: str, key: str, per_minute: int, per_day: int) -> int | None:
        """None when allowed (the hit is counted). Otherwise seconds until a hit would pass."""
        now = self._clock()
        q = self._hits.setdefault((name, key), deque())
        while q and now - q[0] > DAY:
            q.popleft()
        recent = [t for t in q if now - t <= 60]
        if len(recent) >= per_minute:
            return max(1, int(60 - (now - recent[0])) + 1)
        if len(q) >= per_day:
            return max(1, int(DAY - (now - q[0])) + 1)
        q.append(now)
        if len(self._hits) > MAX_KEYS:
            self._hits.pop(next(iter(self._hits)))
        return None


class Streams:
    """Open SSE connections: a cap per client and a cap in total."""

    def __init__(self, per_client: int, total: int) -> None:
        self.per_client, self.total = per_client, total
        self._open: defaultdict[str, int] = defaultdict(int)

    def acquire(self, key: str) -> bool:
        if self._open[key] >= self.per_client or sum(self._open.values()) >= self.total:
            return False
        self._open[key] += 1
        return True

    def release(self, key: str) -> None:
        self._open[key] = max(0, self._open[key] - 1)
        if not self._open[key]:
            del self._open[key]


def client_key(headers: dict[str, str], peer: str, proxy_secret: str) -> str:
    """Who is calling. The web proxy sends the browser's address in `x-weft-client-ip`, signed
    with a shared secret; a direct caller cannot forge it. Otherwise the address Cloud Run
    appended last to `x-forwarded-for` (the direct caller's), which the caller cannot set."""
    signed = proxy_secret and hmac.compare_digest(headers.get("x-weft-proxy", ""), proxy_secret)
    if signed and (ip := headers.get("x-weft-client-ip", "").strip()):
        return ip
    return headers.get("x-forwarded-for", "").split(",")[-1].strip() or peer
