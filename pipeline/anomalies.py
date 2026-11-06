"""Nightly stage 8: run the rules engine over the graph and reconcile with what is stored.

An anomaly that appears is inserted, one whose inputs changed gets a new version, and one that no
longer fires is marked withdrawn. Every change is appended to `anomalies_log` with the rule
version, so changing a threshold shows exactly what appeared and disappeared.
"""

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from pipeline.ctx import Ctx
from weft_core import config, graph, rules
from weft_core.rules import Anomaly, EventInput, Figure, Group, Rep


def _dt(v: str | None) -> datetime:
    return datetime.fromisoformat(v) if v else datetime.min


def load_event(
    ctx: Ctx, ev: dict[str, Any], sources: dict[str, dict[str, Any]], texts: dict[str, str]
) -> EventInput:
    reps = graph.reports_of_event(ctx.db, ev["id"])
    rr = [
        Rep(
            id=r["id"],
            source_id=r["source_id"],
            source_name=sources[r["source_id"]]["name"],
            perspective=r["perspective"],
            published_at=_dt(r["published_at"] or r["fetched_at"]),
            owner_id=sources[r["source_id"]]["owner_id"],
            paywalled=bool(sources[r["source_id"]]["paywalled"]),
            healthy=bool(sources[r["source_id"]]["healthy"]),
            type=r["type"],
            text=texts.setdefault(r["id"], ctx.text_of(r)),
        )
        for r in reps
        if r["source_id"] in sources
    ]
    claims = graph.select(ctx.db, "claims", "event_id=?", (ev["id"],))
    by_group: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in claims:
        if c["group_id"]:
            by_group[c["group_id"]].append({"report_id": c["report_id"], "text": c["text"]})
    groups = [
        Group(g["id"], g["label"], {c["report_id"] for c in by_group[g["id"]]}, by_group[g["id"]])
        for g in graph.select(ctx.db, "claim_groups", "event_id=?", (ev["id"],))
    ]
    figs = [
        Figure(f["id"], f["report_id"], f["quantity"], f["value"], f["text"])
        for f in graph.select(ctx.db, "figures", "event_id=? AND kind='number'", (ev["id"],))
    ]
    return EventInput(ev["id"], ev["story_id"], _dt(ev["first_seen"]), rr, groups, figs)


def reconcile(ctx: Ctx, found: list[Anomaly]) -> int:
    ver = ctx.rules["version"]
    current = {a["id"]: a for a in graph.select(ctx.db, "anomalies")}
    changes = 0

    def log(a_id: str, change: str, rule: str, version: int, status: str) -> None:
        ctx.db.execute(
            "INSERT INTO anomalies_log(at,anomaly_id,change,rule,rule_version,status) "
            "VALUES(?,?,?,?,?,?)",
            (ctx.now, a_id, change, rule, version, status),
        )

    seen = set()
    for a in found:
        seen.add(a.id)
        row = {
            "id": a.id,
            "rule": a.rule,
            "rule_version": a.rule_version,
            "status": a.status,
            "subject_kind": a.subject_kind,
            "subject_id": a.subject_id,
            "story_id": a.story_id or None,
            "event_id": a.event_id,
            "summary": a.summary,
            "inputs": a.inputs,
            "evidence_ids": a.evidence_ids,
            "detail": a.detail,
        }
        old = current.get(a.id)
        if old is None or old["status"] == "withdrawn":
            graph.put(ctx.db, "anomalies", row, ctx.now)
            log(a.id, "appeared", a.rule, a.rule_version, a.status)
            changes += 1
        elif (old["status"], old["evidence_ids"], old["rule_version"]) != (
            a.status,
            a.evidence_ids,
            a.rule_version,
        ):
            graph.put(ctx.db, "anomalies", row, ctx.now)
            log(a.id, "changed", a.rule, a.rule_version, a.status)
            changes += 1
    for a_id, old in current.items():
        if a_id not in seen and old["status"] != "withdrawn":
            graph.put(
                ctx.db,
                "anomalies",
                {k: old[k] for k in old if k not in ("valid_from", "valid_to")}
                | {"status": "withdrawn", "rule_version": ver},
                ctx.now,
            )
            log(a_id, "withdrawn", old["rule"], ver, "withdrawn")
            changes += 1
    return changes


def run(ctx: Ctx) -> int:
    cfg = ctx.rules
    now = _dt(ctx.now)
    sources = {s["id"]: s for s in ctx.db.execute("SELECT * FROM sources")}
    texts: dict[str, str] = {}
    found: list[Anomaly] = []
    cutoff = (now - timedelta(days=ctx.cfg["nightly"]["regroup_days"])).isoformat()
    stories: dict[str, list[Rep]] = defaultdict(list)
    for ev in graph.select(ctx.db, "events", "first_seen >= ?", (cutoff,)):
        e = load_event(ctx, ev, sources, texts)
        found += rules.evaluate_event(e, cfg, now)
        stories[ev["story_id"]] += e.reports
    if cfg["rules"]["silence"]["enabled"]:
        for story_id, reps in stories.items():
            found += rules.silence(story_id, reps, now, cfg)
    if cfg["rules"]["silent_edit"]["enabled"]:
        edits = []
        for reps in stories.values():
            for r in reps:
                versions = ctx.versions_of(r.id)
                if len(versions) > 1:
                    edits.append(rules.Edit(r, versions))
        report_story = {r.id: s for s, rs in stories.items() for r in rs}
        for a in rules.silent_edit(edits, cfg):
            a.story_id = report_story.get(a.subject_id, "")
            found.append(a)
    return reconcile(ctx, found)


def rules_cfg() -> dict[str, Any]:
    return config.rules()
