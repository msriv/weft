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
    """Re-cluster claims of events that got reports inside the regroup window. A group is
    written only when it is new or changed, and groups that no longer exist are closed, so
    `valid_from` means "first seen in this form" and stale groups never stay current."""
    days = ctx.cfg["nightly"]["regroup_days"]
    touched = {r["event_id"] for r in ctx.recent_reports(days) if r["event_id"]}
    by_event: dict[str, list[dict[str, Any]]] = {e: [] for e in touched}
    for c in graph.select(ctx.db, "claims", "n.event_id IS NOT NULL"):
        if c["event_id"] in touched:
            by_event[c["event_id"]].append(c)
    made = 0
    for event_id, claims in by_event.items():
        perspective = {r["id"]: r["perspective"] for r in graph.reports_of_event(ctx.db, event_id)}
        old = {
            g["id"]: g for g in graph.select(ctx.db, "claim_groups", "n.event_id=?", (event_id,))
        }
        keep: set[str] = set()
        for members in cluster(
            claims, ctx.cfg["nightly"]["claim_group_cosine"], lambda a, b: _contradict(ctx, a, b)
        ):
            members.sort(key=lambda c: (c["report_id"], c["start_char"]))
            gid = hashlib.sha256(
                f"{event_id}:{'|'.join(sorted(c['id'] for c in members))}".encode()
            ).hexdigest()[:32]  # id = membership: a changed group is a new group
            keep.add(gid)
            persp = sorted(
                {perspective[c["report_id"]] for c in members if c["report_id"] in perspective}
            )
            row = {
                "id": gid,
                "event_id": event_id,
                "label": min(members, key=lambda c: len(c["text"]))["text"][:300],
                "perspectives": persp,
                "n_reports": len({c["report_id"] for c in members}),
            }
            prev = old.get(gid)
            if prev is None or any(
                prev[k] != row[k] for k in ("label", "perspectives", "n_reports")
            ):
                graph.put(ctx.db, "claim_groups", row)
                made += 1
            for c in members:
                if c["group_id"] != gid:
                    graph.put(ctx.db, "claims", {**_row(c), "group_id": gid})
        for gid in set(old) - keep:  # superseded groups stop being current
            ctx.db.execute(
                "MATCH (n:ClaimGroup {id: ?}) WHERE n.valid_to IS NULL SET n.valid_to=?",
                (gid, ctx.now),
            )
    return made


def nli_scores(ctx: Ctx, premise: str, hypothesis: str) -> tuple[float, float]:
    """(contradiction, entailment) of one direction, cached by text hash in the graph so a pair
    is scored once across nights (#99). The NLI model is pinned, so the cache stays valid."""
    key = hashlib.sha256(f"{premise}\x00{hypothesis}".encode()).hexdigest()[:32]
    hit = ctx.db.execute("MATCH (n:NliCache {key: ?}) RETURN n.c AS c, n.e AS e", (key,))
    if hit:
        return float(hit[0]["c"]), float(hit[0]["e"])
    c = ctx.nlp.nli.contradiction(premise, hypothesis)
    e = ctx.nlp.nli.entailment(premise, hypothesis)
    ctx.db.execute("MERGE (n:NliCache {key: ?}) SET n.c=?, n.e=?", (key, c, e))
    return c, e


def contradicts(ctx: Ctx, a: str, b: str) -> float:
    """Contradiction score when the pair counts as contradicting, else 0: at least the threshold
    both ways, or 0.9 one way with entailment under 0.1 that way."""
    cut = ctx.cfg["nightly"]["nli_contradiction"]
    (cab, eab), (cba, eba) = nli_scores(ctx, a, b), nli_scores(ctx, b, a)
    if min(cab, cba) >= cut:
        return max(cab, cba)
    one_way = [c for c, e in ((cab, eab), (cba, eba)) if c >= 0.9 and e < 0.1]
    return max(one_way, default=0.0)


def _contradict(ctx: Ctx, a: str, b: str) -> bool:
    return contradicts(ctx, a, b) > 0


def content(c: dict[str, Any]) -> str:
    """The claim without its attribution wrapper (#101): "X said Y" compares as Y."""
    if c.get("content_start") is None or c.get("start_char") is None:
        return str(c["text"])
    a, b = c["content_start"] - c["start_char"], c["content_end"] - c["start_char"]
    return str(c["text"][a:b]) or str(c["text"])


def _medoid(texts: list[str], embed: Callable[[str], list[float]]) -> str:
    if not texts:
        return ""
    vecs = [embed(t) for t in texts]
    return texts[max(range(len(texts)), key=lambda i: sum(cosine(vecs[i], v) for v in vecs))]


def run_conflicts(ctx: Ctx) -> int:
    """NLI over pairs of claim groups in one event (#99): the content of each group's label
    claim, attribution stripped, after the event's medoid headline as shared context. Only pairs
    that are topically close, share an entity and give no differing number are checked; numbers
    are the numbers rule's job."""
    from pipeline.figures import numbers

    cfg = ctx.cfg["nightly"]
    by_event: dict[str, list[dict[str, Any]]] = {}
    for g in graph.select(ctx.db, "claim_groups"):
        by_event.setdefault(g["event_id"], []).append(g)
    embedded: dict[str, list[float]] = {}

    def embed(t: str) -> list[float]:
        if t not in embedded:
            embedded[t] = ctx.nlp.embedder.embed(t)
        return embedded[t]

    made = 0
    for event_id, groups in by_event.items():
        claims = graph.select(ctx.db, "claims", "n.event_id=?", (event_id,))
        label_claim: dict[str, dict[str, Any]] = {}
        for c in claims:
            g = c["group_id"]
            if g and (g not in label_claim or len(c["text"]) < len(label_claim[g]["text"])):
                label_claim[g] = c
        head = _medoid([r["title"] for r in graph.reports_of_event(ctx.db, event_id)], embed)
        text = {
            g["id"]: content(label_claim[g["id"]]) if g["id"] in label_claim else g["label"]
            for g in groups
        }
        ents = {gid: {n for n, _ in ctx.nlp.entities.extract(t)} for gid, t in text.items()}
        nums = {gid: {f["value"] for f in numbers(t)} for gid, t in text.items()}
        for a, b in combinations(sorted(groups, key=lambda g: g["id"]), 2):
            ta, tb = text[a["id"]], text[b["id"]]
            if cosine(embed(ta), embed(tb)) < cfg["conflict_min_cosine"]:
                continue
            if ents[a["id"]] and ents[b["id"]] and not ents[a["id"]] & ents[b["id"]]:
                continue  # about different things
            if nums[a["id"]] and nums[b["id"]] and nums[a["id"]] != nums[b["id"]]:
                continue
            ctx_a, ctx_b = (f"{head}. {ta}", f"{head}. {tb}") if head else (ta, tb)
            p = contradicts(ctx, ctx_a, ctx_b)
            if p > 0:
                _put_conflict(ctx, a["id"], b["id"], event_id, p)
                made += 1
    return made


def _put_conflict(ctx: Ctx, a: str, b: str, event_id: str, p: float) -> None:
    ctx.db.execute(
        "OPTIONAL MATCH (c:Conflict {group_a: ?, group_b: ?}) WHERE c.valid_to IS NULL "
        "WITH c WHERE c IS NULL "
        "CREATE (:Conflict {group_a: ?, group_b: ?, event_id: ?, nli_score: ?, valid_from: ?})",
        (a, b, a, b, event_id, p, ctx.now),
    )


def _row(r: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in r.items() if k not in ("valid_from", "valid_to")}
