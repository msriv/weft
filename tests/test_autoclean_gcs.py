"""GCS rules (#154) with an in-memory bucket, and the snapshot's completion marker."""

import json
from datetime import timedelta
from typing import Any

from tests.test_autoclean import NOW, ctx
from weft_core import autoclean as ac
from weft_core import config
from weft_core.autoclean import Blob


class FakeBlobs:
    def __init__(self, ages_days: dict[str, float]) -> None:
        self.t = {n: NOW - timedelta(days=d) for n, d in ages_days.items()}
        self.deleted: list[str] = []

    def list(self, prefix: str = "", limit: int | None = None) -> list[Blob]:
        out = [Blob(n, t) for n, t in sorted(self.t.items()) if n.startswith(prefix)]
        return out[:limit]

    def delete(self, name: str) -> None:
        self.deleted.append(name)
        del self.t[name]


def run(c: Any, name: str, **kw: Any) -> dict[str, Any]:
    cfg = {
        **config.load("autoclean.yaml"),
    }
    cfg["rules"] = {**cfg["rules"], name: {**cfg["rules"][name], "mode": "apply"}}
    return {r["rule"]: r for r in ac.run_all(c.db, NOW, cfg=cfg, **kw)}[name]


def test_orphan_state_deletes_old_blobs_and_keeps_fresh_ones_and_snapshots() -> None:
    c = ctx()
    b = FakeBlobs(
        {
            "poller-state/old": 31,
            "poller-state/fresh": 1,
            "crawler-state/stable-page": 60,  # changed rarely: inside its 90-day window
            "crawler-state/dead": 100,
            "2026-01-01/reports.parquet": 300,  # never touched
        }
    )
    r = run(c, "orphan_state", snapshots=b)
    assert r["status"] == "ok" and r["changed"] == 2, r["note"]
    assert sorted(b.t) == [
        "2026-01-01/reports.parquet",
        "crawler-state/stable-page",
        "poller-state/fresh",
    ]
    assert run(c, "orphan_state", snapshots=b)["changed"] == 0


def test_partial_snapshots_are_reported_not_deleted() -> None:
    c = ctx()
    b = FakeBlobs(
        {
            "2026-11-01/reports.parquet": 13,  # no _SUCCESS, old: reported
            "2026-11-02/reports.parquet": 12,
            "2026-11-02/_SUCCESS": 12,
            "2026-11-13/reports.parquet": 1,  # no marker yet but too new to judge
            "poller-state/x": 1,
        }
    )
    r = run(c, "partial_snapshots", snapshots=b)
    assert json.loads(r["sample_ids"]) == ["2026-11-01"] and not b.deleted


class FakeWh:
    def __init__(self, have: set[str]) -> None:
        self.have = have

    def query(self, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        return [{"item_id": i} for i in params["ids"] if i in self.have]

    def execute(self, sql: str, params: dict[str, Any]) -> int:
        raise AssertionError("report only")


def test_raw_without_row_reports_objects_with_no_row() -> None:
    c = ctx()
    raw = FakeBlobs({"a.html": 1, "a.v1.html": 0.5, "b.html": 1, "c.pdf": 1, "d.html": 0.01})
    r = run(c, "raw_without_row", raw=raw, warehouse=FakeWh({"a"}))
    assert json.loads(r["sample_ids"]) == ["b", "c"]  # d is under an hour old, a has its row
    assert not raw.deleted


def test_export_writes_documents_and_success_last() -> None:
    from pipeline import snapshot
    from weft_core import graph

    c = ctx()
    graph.put(c.db, "documents", {"id": "d1", "url": "u"}, NOW.isoformat())

    class Mem:
        def __init__(self) -> None:
            self.order: list[str] = []

        def write(self, path: str, data: bytes) -> None:
            self.order.append(path)
            if path.endswith("_SUCCESS"):
                self.counts = json.loads(data)

    m = Mem()
    snapshot.export(c, m)
    day = NOW.date().isoformat()
    assert f"{day}/documents.parquet" in m.order
    assert m.order[-1] == f"{day}/_SUCCESS" and m.counts["documents"] == 1
    assert m.counts["reports"] == 0  # an empty table is still counted, just not written
