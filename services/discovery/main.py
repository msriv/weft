"""Cloud Run job: read recent GDELT files and register verified feeds for each beat.

GKG_FILES (default 4 = the last hour, matching the hourly schedule) sets how far back to read;
the first local run (seed) reads a day so the system starts with more than a handful of sources.
"""

import os

import httpx

from weft_core import discovery, portals, store
from weft_core.polite import PoliteClient


def main() -> int:
    db = store.from_env()
    discovery.seed_beats(db) if not store.beats(db) else None
    with httpx.Client(timeout=30, follow_redirects=True) as http:
        gkg = discovery.latest_gkg(http, int(os.environ.get("GKG_FILES", "4")))
        found = discovery.discover(db, PoliteClient(http), gkg)
        for domain, feeds in found.items():
            print(f"registered {domain}: {feeds}")
        for domain, start in portals.discover_portals(db, PoliteClient(http)).items():
            print(f"registered portal {domain}: {start}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
