import base64
import contextlib
import json
import types
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from services.fetcher.app import create_app
from services.fetcher.fetcher import fetch_item, published_at
from weft_core.polite import PoliteClient
from weft_core.urls import normalize_url

BODY = " ".join(f"Sentence number {i} of the report." for i in range(60))
HTML = f"""<html><head><title>Port closed</title>
<link rel="canonical" href="https://x.test/story/1/"></head>
<body><article><h1>Port closed</h1><p>{BODY}</p></article></body></html>"""
SRC = {"id": "x", "rate_limit": {"requests": 1, "per_seconds": 1}}
MSG = {"source_id": "x", "url": "https://x.test/story/1?utm=1"}


class MemStore:
    def __init__(self) -> None:
        self.rows: list[tuple[dict[str, Any], dict[str, Any], bytes]] = []
        self.dead: set[str] = set()

    def mark_dead(self, url: str) -> None:
        self.dead.add(url)

    def seen(self, canonical_url: str | None, text_hash: str) -> bool:
        return canonical_url in self.dead or any(
            canonical_url in (r[0]["canonical_url"], r[0]["url"]) or r[0]["text_hash"] == text_hash
            for r in self.rows
        )

    def save(
        self, raw_row: dict[str, Any], extracted_row: dict[str, Any], content: bytes, ext: str
    ) -> None:
        self.rows.append((raw_row, extracted_row, content))


def client(page: httpx.Response) -> PoliteClient:
    def h(req: httpx.Request) -> httpx.Response:
        return httpx.Response(404) if req.url.path == "/robots.txt" else page

    return PoliteClient(httpx.Client(transport=httpx.MockTransport(h)), sleep=lambda s: None)


def test_normalize_url() -> None:
    assert normalize_url("HTTPS://X.test/a/#frag") == "https://x.test/a"


def test_store_extract_and_dedupe() -> None:
    store = MemStore()
    http = client(httpx.Response(200, text=HTML))
    assert fetch_item(MSG, SRC, http, store).status == "stored"
    raw, ext, _ = store.rows[0]
    assert raw["canonical_url"] == "https://x.test/story/1" and raw["text_hash"]
    assert ext["status"] == "ok" and len(ext["summary"]) <= 500  # lede only, not the article
    # same URL again, and same text under another URL: both duplicates
    assert fetch_item(MSG, SRC, http, store).status == "duplicate"
    other = {**MSG, "url": "https://x.test/story/other"}
    page2 = HTML.replace("https://x.test/story/1/", "https://x.test/story/2/")
    assert (
        fetch_item(other, SRC, client(httpx.Response(200, text=page2)), store).status == "duplicate"
    )
    assert len(store.rows) == 1


def test_empty_page_records_extraction_failure() -> None:
    store = MemStore()
    res = fetch_item(MSG, SRC, client(httpx.Response(200, text="<html></html>")), store)
    assert res.status == "extract_failed" and store.rows[0][1]["status"] == "failed"


def test_robots_block_is_skipped_not_fetched() -> None:
    def h(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /")
        raise AssertionError("fetched a disallowed page")

    http = PoliteClient(httpx.Client(transport=httpx.MockTransport(h)), sleep=lambda s: None)
    assert fetch_item(MSG, SRC, http, MemStore()).status == "blocked"  # acked, not retried


def test_known_url_is_not_downloaded_again() -> None:
    store = MemStore()
    calls: list[str] = []

    def h(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.path)
        return (
            httpx.Response(404) if req.url.path == "/robots.txt" else httpx.Response(200, text=HTML)
        )

    http = PoliteClient(httpx.Client(transport=httpx.MockTransport(h)), sleep=lambda s: None)
    assert fetch_item(MSG, SRC, http, store).status == "stored"
    assert fetch_item(MSG, SRC, http, store).status == "duplicate"
    assert calls.count("/story/1") == 1


def test_published_at_is_a_full_timestamp() -> None:
    now = "2026-11-12T10:00:00+00:00"
    assert published_at("Wed, 11 Nov 2026 22:15:00 +0530", "", now) == "2026-11-11T16:45:00+00:00"
    meta = '<meta property="article:published_time" content="2026-11-12T08:30:00Z">'
    assert published_at(None, meta, now) == "2026-11-12T08:30:00+00:00"
    assert published_at("2026-11-12", "", now) == now  # bare date: fall back, never midnight
    assert published_at("2026-11-13T09:00:00+00:00", "", now) == now  # future: clamped


def _push(c: TestClient, msg: dict[str, Any]) -> httpx.Response:
    data = base64.b64encode(json.dumps(msg).encode()).decode()
    resp: httpx.Response = c.post("/", json={"message": {"data": data}})
    return resp


def test_push_endpoint_status_codes() -> None:
    store = MemStore()
    c = TestClient(create_app(store, client(httpx.Response(200, text=HTML)), {"x": SRC}))
    assert _push(c, MSG).status_code == 204 and len(store.rows) == 1
    assert _push(c, {**MSG, "source_id": "nope"}).status_code == 204  # unknown source: dropped
    bad = TestClient(create_app(store, client(httpx.Response(500)), {"x": SRC}))
    assert _push(bad, {**MSG, "url": "https://x.test/other"}).status_code == 502  # retried


def test_push_logs_one_structured_line(capsys: pytest.CaptureFixture[str]) -> None:
    c = TestClient(create_app(MemStore(), client(httpx.Response(200, text=HTML)), {"x": SRC}))
    _push(c, MSG)
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert line == {"event": "item_processed", "source_id": "x", "status": "stored"}


def test_normalize_url_drops_tracking_and_sorts_the_rest() -> None:
    bare = "https://x.test/a?id=3&page=2"
    assert normalize_url("https://x.test/a/?page=2&utm_source=x&id=3&fbclid=9") == bare
    assert normalize_url("https://x.test/a?utm_campaign=q") == "https://x.test/a"


def test_seen_check_uses_the_graph_not_a_bigquery_job() -> None:
    from services.fetcher.app import GcpStore

    class Bq:
        def query(self, *a: Any, **k: Any) -> Any:
            raise AssertionError("seen() must not run a BigQuery query job")

    class Db:
        def __init__(self) -> None:
            self.keys: set[str] = set()

        def execute(self, q: str, args: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
            if q.startswith("UNWIND"):
                self.keys |= set(args[0])
                return []
            return [
                {"stored": True, "fails": 0, "last": "2026-01-01T00:00:00+00:00"}
                for k in args[0]
                if k in self.keys
            ][:1]

    s = object.__new__(GcpStore)
    s._bq, s._db = Bq(), Db()  # type: ignore[assignment]
    assert not s.seen("https://x.test/a", "")
    s._mark_seen(
        {"url": "https://x.test/a?utm_source=x", "canonical_url": "https://x.test/a",
         "text_hash": "abc", "fetched_at": "2026-01-01T00:00:00+00:00"}
    )  # fmt: skip
    assert (
        s.seen("https://x.test/a", "")
        and s.seen(None, "abc")
        and not s.seen("https://x.test/b", "zzz")
    )


def test_domain_matching() -> None:
    from weft_core import domains

    ex = {"id": "ex", "domain": "example.com"}
    assert domains.owner_of("https://news.example.com/a", [ex]) == ex
    assert domains.owner_of("https://www.example.com/a", [ex]) == ex
    assert domains.owner_of("https://example.org/a", [ex]) is None
    co = {"id": "co", "domain": "bbc.co.uk"}
    assert domains.owner_of("https://www.bbc.co.uk/n", [co]) == co
    wired = {"id": "w", "domain": "x.test", "link_domains": ["cdn.partner.test"]}
    assert domains.owner_of("https://cdn.partner.test/p", [wired]) == wired


def test_redirect_to_the_feeds_own_article_is_stored_and_a_foreign_one_is_not() -> None:
    src = {**SRC, "domain": "x.test"}
    store = MemStore()
    r = fetch_item(MSG, src, client(httpx.Response(200, text=HTML)), store, [src])
    assert r.status == "stored" and store.rows[0][0]["source_id"] == "x"
    other = {**SRC, "id": "y", "domain": "y.test"}
    foreign = HTML.replace("https://x.test/story/1/", "https://elsewhere.example/story/1/")
    store2 = MemStore()
    r2 = fetch_item(MSG, src, client(httpx.Response(200, text=foreign)), store2, [src, other])
    assert r2.status == "foreign" and store2.rows == []
    moved = HTML.replace("https://x.test/story/1/", "https://y.test/story/1/")
    store3 = MemStore()
    r3 = fetch_item(MSG, src, client(httpx.Response(200, text=moved)), store3, [src, other])
    assert r3.status == "stored" and store3.rows[0][0]["source_id"] == "y"


def _page(headers: dict[str, str], body: bytes = b"x") -> httpx.Response:
    return httpx.Response(200, headers=headers, content=body)


def test_private_addresses_and_redirects_to_them_are_refused() -> None:
    from weft_core.polite import Refused

    for host in ("127.0.0.1", "10.0.0.5", "169.254.169.254"):
        with pytest.raises(Refused, match="address"):
            client(_page({"content-type": "text/html"})).get(f"http://{host}/a", 0, {})
    http = client(httpx.Response(302, headers={"location": "http://169.254.169.254/latest"}))
    msg = {"source_id": "x", "url": "https://x.test/r"}
    assert fetch_item(msg, SRC, http, MemStore()).status == "refused"


def test_scheme_and_redirect_limit() -> None:
    from weft_core.polite import Refused

    with pytest.raises(Refused, match="scheme"):
        client(_page({})).get("file:///etc/passwd", 0, {})
    loop = httpx.Response(302, headers={"location": "https://x.test/again"})
    with pytest.raises(Refused, match="redirects"):
        client(loop).get("https://x.test/a", 0, {})


def test_oversize_body_stops_early_and_is_permanent() -> None:
    big = _page({"content-type": "text/html"}, b"a" * 200)
    http = client(big)
    http._limits = {**http._limits, "max_html_bytes": 100}
    msg = {"source_id": "x", "url": "https://x.test/big"}
    store = MemStore()
    assert fetch_item(msg, SRC, http, store).status == "too_large" and not store.rows


def test_unsupported_type_never_reaches_the_extractor() -> None:
    msg = {"source_id": "x", "url": "https://x.test/img"}
    store = MemStore()
    r = fetch_item(msg, SRC, client(_page({"content-type": "image/png"}, b"\x89PNG")), store)
    assert r.status == "unsupported" and not store.rows


def test_xml_with_entity_declarations_is_rejected() -> None:
    from weft_core.polite import Refused

    bomb = b'<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaa">]><urlset>&a;</urlset>'
    with pytest.raises(Refused, match="entity"):
        client(_page({"content-type": "application/xml"}, bomb)).get("https://x.test/s.xml", 0, {})


def test_pdf_is_cut_at_the_page_cap_and_still_stored(monkeypatch: pytest.MonkeyPatch) -> None:
    import pdfplumber

    from services.fetcher import fetcher

    page = types.SimpleNamespace(extract_text=lambda: "Sentence 0 of the filing.")
    pdf = types.SimpleNamespace(pages=[page] * 2000, metadata={"Title": "Filing"})
    ctx = contextlib.nullcontext(pdf)
    monkeypatch.setattr(pdfplumber, "open", lambda f: ctx)
    d, ext = fetcher._extract(b"%PDF", "https://x.test/a.pdf", "application/pdf")
    assert ext == "pdf" and d["text"].count("Sentence 0 ") == fetcher.MAX_PDF_PAGES


def test_failed_extraction_is_retried_daily_up_to_three_times() -> None:
    from datetime import UTC, datetime, timedelta

    from services.fetcher.fetcher import seen_from_rows

    now = datetime(2026, 11, 14, 12, tzinfo=UTC)

    def failed(ago: timedelta) -> tuple[str | None, datetime]:
        return None, now - ago

    assert not seen_from_rows([], now)
    assert seen_from_rows([("abc", now - timedelta(days=9))], now)  # stored item
    assert seen_from_rows([failed(timedelta(hours=2))], now)  # too soon to retry
    assert not seen_from_rows([failed(timedelta(hours=25))], now)  # a day on: try again
    two = [failed(timedelta(days=2)), failed(timedelta(days=1, hours=1))]
    assert not seen_from_rows(two, now)
    assert seen_from_rows([*two, failed(timedelta(days=3))], now)  # third failure: give up
    # a retry that worked: the stored row wins over the earlier failure
    assert seen_from_rows([failed(timedelta(days=2)), ("abc", now)], now)


def _count(handler_status: int) -> tuple[PoliteClient, list[str]]:
    calls: list[str] = []

    def h(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.path)
        return (
            httpx.Response(404) if req.url.path == "/robots.txt" else httpx.Response(handler_status)
        )

    return PoliteClient(httpx.Client(transport=httpx.MockTransport(h)), sleep=lambda s: None), calls


def test_a_404_is_acknowledged_once_logged_dead_and_not_fetched_again(
    capsys: pytest.CaptureFixture[str],
) -> None:
    store = MemStore()
    http, calls = _count(404)
    c = TestClient(create_app(store, http, {"x": SRC}))
    assert _push(c, MSG).status_code == 204  # not a 502: Pub/Sub must not redeliver it
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert line["status"] == "dead"
    assert _push(c, MSG).status_code == 204  # the feed lists it again: a duplicate, no request
    assert calls.count("/story/1") == 1
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["status"] == "duplicate"


@pytest.mark.parametrize("status", [410, 403, 451])
def test_other_permanent_4xx_are_dead(status: int) -> None:
    http, _ = _count(status)
    assert fetch_item(MSG, SRC, http, MemStore()).status == "dead"


@pytest.mark.parametrize("status", [408, 500, 502])
def test_transient_statuses_are_retried(status: int) -> None:
    http, _ = _count(status)
    with pytest.raises(httpx.HTTPStatusError):
        fetch_item(MSG, SRC, http, MemStore())


def test_a_cooling_host_is_acknowledged_and_one_task_is_scheduled(
    capsys: pytest.CaptureFixture[str],
) -> None:
    http, _ = _count(429)
    tasks: list[tuple[dict[str, Any], Any]] = []
    c = TestClient(
        create_app(
            MemStore(),
            http,
            {"x": SRC},
            queue_for=lambda base: lambda body, when: tasks.append((body, when)),
        )
    )
    assert _push(c, MSG).status_code == 204  # no 503: the redelivery storm is gone
    assert len(tasks) == 1 and tasks[0][0]["fetch"] == MSG and tasks[0][0]["attempt"] == 1
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["status"] == "deferred"
    # the task comes back to /refetch with the same message; the host is still cooling
    assert c.post("/refetch", json=tasks[0][0]).status_code == 204
    assert len(tasks) == 2 and tasks[1][0]["attempt"] == 2


def test_deferral_stops_after_the_limit() -> None:
    from services.fetcher.app import MAX_DEFERRALS

    http, _ = _count(429)
    tasks: list[Any] = []
    c = TestClient(
        create_app(MemStore(), http, {"x": SRC}, queue_for=lambda b: lambda *a: tasks.append(a))
    )
    assert c.post("/refetch", json={"fetch": MSG, "attempt": MAX_DEFERRALS}).status_code == 204
    assert tasks == []


def test_a_refetch_blocked_by_robots_is_not_retried() -> None:
    def h(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="User-agent: *\nDisallow: /")

    http = PoliteClient(httpx.Client(transport=httpx.MockTransport(h)), sleep=lambda s: None)
    db = types.SimpleNamespace(execute=lambda *a, **k: [])
    files = types.SimpleNamespace(save_version=lambda *a: None)
    c = TestClient(create_app(MemStore(), http, {"x": SRC}, db=db, files=files))  # type: ignore[arg-type]
    task = {"item_id": "i", "source_id": "x", "url": MSG["url"], "n": 1}
    assert c.post("/refetch", json=task).status_code == 204
