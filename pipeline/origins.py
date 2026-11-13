"""Nightly stage: independent origins (#98). Reports of one event whose texts are near copies
(5-shingle containment >= 0.6, or stream MinHash >= 0.8) form one origin cluster; its origin is
the earliest report. Rules and coverage labels count origins, so one wire story republished by
ten outlets counts once. Copies stay listed (rule 6): only counts change."""

from typing import Any

from pipeline.ctx import Ctx
from weft_core import graph
from weft_core.textutil import minhash_similarity, shingles

CONTAINMENT = 0.6
MINHASH = 0.8


def containment(a: set[str], b: set[str]) -> float:
    return len(a & b) / min(len(a), len(b)) if a and b else 0.0


def clusters(reps: list[dict[str, Any]], texts: dict[str, str]) -> dict[str, str]:
    """Report id -> origin id (union-find, O(n^2) per event)."""
    parent = {r["id"]: r["id"] for r in reps}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    sh = {r["id"]: shingles(texts[r["id"]]) for r in reps}
    for i, a in enumerate(reps):
        for b in reps[i + 1 :]:
            mh = (
                minhash_similarity(a["minhash"], b["minhash"])
                if a.get("minhash") and b.get("minhash")
                else 0.0
            )
            if mh >= MINHASH or containment(sh[a["id"]], sh[b["id"]]) >= CONTAINMENT:
                parent[find(a["id"])] = find(b["id"])
    when = {r["id"]: (r["published_at"] or r["fetched_at"] or "", r["id"]) for r in reps}
    first: dict[str, str] = {}
    for r in reps:
        root = find(r["id"])
        if root not in first or when[r["id"]] < when[first[root]]:
            first[root] = r["id"]
    return {r["id"]: first[find(r["id"])] for r in reps}


def run(ctx: Ctx) -> int:
    changed = 0
    events = {r["event_id"] for r in ctx.recent_reports(ctx.cfg["nightly"]["regroup_days"])}
    for eid in events - {None}:
        reps = graph.reports_of_event(ctx.db, eid)
        texts = {r["id"]: ctx.text_of(r) or f"{r['title']} {r['summary']}" for r in reps}
        origin_of = clusters(reps, texts)
        for r in reps:
            origin = origin_of[r["id"]]
            if r.get("origin_id") != origin:
                ctx.db.execute(  # every version: origin is derived, not history
                    "MATCH (n:Report {id: ?}) SET n.origin_id=?", (r["id"], origin)
                )
                changed += 1
    return changed
