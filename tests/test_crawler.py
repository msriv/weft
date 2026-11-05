from typing import Any

import httpx

from services.crawler.crawler import crawl_source
from services.fetcher.fetcher import ingest
from tests.test_fetcher import MemStore
from weft_core.polite import PoliteClient

PRESS = """<html><body>
<a href="/press/a">A</a> <a href="/press/doc.pdf">PDF</a> <a href="/other/x">X</a>
<a href="https://elsewhere.test/press/y">Y</a> <a href="/press/a#frag">A again</a>
</body></html>"""


def page(n: str) -> str:
    body = " ".join(f"Statement {n} sentence {i}." for i in range(60))
    return (
        f"<html><head><title>{n}</title></head><body><article><p>{body}</p></article></body></html>"
    )


def pdf_bytes(text: str) -> bytes:
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            "/Resources << /Font << /F1 5 0 R >> >> >>"
        ),
        None,
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    stream = f"BT /F1 12 Tf 72 700 Td ({text}) Tj ET"
    objs[3] = f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream"
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return out


class Hashes:
    def __init__(self) -> None:
        self.d: dict[str, str] = {}

    def get(self, url: str) -> str | None:
        return self.d.get(url)

    def put(self, url: str, content_hash: str) -> None:
        self.d[url] = content_hash


SRC: dict[str, Any] = {
    "id": "mod",
    "rate_limit": {"requests": 1, "per_seconds": 1},
    "crawl": {"start_urls": ["https://gov.test/press/"], "allow": ["^/press/"], "max_depth": 2},
}


def site(pages: dict[str, httpx.Response], hits: list[str]) -> PoliteClient:
    def h(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        hits.append(req.url.path)
        return pages.get(req.url.path, httpx.Response(404))

    return PoliteClient(httpx.Client(transport=httpx.MockTransport(h)), sleep=lambda s: None)


def test_pdf_text_is_extracted() -> None:
    store = MemStore()
    text = "Order number 42 on port access. " * 5
    res = ingest(
        {"source_id": "m", "url": "https://gov.test/a.pdf"},
        pdf_bytes(text),
        "application/pdf",
        200,
        store,
    )
    assert res.status == "stored" and "Order number 42" in store.rows[0][1]["summary"]


def test_crawl_ingests_allowed_pages_and_detects_change() -> None:
    hits: list[str] = []
    html = {"content-type": "text/html"}
    pages = {
        "/press/": httpx.Response(200, text=PRESS, headers=html),
        "/press/a": httpx.Response(200, text=page("a"), headers=html),
        "/press/doc.pdf": httpx.Response(
            200,
            content=pdf_bytes("Official order text " * 8),
            headers={"content-type": "application/pdf"},
        ),
    }
    store, state = MemStore(), Hashes()
    first = crawl_source(SRC, site(pages, hits), store, state)
    assert first["stored"] == 2  # the page and the PDF; the listing page is not stored
    assert "/other/x" not in hits and all("elsewhere" not in h for h in hits)

    again = crawl_source(SRC, site(pages, []), store, state)
    assert again["stored"] == 0 and again["unchanged"] == 2

    pages["/press/a"] = httpx.Response(200, text=page("a changed"), headers=html)
    changed = crawl_source(SRC, site(pages, []), store, state)
    assert changed["stored"] == 1 and len(store.rows) == 3  # new version, old one kept


def test_blocked_start_page_is_skipped() -> None:
    def h(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="User-agent: *\nDisallow: /")

    http = PoliteClient(httpx.Client(transport=httpx.MockTransport(h)), sleep=lambda s: None)
    assert crawl_source(SRC, http, MemStore(), Hashes())["skipped"] == 1
