"""Polite client: robots.txt TTL, Crawl-delay, Retry-After forms, escalating backoff, shared cooldowns."""

from datetime import UTC, datetime, timedelta

import httpx

from weft_core import polite
from weft_core.polite import MemoryCooldowns, PoliteClient

LIMITS = {
    "max_html_bytes": 10**6,
    "max_pdf_bytes": 10**6,
    "max_redirects": 3,
    "deadline_seconds": 60,
    "max_pdf_pages": 10,
}
T0 = datetime(2026, 10, 21, 7, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def mono(self) -> float:
        return self.t

    def wall(self) -> datetime:
        return T0 + timedelta(seconds=self.t)

    def sleep(self, s: float) -> None:
        self.t += s


def client(handler, clock: Clock, cool=None) -> PoliteClient:  # type: ignore[no-untyped-def]
    return PoliteClient(
        httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=clock.sleep,
        clock=clock.mono,
        limits=LIMITS,
        cooldowns=cool,
        wall=clock.wall,
    )


def test_robots_refetched_after_ttl() -> None:
    clock, seen = Clock(), []

    def h(req: httpx.Request) -> httpx.Response:
        seen.append(req.url.path)
        return httpx.Response(
            200, text="User-agent: *\nAllow: /", headers={"content-type": "text/plain"}
        )

    c = client(h, clock)
    c.allowed("https://a.example/x")
    c.allowed("https://a.example/y")
    assert seen == ["/robots.txt"]
    clock.t += polite.ROBOTS_TTL_SECONDS + 1
    c.allowed("https://a.example/x")
    assert seen == ["/robots.txt", "/robots.txt"]


def test_failed_robots_is_retried_after_an_hour() -> None:
    clock, calls = Clock(), []

    def h(req: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectError("down")
        return httpx.Response(
            200, text="User-agent: *\nAllow: /", headers={"content-type": "text/plain"}
        )

    c = client(h, clock)
    assert c.allowed("https://a.example/x") is False  # unknown: do not fetch
    clock.t += 60
    assert c.allowed("https://a.example/x") is False and len(calls) == 1
    clock.t += polite.ROBOTS_RETRY_SECONDS
    assert c.allowed("https://a.example/x") is True and len(calls) == 2


def test_retry_after_both_forms_and_clamp() -> None:
    assert polite.retry_after("120", T0) == 120
    assert polite.retry_after("Wed, 21 Oct 2026 07:28:00 GMT", T0) == 28 * 60
    assert polite.retry_after("garbage", T0) is None


def _limited(retry: str | None):  # type: ignore[no-untyped-def]
    def h(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(429, headers={"Retry-After": retry} if retry else {})

    return h


def test_huge_retry_after_is_clamped() -> None:
    clock, cool = Clock(), MemoryCooldowns()
    c = client(_limited("86400"), clock, cool)
    assert c.get("https://a.example/p", 0, {}) is None
    assert cool.get("a.example")[0] == T0.timestamp() + polite.BACKOFF_MAX_SECONDS


def test_consecutive_429s_back_off_longer_and_success_resets() -> None:
    clock, cool = Clock(), MemoryCooldowns()
    ok: list[int] = []

    def h(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return (
            httpx.Response(200, text="hi", headers={"content-type": "text/html"})
            if ok
            else httpx.Response(429)
        )

    c = client(h, clock, cool)
    waits = []
    for _ in range(3):
        assert c.get("https://a.example/p", 0, {}) is None
        until = cool.get("a.example")[0]
        waits.append(until - clock.wall().timestamp())
        clock.t = until - T0.timestamp() + 1
    assert waits[0] < waits[1] < waits[2]
    ok.append(1)
    assert c.get("https://a.example/p", 0, {}) is not None
    assert cool.get("a.example")[1] == 0


def test_cooldown_set_elsewhere_is_seen() -> None:
    clock, cool = Clock(), MemoryCooldowns()
    cool.set("a.example", T0.timestamp() + 600, 1)  # as if the fetcher had set it
    c = client(
        lambda r: httpx.Response(200, text="x", headers={"content-type": "text/html"}), clock, cool
    )
    assert c.get("https://a.example/p", 0, {}) is None


def test_crawl_delay_slows_a_fast_source() -> None:
    clock = Clock()

    def h(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(
                200, text="User-agent: *\nCrawl-delay: 30", headers={"content-type": "text/plain"}
            )
        return httpx.Response(200, text="x", headers={"content-type": "text/html"})

    c = client(h, clock)
    c.get("https://a.example/1", 10, {})
    before = clock.t
    c.get("https://a.example/2", 10, {})
    assert clock.t - before >= 30


def test_a_cooldown_on_one_host_does_not_delay_another() -> None:
    clock = Clock()

    def h(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(429) if req.url.host == "a.test" else httpx.Response(200, text="ok")

    c = client(h, clock)
    assert c.get("https://a.test/1", 10.0, {}) is None  # A is cooling down
    before = clock.t
    assert c.get("https://b.test/1", 10.0, {}) is not None
    assert clock.t == before  # B did not wait for A, and had no earlier request to wait for
    assert c.ready_at("https://a.test/2") is not None and c.ready_at("https://b.test/2") is None


def test_concurrent_requests_to_one_host_never_overlap_and_keep_the_interval() -> None:
    import threading
    import time

    active, peak, starts = 0, 0, []
    guard = threading.Lock()

    def h(req: httpx.Request) -> httpx.Response:
        nonlocal active, peak
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        with guard:
            active += 1
            peak = max(peak, active)
            starts.append(time.monotonic())
        time.sleep(0.02)
        with guard:
            active -= 1
        return httpx.Response(200, text="ok")

    c = PoliteClient(httpx.Client(transport=httpx.MockTransport(h)), limits=LIMITS)
    threads = [
        threading.Thread(target=c.get, args=(f"https://a.test/{i}", 0.1, {})) for i in range(3)
    ]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert peak == 1
    assert (
        len(starts) == 3 and min(b - a for a, b in zip(sorted(starts), sorted(starts)[1:])) >= 0.09
    )
