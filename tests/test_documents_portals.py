from typing import Any, ClassVar

import httpx

from pipeline.ctx import Ctx
from pipeline.statements import run as run_statements
from pipeline.statements import slug, turns
from services.stream_worker.worker import Deps, document_kind, process, process_document
from weft_core import config, discovery, graph, portals, store
from weft_core.nlp import HashEmbedder, LexicalNli, Nlp, RegexEntities, StopwordLangId
from weft_core.polite import PoliteClient
from weft_core.store import SqliteDb

NLP = Nlp(HashEmbedder(), StopwordLangId(), RegexEntities(), LexicalNli())


def test_gov_detection_and_outbound_links() -> None:
    assert portals.is_gov("pib.gov.in") and portals.is_gov("www.knesset.gov.il")
    assert portals.is_gov("rada.gov.ua") and not portals.is_gov("example.com")
    html = (
        '<a href="https://eci.gov.in/x">a</a><a href="https://news.example/y">b</a>'
        '<a href="/local">c</a><a href="https://www.pib.gov.in/z">d</a>'
    )
    assert portals.outbound_gov_domains(html, "https://paper.example/a") == {
        "eci.gov.in",
        "pib.gov.in",
    }


def test_portal_discovery_registers_crawlable_portal_and_rejects_empty() -> None:
    db = SqliteDb()
    store.init(db)
    portals.record_candidates(db, {"eci.gov.in", "empty.gov.xx"}, "https://paper.example/a")
    portals.record_candidates(
        db, {"eci.gov.in", "empty.gov.xx", "once.gov.yy"}, "https://paper.example/b"
    )
    home = (
        '<title>Election Commission</title><a href="/press-releases/">p</a><a href="/about">a</a>'
        '<a href="/media/speeches/">s</a>'
    )

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        if req.url.host == "eci.gov.in":
            return httpx.Response(200, text=home, headers={"content-type": "text/html"})
        return httpx.Response(200, text="<p>nothing</p>", headers={"content-type": "text/html"})

    got = portals.discover_portals(
        db, PoliteClient(httpx.Client(transport=httpx.MockTransport(handler)))
    )
    assert list(got) == ["eci.gov.in"] and "https://eci.gov.in/press-releases/" in got["eci.gov.in"]
    (src,) = [s for s in store.active_sources(db) if "crawl" in s]
    assert src["type"] == "gov" and "state_run" not in src  # ownership stays unverified
    assert src["crawl"]["max_depth"] == 2
    assert "once.gov.yy" not in store.known_domains(db)  # one link is not enough to probe
    assert {"eci.gov.in", "empty.gov.xx"} <= store.known_domains(db)  # rejected ones not re-probed


def setup() -> tuple[SqliteDb, Deps]:
    db = SqliteDb()
    graph.init(db)
    discovery.seed_beats(db)
    store.register_source(
        db, domain="a.il", name="a", homepage="https://a.il", feeds=["f"], via="t"
    )
    store.register_source(
        db,
        domain="mod.gov.il",
        name="MoD",
        homepage="https://mod.gov.il",
        feeds=[],
        via="portal-links",
        type="gov",
        crawl={"start_urls": ["x"]},
    )
    return db, Deps(db, NLP, config.pipeline())


def test_document_attaches_to_event_without_inflating_it_and_gets_a_kind() -> None:
    db, d = setup()
    t = "Iran fires missiles at Israel, Tehran says it targeted military bases"
    process(
        {
            "item_id": "r1",
            "source_id": "a-il",
            "url": "https://a/1",
            "title": t,
            "summary": "Israel air defences intercepted missiles from Iran overnight.",
            "published_at": "2026-11-06T01:00:00+00:00",
        },
        d,
    )
    msg: dict[str, Any] = {
        "item_id": "d1",
        "source_id": "mod-gov-il",
        "url": "https://mod.gov.il/press/statement-1",
        "title": t,
        "summary": "Israel air defences intercepted missiles from Iran overnight.",
        "published_at": "2026-11-06T02:00:00+00:00",
    }
    assert process_document(msg, d) == "attached"
    assert process_document(msg, d) == "duplicate"
    doc = graph.get(db, "documents", "d1")
    rep = graph.get(db, "reports", "r1")
    assert doc and rep and doc["event_id"] == rep["event_id"] and doc["kind"] == "release"
    assert graph.get(db, "events", rep["event_id"])["n_reports"] == 1  # type: ignore[index]
    assert document_kind("https://x/debates/2026-11-05", "") == "transcript"
    assert document_kind("https://x/gazette/1", "") == "gazette"


TRANSCRIPT = """Debate on the notice of removal.
Speaker (Chair): The House will come to order.
Mr. Rahul Verma (Opposition): The notice has 193 signatures and we ask for a vote.
NOTE: Not a speaker line.
Anita Rao: The government will respond in writing.
"""


def test_statements_from_transcript_turns() -> None:
    t = turns(TRANSCRIPT)
    assert [x[0] for x in t] == ["Speaker", "Rahul Verma", "Anita Rao"]
    assert t[1][1] == "Opposition" and TRANSCRIPT[t[1][2] : t[1][3]] == t[1][4]
    db, d = setup()
    graph.put(
        db,
        "documents",
        {
            "id": "d9",
            "url": "u",
            "issuer_id": "mod-gov-il",
            "kind": "transcript",
            "published_at": "2026-11-06T00:00:00+00:00",
            "title": "t",
            "summary": "s",
        },
        "2026-11-06T00:00:00+00:00",
    )
    ctx = Ctx(db, d.cfg, NLP, lambda r: TRANSCRIPT, None, "2026-11-06T12:00:00+00:00")
    assert run_statements(ctx) == 3 and run_statements(ctx) == 0
    assert slug("Rahul Verma") == "rahul-verma"
    row = db.execute("SELECT * FROM actors WHERE id='rahul-verma'")[0]
    assert row["role"] == "Opposition"


BLANK_PDF = (
    b"%PDF-1.1\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
    b"trailer<</Root 1 0 R/Size 4>>\n%%EOF\n"
)


def test_scanned_pdf_falls_back_to_ocr(monkeypatch: Any) -> None:
    from services.fetcher import fetcher

    monkeypatch.setattr(fetcher, "ocr_page", lambda page: "Scanned order text recovered by OCR")
    meta, ext = fetcher._extract(BLANK_PDF, "https://x.gov/order.pdf", "application/pdf")
    assert ext == "pdf" and "recovered by OCR" in meta["text"]
    monkeypatch.setattr(fetcher, "ocr_page", lambda page: "")  # no tesseract: recorded as failure
    meta, _ = fetcher._extract(BLANK_PDF, "https://x.gov/order.pdf", "application/pdf")
    assert not meta["text"].strip()


def test_refetch_schedule_and_version_collection() -> None:
    from datetime import UTC, datetime, timedelta

    from services.fetcher import refetch

    queued: list[tuple[dict[str, Any], datetime]] = []
    now = datetime(2026, 11, 6, tzinfo=UTC)
    refetch.schedule(
        {"item_id": "i", "source_id": "s", "url": "https://x/a"},
        lambda b, t: queued.append((b, t)),
        now,
    )
    assert [t - now for _, t in queued] == [
        timedelta(hours=1),
        timedelta(hours=24),
        timedelta(days=7),
    ]
    assert [b["n"] for b, _ in queued] == [1, 2, 3]

    page = (
        "<html><body><article><p>"
        + " ".join(f"Sentence {i} of the report." for i in range(60))
        + "</p></article></body></html>"
    )
    pages = {"text": page}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text=pages["text"], headers={"content-type": "text/html"})

    http = PoliteClient(httpx.Client(transport=httpx.MockTransport(handler)))
    db = SqliteDb()
    graph.init(db)

    class Files:
        saved: ClassVar[list[tuple[str, int]]] = []

        def save_version(self, item_id: str, n: int, content: bytes, ext: str) -> None:
            self.saved.append((item_id, n))

    src = {"rate_limit": {"requests": 1, "per_seconds": 0}}
    task = {"item_id": "i", "url": "https://x/a", "n": 1}
    first = refetch.refetch(task, src, http, db, Files())
    assert first == "unchanged"  # no earlier version recorded in this fixture
    pages["text"] = page.replace("Sentence 3 of", "Sentence three of")
    assert refetch.refetch({**task, "n": 2}, src, http, db, Files()) == "changed"
    assert [r["n"] for r in db.execute("SELECT n FROM report_versions ORDER BY n")] == [1, 2]
