from typing import Any

import httpx
import pytest

from services.poller.poller import FeedState, Poller, PollSkipped
from weft_core.polite import PoliteClient

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>A</title><link>https://x.test/a</link></item>
<item><title>B</title><link>https://x.test/b</link></item></channel></rss>"""
SITEMAP = b"""<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://x.test/c</loc></url></urlset>"""
SRC = {"id": "x", "rate_limit": {"requests": 1, "per_seconds": 10}}


class Mem:
    def __init__(self) -> None:
        self.d: dict[str, FeedState] = {}

    def get(self, url: str) -> FeedState:
        return self.d.get(url, FeedState())

    def put(self, url: str, state: FeedState) -> None:
        self.d[url] = state


def make(handler: Any, now: list[float] | None = None) -> tuple[Poller, list[dict[str, Any]], Mem]:
    out: list[dict[str, Any]] = []
    mem = Mem()
    t = now if now is not None else [0.0]
    polite = PoliteClient(
        httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda s: t.__setitem__(0, t[0] + s), clock=lambda: t[0],
    )  # fmt: skip
    p = Poller(polite, mem, out.append)
    return p, out, mem


def site(feed: httpx.Response, robots: str = "") -> Any:
    def h(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text=robots)
        return feed

    return h


def test_feed_publishes_items_and_stores_etag() -> None:
    p, out, mem = make(site(httpx.Response(200, content=RSS, headers={"ETag": "e1"})))
    assert p.poll_feed(SRC, "https://x.test/rss") == 2
    assert [m["url"] for m in out] == ["https://x.test/a", "https://x.test/b"]
    assert mem.d["https://x.test/rss"].etag == "e1"


def test_conditional_get_sends_etag_and_304_publishes_nothing() -> None:
    seen: list[str | None] = []

    def h(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        seen.append(req.headers.get("If-None-Match"))
        return httpx.Response(304)

    p, out, mem = make(h)
    mem.put("https://x.test/rss", FeedState(etag="e1"))
    assert p.poll_feed(SRC, "https://x.test/rss") == 0
    assert seen == ["e1"] and out == []


def test_sitemap() -> None:
    p, _, _ = make(site(httpx.Response(200, content=SITEMAP)))
    assert p.poll_sitemap(SRC, "https://x.test/sm.xml") == 1


def test_robots_disallow_is_obeyed() -> None:
    p, out, _ = make(site(httpx.Response(200, content=RSS), "User-agent: *\nDisallow: /"))
    with pytest.raises(PollSkipped):
        p.poll_feed(SRC, "https://x.test/rss")
    assert out == []


def test_robots_5xx_means_do_not_poll() -> None:
    p, _, _ = make(lambda r: httpx.Response(503))
    with pytest.raises(PollSkipped):
        p.poll_feed(SRC, "https://x.test/rss")


def test_429_backs_off_host() -> None:
    calls: list[str] = []

    def h(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        calls.append(req.url.path)
        return httpx.Response(429, headers={"Retry-After": "120"})

    t = [0.0]
    p, _, _ = make(h, t)
    with pytest.raises(PollSkipped):
        p.poll_feed(SRC, "https://x.test/rss")
    with pytest.raises(PollSkipped):
        p.poll_feed(SRC, "https://x.test/rss2")  # inside cooldown: no request
    assert calls == ["/rss"]
    t[0] = 200.0
    with pytest.raises(PollSkipped):  # still 429, but the request was made again
        p.poll_feed(SRC, "https://x.test/rss2")
    assert calls == ["/rss", "/rss2"]


def test_per_domain_rate_limit_sleeps() -> None:
    t = [0.0]
    p, _, _ = make(site(httpx.Response(200, content=RSS)), t)
    p.poll_feed(SRC, "https://x.test/rss")
    p.poll_feed(SRC, "https://x.test/rss2")
    assert t[0] >= 10


def test_run_reports_failing_source_and_continues() -> None:
    def h(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(500) if "bad" in req.url.host else httpx.Response(200, content=RSS)

    p, out, _ = make(h)
    bad = {**SRC, "id": "bad", "feeds": ["https://bad.test/rss"]}
    good = {**SRC, "id": "good", "feeds": ["https://x.test/rss"]}
    res = p.run([bad, good])
    assert res["bad"] and res["good"] is None and len(out) == 2
