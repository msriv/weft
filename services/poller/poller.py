"""Poll RSS/Atom feeds and news sitemaps and publish new item URLs to `items.new`.

Ingestion rules (CLAUDE.md): obey robots.txt, one connection per domain, back off on 429,
never bypass paywalls. Dedupe is the fetcher's job (canonical URL + text hash), so the
poller may publish a URL more than once.
"""

import time
import urllib.robotparser
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit

import feedparser
import httpx

USER_AGENT = "WeftBot/0.1 (+https://github.com/msriv/weft)"
DEFAULT_BACKOFF_SECONDS = 300.0


@dataclass
class FeedState:
    etag: str | None = None
    last_modified: str | None = None


class State(Protocol):
    def get(self, url: str) -> FeedState: ...
    def put(self, url: str, state: FeedState) -> None: ...


Publish = Callable[[dict[str, Any]], None]


class Poller:
    def __init__(
        self,
        http: httpx.Client,
        state: State,
        publish: Publish,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._http, self._state, self._publish = http, state, publish
        self._sleep, self._clock = sleep, clock
        self._last_request: dict[str, float] = {}  # host -> time of last request
        self._cooldown_until: dict[str, float] = {}  # host -> backoff end after 429
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    def _allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            resp = self._http.get(origin + "/robots.txt", headers={"User-Agent": USER_AGENT})
            if resp.status_code >= 500 or resp.status_code in (401, 403):
                self._robots[origin] = None  # unreachable or forbidden robots.txt: do not poll
            else:  # other 4xx means no robots.txt: allow all
                rp.parse(resp.text.splitlines() if resp.status_code == 200 else [])
                self._robots[origin] = rp
        rp_ = self._robots[origin]
        return rp_ is not None and rp_.can_fetch(USER_AGENT, url)

    def _get(self, url: str, min_interval: float, headers: dict[str, str]) -> httpx.Response | None:
        """One polite GET. Returns None when skipped (robots, cooldown) or rate limited."""
        host = urlsplit(url).netloc
        now = self._clock()
        if self._cooldown_until.get(host, 0) > now:
            return None
        if not self._allowed(url):
            return None
        wait = self._last_request.get(host, -1e9) + min_interval - self._clock()
        if wait > 0:
            self._sleep(wait)
        self._last_request[host] = self._clock()
        resp = self._http.get(url, headers={"User-Agent": USER_AGENT, **headers})
        if resp.status_code in (429, 503):
            retry = resp.headers.get("Retry-After", "")
            delay = float(retry) if retry.isdigit() else DEFAULT_BACKOFF_SECONDS
            self._cooldown_until[host] = self._clock() + delay
            return None
        if resp.status_code != 304:
            resp.raise_for_status()
        return resp

    def _conditional_get(self, url: str, interval: float) -> httpx.Response | None:
        st = self._state.get(url)
        headers = {}
        if st.etag:
            headers["If-None-Match"] = st.etag
        if st.last_modified:
            headers["If-Modified-Since"] = st.last_modified
        resp = self._get(url, interval, headers)
        if resp is None or resp.status_code == 304:
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
                self._emit(source, str(link), e.get("title"), e.get("published"))
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

    def run(self, sources: list[dict[str, Any]]) -> dict[str, str]:
        """Poll every source once. Returns {source_id: error} for sources that failed."""
        failures: dict[str, str] = {}
        for s in sources:
            try:
                for u in s.get("feeds", []):
                    self.poll_feed(s, u)
                for u in s.get("sitemaps", []):
                    self.poll_sitemap(s, u)
            except (httpx.HTTPError, ET.ParseError) as exc:
                failures[s["id"]] = str(exc)
        return failures


def _interval(source: dict[str, Any]) -> float:
    rl = source["rate_limit"]
    return float(rl["per_seconds"] / rl["requests"])
