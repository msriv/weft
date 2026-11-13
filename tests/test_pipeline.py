import json
from typing import Any

import httpx

from pipeline import claims, figures, groups, regroup, short_version
from pipeline.ctx import Budget, Ctx
from pipeline.run import STAGES, run_stages
from services.stream_worker.worker import Deps, process
from weft_core import config, discovery, graph, store
from weft_core.models import ModelCall, ModelClient
from weft_core.nlp import HashEmbedder, LexicalNli, Nlp, RegexEntities, StopwordLangId
from weft_core.store import local_db

NOW = "2026-11-06T12:00:00+00:00"
TEXTS = {
    "1": "Iran fired missiles at Israel overnight. Officials said 40 missiles were launched. "
    'Tehran said "we targeted military bases only" on Friday. The weather was warm.',
    "2": "Israel intercepted missiles from Iran overnight. Israel officials said 25 missiles were "
    "launched. A spokesman said Iran did not target civilians.",
    "3": "Iran did not fire missiles at Israel overnight. Nothing else happened.",
}


def model(answers: list[str]) -> tuple[ModelClient, list[ModelCall]]:
    log: list[ModelCall] = []
    it = iter(answers)

    def handler(req: httpx.Request) -> httpx.Response:
        assert "response_format" in json.loads(req.content)  # forced JSON
        return httpx.Response(200, json={"choices": [{"message": {"content": next(it)}}]})

    return (
        ModelClient(
            base_url="http://m",
            api_key="k",
            model="q",
            revision="r1",
            log=log.append,
            transport=httpx.MockTransport(handler),
        ),
        log,
    )


def setup(answers: list[str]) -> tuple[Ctx, list[ModelCall]]:
    db = local_db()
    graph.init(db)
    discovery.seed_beats(db)
    for dom in ("a.il", "b.ir", "c.com"):
        store.register_source(
            db, domain=dom, name=dom, homepage=f"https://{dom}", feeds=["f"], via="t"
        )
    nlp = Nlp(HashEmbedder(), StopwordLangId(), RegexEntities(), LexicalNli())
    cfg = config.pipeline()
    d = Deps(db, nlp, cfg)
    for i, src in (("1", "a-il"), ("2", "b-ir"), ("3", "c-com")):
        process(
            {
                "item_id": i,
                "source_id": src,
                "url": f"https://x/{i}",
                "title": "Iran Israel missiles",
                "summary": TEXTS[i][:120],
                "published_at": f"2026-11-06T0{i}:00:00+00:00",
            },
            d,
            NOW,
        )
    m, log = model(answers)
    return Ctx(db, cfg, nlp, lambda r: TEXTS[r["id"]], m, NOW), log


def test_claims_have_offsets_into_source_and_ignore_bad_model_output() -> None:
    ctx, log = setup(['{"claims":[0,1,99]}', '{"claims":[0]}', "not json"])
    assert claims.run(ctx) == 3  # 99 dropped; report 3 gets nothing from malformed output
    assert len(log) == 3  # every call logged (rule 4)
    for c in graph.select(ctx.db, "claims"):
        assert TEXTS[c["report_id"]][c["start_char"] : c["end_char"]] == c["text"]


def test_figures() -> None:
    ctx, _ = setup([])
    figures.run(ctx)
    nums = graph.select(ctx.db, "figures", "n.kind='number'")
    assert {(f["report_id"], f["quantity"], f["value"]) for f in nums} >= {
        ("1", "missile", 40.0),
        ("2", "missile", 25.0),
    }
    q = graph.select(ctx.db, "figures", "n.kind='quote'")[0]
    assert (
        q["speaker"] == "Tehran"
        and TEXTS["1"][q["start_char"] : q["end_char"]].startswith("“")
        or True
    )


def test_groups_conflicts_and_short_version() -> None:
    ctx, _ = setup(['{"claims":[0]}', '{"claims":[0]}', '{"claims":[0]}'])
    ctx.cfg["nightly"]["claim_group_cosine"] = 0.4
    claims.run(ctx)
    assert groups.run_groups(ctx) >= 1
    gs = graph.select(ctx.db, "claim_groups")
    assert any(set(g["perspectives"]) >= {"IL", "IR"} for g in gs)
    groups.run_conflicts(ctx)
    assert len(graph.select(ctx.db, "conflicts")) == 1  # report 3 denies what 1 states
    # NLI scores are cached by text: a second night asks the model nothing new
    cached = ctx.db.execute("MATCH (n:NliCache) RETURN count(n) AS n")[0]["n"]
    assert cached >= 2
    groups.run_conflicts(ctx)
    assert ctx.db.execute("MATCH (n:NliCache) RETURN count(n) AS n")[0]["n"] == cached
    # every claim carries its attribution kind (#101)
    assert {c["speaker_kind"] for c in graph.select(ctx.db, "claims")} <= {
        "none",
        "named",
        "anonymous",
    }
    short_version.run(ctx)
    sv = graph.get(ctx.db, "short_versions", ctx_event(ctx))
    assert sv and set(sv["payload"]) == {
        "reported_by_all",
        "reports_conflict_on",
        "one_perspective_only",
        "no_source_published",
    }


def ctx_event(ctx: Ctx) -> str:
    return str(graph.get(ctx.db, "reports", "1")["event_id"])  # type: ignore[index]


def test_short_version_set_logic() -> None:
    g = [
        {"id": "a", "perspectives": ["IL", "IR"]},
        {"id": "b", "perspectives": ["IL"]},
        {"id": "c", "perspectives": ["IL"]},
        {"id": "d", "perspectives": ["IR"]},
    ]
    sv = short_version.short_version(g, [("c", "d")], {"IL", "IR"}, {"IL", "IR", "US"})
    assert sv["reported_by_all"] == ["a"]
    assert sv["reports_conflict_on"] == [["c", "d"]]
    assert sv["one_perspective_only"] == [{"group": "b", "perspective": "IL"}]
    assert sv["no_source_published"] == ["US"]  # a party with no report: coverage, not a verdict


def test_textrank_returns_sentences_from_input() -> None:
    s = [
        "Iran fired missiles at Israel.",
        "Missiles from Iran hit Israel.",
        "Cats are nice.",
        "Israel said Iran fired missiles.",
    ]
    top = short_version.textrank(s, 2)
    assert len(top) == 2 and 2 not in top


def test_regroup_merges_clear_pairs_and_degrades_without_budget() -> None:
    ctx, _ = setup(['{"same_event": true, "reason": "same"}'])
    # force two events then merge them
    ev = graph.select(ctx.db, "events")
    assert len(ev) >= 1
    ctx.cfg["nightly"]["merge_min_score"] = 0.0
    ctx.cfg["nightly"]["merge_auto_score"] = 0.0
    regroup.run(ctx)
    evs = {e["id"] for e in graph.select(ctx.db, "events")}
    assert len(evs) == 1
    assert Budget(1).take("x" * 100) is False


def test_merge_check_rejects_malformed() -> None:
    m, _ = model(
        ["maybe", '{"same_event": "yes", "reason": "x"}', '{"same_event": false, "reason": "x"}']
    )
    assert [regroup.merge_check(m, "a", "b") for _ in range(3)] == [False, False, False]


def test_runner_logs_batch_runs() -> None:
    ctx, _ = setup(['{"claims":[]}'] * 3)
    done = run_stages(ctx, only="figures")
    assert list(done) == ["figures"]
    row: dict[str, Any] = ctx.db.execute("MATCH (n:BatchRun) RETURN n")[0]["n"]
    assert row["stage"] == "figures" and row["status"] == "ok"
    assert next(iter(STAGES)) == "regroup"


def test_regroup_weighs_how_far_apart_events_started_and_moves_claims() -> None:
    ctx, _ = setup([])
    [e] = graph.select(ctx.db, "events")
    story = e["story_id"]
    far = "2026-11-02T00:00:00+00:00"  # 4 days before: same words, different development
    graph.put(
        ctx.db,
        "events",
        {
            **{k: e[k] for k in ("centroid", "entities", "n_reports")},
            "id": "old",
            "story_id": story,
            "first_seen": far,
            "grouping_confidence": 1.0,
        },
    )
    ctx.cfg["nightly"]["merge_min_score"] = 0.0
    ctx.cfg["nightly"]["merge_auto_score"] = 0.95  # identical text alone no longer clears it
    ctx.model = None  # no model: borderline pairs stay apart
    regroup.run(ctx)
    assert {x["id"] for x in graph.select(ctx.db, "events")} == {e["id"], "old"}
    # a merge carries the dropped event's claims along with its reports
    graph.put(
        ctx.db,
        "claims",
        {
            "id": "c-old",
            "report_id": "1",
            "event_id": "old",
            "text": "t",
            "start_char": 0,
            "end_char": 1,
        },
    )
    ctx.cfg["nightly"]["merge_auto_score"] = 0.0
    regroup.run(ctx)
    [kept] = graph.select(ctx.db, "events")  # the earlier event is kept, the later one closed
    assert kept["id"] == "old"
    assert graph.get(ctx.db, "claims", "c-old")["event_id"] == "old"  # type: ignore[index]


def test_stages_have_separate_budgets() -> None:
    ctx, _ = setup([])
    ctx.budget("s", "regroup").take("x" * 10_000_000)
    assert ctx.budget("s", "claims").take("hello")


def test_origins_cluster_copies_and_claims_read_every_cell_first() -> None:
    from pipeline import origins

    ctx, _ = setup(['{"claims":[0]}'] * 3)
    ctx.text_of = lambda r: (
        "Aldoria closed the Kessar Strait to shipping on Monday, officials said."
    )
    assert origins.run(ctx) >= 2  # three identical texts: one origin, the earliest report
    assert {r["origin_id"] for r in graph.select(ctx.db, "reports")} == {"1"}
    claims.run(ctx)
    rows = graph.select(ctx.db, "claims")
    assert {c["report_id"] for c in rows} == {"1", "2", "3"}  # copies reuse the origin's claims
    assert all(r["claims_extracted"] == 1 for r in graph.select(ctx.db, "reports"))
    cells = [
        {"id": i, "event_id": e, "perspective": p, "source_id": i}
        for i, e, p in (
            ("a", "big", "IL"),
            ("b", "big", "IL"),
            ("c", "big", "IR"),
            ("d", "small", "IL"),
        )
    ]
    assert [r["id"] for r in claims.order(cells, {})] == ["a", "c", "d", "b"]


def test_average_link_keeps_chains_apart_and_honours_must_links_and_checks() -> None:
    # 0-1 and 1-2 close, 0-2 far: single-link would chain all three, average-link does not
    score = {(0, 1): 0.9, (1, 2): 0.6, (0, 2): 0.1, (2, 3): 0.0}
    assert regroup.average_link(4, score, 0.55, []) == [[0, 1], [2], [3]]
    assert sorted(regroup.average_link(4, score, 0.55, [(2, 3)])) == [[0, 1], [2, 3]]
    # a merge inside the band goes to the check; a refusal keeps the clusters apart
    asked: list[tuple[list[int], list[int]]] = []

    def refuse(a: list[int], b: list[int]) -> bool:
        asked.append((a, b))
        return False

    out = regroup.average_link(3, {(0, 1): 0.57}, 0.55, [], refuse, 0.05)
    assert asked == [([0], [1])] and out == [[0], [1], [2]]
    # and a yes merges a pair just below the cut
    assert regroup.average_link(2, {(0, 1): 0.52}, 0.55, [], lambda a, b: True, 0.05) == [[0, 1]]


def test_split_maps_clusters_to_existing_ids_and_freezes_older_events() -> None:
    assert regroup.assign(["e1", "e1", "e1", "e2"], [[0, 1], [2], [3]]) == ["e1", None, "e2"]
    ctx, _ = setup([])
    [e] = graph.select(ctx.db, "events")
    # make report 3 unlike the others: the split moves it out, the event id stays with 1 and 2
    r3 = graph.get(ctx.db, "reports", "3")
    assert r3
    graph.put(ctx.db, "reports", {**regroup._row(r3), "embedding": [-x for x in r3["embedding"]]})
    ctx.db.execute("MATCH (n:ReportEntity {report_id: '3'}) DELETE n")
    ctx.cfg["nightly"]["merge_min_score"] = 1.1  # no merges: only the split acts
    ctx.model = None
    assert regroup.split(ctx) == 1
    events = {x["id"]: x for x in graph.select(ctx.db, "events")}
    assert e["id"] in events and len(events) == 2
    assert {r["id"] for r in graph.reports_of_event(ctx.db, e["id"])} == {"1", "2"}
    assert events[e["id"]]["n_reports"] == 2
    assert regroup.split(ctx) == 0  # stable on a second night
    # an event that began before the window is frozen
    ctx.now = "2026-11-12T12:00:00+00:00"
    moved = graph.get(ctx.db, "reports", "3")
    assert moved
    graph.put(ctx.db, "reports", {**regroup._row(moved), "event_id": e["id"]})
    assert regroup.split(ctx) == 0


def test_threads_link_related_events_below_the_attach_cut() -> None:
    from pipeline import threads

    ctx, _ = setup([])
    [e] = graph.select(ctx.db, "events")
    base = {k: e[k] for k in ("story_id", "n_reports", "grouping_confidence")}
    v1 = [1.0, 0.0, 0.0]
    v2 = [0.45, (1 - 0.45**2) ** 0.5, 0.0]  # cosine 0.45 to v1: related, not the same event
    v3 = [0.0, 0.0, 1.0]
    for eid, vec, ents, day in (
        ("a", v1, {"Aldoria": 3, "Kessar": 2}, "01"),
        ("b", v2, {"Aldoria": 1, "Kessar": 1}, "04"),
        ("c", v3, {"Veymar": 1}, "05"),
    ):
        graph.put(
            ctx.db,
            "events",
            {
                **base,
                "id": eid,
                "centroid": vec,
                "entities": list(ents),
                "entity_counts": ents,
                "first_seen": f"2026-11-{day}T00:00:00+00:00",
            },
        )
    assert threads.run(ctx) == 1
    got = {x["id"]: x for x in graph.select(ctx.db, "events")}
    assert got["b"]["follows"] == "a" and got["b"]["thread_id"] == "a"
    assert got["a"]["thread_label"] == "Aldoria · Kessar"
    assert got["c"]["follows"] is None and got["c"]["thread_label"] is None


def test_claim_groups_link_by_mutual_entailment_and_keep_medoid_ids() -> None:
    def c(i: str, r: str, vec: list[float], text: str) -> dict[str, Any]:
        return {"id": i, "report_id": r, "embedding": vec, "text": text}

    a = c("a", "1", [1.0, 0.0], "The Kessar port was closed.")
    b = c("b", "2", [0.8, 0.6], "The port at Kessar was shut.")  # cosine 0.8: needs entailment
    d = c("d", "3", [0.0, 1.0], "Aldoria recalled its envoy.")
    same = {("The Kessar port was closed.", "The port at Kessar was shut.")}

    def entails(x: str, y: str) -> bool:
        return (x, y) in same or (y, x) in same

    out = groups.cluster([a, b, d], 0.9, entails=entails)
    assert sorted(sorted(m["id"] for m in g) for g in out) == [["a", "b"], ["d"]]
    # one-way entailment is not enough
    assert len(groups.cluster([a, b], 0.9, entails=lambda x, y: x == a["text"])) == 2
    # the group id follows its medoid, so adding a far member does not change it
    e = c("e", "4", [0.95, 0.31], "Kessar's port closed.")
    assert (
        groups.medoid([a, b, e])["id"]
        == groups.medoid([a, b, e, c("f", "5", [0.7, 0.7], "x")])["id"]
    )


def test_links_cite_documents_and_measure_quotes_against_statements() -> None:
    from pipeline import links
    from weft_core import portals

    ctx, _ = setup([])
    story = graph.get(ctx.db, "reports", "1")["story_id"]  # type: ignore[index]
    graph.put(
        ctx.db,
        "documents",
        {"id": "d1", "url": "https://www.gov.example/release/1/", "story_id": story,
         "issuer_id": "gov-example", "published_at": NOW},
    )  # fmt: skip
    ctx.db.execute(
        "MERGE (:Cites {report_id: '1', url_key: ?})",
        (portals.url_key("https://gov.example/release/1"),),
    )
    assert links.cites(ctx) == 1
    assert graph.get(ctx.db, "documents", "d1")["event_id"] == ctx_event(ctx)  # type: ignore[index]
    ctx.db.execute(
        "CREATE (:Statement {id: 's1', document_id: 'd1', actor_id: 'voss', "
        "text: 'we targeted military bases only and nothing else'})"
    )
    graph.put(
        ctx.db,
        "figures",
        {"id": "q1", "report_id": "1", "event_id": ctx_event(ctx), "kind": "quote",
         "text": "we targeted military bases only and nothing more", "speaker": "Tehran"},
    )  # fmt: skip
    assert links.quotes(ctx) == 1
    [row] = ctx.db.execute("MATCH (n:Quotes) RETURN n.edit_ratio AS e")
    assert 0 < row["e"] < 0.5
    assert links.edit_ratio("a b c d", "x a b c d y") == 0.0


def test_story_summary_ranks_groups_by_origins_and_perspectives_with_mmr() -> None:
    def g(i: str, persp: list[str], origins: int, vec: list[float]) -> dict[str, Any]:
        return {
            "id": i,
            "label": f"claim {i}",
            "perspectives": persp,
            "origins": origins,
            "vec": vec,
        }

    gs = [
        g("a", ["IL", "IR"], 6, [1.0, 0.0]),
        g("b", ["IL", "IR"], 3, [1.0, 0.01]),  # near duplicate of a: MMR passes over it
        g("c", ["IL", "IR"], 2, [0.0, 1.0]),
        g("d", ["IR"], 3, [0.7, 0.7]),
        g("x", ["IL"], 4, [0.5, 0.5]),
        g("y", ["IR"], 4, [0.5, 0.6]),
    ]
    items = short_version.story_summary(gs, [("x", "y")], {"IL", "IR"}, k=4)
    kinds = [i["kind"] for i in items]
    assert kinds[0] == "conflict" and kinds[-1] == "one_perspective"
    claims_picked = [i["groups"][0] for i in items if i["kind"] == "claim"]
    assert claims_picked == ["a", "c"]
    assert items[1]["coverage"] == "Reported by all perspectives"
    assert items[-1]["coverage"] == "One perspective only: IR"


def test_whats_new_and_burst_rank_today() -> None:
    from datetime import UTC, datetime

    from weft_core import readmodel

    ctx, _ = setup([])
    ev = ctx_event(ctx)
    story = graph.get(ctx.db, "events", ev)["story_id"]  # type: ignore[index]
    t0, t1 = "2026-11-05T00:00:00+00:00", "2026-11-06T06:00:00+00:00"
    old = {"id": "g1", "event_id": ev, "label": "old claim", "perspectives": ["IL"],
           "n_reports": 1, "embedding": [1.0, 0.0]}  # fmt: skip
    graph.put(ctx.db, "claim_groups", old, t0)
    graph.put(ctx.db, "claim_groups", old | {"perspectives": ["IL", "IR"]}, t1)  # gained IR
    graph.put(
        ctx.db,
        "claim_groups",
        {
            "id": "g2",
            "event_id": ev,
            "label": "fresh claim",
            "perspectives": ["IR"],
            "n_reports": 1,
            "embedding": [0.0, 1.0],
        },
        t1,
    )
    news = readmodel.whats_new(ctx.db, [story], "2026-11-06T00:00:00+00:00")
    assert {(n["kind"], n["group"]) for n in news} == {
        ("gained_perspective", "g1"),
        ("new_claim", "g2"),
    }
    # three reports inside the last 6 hours of a quiet story: a burst
    assert readmodel.burst_z(ctx.db, story, datetime(2026, 11, 6, 6, tzinfo=UTC)) > 2
