"""Nightly stage 10: dated snapshot of the graph to GCS (Parquet) and the daily diff.

The graph keeps every version of every row, so a snapshot is the rows valid at that moment, and
anyone can rebuild what a page showed on a past date. The diff (what appeared, closed or merged
since the previous run) feeds Today and the email digest.
"""

import io
import json
from datetime import datetime, timedelta
from typing import Any, Protocol

import pyarrow as pa
import pyarrow.parquet as pq

from pipeline.ctx import Ctx
from weft_core import graph

TABLES = [
    "reports",
    "events",
    "claims",
    "claim_groups",
    "conflicts",
    "figures",
    "short_versions",
    "anomalies",
]


class Sink(Protocol):
    def write(self, path: str, data: bytes) -> None: ...


class GcsSink:
    def __init__(self, bucket: str) -> None:
        from google.cloud import storage  # type: ignore[attr-defined]

        self._b = storage.Client().bucket(bucket)

    def write(self, path: str, data: bytes) -> None:
        self._b.blob(path).upload_from_string(data)


def _parquet(rows: list[dict[str, Any]]) -> bytes:
    buf = io.BytesIO()
    pq.write_table(pa.Table.from_pylist(rows), buf)
    return buf.getvalue()


def export(ctx: Ctx, sink: Sink, tables: list[str] = TABLES) -> int:
    day = ctx.now[:10]
    n = 0
    for t in tables:
        rows = ctx.db.execute(*_valid_at(t, ctx.now))
        if rows:
            sink.write(f"{day}/{t}.parquet", _parquet(rows))
            n += len(rows)
    return n


def _valid_at(table: str, at: str) -> tuple[str, tuple[Any, ...]]:
    clause, args = graph.asof(at)
    return f"SELECT * FROM {table} WHERE {clause}", args


def diff(ctx: Ctx, since: str) -> dict[str, list[str]]:
    """Ids that appeared or closed between `since` and now."""

    def ids(sql: str, *args: Any) -> list[str]:
        return sorted(r["id"] for r in ctx.db.execute(sql, args))

    def new(table: str) -> list[str]:
        return ids(
            f"SELECT DISTINCT id FROM {table} t WHERE valid_from > ? AND NOT EXISTS "
            f"(SELECT 1 FROM {table} o WHERE o.id=t.id AND o.valid_from <= ?)",
            since,
            since,
        )

    return {
        "new_reports": new("reports"),
        "new_events": new("events"),
        "new_claim_groups": new("claim_groups"),
        "merged_events": ids(
            "SELECT id FROM events e WHERE valid_to > ? AND NOT EXISTS "
            "(SELECT 1 FROM events c WHERE c.id=e.id AND c.valid_to IS NULL)",
            since,
        ),
        "moved_reports": ids(
            "SELECT DISTINCT r.id FROM reports r JOIN reports o ON o.id=r.id AND o.valid_to=r.valid_from "
            "WHERE r.valid_from > ? AND r.event_id IS NOT o.event_id",
            since,
        ),
    }


def run(ctx: Ctx, sink: Sink | None = None) -> int:
    since = (datetime.fromisoformat(ctx.now) - timedelta(days=1)).isoformat()
    d = diff(ctx, since)
    ctx.db.execute(
        "INSERT INTO daily_diffs(day,payload) VALUES(?,?) ON CONFLICT(day) DO UPDATE SET "
        "payload=excluded.payload",
        (ctx.now[:10], json.dumps(d)),
    )
    if sink is not None:
        export(ctx, sink)
    return sum(len(v) for v in d.values())
