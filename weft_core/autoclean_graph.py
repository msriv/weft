"""Autoclean rules for graph integrity (#149). Importing this module registers them.

Nodes join on id properties, not relationships, so Neo4j enforces nothing: a crash between two
statements, or two concurrent pushes, can leave a duplicate current version, a count that is off,
or a child whose parent is gone. Repair before delete. A child is deleted only when its parent
exists in no version at all: a child of a closed parent version stays, because Replay still
shows it. Anomalies, their log and feedback are never touched here (they are the audit trail).
"""

import json
from datetime import timedelta
from typing import Any

from weft_core import store
from weft_core.autoclean import Env, Match, Rule, batched, register

VERSIONED = sorted(label for label, props in store.NODES.items() if "valid_from" in props)
_ID = (
    "labels(c)[0] + ':' + toString(coalesce(c.id, c.report_id, c.pair, c.figure_id, c.source_id,"
    " c.story_id, c.domain_id, c.beat_id, c.group_a, c.document_id))"
)


def _count(env: Env, query: str, args: tuple[Any, ...] = ()) -> int:
    return int(env.db.execute(query, args)[0]["n"])


def _samples(env: Env, query: str, args: tuple[Any, ...] = ()) -> list[str]:
    return [str(r["id"]) for r in env.db.execute(f"{query} LIMIT 20", args)]


# --- repairs ----------------------------------------------------------------------------------

_DUP = (
    "MATCH (n:{label}) WHERE n.valid_to IS NULL WITH n.id AS id, collect(n) AS ns "
    "WHERE size(ns) > 1 {tail}"
)


def _dup_match(env: Env) -> Match:
    total, samples = 0, []
    for label in VERSIONED:
        q = _DUP.format(label=label, tail="RETURN id, size(ns) - 1 AS extra")
        rows = env.db.execute(q)
        total += sum(r["extra"] for r in rows)
        samples += [f"{label}:{r['id']}" for r in rows]
    return Match(total, None, samples)


def _dup_apply(env: Env) -> int:
    fixed = 0
    for label in VERSIONED:
        # keep the newest valid_from open; close the others at that moment
        q = (
            f"MATCH (n:{label}) WHERE n.valid_to IS NULL "
            "WITH n.id AS id, n ORDER BY n.valid_from DESC WITH id, collect(n) AS ns "
            "WHERE size(ns) > 1 UNWIND ns[1..] AS old SET old.valid_to = ns[0].valid_from "
            "RETURN count(old) AS n"
        )
        fixed += _count(env, q)
    return fixed


register(Rule("duplicate_current", 1, _dup_match, _dup_apply))

_COUNTS = (
    "MATCH (e:Event) WHERE e.valid_to IS NULL OPTIONAL MATCH (r:Report) "
    "WHERE r.event_id = e.id AND r.valid_to IS NULL "
    "WITH e, count(r) AS k WHERE coalesce(e.n_reports, -1) <> k "
)


def _counts_match(env: Env) -> Match:
    q = _COUNTS + "RETURN e.id AS id"
    rows = env.db.execute(q)
    of = _count(env, "MATCH (e:Event) WHERE e.valid_to IS NULL RETURN count(e) AS n")
    return Match(len(rows), of, [r["id"] for r in rows])


def _counts_apply(env: Env) -> int:
    return _count(env, _COUNTS + "SET e.n_reports = k RETURN count(e) AS n")


register(Rule("event_counts", 1, _counts_match, _counts_apply))

_EMPTY = (
    "MATCH (e:Event) WHERE e.valid_to IS NULL AND e.valid_from < ? AND NOT EXISTS { "
    "MATCH (r) WHERE (r:Report OR r:Document) AND r.event_id = e.id AND r.valid_to IS NULL } "
)


def _empty_args(env: Env) -> tuple[str]:
    return ((env.now - timedelta(hours=env.conf["min_age_hours"])).isoformat(),)


def _empty_match(env: Env) -> Match:
    rows = env.db.execute(_EMPTY + "RETURN e.id AS id", _empty_args(env))
    of = _count(env, "MATCH (e:Event) WHERE e.valid_to IS NULL RETURN count(e) AS n")
    return Match(len(rows), of, [r["id"] for r in rows])


def _empty_apply(env: Env) -> int:
    # closed, not deleted: it was a real version once
    q = _EMPTY + "SET e.valid_to = ? RETURN count(e) AS n"
    return _count(env, q, (*_empty_args(env), env.now.isoformat()))


register(Rule("empty_event", 1, _empty_match, _empty_apply))

_NO_EVENT = (
    "c.valid_to IS NULL AND c.event_id IS NOT NULL AND NOT EXISTS { "
    "MATCH (e:Event {id: c.event_id}) WHERE e.valid_to IS NULL }"
)


def _dangling_match(env: Env) -> Match:
    total, samples = 0, []
    for label in ("Report", "Document", "Claim", "Figure"):
        q = f"MATCH (c:{label}) WHERE {_NO_EVENT} RETURN c.id AS id"
        rows = env.db.execute(q)
        total += len(rows)
        samples += [f"{label}:{r['id']}" for r in rows]
    return Match(total, None, samples)


def _dangling_apply(env: Env) -> int:
    fixed = 0
    for label in ("Report", "Document"):  # unplaced again: regroup places them
        fixed += _count(
            env, f"MATCH (c:{label}) WHERE {_NO_EVENT} REMOVE c.event_id RETURN count(c) AS n"
        )
    for label in ("Claim", "Figure"):  # follow the report they were read from
        fixed += _count(
            env,
            f"MATCH (c:{label}) WHERE {_NO_EVENT} "
            "OPTIONAL MATCH (r:Report {id: c.report_id}) WHERE r.valid_to IS NULL "
            "WITH c, r SET c.event_id = r.event_id RETURN count(c) AS n",
        )
    return fixed


register(Rule("dangling_event_ref", 1, _dangling_match, _dangling_apply))

_NO_V0 = (
    "MATCH (r:Report) WHERE r.valid_to IS NULL AND r.text_hash IS NOT NULL AND NOT EXISTS { "
    "MATCH (v:ReportVersion {report_id: r.id, n: 0}) } "
)


def _v0_match(env: Env) -> Match:
    rows = env.db.execute(_NO_V0 + "RETURN r.id AS id")
    return Match(len(rows), None, [r["id"] for r in rows])


def _v0_apply(env: Env) -> int:
    return _count(
        env,
        _NO_V0 + "CREATE (:ReportVersion {report_id: r.id, n: 0, fetched_at: r.fetched_at, "
        "text_hash: r.text_hash}) RETURN count(r) AS n",
    )


register(Rule("missing_version0", 1, _v0_match, _v0_apply))


def _stale_sources(env: Env) -> list[str]:
    """Sources with a current report whose stored perspective differs from the derived one."""
    out = []
    pairs = env.db.execute(
        "MATCH (r:Report) WHERE r.valid_to IS NULL "
        "RETURN DISTINCT r.source_id AS source_id, r.story_id AS story_id, r.perspective AS p"
    )
    srcs = {s["id"]: s for s in store.all_sources(env.db)}
    for row in pairs:
        src = srcs.get(row["source_id"])
        if src and store.report_perspective(env.db, src, row["story_id"]) != row["p"]:
            out.append(row["source_id"])
    return sorted(set(out))


def _stale_match(env: Env) -> Match:
    found = _stale_sources(env)
    return Match(len(found), None, found)


def _stale_apply(env: Env) -> int:
    found = _stale_sources(env)
    for sid in found:
        store.retag(env.db, sid)
    return len(found)


register(Rule("stale_perspective", 1, _stale_match, _stale_apply))


def _bad_follows(env: Env) -> list[tuple[str, list[str], list[str]]]:
    """(email, follows, follows that match a story) for subscriptions with a dead id."""
    live = {r["id"] for r in env.db.execute("MATCH (s:Story) RETURN s.id AS id")}
    out = []
    for r in env.db.execute("MATCH (n:Subscription) RETURN n.email AS email, n.follows AS f"):
        follows = json.loads(r["f"] or "[]")
        kept = [f for f in follows if f in live]
        if kept != follows:
            out.append((r["email"], follows, kept))
    return out


def _follows_match(env: Env) -> Match:
    bad = _bad_follows(env)
    return Match(sum(len(f) - len(k) for _, f, k in bad), None, [e for e, _, _ in bad])


def _follows_apply(env: Env) -> int:
    bad = _bad_follows(env)
    for email, follows, kept in bad:
        env.db.execute(
            "MATCH (n:Subscription {email: ?}) SET n.follows = ?", (email, json.dumps(kept))
        )
    return sum(len(f) - len(k) for _, f, k in bad)


register(Rule("subscription_follows", 1, _follows_match, _follows_apply))

_NO_GROUP = (
    "MATCH (c:Claim) WHERE c.valid_to IS NULL AND c.group_id IS NOT NULL AND NOT EXISTS { "
    "MATCH (g:ClaimGroup {id: c.group_id}) } "
)


def _group_ref_match(env: Env) -> Match:
    rows = env.db.execute(_NO_GROUP + "RETURN c.id AS id")
    return Match(len(rows), None, [r["id"] for r in rows])


def _group_ref_apply(env: Env) -> int:  # keep the claim, clear the field
    return _count(env, _NO_GROUP + "REMOVE c.group_id RETURN count(c) AS n")


register(Rule("dangling_group_ref", 1, _group_ref_match, _group_ref_apply))

# --- orphans: delete a child whose parent exists in no version ---------------------------------


def _gone(key: str, parent: str, pkey: str = "id") -> str:
    return f"(c.{key} IS NOT NULL AND NOT EXISTS {{ MATCH (p:{parent} {{{pkey}: c.{key}}}) }})"


def _either(*conds: str) -> str:
    return "(" + " OR ".join(conds) + ")"


Part = tuple[str, str]  # (child label, condition on c that says it is an orphan)


def _orphan_rule(name: str, parts: list[Part]) -> Rule:
    def match(env: Env) -> Match:
        matched, of, samples = 0, 0, []
        for label, cond in parts:
            matched += _count(env, f"MATCH (c:{label}) WHERE ({cond}) RETURN count(c) AS n")
            of += _count(env, f"MATCH (c:{label}) RETURN count(c) AS n")
            samples += _samples(env, f"MATCH (c:{label}) WHERE ({cond}) RETURN {_ID} AS id")
        return Match(matched, of, samples)

    def apply(env: Env) -> int:
        return sum(
            batched(
                env.db,
                f"MATCH (c:{label}) WHERE ({cond}) WITH c LIMIT {{batch}} "
                "DETACH DELETE c RETURN count(*) AS n",
            )
            for label, cond in parts
        )

    return register(Rule(name, 1, match, apply, destructive=True))


def _report(key: str = "report_id") -> str:
    return _gone(key, "Report")


_orphan_rule(
    "orphan_report_children",
    [
        ("ReportEntity", _report()),
        ("ReportVersion", _report()),
        ("Copy", _either(_report(), _report("copy_of"))),
        ("Cites", _report()),
        ("Quotes", _gone("figure_id", "Figure")),
        ("BeatMaybe", f"c.label IS NULL AND {_report()}"),  # a labelled one is eval data
        ("Claim", _report()),
        ("Figure", _report()),
    ],
)
_orphan_rule(
    "orphan_group_children",
    [
        ("Conflict", _either(_gone("group_a", "ClaimGroup"), _gone("group_b", "ClaimGroup"))),
        ("DomainDriver", _gone("group_id", "ClaimGroup")),
    ],
)
_orphan_rule(
    "orphan_story_children",
    [
        ("StoryParty", _gone("story_id", "Story")),
        (
            "ShortVersion",
            "c.id STARTS WITH 'story:' AND NOT EXISTS { MATCH (p:Story {id: substring(c.id, 6)}) }",
        ),
        ("Prediction", _gone("story_id", "Story")),
    ],
)
_orphan_rule(
    "orphan_event_children",
    [
        (
            "ShortVersion",
            "NOT c.id STARTS WITH 'story:' AND NOT EXISTS { MATCH (p:Event {id: c.id}) }",
        ),
        (
            "MergeRejected",
            _either(
                "NOT EXISTS { MATCH (p:Event {id: split(c.pair, '|')[0]}) }",
                "NOT EXISTS { MATCH (p:Event {id: split(c.pair, '|')[1]}) }",
            ),
        ),
    ],
)
_orphan_rule("orphan_source_children", [("SourceWeight", _gone("source_id", "Source"))])
_orphan_rule(
    "orphan_document_children",
    [
        ("Statement", _either(_gone("document_id", "Document"), _gone("actor_id", "Actor"))),
        ("Quotes", _gone("statement_id", "Statement")),
    ],
)
_orphan_rule(
    "orphan_beat_children",
    [
        ("BeatProfile", _gone("beat_id", "Beat")),
        ("BeatMaybe", f"c.label IS NULL AND {_gone('beat_id', 'Beat')}"),
        ("DomainCandidate", _gone("beat_id", "Beat")),
    ],
)
_orphan_rule(
    "orphan_domain_children",
    [
        ("DomainDriver", _gone("domain_id", "Domain")),
        ("Prediction", f"c.status = 'open' AND {_gone('domain_id', 'Domain')}"),
    ],
)

# --- report only: a person decides -------------------------------------------------------------


def _broken_refs(env: Env) -> list[str]:
    out = [
        f"Story:{r['id']}"
        for r in env.db.execute(
            "MATCH (c:Story) WHERE c.beat_id IS NOT NULL AND NOT EXISTS { "
            "MATCH (p:Beat {id: c.beat_id}) } RETURN c.id AS id"
        )
    ]
    out += [
        f"Report:{r['id']}"
        for r in env.db.execute(
            "MATCH (c:Report) WHERE c.valid_to IS NULL AND c.source_id IS NOT NULL AND NOT EXISTS { "
            "MATCH (p:Source {id: c.source_id}) } RETURN c.id AS id"
        )
    ]
    ids: set[str] = set()
    anomalies = env.db.execute(
        "MATCH (a:Anomaly) WHERE a.valid_to IS NULL RETURN a.id AS id, a.subject_id AS s, "
        "a.event_id AS e, a.evidence_ids AS ev"
    )
    for a in anomalies:
        ids |= {x for x in [a["s"], a["e"], *json.loads(a["ev"] or "[]")] if isinstance(x, str)}
    found = {
        r["id"]
        for r in env.db.execute(
            "MATCH (n) WHERE n.id IN ? RETURN DISTINCT n.id AS id", (sorted(ids),)
        )
    }
    for a in anomalies:  # rule 2: evidence is stored, so a broken pointer needs a look
        refs = [x for x in [a["s"], a["e"], *json.loads(a["ev"] or "[]")] if isinstance(x, str)]
        if any(x not in found for x in refs):
            out.append(f"Anomaly:{a['id']}")
    return sorted(out)


def _broken_match(env: Env) -> Match:
    found = _broken_refs(env)
    return Match(len(found), None, found)


# Never auto-deleted: an anomaly's evidence is part of its record (product rule 2).
register(Rule("broken_references", 1, _broken_match, lambda env: 0))
