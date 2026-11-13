"""Nightly stage 8: run the rules engine over the graph and reconcile with what is stored.

An anomaly that appears is inserted, one whose inputs changed gets a new version, and one that no
longer fires is marked withdrawn. Every change is appended to `anomalies_log` with the rule
version, so changing a threshold shows exactly what appeared and disappeared.
"""

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from pipeline.ctx import Ctx
from weft_core import config, feedback, graph, rules, store
from weft_core.rules import Anomaly, EventInput, Figure, Group, Rep


def _dt(v: str | None) -> datetime:
    return datetime.fromisoformat(v) if v else datetime.min


def load_event(
    ctx: Ctx, ev: dict[str, Any], sources: dict[str, dict[str, Any]], texts: dict[str, str]
) -> EventInput:
    reps = graph.reports_of_event(ctx.db, ev["id"])
    claims = graph.select(ctx.db, "claims", "n.event_id=?", (ev["id"],))
    claimed = {c["report_id"] for c in claims}
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
            origin_id=r.get("origin_id") or "",
            # reports from before the flag count as read when they have claims
            claims_extracted=bool(r.get("claims_extracted")) or r["id"] in claimed,
            correction_note=r.get("correction_note") or "",
        )
        for r in reps
        if r["source_id"] in sources
    ]
    by_group: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in claims:
        if c["group_id"]:
            by_group[c["group_id"]].append(
                {
                    "report_id": c["report_id"],
                    "text": c["text"],
                    **{k: c.get(k) for k in ("speaker", "speaker_kind", "stance") if c.get(k)},
                }
            )
    groups = [
        Group(g["id"], g["label"], {c["report_id"] for c in by_group[g["id"]]}, by_group[g["id"]])
        for g in graph.select(ctx.db, "claim_groups", "n.event_id=?", (ev["id"],))
    ]

    def group_of(f: dict[str, Any]) -> str | None:
        """The claim group of the claim sentence that contains the figure."""
        for c in claims:
            if (
                c["report_id"] == f["report_id"]
                and c["group_id"]
                and (c["start_char"] or 0) <= (f["start_char"] or 0) < (c["end_char"] or 0)
            ):
                return str(c["group_id"])
        return None

    figs = [
        Figure(
            f["id"],
            f["report_id"],
            f["quantity"],
            f["value"],
            f["text"],
            group_of(f),
            f.get("hedge"),
        )
        for f in graph.select(ctx.db, "figures", "n.event_id=? AND n.kind='number'", (ev["id"],))
    ]
    conflicts = [
        (c["group_a"], c["group_b"], c["nli_score"])
        for c in graph.select(ctx.db, "conflicts", "n.event_id=?", (ev["id"],))
    ]
    return EventInput(
        ev["id"],
        ev["story_id"],
        _dt(ev["first_seen"]),
        rr,
        groups,
        figs,
        conflicts,
        party_names(ctx, ev["story_id"]),
        load_quotes(ctx, ev["id"], sources),
    )


def load_quotes(
    ctx: Ctx, event_id: str, sources: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    rows = ctx.db.execute(
        "MATCH (f:Figure {event_id: ?, kind: 'quote'}) WHERE f.valid_to IS NULL "
        "MATCH (q:Quotes {figure_id: f.id}) MATCH (s:Statement {id: q.statement_id}) "
        "MATCH (d:Document {id: s.document_id}) WHERE d.valid_to IS NULL "
        "OPTIONAL MATCH (a:Actor {id: s.actor_id}) "
        "RETURN f.id AS figure_id, f.report_id AS report_id, f.text AS text, f.speaker AS speaker, "
        "s.id AS statement_id, s.text AS statement, a.name AS actor, d.issuer_id AS issuer_id, "
        "q.edit_ratio AS edit_ratio",
        (event_id,),
    )
    return [
        {**r, "issuer": (sources.get(r["issuer_id"]) or {}).get("name") or r["issuer_id"]}
        for r in rows
    ]


def party_names(ctx: Ctx, story_id: str) -> list[str]:
    """Names a speaker may carry when it is a party to the story (rule 7): the beat's group
    labels on grouped beats, else each party country's English name and code."""
    groups = set(store.beat_groups(ctx.db, story_id).values())
    if groups:
        return sorted(groups)
    codes = [
        r["p"]
        for r in ctx.db.execute(
            "MATCH (n:StoryParty {story_id: ?}) RETURN n.party AS p", (story_id,)
        )
    ]
    names: dict[str, str] = {}
    try:  # babel comes with trafilatura; without it only the codes match
        from babel import Locale

        names = dict(Locale("en").territories)
    except ImportError:
        pass
    return sorted({n for c in codes for n in (names.get(c.upper()), c) if n and len(n) > 2})


def reconcile(
    ctx: Ctx,
    found: list[Anomaly],
    events: set[str] | None = None,
    stories: set[str] | None = None,
) -> int:
    """`events` and `stories` are what this run evaluated. An anomaly outside them (its event
    aged out of the window) keeps its last state: not firing on unevaluated input is not a
    withdrawal. None means everything was evaluated."""
    ver = ctx.rules["version"]
    current = {a["id"]: a for a in graph.select(ctx.db, "anomalies")}
    changes = 0

    def log(a_id: str, change: str, rule: str, version: int, status: str) -> None:
        ctx.db.execute(  # seq keeps log order within one run (same `at`)
            "MERGE (c:Counter {name: 'anomalies_log'}) SET c.n = coalesce(c.n, 0) + 1 "
            "CREATE (:AnomalyLog {seq: c.n, at: ?, anomaly_id: ?, change: ?, rule: ?, "
            "rule_version: ?, status: ?})",
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

    live = {e["id"] for e in graph.select(ctx.db, "events")} if events is not None else set()

    def in_scope(a: dict[str, Any]) -> bool:
        if events is None:
            return True
        if a["event_id"]:  # merged-away (closed) events are in scope, so theirs are withdrawn
            return a["event_id"] in events or a["event_id"] not in live
        return (a["story_id"] or "") in (stories or set())

    for a_id, old in current.items():
        if a_id not in seen and old["status"] != "withdrawn" and in_scope(old):
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
    sources = {s["id"]: s for s in store.all_sources(ctx.db)}
    texts: dict[str, str] = {}
    found: list[Anomaly] = []
    cutoff = (now - timedelta(days=ctx.cfg["nightly"]["regroup_days"])).isoformat()
    stories: dict[str, list[Rep]] = defaultdict(list)
    evaluated: set[str] = set()
    for ev in graph.select(ctx.db, "events", "n.first_seen >= ?", (cutoff,)):
        evaluated.add(ev["id"])
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
    # a rule notifies only once owner labels show it is useful (#114); until then provisional
    ok = feedback.promoted(ctx.db, cfg)
    for a in found:
        if a.status == "active" and a.rule not in ok:
            a.status = "provisional"
    return reconcile(ctx, found, evaluated, set(stories))


def rules_cfg() -> dict[str, Any]:
    return config.rules()
