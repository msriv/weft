"""Autoclean rules that expire caches, stale queues and off-beat reports (#152). Importing this
module registers them.

Each rule names the nodes that are written forever and read only for a short window. What stays
forever is on purpose: labelled `BeatMaybe` (the eval set), rated `ReviewItem`, `SourceWeight`,
`SeriesPoint`, `AnomalyLog` and corrections, which pages and audits read. Nothing here looks at
source weight (product rule 6): off-beat reports are in no story and are shown nowhere.
"""

from datetime import timedelta

from weft_core.autoclean import Env, Match, Rule, batched, register
from weft_core.autoclean_graph import _count, _samples

Part = tuple[str, str]  # (label, condition on n; one `?` is the cutoff)


def _cutoff(env: Env) -> tuple[str]:
    return ((env.now - timedelta(days=env.conf["days"])).isoformat(),)


_KEY = "toString(coalesce(n.key, n.pair, n.domain, n.id, n.run_id, n.day, n.report_id, n.email))"


def _expiry_rule(
    name: str, parts: list[Part], *, destructive: bool = True, stamp: tuple[str, str] | None = None
) -> Rule:
    """Delete nodes past `days`. `stamp=(label, prop)` first dates old nodes that predate the
    timestamp (set to now), so they live one more full window instead of vanishing."""

    def match(env: Env) -> Match:
        c, total, samples = _cutoff(env), 0, []
        for label, cond in parts:
            total += _count(env, f"MATCH (n:{label}) WHERE ({cond}) RETURN count(n) AS n", c)
            samples += _samples(env, f"MATCH (n:{label}) WHERE ({cond}) RETURN {_KEY} AS id", c)
        of = sum(_count(env, f"MATCH (n:{label}) RETURN count(n) AS n") for label, _ in parts)
        return Match(total, of, samples)

    def apply(env: Env) -> int:
        if stamp:
            env.db.execute(
                f"MATCH (n:{stamp[0]}) WHERE n.{stamp[1]} IS NULL SET n.{stamp[1]} = ?",
                (env.now.isoformat(),),
            )
        return sum(
            batched(
                env.db,
                f"MATCH (n:{label}) WHERE ({cond}) WITH n LIMIT {{batch}} "
                "DETACH DELETE n RETURN count(*) AS n",
                _cutoff(env),
            )
            for label, cond in parts
        )

    return register(Rule(name, 1, match, apply, destructive=destructive))


# Caches: recomputed or re-asked if dropped, so they do not need a snapshot first.
_expiry_rule(
    "nli_cache",
    [("NliCache", "n.created_at < ?")],
    destructive=False,
    stamp=("NliCache", "created_at"),
)
_EVENT_GONE = (
    "NOT EXISTS {{ MATCH (e:Event {{id: split(n.pair, '|')[{i}]}}) WHERE e.valid_to IS NULL }}"
)
_expiry_rule(
    "merge_rejected",
    [
        (
            "MergeRejected",
            "n.created_at < ? OR " + _EVENT_GONE.format(i=0) + " OR " + _EVENT_GONE.format(i=1),
        )
    ],
    destructive=False,
    stamp=("MergeRejected", "created_at"),
)
_expiry_rule("portal_candidates", [("PortalCandidate", "n.last_seen < ?")], destructive=False)
_expiry_rule(
    "translations", [("Translation", "coalesce(n.last_used, n.created_at) < ?")], destructive=False
)
# A request whose probe never clears it stays forever otherwise (prune_candidates skips them).
_expiry_rule("requested_candidates", [("DomainCandidate", "n.requested = 1 AND n.first_seen < ?")])
# Queues. A label on a BeatMaybe or a rating on a ReviewItem is the owner's work: kept.
_expiry_rule(
    "beat_maybe",
    [("BeatMaybe", "n.label IS NULL AND n.created_at < ?")],
    stamp=("BeatMaybe", "created_at"),
)
_expiry_rule("review_items", [("ReviewItem", "n.rating IS NULL AND n.sampled_at < ?")])
_expiry_rule("batch_runs", [("BatchRun", "n.started_at < ?"), ("AutocleanRun", "n.started_at < ?")])
_expiry_rule("daily_diff", [("DailyDiff", "n.day < ?")])

# --- off-beat reports -------------------------------------------------------------------------

_OFFBEAT = (
    "MATCH (r:Report) WHERE r.story_id IS NULL AND coalesce(r.published_at, r.fetched_at) < ? "
    "WITH DISTINCT r.id AS id WHERE NOT EXISTS { MATCH (v:Report {id: id}) WHERE v.story_id IS NOT "
    "NULL OR coalesce(v.published_at, v.fetched_at) >= ? } AND NOT EXISTS { "
    "MATCH (m:BeatMaybe {report_id: id}) WHERE m.label IS NOT NULL } "
)
_CHILDREN = ("ReportEntity", "ReportVersion", "Copy", "Cites", "BeatMaybe", "Claim", "Figure")


def _offbeat_args(env: Env) -> tuple[str, str]:
    c = _cutoff(env)[0]
    return c, c


def _offbeat_match(env: Env) -> Match:
    a = _offbeat_args(env)
    n = _count(env, _OFFBEAT + "RETURN count(id) AS n", a)
    of = _count(env, "MATCH (r:Report) WHERE r.valid_to IS NULL RETURN count(r) AS n")
    return Match(n, of, _samples(env, _OFFBEAT + "RETURN id AS id", a))


def _offbeat_apply(env: Env) -> int:
    """Delete every version of the report and its child nodes. Its `raw_items` row stays in
    BigQuery, so the URL is still deduped."""
    total = 0
    while True:
        ids = [
            r["id"] for r in env.db.execute(_OFFBEAT + "RETURN id LIMIT 5000", _offbeat_args(env))
        ]
        if not ids:
            return total
        for label in _CHILDREN:
            env.db.execute(f"MATCH (c:{label}) WHERE c.report_id IN ? DETACH DELETE c", (ids,))
        env.db.execute("MATCH (c:Copy) WHERE c.copy_of IN ? DETACH DELETE c", (ids,))
        env.db.execute("MATCH (r:Report) WHERE r.id IN ? DETACH DELETE r", (ids,))
        total += len(ids)


register(Rule("offbeat_reports", 1, _offbeat_match, _offbeat_apply, destructive=True))

# --- reader data (spec: minimal data) ---------------------------------------------------------

_EMAIL = "n.status <> 'open' AND n.email IS NOT NULL AND n.created_at < ?"


def _email_match(env: Env) -> Match:
    c = _cutoff(env)
    rows = env.db.execute(f"MATCH (n:ReaderReport) WHERE {_EMAIL} RETURN n.id AS id", c)
    return Match(len(rows), None, [str(r["id"]) for r in rows])


def _email_apply(env: Env) -> int:
    # shortcut: ReaderReport has no resolved_at, so the clock runs from created_at; add the
    # field if reports often stay open longer than the window
    return _count(
        env,
        f"MATCH (n:ReaderReport) WHERE {_EMAIL} REMOVE n.email RETURN count(n) AS n",
        _cutoff(env),
    )


register(Rule("reader_report_email", 1, _email_match, _email_apply))
