"""One-off: copy the URLs and text hashes already in BigQuery `raw_items` into `Seen` nodes, so
the fetcher does not download old articles again after the move off BigQuery (#161).

    python -m services.fetcher.backfill_seen
"""

import os

from services.fetcher.fetcher import seen_keys
from weft_core import graph, store
from weft_core.gcp import bigquery_client


def main() -> int:
    project = os.environ["PROJECT_ID"]
    db = store.from_env()
    graph.init(db)
    rows = bigquery_client(project).query(
        f"SELECT url, canonical_url, text_hash, fetched_at FROM `{project}.weft.raw_items`"
    )
    batch: list[tuple[str, str, bool]] = []
    total = 0
    for r in rows.result():
        at = r.fetched_at.isoformat()
        for k in {*seen_keys(r.url, r.text_hash or ""), *seen_keys(r.canonical_url, "")}:
            batch.append((k, at, bool(r.text_hash)))  # no text hash: a failed extraction
        if len(batch) >= 1000:
            _flush(db, batch)
            total += len(batch)
            batch = []
    _flush(db, batch)
    print(f"seen keys written: {total + len(batch)}")
    return 0


def _flush(db: store.Db, batch: list[tuple[str, str, bool]]) -> None:
    if batch:
        db.execute(
            "UNWIND ? AS r MERGE (n:Seen {key: r[0]}) ON CREATE SET n.at = r[1], n.fails = 0 "
            "SET n.stored = coalesce(n.stored, false) OR r[2], "
            "n.fails = n.fails + CASE WHEN r[2] THEN 0 ELSE 1 END, n.last = r[1]",
            (batch,),
        )


if __name__ == "__main__":
    raise SystemExit(main())
