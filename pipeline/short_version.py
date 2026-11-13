"""Nightly stage 6: the short version, as pure set logic over which perspectives carry each
claim group. Coverage language only (rule 1): who reported what, never what is true.

Plus extractive story summaries (TextRank over source sentences): every summary sentence is a
real sentence from a report.
"""

import re
from datetime import datetime, timedelta
from typing import Any

from pipeline.ctx import Ctx
from weft_core import graph, readmodel, store
from weft_core.textutil import jaccard, words


def short_version(
    groups: list[dict[str, Any]],
    conflicts: list[tuple[str, str]],
    event_perspectives: set[str],
    parties: set[str],
) -> dict[str, Any]:
    """groups: {id, label, perspectives}. parties: perspective codes of the story's parties."""
    in_conflict = {g for pair in conflicts for g in pair}
    out: dict[str, list[Any]] = {
        "reported_by_all": [],
        "reports_conflict_on": [[a, b] for a, b in conflicts],
        "one_perspective_only": [],
        "no_source_published": sorted(parties - event_perspectives),
    }
    named = event_perspectives - {"unattributed"}
    for g in groups:
        p = set(g["perspectives"]) - {"unattributed"}
        if g["id"] in in_conflict:
            continue
        if len(named) >= 2 and p >= named:
            out["reported_by_all"].append(g["id"])
        elif len(p) == 1 and len(named) >= 2:  # "only one" means something only if others reported
            out["one_perspective_only"].append({"group": g["id"], "perspective": next(iter(p))})
    return out


def textrank(sents: list[str], k: int = 3, iters: int = 30) -> list[int]:
    """Indices of the k most central sentences (word-overlap graph, damping 0.85)."""
    ws = [set(words(s)) for s in sents]
    n = len(sents)
    if n <= k:
        return list(range(n))
    w = [[jaccard(ws[i], ws[j]) if i != j else 0.0 for j in range(n)] for i in range(n)]
    rank = [1.0 / n] * n
    for _ in range(iters):
        rank = [
            0.15 / n + 0.85 * sum(w[j][i] / (sum(w[j]) or 1) * rank[j] for j in range(n))
            for i in range(n)
        ]
    return sorted(sorted(range(n), key=lambda i: -rank[i])[:k])


def run(ctx: Ctx) -> int:
    n = 0
    recent = (datetime.fromisoformat(ctx.now) - timedelta(days=7)).isoformat()
    for story in {r["story_id"] for r in ctx.recent_reports(14)}:
        # grouped beats (D21): every outlet group is a side; else country parties
        parties = set(store.beat_groups(ctx.db, story).values()) or {
            p["party"].upper()
            for p in ctx.db.execute(
                "MATCH (n:StoryParty {story_id: ?}) RETURN n.party AS party", (story,)
            )
            if re.fullmatch(r"[A-Za-z]{2}", p["party"])
        }
        story_sents: list[str] = []
        share = _origin_shares(ctx, story)
        tracked, _ = readmodel.untracked(ctx.db, sorted(parties))
        for e in graph.select(ctx.db, "events", "n.story_id=?", (story,)):
            reports = graph.reports_of_event(ctx.db, e["id"])
            expected = _expected(ctx, e, reports, parties, set(tracked), share)
            groups = graph.select(ctx.db, "claim_groups", "n.event_id=?", (e["id"],))
            conf = [
                (c["group_a"], c["group_b"])
                for c in graph.select(ctx.db, "conflicts", "n.event_id=?", (e["id"],))
            ]
            sv = short_version(groups, conf, {r["perspective"] for r in reports}, expected)
            graph.put(ctx.db, "short_versions", {"id": e["id"], "payload": sv})
            if e["first_seen"] >= recent:  # the story summary covers the last week only
                story_sents += [r["summary"].split(". ")[0] for r in reports[:3] if r["summary"]]
            n += 1
        top = textrank(story_sents)
        graph.put(
            ctx.db,
            "short_versions",
            {"id": f"story:{story}", "payload": {"summary": [story_sents[i] for i in top]}},
        )
    return n


def _origin_shares(ctx: Ctx, story: str) -> dict[str, float]:
    """q_p: each perspective's share of the story's independent texts over 30 days."""
    rows = graph.select(
        ctx.db,
        "reports",
        "n.story_id=? AND coalesce(n.published_at, n.fetched_at) >= ?",
        (story, (datetime.fromisoformat(ctx.now) - timedelta(days=30)).isoformat()),
    )
    origins: dict[str, str] = {}
    for r in rows:
        origins.setdefault(r.get("origin_id") or r["id"], r["perspective"])
    total = len(origins) or 1
    out: dict[str, float] = {}
    for p in origins.values():
        out[p] = out.get(p, 0.0) + 1 / total
    return out


def _expected(
    ctx: Ctx,
    e: dict[str, Any],
    reports: list[dict[str, Any]],
    parties: set[str],
    tracked: set[str],
    share: dict[str, float],
) -> set[str]:
    """Parties whose silence on this event means something (#100): Weft tracks no source there
    (shown as untracked), or the event is big enough that p would be expected to have published
    (N * q_p >= 3, a Poisson P(0) <= 0.05) and a healthy source from p published something
    within 48 h of the event."""
    n = len({r.get("origin_id") or r["id"] for r in reports})
    end = (datetime.fromisoformat(e["first_seen"]) + timedelta(hours=48)).isoformat()
    out = set()
    for p in parties:
        if p not in tracked:
            out.add(p)
            continue
        if n * share.get(p, 0.0) < 3:
            continue
        if ctx.db.execute(
            "MATCH (r:Report {perspective: ?}) WHERE r.valid_to IS NULL "
            "AND coalesce(r.published_at, r.fetched_at) >= ? "
            "AND coalesce(r.published_at, r.fetched_at) <= ? "
            "MATCH (s:Source {id: r.source_id}) WHERE coalesce(s.healthy, 1) = 1 "
            "RETURN 1 AS x LIMIT 1",
            (p, e["first_seen"], end),
        ):
            out.add(p)
    return out
