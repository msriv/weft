"""Nightly stages 4 and 5: claim groups (embedding clustering within an event) and conflicts (NLI).

Models only supply inputs here (rule 2): groups and NLI scores feed the rules engine and the
short version. Nothing in this module decides that anything is true or false.
"""

import hashlib
from collections.abc import Callable
from itertools import combinations
from typing import Any

from pipeline.ctx import Ctx
from weft_core import graph
from weft_core.textutil import cosine


def cluster(
    claims: list[dict[str, Any]],
    threshold: float,
    contradicts: Callable[[str, str], bool] = lambda a, b: False,
) -> list[list[dict[str, Any]]]:
    """Single-link clustering by cosine, closest pairs first. Claims of one report never cluster
    together (a group means several reports say the same thing), and two clusters never join if
    any pair across them contradicts: opposite claims are close in vector space but are not the
    same claim."""
    pairs = sorted(
        (
            (cosine(claims[i]["embedding"], claims[j]["embedding"]), i, j)
            for i, j in combinations(range(len(claims)), 2)
            if claims[i]["report_id"] != claims[j]["report_id"]
        ),
        reverse=True,
    )
    clusters: dict[int, list[int]] = {i: [i] for i in range(len(claims))}
    owner = list(range(len(claims)))
    for sim, i, j in pairs:
        if sim < threshold:
            break
        a, b = owner[i], owner[j]
        if a == b or any(
            contradicts(claims[x]["text"], claims[y]["text"])
            for x in clusters[a]
            for y in clusters[b]
        ):
            continue
        for x in clusters[b]:
            owner[x] = a
        clusters[a] += clusters.pop(b)
    return [[claims[i] for i in members] for members in clusters.values()]


def run_groups(ctx: Ctx) -> int:
    perspective = {r["id"]: r["perspective"] for r in ctx.recent_reports(2)}
    by_event: dict[str, list[dict[str, Any]]] = {}
    for c in graph.select(ctx.db, "claims", "event_id IS NOT NULL"):
        by_event.setdefault(c["event_id"], []).append(c)
    made = 0
    for event_id, claims in by_event.items():
        for members in cluster(
            claims, ctx.cfg["nightly"]["claim_group_cosine"], lambda a, b: _contradict(ctx, a, b)
        ):
            members.sort(key=lambda c: (c["report_id"], c["start_char"]))
            gid = hashlib.sha256(f"{event_id}:{members[0]['id']}".encode()).hexdigest()[:32]
            persp = sorted(
                {perspective[c["report_id"]] for c in members if c["report_id"] in perspective}
            )
            label = min(members, key=lambda c: len(c["text"]))["text"]
            graph.put(
                ctx.db,
                "claim_groups",
                {
                    "id": gid,
                    "event_id": event_id,
                    "label": label[:300],
                    "perspectives": persp,
                    "n_reports": len({c["report_id"] for c in members}),
                },
            )
            for c in members:
                if c["group_id"] != gid:
                    graph.put(ctx.db, "claims", {**_row(c), "group_id": gid})
            made += 1
    return made


def _contradict(ctx: Ctx, a: str, b: str) -> bool:
    nli = ctx.nlp.nli
    p = max(nli.contradiction(a, b), nli.contradiction(b, a))
    return bool(p >= ctx.cfg["nightly"]["nli_contradiction"])


def run_conflicts(ctx: Ctx) -> int:
    """NLI over pairs of group labels in one event. Only topically close pairs are checked."""
    cfg = ctx.cfg["nightly"]
    by_event: dict[str, list[dict[str, Any]]] = {}
    for g in graph.select(ctx.db, "claim_groups"):
        by_event.setdefault(g["event_id"], []).append(g)
    made = 0
    for event_id, groups in by_event.items():
        for a, b in combinations(sorted(groups, key=lambda g: g["id"]), 2):
            embed = ctx.nlp.embedder.embed
            if cosine(embed(a["label"]), embed(b["label"])) < cfg["conflict_min_cosine"]:
                continue
            p = max(
                ctx.nlp.nli.contradiction(a["label"], b["label"]),
                ctx.nlp.nli.contradiction(b["label"], a["label"]),
            )
            if p >= cfg["nli_contradiction"]:
                _put_conflict(ctx, a["id"], b["id"], event_id, p)
                made += 1
    return made


def _put_conflict(ctx: Ctx, a: str, b: str, event_id: str, p: float) -> None:
    if not ctx.db.execute(
        "SELECT 1 FROM conflicts WHERE group_a=? AND group_b=? AND valid_to IS NULL", (a, b)
    ):
        ctx.db.execute(
            "INSERT INTO conflicts(group_a,group_b,event_id,nli_score,valid_from) VALUES(?,?,?,?,?)",
            (a, b, event_id, p, ctx.now),
        )


def _row(r: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in r.items() if k not in ("valid_from", "valid_to")}
