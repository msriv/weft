"""One change poll per story per instance, fanned out to every open SSE connection (#168)."""

import asyncio
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Any


class ChangeHub:
    def __init__(
        self, changes: Callable[[str, str], list[dict[str, Any]]], interval: float
    ) -> None:
        self._changes, self._interval = changes, interval
        self._subs: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}

    async def _poll(self, story_id: str) -> None:
        cursor = datetime.now(UTC).isoformat()
        while self._subs.get(story_id):
            for m in await asyncio.to_thread(self._changes, story_id, cursor):
                cursor = max(cursor, m["at"])
                for q in list(self._subs.get(story_id, ())):
                    q.put_nowait(m)
            await asyncio.sleep(self._interval)

    async def subscribe(self, story_id: str) -> AsyncIterator[dict[str, Any] | None]:
        """Yields changes; None on each quiet interval (the caller sends a keepalive)."""
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subs.setdefault(story_id, set()).add(q)
        task = self._tasks.get(story_id)
        if task is None or task.done():
            self._tasks[story_id] = asyncio.create_task(self._poll(story_id))
        try:
            while True:
                try:
                    yield await asyncio.wait_for(q.get(), timeout=self._interval)
                except TimeoutError:
                    yield None
        finally:
            subs = self._subs.get(story_id, set())
            subs.discard(q)
            if not subs:
                self._subs.pop(story_id, None)  # the poll loop ends on its next turn
