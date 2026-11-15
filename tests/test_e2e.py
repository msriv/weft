"""Feed entry to public API, in process: fixture feeds from fictional outlets go through the
poller, the fetcher, the stream worker, the nightly stages (with a scripted model) and the API.
Real Neo4j; fake GCS, BigQuery and Pub/Sub."""

import json
from typing import Any

import httpx
from fastapi.testclient import TestClient

from pipeline.ctx import Ctx
from pipeline.run import run_stages
from services.api.app import create_app
from services.fetcher.fetcher import fetch_item
from services.poller.poller import FeedState, Poller
from services.stream_worker.worker import Deps, process
from tests.test_fetcher import MemStore
from weft_core import config, discovery, graph, store
from weft_core.models import ModelClient
from weft_core.nlp import HashEmbedder, LexicalNli, Nlp, RegexEntities, StopwordLangId
from weft_core.polite import PoliteClient

NOW = "2026-11-06T12:00:00+00:00"
# Three invented outlets in two countries. Their text is generic wire-style filler about the beat.
OUTLETS = {
    "harbor-courier.example": "IL",
    "northgate-post.example": "IL",
    "vale-ledger.example": "IR",
}
LEDE = "Iran fired missiles at Israel overnight, officials said, and air defences intercepted most of them."


def article(host: str, n: int) -> str:
    body = " ".join(
        [
            f"{LEDE}",
            "Officials said 40 missiles were launched in two waves before dawn.",
            "A spokesman said the strikes targeted military bases only.",
            f"Reporters at {host} said the sirens sounded across the region for an hour.",
            "Emergency services reported no confirmed deaths by the afternoon.",
            f"This is report {n} from {host}.",
        ]
        * 2
    )
    return f"<html><head><title>Iran fires missiles at Israel overnight</title></head><body><article><h1>Iran fires missiles at Israel overnight</h1><p>{body}</p></article></body></html>"


def feed(host: str) -> str:
    items = "".join(
        f"<item><title>Iran fires missiles at Israel overnight</title><link>https://{host}/a{n}</link>"
        f"<pubDate>Fri, 06 Nov 2026 0{n + 1}:00:00 +0000</pubDate></item>"
        for n in (1, 2)
    )
    return f'<rss version="2.0"><channel>{items}</channel></rss>'


def site(req: httpx.Request) -> httpx.Response:
    host, path = req.url.host, req.url.path
    if path == "/robots.txt":
        return httpx.Response(404)
    if path == "/feed":
        return httpx.Response(
            200, content=feed(host), headers={"content-type": "application/rss+xml"}
        )
    return httpx.Response(
        200, text=article(host, int(path[-1])), headers={"content-type": "text/html"}
    )


class State:
    def __init__(self) -> None:
        self.d: dict[str, FeedState] = {}

    def get(self, url: str) -> FeedState:
        return self.d.get(url, FeedState())

    def put(self, url: str, state: FeedState) -> None:
        self.d[url] = state


def scripted_model() -> ModelClient:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"claims":[0]}'}}]})

    return ModelClient(
        base_url="http://m",
        api_key="k",
        model="q",
        revision="r1",
        log=lambda c: None,
        transport=httpx.MockTransport(handler),
    )


def test_feed_to_public_api() -> None:
    db = store.local_db()
    graph.init(db)
    discovery.seed_beats(db)
    for dom, country in OUTLETS.items():
        store.register_source(
            db,
            domain=dom,
            name=dom,
            homepage=f"https://{dom}",
            feeds=[f"https://{dom}/feed"],
            via="t",
        )
        store.set_country(db, dom.replace(".", "-"), country, "fixture")
    sources = store.active_sources(db)
    by_id = {s["id"]: s for s in sources}

    # 1. poller: 3 outlets x 2 entries = 6 URLs
    http = PoliteClient(httpx.Client(transport=httpx.MockTransport(site)), sleep=lambda s: None)
    polled: list[dict[str, Any]] = []
    assert all(e is None for e in Poller(http, State(), polled.append).run(sources).values())
    assert len(polled) == 6

    # 2. fetcher: each URL becomes an items-extracted message
    mem = MemStore()
    extracted: list[dict[str, Any]] = []
    for m in polled:
        r = fetch_item(m, by_id[m["source_id"]], http, mem)
        assert r.status == "stored"
        assert r.message is not None
        extracted.append(r.message)
    assert len(extracted) == 6

    # 3. stream worker places each on the beat
    nlp = Nlp(HashEmbedder(), StopwordLangId(), RegexEntities(), LexicalNli())
    cfg = config.pipeline()
    cfg["nightly"]["claim_group_cosine"] = 0.4
    deps = Deps(db, nlp, cfg)
    statuses = [
        process({**m, "published_at": f"2026-11-06T0{i + 1}:00:00+00:00"}, deps, NOW)
        for i, m in enumerate(extracted)
    ]
    assert set(statuses) <= {"new_event", "attached"} and statuses.count("new_event") == 1
    reports = graph.select(db, "reports")
    assert len(reports) == 6 and {r["story_id"] for r in reports} == {"iran-israel-war"}
    [event] = graph.select(db, "events")
    assert {r["perspective"] for r in reports if r["event_id"] == event["id"]} == {"IL", "IR"}

    # 4. nightly stages with a scripted model: one claim group, one short version
    text = {m["item_id"]: article(httpx.URL(m["url"]).host, 1) for m in extracted}
    ctx = Ctx(db, cfg, nlp, lambda r: text[r["id"]], scripted_model(), NOW)
    run_stages(ctx)
    assert len(graph.select(db, "claim_groups")) >= 1
    assert graph.get(db, "short_versions", event["id"]) is not None

    # 5. the API: a story is a 404 until it is published, then 200
    c = TestClient(create_app(db, "t0k"))
    assert c.get("/v1/stories/iran-israel-war").status_code == 404
    store.set_public(db, "iran-israel-war", True)
    r = c.get("/v1/stories/iran-israel-war")
    assert r.status_code == 200 and json.dumps(r.json())
