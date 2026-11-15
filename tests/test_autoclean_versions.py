"""Version compaction (#151): lossless for Replay, and it keeps the audit trail."""

import json
from datetime import timedelta
from typing import Any

from tests.test_autoclean import NOW, ctx
from tests.test_autoclean_graph import count, go
from weft_core import graph, readmodel, store

D = (NOW - timedelta(days=60)).date()  # the past day Replay is asked about
DAY = D.isoformat()
NEXT = (D + timedelta(days=1)).isoformat()


def t(hh: int, day: str = DAY) -> str:
    return f"{day}T{hh:02d}:00:00+00:00"


def build(c: Any) -> None:
    store.create_story(c.db, "s", "beat", "A story")
    store.set_public(c.db, "s", True)
    # one event rewritten three times on day D (a chain), then again the next day
    for hh in (8, 9, 10, 11):
        graph.put(
            c.db,
            "events",
            {
                "id": "e",
                "story_id": "s",
                "first_seen": t(8),
                "centroid": [0.1, 0.2],
                "entity_counts": {"x": hh},
                "n_reports": hh - 7,
                "label_report_id": "r",
            },
            t(hh),
        )
    graph.put(
        c.db, "events", {"id": "e", "story_id": "s", "first_seen": t(8), "n_reports": 5}, t(3, NEXT)
    )
    for i, hh in enumerate((8, 11)):
        graph.put(
            c.db,
            "reports",
            {
                "id": f"r{i}",
                "story_id": "s",
                "event_id": "e",
                "source_id": "src",
                "perspective": "IL",
                "title": f"T{i}",
                "published_at": t(hh),
                "fetched_at": t(hh),
                "type": "news",
                "embedding": [0.3, 0.4],
                "minhash": [1, 2, 3],
            },
            t(hh),
        )
    graph.put(
        c.db,
        "reports",
        {
            "id": "r0",
            "story_id": "s",
            "event_id": "e",
            "source_id": "src",
            "perspective": "IL",
            "title": "T0 edited",
            "published_at": t(8),
            "fetched_at": t(8),
            "type": "news",
        },
        t(2, NEXT),
    )
    graph.put(
        c.db,
        "anomalies",
        {
            "id": "an",
            "story_id": "s",
            "rule": "x",
            "status": "open",
            "event_id": "e",
            "evidence_ids": ["r0"],
        },
        t(9),
    )
    graph.put(
        c.db,
        "anomalies",
        {
            "id": "an",
            "story_id": "s",
            "rule": "x",
            "status": "open",
            "event_id": "e",
            "evidence_ids": ["r0"],
        },
        t(10),
    )


def replay(c: Any, day: str) -> str:
    end = f"{day}T23:59:59+00:00"
    page = readmodel.story_graph(c.db, "s", at=end, days=0)
    return json.dumps(page, sort_keys=True, default=str)


def test_replay_is_identical_after_both_rules_and_history_is_kept() -> None:
    c = ctx()
    build(c)
    before = {d: replay(c, d) for d in (DAY, NEXT)}
    versions_before = count(c, "MATCH (n:Event {id: 'e'}) RETURN count(n) AS n")
    assert versions_before == 5
    out = go(c, "strip_closed_vectors", "collapse_intraday_versions")
    assert out["strip_closed_vectors"]["status"] == "ok", out["strip_closed_vectors"]["note"]
    assert out["collapse_intraday_versions"]["status"] == "ok", out["collapse_intraday_versions"][
        "note"
    ]
    assert {d: replay(c, d) for d in (DAY, NEXT)} == before
    # the chain of three same-day versions is gone; the one that took over starts when it did
    rows = c.db.execute(
        "MATCH (n:Event {id: 'e'}) RETURN n.valid_from AS f, n.valid_to AS t ORDER BY f"
    )
    assert rows == [{"f": t(8), "t": t(3, NEXT)}, {"f": t(3, NEXT), "t": None}]
    # closed versions lost their vectors; the open ones kept theirs
    closed = c.db.execute(
        "MATCH (n:Report) WHERE n.valid_to IS NOT NULL RETURN n.embedding AS e, n.minhash AS m"
    )
    assert closed and all(r["e"] is None and r["m"] is None for r in closed)
    cur = c.db.execute(
        "MATCH (n:Report {id: 'r1'}) WHERE n.valid_to IS NULL RETURN n.embedding AS e"
    )
    assert cur[0]["e"] is not None
    # the audit trail is untouched: both Anomaly versions are still there
    assert count(c, "MATCH (n:Anomaly {id: 'an'}) RETURN count(n) AS n") == 2


def test_recent_versions_and_open_versions_are_left_alone_and_a_second_run_is_a_noop() -> None:
    c = ctx()
    recent = (NOW - timedelta(days=3)).date().isoformat()
    for hh in (8, 9, 10):
        graph.put(c.db, "events", {"id": "e", "story_id": "s", "centroid": [1.0]}, t(hh, recent))
    first = go(c, "strip_closed_vectors", "collapse_intraday_versions")
    assert first["strip_closed_vectors"]["changed"] == 0  # closed 3 days ago, window is 7
    assert first["collapse_intraday_versions"]["changed"] == 0  # window is 30
    assert count(c, "MATCH (n:Event) RETURN count(n) AS n") == 3
    c2 = ctx()
    build(c2)
    go(c2, "strip_closed_vectors", "collapse_intraday_versions")
    again = go(c2, "strip_closed_vectors", "collapse_intraday_versions", snapshot=False)
    assert again["strip_closed_vectors"]["changed"] == 0
    assert again["collapse_intraday_versions"]["changed"] == 0


def test_a_same_day_version_with_no_successor_is_kept() -> None:
    c = ctx()
    graph.put(c.db, "events", {"id": "gone"}, t(8))
    c.db.execute(
        "MATCH (n:Event {id: 'gone'}) SET n.valid_to = ?", (t(9),)
    )  # closed, nothing after
    out = go(c, "collapse_intraday_versions")
    assert out["collapse_intraday_versions"]["changed"] == 0
    assert count(c, "MATCH (n:Event {id: 'gone'}) RETURN count(n) AS n") == 1


def test_compaction_waits_for_a_good_snapshot() -> None:
    c = ctx()
    build(c)
    out = go(c, "strip_closed_vectors", "collapse_intraday_versions", snapshot=False)
    assert out["strip_closed_vectors"]["status"] == "skipped"
    assert out["collapse_intraday_versions"]["status"] == "skipped"
    assert count(c, "MATCH (n:Event {id: 'e'}) RETURN count(n) AS n") == 5
