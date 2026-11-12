"""Polite HTTP for ingestion (CLAUDE.md): robots.txt, one connection per domain,
back off on 429, never bypass paywalls. Shared by the poller and the fetcher."""

import time
import urllib.robotparser
from collections.abc import Callable
from urllib.parse import urlsplit

import httpx

USER_AGENT = "WeftBot/0.1 (+https://github.com/msriv/weft)"
DEFAULT_BACKOFF_SECONDS = 300.0


class PoliteClient:
    def __init__(
        self,
        http: httpx.Client,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._http = http
        self._sleep, self._clock = sleep, clock
        self._last_request: dict[str, float] = {}  # host -> time of last request
        self._cooldown_until: dict[str, float] = {}  # host -> backoff end after 429
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    def allowed(self, url: str) -> bool:
        """False when robots.txt disallows the URL or cannot be read (cached per origin)."""
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

    def get(self, url: str, min_interval: float, headers: dict[str, str]) -> httpx.Response | None:
        """One polite GET. Returns None when skipped (robots, cooldown) or rate limited."""
        host = urlsplit(url).netloc
        now = self._clock()
        if self._cooldown_until.get(host, 0) > now:
            return None
        if not self.allowed(url):
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
