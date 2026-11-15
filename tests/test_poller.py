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


def test_second_poll_of_the_same_feed_publishes_nothing_and_a_new_entry_alone() -> None:
    body = [RSS]
    p, out, _ = make(
        lambda r: httpx.Response(404 if r.url.path == "/robots.txt" else 200, content=body[0])
    )
    assert p.poll_feed(SRC, "https://x.test/rss") == 2
    assert p.poll_feed(SRC, "https://x.test/rss") == 0
    body[0] = RSS.replace(
        b"</channel>",
        b"<item><title>C</title><link>https://x.test/c?utm_source=z</link></item></channel>",
    )
    assert p.poll_feed(SRC, "https://x.test/rss") == 1
    assert [m["url"] for m in out] == [
        "https://x.test/a", "https://x.test/b", "https://x.test/c?utm_source=z",
    ]  # fmt: skip


def test_tracking_parameters_do_not_make_an_entry_new() -> None:
    body = [RSS]
    p, _, _ = make(
        lambda r: httpx.Response(404 if r.url.path == "/robots.txt" else 200, content=body[0])
    )
    p.poll_feed(SRC, "https://x.test/rss")
    body[0] = RSS.replace(b"x.test/a<", b"x.test/a?utm_source=tw&fbclid=1<")
    assert p.poll_feed(SRC, "https://x.test/rss") == 0


FEED10 = (
    b'<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>'
    + b"".join(
        f"<item><title>{t}</title><link>https://x.test/{i}</link>"
        f"<description>{d}</description></item>".encode()
        for i, (t, d) in enumerate(
            [("Iran strikes Israel", "missiles"), ("Cat show", "fluffy")] * 2
            + [("Cooking tips", "pasta")] * 4
            + [("Israel Iran war talks", "<b>diplomats</b>"), ("Garden", "roses")]
        )
    )
    + b"</channel></rss>"
)
BEATS = [{"id": "w", "name": "w", "patterns": [r"\bIran\b", r"\bIsrael\b"], "exclude": []}]


def beat_poller(rate: float = 0.0) -> tuple[Poller, list[dict[str, Any]]]:
    out: list[dict[str, Any]] = []
    polite = PoliteClient(
        httpx.Client(transport=httpx.MockTransport(site(httpx.Response(200, content=FEED10)))),
        sleep=lambda s: None,
    )
    import random

    return Poller(polite, Mem(), out.append, BEATS, rate, random.Random(1)), out


def test_prefilter_publishes_only_entries_that_match_a_beat() -> None:
    p, out = beat_poller()
    p.poll_feed(SRC, "https://x.test/rss")
    assert [m["url"] for m in out] == ["https://x.test/0", "https://x.test/2", "https://x.test/8"]
    assert p.stats["x"] == {"published": 3, "skipped": 7, "sampled": 0, "foreign": 0}


def test_prefilter_sample_still_flows_and_is_counted() -> None:
    p, out = beat_poller(rate=1.0)
    p.poll_feed(SRC, "https://x.test/rss")
    assert len(out) == 10 and p.stats["x"]["sampled"] == 7
    assert [m["url"] for m in out[:3]] == [
        "https://x.test/0",
        "https://x.test/2",
        "https://x.test/8",
    ]


def test_entries_without_title_or_summary_are_published() -> None:
    p, out = beat_poller()
    p._publish_new(SRC, "u", FeedState(), [("https://x.test/s1", None, None, None)])
    assert len(out) == 1


def test_a_skipped_entry_is_not_drawn_for_again() -> None:
    p, out = beat_poller(rate=0.5)
    p.poll_feed(SRC, "https://x.test/rss")
    n = len(out)
    p.poll_feed(SRC, "https://x.test/rss")
    assert len(out) == n


def test_replay_prefilter_check() -> None:
    from evals.replay import prefilter_misses

    rows = [
        {"id": "a", "title": "Iran fires", "summary": ""},
        {"id": "b", "title": "Talks resume", "summary": "no names"},
    ]
    assert prefilter_misses(rows, BEATS) == ["b"]


def test_link_to_another_registered_source_is_reported_under_that_source() -> None:
    a = {**SRC, "id": "a", "domain": "a.test"}
    b = {**SRC, "id": "b", "domain": "b.test"}
    feed = (
        b'<rss version="2.0"><channel><item><title>x</title><link>https://a.test/1</link></item>'
        b"<item><title>y</title><link>https://news.b.test/2</link></item>"
        b"<item><title>z</title><link>https://www.a.test/3</link></item>"
        b"<item><title>w</title><link>https://unknown.example/4</link></item></channel></rss>"
    )
    out: list[dict[str, Any]] = []
    foreign: list[str] = []
    polite = PoliteClient(
        httpx.Client(transport=httpx.MockTransport(site(httpx.Response(200, content=feed)))),
        sleep=lambda s: None,
    )
    p = Poller(polite, Mem(), out.append, on_foreign=lambda d, u: foreign.append(d))
    p.run([{**a, "feeds": ["https://a.test/rss"]}, b])
    assert [(m["url"], m["source_id"]) for m in out] == [
        ("https://a.test/1", "a"),
        ("https://news.b.test/2", "b"),
        ("https://www.a.test/3", "a"),
    ]
    assert foreign == ["unknown.example"] and p.stats["a"]["foreign"] == 1
