"""Read model behind the public API: plain functions from the graph to JSON-ready dicts.

Only public stories are readable (the admin toggle, D15); anything under a non-public story
returns None and the API answers 404. Source weight changes ordering only (rule 6): every report
is returned, sorted, never filtered. Labels use coverage language only (rule 1). Documents carry
their issuer and whether the issuer is a party to this story (rule 7).
"""

import json
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from weft_core import config, graph
from weft_core.perspectives import perspective_of
from weft_core.rules import log_odds
from weft_core.store import Db
from weft_core.textutil import words
from weft_core.weights import FACTORS

QUIET_AFTER = timedelta(hours=48)


# --- shared helpers ---------------------------------------------------------------------------


def public_story(db: Db, story_id: str) -> dict[str, Any] | None:
    rows = db.execute("SELECT * FROM stories WHERE id=? AND public=1", (story_id,))
    return rows[0] if rows else None


def parties(db: Db, story_id: str) -> list[dict[str, Any]]:
    return [
        {"party": r["party"], "cited": bool(r["citation"]), "citation": r["citation"]}
        for r in db.execute(
            "SELECT party, citation FROM story_parties WHERE story_id=?", (story_id,)
        )
    ]


def sources_by_id(db: Db) -> dict[str, dict[str, Any]]:
    return {s["id"]: s for s in db.execute("SELECT * FROM sources")}


def weights_latest(db: Db) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for r in db.execute("SELECT * FROM source_weights ORDER BY day"):
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
        for a in graph.select(db, "anomalies", f"status!='withdrawn' AND ({where})", args, at)
    ]


# --- stories ----------------------------------------------------------------------------------


def story_card(db: Db, s: dict[str, Any], at: str | None = None) -> dict[str, Any]:
    reps = graph.select(db, "reports", "story_id=?", (s["id"],), at)
    anomalies = anomalies_for(db, "story_id=?", (s["id"],), at)
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
    cards = [story_card(db, s) for s in db.execute("SELECT * FROM stories WHERE public=1")]
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


def story_graph(db: Db, story_id: str, at: str | None = None) -> dict[str, Any] | None:
    """Nodes and edges for the story view, as of `at` (Replay). Layout is computed by the client:
    x = day, one band per perspective, official documents on the spine."""
    s = public_story(db, story_id)
    if s is None:
        return None
    src = sources_by_id(db)
    plist = parties(db, story_id)
    reps = graph.select(db, "reports", "story_id=?", (story_id,), at)
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in reps:
        if r["event_id"]:
            groups[(r["event_id"], r["perspective"])].append(r)
    anomalies = anomalies_for(db, "story_id=?", (story_id,), at)
    flagged = defaultdict(list)
    for a in anomalies:
        for rid in a["evidence_ids"]:
            flagged[rid].append(a["id"])
    nodes: list[dict[str, Any]] = []
    for (eid, persp), rs in sorted(groups.items()):
        days = sorted((r["published_at"] or r["fetched_at"] or "") for r in rs)
        nodes.append(
            {
                "id": f"{eid}:{persp}",
                "kind": "report_group",
                "event_id": eid,
                "perspective": persp,
                "count": len(rs),
                "at": days[0],
                "sources": sorted(
                    {src[r["source_id"]]["name"] for r in rs if r["source_id"] in src}
                ),
                "anomalies": sorted({a for r in rs for a in flagged.get(r["id"], [])}),
                "report_ids": [r["id"] for r in rs],
            }
        )
    for d in graph.select(db, "documents", "story_id=?", (story_id,), at):
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
            "event_id IN (SELECT id FROM events WHERE story_id=?)",
            (story_id,),
            at,
        )
    }
    edges = []
    for c in graph.select(db, "conflicts", "1=1", (), at):
        if c["group_a"] in gid_persp and c["group_b"] in gid_persp:
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
        "perspectives": sorted({n["perspective"] for n in nodes if "perspective" in n}),
        "nodes": nodes,
        "edges": edges,
        "anomalies": anomalies,
        "events": [
            event_row(db, e, at) for e in graph.select(db, "events", "story_id=?", (story_id,), at)
        ],
        "short_version": _event_short_versions(db, story_id, at),
        "weights_note": "Source weight changes ordering only. No report is hidden.",
    }


def _event_short_versions(db: Db, story_id: str, at: str | None) -> dict[str, Any]:
    """Story-level short version: the event-level set logic with claim-group labels resolved,
    so the page can say what is reported by all, what conflicts, and what no source has published."""
    label = {
        g["id"]: g["label"]
        for g in graph.select(
            db,
            "claim_groups",
            "event_id IN (SELECT id FROM events WHERE story_id=?)",
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
    for e in graph.select(db, "events", "story_id=?", (story_id,), at):
        sv = graph.get(db, "short_versions", e["id"], at)
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
    first = reps[0] if reps else None
    return {
        "id": e["id"],
        "story_id": e["story_id"],
        "label": first["title"] if first else None,
        "first_seen": e["first_seen"],
        "reports": len(reps),
        "perspectives": sorted({r["perspective"] for r in reps}),
        "grouping_confidence": e["grouping_confidence"],
    }


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
                    for c in db.execute("SELECT copy_of FROM copies WHERE report_id=?", (r["id"],))
                ],
            }
        )
    for rs in by_p.values():  # ordering only: heavier sources first, nothing dropped
        rs.sort(key=lambda r: (-(r["source"]["weight"] or 0), r["published_at"] or ""))
    groups = graph.select(db, "claim_groups", "event_id=?", (event_id,), at)
    claims = graph.select(db, "claims", "event_id=?", (event_id,), at)
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
        for f in graph.select(db, "figures", "event_id=?", (event_id,), at)
    ]
    docs = []
    for d in graph.select(db, "documents", "event_id=?", (event_id,), at):
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
            for c in graph.select(db, "conflicts", "event_id=?", (event_id,), at)
        ],
        "figures": figs,
        "documents": docs,
        "anomalies": anomalies_for(db, "event_id=?", (event_id,), at),
        "short_version": sv["payload"] if sv else None,
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
        out[p] = {"headline": rs[0]["title"] if rs else None, "words": top, "reports": len(rs)}
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
            links = [{"label": "Evidence", "id": i} for i in row["evidence_ids"]]
        return {"kind": kind, "node": row, "links": links}
    return None


# --- sources ----------------------------------------------------------------------------------


def list_sources(db: Db) -> list[dict[str, Any]]:
    w = weights_latest(db)
    out = [
        source_label(s, w.get(s["id"]))
        for s in db.execute("SELECT * FROM sources WHERE status='active'")
    ]
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
        "source_id=? AND story_id IN (SELECT id FROM stories WHERE public=1)",
        (source_id,),
    )
    ids = {r["id"] for r in reps}
    anomalies = [
        a
        for a in anomalies_for(db, "1=1")
        if a["subject_id"] == source_id or ids & set(a["evidence_ids"])
    ]
    history = [
        {"day": r["day"], "weight": r["weight"]}
        for r in db.execute(
            "SELECT day, weight FROM source_weights WHERE source_id=? ORDER BY day", (source_id,)
        )
    ]
    siblings = (
        [
            x["name"]
            for x in db.execute(
                "SELECT name FROM sources WHERE owner_id=? AND id!=?", (s["owner_id"], source_id)
            )
        ]
        if s["owner_id"]
        else []
    )
    cur = w.get(source_id)
    claims = (
        graph.select(db, "claims", f"report_id IN ({','.join('?' * len(ids))})", tuple(ids))
        if ids
        else []
    )
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
            "SELECT st.*, a.name, a.role FROM statements st JOIN actors a ON a.id=st.actor_id "
            "WHERE st.document_id=? ORDER BY st.start_char",
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
    rows = db.execute("SELECT * FROM actors WHERE id=?", (actor_id,))
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
            "SELECT st.id, st.document_id, st.text, d.title, d.published_at, d.story_id "
            "FROM statements st JOIN documents d ON d.id=st.document_id AND d.valid_to IS NULL "
            "WHERE st.actor_id=? AND d.story_id IN (SELECT id FROM stories WHERE public=1) "
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
            "kind='quote' AND speaker IS NOT NULL AND LOWER(speaker)=LOWER(?) AND event_id IN "
            "(SELECT e.id FROM events e WHERE e.valid_to IS NULL AND e.story_id IN "
            "(SELECT id FROM stories WHERE public=1))",
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
    """Coverage by country for the Threads and Globe views. A gap is a party country to a story
    where we hold few reports; it describes our coverage, not the story."""
    items, gaps = [], []
    for s in db.execute("SELECT * FROM stories WHERE public=1"):
        card = story_card(db, s)
        counts = Counter(
            r["perspective"] for r in graph.select(db, "reports", "story_id=?", (s["id"],))
        )
        anomalies = anomalies_for(db, "story_id=?", (s["id"],))
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
        for p in parties(db, s["id"]):
            code = p["party"].upper()
            if len(code) == 2 and counts.get(code, 0) < GAP_BELOW:
                gaps.append(
                    {
                        "story_id": s["id"],
                        "title": s["title"],
                        "country": code,
                        "reports": counts.get(code, 0),
                    }
                )
    return {"stories": items, "gaps": gaps}


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

MODELS = [
    {
        "job": "Claim extraction",
        "model": "Qwen/Qwen3-14B",
        "how": "Picks sentences that state checkable claims; offsets come from our own splitter",
    },
    {
        "job": "Merge check",
        "model": "Qwen/Qwen3-8B",
        "how": "Yes or no on borderline pairs of events",
    },
    {
        "job": "Translation",
        "model": "google/madlad400-3b-mt",
        "how": "Shown with a label and a Show original toggle",
    },
    {"job": "Embeddings", "model": "BAAI/bge-m3", "how": "Groups similar reports and claims"},
    {
        "job": "Conflict check (NLI)",
        "model": "mDeBERTa-v3-base-xnli",
        "how": "Finds claims that contradict each other",
    },
    {
        "job": "Ask Weft",
        "model": "openai/gpt-oss-20b",
        "how": "Answers questions from the graph with read-only tools; cites nodes",
    },
]


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
        "models": MODELS,
        "model_calls_note": "Every model input and output is logged with the pinned model revision.",
        "corrections": [
            dict(c)
            for c in db.execute(
                "SELECT day, kind, what FROM corrections ORDER BY day DESC, rowid DESC"
            )
        ],
        "gdelt_citation": "GDELT Project (gdeltproject.org), used for discovery and coverage gaps only.",
    }


# --- today ------------------------------------------------------------------------------------


def today(db: Db, followed_beats: list[str] | None = None) -> dict[str, Any]:
    """Overnight changes (latest daily diff, public stories only), breaking now, blind spots."""
    public = {s["id"]: s for s in db.execute("SELECT * FROM stories WHERE public=1")}
    cards = {sid: story_card(db, s) for sid, s in public.items()}
    diff_rows = db.execute("SELECT day, payload FROM daily_diffs ORDER BY day DESC LIMIT 1")
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
        for a in anomalies_for(db, "status='active'")
        if a["story_id"] in public
        and a["since"] >= (datetime.now(UTC) - timedelta(days=1)).isoformat()
    ]
    breaking = [
        c
        for c in cards.values()
        if c["status"] == "developing" and c["provisional_anomalies"] + c["anomalies"] >= 0
    ]
    breaking.sort(key=lambda c: c["last_report_at"] or "", reverse=True)
    blind = []
    for sid in public:
        for e in graph.select(db, "events", "story_id=?", (sid,)):
            sv = graph.get(db, "short_versions", e["id"])
            if sv and sv["payload"].get("no_source_published"):
                blind.append(
                    {
                        "story_id": sid,
                        "title": public[sid]["title"],
                        "event_id": e["id"],
                        "no_source_published": sv["payload"]["no_source_published"],
                    }
                )
    followed = [c for c in cards.values() if followed_beats and c["beat"] in followed_beats]
    return {
        "day": diff_rows[0]["day"] if diff_rows else None,
        "changes": changes,
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
    db.execute(
        "INSERT INTO reader_reports(kind,ref_id,message,email,created_at) VALUES(?,?,?,?,?)",
        (kind, ref_id, message, email, datetime.now(UTC).isoformat()),
    )
    return int(db.execute("SELECT MAX(rowid) AS n FROM reader_reports")[0]["n"])


def add_correction(db: Db, kind: str, what: str, day: str | None = None) -> None:
    db.execute(
        "INSERT INTO corrections(day,kind,what) VALUES(?,?,?)",
        (day or datetime.now(UTC).date().isoformat(), kind, what),
    )
