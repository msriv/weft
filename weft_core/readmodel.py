"""Read model behind the public API: plain functions from the graph to JSON-ready dicts.

Only public stories are readable (the admin toggle, D15); anything under a non-public story
returns None and the API answers 404. Source weight changes ordering only (rule 6): every report
is returned, sorted, never filtered. Labels use coverage language only (rule 1). Documents carry
their issuer and whether the issuer is a party to this story (rule 7).
"""

import json
import math
import os
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from weft_core import config, detective, feedback, graph, store
from weft_core.perspectives import perspective_of
from weft_core.rules import log_odds
from weft_core.store import Db
from weft_core.textutil import cosine, words
from weft_core.weights import FACTORS

QUIET_AFTER = timedelta(hours=48)


# --- shared helpers ---------------------------------------------------------------------------


def public_story(db: Db, story_id: str) -> dict[str, Any] | None:
    s = store.get_story(db, story_id)
    return s if s and s["public"] == 1 else None


def parties(db: Db, story_id: str) -> list[dict[str, Any]]:
    return [
        {"party": r["party"], "cited": bool(r["citation"]), "citation": r["citation"]}
        for r in store.nodes(
            db,
            "StoryParty",
            "MATCH (n:StoryParty {story_id: ?}) RETURN n ORDER BY n.party",
            (story_id,),
        )
    ]


def sources_by_id(db: Db) -> dict[str, dict[str, Any]]:
    return {s["id"]: s for s in store.all_sources(db)}


def weights_latest(db: Db) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for r in store.nodes(db, "SourceWeight", "MATCH (n:SourceWeight) RETURN n ORDER BY n.day"):
        out[r["source_id"]] = {
            "weight": r["weight"],
            "insufficient": bool(r["insufficient"]),
            "factors": json.loads(r["factors"]),
            "n_reports": r["n_reports"],
        }
    return out


def source_label(s: dict[str, Any], w: dict[str, Any] | None = None) -> dict[str, Any]:
    state = s["state_run"]
    return {
        "id": s["id"],
        "name": s["name"],
        "homepage": s["homepage"],
        "type": s["type"],
        "country": s["country"],
        "perspective": perspective_of(s),
        # state_run and ownership are only asserted with a citation; otherwise "unverified"
        "state_run": "unverified" if state is None else ("state-run" if state else "not state-run"),
        "state_run_source": s["state_run_source"],
        "owner_id": s["owner_id"],
        "ownership_source": s["ownership_source"],
        "paywalled": bool(s["paywalled"]),
        "healthy": bool(s["healthy"]),
        "weight": w["weight"] if w else None,
        "weight_insufficient": w["insufficient"] if w else True,
    }


def untracked(db: Db, codes: list[str]) -> tuple[list[str], list[str]]:
    """Split "no source has published" perspectives into (sources exist but published nothing,
    Weft tracks no active source there). The second is a gap in Weft's list, not silence."""
    have = {perspective_of(s) for s in store.all_sources(db, "n.status='active'")}
    have |= {g for b in store.beats(db) for g in b["groups"].values()}
    return [c for c in codes if c in have], [c for c in codes if c not in have]


def _split_sv(db: Db, sv: dict[str, Any] | None) -> dict[str, Any] | None:
    if not sv:
        return sv
    published, missing = untracked(db, sv.get("no_source_published") or [])
    return {**sv, "no_source_published": published, "untracked": missing}


def issuer_label(s: dict[str, Any], story_parties: list[dict[str, Any]]) -> dict[str, Any]:
    """Rule 7: a document is its issuer's account; whether that issuer is a party is per story."""
    names = {p["party"].lower() for p in story_parties}
    persp = perspective_of(s).lower()
    return {
        **source_label(s),
        "is_party": persp in names or s["name"].lower() in names or s["id"].lower() in names,
    }


def _anomaly_view(a: dict[str, Any]) -> dict[str, Any]:
    return {
        k: a[k]
        for k in (
            "id",
            "rule",
            "rule_version",
            "status",
            "subject_kind",
            "subject_id",
            "story_id",
            "event_id",
            "summary",
            "inputs",
            "evidence_ids",
            "detail",
        )
    } | {"since": a["valid_from"]}


def anomalies_for(
    db: Db, where: str, args: tuple[Any, ...] = (), at: str | None = None
) -> list[dict[str, Any]]:
    return [
        _anomaly_view(a)
        for a in graph.select(db, "anomalies", f"n.status<>'withdrawn' AND ({where})", args, at)
    ]


# --- stories ----------------------------------------------------------------------------------


def story_card(db: Db, s: dict[str, Any], at: str | None = None) -> dict[str, Any]:
    reps = graph.select(db, "reports", "n.story_id=?", (s["id"],), at)
    anomalies = anomalies_for(db, "n.story_id=?", (s["id"],), at)
    last = max((r["published_at"] or r["fetched_at"] or "" for r in reps), default=None)
    now = datetime.fromisoformat(at) if at else datetime.now(UTC)
    quiet = not last or now - datetime.fromisoformat(last) > QUIET_AFTER
    return {
        "id": s["id"],
        "title": s["title"],
        "beat": s["beat_id"],
        "status": "quiet" if quiet else "developing",
        "reports": len(reps),
        "events": len({r["event_id"] for r in reps if r["event_id"]}),
        "sources": len({r["source_id"] for r in reps}),
        "perspectives": sorted({r["perspective"] for r in reps}),
        "anomalies": sum(a["status"] == "active" for a in anomalies),
        "provisional_anomalies": sum(a["status"] == "provisional" for a in anomalies),
        "last_report_at": last,
        "parties": parties(db, s["id"]),
    }


def list_stories(
    db: Db, region: str | None = None, topic: str | None = None, sort: str = "recent"
) -> list[dict[str, Any]]:
    cards = [
        story_card(db, s)
        for s in store.nodes(db, "Story", "MATCH (n:Story {public: 1}) RETURN n ORDER BY n.id")
    ]
    if region:
        cards = [c for c in cards if region.upper() in c["perspectives"]]
    if topic:
        cards = [c for c in cards if c["beat"] == topic]
    key = {
        "recent": lambda c: c["last_report_at"] or "",
        "anomalies": lambda c: (c["anomalies"], c["last_report_at"] or ""),
        "reports": lambda c: c["reports"],
    }.get(sort, lambda c: c["last_report_at"] or "")
    return sorted(cards, key=key, reverse=True)


WINDOW_DAYS = 7


def story_graph(
    db: Db,
    story_id: str,
    at: str | None = None,
    days: int = WINDOW_DAYS,
    until: str | None = None,
) -> dict[str, Any] | None:
    """Nodes and edges for the story view, as of `at` (Replay). Layout is computed by the client:
    x = day, one band per perspective, official documents on the spine. Only the `days` days
    ending at `until` (default: `at`, else now) are shown; `days=0` shows the whole story."""
    s = public_story(db, story_id)
    if s is None:
        return None
    src = sources_by_id(db)
    plist = parties(db, story_id)
    end = until or at or datetime.now(UTC).isoformat()
    start = (datetime.fromisoformat(end) - timedelta(days=days)).isoformat() if days else ""
    every = graph.select(db, "reports", "n.story_id=?", (story_id,), at)
    when = {r["id"]: r["published_at"] or r["fetched_at"] or "" for r in every}
    reps = [r for r in every if start <= when[r["id"]] <= end]
    rep_ids = {r["id"] for r in reps}
    in_window = {r["event_id"] for r in reps if r["event_id"]}
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in reps:
        if r["event_id"]:
            groups[(r["event_id"], r["perspective"])].append(r)
    anomalies = [
        a
        for a in anomalies_for(db, "n.story_id=?", (story_id,), at)
        if a["event_id"] in in_window or rep_ids & set(a["evidence_ids"])
    ]
    flagged = defaultdict(list)
    for a in anomalies:
        for rid in a["evidence_ids"]:
            flagged[rid].append(a["id"])
    nodes: list[dict[str, Any]] = []
    for (eid, persp), rs in sorted(groups.items()):
        stamps = sorted(when[r["id"]] for r in rs)
        nodes.append(
            {
                "id": f"{eid}:{persp}",
                "kind": "report_group",
                "event_id": eid,
                "perspective": persp,
                "count": len(rs),
                "at": stamps[0],
                "sources": sorted(
                    {src[r["source_id"]]["name"] for r in rs if r["source_id"] in src}
                ),
                "anomalies": sorted({a for r in rs for a in flagged.get(r["id"], [])}),
                "report_ids": [r["id"] for r in rs],
            }
        )
    for d in graph.select(db, "documents", "n.story_id=?", (story_id,), at):
        if not start <= (d["published_at"] or "") <= end:
            continue
        issuer = src.get(d["issuer_id"])
        nodes.append(
            {
                "id": d["id"],
                "kind": "document",
                "event_id": d["event_id"],
                "title": d["title"],
                "doc_kind": d["kind"],
                "at": d["published_at"],
                "issuer": issuer_label(issuer, plist) if issuer else None,
                "anomalies": [],
            }
        )
    gid_persp: dict[str, set[str]] = {
        g["id"]: set(g["perspectives"])
        for g in graph.select(
            db,
            "claim_groups",
            "EXISTS { MATCH (e:Event {id: n.event_id, story_id: ?}) }",
            (story_id,),
            at,
        )
    }
    edges = []
    for c in graph.select(db, "conflicts", "true", (), at):
        if c["event_id"] in in_window and c["group_a"] in gid_persp and c["group_b"] in gid_persp:
            edges.append(
                {
                    "kind": "conflict",
                    "event_id": c["event_id"],
                    "groups": [c["group_a"], c["group_b"]],
                    "between": [sorted(gid_persp[c["group_a"]]), sorted(gid_persp[c["group_b"]])],
                    "nli_score": c["nli_score"],
                }
            )
    sv = graph.get(db, "short_versions", f"story:{story_id}", at)
    return {
        "story": story_card(db, s, at),
        "as_of": at,
        "summary": (sv or {}).get("payload", {}).get("summary", []),
        "summary_items": (sv or {}).get("payload", {}).get("items", []),
        "perspectives": sorted({n["perspective"] for n in nodes if "perspective" in n}),
        "nodes": nodes,
        "edges": edges,
        "anomalies": anomalies,
        "events": [
            event_row(db, e, at)
            for e in graph.select(
                db, "events", "n.story_id=?", (story_id,), at, "ORDER BY n.first_seen DESC"
            )
            if e["id"] in in_window
        ],
        "window": {
            "from": start or None,
            "to": end,
            "days": days,
            "older": any(t < start for t in when.values()) if start else False,
        },
        "short_version": _split_sv(db, _event_short_versions(db, story_id, at, in_window)),
        "weights_note": "Source weight changes ordering only. No report is hidden.",
    }


def _event_short_versions(
    db: Db, story_id: str, at: str | None, events: set[str] | None = None
) -> dict[str, Any]:
    """Story-level short version: the event-level set logic with claim-group labels resolved,
    so the page can say what is reported by all, what conflicts, and what no source has published."""
    label = {
        g["id"]: g["label"]
        for g in graph.select(
            db,
            "claim_groups",
            "EXISTS { MATCH (e:Event {id: n.event_id, story_id: ?}) }",
            (story_id,),
            at,
        )
    }
    out: dict[str, Any] = {
        "reported_by_all": [],
        "reports_conflict_on": [],
        "one_perspective_only": [],
        "no_source_published": [],
    }
    for e in graph.select(db, "events", "n.story_id=?", (story_id,), at):
        sv = (
            graph.get(db, "short_versions", e["id"], at)
            if events is None or e["id"] in events
            else None
        )
        if not sv:
            continue
        p = sv["payload"]
        out["reported_by_all"] += [
            {"event_id": e["id"], "group": g, "label": label.get(g, "")}
            for g in p["reported_by_all"]
        ]
        out["reports_conflict_on"] += [
            {"event_id": e["id"], "labels": [label.get(g, "") for g in pair]}
            for pair in p["reports_conflict_on"]
        ]
        out["one_perspective_only"] += [
            {
                "event_id": e["id"],
                "label": label.get(x["group"], ""),
                "perspective": x["perspective"],
            }
            for x in p["one_perspective_only"]
        ]
        out["no_source_published"] = sorted(
            set(out["no_source_published"]) | set(p["no_source_published"])
        )
    return out


def event_row(db: Db, e: dict[str, Any], at: str | None = None) -> dict[str, Any]:
    reps = graph.reports_of_event(db, e["id"], at)
    # the medoid headline among news reports (#112), else the earliest report's
    first = next(
        (r for r in reps if r["id"] == e.get("label_report_id")), reps[0] if reps else None
    )
    return {
        "id": e["id"],
        "story_id": e["story_id"],
        "label": first["title"] if first else None,
        "label_source": _source_name(db, first["source_id"]) if first else None,
        "first_seen": e["first_seen"],
        "reports": len(reps),
        "outlets": len({r["source_id"] for r in reps}),
        "origins": len({r.get("origin_id") or r["id"] for r in reps}),
        "perspectives": sorted({r["perspective"] for r in reps}),
        "grouping_confidence": e["grouping_confidence"],
        "follows": e.get("follows"),
        "thread_id": e.get("thread_id") or e["id"],
        "thread_label": e.get("thread_label"),
    }


def _source_name(db: Db, source_id: str) -> str | None:
    rows = store.all_sources(db, "n.id=?", (source_id,))
    return rows[0]["name"] if rows else None


# --- events -----------------------------------------------------------------------------------


def event_page(db: Db, event_id: str, at: str | None = None) -> dict[str, Any] | None:
    e = graph.get(db, "events", event_id, at)
    if e is None or public_story(db, e["story_id"]) is None:
        return None
    src, wts, plist = sources_by_id(db), weights_latest(db), parties(db, e["story_id"])
    reps = graph.reports_of_event(db, event_id, at)
    by_p: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in reps:
        s = src.get(r["source_id"])
        if s is None:
            continue
        by_p[r["perspective"]].append(
            {
                "id": r["id"],
                "url": r["url"],
                "title": r["title"],
                "summary": r["summary"],
                "type": r["type"],
                "lang": r["lang"],
                "published_at": r["published_at"],
                "source": source_label(s, wts.get(s["id"])),
                "copy_of": [
                    c["copy_of"]
                    for c in db.execute(
                        "MATCH (c:Copy {report_id: ?}) RETURN c.copy_of AS copy_of", (r["id"],)
                    )
                ],
            }
        )
    for rs in by_p.values():  # ordering only: heavier sources first, nothing dropped
        rs.sort(key=lambda r: (-(r["source"]["weight"] or 0), r["published_at"] or ""))
    groups = graph.select(db, "claim_groups", "n.event_id=?", (event_id,), at)
    claims = graph.select(db, "claims", "n.event_id=?", (event_id,), at)
    claim_by_group: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in claims:
        if c["group_id"]:
            claim_by_group[c["group_id"]].append(
                {
                    "report_id": c["report_id"],
                    "text": c["text"],
                    "start": c["start_char"],
                    "end": c["end_char"],
                }
            )
    figs = [
        {
            k: f[k]
            for k in (
                "id",
                "report_id",
                "kind",
                "quantity",
                "value",
                "unit",
                "speaker",
                "text",
                "start_char",
                "end_char",
            )
        }
        for f in graph.select(db, "figures", "n.event_id=?", (event_id,), at)
    ]
    docs = []
    for d in graph.select(db, "documents", "n.event_id=?", (event_id,), at):
        s = src.get(d["issuer_id"])
        docs.append(
            {
                "id": d["id"],
                "title": d["title"],
                "kind": d["kind"],
                "url": d["url"],
                "published_at": d["published_at"],
                "issuer": issuer_label(s, plist) if s else None,
            }
        )
    sv = graph.get(db, "short_versions", event_id, at)
    return {
        "event": event_row(db, e, at),
        "voices": _voices(by_p),
        "perspectives": {p: rs for p, rs in sorted(by_p.items())},
        "claim_groups": [
            {
                "id": g["id"],
                "label": g["label"],
                "perspectives": g["perspectives"],
                "n_reports": g["n_reports"],
                "claims": claim_by_group.get(g["id"], []),
            }
            for g in groups
        ],
        "conflicts": [
            {"groups": [c["group_a"], c["group_b"]], "nli_score": c["nli_score"]}
            for c in graph.select(db, "conflicts", "n.event_id=?", (event_id,), at)
        ],
        "figures": figs,
        "documents": docs,
        "anomalies": anomalies_for(db, "n.event_id=?", (event_id,), at),
        "short_version": _split_sv(db, sv["payload"]) if sv else None,
        "parties": plist,
    }


def _voices(by_p: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    """Per perspective: the heaviest source's headline and the words used far more than by the
    other perspectives (weighted log-odds). A reading aid, not a flag: no anomaly comes from it."""
    counts = {
        p: Counter(w for r in rs for w in words(f"{r['title']} {r['summary']}") if len(w) > 3)
        for p, rs in by_p.items()
    }
    out = {}
    for p, rs in by_p.items():
        rest: Counter[str] = Counter()
        for q, c in counts.items():
            if q != p:
                rest.update(c)
        z = log_odds(counts[p], rest) if rest else {}
        top = [w for w, v in sorted(z.items(), key=lambda x: -x[1]) if v > 1.0][:5]
        out[p] = {
            "headline": rs[0]["title"] if rs else None,
            "headline_source": rs[0]["source"]["name"] if rs else None,
            "words": top,
            "reports": len(rs),
        }
    return out


# --- nodes ------------------------------------------------------------------------------------


def node(db: Db, node_id: str) -> dict[str, Any] | None:
    """Any node by id, with its evidence and links to the original sources."""
    for table, kind in (
        ("reports", "report"),
        ("documents", "document"),
        ("claim_groups", "claim_group"),
        ("anomalies", "anomaly"),
        ("events", "event"),
        ("claims", "claim"),
    ):
        row = graph.get(db, table, node_id)
        if row is None:
            continue
        sid = row.get("story_id") or (
            (graph.get(db, "events", row["event_id"]) or {}).get("story_id")
            if row.get("event_id")
            else None
        )
        if sid is None or public_story(db, sid) is None:
            return None
        row = {k: v for k, v in row.items() if k not in ("embedding", "centroid", "minhash")}
        links = []
        if kind in ("report", "document"):
            links = [{"label": "Original", "url": row["url"]}]
        if kind == "anomaly":
            links = [_evidence(db, i) for i in row["evidence_ids"]]
        return {"kind": kind, "node": row, "links": links}
    return None


def _evidence(db: Db, eid: str) -> dict[str, Any]:
    """An evidence id as a reader sees it: outlet and headline for a report, the sentence for a
    figure. Both link to the report node."""
    fig = graph.get(db, "figures", eid)
    rid = fig["report_id"] if fig else eid
    r = graph.get(db, "reports", rid)
    if r is None:
        return {"label": "Evidence", "id": eid}
    src = sources_by_id(db).get(r["source_id"], {}).get("name", r["source_id"])
    out = {"label": f"{src}: {r['title']}", "id": rid, "source": src}
    if fig:
        # the sentence (claim) the figure sits in, else the figure's own span
        at = fig["start_char"] or 0
        claim = next(
            (
                c
                for c in graph.select(db, "claims", "n.report_id=?", (rid,))
                if (c["start_char"] or 0) <= at < (c["end_char"] or 0)
            ),
            None,
        )
        out["quote"] = claim["text"] if claim else fig["text"]
    return out


# --- sources ----------------------------------------------------------------------------------


def list_sources(db: Db) -> list[dict[str, Any]]:
    w = weights_latest(db)
    out = [source_label(s, w.get(s["id"])) for s in store.all_sources(db, "n.status='active'")]
    return sorted(out, key=lambda s: (-(s["weight"] or 0), s["name"]))


def source_profile(db: Db, source_id: str) -> dict[str, Any] | None:
    s = sources_by_id(db).get(source_id)
    if s is None:
        return None
    w = weights_latest(db)
    # public stories only: a source page never leaks reports of unpublished stories
    reps = graph.select(
        db,
        "reports",
        "n.source_id=? AND EXISTS { MATCH (s:Story {id: n.story_id, public: 1}) }",
        (source_id,),
    )
    ids = {r["id"] for r in reps}
    anomalies = [
        a
        for a in anomalies_for(db, "true")
        if a["subject_id"] == source_id or ids & set(a["evidence_ids"])
    ]
    history = [
        {"day": r["day"], "weight": r["weight"]}
        for r in db.execute(
            "MATCH (n:SourceWeight {source_id: ?}) RETURN n.day AS day, n.weight AS weight "
            "ORDER BY n.day",
            (source_id,),
        )
    ]
    siblings = (
        [
            x["name"]
            for x in db.execute(
                "MATCH (n:Source {owner_id: ?}) WHERE n.id<>? RETURN n.name AS name",
                (s["owner_id"], source_id),
            )
        ]
        if s["owner_id"]
        else []
    )
    cur = w.get(source_id)
    claims = graph.select(db, "claims", "n.report_id IN ?", (list(ids),)) if ids else []
    return {
        "source": source_label(s, cur),
        "factors": cur["factors"] if cur else None,
        "factor_names": list(FACTORS),
        "history": history,
        "anomalies": anomalies,
        "same_owner": siblings,
        "index": {
            "reports": len(reps),
            "claims": len(claims),
            "stories": len({r["story_id"] for r in reps}),
            "tracked_since": s["discovered_at"],
        },
        "weight_note": "Weight changes ordering only. No report is hidden. We never score whether an outlet was right.",
    }


# --- documents and actors ---------------------------------------------------------------------


def document_page(db: Db, doc_id: str) -> dict[str, Any] | None:
    d = graph.get(db, "documents", doc_id)
    if d is None or d["story_id"] is None or public_story(db, d["story_id"]) is None:
        return None
    s = sources_by_id(db).get(d["issuer_id"])
    plist = parties(db, d["story_id"])
    statements = [
        {
            "id": r["id"],
            "actor_id": r["actor_id"],
            "actor": r["name"],
            "role": r["role"],
            "text": r["text"],
            "start": r["start_char"],
            "end": r["end_char"],
        }
        for r in db.execute(
            "MATCH (st:Statement {document_id: ?}) MATCH (a:Actor {id: st.actor_id}) "
            "RETURN st.id AS id, st.actor_id AS actor_id, a.name AS name, a.role AS role, "
            "st.text AS text, st.start_char AS start_char, st.end_char AS end_char "
            "ORDER BY st.start_char",
            (doc_id,),
        )
    ]
    return {
        "document": {
            k: d[k]
            for k in (
                "id",
                "url",
                "kind",
                "title",
                "summary",
                "published_at",
                "lang",
                "story_id",
                "event_id",
            )
        },
        "issuer": issuer_label(s, plist) if s else None,
        "label": (
            f"Issued by {s['name']}, a party to this story: this is that party's account."
            if s and issuer_label(s, plist)["is_party"]
            else f"Issued by {s['name']}."
            if s
            else None
        ),
        "statements": statements,
        "event": event_row(db, graph.get(db, "events", d["event_id"]) or {}, None)
        if d["event_id"]
        else None,
    }


def actor_page(db: Db, actor_id: str) -> dict[str, Any] | None:
    rows = store.nodes(db, "Actor", "MATCH (n:Actor {id: ?}) RETURN n", (actor_id,))
    if not rows:
        return None
    a = rows[0]
    statements = [
        {
            "id": r["id"],
            "document_id": r["document_id"],
            "text": r["text"],
            "title": r["title"],
            "published_at": r["published_at"],
            "story_id": r["story_id"],
        }
        for r in db.execute(
            "MATCH (st:Statement {actor_id: ?}) MATCH (d:Document {id: st.document_id}) "
            "WHERE d.valid_to IS NULL AND EXISTS { MATCH (:Story {id: d.story_id, public: 1}) } "
            "RETURN st.id AS id, st.document_id AS document_id, st.text AS text, "
            "d.title AS title, d.published_at AS published_at, d.story_id AS story_id "
            "ORDER BY d.published_at DESC",
            (actor_id,),
        )
    ]
    if not statements:
        return None  # an actor with no public statements has no public page
    quoted = [
        {"report_id": f["report_id"], "quote": f["text"], "event_id": f["event_id"]}
        for f in graph.select(
            db,
            "figures",
            "n.kind='quote' AND n.speaker IS NOT NULL AND toLower(n.speaker)=toLower(?) AND "
            "EXISTS { MATCH (e:Event {id: n.event_id}) WHERE e.valid_to IS NULL AND "
            "EXISTS { MATCH (:Story {id: e.story_id, public: 1}) } }",
            (a["name"],),
        )
    ]
    return {
        "actor": {k: a[k] for k in ("id", "name", "role", "wikidata_id")},
        "statements": statements,
        "reported_as": quoted,
    }


# --- world, method ----------------------------------------------------------------------------


def world(db: Db) -> dict[str, Any]:
    """`stories`: reports per story per outlet country (Threads view). `places`: each story at
    the countries it is about, with where its reports come from (Globe). A gap is a party
    country to a story where we hold few reports; it describes our coverage, not the story."""
    items, gaps, places = [], [], []
    beat_places = {b["id"]: b["places"] for b in store.beats(db)}
    for s in store.nodes(db, "Story", "MATCH (n:Story {public: 1}) RETURN n ORDER BY n.id"):
        card = story_card(db, s)
        counts = Counter(
            r["perspective"] for r in graph.select(db, "reports", "n.story_id=?", (s["id"],))
        )
        anomalies = anomalies_for(db, "n.story_id=?", (s["id"],))
        for country, n in counts.items():
            if country != "unattributed":
                items.append(
                    {
                        "story_id": s["id"],
                        "title": s["title"],
                        "country": country,
                        "reports": n,
                        "perspectives": len(counts),
                        "anomalies": len([a for a in anomalies if a["status"] == "active"]),
                        "provisional": any(a["status"] == "provisional" for a in anomalies),
                        "last_report_at": card["last_report_at"],
                    }
                )
        party_codes = [p["party"].upper() for p in parties(db, s["id"])]
        # Globe: one marker per country the story is about, with where its reports come from
        for code in sorted(
            {*beat_places.get(s["beat_id"], []), *(c for c in party_codes if len(c) == 2)}
        ):
            places.append(
                {
                    "story_id": s["id"],
                    "title": s["title"],
                    "country": code,
                    "reports": sum(counts.values()),
                    "perspectives": len(counts),
                    "anomalies": len([a for a in anomalies if a["status"] == "active"]),
                    "provisional": any(a["status"] == "provisional" for a in anomalies),
                    "last_report_at": card["last_report_at"],
                    "from": dict(counts.most_common()),
                }
            )
        for code in party_codes:
            if len(code) == 2 and counts.get(code, 0) < GAP_BELOW:
                gaps.append(
                    {
                        "story_id": s["id"],
                        "title": s["title"],
                        "country": code,
                        "reports": counts.get(code, 0),
                    }
                )
    return {"stories": items, "places": places, "gaps": gaps}


GAP_BELOW = 3  # fewer reports than this from a party country is shown as a coverage gap

DESCRIPTIONS = {
    "names_sources": (
        "Names its sources",
        "Share of claims attributed to a named person, document or outlet",
        "raises",
    ),
    "links_documents": (
        "Links what it cites",
        "Share of references to official documents that link to them",
        "raises",
    ),
    "corrects_openly": (
        "Corrects in the open",
        "Corrections published with a visible note",
        "raises",
    ),
    "silent_edits": (
        "Silent edits",
        "Changes to published text with no note, found by comparing saved copies",
        "lowers",
    ),
    "copied_wording": (
        "Copied wording",
        "Text near-identical to another outlet, without credit",
        "lowers",
    ),
    "opinion_share": ("Opinion share", "Share of output that is op-ed or commentary", "lowers"),
}


def models() -> list[dict[str, str]]:
    """What runs where, read from the deployment: one hosted model (MODEL_NAME at MODEL_REVISION)
    does every hosted job; embeddings and NLI run on our own CPUs."""
    hosted = os.environ.get("MODEL_NAME") or "no hosted model configured"
    if os.environ.get("MODEL_REVISION"):
        hosted += f" (revision {os.environ['MODEL_REVISION']})"
    real = os.environ.get("WEFT_NLP") == "real"
    out = [
        {
            "job": "Claim extraction",
            "model": hosted,
            "how": "Picks sentences that state checkable claims; offsets come from our own splitter",
        },
        {"job": "Merge check", "model": hosted, "how": "Yes or no on borderline pairs of events"},
        {
            "job": "Ask Weft",
            "model": hosted,
            "how": "Paraphrases retrieved passages as attributed statements; cites them",
        },
        {
            "job": "Embeddings",
            "model": "BAAI/bge-m3" if real else "feature hashing (no model)",
            "how": "Groups similar reports and claims",
        },
        {
            "job": "Conflict check (NLI)",
            "model": "mDeBERTa-v3-base-xnli" if real else "word overlap (no model)",
            "how": "Finds claims that contradict each other",
        },
    ]
    if os.environ.get("DETECTIVE") == "on":
        out.append(
            {
                "job": "Detective mode",
                "model": hosted,
                "how": "Speculative guesses, labelled as such; checked later by a fixed rule",
            }
        )
    return out


def method(db: Db) -> dict[str, Any]:
    r = config.rules()
    return {
        "rules_version": r["version"],
        "provisional": r["provisional"],
        "rules": {k: v for k, v in r["rules"].items()},
        "weights": {
            "config": r["weights"],
            "factors": [
                {
                    "id": f,
                    "name": DESCRIPTIONS[f][0],
                    "how": DESCRIPTIONS[f][1],
                    "direction": DESCRIPTIONS[f][2],
                }
                for f in FACTORS
            ],
        },
        "models": models(),
        "rule_precision": feedback.precision(db),
        "model_calls_note": "Every model input and output is logged with the pinned model revision.",
        "corrections": [
            dict(c)
            for c in db.execute(
                "MATCH (n:Correction) RETURN n.day AS day, n.kind AS kind, n.what AS what "
                "ORDER BY n.day DESC, n.created_at DESC"
            )
        ],
        "gdelt_citation": "GDELT Project (gdeltproject.org), used for discovery and coverage gaps only.",
    }


# --- today ------------------------------------------------------------------------------------


NOVEL_COSINE = 0.75


def whats_new(db: Db, story_ids: list[str], since: str) -> list[dict[str, Any]]:
    """What changed in claim terms since `since` (#112): claim groups unlike any group before
    (max cosine under NOVEL_COSINE), groups that gained a perspective, and new conflicts.
    Coverage language only (rule 1)."""
    if not story_ids:
        return []
    events = {
        e["id"]: e["story_id"] for e in graph.select(db, "events", "n.story_id IN ?", (story_ids,))
    }
    if not events:
        return []
    ev_ids = list(events)
    now_groups = graph.select(db, "claim_groups", "n.event_id IN ?", (ev_ids,))
    before = {
        g["id"]: g for g in graph.select(db, "claim_groups", "n.event_id IN ?", (ev_ids,), since)
    }
    old_vecs: dict[str, list[list[float]]] = defaultdict(list)
    for g in before.values():
        if g.get("embedding"):
            old_vecs[events[g["event_id"]]].append(g["embedding"])
    out: list[dict[str, Any]] = []
    for g in now_groups:
        if (g["valid_from"] or "") < since:
            continue
        story = events[g["event_id"]]
        base = {"story_id": story, "event_id": g["event_id"], "text": g["label"], "group": g["id"]}
        prev = before.get(g["id"])
        if prev is not None:
            gained = sorted(set(g["perspectives"]) - set(prev["perspectives"]) - {"unattributed"})
            if gained:
                out.append(base | {"kind": "gained_perspective", "perspectives": gained})
            continue
        vec = g.get("embedding")
        if vec and max((cosine(vec, v) for v in old_vecs[story]), default=0.0) < NOVEL_COSINE:
            out.append(base | {"kind": "new_claim", "perspectives": g["perspectives"]})
    groups = {g["id"]: g for g in now_groups}
    for c in graph.select(db, "conflicts", "n.event_id IN ?", (ev_ids,)):
        if (c["valid_from"] or "") >= since and c["group_a"] in groups and c["group_b"] in groups:
            out.append(
                {
                    "kind": "new_conflict",
                    "story_id": events[c["event_id"]],
                    "event_id": c["event_id"],
                    "text": f"{groups[c['group_a']]['label']} — versus — {groups[c['group_b']]['label']}",
                    "group": c["group_a"],
                    "perspectives": [],
                }
            )
    order = {"new_conflict": 0, "new_claim": 1, "gained_perspective": 2}
    return sorted(out, key=lambda x: order[x["kind"]])


def burst_z(db: Db, story_id: str, now: datetime) -> float:
    """How unusual the last 6 hours are for a story: independent texts in the window against a
    14-day Poisson baseline, as a z-score (#112)."""
    rows = db.execute(
        "MATCH (r:Report {story_id: ?}) WHERE r.valid_to IS NULL "
        "AND coalesce(r.published_at, r.fetched_at) >= ? "
        "RETURN coalesce(r.origin_id, r.id) AS o, min(coalesce(r.published_at, r.fetched_at)) AS at",
        (story_id, (now - timedelta(days=14)).isoformat()),
    )
    cut = (now - timedelta(hours=6)).isoformat()
    recent = sum(1 for r in rows if r["at"] >= cut)
    lam = max((len(rows) - recent) / (14 * 4 - 1), 0.5)  # per 6 h; floor keeps quiet stories sane
    return (recent - lam) / math.sqrt(lam)


def today(
    db: Db,
    followed_beats: list[str] | None = None,
    since: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """What is new since `since` (default: the last 24 hours) in public stories: new events with
    their headline, outlets and new documents, new anomalies, the stories they belong to, and
    blind spots among events of the last 48 hours."""
    now = now or datetime.now(UTC)
    since = since or (now - timedelta(days=1)).isoformat()
    recent = (now - timedelta(hours=48)).isoformat()
    public = {
        s["id"]: s
        for s in store.nodes(db, "Story", "MATCH (n:Story {public: 1}) RETURN n ORDER BY n.id")
    }
    diff_rows = db.execute(
        "MATCH (n:DailyDiff) RETURN n.day AS day, n.payload AS payload ORDER BY n.day DESC LIMIT 1"
    )
    diff = json.loads(diff_rows[0]["payload"]) if diff_rows else {}
    changes = []
    for key, label in (
        ("new_events", "New events"),
        ("merged_events", "Events merged"),
        ("moved_reports", "Reports regrouped"),
    ):
        ids = diff.get(key, [])
        if ids:
            changes.append({"kind": key, "label": label, "count": len(ids)})
    new_anoms = [
        a
        for a in anomalies_for(db, "n.status='active'")
        if a["story_id"] in public and a["since"] >= since
    ]
    new_events, blind = [], []
    for sid, st in public.items():
        for e in graph.select(db, "events", "n.story_id=? AND n.first_seen >= ?", (sid, recent)):
            if e["first_seen"] >= since:
                docs = graph.select(
                    db, "documents", "n.event_id=? AND n.published_at >= ?", (e["id"], since)
                )
                new_events.append(
                    event_row(db, e)
                    | {"title": st["title"], "beat": st["beat_id"], "new_documents": len(docs)}
                )
            sv = graph.get(db, "short_versions", e["id"])
            split = _split_sv(db, sv["payload"]) if sv else None
            if split and (split["no_source_published"] or split["untracked"]):
                blind.append(
                    {
                        "story_id": sid,
                        "title": st["title"],
                        "event_id": e["id"],
                        "no_source_published": split["no_source_published"],
                        "untracked": split["untracked"],
                    }
                )
    new_events.sort(key=lambda e: e["first_seen"], reverse=True)
    news = whats_new(db, list(public), since)
    active = (
        {e["story_id"] for e in new_events}
        | {a["story_id"] for a in new_anoms}
        | {n["story_id"] for n in news}
    )
    cards = {sid: story_card(db, s) for sid, s in public.items()}
    docs_new = Counter(e["story_id"] for e in new_events for _ in range(e["new_documents"]))
    novelty = Counter(n["story_id"] for n in news)
    rank = {
        sid: burst_z(db, sid, now) + novelty[sid] + docs_new[sid] for sid in active
    }  # burst, plus what is new, plus new documents (#112)
    breaking = sorted(
        (cards[sid] | {"rank": round(rank[sid], 2)} for sid in active),
        key=lambda c: (-c["rank"], c["last_report_at"] or ""),
    )
    followed = [c for c in cards.values() if followed_beats and c["beat"] in followed_beats]
    dn, dr = len(diff.get("directions_new", [])), len(diff.get("directions_resolved", []))
    return {
        "directions": f"Directions: {dn} new, {dr} resolved"
        if detective.enabled() and dn + dr
        else None,
        "day": diff_rows[0]["day"] if diff_rows else None,
        "since": since,
        "changes": changes,
        "new_events": new_events,
        "whats_new": news[:30],
        "new_anomalies": new_anoms,  # provisional ones are excluded: they never notify
        "breaking": breaking[:10],
        "blind_spots": blind,
        "followed": followed,
    }


# --- reports of problems and corrections ------------------------------------------------------

PROBLEM_KINDS = ("grouping", "translation", "flag", "source", "other")


def add_problem(db: Db, kind: str, ref_id: str | None, message: str, email: str | None) -> int:
    if kind not in PROBLEM_KINDS:
        raise ValueError("unknown kind")
    message = message.strip()
    if not 3 <= len(message) <= 2000:
        raise ValueError("message must be 3 to 2000 characters")
    rows = db.execute(
        "MERGE (c:Counter {name: 'reader_reports'}) SET c.n = coalesce(c.n, 0) + 1 "
        "CREATE (n:ReaderReport {id: c.n, kind: ?, ref_id: ?, message: ?, email: ?, "
        "created_at: ?, status: 'open'}) RETURN n.id AS id",
        (kind, ref_id, message, email, datetime.now(UTC).isoformat()),
    )
    return int(rows[0]["id"])


def add_correction(db: Db, kind: str, what: str, day: str | None = None) -> None:
    store.create(
        db,
        "Correction",
        {
            "day": day or datetime.now(UTC).date().isoformat(),
            "kind": kind,
            "what": what,
            "created_at": datetime.now(UTC).isoformat(),
        },
    )


def changes(db: Db, story_id: str, since: str) -> list[dict[str, Any]]:
    """Graph changes of one story after `since` (ISO time), oldest first, for live mode (D10).
    shortcut: read straight from the graph tables; replace with Pub/Sub -> Redis when many
    readers hold streams open."""
    out: list[dict[str, Any]] = []
    reps = graph.select(db, "reports", "n.story_id=? AND n.valid_from > ?", (story_id, since))
    src = sources_by_id(db) if reps else {}
    for r in reps:
        out.append(
            {
                "type": "node.added",
                "at": r["valid_from"],
                "data": {
                    "id": r["id"],
                    "perspective": r["perspective"],
                    "title": r["title"],
                    "source": src.get(r["source_id"], {}).get("name", r["source_id"]),
                    "url": r["url"],
                },
            }
        )
    for a in graph.select(db, "anomalies", "n.story_id=? AND n.valid_from > ?", (story_id, since)):
        out.append(
            {
                "type": "anomaly.updated",
                "at": a["valid_from"],
                "data": {"id": a["id"], "status": a["status"], "summary": a["summary"]},
            }
        )
    return sorted(out, key=lambda m: m["at"])
