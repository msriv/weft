"""Expiry rules (#152): each deletes the old, and keeps its neighbour (a labelled BeatMaybe, a
rated ReviewItem, an off-beat report inside the window)."""

from datetime import timedelta
from typing import Any

from tests.test_autoclean import NOW, ctx
from tests.test_autoclean_graph import count, go
from weft_core import graph

OLD = (NOW - timedelta(days=200)).isoformat()
MID = (NOW - timedelta(days=40)).isoformat()
NEW = (NOW - timedelta(days=1)).isoformat()


def left(c: Any, label: str, key: str) -> set[str]:
    return {r["k"] for r in c.db.execute(f"MATCH (n:{label}) RETURN n.{key} AS k")}


def test_nli_cache_and_merge_rejected_expire_and_old_undated_ones_get_a_date() -> None:
    c = ctx()
    graph.put(c.db, "events", {"id": "a"}, NEW)
    graph.put(c.db, "events", {"id": "b"}, NEW)
    c.db.execute(
        "CREATE (:NliCache {key: 'old', created_at: ?}), (:NliCache {key: 'new', created_at: ?})",
        (MID, NEW),
    )
    c.db.execute("CREATE (:NliCache {key: 'undated'})")
    c.db.execute(
        "CREATE (:MergeRejected {pair: 'a|b', created_at: ?}), (:MergeRejected {pair: 'a|b2', created_at: ?})",
        (NEW, NEW),
    )
    c.db.execute(
        "CREATE (:MergeRejected {pair: 'a|x', created_at: ?}), (:MergeRejected {pair: 'a|b3', created_at: ?})",
        (NEW, MID),
    )
    c.db.execute("CREATE (:MergeRejected {pair: 'a|b'})")  # same pair, undated
    go(c, "nli_cache", "merge_rejected", snapshot=False)
    assert left(c, "NliCache", "key") == {"new", "undated"}
    assert (
        count(
            c,
            "MATCH (n:NliCache {key: 'undated'}) WHERE n.created_at IS NOT NULL RETURN count(n) AS n",
        )
        == 1
    )
    # b2 and x name an event with no current version; b3 is old
    assert left(c, "MergeRejected", "pair") == {"a|b"}


def test_portal_requested_candidates_and_translations() -> None:
    c = ctx()
    c.db.execute(
        "CREATE (:PortalCandidate {domain: 'old.gov', last_seen: ?}), (:PortalCandidate {domain: 'new.gov', last_seen: ?})",
        (MID, NEW),
    )
    c.db.execute(
        "CREATE (:DomainCandidate {domain: 'a', beat_id: 'b', requested: 1, first_seen: ?})", (MID,)
    )
    c.db.execute(
        "CREATE (:DomainCandidate {domain: 'b', beat_id: 'b', requested: 1, first_seen: ?})", (NEW,)
    )
    c.db.execute(
        "CREATE (:DomainCandidate {domain: 'c', beat_id: 'b', first_seen: ?})", (OLD,)
    )  # not requested
    c.db.execute(
        "CREATE (:Translation {key: 'stale', created_at: ?}), (:Translation {key: 'used', created_at: ?, last_used: ?})",
        (OLD, OLD, NEW),
    )
    go(
        c,
        "portal_candidates",
        "requested_candidates",
        "translations",
        extra={"translations": {"days": 90}},
    )
    assert left(c, "PortalCandidate", "domain") == {"new.gov"}
    assert left(c, "DomainCandidate", "domain") == {"b", "c"}
    assert left(c, "Translation", "key") == {"used"}


def test_beat_maybe_and_review_items_keep_what_the_owner_worked_on() -> None:
    c = ctx()
    c.db.execute(
        "CREATE (:BeatMaybe {report_id: 'r1', beat_id: 'b', created_at: ?}), (:BeatMaybe {report_id: 'r2', beat_id: 'b', created_at: ?, label: 'yes'})",
        (MID, MID),
    )
    c.db.execute("CREATE (:BeatMaybe {report_id: 'r3', beat_id: 'b', created_at: ?})", (NEW,))
    c.db.execute(
        "CREATE (:ReviewItem {id: 'u', sampled_at: ?}), (:ReviewItem {id: 'rated', sampled_at: ?, rating: 'ok'}), (:ReviewItem {id: 'fresh', sampled_at: ?})",
        (OLD, OLD, NEW),
    )
    go(c, "beat_maybe", "review_items")
    assert left(c, "BeatMaybe", "report_id") == {"r2", "r3"}
    assert left(c, "ReviewItem", "id") == {"rated", "fresh"}


def test_batch_runs_daily_diff() -> None:
    c = ctx()
    c.db.execute(
        "CREATE (:BatchRun {run_id: 'o', stage: 'x', started_at: ?}), (:BatchRun {run_id: 'n', stage: 'x', started_at: ?})",
        (OLD, NEW),
    )
    c.db.execute(
        "CREATE (:AutocleanRun {run_id: 'o', rule: 'x', started_at: ?}), (:AutocleanRun {run_id: 'n', rule: 'x', started_at: ?})",
        (OLD, NEW),
    )
    c.db.execute("CREATE (:DailyDiff {day: '2026-01-01'}), (:DailyDiff {day: '2026-11-13'})")
    go(
        c,
        "batch_runs",
        "daily_diff",
        extra={"batch_runs": {"days": 180}, "daily_diff": {"days": 90}},
    )
    assert left(c, "BatchRun", "run_id") == {"n", "snap"} and "o" not in left(
        c, "AutocleanRun", "run_id"
    )
    assert left(c, "DailyDiff", "day") == {"2026-11-13"}


def test_offbeat_reports_are_deleted_with_children_only_when_in_no_story_and_old() -> None:
    c = ctx()
    graph.put(c.db, "reports", {"id": "off-old", "published_at": MID}, MID)
    graph.put(c.db, "reports", {"id": "off-new", "published_at": NEW}, NEW)
    graph.put(c.db, "reports", {"id": "on-old", "published_at": MID, "story_id": "s"}, MID)
    # placed once, later unplaced: it was in a story in some version, so it stays
    graph.put(c.db, "reports", {"id": "was-on", "published_at": MID, "story_id": "s"}, MID)
    graph.put(c.db, "reports", {"id": "was-on", "published_at": MID}, NEW)
    graph.put(c.db, "reports", {"id": "off-labelled", "published_at": MID}, MID)
    c.db.execute(
        "CREATE (:BeatMaybe {report_id: 'off-labelled', beat_id: 'b', label: 'yes', created_at: ?})",
        (MID,),
    )
    for rid in ("off-old", "off-new", "on-old"):
        c.db.execute(
            "CREATE (:ReportEntity {report_id: ?, name: 'x'}), (:ReportVersion {report_id: ?, n: 0}), (:Copy {report_id: ?, copy_of: 'on-old'}), (:Cites {report_id: ?, url_key: 'k'})",
            (rid, rid, rid, rid),
        )
    c.db.execute("CREATE (:Copy {report_id: 'on-old', copy_of: 'off-old'})")
    r = go(c, "offbeat_reports")["offbeat_reports"]
    assert r["status"] == "ok" and r["changed"] == 1, r["note"]
    assert left(c, "Report", "id") == {"off-new", "on-old", "was-on", "off-labelled"}
    assert left(c, "ReportEntity", "report_id") == {"off-new", "on-old"}
    assert (
        count(
            c,
            "MATCH (n:Copy) WHERE n.report_id = 'off-old' OR n.copy_of = 'off-old' RETURN count(n) AS n",
        )
        == 0
    )


def test_reader_email_cleared_after_resolution_window() -> None:
    c = ctx()
    c.db.execute(
        "CREATE (:ReaderReport {id: 1, status: 'resolved', email: 'a@x', created_at: ?, message: 'm'})",
        (MID,),
    )
    c.db.execute(
        "CREATE (:ReaderReport {id: 2, status: 'open', email: 'b@x', created_at: ?})", (MID,)
    )
    c.db.execute(
        "CREATE (:ReaderReport {id: 3, status: 'resolved', email: 'c@x', created_at: ?})", (NEW,)
    )
    go(c, "reader_report_email", snapshot=False)
    got = {
        r["id"]: r["e"]
        for r in c.db.execute("MATCH (n:ReaderReport) RETURN n.id AS id, n.email AS e")
    }
    assert got == {1: None, 2: "b@x", 3: "c@x"}
    assert count(c, "MATCH (n:ReaderReport {id: 1}) RETURN count(n) AS n") == 1  # the report stays
