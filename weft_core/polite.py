"""Polite HTTP for ingestion (CLAUDE.md): robots.txt, one connection per domain,
back off on 429, never bypass paywalls. Shared by the poller and the fetcher."""

import ipaddress
import socket
import time
import urllib.robotparser
from collections.abc import Callable
from urllib.parse import urljoin, urlsplit

import httpx

from weft_core import config

USER_AGENT = "WeftBot/0.1 (+https://github.com/msriv/weft)"
DEFAULT_BACKOFF_SECONDS = 300.0


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


class PoliteClient:
    def __init__(
        self,
        http: httpx.Client,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        limits: dict[str, int] | None = None,
    ) -> None:
        self._limits = limits or config.pipeline()["fetch"]
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
            resp = self._fetch(origin + "/robots.txt", {}, ROBOTS_MAX_BYTES, any_type=True)
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
        resp = self._fetch(url, headers)
        if resp.status_code in (429, 503):
            retry = resp.headers.get("Retry-After", "")
            delay = float(retry) if retry.isdigit() else DEFAULT_BACKOFF_SECONDS
            self._cooldown_until[host] = self._clock() + delay
            return None
        if resp.status_code != 304:
            resp.raise_for_status()
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
