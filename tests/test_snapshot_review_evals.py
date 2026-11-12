import io
import json
from typing import Any

import pyarrow.parquet as pq

from evals.gate import check, prompt_versions
from evals.run import HERE, chrf, run_all
from pipeline import review_sample, snapshot
from pipeline.ctx import Ctx
from weft_core import config, graph, review
from weft_core.nlp import HashEmbedder, LexicalNli, Nlp, RegexEntities, StopwordLangId
from weft_core.store import local_db


def ctx() -> Ctx:
    db = local_db()
    graph.init(db)
    return Ctx(
        db,
        config.pipeline(),
        Nlp(HashEmbedder(), StopwordLangId(), RegexEntities(), LexicalNli()),
        lambda r: "",
        None,
        "2026-11-06T12:00:00+00:00",
    )


def report(c: Ctx, i: str, event: str, at: str) -> None:
    graph.put(
        c.db,
        "reports",
        {
            "id": i,
            "url": f"u{i}",
            "source_id": "s",
            "perspective": "IL",
            "story_id": "st",
            "event_id": event,
            "type": "news",
            "title": f"t{i}",
            "summary": "x",
        },
        at,
    )


class Mem:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    def write(self, path: str, data: bytes) -> None:
        self.files[path] = data


def test_snapshot_exports_parquet_and_diff_sees_moves_and_new() -> None:
    c = ctx()
    t0, t1 = "2026-11-05T00:00:00+00:00", "2026-11-06T06:00:00+00:00"
    graph.put(
        c.db, "events", {"id": "e1", "story_id": "st", "first_seen": t0, "centroid": [1.0]}, t0
    )
    graph.put(
        c.db, "events", {"id": "e2", "story_id": "st", "first_seen": t0, "centroid": [1.0]}, t0
    )
    report(c, "r1", "e1", t0)
    report(c, "r2", "e2", t0)
    report(c, "r1", "e2", t1)  # regroup moved r1
    report(c, "r3", "e2", t1)
    c.db.execute("MATCH (n:Event {id: 'e1'}) SET n.valid_to=?", (t1,))  # e1 merged away
    d = snapshot.diff(c, "2026-11-05T12:00:00+00:00")
    assert d["new_reports"] == ["r3"] and d["moved_reports"] == ["r1"]
    assert d["merged_events"] == ["e1"]
    sink = Mem()
    assert snapshot.run(c, sink) == 3
    rows = pq.read_table(io.BytesIO(sink.files["2026-11-06/reports.parquet"])).to_pylist()
    assert {r["id"] for r in rows} == {"r1", "r2", "r3"} and all(
        r["valid_to"] is None for r in rows
    )
    assert json.loads(
        c.db.execute("MATCH (n:DailyDiff) RETURN n.payload AS payload")[0]["payload"]
    )["new_reports"] == ["r3"]


def test_review_sample_is_deterministic_rated_and_measured() -> None:
    c = ctx()
    for i in range(30):
        report(c, f"r{i}", "e", "2026-11-06T01:00:00+00:00")
    assert review_sample.run(c) == 1  # 1% of 30 rounds up to 1 item
    assert review_sample.run(c) == 0  # same night again queues nothing new
    (item,) = review.open_items(c.db)
    assert item["kind"] == "merge"
    assert review.rate(c.db, item["id"], "good", "ed") and not review.rate(
        c.db, "nope", "good", "ed"
    )
    assert review.quality(c.db) == {"merge": {"rated": 1, "good_share": 1.0}}


def test_eval_gate_passes_now_and_fails_on_regression_or_prompt_bump() -> None:
    base = json.loads((HERE / "baseline.json").read_text())
    scores = run_all()
    assert check(base, scores, prompt_versions()) == []
    worse: dict[str, Any] = {**scores, "merges": {"f1": 0.5}}
    assert any("merges.f1" in e for e in check(base, worse, prompt_versions()))
    assert any("prompt versions" in e for e in check(base, scores, [*prompt_versions(), "x-y@2"]))


def test_chrf() -> None:
    assert chrf("abc def", "abc def") == 1.0 and chrf("zzz", "abc") == 0.0
