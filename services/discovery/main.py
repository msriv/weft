"""Cloud Run job: read the newest GDELT file and register verified feeds for each beat."""

import httpx

from weft_core import discovery, portals, store
from weft_core.polite import PoliteClient


def main() -> int:
    db = store.from_env()
    discovery.seed_beats(db) if not store.beats(db) else None
    with httpx.Client(timeout=30, follow_redirects=True) as http:
        found = discovery.discover(db, PoliteClient(http), discovery.latest_gkg(http))
        for domain, feeds in found.items():
            print(f"registered {domain}: {feeds}")
        for domain, start in portals.discover_portals(db, PoliteClient(http)).items():
            print(f"registered portal {domain}: {start}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
