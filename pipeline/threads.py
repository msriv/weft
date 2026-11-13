"""Nightly: thread the events of a story (#109).

Event B FOLLOWS an earlier event A when they share informative entities (IDF-weighted entity
cosine at least `thread_entity_cosine`), their text is related but below the attach cut
(centroid cosine inside `thread_centroid_band`), and B began within `thread_max_gap_days` of A's
last report. Each event keeps only its best predecessor, so threads form a forest. A thread is
labelled by its two most informative entities. Deterministic; no model.
"""

from datetime import datetime, timedelta
from typing import Any

from pipeline.ctx import Ctx
from services.stream_worker.worker import IDF_WINDOW, story_idf
from weft_core import clustering, graph
from weft_core.textutil import cosine


def predecessor(
    b: dict[str, Any], earlier: list[dict[str, Any]], cfg: dict[str, Any], idf: dict[str, float]
) -> str | None:
    lo, hi = cfg["thread_centroid_band"]
    gap = timedelta(days=cfg["thread_max_gap_days"])
    start = datetime.fromisoformat(b["first_seen"])
    ents = set(clustering.entity_counts(b))
    best, pick = 0.0, None
    for a in earlier:
        if start - datetime.fromisoformat(a.get("last_seen") or a["first_seen"]) > gap:
            continue
        ent = clustering.entity_cosine(ents, clustering.entity_counts(a), idf)
        if (
            ent < cfg["thread_entity_cosine"]
            or not lo <= cosine(b["centroid"], a["centroid"]) <= hi
        ):
            continue
        if ent > best:
            best, pick = ent, a["id"]
    return pick


def label(members: list[dict[str, Any]], idf: dict[str, float]) -> str:
    weight: dict[str, float] = {}
    for e in members:
        for name, n in clustering.entity_counts(e).items():
            weight[name] = weight.get(name, 0.0) + n * idf.get(name, 1.0)
    return " · ".join(sorted(weight, key=lambda k: (-weight[k], k))[:2])


def root(eid: str, follows: dict[str, str | None]) -> str:
    """First event of `eid`'s thread (predecessors outside the window end the walk)."""
    while (up := follows.get(eid)) and up in follows:
        eid = up
    return eid


def run(ctx: Ctx) -> int:
    cfg = ctx.cfg["nightly"]
    now = datetime.fromisoformat(ctx.now)
    since = (now - timedelta(days=cfg["regroup_days"])).isoformat()
    look = (now - timedelta(days=cfg["regroup_days"] + cfg["thread_max_gap_days"])).isoformat()
    links = 0
    for story_id in {r["story_id"] for r in ctx.recent_reports(cfg["regroup_days"])}:
        events = sorted(
            graph.select(ctx.db, "events", "n.story_id=? AND n.first_seen >= ?", (story_id, look)),
            key=lambda e: (e["first_seen"], e["id"]),
        )
        idf, _ = story_idf(ctx.db, story_id, (now - IDF_WINDOW).isoformat())
        follows: dict[str, str | None] = {e["id"]: e.get("follows") for e in events}
        for i, b in enumerate(events):
            if b["first_seen"] >= since:
                follows[b["id"]] = predecessor(b, events[:i], cfg, idf)
        threads: dict[str, list[dict[str, Any]]] = {}
        for e in events:
            threads.setdefault(root(e["id"], follows), []).append(e)
        for tid, members in threads.items():
            name = label(members, idf) if len(members) > 1 else None
            for e in members:
                links += follows[e["id"]] is not None
                # derived fields: set on every version, like origin_id
                ctx.db.execute(
                    "MATCH (n:Event {id: ?}) SET n.follows=?, n.thread_id=?, n.thread_label=?",
                    (e["id"], follows[e["id"]], tid, name),
                )
    return links
