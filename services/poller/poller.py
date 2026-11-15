"""Poll RSS/Atom feeds and news sitemaps and publish new item URLs to `items.new`.

Ingestion rules (CLAUDE.md): obey robots.txt, one connection per domain, back off on 429,
never bypass paywalls. The poller publishes an entry once: it remembers the URLs it already
published per feed (#161). The fetcher still dedupes (canonical URL + text hash) as a backstop.
"""

import hashlib
import random
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

import feedparser
import httpx

from weft_core import prefilter
from weft_core.polite import PoliteClient
from weft_core.urls import normalize_url


class PollSkipped(Exception):
    """robots.txt, a cooldown or a 429 stopped the request: not a success for feed health."""


@dataclass
class FeedState:
    etag: str | None = None
    last_modified: str | None = None
    seen: list[str] = field(default_factory=list)  # short hashes of published URLs, oldest first


class State(Protocol):
    def get(self, url: str) -> FeedState: ...
    def put(self, url: str, state: FeedState) -> None: ...


MIN_SEEN = 2000  # shortcut: grows to twice the feed when a sitemap is larger, then forgets oldest


def key(url: str) -> str:
    return hashlib.sha1(normalize_url(url).encode(), usedforsecurity=False).hexdigest()[:12]


Publish = Callable[[dict[str, Any]], None]


class Poller:
    def __init__(
        self,
        http: PoliteClient,
        state: State,
        publish: Publish,
        beats: list[dict[str, Any]] | None = None,
        sample_rate: float = 0.02,
        rng: random.Random | None = None,
    ) -> None:
        self._http, self._state, self._publish = http, state, publish
        self._beats, self._sample_rate = beats, sample_rate
        self._rng = rng or random.Random()
        # per source: how many entries were published, skipped as off-beat, or kept as a sample
        self.stats: dict[str, dict[str, int]] = {}

    def _conditional_get(
        self, url: str, interval: float
    ) -> tuple[httpx.Response, FeedState] | None:
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
        return resp, FeedState(resp.headers.get("ETag"), resp.headers.get("Last-Modified"), st.seen)

    def _publish_new(
        self,
        source: dict[str, Any],
        url: str,
        st: FeedState,
        entries: list[tuple[str, Any, Any, str | None]],
    ) -> int:
        """Publish entries not published before, then save the state (etag and the seen set)."""
        known = set(st.seen)
        n = 0
        stats = self.stats.setdefault(source["id"], {"published": 0, "skipped": 0, "sampled": 0})
        fresh = [e for e in entries if key(e[0]) not in known]
        verdicts = {
            link: "publish"
            if self._beats is None
            else prefilter.decide(self._beats, title, summary, self._sample_rate, self._rng)
            for link, title, _, summary in fresh
        }
        # on-beat entries first, so they are not queued behind the sampled ones
        for link, title, published, _ in sorted(fresh, key=lambda e: verdicts[e[0]] != "publish"):
            k = key(link)
            st.seen.append(k)  # decided once: a skipped entry is not drawn for again next poll
            known.add(k)
            if verdicts[link] == "skip":
                stats["skipped"] += 1
                continue
            self._emit(source, link, title, published)
            stats["sampled" if verdicts[link] == "sample" else "published"] += 1
            n += 1
        cap = max(MIN_SEEN, 2 * len(entries))
        st.seen = st.seen[-cap:]
        self._state.put(url, st)
        return n

    def poll_feed(self, source: dict[str, Any], url: str) -> int:
        got = self._conditional_get(url, _interval(source))
        if got is None:
            return 0
        resp, st = got
        entries = [
            (
                str(e["link"]),
                e.get("title"),
                e.get("published") or e.get("updated"),
                _plain(e.get("summary")),
            )
            for e in feedparser.parse(resp.content).entries
            if e.get("link")
        ]
        return self._publish_new(source, url, st, entries)

    def poll_sitemap(self, source: dict[str, Any], url: str) -> int:
        got = self._conditional_get(url, _interval(source))
        if got is None:
            return 0
        resp, st = got
        entries: list[tuple[str, Any, Any, str | None]] = [
            (el.text.strip(), None, None, None)
            for el in ET.fromstring(resp.content).iter()
            if el.tag.endswith("}loc") and el.text
        ]
        return self._publish_new(source, url, st, entries)

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


_TAGS = re.compile(r"<[^>]+>")


def _plain(html: Any) -> str | None:
    return _TAGS.sub(" ", str(html)) if html else None


def _interval(source: dict[str, Any]) -> float:
    rl = source["rate_limit"]
    return float(rl["per_seconds"] / rl["requests"])
