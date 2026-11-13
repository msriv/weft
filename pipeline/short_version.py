"""Nightly stage 6: the short version, as pure set logic over which perspectives carry each
claim group. Coverage language only (rule 1): who reported what, never what is true.

Plus extractive story summaries (#112): claim groups of the last 48 h ranked by independent
origins times perspectives and picked by MMR, each shown as a real claim sentence with its
coverage label; TextRank over ledes when there are no groups yet. Every summary sentence is a
real sentence from a report.
"""

import re
from datetime import datetime, timedelta
from typing import Any

from pipeline.ctx import Ctx
from weft_core import graph, readmodel, store
from weft_core.textutil import cosine, jaccard, words


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


def mmr(items: list[dict[str, Any]], k: int, lam: float = 0.7) -> list[dict[str, Any]]:
    """Maximal marginal relevance: high `score`, low similarity to what is already picked.
    items: {score, vec}. Scores are scaled to [0, 1] first."""
    if not items:
        return []
    top = max(i["score"] for i in items) or 1.0
    picked: list[dict[str, Any]] = []
    rest = list(items)
    while rest and len(picked) < k:
        best = max(
            rest,
            key=lambda i: (
                lam * i["score"] / top
                - (1 - lam) * max((cosine(i["vec"], p["vec"]) for p in picked), default=0.0)
            ),
        )
        picked.append(best)
        rest.remove(best)
    return picked


def story_summary(
    groups: list[dict[str, Any]],
    conflicts: list[tuple[str, str]],
    named: set[str],
    k: int = 5,
) -> list[dict[str, Any]]:
    """Summary items from claim groups (#112): groups scored by independent origins times
    perspectives, picked by MMR, plus the top conflict pair and the top one-perspective item.
    Each item is a real claim sentence (rule 3) with a coverage label (rule 1).
    groups: {id, label, perspectives, origins, vec}."""
    by_id = {g["id"]: g for g in groups}
    for g in groups:
        g["score"] = g["origins"] * max(1, len(set(g["perspectives"]) - {"unattributed"}))
    in_conflict = {x for pair in conflicts for x in pair}
    out = []
    pair = max(
        (c for c in conflicts if c[0] in by_id and c[1] in by_id),
        key=lambda c: by_id[c[0]]["score"] + by_id[c[1]]["score"],
        default=None,
    )
    if pair:
        out.append(
            {
                "kind": "conflict",
                "text": f"{by_id[pair[0]]['label']} — versus — {by_id[pair[1]]['label']}",
                "coverage": "Reports conflict on this",
                "groups": list(pair),
            }
        )
    lone = [
        g
        for g in groups
        if g["id"] not in in_conflict
        and len(named) >= 2
        and len(set(g["perspectives"]) - {"unattributed"}) == 1
    ]
    one = max(lone, key=lambda g: g["score"], default=None)
    rest = [g for g in groups if g["id"] not in in_conflict and g is not one]
    for g in mmr(rest, k - len(out) - (1 if one else 0)):
        p = set(g["perspectives"]) - {"unattributed"}
        cov = (
            "Reported by all perspectives"
            if len(named) >= 2 and p >= named
            else f"Reported by {len(p)} perspective{'s' if len(p) != 1 else ''}"
        )
        out.append({"kind": "claim", "text": g["label"], "coverage": cov, "groups": [g["id"]]})
    if one:
        out.append(
            {
                "kind": "one_perspective",
                "text": one["label"],
                "coverage": f"One perspective only: {next(iter(set(one['perspectives']) - {'unattributed'}))}",
                "groups": [one["id"]],
            }
        )
    return out


def medoid_headline(reports: list[dict[str, Any]]) -> str | None:
    """The report whose embedding is closest to all news reports of the event (#112)."""
    news = [r for r in reports if r.get("type", "news") == "news" and r.get("embedding")]
    if not news:
        return None
    vecs = [r["embedding"] for r in news]
    best = max(
        range(len(news)),
        key=lambda i: (
            round(sum(cosine(vecs[i], v) for v in vecs), 9),
            [-ord(c) for c in news[i]["id"]],
        ),
    )
    return str(news[best]["id"])


def run(ctx: Ctx) -> int:
    n = 0
    recent_groups = (datetime.fromisoformat(ctx.now) - timedelta(hours=48)).isoformat()
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
        summary_groups: list[dict[str, Any]] = []
        summary_conflicts: list[tuple[str, str]] = []
        story_named: set[str] = set()
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
            label = medoid_headline(reports)
            if label and label != e.get("label_report_id"):
                ctx.db.execute(  # derived: set on every version, like origin_id
                    "MATCH (n:Event {id: ?}) SET n.label_report_id=?", (e["id"], label)
                )
            story_named |= {r["perspective"] for r in reports} - {"unattributed"}
            origin = {r["id"]: r.get("origin_id") or r["id"] for r in reports}
            members: dict[str, set[str]] = {}
            for c in graph.select(ctx.db, "claims", "n.event_id=?", (e["id"],)):
                if c["group_id"] and c["report_id"] in origin:
                    members.setdefault(c["group_id"], set()).add(origin[c["report_id"]])
            for g in groups:
                if (g["valid_from"] or "") >= recent_groups and g.get("embedding"):
                    summary_groups.append(
                        {**g, "origins": len(members.get(g["id"], ())), "vec": g["embedding"]}
                    )
            summary_conflicts += conf
            if e["first_seen"] >= recent:  # the story summary covers the last week only
                story_sents += [r["summary"].split(". ")[0] for r in reports[:3] if r["summary"]]
            n += 1
        items = story_summary(summary_groups, summary_conflicts, story_named)
        if items:
            payload: dict[str, Any] = {"summary": [i["text"] for i in items], "items": items}
        else:  # no claim groups in the last 48 h yet: extractive TextRank over ledes
            payload = {"summary": [story_sents[i] for i in textrank(story_sents)]}
        graph.put(ctx.db, "short_versions", {"id": f"story:{story}", "payload": payload})
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
