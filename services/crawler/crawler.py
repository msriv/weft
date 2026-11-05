"""Crawl government/parliament/court portals and ingest documents that are new or changed.

Start URLs are listing pages: they are walked for links but not stored. Linked pages and PDFs
under `crawl.allow` are ingested as versions: an unchanged content hash is skipped, a changed
one becomes a new version (same URL, new text hash).
"""

import hashlib
import re
from html.parser import HTMLParser
from typing import Any, Protocol
from urllib.parse import urldefrag, urljoin, urlsplit

from services.fetcher.fetcher import Store, ingest, interval
from weft_core.polite import PoliteClient

MAX_PAGES = 200  # shortcut: per-source cap per run; raise or paginate when a portal needs more


class HashState(Protocol):
    def get(self, url: str) -> str | None: ...
    def put(self, url: str, content_hash: str) -> None: ...


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self.hrefs += [v for k, v in attrs if k == "href" and v]


def crawl_source(
    source: dict[str, Any], http: PoliteClient, store: Store, state: HashState
) -> dict[str, int]:
    cfg = source["crawl"]
    allow = [re.compile(p) for p in cfg.get("allow", [])]
    start = cfg["start_urls"]
    hosts = {urlsplit(u).netloc for u in start}
    max_depth = cfg.get("max_depth", 1)
    counts = {"stored": 0, "unchanged": 0, "skipped": 0, "other": 0}
    seen = set(start)
    queue = [(u, 0) for u in start]
    while queue and len(seen) <= MAX_PAGES:
        url, depth = queue.pop(0)
        resp = http.get(url, interval(source), {})
        if resp is None:
            counts["skipped"] += 1
            continue
        ctype = resp.headers.get("content-type", "")
        digest = hashlib.sha256(resp.content).hexdigest()
        if depth > 0:
            if state.get(url) == digest:
                counts["unchanged"] += 1
            else:
                res = ingest(
                    {"source_id": source["id"], "url": url},
                    resp.content,
                    ctype,
                    resp.status_code,
                    store,
                    versioned=True,
                )
                counts["stored" if res.status == "stored" else "other"] += 1
                state.put(url, digest)
        if depth < max_depth and "html" in ctype:
            parser = _Links()
            parser.feed(resp.text)
            for href in parser.hrefs:
                link = urldefrag(urljoin(url, href))[0]
                p = urlsplit(link)
                ok = p.scheme in ("http", "https") and p.netloc in hosts
                if ok and link not in seen and (not allow or any(a.search(p.path) for a in allow)):
                    seen.add(link)
                    queue.append((link, depth + 1))
    return counts
