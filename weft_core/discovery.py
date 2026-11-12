"""Automated source discovery (D11, D15). GDELT GKG says which outlets cover a beat; for each
outlet we do not know yet we find a feed, check it is live, and register it in the store.

GDELT only nominates domains. A source is registered only when its feed was fetched politely
and parsed with a recent entry. Country, ownership and state_run are left unverified (NULL):
nothing here has a citation for them.
"""

import io
import re
import zipfile
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from time import mktime
from urllib.parse import urljoin, urlsplit

import feedparser
import httpx

from weft_core import store
from weft_core.polite import PoliteClient

GDELT_LAST = "http://data.gdeltproject.org/gdeltv2/lastupdate.txt"
FALLBACK_PATHS = ("/feed", "/rss", "/rss.xml", "/feed.xml", "/atom.xml")
MIN_URLS = 3  # a domain needs this many matching articles in the window to be probed
MAX_AGE = timedelta(days=7)  # a feed with nothing newer than this is not live
PROBE_INTERVAL = 10.0


def parse_gkg(text: str) -> Iterable[tuple[str, str, str]]:
    """Yield (domain, url, searchable text) per GKG 2.1 row: URL, V1 themes/locations/persons/orgs."""
    for line in text.splitlines():
        f = line.split("\t")
        if len(f) > 13 and f[3] and f[4].startswith("http"):
            yield f[3].lower(), f[4], " ".join((f[4], f[7], f[9], f[11], f[13]))


def candidate_domains(
    rows: Iterable[tuple[str, str, str]], patterns: list[str], known: set[str]
) -> dict[str, set[str]]:
    """Unknown domains with the URLs of articles matching any beat pattern."""
    rx = re.compile("|".join(f"(?:{p})" for p in patterns), re.IGNORECASE)
    hits: dict[str, set[str]] = defaultdict(set)
    for domain, url, blob in rows:
        if domain not in known and rx.search(blob):
            hits[domain].add(url)
    return hits


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.feeds: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if (
            tag == "link"
            and a.get("href")
            and "alternate" in (a.get("rel") or "").lower()
            and (a.get("type") or "").lower() in ("application/rss+xml", "application/atom+xml")
        ):
            self.feeds.append(a["href"] or "")


def feed_urls(homepage: str, html: str) -> list[str]:
    """Declared feeds first, then conventional paths."""
    p = _Links()
    p.feed(html)
    origin = "{0.scheme}://{0.netloc}".format(urlsplit(homepage))
    return list(
        dict.fromkeys(
            [urljoin(homepage, h) for h in p.feeds] + [origin + path for path in FALLBACK_PATHS]
        )
    )


def feed_is_live(resp: httpx.Response, now: datetime) -> bool:
    entries = feedparser.parse(resp.content).entries
    stamps = [
        datetime.fromtimestamp(mktime(e.published_parsed), UTC)
        for e in entries
        if e.get("published_parsed") and e.get("link")
    ]
    return bool(stamps) and now - max(stamps) <= MAX_AGE


def verified_feeds(http: PoliteClient, domain: str, now: datetime) -> tuple[str, str, list[str]]:
    """(name, homepage, live feeds) for one domain. Empty feed list = nothing verified."""
    home = f"https://{domain}/"
    try:
        page = http.get(home, PROBE_INTERVAL, {})
    except httpx.HTTPError:
        return domain, home, []
    if page is None:
        return domain, home, []
    title = re.search(r"<title[^>]*>([^<]{1,120})", page.text, re.IGNORECASE)
    name = title.group(1).strip() if title else domain
    live: list[str] = []
    for url in feed_urls(str(page.url), page.text)[:6]:
        try:
            resp = http.get(url, PROBE_INTERVAL, {})
        except httpx.HTTPError:
            continue
        if resp is not None and feed_is_live(resp, now):
            live.append(url)
            break  # one verified feed is enough to register
    return name, home, live


def discover(
    db: store.Db, http: PoliteClient, gkg_text: str, now: datetime | None = None, limit: int = 20
) -> dict[str, list[str]]:
    """One pass over one GKG file. Returns {domain: feeds} for newly registered sources."""
    now = now or datetime.now(UTC)
    rows = list(parse_gkg(gkg_text))
    found: dict[str, list[str]] = {}
    for beat in store.beats(db):
        known = store.known_domains(db)
        hits = candidate_domains(rows, beat["patterns"], known)
        ranked = sorted(hits, key=lambda d: -len(hits[d]))
        for domain in [d for d in ranked if len(hits[d]) >= MIN_URLS][:limit]:
            name, home, feeds = verified_feeds(http, domain, now)
            store.register_source(
                db,
                domain=domain,
                name=name,
                homepage=home,
                feeds=feeds,
                via=f"gdelt:{beat['id']}",
                rejected=not feeds,
            )
            if feeds:
                found[domain] = feeds
    return found


def latest_gkg(http: httpx.Client, files: int = 1) -> str:
    """The newest `files` published GKG files (GDELT 2.0, one per 15 min), joined.
    One file is a thin sample; a domain rarely has MIN_URLS beat articles in 15 minutes."""
    index = http.get(GDELT_LAST)
    index.raise_for_status()
    url = next(line.split()[2] for line in index.text.splitlines() if "gkg.csv.zip" in line)
    texts: list[str] = []
    # the newest file is sometimes listed before it is served, and GDELT skips a slot now and
    # then: walk back one slot per file plus one spare
    for _ in range(files + 1):
        r = http.get(url)
        if r.status_code == 200:
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                texts.append(z.read(z.namelist()[0]).decode("utf-8", "replace"))
            if len(texts) == files:
                break
        url = _previous(url)
    if not texts:
        raise RuntimeError(f"GDELT GKG not available: {url}")
    return "\n".join(texts)


def _previous(url: str) -> str:
    m = re.search(r"/(\d{14})\.", url)
    assert m
    t = datetime.strptime(m.group(1), "%Y%m%d%H%M%S") - timedelta(minutes=15)
    return url.replace(m.group(1), t.strftime("%Y%m%d%H%M%S"))


def seed_beats(db: store.Db) -> None:
    """Initial beat inputs (Mihir, 2026-11-06). Patterns are regexes over GDELT fields in
    discovery and over title + lede in the stream worker; both are editable in the DB.
    Parties are proposals, stored without a citation until an admin confirms them (D15)."""
    for id_, name, pats, parties in BEATS:
        store.add_beat(db, id_, name, pats, parties=parties)


_CEC = r"chief[\s_-]*election[\s_-]*commissioner|election[\s_-]*commission"
BEATS: list[tuple[str, str, list[str], list[str]]] = [
    (
        "iran-israel-war",
        "Iran-Israel war",
        [r"\biran\b.*\bisrael\b|\bisrael\b.*\biran\b"],
        ["IR", "IL"],
    ),
    (
        "ukraine-russia-war",
        "Ukraine-Russia war",
        [r"\bukrain\w*\b.*\brussia\w*\b|\brussia\w*\b.*\bukrain\w*\b"],
        ["UA", "RU"],
    ),
    (
        "us-senate-democrats",
        "Democrats winning US Senate elections",
        [r"senate.*democrat|democrat.*senate"],
        ["Democratic Party", "Republican Party"],
    ),
    (
        "india-cec-impeachment",
        "Opposition move to impeach CEC Gyanesh Kumar",
        # the name alone, or impeach/removal talk next to the Election Commission
        [
            r"gyanesh[\s_-]*kumar",
            rf"(impeach|removal|remove)\w*.*({_CEC})|({_CEC}).*(impeach|removal|remove)\w*",
        ],
        ["Election Commission of India", "Indian opposition parties"],
    ),
]
