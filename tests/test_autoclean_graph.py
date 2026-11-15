"""Integrity rules (#149): a fixture with the fault, the repaired state, a healthy neighbour that
is left alone, and a child of a closed (not deleted) parent version that Replay still needs."""

import json
from datetime import timedelta
from typing import Any

from tests.test_autoclean import NOW, ctx
from weft_core import autoclean as ac
from weft_core import graph
from weft_core.autoclean import settings
from weft_core.autoclean_graph import VERSIONED  # noqa: F401  (also registers the rules)

LONG_AGO = (NOW - timedelta(days=3)).isoformat()


def go(
    c: Any, *names: str, snapshot: bool = True, extra: dict[str, dict[str, Any]] | None = None
) -> dict[str, dict[str, Any]]:
    if snapshot:
        c.db.execute(
            "CREATE (:BatchRun {run_id: 'snap', stage: 'snapshot', status: 'ok', "
            "started_at: ?, ended_at: ?})",
            (NOW.isoformat(), NOW.isoformat()),
        )
    from tests.test_autoclean import CFG

    rules = {
        n: {
            **CFG["rules"].get(n, {}),
            "mode": "apply",
            "max_fraction": 1.0,
            **(extra or {}).get(n, {}),
        }
        for n in names
    }
    cfg = {**CFG, "rules": {**CFG["rules"], **rules}}
    return {r["rule"]: r for r in ac.run_all(c.db, NOW, cfg=cfg)}


def count(c: Any, q: str, *args: Any) -> int:
    return int(c.db.execute(q, tuple(args))[0]["n"])


def test_put_is_one_statement_and_keeps_history() -> None:
    c = ctx()
    graph.put(c.db, "events", {"id": "e", "story_id": "s"}, "2026-01-01T00:00:00")
    graph.put(c.db, "events", {"id": "e", "story_id": "s"}, "2026-01-02T00:00:00")
    rows = c.db.execute("MATCH (n:Event) RETURN n.valid_from AS f, n.valid_to AS t ORDER BY f")
    assert rows == [
        {"f": "2026-01-01T00:00:00", "t": "2026-01-02T00:00:00"},
        {"f": "2026-01-02T00:00:00", "t": None},
    ]


def test_duplicate_current_keeps_the_newest_open() -> None:
    c = ctx()
    for v, f in (("a", "2026-01-01"), ("b", "2026-01-02"), ("c", "2026-01-03")):
        c.db.execute("CREATE (:Event {id: 'e', story_id: ?, valid_from: ?})", (v, f))
    c.db.execute("CREATE (:Event {id: 'ok', valid_from: '2026-01-01'})")
    r = go(c, "duplicate_current")["duplicate_current"]
    assert r["matched"] == 2 and r["changed"] == 2
    rows = c.db.execute(
        "MATCH (n:Event {id: 'e'}) RETURN n.story_id AS s, n.valid_to AS t ORDER BY s"
    )
    assert rows == [
        {"s": "a", "t": "2026-01-03"},  # closed at the newest one's valid_from
        {"s": "b", "t": "2026-01-03"},
        {"s": "c", "t": None},
    ]
    assert count(c, "MATCH (n:Event {id: 'ok'}) WHERE n.valid_to IS NULL RETURN count(n) AS n") == 1
    assert go(c, "duplicate_current", snapshot=False)["duplicate_current"]["changed"] == 0


def test_event_counts_are_recounted() -> None:
    c = ctx()
    graph.put(c.db, "events", {"id": "e1", "n_reports": 5}, LONG_AGO)
    graph.put(c.db, "events", {"id": "e2", "n_reports": 1}, LONG_AGO)
    for i in ("r1", "r2"):
        graph.put(c.db, "reports", {"id": i, "event_id": "e1"}, LONG_AGO)
    graph.put(c.db, "reports", {"id": "r3", "event_id": "e2"}, LONG_AGO)
    go(c, "event_counts")
    got = {
        r["id"]: r["n"] for r in c.db.execute("MATCH (e:Event) RETURN e.id AS id, e.n_reports AS n")
    }
    assert got == {"e1": 2, "e2": 1}


def test_empty_event_is_closed_not_deleted_and_a_new_one_is_left() -> None:
    c = ctx()
    graph.put(c.db, "events", {"id": "empty"}, LONG_AGO)
    graph.put(c.db, "events", {"id": "full"}, LONG_AGO)
    graph.put(c.db, "events", {"id": "new"}, (NOW - timedelta(minutes=5)).isoformat())
    graph.put(c.db, "reports", {"id": "r", "event_id": "full"}, LONG_AGO)
    go(c, "empty_event")
    open_ids = {
        r["id"] for r in c.db.execute("MATCH (e:Event) WHERE e.valid_to IS NULL RETURN e.id AS id")
    }
    assert open_ids == {"full", "new"}
    assert count(c, "MATCH (e:Event {id: 'empty'}) RETURN count(e) AS n") == 1  # still there


def test_dangling_event_ref_clears_reports_and_follows_the_report_for_claims() -> None:
    c = ctx()
    graph.put(c.db, "events", {"id": "live"}, LONG_AGO)
    graph.put(c.db, "reports", {"id": "gone-r", "event_id": "dead"}, LONG_AGO)
    graph.put(c.db, "reports", {"id": "ok-r", "event_id": "live"}, LONG_AGO)
    graph.put(c.db, "claims", {"id": "c1", "report_id": "ok-r", "event_id": "dead"}, LONG_AGO)
    graph.put(c.db, "claims", {"id": "c2", "report_id": "ok-r", "event_id": "live"}, LONG_AGO)
    go(c, "dangling_event_ref")
    ev = {
        r["id"]: r["e"]
        for r in c.db.execute(
            "MATCH (n) WHERE n:Report OR n:Claim RETURN n.id AS id, n.event_id AS e"
        )
    }
    assert ev == {"gone-r": None, "ok-r": "live", "c1": "live", "c2": "live"}


def test_missing_version0_is_created_from_the_report() -> None:
    c = ctx()
    graph.put(c.db, "reports", {"id": "a", "text_hash": "h", "fetched_at": "t0"}, LONG_AGO)
    graph.put(c.db, "reports", {"id": "b", "text_hash": "h2", "fetched_at": "t1"}, LONG_AGO)
    c.db.execute(
        "CREATE (:ReportVersion {report_id: 'b', n: 0, fetched_at: 't1', text_hash: 'h2'})"
    )
    go(c, "missing_version0")
    rows = c.db.execute(
        "MATCH (v:ReportVersion) RETURN v.report_id AS r, v.fetched_at AS f, v.text_hash AS h ORDER BY r"
    )
    assert rows == [{"r": "a", "f": "t0", "h": "h"}, {"r": "b", "f": "t1", "h": "h2"}]


def test_stale_perspective_is_retagged() -> None:
    c = ctx()
    c.db.execute(
        "CREATE (:Source {id: 's1', name: 'S', country: 'IL', status: 'active', type: 'news',"
        " feeds: '[]', sitemaps: '[]', languages: '[\"en\"]', min_interval: 10.0})"
    )
    graph.put(c.db, "reports", {"id": "r", "source_id": "s1", "perspective": "US"}, LONG_AGO)
    r = go(c, "stale_perspective")["stale_perspective"]
    assert r["changed"] == 1
    assert graph.get(c.db, "reports", "r")["perspective"] == "IL"  # type: ignore[index]


def test_subscription_follows_drop_ids_with_no_story() -> None:
    c = ctx()
    c.db.execute("CREATE (:Story {id: 's1'})")
    c.db.execute("CREATE (:Subscription {email: 'a@x', follows: ?})", (json.dumps(["s1", "gone"]),))
    c.db.execute("CREATE (:Subscription {email: 'b@x', follows: ?})", (json.dumps(["s1"]),))
    go(c, "subscription_follows")
    got = {
        r["e"]: json.loads(r["f"])
        for r in c.db.execute("MATCH (n:Subscription) RETURN n.email AS e, n.follows AS f")
    }
    assert got == {"a@x": ["s1"], "b@x": ["s1"]}


def test_dangling_group_ref_keeps_the_claim() -> None:
    c = ctx()
    graph.put(c.db, "claim_groups", {"id": "g"}, LONG_AGO)
    graph.put(c.db, "claims", {"id": "c1", "group_id": "nope"}, LONG_AGO)
    graph.put(c.db, "claims", {"id": "c2", "group_id": "g"}, LONG_AGO)
    go(c, "dangling_group_ref")
    got = {
        r["id"]: r["g"] for r in c.db.execute("MATCH (n:Claim) RETURN n.id AS id, n.group_id AS g")
    }
    assert got == {"c1": None, "c2": "g"}


def test_orphan_report_children_deleted_but_a_closed_parent_version_keeps_them() -> None:
    c = ctx()
    graph.put(c.db, "reports", {"id": "live"}, LONG_AGO)
    graph.put(c.db, "reports", {"id": "closed"}, LONG_AGO)
    c.db.execute("MATCH (r:Report {id: 'closed'}) SET r.valid_to = ?", (NOW.isoformat(),))
    for rid in ("live", "closed", "gone"):
        c.db.execute("CREATE (:ReportEntity {report_id: ?, name: 'x'})", (rid,))
        c.db.execute("CREATE (:ReportVersion {report_id: ?, n: 0})", (rid,))
        c.db.execute("CREATE (:Cites {report_id: ?, url_key: 'k'})", (rid,))
    c.db.execute("CREATE (:Copy {report_id: 'live', copy_of: 'gone'})")
    c.db.execute("CREATE (:BeatMaybe {report_id: 'gone', beat_id: 'b'})")
    c.db.execute(
        "CREATE (:BeatMaybe {report_id: 'gone', beat_id: 'b2', label: 'yes'})"
    )  # eval data
    graph.put(c.db, "claims", {"id": "orphan-claim", "report_id": "gone"}, LONG_AGO)
    graph.put(c.db, "claims", {"id": "kept-claim", "report_id": "closed"}, LONG_AGO)
    r = go(c, "orphan_report_children", extra={"orphan_report_children": {"max_rows": 100}})[
        "orphan_report_children"
    ]
    assert r["status"] == "ok", r["note"]
    left = {x["id"] for x in c.db.execute("MATCH (n:ReportEntity) RETURN n.report_id AS id")}
    assert left == {"live", "closed"}
    assert count(c, "MATCH (n:Copy) RETURN count(n) AS n") == 0  # either end
    assert count(c, "MATCH (n:BeatMaybe) RETURN count(n) AS n") == 1  # the labelled one stays
    assert {x["id"] for x in c.db.execute("MATCH (n:Claim) RETURN n.id AS id")} == {"kept-claim"}


def test_orphan_rules_need_a_good_snapshot_and_respect_the_cap() -> None:
    c = ctx()
    c.db.execute("CREATE (:SourceWeight {source_id: 'gone', day: 'd'})")
    r = go(c, "orphan_source_children", snapshot=False)["orphan_source_children"]
    assert r["status"] == "skipped" and count(c, "MATCH (n:SourceWeight) RETURN count(n) AS n") == 1
    c2 = ctx()
    c2.db.execute("CREATE (:Source {id: 'ok'})")
    for i in range(10):
        c2.db.execute("CREATE (:SourceWeight {source_id: ?, day: 'd'})", ("ok" if i else "gone",))
    capped = go(
        c2, "orphan_source_children", extra={"orphan_source_children": {"max_fraction": 0.05}}
    )
    assert capped["orphan_source_children"]["status"] == "aborted"  # 1 of 10 is over 5%


def test_other_orphan_rules_delete_only_orphans() -> None:
    c = ctx()
    c.db.execute(
        "CREATE (:Story {id: 's'}), (:Beat {id: 'b'}), (:Event {id: 'e'}), (:Document {id: 'd'}), (:Domain {id: 'dm'})"
    )
    c.db.execute("CREATE (:ClaimGroup {id: 'g'}), (:Actor {id: 'a'})")
    q = [
        "CREATE (:StoryParty {story_id: 's'}), (:StoryParty {story_id: 'x'})",
        "CREATE (:ShortVersion {id: 'story:s'}), (:ShortVersion {id: 'story:x'})",
        "CREATE (:ShortVersion {id: 'e'}), (:ShortVersion {id: 'ex'})",
        "CREATE (:MergeRejected {pair: 'e|e'}), (:MergeRejected {pair: 'e|gone'})",
        "CREATE (:Statement {id: 's1', document_id: 'd', actor_id: 'a'}), (:Statement {id: 's2', document_id: 'x', actor_id: 'a'})",
        "CREATE (:BeatProfile {beat_id: 'b'}), (:BeatProfile {beat_id: 'x'}), (:DomainCandidate {domain: 'd1', beat_id: 'x'})",
        "CREATE (:DomainDriver {domain_id: 'dm', group_id: 'g'}), (:DomainDriver {domain_id: 'x', group_id: 'g'}), (:DomainDriver {domain_id: 'dm', group_id: 'x'})",
        "CREATE (:Conflict {group_a: 'g', group_b: 'x'}), (:Conflict {group_a: 'g', group_b: 'g'})",
        "CREATE (:Prediction {id: 'p1', domain_id: 'x', status: 'open'}), (:Prediction {id: 'p2', domain_id: 'x', status: 'resolved'})",
    ]
    for stmt in q:
        c.db.execute(stmt)
    names = [n for n in ac.RULES if n.startswith("orphan_") and n != "orphan_report_children"]
    ex = {n: {"max_rows": 100} for n in names}
    out = go(c, *names, extra=ex)
    assert all(out[n]["status"] == "ok" for n in names), {n: out[n]["note"] for n in names}

    def n(lab: str) -> int:
        return count(c, f"MATCH (n:{lab}) RETURN count(n) AS n")

    assert (n("StoryParty"), n("ShortVersion"), n("MergeRejected"), n("Statement")) == (1, 2, 1, 1)
    assert (n("BeatProfile"), n("DomainCandidate"), n("DomainDriver"), n("Conflict")) == (
        1,
        0,
        1,
        1,
    )
    assert {r["id"] for r in c.db.execute("MATCH (p:Prediction) RETURN p.id AS id")} == {
        "p2"
    }  # resolved kept


def test_broken_references_are_reported_never_deleted() -> None:
    c = ctx()
    graph.put(
        c.db,
        "anomalies",
        {"id": "an", "subject_id": "r1", "evidence_ids": ["r1", "missing"]},
        LONG_AGO,
    )
    graph.put(c.db, "reports", {"id": "r1", "source_id": "nosource"}, LONG_AGO)
    c.db.execute("CREATE (:Story {id: 's', beat_id: 'nobeat'})")
    r = go(c, "broken_references")["broken_references"]
    assert set(json.loads(r["sample_ids"])) == {"Anomaly:an", "Report:r1", "Story:s"}
    assert count(c, "MATCH (n:Anomaly) RETURN count(n) AS n") == 1


def test_healthy_graph_is_untouched_by_every_integrity_rule() -> None:
    c = ctx()
    graph.put(c.db, "events", {"id": "e", "n_reports": 1}, LONG_AGO)
    graph.put(
        c.db, "reports", {"id": "r", "event_id": "e", "source_id": "s", "text_hash": "h"}, LONG_AGO
    )
    c.db.execute("CREATE (:ReportVersion {report_id: 'r', n: 0, text_hash: 'h'})")
    c.db.execute(
        "CREATE (:Source {id: 's', status: 'active', type: 'news', feeds: '[]', sitemaps: '[]', languages: '[\"en\"]', min_interval: 10.0})"
    )
    names = [
        n
        for n in ac.RULES
        if n
        in (
            "duplicate_current",
            "event_counts",
            "empty_event",
            "dangling_event_ref",
            "missing_version0",
            "dangling_group_ref",
        )
        or n.startswith("orphan_")
    ]
    out = go(c, *names)
    assert {n: out[n]["changed"] for n in names} == dict.fromkeys(names, 0)
    assert settings({"defaults": {"a": 1}, "rules": {}}, "x") == {"a": 1}
