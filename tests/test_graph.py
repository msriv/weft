from weft_core import graph, store
from weft_core.store import SqliteDb


def db() -> SqliteDb:
    d = SqliteDb()
    graph.init(d)
    return d


def test_put_closes_previous_version_and_asof_replays() -> None:
    d = db()
    graph.put(
        d,
        "events",
        {"id": "e", "story_id": "s", "first_seen": "t", "centroid": [1.0]},
        "2026-01-01T00:00:00",
    )
    graph.put(
        d,
        "events",
        {"id": "e", "story_id": "s", "first_seen": "t", "centroid": [2.0]},
        "2026-01-02T00:00:00",
    )
    assert graph.get(d, "events", "e")["centroid"] == [2.0]  # type: ignore[index]
    assert graph.get(d, "events", "e", "2026-01-01T12:00:00")["centroid"] == [1.0]  # type: ignore[index]
    assert d.execute("SELECT COUNT(*) AS n FROM events")[0]["n"] == 2  # nothing deleted


def test_init_is_idempotent() -> None:
    d = db()
    graph.init(d)
    assert store.beats(d) == []
