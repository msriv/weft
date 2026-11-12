"""Nightly stage 6: the short version, as pure set logic over which perspectives carry each
claim group. Coverage language only (rule 1): who reported what, never what is true.

Plus extractive story summaries (TextRank over source sentences): every summary sentence is a
real sentence from a report.
"""

import re
from typing import Any

from pipeline.ctx import Ctx
from weft_core import graph
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
        elif len(p) == 1:
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
    for story in {r["story_id"] for r in ctx.recent_reports(14)}:
        parties = {
            p["party"].upper()
            for p in ctx.db.execute(
                "MATCH (n:StoryParty {story_id: ?}) RETURN n.party AS party", (story,)
            )
            if re.fullmatch(r"[A-Za-z]{2}", p["party"])
        }
        story_sents: list[str] = []
        for e in graph.select(ctx.db, "events", "n.story_id=?", (story,)):
            reports = graph.reports_of_event(ctx.db, e["id"])
            groups = graph.select(ctx.db, "claim_groups", "n.event_id=?", (e["id"],))
            conf = [
                (c["group_a"], c["group_b"])
                for c in graph.select(ctx.db, "conflicts", "n.event_id=?", (e["id"],))
            ]
            sv = short_version(groups, conf, {r["perspective"] for r in reports}, parties)
            graph.put(ctx.db, "short_versions", {"id": e["id"], "payload": sv})
            story_sents += [r["summary"].split(". ")[0] for r in reports[:3] if r["summary"]]
            n += 1
        top = textrank(story_sents)
        graph.put(
            ctx.db,
            "short_versions",
            {"id": f"story:{story}", "payload": {"summary": [story_sents[i] for i in top]}},
        )
    return n
