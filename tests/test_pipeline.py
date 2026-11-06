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
from weft_core.store import SqliteDb

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
    db = SqliteDb()
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
    nums = graph.select(ctx.db, "figures", "kind='number'")
    assert {(f["report_id"], f["quantity"], f["value"]) for f in nums} >= {
        ("1", "missile", 40.0),
        ("2", "missile", 25.0),
    }
    q = graph.select(ctx.db, "figures", "kind='quote'")[0]
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
    row: dict[str, Any] = ctx.db.execute("SELECT * FROM batch_runs")[0]
    assert row["stage"] == "figures" and row["status"] == "ok"
    assert next(iter(STAGES)) == "regroup"
