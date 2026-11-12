"""The story graph in Neo4j (spec, D19). Graph-level names (`reports`, `events`, ...) map to
node labels in `LABELS`; their properties are declared in `store.NODES`.

Every versioned node has `valid_from` / `valid_to`. Nothing is deleted: a correction closes the
current version (sets `valid_to`) and opens a new node for the new one, which is what makes Replay
and the corrections log possible. The current version has `valid_to IS NULL`.
Vectors are JSON arrays searched in Python over the open events of the last 72 hours.
shortcut: no relationships or Neo4j vector index yet, nodes join on id properties; add them when
graph size makes property joins or brute-force cosine slow.
"""

import json
from datetime import UTC, datetime
from typing import Any

from weft_core import store
from weft_core.store import Db

LABELS = {
    "reports": "Report",
    "events": "Event",
    "claims": "Claim",
    "claim_groups": "ClaimGroup",
    "conflicts": "Conflict",
    "figures": "Figure",
    "short_versions": "ShortVersion",
    "anomalies": "Anomaly",
    "documents": "Document",
}


def init(db: Db) -> None:
    store.init(db)


def now() -> str:
    return datetime.now(UTC).isoformat()


JSON_COLS = {
    "embedding",
    "centroid",
    "minhash",
    "entities",
    "perspectives",
    "evidence_ids",
    "payload",
    "inputs",
    "detail",
    "factors",
}


def _dec(row: dict[str, Any]) -> dict[str, Any]:
    return {
        k: json.loads(v) if k in JSON_COLS and isinstance(v, str) else v for k, v in row.items()
    }


def put(db: Db, table: str, row: dict[str, Any], at: str | None = None) -> None:
    """Close the current version of row['id'] and open a new one."""
    at = at or now()
    label = LABELS[table]
    db.execute(
        f"MATCH (n:{label} {{id: ?}}) WHERE n.valid_to IS NULL SET n.valid_to=?", (row["id"], at)
    )
    store.create(db, label, {**row, "valid_from": at, "valid_to": None})


def asof(at: str | None) -> tuple[str, tuple[Any, ...]]:
    """Cypher condition on `n` for nodes valid at `at` (ISO string); None means current."""
    if at is None:
        return "n.valid_to IS NULL", ()
    return "n.valid_from <= ? AND (n.valid_to IS NULL OR n.valid_to > ?)", (at, at)


def select(
    db: Db,
    table: str,
    where: str = "true",
    args: tuple[Any, ...] = (),
    at: str | None = None,
    tail: str = "",
) -> list[dict[str, Any]]:
    """Versioned nodes valid at `at`. `where` and `tail` are Cypher over `n`."""
    clause, cargs = asof(at)
    label = LABELS[table]
    q = f"MATCH (n:{label}) WHERE {clause} AND ({where}) RETURN n {tail}"
    return [_dec(r) for r in store.nodes(db, label, q, cargs + args)]


def get(db: Db, table: str, id: str, at: str | None = None) -> dict[str, Any] | None:
    rows = select(db, table, "n.id=?", (id,), at)
    return rows[0] if rows else None


def reports_of_event(db: Db, event_id: str, at: str | None = None) -> list[dict[str, Any]]:
    return select(db, "reports", "n.event_id=?", (event_id,), at, "ORDER BY n.published_at")


def open_events(db: Db, story_id: str, since: str) -> list[dict[str, Any]]:
    """Current events of a story that saw a report after `since` (the stream-path candidate set)."""
    return select(
        db,
        "events",
        "n.story_id=? AND EXISTS { MATCH (r:Report) WHERE r.event_id = n.id AND "
        "r.valid_to IS NULL AND coalesce(r.published_at, r.fetched_at) >= ? }",
        (story_id, since),
    )
