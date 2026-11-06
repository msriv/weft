"""Operational store (D15/D16): beats, sources, stories. SQLite SQL, so the same statements run
on Turso (libSQL) in production and on a local SQLite file in tests and dev.

Product rules baked into the schema: `state_run` and `owner_id` are NULL (shown as "unverified")
unless a citation URL is stored with them; `stories.public` defaults to 0 and only the admin
toggle sets it; party status is per story (`story_parties`).
"""

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx

SCHEMA = """
CREATE TABLE IF NOT EXISTS beats (
  id TEXT PRIMARY KEY, name TEXT NOT NULL,
  patterns TEXT NOT NULL,            -- JSON list of case-insensitive regexes over GDELT fields
  languages TEXT NOT NULL DEFAULT '["en"]');
CREATE TABLE IF NOT EXISTS sources (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, homepage TEXT NOT NULL, domain TEXT NOT NULL UNIQUE,
  country TEXT, languages TEXT NOT NULL DEFAULT '["en"]', type TEXT NOT NULL DEFAULT 'news',
  state_run INTEGER, state_run_source TEXT,   -- NULL = unverified
  owner_id TEXT, ownership_source TEXT,
  feeds TEXT NOT NULL DEFAULT '[]', sitemaps TEXT NOT NULL DEFAULT '[]',
  paywalled INTEGER NOT NULL DEFAULT 0, min_interval REAL NOT NULL DEFAULT 10,
  status TEXT NOT NULL DEFAULT 'active',      -- active | rejected (no live feed found)
  discovered_via TEXT NOT NULL, discovered_at TEXT NOT NULL, verified_at TEXT);
CREATE TABLE IF NOT EXISTS stories (
  id TEXT PRIMARY KEY, beat_id TEXT NOT NULL REFERENCES beats(id), title TEXT NOT NULL,
  public INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS story_parties (
  story_id TEXT NOT NULL REFERENCES stories(id), party TEXT NOT NULL, citation TEXT,
  PRIMARY KEY (story_id, party));
"""


class Db(Protocol):
    def execute(self, sql: str, args: tuple[Any, ...] = ()) -> list[dict[str, Any]]: ...


class SqliteDb:
    def __init__(self, path: str = ":memory:") -> None:
        self._c = sqlite3.connect(path, check_same_thread=False)
        self._c.row_factory = sqlite3.Row

    def execute(self, sql: str, args: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        cur = self._c.execute(sql, args)
        self._c.commit()
        return [dict(r) for r in cur.fetchall()]


class TursoDb:
    """Turso over its HTTP pipeline API (no extra dependency). One request per statement."""

    def __init__(self, url: str, token: str, http: httpx.Client | None = None) -> None:
        self._url = url.replace("libsql://", "https://", 1).rstrip("/") + "/v2/pipeline"
        self._http = http or httpx.Client(timeout=30)
        self._auth = {"Authorization": f"Bearer {token}"}

    @staticmethod
    def _arg(v: Any) -> dict[str, str]:
        if v is None:
            return {"type": "null"}
        if isinstance(v, bool | int):
            return {"type": "integer", "value": str(int(v))}
        if isinstance(v, float):
            return {"type": "float", "value": repr(v)}
        return {"type": "text", "value": str(v)}

    def execute(self, sql: str, args: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        stmt = {"sql": sql, "args": [self._arg(a) for a in args]}
        body = {"requests": [{"type": "execute", "stmt": stmt}, {"type": "close"}]}
        r = self._http.post(self._url, json=body, headers=self._auth)
        r.raise_for_status()
        first = r.json()["results"][0]
        if first["type"] == "error":
            raise RuntimeError(f"turso: {first['error']['message']}")
        res = first["response"]["result"]
        cols = [c["name"] for c in res["cols"]]
        return [{c: _cell(v) for c, v in zip(cols, row, strict=True)} for row in res["rows"]]


def _cell(v: dict[str, Any]) -> Any:
    t = v["type"]
    return (
        None
        if t == "null"
        else int(v["value"])
        if t == "integer"
        else (float(v["value"]) if t == "float" else v["value"])
    )


def init(db: Db) -> None:
    for stmt in SCHEMA.split(";"):
        if stmt.strip():
            db.execute(stmt)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def add_beat(
    db: Db, id: str, name: str, patterns: list[str], languages: list[str] | None = None
) -> None:
    db.execute(
        "INSERT INTO beats(id,name,patterns,languages) VALUES(?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET name=excluded.name, patterns=excluded.patterns, "
        "languages=excluded.languages",
        (id, name, json.dumps(patterns), json.dumps(languages or ["en"])),
    )


def beats(db: Db) -> list[dict[str, Any]]:
    return [{**r, "patterns": json.loads(r["patterns"])} for r in db.execute("SELECT * FROM beats")]


def known_domains(db: Db) -> set[str]:
    """Domains already decided on, including rejected ones, so they are not re-probed forever."""
    return {r["domain"] for r in db.execute("SELECT domain FROM sources")}


def register_source(
    db: Db,
    *,
    domain: str,
    name: str,
    homepage: str,
    feeds: list[str],
    via: str,
    rejected: bool = False,
) -> None:
    """Insert a discovered source. Ownership and state_run stay NULL: nothing here cites them."""
    db.execute(
        "INSERT OR IGNORE INTO sources(id,name,homepage,domain,feeds,status,discovered_via,"
        "discovered_at,verified_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (
            domain.replace(".", "-"),
            name,
            homepage,
            domain,
            json.dumps(feeds),
            "rejected" if rejected else "active",
            via,
            _now(),
            None if rejected else _now(),
        ),
    )


def active_sources(db: Db) -> list[dict[str, Any]]:
    """Active sources in the shape of config/sources/schema.json, for the poller."""
    out = []
    for r in db.execute("SELECT * FROM sources WHERE status='active'"):
        e: dict[str, Any] = {
            "id": r["id"],
            "name": r["name"],
            "homepage": r["homepage"],
            "languages": json.loads(r["languages"]),
            "type": r["type"],
            "feeds": json.loads(r["feeds"]),
            "sitemaps": json.loads(r["sitemaps"]),
            "paywalled": bool(r["paywalled"]),
            "rate_limit": {"requests": 1, "per_seconds": r["min_interval"]},
        }
        for k in ("country", "state_run", "state_run_source", "owner_id", "ownership_source"):
            if r[k] is not None:
                e[k] = bool(r[k]) if k == "state_run" else r[k]
        out.append(e)
    return out


def create_story(db: Db, id: str, beat_id: str, title: str) -> None:
    db.execute(
        "INSERT INTO stories(id,beat_id,title,created_at) VALUES(?,?,?,?)",
        (id, beat_id, title, _now()),
    )


def set_public(db: Db, story_id: str, public: bool) -> bool:
    """Admin toggle. False if the story does not exist."""
    if not db.execute("SELECT 1 FROM stories WHERE id=?", (story_id,)):
        return False
    db.execute("UPDATE stories SET public=? WHERE id=?", (int(public), story_id))
    return True


def stories(db: Db, *, public_only: bool) -> list[dict[str, Any]]:
    where = " WHERE public=1" if public_only else ""
    return [
        {**r, "public": bool(r["public"])}
        for r in db.execute(f"SELECT id,beat_id,title,public,created_at FROM stories{where}")
    ]
