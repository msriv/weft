"""Polite HTTP for ingestion (CLAUDE.md): robots.txt, one connection per domain,
back off on 429, never bypass paywalls. Shared by the poller and the fetcher."""

import ipaddress
import os
import socket
import time
import urllib.robotparser
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any, Protocol
from urllib.parse import urljoin, urlsplit

import httpx

from weft_core import config

# BOT_CONTACT_URL: a public page that says what the bot does and how to opt out (/bot on the site).
USER_AGENT = (
    f"WeftBot/0.1 (+{os.environ.get('BOT_CONTACT_URL') or 'https://github.com/msriv/weft'})"
)
DEFAULT_BACKOFF_SECONDS = 300.0
BACKOFF_MAX_SECONDS = 3600.0  # shortcut: constants, not config; move to pipeline.yaml if tuned
CRAWL_DELAY_MAX_SECONDS = 60.0
ROBOTS_TTL_SECONDS = 24 * 3600.0
ROBOTS_RETRY_SECONDS = 3600.0


ROBOTS_MAX_BYTES = 500_000
OK_TYPES = ("text/", "application/xhtml", "application/xml", "application/pdf")
OK_XML_SUFFIX = ("+xml",)  # application/rss+xml, application/atom+xml, ...


class Refused(httpx.HTTPError):
    """A permanent refusal, not worth a retry: `reason` is address, scheme, redirects,
    too_large, timeout, unsupported or entity."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


def resolve(host: str) -> list[str]:
    """Every address the host resolves to. shortcut: the connection resolves again, so a
    rebinding DNS server could still win the race; pin the address in the transport if needed."""
    try:
        return sorted({str(i[4][0]) for i in socket.getaddrinfo(host, None)})
    except socket.gaierror as exc:
        raise Refused("address", f"{host} does not resolve") from exc


def check_url(url: str) -> None:
    """Refuse non-http(s) URLs and hosts that are, or resolve to, a non-public address
    (loopback, private, link-local, metadata, reserved)."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise Refused("scheme", url[:100])
    for addr in resolve(parts.hostname):
        if not ipaddress.ip_address(addr.split("%")[0]).is_global:
            raise Refused("address", f"{parts.hostname} -> {addr}")


def retry_after(value: str, now: datetime) -> float | None:
    """Seconds from a Retry-After header, in either form (delta-seconds or HTTP-date)."""
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        return max(0.0, (parsedate_to_datetime(value) - now).total_seconds())
    except (TypeError, ValueError):
        return None


class Cooldowns(Protocol):
    """Per-host backoff shared by every service that fetches: (until epoch seconds, strikes)."""

    def get(self, host: str) -> tuple[float, int]: ...
    def set(self, host: str, until: float, strikes: int) -> None: ...


class MemoryCooldowns:
    def __init__(self) -> None:
        self._d: dict[str, tuple[float, int]] = {}

    def get(self, host: str) -> tuple[float, int]:
        return self._d.get(host, (0.0, 0))

    def set(self, host: str, until: float, strikes: int) -> None:
        self._d[host] = (until, strikes)


class HostCooldowns:
    """Cooldowns kept on a `Host` node, so the poller, crawler and fetcher share them and a
    restart keeps them."""

    def __init__(self, db: Any) -> None:
        self._db = db

    def get(self, host: str) -> tuple[float, int]:
        rows = self._db.execute(
            "MATCH (h:Host {name: ?}) RETURN h.cooldown_until AS u, h.strikes AS n", (host,)
        )
        return (float(rows[0]["u"] or 0), int(rows[0]["n"] or 0)) if rows else (0.0, 0)

    def set(self, host: str, until: float, strikes: int) -> None:
        self._db.execute(
            "MERGE (h:Host {name: ?}) SET h.cooldown_until = ?, h.strikes = ?",
            (host, until, strikes),
        )


class PoliteClient:
    def __init__(
        self,
        http: httpx.Client,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        limits: dict[str, int] | None = None,
        cooldowns: Cooldowns | None = None,
        wall: Callable[[], datetime] | None = None,
    ) -> None:
        self._limits = limits or config.pipeline()["fetch"]
        self._cool: Cooldowns = cooldowns or MemoryCooldowns()
        # Wall time follows the injected clock, so a test clock moves cooldowns too.
        t0 = datetime.now(UTC) - timedelta(seconds=clock())
        self._wall = wall or (lambda: t0 + timedelta(seconds=clock()))
        self._http = http
        self._sleep, self._clock = sleep, clock
        self._last_request: dict[str, float] = {}  # host -> time of last request
        # origin -> (parsed robots or None when unknown, time to look again)
        self._robots: dict[str, tuple[urllib.robotparser.RobotFileParser | None, float]] = {}

    def _rules(self, url: str) -> urllib.robotparser.RobotFileParser | None:
        """robots.txt for the URL's origin, cached with a TTL. None means unknown (unreachable
        or forbidden): do not fetch, look again after ROBOTS_RETRY_SECONDS."""
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        hit = self._robots.get(origin)
        if hit and hit[1] > self._clock():
            return hit[0]
        rp: urllib.robotparser.RobotFileParser | None = urllib.robotparser.RobotFileParser()
        ttl = ROBOTS_TTL_SECONDS
        try:
            resp = self._fetch(origin + "/robots.txt", {}, ROBOTS_MAX_BYTES, any_type=True)
        except Refused:
            raise  # permanent (address, scheme, redirects): the caller records the reason
        except httpx.HTTPError:
            resp = None  # connection error or timeout: unknown for now
        if resp is None or resp.status_code >= 500 or resp.status_code in (401, 403):
            rp, ttl = None, ROBOTS_RETRY_SECONDS
        else:  # other 4xx means no robots.txt: allow all
            assert rp is not None
            rp.parse(resp.text.splitlines() if resp.status_code == 200 else [])
        self._robots[origin] = (rp, self._clock() + ttl)
        return rp

    def allowed(self, url: str) -> bool:
        """False when robots.txt disallows the URL or cannot be read."""
        rp = self._rules(url)
        return rp is not None and rp.can_fetch(USER_AGENT, url)

    def get(self, url: str, min_interval: float, headers: dict[str, str]) -> httpx.Response | None:
        """One polite GET. Returns None when skipped (robots, cooldown) or rate limited."""
        host = urlsplit(url).netloc
        until, strikes = self._cool.get(host)
        if until > self._wall().timestamp():
            return None
        if not self.allowed(url):
            return None
        rp = self._rules(url)
        delay = rp.crawl_delay(USER_AGENT) if rp else None
        if delay:
            min_interval = max(min_interval, min(float(delay), CRAWL_DELAY_MAX_SECONDS))
        wait = self._last_request.get(host, -1e9) + min_interval - self._clock()
        if wait > 0:
            self._sleep(wait)
        self._last_request[host] = self._clock()
        resp = self._fetch(url, headers)
        if resp.status_code in (429, 503):
            hinted = retry_after(resp.headers.get("Retry-After", ""), self._wall())
            wait_s = hinted if hinted is not None else DEFAULT_BACKOFF_SECONDS * 2**strikes
            until = self._wall().timestamp() + min(wait_s, BACKOFF_MAX_SECONDS)
            self._cool.set(host, until, strikes + 1)
            return None
        if resp.status_code != 304:
            resp.raise_for_status()
        if strikes:
            self._cool.set(host, 0.0, 0)  # success resets the strikes
        return resp

    def _fetch(
        self,
        url: str,
        headers: dict[str, str],
        max_bytes: int | None = None,
        any_type: bool = False,
    ) -> httpx.Response:
        """GET with the address check on every hop (redirects are followed by hand), a body
        size cap, a total deadline and a content-type allowlist."""
        lim = self._limits
        deadline = self._clock() + lim["deadline_seconds"]
        for _ in range(lim["max_redirects"] + 1):
            check_url(url)
            with self._http.stream(
                "GET",
                url,
                headers={"User-Agent": USER_AGENT, **headers},
                follow_redirects=False,
            ) as r:
                if r.is_redirect and (loc := r.headers.get("location")):
                    url = urljoin(url, loc)
                    continue
                kind = r.headers.get("content-type", "").split(";")[0].strip().lower()
                if not any_type and r.status_code < 400 and not _allowed(kind, url):
                    raise Refused("unsupported", kind)
                cap = max_bytes or lim["max_pdf_bytes" if "pdf" in kind else "max_html_bytes"]
                if (n := r.headers.get("content-length", "")).isdigit() and int(n) > cap:
                    raise Refused("too_large", n)
                body = bytearray()
                for chunk in r.iter_bytes():
                    body += chunk
                    if len(body) > cap:
                        raise Refused("too_large", f">{cap}")
                    if self._clock() > deadline:
                        raise Refused("timeout", url[:100])
                if b"<!ENTITY" in body and ("xml" in kind or body.lstrip()[:5] == b"<?xml"):
                    raise Refused("entity", "XML with entity declarations")
                return httpx.Response(
                    r.status_code, headers=r.headers, content=bytes(body), request=r.request
                )
        raise Refused("redirects", url[:100])


def _allowed(kind: str, url: str) -> bool:
    return (
        not kind
        or kind.startswith(OK_TYPES)
        or kind.endswith(OK_XML_SUFFIX)
        or (kind == "application/octet-stream" and url.lower().endswith(".pdf"))
    )
