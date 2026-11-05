"""Cloud Run job entrypoint: crawl every portal source once, daily."""

import hashlib
import os
import sys

import httpx
from google.cloud import storage  # type: ignore[attr-defined]

from services.crawler.crawler import crawl_source
from services.fetcher.app import GcpStore
from weft_core.polite import PoliteClient
from weft_core.sources import load_sources


class GcsHashes:
    def __init__(self, bucket: str, prefix: str = "crawler-state/") -> None:
        self._bucket = storage.Client().bucket(bucket)
        self._prefix = prefix

    def _blob(self, url: str):  # type: ignore[no-untyped-def]
        return self._bucket.blob(self._prefix + hashlib.sha256(url.encode()).hexdigest())

    def get(self, url: str) -> str | None:
        blob = self._blob(url)
        return str(blob.download_as_text()) if blob.exists() else None

    def put(self, url: str, content_hash: str) -> None:
        self._blob(url).upload_from_string(content_hash)


def main() -> int:
    project = os.environ["PROJECT_ID"]
    store = GcpStore(project, os.environ["RAW_BUCKET"])
    state = GcsHashes(os.environ["STATE_BUCKET"])
    failed = 0
    with httpx.Client(timeout=60, follow_redirects=True) as http:
        polite = PoliteClient(http)
        for s in (s for s in load_sources() if "crawl" in s):
            try:
                print(s["id"], crawl_source(s, polite, store, state))
            except httpx.HTTPError as exc:
                failed += 1
                print(f"crawl failed: {s['id']}: {exc}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
