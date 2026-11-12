"""Editor review queue: a 1% sample of merges, claims and translations (nightly stage 11).

Optional, never a gate on publishing (D15). Ratings feed the exit check for Phase 2: merge and
claim quality against the agreed bar.
"""

import hashlib
import json
import math
from datetime import UTC, datetime
from typing import Any

from weft_core import graph, store
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
                db, "reports", "n.event_id IS NOT NULL AND n.valid_from >= ?", (since,)
            )
        ],
        "claim": [
            (c["id"], {"text": c["text"], "report_id": c["report_id"]})
            for c in graph.select(db, "claims", "n.valid_from >= ?", (since,))
        ],
        "translation": [
            (t["key"], {"lang": t["lang"], "text": t["text"][:300]})
            for t in store.nodes(
                db,
                "Translation",
                "MATCH (n:Translation) WHERE n.created_at >= ? RETURN n",
                (since,),
            )
        ],
    }
    queued = 0
    for kind, items in pools.items():
        if not items:
            continue
        take = max(1, math.ceil(rate * len(items)))
        for ref, payload in sorted(items, key=lambda x: _rank(day, x[0]))[:take]:
            made = db.execute(
                "MERGE (n:ReviewItem {id: ?}) ON CREATE SET n.kind=?, n.ref_id=?, n.payload=?, "
                "n.sampled_at=?, n.new=true WITH n, n.new AS new REMOVE n.new RETURN new",
                (f"{kind}:{ref}", kind, ref, json.dumps(payload), now),
            )
            queued += bool(made[0]["new"])
    return queued


def open_items(db: Db) -> list[dict[str, Any]]:
    rows = store.nodes(
        db,
        "ReviewItem",
        "MATCH (n:ReviewItem) WHERE n.rating IS NULL RETURN n ORDER BY n.sampled_at",
    )
    return [{**r, "payload": json.loads(r["payload"])} for r in rows]


def rate(db: Db, item_id: str, rating: str, reviewer: str) -> bool:
    if rating not in ("good", "bad"):
        raise ValueError("rating must be good or bad")
    return bool(
        db.execute(
            "MATCH (n:ReviewItem {id: ?}) SET n.rating=?, n.reviewer=?, n.rated_at=? RETURN 1 AS x",
            (item_id, rating, reviewer, datetime.now(UTC).isoformat()),
        )
    )


def quality(db: Db) -> dict[str, dict[str, float]]:
    """Per kind: rated count and the share rated good (the exit-check number)."""
    out: dict[str, dict[str, float]] = {}
    for r in db.execute(
        "MATCH (n:ReviewItem) WHERE n.rating IS NOT NULL RETURN n.kind AS kind, count(n) AS n, "
        "sum(CASE WHEN n.rating='good' THEN 1 ELSE 0 END) AS good"
    ):
        out[r["kind"]] = {"rated": r["n"], "good_share": r["good"] / r["n"]}
    return out
