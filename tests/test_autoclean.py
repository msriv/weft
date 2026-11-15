import json
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

import pytest

from pipeline import autoclean as stage
from pipeline.ctx import Ctx
from weft_core import autoclean as ac
from weft_core import (
    autoclean_rules,  # noqa: F401  (registers the rules)
    config,
    graph,
)
from weft_core.nlp import HashEmbedder, LexicalNli, Nlp, RegexEntities, StopwordLangId
from weft_core.store import local_db

NOW = datetime(2026, 11, 14, 6, 0, tzinfo=UTC)
CFG = config.load("autoclean.yaml")


class FakeDb:
    """Enough of `Db` for the framework: records statements, answers the snapshot query."""

    def __init__(self, snapshot: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.snapshot = snapshot

    def execute(self, query: str, args: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        self.calls.append((query, args))
        return [self.snapshot] if "stage: 'snapshot'" in query and self.snapshot else []

    def runs(self) -> list[dict[str, Any]]:
        return [a[0] for q, a in self.calls if "CREATE (n:AutocleanRun)" in q]


class Thing:
    """A rule over a counter: `todo` rows to fix, fixed by apply."""

    def __init__(self, todo: int, of: int | None = None, destructive: bool = False) -> None:
        self.todo, self.of, self.applied = todo, of, 0
        self.rule = ac.Rule("t", 3, self.match, self.apply, destructive)

    def match(self, env: ac.Env) -> ac.Match:
        return ac.Match(self.todo, self.of, [f"id{i}" for i in range(self.todo)])

    def apply(self, env: ac.Env) -> int:
        n, self.todo = self.todo, 0
        self.applied += n
        return n


def run(db: FakeDb, t: Thing, mode: str, good: bool = True, **conf: Any) -> dict[str, Any]:
    cfg = {"defaults": CFG["defaults"], "rules": {"t": {"mode": mode, **conf}}}
    rec = ac.run_rule(db, t.rule, cfg, run_id="r", now=NOW, snapshot_good=good)
    assert rec
    return rec


def test_dry_run_changes_nothing_and_logs_matches(capsys: pytest.CaptureFixture[str]) -> None:
    db, t = FakeDb(), Thing(30)
    rec = run(db, t, "dry_run")
    assert (rec["status"], rec["matched"], rec["changed"]) == ("dry_run", 30, 0)
    assert t.applied == 0 and len(json.loads(rec["sample_ids"])) == 20  # at most 20 sample ids
    stored = db.runs()[0]
    assert stored["rule"] == "t" and stored["rule_version"] == 3 and stored["mode"] == "dry_run"
    line = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert line["event"] == "autoclean_rule" and line["matched"] == 30


def test_rule_over_its_cap_aborts_and_alerts(capsys: pytest.CaptureFixture[str]) -> None:
    t = Thing(60, of=1000)  # 6% of 1000 > 5%
    rec = run(FakeDb(), t, "apply")
    assert rec["status"] == "aborted" and rec["changed"] == 0 and t.applied == 0
    line = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert line["severity"] == "ERROR" and line["event"] == "autoclean_aborted"
    assert run(FakeDb(), Thing(11), "apply", max_rows=10)["status"] == "aborted"
    assert run(FakeDb(), Thing(50, of=1000), "apply")["status"] == "ok"  # exactly 5% is fine


def test_dry_run_says_when_it_would_abort() -> None:
    rec = run(FakeDb(), Thing(60, of=1000), "dry_run")
    assert rec["status"] == "dry_run" and "would abort" in rec["note"]


def test_destructive_rule_needs_a_good_snapshot() -> None:
    t = Thing(5, destructive=True)
    rec = run(FakeDb(), t, "apply", good=False)
    assert rec["status"] == "skipped" and t.applied == 0
    assert run(FakeDb(), t, "apply", good=True)["changed"] == 5
    t2 = Thing(5)  # a repair, not a delete: no snapshot needed
    assert run(FakeDb(), t2, "apply", good=False)["changed"] == 5


def test_second_run_changes_nothing() -> None:
    t = Thing(7)
    assert run(FakeDb(), t, "apply")["changed"] == 7
    assert run(FakeDb(), t, "apply")["changed"] == 0


def test_disabled_rule_is_not_run() -> None:
    cfg = {"defaults": CFG["defaults"], "rules": {"t": {"enabled": False}}}
    t = Thing(1)
    assert ac.run_rule(FakeDb(), t.rule, cfg, run_id="r", now=NOW, snapshot_good=True) is None


def test_failing_rule_is_recorded_and_does_not_stop_the_others() -> None:
    def boom(env: ac.Env) -> ac.Match:
        raise RuntimeError("bq down")

    bad = ac.Rule("bad", 1, boom, lambda env: 0)
    rec = ac.run_rule(FakeDb(), bad, CFG, run_id="r", now=NOW, snapshot_good=True)
    assert rec and rec["status"] == "failed" and "bq down" in rec["note"]


def test_snapshot_must_be_ok_and_under_36_hours_old() -> None:
    def ok(ended: datetime, status: str = "ok") -> FakeDb:
        return FakeDb({"status": status, "ended_at": ended.isoformat()})

    assert ac.snapshot_ok(ok(NOW - timedelta(hours=35)), NOW)
    assert not ac.snapshot_ok(ok(NOW - timedelta(hours=37)), NOW)
    assert not ac.snapshot_ok(ok(NOW - timedelta(hours=1), "failed"), NOW)
    assert not ac.snapshot_ok(FakeDb(), NOW)  # no snapshot run at all


def test_batched_loops_until_a_pass_changes_less_than_a_batch() -> None:
    class D:
        passes: ClassVar[list[int]] = [ac.BATCH, ac.BATCH, 17]

        def execute(self, q: str, a: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
            assert f"LIMIT {ac.BATCH}" in q
            return [{"n": self.passes.pop(0)}]

    assert ac.batched(D(), "MATCH (n) WITH n LIMIT {batch} DELETE n RETURN count(*) AS n") == (
        2 * ac.BATCH + 17
    )


def test_every_rule_has_a_config_entry_and_ships_in_dry_run() -> None:
    assert ac.RULES, "no rules registered"
    for name in ac.RULES:
        assert name in CFG["rules"], f"{name} needs an entry in config/autoclean.yaml"
        assert ac.settings(CFG, name)["mode"] == "dry_run", f"{name} must ship in dry_run"


# --- rules that need Neo4j (CI runs a throwaway server) ---------------------------------------


def ctx() -> Ctx:
    db = local_db()
    graph.init(db)
    return Ctx(
        db,
        config.pipeline(),
        Nlp(HashEmbedder(), StopwordLangId(), RegexEntities(), LexicalNli()),
        lambda r: "",
        None,
        NOW.isoformat(),
    )


def apply_cfg(*names: str, **extra: Any) -> dict[str, Any]:
    rules = {n: {**CFG["rules"].get(n, {}), "mode": "apply", **extra.get(n, {})} for n in names}
    return {**CFG, "rules": {**CFG["rules"], **rules}}


def test_stale_batch_runs_are_abandoned_and_fresh_ones_kept() -> None:
    c = ctx()
    old, fresh = (NOW - timedelta(hours=4)).isoformat(), (NOW - timedelta(hours=1)).isoformat()
    for run_id, at in (("a", old), ("b", fresh)):
        c.db.execute(
            "CREATE (:BatchRun {run_id: ?, stage: 'claims', started_at: ?, status: 'running'})",
            (run_id, at),
        )
    cfg = apply_cfg("stale_batch_runs")
    ac.run_all(c.db, NOW, cfg=cfg)
    status = {
        r["id"]: r["s"]
        for r in c.db.execute("MATCH (n:BatchRun) RETURN n.run_id AS id, n.status AS s")
    }
    assert status == {"a": "abandoned", "b": "running"}
    again = {r["rule"]: r for r in ac.run_all(c.db, NOW, cfg=cfg)}
    assert again["stale_batch_runs"]["changed"] == 0


def test_claims_skipped_is_stored_and_counted_per_beat() -> None:
    c = ctx()
    c.db.execute("CREATE (:Story {id: 'st', beat_id: 'bt'})")
    old, new = (NOW - timedelta(days=3)).isoformat(), (NOW - timedelta(hours=5)).isoformat()
    for i, (at, claimed) in {"old": (old, None), "done": (old, 1), "new": (new, None)}.items():
        graph.put(
            c.db,
            "reports",
            {"id": i, "story_id": "st", "published_at": at, "claims_extracted": claimed},
            at,
        )
    recs = {r["rule"]: r for r in ac.run_all(c.db, NOW, cfg=apply_cfg("claims_skipped"))}
    r = recs["claims_skipped"]
    assert r["changed"] == 1 and json.loads(r["note"].split(": ", 1)[1]) == {"bt": 1}
    got = {
        x["id"]: x["v"]
        for x in c.db.execute("MATCH (n:Report) RETURN n.id AS id, n.claims_extracted AS v")
    }
    assert got == {"old": 0, "done": 1, "new": None}  # recent ones still wait their turn


class FakeWarehouse:
    def __init__(self, rows: list[dict[str, Any]], n: int = 0) -> None:
        self.rows, self.n = rows, n
        self.sql: list[str] = []

    def query(self, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        self.sql.append(sql)
        return [{"n": self.n}] if "COUNT(*)" in sql else self.rows

    def execute(self, sql: str, params: dict[str, Any]) -> int:
        self.sql.append(sql)
        assert params["cutoff"] == NOW - timedelta(days=30)
        return self.n


def test_model_call_inputs_nulls_only_the_text_past_retention() -> None:
    c = ctx()
    wh = FakeWarehouse([{"id": "h1"}], n=4)
    recs = {
        r["rule"]: r
        for r in ac.run_all(c.db, NOW, warehouse=wh, cfg=apply_cfg("model_call_inputs"))
    }
    r = recs["model_call_inputs"]
    assert r["changed"] == 4 and json.loads(r["sample_ids"]) == ["h1"]
    update = next(s for s in wh.sql if s.startswith("UPDATE `{ds}.model_calls`"))
    assert "SET input = NULL" in update and "called_at < @cutoff" in update
    for kept in ("input_hash", "model", "revision", "seed", "output", "prompt_template"):
        assert f"{kept} =" not in update  # rule 4 columns are never touched


UNPLACED = {
    "source_id": "s1",
    "url": "https://x/a",
    "published_at": None,
    "fetched_at": NOW - timedelta(hours=5),
    "text_hash": "h",
    "title": "T",
    "summary": "S",
}


def test_unplaced_items_are_republished_once_and_not_again_when_placed() -> None:
    c = ctx()
    c.db.execute(
        "CREATE (:Source {id: 's1', status: 'active', type: 'news', homepage: 'https://x',"
        " feeds: '[]', sitemaps: '[]', languages: '[\"en\"]', min_interval: 10.0})"
    )
    graph.put(c.db, "reports", {"id": "placed", "source_id": "s1"}, NOW.isoformat())
    wh = FakeWarehouse(
        [
            {**UNPLACED, "item_id": "lost"},
            {**UNPLACED, "item_id": "placed"},
            {**UNPLACED, "item_id": "gone", "source_id": "removed"},
        ]
    )
    sent: list[tuple[str, dict[str, Any]]] = []
    cfg = apply_cfg("unplaced_items")
    recs = ac.run_all(c.db, NOW, warehouse=wh, publish=lambda t, m: sent.append((t, m)), cfg=cfg)
    assert [r["changed"] for r in recs if r["rule"] == "unplaced_items"] == [1]
    assert sent[0][0] == "items-extracted" and sent[0][1]["item_id"] == "lost"
    # the worker places it: the next run finds nothing to send
    graph.put(c.db, "reports", {"id": "lost", "source_id": "s1"}, NOW.isoformat())
    sent.clear()
    ac.run_all(c.db, NOW, warehouse=wh, publish=lambda t, m: sent.append((t, m)), cfg=cfg)
    assert not sent


def test_unplaced_items_cap_stops_a_mass_republish() -> None:
    c = ctx()
    c.db.execute(
        "CREATE (:Source {id: 's1', status: 'active', type: 'news', homepage: 'https://x',"
        " feeds: '[]', sitemaps: '[]', languages: '[\"en\"]', min_interval: 10.0})"
    )
    wh = FakeWarehouse([{**UNPLACED, "item_id": f"i{i}"} for i in range(6)])
    sent: list[Any] = []
    cfg = apply_cfg("unplaced_items", unplaced_items={"max_rows": 5})
    recs = ac.run_all(c.db, NOW, warehouse=wh, publish=lambda t, m: sent.append(m), cfg=cfg)
    assert [r["status"] for r in recs if r["rule"] == "unplaced_items"] == ["aborted"]
    assert not sent


def test_stage_runs_in_dry_run_and_changes_nothing() -> None:
    c = ctx()
    c.db.execute(
        "CREATE (:BatchRun {run_id: 'a', stage: 'claims', started_at: ?, status: 'running'})",
        ((NOW - timedelta(days=1)).isoformat(),),
    )
    c.warehouse = FakeWarehouse([])
    assert stage.run(c) == 0
    assert c.db.execute("MATCH (n:BatchRun) RETURN n.status AS s") == [{"s": "running"}]
    runs = c.db.execute("MATCH (n:AutocleanRun) RETURN n.rule AS r, n.status AS s")
    assert {r["r"] for r in runs} == set(ac.RULES) and {r["s"] for r in runs} == {"dry_run"}
