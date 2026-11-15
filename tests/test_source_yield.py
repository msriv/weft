from datetime import UTC, datetime, timedelta

from weft_core import graph, sourceyield, store

NOW = datetime(2026, 11, 14, 9, 0, tzinfo=UTC)
CFG = {
    "window_days": 14, "dormant_days": 30, "low_yield": 0.05, "low_every": 6,
    "run_seconds": 600, "max_per_beat": 2, "max_total": 10,
}  # fmt: skip


def src(
    db: store.Db, sid: str, rel: float, y: float | None, beat: str = "b1", age: int = 40
) -> None:
    store.register_source(
        db, domain=f"{sid}.example", name=sid, homepage="h", feeds=["f"], via=f"gdelt:{beat}",
        relevance=rel,
    )  # fmt: skip
    db.execute(
        "MATCH (n:Source {id: ?}) SET n.yield_14d = ?, n.discovered_at = ?",
        (f"{sid}-example", y, (NOW - timedelta(days=age)).isoformat()),
    )


def report(db: store.Db, sid: str, i: int, days_ago: int, on_beat: bool) -> None:
    graph.put(
        db, "reports",
        {"id": f"{sid}{i}", "source_id": f"{sid}-example", "story_id": "s" if on_beat else None,
         "published_at": (NOW - timedelta(days=days_ago)).isoformat()},
    )  # fmt: skip


def test_ceiling_blocks_weaker_and_replaces_lowest_yield() -> None:
    db = store.local_db()
    store.init(db)
    src(db, "a", 0.9, 0.5)
    src(db, "b", 0.6, 0.01)
    assert not sourceyield.make_room(db, "b1", 0.5, CFG)  # weaker than the weakest: waits
    assert {s["id"] for s in store.active_sources(db)} == {"a-example", "b-example"}
    assert sourceyield.make_room(db, "b1", 0.8, CFG)  # stronger: b goes dormant
    assert {s["id"] for s in store.active_sources(db)} == {"a-example"}
    assert sourceyield.make_room(db, "other-beat", 0.1, CFG)  # room under its own ceiling


def test_source_without_onbeat_reports_goes_dormant_and_is_skipped() -> None:
    db = store.local_db()
    store.init(db)
    src(db, "quiet", 0.5, None)
    src(db, "busy", 0.5, None)
    for i in range(3):
        report(db, "quiet", i, 2, False)
        report(db, "busy", i, 2, i == 0)
    assert sourceyield.refresh(db, CFG, NOW) == ["quiet-example"]
    [s] = store.active_sources(db)
    assert s["id"] == "busy-example" and abs(s["yield"] - 1 / 3) < 1e-9


def test_low_yield_polled_every_nth_run_and_admin_reactivates() -> None:
    s = {"id": "x", "yield": 0.0}
    hits = sum(sourceyield.due(s, CFG, NOW + timedelta(seconds=600 * i)) for i in range(12))
    assert hits == 2
    assert sourceyield.due({"id": "x", "yield": 0.5}, CFG, NOW)
    assert sourceyield.due({"id": "x", "yield": None}, CFG, NOW)


def test_uncovered_country_probed_first() -> None:
    cands = [("a.co.uk", 0.5), ("b.co.in", 0.5), ("c.co.uk", 0.9)]
    country = {"a.co.uk": "GB", "c.co.uk": "GB", "b.co.in": "IN"}.get
    out = sourceyield.order(cands, {"GB": 3}, country)
    assert out[0][0] == "b.co.in"
