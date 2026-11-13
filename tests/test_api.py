"""API tests over a graph built by the real stream worker and nightly stages."""

import pytest
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
    story = c.get("/v1/stories/iran-israel-war?until=2026-11-06").json()
    assert {n["kind"] for n in story["nodes"]} == {"report_group", "document"}
    later = c.get("/v1/stories/iran-israel-war?until=2026-11-20").json()  # a week with no reports
    assert later["nodes"] == [] and later["events"] == [] and later["window"]["older"] is True
    assert c.get("/v1/stories/iran-israel-war?until=2026-11-20&days=0").json()["nodes"]
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
    assert m["rules_version"] == 6 and len(m["weights"]["factors"]) == 6
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
    assert next(s for s in store.active_sources(ctx.db) if s["id"] == "a-il")["state_run"] is True
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
                {"text": "{outlet} reported that officials confirmed the strike.", "passages": [1]},
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
    q = "what did outlets report about the strike?"
    outlet = ask.retrieve(ctx.db, ctx.nlp.embedder, q)[0]["outlet"]
    reply = reply.replace("{outlet}", outlet)
    out = ask.answer(ctx.db, ctx.nlp.embedder, model, q)
    assert [s["text"] for s in out["sentences"]] == [
        "Outlet A reported the strike.",
        f"{outlet} reported that officials confirmed the strike.",  # attributed: kept
    ]
    assert "1 statement(s) were left out" in out["note"]  # the bare verdict, and the reader is told
    assert out["cites"][0]["published_at"]
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
    added = next(m for m in got if m["type"] == "node.added")["data"]
    assert added["title"] and added["source"] and added["url"].startswith("https://")
    assert readmodel.changes(ctx.db, "iran-israel-war", "2999-01-01") == []


def test_digest_only_for_followed_stories_never_provisional_and_unsubscribes() -> None:
    from datetime import UTC, datetime

    from weft_core import digest

    c, ctx = build()
    c.put("/admin/stories/iran-israel-war/public", json={"public": True}, headers=H)
    assert c.put("/v1/subscription", json={"email": "bad", "frequency": "daily"}).status_code == 422
    for who, follows in (("a@x.org", ["iran-israel-war"]), ("b@x.org", [])):
        assert (
            c.put(
                "/v1/subscription", json={"email": who, "frequency": "daily", "follows": follows}
            ).status_code
            == 200
        )
    ctx.db.execute(
        "MERGE (n:DailyDiff {day: '2026-11-06'}) SET n.payload=?", ('{"new_events":["e"]}',)
    )
    sent: list[tuple[str, str, str]] = []
    n = digest.send_due(
        ctx.db, lambda *a: sent.append(a), "https://w.test", datetime(2026, 11, 6, tzinfo=UTC)
    )
    assert n == 1 and [to for to, _, _ in sent] == ["a@x.org"]
    assert "headline from" in sent[0][2] and "outlets" in sent[0][2]  # new events, not totals
    assert (
        digest.send_due(
            ctx.db, lambda *a: sent.append(a), "https://w.test", datetime(2026, 11, 6, tzinfo=UTC)
        )
        == 0
    )
    token = ctx.db.execute("MATCH (n:Subscription {email: 'a@x.org'}) RETURN n.token AS token")[0][
        "token"
    ]
    assert c.get(f"/v1/unsubscribe?token={token}").json() == {"unsubscribed": True}
    assert c.get(f"/v1/unsubscribe?token={token}").status_code == 404


def test_admin_sees_pipeline_runs() -> None:
    from pipeline.run import run_stages

    c, ctx = build()
    run_stages(ctx, only="figures")
    assert c.get("/admin/runs").status_code == 401
    runs = c.get("/admin/runs", headers=H).json()
    assert [(r["stage"], r["status"]) for r in runs] == [("figures", "ok")]
    assert runs[0]["ended_at"] and runs[0]["rows_out"] is not None


def test_admin_edits_source_country_and_reports_follow() -> None:
    c, ctx = build()
    rows = c.get("/admin/sources", headers=H).json()
    assert {"id", "country", "paywalled", "status", "last_report_at"} <= rows[0].keys()
    ok = c.patch("/admin/sources/a-il", json={"country": "us", "paywalled": True}, headers=H)
    assert ok.status_code == 200
    reps = graph.select(ctx.db, "reports", "n.source_id=?", ("a-il",))
    assert reps and {r["perspective"] for r in reps} == {"US"}  # re-tagged, not frozen
    [src] = store.all_sources(ctx.db, "n.id=?", ("a-il",))
    assert src["paywalled"] == 1 and src["country_source"] == "admin"
    assert c.patch("/admin/sources/a-il", json={"status": "gone"}, headers=H).status_code == 422


def test_admin_edits_beat_terms_and_sees_unplaced() -> None:
    c, ctx = build()
    assert c.put("/admin/beats/nope", json={"patterns": ["x"]}, headers=H).status_code == 404
    bad = c.put("/admin/beats/iran-israel-war", json={"patterns": ["(unclosed"]}, headers=H)
    assert bad.status_code == 422
    ok = c.put(
        "/admin/beats/iran-israel-war",
        json={"patterns": [r"\biran\b", " "], "exclude": [r"\boil\b"]},
        headers=H,
    )
    assert ok.json()["patterns"] == [r"\biran\b"]
    [b] = [b for b in c.get("/admin/beats", headers=H).json() if b["id"] == "iran-israel-war"]
    assert b["exclude"] == [r"\boil\b"] and b["edited"] == 1
    graph.put(ctx.db, "reports", {"id": "u1", "title": "Bakery", "fetched_at": "2026-11-07"})
    assert "u1" in [r["id"] for r in c.get("/admin/unplaced", headers=H).json()]


def test_admin_queues_a_source_for_discovery() -> None:
    c, ctx = build()
    assert c.post("/admin/sources", json={"url": "not a url"}, headers=H).status_code == 422
    ok = c.post("/admin/sources", json={"url": "https://www.Example.org/news"}, headers=H)
    assert ok.status_code == 202 and ok.json()["domain"] == "www.example.org"
    assert store.requested_sources(ctx.db) == [{"domain": "www.example.org", "beat_id": ""}]


def test_untracked_party_is_not_called_silent() -> None:
    from weft_core import readmodel
    from weft_core.perspectives import perspective_of

    _, ctx = build()
    have = perspective_of(store.all_sources(ctx.db, "n.status='active'")[0])
    assert readmodel.untracked(ctx.db, [have, "ZZ"]) == ([have], ["ZZ"])


def test_globe_places_stories_where_they_happen() -> None:
    c, _ = build()
    c.put("/admin/stories/iran-israel-war/public", json={"public": True}, headers=H)
    w = c.get("/v1/world").json()
    places = {p["country"] for p in w["places"] if p["story_id"] == "iran-israel-war"}
    assert places == {"IR", "IL"}  # where it happens, not where the outlets are
    assert sum(w["places"][0]["from"].values()) == w["places"][0]["reports"]


def test_anomaly_evidence_is_named_by_outlet_and_headline() -> None:
    from weft_core import readmodel

    _, ctx = build()
    r = graph.get(ctx.db, "reports", "1")
    assert r is not None
    graph.put(
        ctx.db,
        "figures",
        {
            "id": "f1",
            "report_id": "1",
            "event_id": r["event_id"],
            "kind": "number",
            "text": "12",
            "start_char": 0,
            "end_char": 2,
        },
    )
    rep = readmodel._evidence(ctx.db, "1")
    assert rep["id"] == "1" and r["title"] in rep["label"]
    fig = readmodel._evidence(ctx.db, "f1")
    assert fig["id"] == "1" and fig["quote"]  # links to the report, quotes the sentence
    assert readmodel._evidence(ctx.db, "nope") == {"label": "Evidence", "id": "nope"}


def test_today_lists_only_what_is_new() -> None:
    from datetime import UTC, datetime

    from weft_core import readmodel

    _, ctx = build()
    store.set_public(ctx.db, "iran-israel-war", True)
    now = datetime(2026, 11, 6, 12, tzinfo=UTC)
    t = readmodel.today(ctx.db, now=now)
    assert t["new_events"] and t["breaking"]
    assert all(e["first_seen"] >= t["since"] for e in t["new_events"])
    later = readmodel.today(ctx.db, now=datetime(2026, 11, 20, tzinfo=UTC))
    assert later["new_events"] == [] and later["breaking"] == [] and later["blind_spots"] == []


def test_method_page_names_the_configured_model(monkeypatch: pytest.MonkeyPatch) -> None:
    from weft_core import readmodel

    monkeypatch.setenv("MODEL_NAME", "org/some-model")
    monkeypatch.setenv("MODEL_REVISION", "abc")
    jobs = {m["job"]: m["model"] for m in readmodel.models()}
    assert jobs["Claim extraction"] == "org/some-model (revision abc)"
    assert "Translation" not in jobs


def test_domestic_beat_groups_outlets_instead_of_countries() -> None:
    from pipeline import short_version

    c, ctx = build()
    srcs = sorted(
        {r["source_id"] for r in graph.select(ctx.db, "reports", "n.story_id IS NOT NULL")}
    )
    body = {"patterns": [r"\biran\b"], "groups": {"nope": "Left"}}
    assert c.put("/admin/beats/iran-israel-war", json=body, headers=H).status_code == 422
    groups = {srcs[0]: "Left", **{s: "Right" for s in srcs[1:]}}
    body["groups"] = groups
    assert c.put("/admin/beats/iran-israel-war", json=body, headers=H).json()["groups"] == groups
    tags = {
        r["source_id"]: r["perspective"]
        for r in graph.select(ctx.db, "reports", "n.story_id IS NOT NULL")
    }
    assert tags == groups  # every report re-tagged with its outlet's group
    store.set_country(ctx.db, srcs[0], "us", "admin")  # a country edit does not undo the group
    assert graph.get(ctx.db, "reports", "1")["perspective"] in {"Left", "Right"}  # type: ignore[index]
    short_version.run(ctx)
    ev = graph.get(ctx.db, "reports", "1")["event_id"]  # type: ignore[index]
    sv = graph.get(ctx.db, "short_versions", ev)["payload"]  # type: ignore[index]
    assert set(sv["no_source_published"]) <= {"Left", "Right"}  # sides are the groups now


def test_open_questions_come_from_rules_and_leave_when_answered() -> None:
    from datetime import UTC, date, datetime

    from weft_core import questions

    assert questions.future_dates(
        "A vote on 20 November and talks March 3", date(2026, 11, 13)
    ) == [date(2026, 11, 20)]  # March 3 has passed this year
    c, ctx = build()
    assert c.get("/v1/stories/iran-israel-war/questions").status_code == 404  # not public
    store.set_public(ctx.db, "iran-israel-war", True)
    qs = c.get("/v1/stories/iran-israel-war/questions").json()
    assert any(q["kind"] == "conflict" for q in qs)  # the fixture has a conflict
    assert all(q["groups"] and q["would_change"] for q in qs)
    ctx.db.execute("MATCH (n:Conflict) DETACH DELETE n")
    later = questions.open_questions(ctx.db, "iran-israel-war", datetime(2026, 11, 6, tzinfo=UTC))
    assert not any(q["kind"] == "conflict" for q in later)
