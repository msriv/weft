"""World directions (D22, #117-#130). Placeholder text only; never real news."""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from services.api.app import create_app
from weft_core import beats, directions, discovery, graph, store
from weft_core.models import ModelCall, ModelClient
from weft_core.nlp import HashEmbedder, LexicalNli
from weft_core.store import local_db

NOW = datetime(2026, 11, 13, 12, tzinfo=UTC)
CFG = directions.cfg()


def db_with_beats() -> store.Neo4jDb:
    db = local_db()
    graph.init(db)
    discovery.seed_beats(db)
    for b in store.beats(db):
        beats.ensure_story(db, b)
    return db


def test_domains_come_from_parties_and_beats_capped_and_idempotent() -> None:
    db = db_with_beats()
    first = directions.build_domains(db, NOW, CFG)
    again = directions.build_domains(db, NOW, CFG)
    assert [d["id"] for d in first] == [d["id"] for d in again]  # idempotent
    ids = {d["id"] for d in first}
    assert len(ids) == CFG["domains"]["max_active"] == 12
    assert {f"politics:{b['id']}" for b in store.beats(db)} <= ids  # every beat keeps one
    assert "currency:IL" in ids and directions.currency_of("IL") == "ILS"
    total = directions.domains(db)
    assert len(total) == 16 and sum(d["status"] == "dormant" for d in total) == 4


def group(i: str, label: str, days_old: float = 1) -> dict[str, Any]:
    return {"id": i, "label": label, "valid_from": (NOW - timedelta(days=days_old)).isoformat()}


def reps(n: int, prefix: str) -> list[dict[str, Any]]:
    return [
        {"id": f"{prefix}{k}", "s": f"s{k}", "p": "IL" if k % 2 else "IR", "o": f"{prefix}{k}"}
        for k in range(n)
    ]


@pytest.mark.parametrize(
    ("facet", "label"),
    [
        ("currency", "The shekel fell against the dollar"),
        ("economy", "Inflation rose to a new high"),
        ("government", "The cabinet met after a minister resigned"),
        ("politics", "The opposition called a vote"),
    ],
)
def test_drivers_need_the_facet_lexicon_the_subject_and_a_pool_of_five(
    facet: str, label: str
) -> None:
    dom = {"id": f"{facet}:IL", "subject": "IL", "subject_kind": "country", "facet": facet}
    groups = [group(f"g{i}", f"{label} {i}") for i in range(5)] + [group("x", "Weather was warm")]
    rs = {g["id"]: reps(4, g["id"]) for g in groups}
    names = {r["id"]: {"IL"} for g in groups for r in rs[g["id"]][:2]}  # half name Israel
    out = directions.pick_drivers(dom, groups, rs, names, NOW, CFG)
    assert len(out) == 5 and "x" not in {d["group_id"] for d in out}
    assert out[0]["n_origins"] == 4
    # four groups only: below the pool, no drivers
    assert directions.pick_drivers(dom, groups[1:], rs, names, NOW, CFG) == []
    # a quarter naming the country is not enough
    few = {r["id"]: {"IL"} for g in groups for r in rs[g["id"]][:1]}
    assert directions.pick_drivers(dom, groups, rs, few, NOW, CFG) == []


def model(answer: dict[str, Any]) -> tuple[ModelClient, list[ModelCall]]:
    log: list[ModelCall] = []

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(answer)}}]})

    m = ModelClient(base_url="http://m", api_key="k", model="q", revision="r1", log=log.append,
                    transport=httpx.MockTransport(handler))  # fmt: skip
    return m, log


def seed_drivers(db: store.Neo4jDb, dom_id: str, n: int = 6) -> None:
    db.execute(
        "MERGE (n:Domain {id: ?}) SET n.subject='IL', n.subject_kind='country', "
        "n.facet='government', n.label='Aldoria: government', n.status='active'",
        (dom_id,),
    )
    for i in range(n):
        gid = f"g{i}"
        graph.put(db, "claim_groups", {"id": gid, "event_id": "e", "label": f"Minister {i} resigned",
                                       "perspectives": ["IL"], "n_reports": 1})  # fmt: skip
        graph.put(db, "reports", {"id": f"r{i}", "source_id": f"s{i}", "perspective": "IL",
                                  "story_id": "st", "event_id": "e"})  # fmt: skip
        graph.put(db, "claims", {"id": f"c{i}", "report_id": f"r{i}", "event_id": "e",
                                 "group_id": gid, "text": "t"})  # fmt: skip
        db.execute(
            "MERGE (n:DomainDriver {domain_id: ?, group_id: ?}) SET n.day=?, n.score=?, "
            "n.n_origins=1, n.perspectives='[\"IL\"]'",
            (dom_id, gid, NOW.date().isoformat(), 10 - i),
        )


def spec(**kw: Any) -> dict[str, Any]:
    base = {
        "question": "Will the cabinet hold a confidence vote?",
        "probability": 0.4,
        "deadline": (NOW + timedelta(days=30)).date().isoformat(),
        "confirm_if": "The cabinet held a confidence vote.",
        "refute_if": "No confidence vote was held.",
        "reference_class": "Confidence vote within a month",
        "based_on": [1, 2],
    }
    return base | kw


def test_generation_keeps_only_cited_bounded_verdict_free_questions_and_logs_calls() -> None:
    db = local_db()
    graph.init(db)
    seed_drivers(db, "government:IL")
    bad = [
        spec(question="Uncited", based_on=[1]),
        spec(question="Too soon", deadline=(NOW + timedelta(days=2)).date().isoformat()),
        spec(question="Will reports say it is confirmed?"),
    ]
    m, log = model({"speculations": [spec(), *bad]})
    [d] = directions.domains(db)
    made = directions.generate(db, m, HashEmbedder(), d, NOW.isoformat(), CFG)
    assert made == 1 and len(log) == 1 and log[0].prompt_template == "directions@1"
    [p] = directions.speculations(db, "government:IL")
    assert p["origin"] == "model" and p["model"] == "q@r1" and len(p["based_on"]) == 2
    [d] = directions.domains(db)
    assert (d["proposed"], d["dropped"]) == (4, 3)
    # called again the same day: the 3-day spacing holds and no call is made
    assert (
        directions.generate(db, m, HashEmbedder(), d, NOW.isoformat(), CFG) == 0 and len(log) == 1
    )


def test_generation_skips_a_domain_over_budget() -> None:
    db = local_db()
    graph.init(db)
    seed_drivers(db, "government:IL")
    m, log = model({"speculations": [spec()]})
    [d] = directions.domains(db)
    assert directions.generate(db, m, HashEmbedder(), d, NOW.isoformat(), CFG, lambda _: False) == 0
    assert log == []


def test_numeric_questions_resolve_from_the_datum_and_expired_is_a_miss() -> None:
    db = local_db()
    graph.init(db)
    db.execute(
        "MERGE (n:Domain {id: 'currency:IL'}) SET n.subject='IL', n.subject_kind='country', "
        "n.facet='currency', n.label='x', n.status='active', n.currency='ILS'"
    )
    start = NOW.date() - timedelta(days=200)
    for k in range(200):
        db.execute(
            "MERGE (n:SeriesPoint {series_id: 'EUR/ILS', day: ?}) SET n.value=?, n.source='test'",
            ((start + timedelta(days=k)).isoformat(), 4.0 + 0.001 * k),
        )
    assert directions.template_questions(db, NOW.isoformat()) == 1
    assert directions.template_questions(db, NOW.isoformat()) == 1  # same week: same question
    [p] = directions.speculations(db, "currency:IL")
    assert p["origin"] == "template" and p["probability"] == 0.98  # a rising series
    later = NOW + timedelta(days=31)
    db.execute(
        "MERGE (n:SeriesPoint {series_id: 'EUR/ILS', day: ?}) SET n.value=5.0, n.source='test'",
        ((NOW + timedelta(days=30)).date().isoformat(),),
    )
    [d] = directions.domains(db)
    assert directions.resolve(db, LexicalNli(), d, later.isoformat(), CFG) == 1
    [p] = directions.speculations(db, "currency:IL")
    assert p["status"] == "supported" and p["evidence"][0]["value"] == 5.0
    assert directions.outcome(p) == "The published rate says yes"
    # a claim question past its deadline with no matching report: expired, scored as a miss
    seed_drivers(db, "government:IL", 1)
    db.execute(
        "CREATE (:Prediction {id: 'q', domain_id: 'government:IL', text: 't', probability: 0.3, "
        "expected_by: '2026-11-20', confirm_if: 'a', refute_if: 'b', made_at: ?, status: 'open', "
        "kind: 'claim', evidence: '[]', based_on: '[]', drivers: '[]'})",
        (NOW.isoformat(),),
    )
    gov = next(x for x in directions.domains(db) if x["id"] == "government:IL")
    directions.resolve(db, LexicalNli(), gov, later.isoformat(), CFG)
    [q] = directions.speculations(db, "government:IL")
    assert q["status"] == "expired" and "counts as a miss" in directions.outcome(q)
    assert directions.outcome(q | {"status": "supported"}) == "Later reports say yes"


def test_scores_match_a_hand_computed_fixture() -> None:
    preds = [
        {"id": "a", "status": "supported", "probability": 0.8, "reference_class": "x"},
        {"id": "b", "status": "contradicted", "probability": 0.6, "reference_class": "x"},
        {"id": "c", "status": "expired", "probability": 0.1, "base_rate": 0.4},
        {"id": "d", "status": "open", "probability": 0.5},
    ]
    s = directions.score(preds, min_base_n=2)
    # (0.2^2 + 0.6^2 + 0.1^2) / 3
    assert s["brier"] == pytest.approx((0.04 + 0.36 + 0.01) / 3)
    # base rates: class x has 1 yes of 2 (0.5) for a and b; c has its own 0.4
    assert s["brier_base_rate"] == pytest.approx((0.25 + 0.25 + 0.16) / 3)
    assert s["counts"] == {"open": 1, "supported": 1, "contradicted": 1, "expired": 1}
    assert [c["decile"] for c in s["calibration"]] == [[0.1, 0.2], [0.6, 0.7], [0.8, 0.9]]
    split = directions.score_split(
        [p | {"domain_id": "economy:IL", "origin": "model"} for p in preds],
        {"economy:IL": "economy"},
    )
    assert split["by_origin"]["model"]["resolved"] == 3 and "economy" in split["by_facet"]


def test_series_fetch_is_one_request_with_backfill() -> None:
    db = local_db()
    graph.init(db)
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(str(req.url))
        return httpx.Response(200, json={"rates": {"2026-11-12": {"INR": 98.1}}})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    assert directions.fetch_series(db, http, "INR", NOW.date()) == 1
    assert len(seen) == 1 and "from=EUR&to=INR" in seen[0] and "2025-10" in seen[0]
    assert directions.series(db, "EUR/INR") == [("2026-11-12", 98.1)]


def test_api_serves_directions_only_with_the_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    db = db_with_beats()
    directions.build_domains(db, NOW, CFG)
    c = TestClient(create_app(db, "t"))
    monkeypatch.delenv("DETECTIVE", raising=False)
    assert c.get("/v1/directions").status_code == 404
    monkeypatch.setenv("DETECTIVE", "on")
    body = c.get("/v1/directions").json()
    assert body["notice"] == "Model speculation, not reporting" and len(body["domains"]) == 12
    cur = next(d for d in body["domains"] if d["facet"] == "currency")
    assert cur["not_advice"] == "Not financial advice." and "track_record" in cur
    assert c.get(f"/v1/directions/{cur['id']}").json()["drivers"] == []
    assert c.get("/v1/directions/nope").status_code == 404


def test_kill_criteria_flag_each_condition() -> None:
    from evals.directions import kill_criteria

    good = [
        {"id": str(i), "status": "supported" if i % 2 else "contradicted",
         "probability": 0.9 if i % 2 else 0.1, "base_rate": 0.5, "origin": "model"}
        for i in range(10)
    ]  # fmt: skip
    ok = kill_criteria(good, [{"proposed": 10, "dropped": 1}], 1.0, 0.5)
    assert ok["stop"] is False and ok["checks"]["brier_beats_base_rate"]["stop"] is False
    bad = [p | {"status": "expired"} for p in good]
    res = kill_criteria(bad, [{"proposed": 10, "dropped": 4}], 4.0, 0.1)
    assert {k for k, v in res["checks"].items() if v["stop"]} == {
        "brier_beats_base_rate",
        "expired_share",
        "dropped_share",
        "worst_decile_gap",
        "monthly_cost_usd",
        "useful_share",
    }
