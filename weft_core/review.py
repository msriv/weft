"""Editor review queue: a 1% sample of merges, claims and translations (nightly stage 11).

Optional, never a gate on publishing (D15). Ratings feed the exit check for Phase 2: merge and
claim quality against the agreed bar.
"""

import hashlib
import json
import math
from datetime import UTC, datetime
from typing import Any

from weft_core import graph
from weft_core.store import Db


def _rank(day: str, ref: str) -> str:
    return hashlib.sha256(f"{day}:{ref}".encode()).hexdigest()


def sample(db: Db, since: str, rate: float, now: str | None = None) -> int:
    """Queue a deterministic sample of everything created since `since`. Returns items queued."""
    now = now or datetime.now(UTC).isoformat()
    day = now[:10]
    pools: dict[str, list[tuple[str, dict[str, Any]]]] = {
        "merge": [
            (r["id"], {"title": r["title"], "event_id": r["event_id"], "url": r["url"]})
            for r in graph.select(
                db, "reports", "event_id IS NOT NULL AND valid_from >= ?", (since,)
            )
        ],
        "claim": [
            (c["id"], {"text": c["text"], "report_id": c["report_id"]})
            for c in graph.select(db, "claims", "valid_from >= ?", (since,))
        ],
        "translation": [
            (t["key"], {"lang": t["lang"], "text": t["text"][:300]})
            for t in db.execute("SELECT * FROM translations WHERE created_at >= ?", (since,))
        ],
    }
    queued = 0
    for kind, items in pools.items():
        if not items:
            continue
        take = max(1, math.ceil(rate * len(items)))
        for ref, payload in sorted(items, key=lambda x: _rank(day, x[0]))[:take]:
            before = db.execute("SELECT 1 FROM review_items WHERE id=?", (f"{kind}:{ref}",))
            if not before:
                db.execute(
                    "INSERT INTO review_items(id,kind,ref_id,payload,sampled_at) VALUES(?,?,?,?,?)",
                    (f"{kind}:{ref}", kind, ref, json.dumps(payload), now),
                )
                queued += 1
    return queued


def open_items(db: Db) -> list[dict[str, Any]]:
    rows = db.execute("SELECT * FROM review_items WHERE rating IS NULL ORDER BY sampled_at")
    return [{**r, "payload": json.loads(r["payload"])} for r in rows]


def rate(db: Db, item_id: str, rating: str, reviewer: str) -> bool:
    if rating not in ("good", "bad"):
        raise ValueError("rating must be good or bad")
    if not db.execute("SELECT 1 FROM review_items WHERE id=?", (item_id,)):
        return False
    db.execute(
        "UPDATE review_items SET rating=?, reviewer=?, rated_at=? WHERE id=?",
        (rating, reviewer, datetime.now(UTC).isoformat(), item_id),
    )
    return True


def quality(db: Db) -> dict[str, dict[str, float]]:
    """Per kind: rated count and the share rated good (the exit-check number)."""
    out: dict[str, dict[str, float]] = {}
    for r in db.execute(
        "SELECT kind, COUNT(*) AS n, SUM(rating='good') AS good FROM review_items "
        "WHERE rating IS NOT NULL GROUP BY kind"
    ):
        out[r["kind"]] = {"rated": r["n"], "good_share": r["good"] / r["n"]}
    return out
