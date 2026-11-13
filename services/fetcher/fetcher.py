"""Fetch one article URL, extract text and metadata, store raw + rows, dedupe.

Rule 5: store summaries and links, not full articles. The raw HTML copy goes to the private
raw bucket (30-day lifecycle); the extracted row keeps only a short lede. Paywalled sources
get the lede only and the paywall is never bypassed.
"""

import hashlib
import io
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit

import pdfplumber
import trafilatura

from weft_core import portals, rules
from weft_core.polite import PoliteClient

LEDE_CHARS = 500
MAX_OCR_PAGES = 30  # shortcut: scans longer than this are cut, raise when a portal needs it


def ocr_page(page: Any) -> str:
    """Tesseract on one rendered page. Empty when pytesseract or the binary is not installed,
    which the caller records as an extraction failure."""
    try:
        import pytesseract

        return str(pytesseract.image_to_string(page.to_image(resolution=200).original))
    except (ImportError, OSError):
        return ""


class Store(Protocol):
    def seen(self, canonical_url: str | None, text_hash: str) -> bool:
        """True if the URL (when given; matched against both the fetched and the canonical URL)
        or the text hash is already stored."""
        ...

    def save(
        self, raw_row: dict[str, Any], extracted_row: dict[str, Any], content: bytes, ext: str
    ) -> None:
        """Write the raw copy, set raw_row["raw_gcs_uri"], insert both rows."""


@dataclass
class Result:
    status: str  # stored | duplicate | skipped | blocked | extract_failed
    item_id: str | None = None
    message: dict[str, Any] | None = None  # `items-extracted` payload, set when stored


def normalize_url(url: str) -> str:
    p = urlsplit(url)
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/") or "/", p.query, ""))


def fetch_item(
    msg: dict[str, Any], source: dict[str, Any], http: PoliteClient, store: Store
) -> Result:
    if store.seen(msg["url"], ""):
        return Result("duplicate")  # feeds repeat entries every poll: never re-download them
    resp = http.get(msg["url"], interval(source), {})
    if resp is None:
        if not http.allowed(msg["url"]):
            return Result("blocked")  # robots.txt: permanent, so the caller must not retry
        return Result("skipped")  # cooldown or 429: caller retries later
    return ingest(msg, resp.content, resp.headers.get("content-type", ""), resp.status_code, store)


def interval(source: dict[str, Any]) -> float:
    rl = source["rate_limit"]
    return float(rl["per_seconds"] / rl["requests"])


def _extract(content: bytes, url: str, content_type: str) -> tuple[dict[str, Any], str]:
    """Return (metadata, file extension). PDFs via pdfplumber, everything else via trafilatura."""
    if "pdf" in content_type or url.lower().endswith(".pdf"):
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
            if not text.strip():  # scanned PDF: no text layer, so OCR the page images
                text = "\n".join(ocr_page(page) for page in pdf.pages[:MAX_OCR_PAGES])
        return {"text": text, "title": (pdf.metadata or {}).get("Title")}, "pdf"
    doc = trafilatura.bare_extraction(
        content.decode("utf-8", errors="replace"), url=url, with_metadata=True
    )
    return ((doc if isinstance(doc, dict) else doc.as_dict()) if doc else {}), "html"


def ingest(
    msg: dict[str, Any],
    content: bytes,
    content_type: str,
    status: int,
    store: Store,
    *,
    versioned: bool = False,
) -> Result:
    """Extract and store one document.

    `versioned` is for portals: the same URL changing is a new version, so only the text
    hash dedupes, and the item id includes it.
    """
    now = datetime.now(UTC).isoformat()
    d, ext = _extract(content, msg["url"], content_type)
    text = d.get("text") or ""
    canonical = normalize_url(d.get("url") or msg["url"])
    item_id = hashlib.sha256(canonical.encode()).hexdigest()[:32]
    if not text.strip():
        # keep a record that extraction failed, for the extraction-failures dashboard
        store.save(
            _raw(item_id, msg, canonical, now, status, "", None),
            {"item_id": item_id, "extracted_at": now, "status": "failed", "error": "no text"},
            content,
            ext,
        )
        return Result("extract_failed", item_id)

    text_hash = hashlib.sha256(" ".join(text.split()).encode()).hexdigest()
    if versioned:
        item_id = hashlib.sha256((canonical + text_hash).encode()).hexdigest()[:32]
    if store.seen(None if versioned else canonical, text_hash):
        return Result("duplicate", item_id)

    lede = text[:LEDE_CHARS]
    meta = {k: v for k, v in d.items() if k in _META_KEYS and v}
    store.save(
        _raw(item_id, msg, canonical, now, status, text_hash, None),
        {
            "item_id": item_id,
            "extracted_at": now,
            "title": d.get("title"),
            "summary": lede,
            "language": d.get("language"),
            "metadata": json.dumps(meta, default=str),
            "status": "ok",
        },
        content,
        ext,
    )
    html = content.decode("utf-8", errors="replace") if ext == "html" else ""
    return Result(
        "stored",
        item_id,
        {
            "item_id": item_id,
            "source_id": msg["source_id"],
            "url": msg["url"],
            "title": d.get("title"),
            "summary": lede,
            "published_at": published_at(msg.get("published"), html, now),
            "section": ",".join(d.get("categories") or [])
            if isinstance(d.get("categories"), list)
            else (d.get("categories") or ""),
            "text_hash": text_hash,
            # read once here, so the nightly weights stage needs no raw copy
            "correction_note": bool(rules.CORRECTION.search(text)),
            "gov_domains": sorted(portals.outbound_gov_domains(html, canonical))
            if ext == "html"
            else [],
        },
    )


_PUBLISHED_META = re.compile(
    r"<meta[^>]+(?:property|name|itemprop)=[\"'](?:article:published_time|datePublished|pubdate)"
    r"[\"'][^>]*content=[\"']([^\"']+)",
    re.IGNORECASE,
)


def published_at(feed_time: Any, html: str, now: str) -> str:
    """A full timestamp, never a bare date: the feed entry's time, then the page's
    article:published_time, then the fetch time. Clamped to `now` so a wrong zone can't
    put a report in the future."""
    m = _PUBLISHED_META.search(html)
    for v in (feed_time, m.group(1) if m else None):
        if ts := _timestamp(v):
            return min(ts, datetime.fromisoformat(now)).isoformat()
    return now


def _timestamp(v: Any) -> datetime | None:
    s = str(v or "").strip()
    if len(s) <= 10:  # empty, or a date with no time: midnight would be a guess
        return None
    try:
        ts = datetime.fromisoformat(s)
    except ValueError:
        try:
            ts = parsedate_to_datetime(s)  # RSS pubDate (RFC 822)
        except (TypeError, ValueError):
            return None
    return (ts if ts.tzinfo else ts.replace(tzinfo=UTC)).astimezone(UTC)


_META_KEYS = {"author", "date", "sitename", "categories", "tags", "description", "hostname"}


def _raw(
    item_id: str,
    msg: dict[str, Any],
    canonical: str,
    now: str,
    status: int,
    text_hash: str,
    uri: str | None,
) -> dict[str, Any]:
    return {
        "item_id": item_id,
        "source_id": msg["source_id"],
        "url": msg["url"],
        "canonical_url": canonical,
        "fetched_at": now,
        "http_status": status,
        "text_hash": text_hash or None,
        "raw_gcs_uri": uri,
    }
