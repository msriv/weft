"""Source yield, polling cadence, dormancy and the active-source ceiling (#171). No model.

Yield = on-beat reports / reports stored over the last `window_days`. Nothing here hides a
stored report (rule 6): it only decides which sources are polled, and how often.
"""

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

from weft_core import store


def refresh(db: store.Db, cfg: dict[str, Any], now: datetime | None = None) -> list[str]:
    """Store each active source's yield. A source with no on-beat report in `dormant_days`
    (and older than that) becomes dormant, unless an admin asked for it. Returns the new ids."""
    now = now or datetime.now(UTC)
    since = (now - timedelta(days=cfg["window_days"])).isoformat()
    long_ago = (now - timedelta(days=cfg["dormant_days"])).isoformat()
    rows = db.execute(
        "MATCH (r:Report) WHERE r.valid_to IS NULL AND coalesce(r.published_at, r.fetched_at) >= ? "
        "RETURN r.source_id AS id, count(r) AS seen, count(r.story_id) AS onbeat",
        (min(since, long_ago),),
    )
    recent = db.execute(
        "MATCH (r:Report) WHERE r.valid_to IS NULL AND r.story_id IS NOT NULL "
        "AND coalesce(r.published_at, r.fetched_at) >= ? RETURN DISTINCT r.source_id AS id",
        (long_ago,),
    )
    live = {r["id"] for r in recent}
    stats = {r["id"]: r for r in rows}
    dormant = []
    for s in store.all_sources(db, "n.status='active'"):
        st = stats.get(s["id"])
        y = None
        if st:
            win = db.execute(
                "MATCH (r:Report {source_id: ?}) WHERE r.valid_to IS NULL "
                "AND coalesce(r.published_at, r.fetched_at) >= ? RETURN count(r) AS seen, "
                "count(r.story_id) AS onbeat",
                (s["id"], since),
            )[0]
            y = win["onbeat"] / win["seen"] if win["seen"] else 0.0
        db.execute("MATCH (n:Source {id: ?}) SET n.yield_14d = ?", (s["id"], y))
        old = (s.get("discovered_at") or "") < long_ago
        if old and s["id"] not in live and (s.get("discovered_via") or "") != "admin":
            db.execute(
                "MATCH (n:Source {id: ?}) SET n.status = 'dormant', n.dormant_at = ?",
                (s["id"], now.isoformat()),
            )
            dormant.append(s["id"])
    return dormant


def due(source: dict[str, Any], cfg: dict[str, Any], now: datetime | None = None) -> bool:
    """High-yield (or not yet measured) sources are polled every run; low-yield ones every
    `low_every`-th run. The slot is fixed per source, so load is spread and nothing is random."""
    y = source.get("yield")
    if y is None or y >= cfg["low_yield"]:
        return True
    now = now or datetime.now(UTC)
    run = int(now.timestamp() // cfg["run_seconds"])
    offset = int(hashlib.sha256(source["id"].encode()).hexdigest(), 16)
    return bool((run + offset) % cfg["low_every"] == 0)


def make_room(db: store.Db, beat_id: str, relevance: float, cfg: dict[str, Any]) -> bool:
    """True when a new source may be active: there is room under both ceilings, or it displaces
    the lowest-yield active source of the beat (made dormant) whose discovery relevance is lower.
    Admin-requested sources do not come through here."""
    active = store.all_sources(db, "n.status='active'")
    mine = [s for s in active if s.get("discovered_via") == f"gdelt:{beat_id}"]
    if len(mine) < cfg["max_per_beat"] and len(active) < cfg["max_total"]:
        return True
    pool = (
        mine
        if len(mine) >= cfg["max_per_beat"]
        else [s for s in active if (s.get("discovered_via") or "").startswith("gdelt:")]
    )
    if not pool:
        return False
    worst = min(pool, key=lambda s: (s.get("yield_14d") or 0.0, s.get("disc_rel") or 0.0))
    if relevance <= (worst.get("disc_rel") or 0.0):
        return False
    db.execute(
        "MATCH (n:Source {id: ?}) SET n.status = 'dormant', n.dormant_at = ?",
        (worst["id"], datetime.now(UTC).isoformat()),
    )
    return True


def order(
    cands: list[tuple[str, float]], counts: dict[str, int], country: Any
) -> list[tuple[str, float]]:
    """Candidates from countries with the fewest active sources first, then by relevance.
    `country(domain)` may return None (unknown), which counts as uncovered."""
    return sorted(cands, key=lambda c: (counts.get(country(c[0]) or "", 0), -c[1], c[0]))
