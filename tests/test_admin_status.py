"""Admin status (#176): empty and populated graph, thresholds, source paging and filters."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from services.api.app import create_app
from weft_core import graph, status, store
from weft_core.store import Neo4jDb, local_db


def fresh() -> Neo4jDb:
    d = local_db()
    graph.init(d)
    return d


NOW = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
CFG = {
    "ingest_slow_minutes": 60,
    "ingest_stopped_minutes": 360,
    "stage_slow_hours": 30,
    "stage_stopped_hours": 54,
    "silent_source_days": 7,
}


def test_empty_graph_says_stopped_not_crash() -> None:
    db = fresh()
    s = status.collect(db, NOW, CFG)
    assert s["ingest"]["state"] == "stopped" and s["ingest"]["stored"] == {
        "last_hour": 0,
        "last_day": 0,
    }
    assert s["nightly"]["stages"] == [] and s["per_beat_today"] == []
    assert s["model_spend"] is None and s["queue"] is None  # shown as not available


def test_populated_graph_counts_and_states() -> None:
    db = fresh()
    store.create(
        db,
        "Source",
        {
            "id": "a",
            "name": "Aldoria Post",
            "domain": "aldoria.example",
            "status": "active",
            "country": "AL",
        },
    )
    store.create(
        db,
        "Source",
        {
            "id": "b",
            "name": "Veymar Wire",
            "domain": "veymar.example",
            "status": "active",
            "country": "VE",
        },
    )
    store.create(db, "Story", {"id": "s1", "beat_id": "kessar", "title": "T", "public": 1})
    for i, (story, mins) in enumerate([("s1", 10), ("s1", 30), (None, 40), ("s1", 60 * 5)]):
        store.create(
            db,
            "Report",
            {
                "id": f"r{i}",
                "source_id": "a",
                "story_id": story,
                "fetched_at": (NOW - timedelta(minutes=mins)).isoformat(),
            },
        )
    store.create(
        db,
        "BatchRun",
        {
            "run_id": "x",
            "stage": "claims",
            "started_at": (NOW - timedelta(hours=40)).isoformat(),
            "status": "ok",
        },
    )
    s = status.collect(db, NOW, CFG)
    assert s["ingest"]["state"] == "ok"
    assert s["ingest"]["stored"] == {"last_hour": 3, "last_day": 4}
    assert {r["beat"]: r["reports"] for r in s["per_beat_today"]} == {"kessar": 3, "unplaced": 1}
    assert s["nightly"]["state"] == "slow"
    assert s["sources"]["active"] == 2 and s["sources"]["silent_ids"] == ["b"]
    assert s["graph"]["nodes"] >= 7


def test_admin_endpoint_and_source_paging() -> None:
    db = fresh()
    for i in range(5):
        store.create(
            db,
            "Source",
            {
                "id": f"s{i}",
                "name": f"Outlet {i}",
                "domain": f"o{i}.example",
                "status": "active" if i < 4 else "rejected",
                "country": "AL" if i % 2 else "VE",
            },
        )
    c = TestClient(create_app(db, "t0k"))
    H = {"X-Admin-Token": "t0k"}
    assert c.get("/admin/status").status_code == 401
    assert c.get("/admin/status", headers=H).json()["sources"]["active"] == 4
    page = c.get("/admin/sources", params={"limit": 2, "offset": 2}, headers=H)
    assert len(page.json()) == 2 and page.headers["X-Total-Count"] == "5"
    assert [
        x["id"] for x in c.get("/admin/sources", params={"q": "OUTLET 3"}, headers=H).json()
    ] == ["s3"]
    assert [
        x["id"] for x in c.get("/admin/sources", params={"status": "rejected"}, headers=H).json()
    ] == ["s4"]
    assert {
        x["id"] for x in c.get("/admin/sources", params={"country": "al"}, headers=H).json()
    } == {"s1", "s3"}
