"""Automated portal discovery (D15): official sites are found from the links news articles make.

When the fetcher extracts a news article it records outbound links to government-looking domains
(`portal_candidates`). Discovery probes the domains that were linked often enough, looks for a
press, news or transcripts section on the homepage, and registers the portal with a crawl config.
Nothing is hand-listed. Country and state_run stay unverified (NULL): no citation exists for them.
"""

import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from weft_core import store
from weft_core.polite import PoliteClient

GOV = re.compile(
    r"(^|\.)(gov|gob|gouv|govt|mil|parliament|sansad|knesset|rada|kremlin|congress|senate|"
    r"president)(\.|$)|(^|\.)(eci|mod|mfa|mid|idf)\.[a-z.]+$",
    re.IGNORECASE,
)
PARLIAMENT = re.compile(r"parliament|sansad|knesset|rada|congress|senate|duma|lok", re.IGNORECASE)
SECTIONS = re.compile(
    r"/(press|news|media|releases?|statements?|speeches|transcripts?|debates?|proceedings|"
    r"orders?|notifications?|gazette)(/|$|-)",
    re.IGNORECASE,
)
PROBE_INTERVAL = 10.0
MIN_HITS = 3  # links from this many on-beat reports (stream worker) before probing


def is_gov(domain: str) -> bool:
    return bool(GOV.search(domain))


class _Hrefs(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self.hrefs += [v for k, v in attrs if k == "href" and v]


def hrefs(html: str, base: str) -> list[str]:
    p = _Hrefs()
    p.feed(html)
    return [urljoin(base, h) for h in p.hrefs]


def outbound_gov_domains(html: str, base_url: str) -> set[str]:
    """Government-looking domains other than the page's own that the page links to."""
    own = urlsplit(base_url).netloc.lower()
    out = set()
    for h in hrefs(html, base_url):
        p = urlsplit(h)
        host = p.netloc.lower().split(":")[0]
        if p.scheme in ("http", "https") and host and host != own and is_gov(host):
            out.add(host.removeprefix("www."))
    return out


def record_candidates(db: store.Db, domains: set[str], example_url: str) -> None:
    now = datetime.now(UTC).isoformat()
    for d in domains:
        db.execute(
            "MERGE (n:PortalCandidate {domain: ?}) ON CREATE SET n.hits=0, n.example_url=? "
            "SET n.hits=n.hits+1, n.last_seen=?",
            (d, example_url, now),
        )


def sections(homepage: str, html: str) -> list[str]:
    """Same-site links that look like press / news / transcript listings, shortest paths first."""
    host = urlsplit(homepage).netloc.lower().removeprefix("www.")
    found = {
        h.split("#")[0]
        for h in hrefs(html, homepage)
        if urlsplit(h).netloc.lower().removeprefix("www.") == host
        and SECTIONS.search(urlsplit(h).path)
    }
    return sorted(found, key=lambda u: (len(urlsplit(u).path), u))[:5]


def discover_portals(db: store.Db, http: PoliteClient, limit: int = 10) -> dict[str, list[str]]:
    """Probe frequently linked, unknown government domains. Returns {domain: start_urls}."""
    known = store.known_domains(db)
    rows = db.execute(
        "MATCH (n:PortalCandidate) WHERE n.hits >= ? "
        "RETURN n.domain AS domain, n.example_url AS example_url ORDER BY n.hits DESC",
        (MIN_HITS,),
    )
    registered: dict[str, list[str]] = {}
    for r in [r for r in rows if r["domain"] not in known][:limit]:
        domain = r["domain"]
        home = f"https://{domain}/"
        page = http.get(home, PROBE_INTERVAL, {})  # None: robots.txt disallows or cooling down
        start: list[str] = []
        if (
            page is not None
            and page.status_code == 200
            and "html" in page.headers.get("content-type", "")
        ):
            start = sections(str(page.url), page.text)
        title = (
            re.search(r"<title[^>]*>(.*?)</title>", page.text, re.DOTALL | re.IGNORECASE)
            if page
            else None
        )
        store.register_source(
            db,
            domain=domain,
            name=title.group(1).strip() if title else domain,
            homepage=home,
            feeds=[],
            via="portal-links",
            rejected=not start,
            type="parliament" if PARLIAMENT.search(domain) else "gov",
            crawl={"start_urls": start, "allow": [SECTIONS.pattern], "max_depth": 2}
            if start
            else None,
        )
        if start:
            registered[domain] = start
    return registered
