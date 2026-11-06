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
CREATE TABLE IF NOT EXISTS claims (
  id TEXT NOT NULL, report_id TEXT NOT NULL, event_id TEXT, group_id TEXT, text TEXT NOT NULL,
  lang TEXT, start_char INTEGER NOT NULL, end_char INTEGER NOT NULL, embedding TEXT,
  {V}, PRIMARY KEY (id, valid_from));
CREATE TABLE IF NOT EXISTS claim_groups (
  id TEXT NOT NULL, event_id TEXT NOT NULL, label TEXT NOT NULL, perspectives TEXT NOT NULL,
  n_reports INTEGER NOT NULL, {V}, PRIMARY KEY (id, valid_from));
CREATE TABLE IF NOT EXISTS conflicts (
  group_a TEXT NOT NULL, group_b TEXT NOT NULL, event_id TEXT NOT NULL, nli_score REAL NOT NULL,
  {V}, PRIMARY KEY (group_a, group_b, valid_from));
CREATE TABLE IF NOT EXISTS figures (
  id TEXT NOT NULL, report_id TEXT NOT NULL, event_id TEXT, kind TEXT NOT NULL,
  quantity TEXT, value REAL, unit TEXT, speaker TEXT, text TEXT NOT NULL,
  start_char INTEGER NOT NULL, end_char INTEGER NOT NULL, {V}, PRIMARY KEY (id, valid_from));
CREATE TABLE IF NOT EXISTS short_versions (
  id TEXT NOT NULL, payload TEXT NOT NULL, {V}, PRIMARY KEY (id, valid_from));
CREATE TABLE IF NOT EXISTS anomalies (
  id TEXT NOT NULL, rule TEXT NOT NULL, rule_version INTEGER NOT NULL, status TEXT NOT NULL,
  subject_kind TEXT NOT NULL, subject_id TEXT NOT NULL, story_id TEXT, event_id TEXT,
  summary TEXT NOT NULL, inputs TEXT NOT NULL, evidence_ids TEXT NOT NULL, detail TEXT NOT NULL,
  {V}, PRIMARY KEY (id, valid_from));
CREATE TABLE IF NOT EXISTS anomalies_log (
  at TEXT NOT NULL, anomaly_id TEXT NOT NULL, change TEXT NOT NULL, rule TEXT NOT NULL,
  rule_version INTEGER NOT NULL, status TEXT);
CREATE TABLE IF NOT EXISTS source_weights (
  source_id TEXT NOT NULL, day TEXT NOT NULL, weight REAL NOT NULL, factors TEXT NOT NULL,
  n_reports INTEGER NOT NULL, insufficient INTEGER NOT NULL, PRIMARY KEY (source_id, day));
CREATE TABLE IF NOT EXISTS report_versions (
  report_id TEXT NOT NULL, n INTEGER NOT NULL, fetched_at TEXT NOT NULL, text_hash TEXT NOT NULL,
  PRIMARY KEY (report_id, n));
CREATE TABLE IF NOT EXISTS documents (
  id TEXT NOT NULL, url TEXT NOT NULL, issuer_id TEXT NOT NULL, kind TEXT NOT NULL,
  story_id TEXT, event_id TEXT, published_at TEXT, lang TEXT, title TEXT, summary TEXT,
  text_hash TEXT, {V}, PRIMARY KEY (id, valid_from));
CREATE TABLE IF NOT EXISTS actors (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, wikidata_id TEXT, role TEXT);
CREATE TABLE IF NOT EXISTS statements (
  id TEXT PRIMARY KEY, actor_id TEXT NOT NULL, document_id TEXT NOT NULL, text TEXT NOT NULL,
  start_char INTEGER NOT NULL, end_char INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS reader_reports (
  kind TEXT NOT NULL, ref_id TEXT, message TEXT NOT NULL, email TEXT, created_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open', resolution TEXT);
CREATE TABLE IF NOT EXISTS corrections (day TEXT NOT NULL, kind TEXT NOT NULL, what TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS translations (
  key TEXT PRIMARY KEY, lang TEXT NOT NULL, text TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS review_items (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, ref_id TEXT NOT NULL, payload TEXT NOT NULL,
  sampled_at TEXT NOT NULL, rating TEXT, reviewer TEXT, rated_at TEXT);
CREATE TABLE IF NOT EXISTS subscriptions (
  email TEXT PRIMARY KEY, frequency TEXT NOT NULL, follows TEXT NOT NULL, token TEXT NOT NULL,
  created_at TEXT NOT NULL, last_sent TEXT);
CREATE TABLE IF NOT EXISTS daily_diffs (day TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS batch_runs (
  run_id TEXT NOT NULL, stage TEXT NOT NULL, started_at TEXT NOT NULL, ended_at TEXT,
  rows_out INTEGER, status TEXT NOT NULL, error TEXT, PRIMARY KEY (run_id, stage));
"""


def init(db: Db) -> None:
    from weft_core import store

    store.init(db)
    for stmt in GRAPH_SCHEMA.split(";"):
        if stmt.strip():
            db.execute(stmt)


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
