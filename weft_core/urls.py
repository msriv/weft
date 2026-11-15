"""URL normalisation shared by the poller and the fetcher: one key per article (#161)."""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Tracking parameters never change the page. Everything else is kept (sorted), since some
# sites really do select the article by query string.
TRACKING = {"fbclid", "gclid", "dclid", "msclkid", "igshid", "mc_cid", "mc_eid", "_ga", "ref_src"}


def normalize_url(url: str) -> str:
    p = urlsplit(url)
    query = sorted(
        (k, v)
        for k, v in parse_qsl(p.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in TRACKING
    )
    return urlunsplit(
        (p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/") or "/", urlencode(query), "")
    )
