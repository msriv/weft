"""Poll RSS/Atom feeds and news sitemaps and publish new item URLs to `items.new`.

Ingestion rules (CLAUDE.md): obey robots.txt, one connection per domain, back off on 429,
never bypass paywalls. Dedupe is the fetcher's job (canonical URL + text hash), so the
poller may publish a URL more than once.
"""

import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import feedparser
import httpx

from weft_core.polite import PoliteClient


class PollSkipped(Exception):
    """robots.txt, a cooldown or a 429 stopped the request: not a success for feed health."""


@dataclass
class FeedState:
    etag: str | None = None
    last_modified: str | None = None


class State(Protocol):
    def get(self, url: str) -> FeedState: ...
    def put(self, url: str, state: FeedState) -> None: ...


Publish = Callable[[dict[str, Any]], None]


class Poller:
    def __init__(self, http: PoliteClient, state: State, publish: Publish) -> None:
        self._http, self._state, self._publish = http, state, publish

    def _conditional_get(self, url: str, interval: float) -> httpx.Response | None:
        st = self._state.get(url)
        headers = {}
        if st.etag:
            headers["If-None-Match"] = st.etag
        if st.last_modified:
            headers["If-Modified-Since"] = st.last_modified
        resp = self._http.get(url, interval, headers)
        if resp is None:
            raise PollSkipped(f"{url}: blocked by robots.txt or backing off")
        if resp.status_code == 304:
            return None
        self._state.put(url, FeedState(resp.headers.get("ETag"), resp.headers.get("Last-Modified")))
        return resp

    def poll_feed(self, source: dict[str, Any], url: str) -> int:
        resp = self._conditional_get(url, _interval(source))
        if resp is None:
            return 0
        n = 0
        for e in feedparser.parse(resp.content).entries:
            if link := e.get("link"):
                self._emit(
                    source, str(link), e.get("title"), e.get("published") or e.get("updated")
                )
                n += 1
        return n

    def poll_sitemap(self, source: dict[str, Any], url: str) -> int:
        resp = self._conditional_get(url, _interval(source))
        if resp is None:
            return 0
        n = 0
        for el in ET.fromstring(resp.content).iter():
            if el.tag.endswith("}loc") and el.text:
                self._emit(source, el.text.strip(), None, None)
                n += 1
        return n

    def _emit(self, source: dict[str, Any], url: str, title: Any, published: Any) -> None:
        self._publish(
            {"source_id": source["id"], "url": url, "title": title, "published": published}
        )

    def run(self, sources: list[dict[str, Any]]) -> dict[str, str | None]:
        """Poll every source once. Returns {source_id: error}, with None for a healthy source."""
        out: dict[str, str | None] = {}
        for s in sources:
            try:
                for u in s.get("feeds", []):
                    self.poll_feed(s, u)
                for u in s.get("sitemaps", []):
                    self.poll_sitemap(s, u)
                out[s["id"]] = None
            except (httpx.HTTPError, ET.ParseError, PollSkipped) as exc:
                out[s["id"]] = str(exc)
        return out


def _interval(source: dict[str, Any]) -> float:
    rl = source["rate_limit"]
    return float(rl["per_seconds"] / rl["requests"])
