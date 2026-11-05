"""Fetch one article URL, extract text and metadata, store raw + rows, dedupe.

Rule 5: store summaries and links, not full articles. The raw HTML copy goes to the private
raw bucket (30-day lifecycle); the extracted row keeps only a short lede. Paywalled sources
get the lede only and the paywall is never bypassed.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit

import trafilatura

from weft_core.polite import PoliteClient

LEDE_CHARS = 500


class Store(Protocol):
    def seen(self, canonical_url: str, text_hash: str) -> bool: ...
    def save(self, raw_row: dict[str, Any], extracted_row: dict[str, Any], html: bytes) -> None:
        """Write the raw HTML, set raw_row["raw_gcs_uri"], insert both rows."""


@dataclass
class Result:
    status: str  # stored | duplicate | skipped | extract_failed
    item_id: str | None = None


def normalize_url(url: str) -> str:
    p = urlsplit(url)
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/") or "/", p.query, ""))


def fetch_item(
    msg: dict[str, Any], source: dict[str, Any], http: PoliteClient, store: Store
) -> Result:
    rl = source["rate_limit"]
    resp = http.get(msg["url"], float(rl["per_seconds"] / rl["requests"]), {})
    if resp is None:
        return Result("skipped")  # robots, cooldown or 429: caller retries later

    now = datetime.now(UTC).isoformat()
    doc = trafilatura.bare_extraction(resp.text, url=msg["url"], with_metadata=True)
    d: dict[str, Any] = (doc if isinstance(doc, dict) else doc.as_dict()) if doc else {}
    text = d.get("text") or ""
    canonical = normalize_url(d.get("url") or msg["url"])
    item_id = hashlib.sha256(canonical.encode()).hexdigest()[:32]
    if not text.strip():
        # keep a record that extraction failed, for the extraction-failures dashboard
        store.save(
            _raw(item_id, msg, canonical, now, resp.status_code, "", None),
            {"item_id": item_id, "extracted_at": now, "status": "failed", "error": "no text"},
            resp.content,
        )
        return Result("extract_failed", item_id)

    text_hash = hashlib.sha256(" ".join(text.split()).encode()).hexdigest()
    if store.seen(canonical, text_hash):
        return Result("duplicate", item_id)

    lede = text[:LEDE_CHARS]
    meta = {k: v for k, v in d.items() if k in _META_KEYS and v}
    store.save(
        _raw(item_id, msg, canonical, now, resp.status_code, text_hash, None),
        {
            "item_id": item_id,
            "extracted_at": now,
            "title": d.get("title"),
            "summary": lede,
            "language": d.get("language"),
            "metadata": json.dumps(meta, default=str),
            "status": "ok",
        },
        resp.content,
    )
    return Result("stored", item_id)


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
