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
from weft_core import graph, store

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
        rows = _valid_at(ctx, t, ctx.now)
        if rows:
            sink.write(f"{day}/{t}.parquet", _parquet(rows))
            n += len(rows)
    return n


def _valid_at(ctx: Ctx, table: str, at: str) -> list[dict[str, Any]]:
    clause, args = graph.asof(at)
    label = graph.LABELS[table]
    return store.nodes(ctx.db, label, f"MATCH (n:{label}) WHERE {clause} RETURN n", args)


def diff(ctx: Ctx, since: str) -> dict[str, list[str]]:
    """Ids that appeared or closed between `since` and now."""

    def ids(query: str, *args: Any) -> list[str]:
        return sorted(r["id"] for r in ctx.db.execute(query, args))

    def new(table: str) -> list[str]:
        label = graph.LABELS[table]
        return ids(
            f"MATCH (n:{label}) WHERE n.valid_from > ? AND NOT EXISTS "
            f"{{ MATCH (o:{label} {{id: n.id}}) WHERE o.valid_from <= ? }} RETURN DISTINCT n.id AS id",
            since,
            since,
        )

    return {
        "new_reports": new("reports"),
        "new_events": new("events"),
        "new_claim_groups": new("claim_groups"),
        "merged_events": ids(
            "MATCH (e:Event) WHERE e.valid_to > ? AND NOT EXISTS "
            "{ MATCH (c:Event {id: e.id}) WHERE c.valid_to IS NULL } RETURN e.id AS id",
            since,
        ),
        "moved_reports": ids(
            "MATCH (r:Report) WHERE r.valid_from > ? MATCH (o:Report {id: r.id}) "
            "WHERE o.valid_to = r.valid_from AND coalesce(r.event_id, '') <> coalesce(o.event_id, '') "
            "RETURN DISTINCT r.id AS id",
            since,
        ),
    }


def run(ctx: Ctx, sink: Sink | None = None) -> int:
    since = (datetime.fromisoformat(ctx.now) - timedelta(days=1)).isoformat()
    d = diff(ctx, since)
    ctx.db.execute("MERGE (n:DailyDiff {day: ?}) SET n.payload=?", (ctx.now[:10], json.dumps(d)))
    if sink is not None:
        export(ctx, sink)
    return sum(len(v) for v in d.values())
