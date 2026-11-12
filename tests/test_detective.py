"""Detective mode: predictions must cite claim groups, are checked only against later reports,
expire when due, and are served only when switched on."""

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


def pred(text: str, due: str, based_on: list[int]) -> dict[str, object]:
    return {
        "text": text,
        "expected_by": due,
        "confirm_if": "c",
        "refute_if": "r",
        "based_on": based_on,
    }


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
    assert log[0].prompt_template == "detective@1"


def test_check_uses_only_later_evidence_and_expires_due_predictions() -> None:
    db = db_with_story()
    m, _ = model(
        [
            json.dumps(
                {
                    "predictions": [
                        pred("Talks happen", "2026-11-20", [1]),
                        pred("Ceasefire", "2026-11-08", [1]),
                    ]
                }
            )
        ]
    )
    detective.predict(db, m, "st", T0)
    put_group(db, "g2", "Talks took place on Monday", T1)
    ps = {p["text"]: i + 1 for i, p in enumerate(detective.predictions(db, "st"))}
    verdict = {
        "results": [
            {"prediction": ps["Talks happen"], "verdict": "supported", "evidence": [1, 2]},
            {"prediction": ps["Ceasefire"], "verdict": "contradicted", "evidence": []},
        ]
    }
    m2, _ = model([json.dumps(verdict)])
    assert detective.check(db, m2, "st", T2) == 2
    by = {p["text"]: p for p in detective.predictions(db, "st")}
    # groups are listed newest first, so 1 is g2 (later) and 2 is g1 (earlier, not evidence)
    assert by["Talks happen"]["status"] == "supported" and by["Talks happen"]["evidence"] == ["g2"]
    assert by["Ceasefire"]["status"] == "expired"  # verdict without evidence dropped; now past due
    card = detective.scorecard(db, "st")
    assert card["hit_rate"] == 1.0 and "Speculation" in card["disclaimer"]


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
