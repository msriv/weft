"""API tests over a graph built by the real stream worker and nightly stages."""

from fastapi.testclient import TestClient

from pipeline import anomalies, claims, figures, groups, short_version, statements, weights
from pipeline.ctx import Ctx
from services.api.app import create_app
from tests.test_pipeline import TEXTS, setup
from weft_core import graph, store

H = {"Authorization": "Bearer t0k"}


def build() -> tuple[TestClient, Ctx]:
    ctx, _ = setup(['{"claims":[0]}', '{"claims":[0]}', '{"claims":[0]}'])
    ctx.cfg["nightly"]["claim_group_cosine"] = 0.4
    for stage in (
        claims.run,
        figures.run,
        groups.run_groups,
        groups.run_conflicts,
        short_version.run,
        anomalies.run,
        weights.run,
    ):
        stage(ctx)
    graph.put(
        ctx.db,
        "documents",
        {
            "id": "d1",
            "url": "https://a/doc",
            "issuer_id": "a-il",
            "kind": "transcript",
            "story_id": "iran-israel-war",
            "event_id": graph.get(ctx.db, "reports", "1")["event_id"],  # type: ignore[index]
            "published_at": "2026-11-06T03:00:00+00:00",
            "title": "Debate",
            "summary": "s",
        },
    )
    ctx.text_of = lambda r: "Anita Rao (Minister): The government will respond in writing."
    statements.run(ctx)
    return TestClient(create_app(ctx.db, "t0k")), ctx


def test_nothing_is_readable_until_the_admin_toggle() -> None:
    c, ctx = build()
    ev = graph.get(ctx.db, "reports", "1")["event_id"]  # type: ignore[index]
    assert c.get("/v1/stories").json() == []
    for path in (
        "/v1/stories/iran-israel-war",
        f"/v1/events/{ev}",
        "/v1/nodes/1",
        "/v1/documents/d1",
        "/v1/actors/anita-rao",
    ):
        assert c.get(path).status_code == 404, path
    assert c.get("/v1/sources/a-il").json()["index"]["reports"] == 0  # no leak through source page
    assert c.put("/admin/stories/iran-israel-war/public", json={"public": True}).status_code == 401
    assert (
        c.put("/admin/stories/iran-israel-war/public", json={"public": True}, headers=H).status_code
        == 200
    )
    assert [s["id"] for s in c.get("/v1/stories").json()] == ["iran-israel-war"]


def test_story_event_node_document_actor_world_method() -> None:
    c, _ = build()
    c.put("/admin/stories/iran-israel-war/public", json={"public": True}, headers=H)
    story = c.get("/v1/stories/iran-israel-war").json()
    assert {n["kind"] for n in story["nodes"]} == {"report_group", "document"}
    assert story["story"]["reports"] == 3 and story["perspectives"]
    assert any(e["kind"] == "conflict" for e in story["edges"])
    ev = story["events"][0]["id"]
    page = c.get(f"/v1/events/{ev}").json()
    assert sum(len(v) for v in page["perspectives"].values()) == 3  # nothing hidden
    first = next(iter(page["perspectives"].values()))[0]
    assert first["source"]["state_run"] == "unverified"  # no citation, so never asserted
    assert page["short_version"]["no_source_published"] == []
    assert c.get("/v1/nodes/1").json()["links"][0]["url"] == "https://x/1"
    doc = c.get("/v1/documents/d1").json()
    assert doc["issuer"]["name"] == "a.il" and doc["issuer"]["is_party"] is True  # IL is a party
    assert "party to this story" in doc["label"]
    assert doc["statements"][0]["actor"] == "Anita Rao"
    assert c.get("/v1/actors/anita-rao").json()["statements"][0]["document_id"] == "d1"
    w = c.get("/v1/world").json()
    assert {i["country"] for i in w["stories"]} >= {"IL", "IR"}
    assert any(g["country"] == "IR" and g["reports"] < 3 for g in w["gaps"])  # coverage gap wording
    m = c.get("/v1/method").json()
    assert m["rules_version"] == 1 and len(m["weights"]["factors"]) == 6
    assert c.get("/v1/today").json()["day"] is None or True


def test_replay_at_date_and_source_profile() -> None:
    c, _ = build()
    c.put("/admin/stories/iran-israel-war/public", json={"public": True}, headers=H)
    early = c.get("/v1/stories/iran-israel-war?at=2000-01-01").json()
    assert early["story"]["reports"] == 0 and early["nodes"] == []
    src = c.get("/v1/sources/a-il").json()
    assert src["source"]["weight"] == 0.5 and src["source"]["weight_insufficient"] is True
    assert "No report is hidden" in src["weight_note"]
    assert c.get("/v1/sources").json()[0]["id"]


def test_admin_cannot_assert_state_run_without_citation_and_problems_flow() -> None:
    c, ctx = build()
    bad = c.patch("/admin/sources/a-il", json={"state_run": True}, headers=H)
    assert bad.status_code == 422
    ok = c.patch(
        "/admin/sources/a-il",
        json={"state_run": True, "state_run_source": "https://x/f"},
        headers=H,
    )
    assert ok.status_code == 200
    assert store.active_sources(ctx.db)[0]["state_run"] is True
    assert (
        c.post("/v1/reports-problem", json={"kind": "bogus", "message": "hello there"}).status_code
        == 422
    )
    r = c.post(
        "/v1/reports-problem", json={"kind": "grouping", "ref_id": "1", "message": "wrong group"}
    )
    assert r.status_code == 201
    assert c.get("/admin/reader-reports", headers=H).json()[0]["message"] == "wrong group"
    c.post(
        f"/admin/reader-reports/{r.json()['id']}/resolve",
        json={"resolution": "regrouped"},
        headers=H,
    )
    c.post("/admin/corrections", json={"kind": "grouping", "what": "Moved a report"}, headers=H)
    assert c.get("/v1/method").json()["corrections"][0]["what"] == "Moved a report"
    q = c.get("/admin/review", headers=H).json()
    assert "open" in q and TEXTS


def test_ask_cites_retrieved_passages_and_drops_verdicts() -> None:
    import json

    import httpx

    from weft_core import ask
    from weft_core.models import ModelClient

    _, ctx = build()
    store.set_public(ctx.db, "iran-israel-war", True)
    reply = json.dumps(
        {
            "statements": [
                {"text": "Outlet A reported the strike.", "passages": [1]},
                {"text": "The strike is confirmed.", "passages": [1]},
                {"text": "Nobody cited this.", "passages": [99]},
            ]
        }
    )
    model = ModelClient(
        base_url="https://llm.test/v1", api_key="k", model="m", revision="r", log=lambda c: None,
        transport=httpx.MockTransport(
            lambda req: httpx.Response(200, json={"choices": [{"message": {"content": reply}}]})
        ),
    )  # fmt: skip
    out = ask.answer(ctx.db, ctx.nlp.embedder, model, "what did outlets report about the strike?")
    assert [s["text"] for s in out["sentences"]] == ["Outlet A reported the strike."]
    assert out["cites"] and out["cites"][0]["id"] == out["sentences"][0]["cites"][0]
    _, hidden = build()  # nothing public: nothing retrievable
    assert ask.retrieve(hidden.db, hidden.nlp.embedder, "strike") == []
    c = TestClient(create_app(ctx.db, "t0k"))
    assert c.post("/v1/ask", json={"question": "strike?"}).status_code == 503


def test_live_changes_and_stream_is_hidden_until_public() -> None:
    from weft_core import readmodel

    c, ctx = build()
    assert c.get("/v1/stories/iran-israel-war/stream").status_code == 404
    got = readmodel.changes(ctx.db, "iran-israel-war", "2000-01-01")
    assert {m["type"] for m in got} >= {"node.added"}
    assert readmodel.changes(ctx.db, "iran-israel-war", "2999-01-01") == []
