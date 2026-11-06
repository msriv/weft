"""The story graph (D17): relational tables that mirror the spec's nodes and relationships.

Every row has `valid_from` / `valid_to`. Nothing is deleted: a correction closes the current
version (sets `valid_to`) and opens a new one, which is what makes Replay and the corrections log
possible. Primary key is (id, valid_from); the current version has `valid_to IS NULL`.
Vectors are JSON arrays; callers search them in Python (see D17).
"""

import json
from datetime import UTC, datetime
from typing import Any

from weft_core.store import Db

V = "valid_from TEXT NOT NULL, valid_to TEXT"

GRAPH_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS reports (
  id TEXT NOT NULL, url TEXT NOT NULL, source_id TEXT NOT NULL, perspective TEXT NOT NULL,
  story_id TEXT, event_id TEXT, published_at TEXT, fetched_at TEXT, type TEXT NOT NULL,
  lang TEXT, title TEXT, summary TEXT, text_hash TEXT, minhash TEXT, embedding TEXT,
  grouping_confidence REAL, {V}, PRIMARY KEY (id, valid_from));
CREATE INDEX IF NOT EXISTS reports_event ON reports(event_id, valid_to);
CREATE TABLE IF NOT EXISTS events (
  id TEXT NOT NULL, story_id TEXT NOT NULL, first_seen TEXT NOT NULL, centroid TEXT NOT NULL,
  entities TEXT NOT NULL DEFAULT '[]', n_reports INTEGER NOT NULL DEFAULT 1,
  grouping_confidence REAL, {V}, PRIMARY KEY (id, valid_from));
CREATE TABLE IF NOT EXISTS report_entities (
  report_id TEXT NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL, wikidata_id TEXT,
  PRIMARY KEY (report_id, name));
CREATE TABLE IF NOT EXISTS entity_links (name TEXT PRIMARY KEY, wikidata_id TEXT);
CREATE TABLE IF NOT EXISTS copies (
  report_id TEXT NOT NULL, copy_of TEXT NOT NULL, jaccard REAL NOT NULL,
  PRIMARY KEY (report_id, copy_of));
"""


def init(db: Db) -> None:
    from weft_core import store

    store.init(db)
    for stmt in GRAPH_SCHEMA.split(";"):
        if stmt.strip():
            db.execute(stmt)


def now() -> str:
    return datetime.now(UTC).isoformat()


JSON_COLS = {"embedding", "centroid", "minhash", "entities", "perspectives", "evidence_ids"}


def _dec(row: dict[str, Any]) -> dict[str, Any]:
    return {
        k: json.loads(v) if k in JSON_COLS and isinstance(v, str) else v for k, v in row.items()
    }


def put(db: Db, table: str, row: dict[str, Any], at: str | None = None) -> None:
    """Close the current version of row['id'] and open a new one."""
    at = at or now()
    db.execute(f"UPDATE {table} SET valid_to=? WHERE id=? AND valid_to IS NULL", (at, row["id"]))
    vals = {
        k: json.dumps(v) if isinstance(v, list | dict) else v
        for k, v in {**row, "valid_from": at, "valid_to": None}.items()
    }
    cols = ",".join(vals)
    db.execute(
        f"INSERT INTO {table}({cols}) VALUES({','.join('?' * len(vals))})", tuple(vals.values())
    )


def asof(at: str | None) -> tuple[str, tuple[Any, ...]]:
    """SQL clause for rows valid at `at` (ISO string); None means current."""
    if at is None:
        return "valid_to IS NULL", ()
    return "valid_from <= ? AND (valid_to IS NULL OR valid_to > ?)", (at, at)


def select(
    db: Db,
    table: str,
    where: str = "1=1",
    args: tuple[Any, ...] = (),
    at: str | None = None,
    tail: str = "",
) -> list[dict[str, Any]]:
    clause, cargs = asof(at)
    rows = db.execute(f"SELECT * FROM {table} WHERE {clause} AND ({where}) {tail}", cargs + args)
    return [_dec(r) for r in rows]


def get(db: Db, table: str, id: str, at: str | None = None) -> dict[str, Any] | None:
    rows = select(db, table, "id=?", (id,), at)
    return rows[0] if rows else None


def reports_of_event(db: Db, event_id: str, at: str | None = None) -> list[dict[str, Any]]:
    return select(db, "reports", "event_id=?", (event_id,), at, "ORDER BY published_at")


def open_events(db: Db, story_id: str, since: str) -> list[dict[str, Any]]:
    """Current events of a story that saw a report after `since` (the stream-path candidate set)."""
    return select(
        db,
        "events",
        "story_id=? AND id IN (SELECT event_id FROM reports WHERE valid_to IS NULL AND "
        "COALESCE(published_at, fetched_at) >= ?)",
        (story_id, since),
    )
