"""Detective mode: predictions must cite claim groups and carry a probability, are resolved by a
fixed rule over later reports (never by a model), expire when due, are scored by Brier, and are
served only when switched on."""

import json

import pytest
from fastapi.testclient import TestClient

from services.api.app import create_app
from tests.test_pipeline import model
from weft_core import detective, graph, store
from weft_core.store import local_db

T0, T1, T2 = "2026-11-06T00:00:00+00:00", "2026-11-07T00:00:00+00:00", "2026-11-09T00:00:00+00:00"


def db_with_story() -> store.Neo4jDb:
    db = local_db()
    store.create_story(db, "st", "st", "Story")
    graph.put(db, "events", {"id": "e", "story_id": "st", "first_seen": T0, "centroid": [1.0]}, T0)
    put_group(db, "g1", "Talks are scheduled for next week", T0)
    return db


def put_group(db: store.Neo4jDb, gid: str, label: str, at: str) -> None:
    graph.put(
        db,
        "claim_groups",
        {"id": gid, "event_id": "e", "label": label, "perspectives": ["IL"], "n_reports": 2},
        at,
    )


def pred(
    text: str, due: str, based_on: list[int], p: float = 0.7, confirm: str = "c", refute: str = "r"
) -> dict[str, object]:
    return {
        "text": text,
        "probability": p,
        "expected_by": due,
        "confirm_if": confirm,
        "refute_if": refute,
        "based_on": based_on,
    }


def later_reports(db: store.Neo4jDb, gid: str, when: str, sources: list[tuple[str, str]]) -> None:
    for i, (src, persp) in enumerate(sources):
        rid = f"{gid}-r{i}"
        graph.put(
            db,
            "reports",
            {
                "id": rid,
                "source_id": src,
                "perspective": persp,
                "story_id": "st",
                "event_id": "e",
                "published_at": when,
            },
            when,
        )
        graph.put(
            db,
            "claims",
            {
                "id": f"{rid}-c",
                "report_id": rid,
                "event_id": "e",
                "group_id": gid,
                "text": "x",
                "start_char": 0,
                "end_char": 1,
            },
            when,
        )


def test_predictions_need_citations_and_a_bounded_date() -> None:
    db = db_with_story()
    out = json.dumps(
        {
            "predictions": [
                pred("Talks happen", "2026-11-20", [1]),
                pred("No citation", "2026-11-20", []),
                pred("Bad index", "2026-11-20", [9]),
                pred("Too far", "2027-06-01", [1]),
                pred("Bad date", "soon", [1]),
            ]
        }
    )
    m, log = model([out])
    assert detective.predict(db, m, "st", T0) == 1
    (p,) = detective.predictions(db, "st")
    assert p["text"] == "Talks happen" and p["based_on"] == ["g1"] and p["status"] == "open"
    assert p["probability"] == 0.7
    assert log[0].prompt_template == "detective@2"


def test_rule_resolves_with_later_multi_outlet_evidence_and_expires_due_ones() -> None:
    from weft_core.nlp import LexicalNli

    db = db_with_story()
    m, _ = model(
        [
            json.dumps(
                {
                    "predictions": [
                        pred("Talks happen", "2026-11-20", [1], 0.8, "talks took place monday"),
                        pred("Ceasefire", "2026-11-08", [1], 0.6, "ceasefire agreed"),
                        pred("Lone outlet", "2026-11-20", [1], 0.3, "port reopened today"),
                    ]
                }
            )
        ]
    )
    detective.predict(db, m, "st", T0)
    put_group(db, "g2", "Talks took place on Monday", T1)
    later_reports(db, "g2", T1, [("a", "IL"), ("b", "IR")])  # two outlets, two perspectives
    put_group(db, "g3", "Port reopened today", T1)
    later_reports(db, "g3", T1, [("a", "IL")])  # one outlet: not enough
    assert detective.check(db, LexicalNli(), "st", T2) == 2
    by = {p["text"]: p for p in detective.predictions(db, "st")}
    assert by["Talks happen"]["status"] == "supported" and by["Talks happen"]["evidence"] == ["g2"]
    assert by["Ceasefire"]["status"] == "expired"  # nothing matched and now past due
    assert by["Lone outlet"]["status"] == "open"
    card = detective.scorecard(db, "st")
    # Brier: supported at 0.8 -> 0.04; expired at 0.6 -> 0.36
    assert card["resolved"] == 2 and abs(card["brier"] - 0.2) < 1e-9 and card["brier_coin"] == 0.25
    assert "Speculation" in card["disclaimer"] and card["calibration"]


def test_at_most_five_open_predictions_per_story() -> None:
    db = db_with_story()
    five = [pred(f"P{i}", "2026-11-20", [1]) for i in range(3)]
    m, _ = model(
        [
            json.dumps({"predictions": five}),
            json.dumps(
                {"predictions": five[:1] + [pred(f"Q{i}", "2026-11-20", [1]) for i in range(3)]}
            ),
        ]
    )
    assert detective.predict(db, m, "st", T0) == 3
    assert detective.predict(db, m, "st", T1) == 2  # room for two more only


def test_api_serves_detective_only_when_on_and_story_public(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = db_with_story()
    c = TestClient(create_app(db, "t0k"))
    assert c.get("/v1/stories/st/detective").status_code == 404
    monkeypatch.setenv("DETECTIVE", "on")
    assert c.get("/v1/stories/st/detective").status_code == 404  # story not public
    store.set_public(db, "st", True)
    assert c.get("/v1/stories/st/detective").json()["predictions"] == []
