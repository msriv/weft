import json
from datetime import UTC, datetime, timedelta

import pytest

from pipeline import anomalies, weights
from pipeline.ctx import Ctx
from weft_core import config, graph, store
from weft_core.nlp import HashEmbedder, LexicalNli, Nlp, RegexEntities, StopwordLangId
from weft_core.store import local_db

NOW = datetime(2026, 11, 6, 12, tzinfo=UTC)


def make() -> Ctx:
    db = local_db()
    graph.init(db)
    for i in range(6):
        d = f"s{i}.{'il' if i % 2 else 'ir'}"
        store.register_source(db, domain=d, name=d, homepage=f"https://{d}", feeds=["f"], via="t")
    t0 = (NOW - timedelta(hours=20)).isoformat()
    graph.put(db, "events", {"id": "e", "story_id": "st", "first_seen": t0, "centroid": [1.0]}, t0)
    for i in range(6):
        d = f"s{i}.{'il' if i % 2 else 'ir'}"
        graph.put(
            db,
            "reports",
            {
                "id": f"r{i}",
                "url": f"u{i}",
                "source_id": d.replace(".", "-"),
                "perspective": "IL" if i % 2 else "IR",
                "story_id": "st",
                "event_id": "e",
                "published_at": t0,
                "type": "news",
                "title": "t",
                "summary": "x",
            },
            t0,
        )
    for i, v in ((0, 40.0), (1, 10.0)):
        graph.put(
            db,
            "figures",
            {
                "id": f"f{i}",
                "report_id": f"r{i}",
                "event_id": "e",
                "kind": "number",
                "quantity": "missile",
                "value": v,
                "text": f"{v} missiles",
                "start_char": 0,
                "end_char": 5,
            },
            t0,
        )
    for i in (0, 1):  # both figures sit in claims of the same group
        graph.put(
            db,
            "claims",
            {
                "id": f"c{i}",
                "report_id": f"r{i}",
                "event_id": "e",
                "group_id": "g",
                "text": "missiles",
                "start_char": 0,
                "end_char": 50,
            },
            t0,
        )
    nlp = Nlp(HashEmbedder(), StopwordLangId(), RegexEntities(), LexicalNli())
    return Ctx(
        db,
        config.pipeline(),
        nlp,
        lambda r: f"{r['id']} alpha beta gamma delta epsilon {r['id']} zeta",
        None,
        NOW.isoformat(),
    )


def test_reconcile_appears_changes_and_withdraws_with_log() -> None:
    c = make()
    c.rules = {**c.rules, "promotion": {"enabled": False}}
    assert anomalies.run(c) == 1
    (a,) = graph.select(c.db, "anomalies")
    assert a["rule"] == "numbers_differ" and a["status"] == "active" and a["rule_version"] == 3
    assert a["evidence_ids"] and a["inputs"]["threshold"] == 0.2
    assert anomalies.run(c) == 0  # nothing changed: no new version, no log line
    c.now = (NOW + timedelta(days=1)).isoformat()
    c.rules = {
        **c.rules,
        "version": 4,
        "rules": {
            **c.rules["rules"],
            "numbers_differ": {"enabled": True, "min_relative_difference": 0.9},
        },
    }  # threshold raised: 75% no longer enough
    assert anomalies.run(c) == 1
    assert graph.get(c.db, "anomalies", a["id"])["status"] == "withdrawn"  # type: ignore[index]
    log = c.db.execute(
        "MATCH (n:AnomalyLog) RETURN n.change AS change, n.rule_version AS rule_version "
        "ORDER BY n.seq"
    )
    assert [(r["change"], r["rule_version"]) for r in log] == [("appeared", 3), ("withdrawn", 4)]
    assert c.db.execute("MATCH (n:Anomaly) RETURN count(n) AS n")[0]["n"] == 2  # history kept


def test_rule_stays_provisional_until_owner_labels_show_it_is_useful() -> None:
    from weft_core import feedback

    c = make()
    anomalies.run(c)
    (a,) = graph.select(c.db, "anomalies")
    assert a["status"] == "provisional"  # no labels yet
    with pytest.raises(ValueError):
        feedback.label(c.db, a["id"], "true")
    for i in range(20):  # the eval set: 20 labelled anomalies of this rule
        c.db.execute(
            "CREATE (:AnomalyFeedback {anomaly_id: ?, rule: 'numbers_differ', rule_version: 3, "
            "label: ?})",
            (f"x{i}", "useful" if i < 14 else "not_useful"),
        )
    assert feedback.precision(c.db)[0]["precision"] == 0.7
    anomalies.run(c)
    assert graph.get(c.db, "anomalies", a["id"])["status"] == "active"  # type: ignore[index]
    feedback.label(c.db, a["id"], "wrong_grouping")
    assert feedback.precision(c.db)[0]["labelled"] == 21


def test_omission_ids_differ_per_perspective() -> None:
    from weft_core.rules import Anomaly

    def omit(p: str) -> Anomaly:
        return Anomaly("omission", 3, "claim_group", "g", "s", "e", "", {}, [], key=p)

    assert omit("IL").id != omit("IR").id


def test_unhealthy_feed_marks_source_and_weights_stage_writes_rows() -> None:
    c = make()
    store.set_health(c.db, ["s0-ir"])
    rows = {
        r["id"]: r["healthy"]
        for r in c.db.execute("MATCH (n:Source) RETURN n.id AS id, n.healthy AS healthy")
    }
    assert rows["s0-ir"] == 0 and rows["s1-il"] == 1
    assert weights.run(c) == 6
    w = store.nodes(c.db, "SourceWeight", "MATCH (n:SourceWeight {source_id: 's1-il'}) RETURN n")[0]
    assert w["insufficient"] == 1 and w["weight"] == 0.5  # one report: neutral, not hidden
    assert "silent_edit_count" in json.loads(w["factors"])


def test_anomaly_on_an_aged_out_event_is_kept_not_withdrawn() -> None:
    c = make()
    c.rules = {**c.rules, "promotion": {"enabled": False}}
    assert anomalies.run(c) == 1
    (a,) = graph.select(c.db, "anomalies")
    c.now = (NOW + timedelta(days=60)).isoformat()  # event far outside the regroup window
    assert anomalies.run(c) == 0
    assert graph.get(c.db, "anomalies", a["id"])["status"] == "active"  # type: ignore[index]
