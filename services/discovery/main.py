"""Cloud Run job: read the newest GDELT file and register verified feeds for each beat."""

import os

import httpx

from weft_core import discovery, store
from weft_core.polite import PoliteClient


def main() -> int:
    db = store.TursoDb(os.environ["TURSO_URL"], os.environ["TURSO_TOKEN"])
    store.init(db)
    discovery.seed_beats(db) if not store.beats(db) else None
    with httpx.Client(timeout=30, follow_redirects=True) as http:
        found = discovery.discover(db, PoliteClient(http), discovery.latest_gkg(http))
    for domain, feeds in found.items():
        print(f"registered {domain}: {feeds}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
