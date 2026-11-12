"""Re-fetch published articles at +1 h, +24 h and +7 days and keep each version (silent-edit rule).

The first version is recorded by the stream worker. Each later fetch stores its raw copy next to
the original (`{item_id}.v{n}.html`, same private 30-day lifecycle) and a row in
`report_versions`. The rules engine diffs consecutive versions; this module only collects them.
"""

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from services.fetcher.fetcher import _extract, interval
from weft_core.polite import PoliteClient
from weft_core.store import Db

DELAYS = [
    timedelta(hours=1),
    timedelta(hours=24),
    timedelta(days=7),
]  # config/rules.yaml refetch_after


class VersionStore(Protocol):
    def save_version(self, item_id: str, n: int, content: bytes, ext: str) -> None: ...


Enqueue = Callable[[dict[str, Any], datetime], None]


def schedule(msg: dict[str, Any], enqueue: Enqueue, now: datetime | None = None) -> None:
    now = now or datetime.now(UTC)
    for n, delay in enumerate(DELAYS, start=1):
        enqueue(
            {"item_id": msg["item_id"], "source_id": msg["source_id"], "url": msg["url"], "n": n},
            now + delay,
        )


def text_hash(text: str) -> str:
    return hashlib.sha256(" ".join(text.split()).encode()).hexdigest()


def refetch(
    task: dict[str, Any], source: dict[str, Any], http: PoliteClient, db: Db, files: VersionStore
) -> str:
    """Returns 'skipped' (robots, cooldown, 429: Cloud Tasks retries), 'unchanged' or 'changed'."""
    resp = http.get(task["url"], interval(source), {})
    if resp is None:
        return "skipped"
    ctype = resp.headers.get("content-type", "")
    meta, ext = _extract(resp.content, task["url"], ctype)
    text = meta.get("text") or ""
    if not text.strip():
        return "unchanged"  # page gone or paywalled now; never treat an empty page as an edit
    h = text_hash(text)
    last = db.execute(
        "MATCH (v:ReportVersion {report_id: ?}) RETURN v.text_hash AS text_hash "
        "ORDER BY v.n DESC LIMIT 1",
        (task["item_id"],),
    )
    files.save_version(task["item_id"], task["n"], resp.content, ext)
    db.execute(
        "MERGE (v:ReportVersion {report_id: ?, n: ?}) SET v.fetched_at=?, v.text_hash=?",
        (task["item_id"], task["n"], datetime.now(UTC).isoformat(), h),
    )
    return "changed" if last and last[0]["text_hash"] != h else "unchanged"
