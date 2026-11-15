"""Which registered source does a URL belong to? (#169)

A feed lists links to other sites: wire copy hosted by the agency, partner content, redirect
services. A report belongs to the source whose site it is on, not to the feed that listed it.
"""

from typing import Any
from urllib.parse import urlsplit

_SLD = {"co", "com", "org", "net", "gov", "ac", "edu", "gen", "nic"}


def host_of(url: str) -> str:
    h = urlsplit(url if "//" in url else f"//{url}").netloc.lower().split(":")[0]
    return h.removeprefix("www.")


def registrable(host: str) -> str:
    parts = host.split(".")
    if len(parts) < 2:
        return host
    n = 3 if len(parts) >= 3 and parts[-2] in _SLD and len(parts[-1]) == 2 else 2
    return ".".join(parts[-n:])


def _own(source: dict[str, Any]) -> list[str]:
    return [host_of(d) for d in [source.get("domain") or source.get("homepage") or ""] if d] + [
        host_of(d) for d in source.get("link_domains") or []
    ]


def owner_of(url: str, sources: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The source whose domain (or listed `link_domains`) holds `url`; a subdomain matches its
    parent. When several match, the most specific domain wins."""
    host = host_of(url)
    best: tuple[int, dict[str, Any]] | None = None
    for s in sources:
        for d in _own(s):
            if (host == d or host.endswith("." + d)) and (best is None or len(d) > best[0]):
                best = (len(d), s)
    if best:
        return best[1]
    # same registered site, different subdomain of a source that is itself a subdomain
    reg = registrable(host)
    same = [s for s in sources if any(registrable(d) == reg for d in _own(s))]
    return same[0] if len(same) == 1 else None


def attribute(url: str, feed_source: dict[str, Any], sources: list[dict[str, Any]]) -> str | None:
    """Source id the URL belongs to: the feed's own, another registered one, or None (unknown)."""
    if not _own(feed_source):
        return str(feed_source["id"])  # nothing to compare with: trust the feed
    own = owner_of(url, [feed_source])
    if own is not None:
        return str(own["id"])
    other = owner_of(url, sources)
    return str(other["id"]) if other is not None else None
