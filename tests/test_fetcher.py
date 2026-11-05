import base64
import json
from typing import Any

import httpx
from fastapi.testclient import TestClient

from services.fetcher.app import create_app
from services.fetcher.fetcher import fetch_item, normalize_url
from weft_core.polite import PoliteClient

BODY = " ".join(f"Sentence number {i} of the report." for i in range(60))
HTML = f"""<html><head><title>Port closed</title>
<link rel="canonical" href="https://x.test/story/1/"></head>
<body><article><h1>Port closed</h1><p>{BODY}</p></article></body></html>"""
SRC = {"id": "x", "rate_limit": {"requests": 1, "per_seconds": 1}}
MSG = {"source_id": "x", "url": "https://x.test/story/1?utm=1"}


class MemStore:
    def __init__(self) -> None:
        self.rows: list[tuple[dict[str, Any], dict[str, Any], bytes]] = []

    def seen(self, canonical_url: str | None, text_hash: str) -> bool:
        return any(
            r[0]["canonical_url"] == canonical_url or r[0]["text_hash"] == text_hash
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
    assert fetch_item(MSG, SRC, http, MemStore()).status == "skipped"


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
