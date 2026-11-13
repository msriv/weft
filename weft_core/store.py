"""Neo4j access (spec: Neo4j holds the story graph; D19). Every node type the code stores is
listed in `NODES` with its properties and defaults, so reads always return every property even
though Neo4j does not store nulls.

Product rules baked in: `state_run` and `owner_id` are null (shown as "unverified") unless a
citation URL is stored with them; `Story.public` defaults to 0 and only the admin toggle sets it;
party status is per story (`StoryParty`).

Queries are Cypher with `?` placeholders, numbered in order (`?` becomes `$p0`, `$p1`, ...), so
call sites pass a plain tuple of arguments.
"""

import json
import os
import re
import time
from datetime import UTC, datetime
from typing import Any, Protocol

# label -> property -> default. `V` marks versioned nodes (valid_from / valid_to, see graph.py).
V = {"valid_from": None, "valid_to": None}
NODES: dict[str, dict[str, Any]] = {
    "Beat": {
        "id": None,
        "name": None,
        "patterns": "[]",
        "exclude": "[]",
        "languages": '["en"]',
        "parties": "[]",
        "places": "[]",
        "groups": "{}",
        "edited": None,
    },
    "Source": {
        "id": None,
        "name": None,
        "homepage": None,
        "domain": None,
        "country": None,
        "country_source": None,
        "rejected_reason": None,
        "languages": '["en"]',
        "type": "news",
        "state_run": None,
        "state_run_source": None,
        "owner_id": None,
        "ownership_source": None,
        "crawl": None,
        "feeds": "[]",
        "sitemaps": "[]",
        "healthy": 1,
        "paywalled": 0,
        "min_interval": 10.0,
        "status": "active",
        "discovered_via": None,
        "discovered_at": None,
        "verified_at": None,
    },
    "PortalCandidate": {"domain": None, "hits": 0, "example_url": None, "last_seen": None},
    "Story": {"id": None, "beat_id": None, "title": None, "public": 0, "created_at": None},
    "StoryParty": {"story_id": None, "party": None, "citation": None},
    "Report": {
        "id": None,
        "url": None,
        "source_id": None,
        "perspective": None,
        "story_id": None,
        "event_id": None,
        "published_at": None,
        "fetched_at": None,
        "type": None,
        "lang": None,
        "title": None,
        "summary": None,
        "text_hash": None,
        "minhash": None,
        "embedding": None,
        "grouping_confidence": None,
        "correction_note": None,
        "origin_id": None,  # the earliest report of its independent-text cluster (#98)
        "claims_extracted": None,  # 1 once claim extraction has read it (#106)
        **V,
    },
    "Event": {
        "id": None,
        "story_id": None,
        "first_seen": None,
        "centroid": None,
        "entities": "[]",
        "entity_counts": "{}",
        "last_seen": None,
        "n_reports": 1,
        "grouping_confidence": None,
        "follows": None,
        "thread_id": None,
        "thread_label": None,
        **V,
    },
    "ReportEntity": {"report_id": None, "name": None, "kind": None, "wikidata_id": None},
    "EntityLink": {"name": None, "wikidata_id": None},
    "Copy": {"report_id": None, "copy_of": None, "jaccard": None},
    "Claim": {
        "id": None,
        "report_id": None,
        "event_id": None,
        "group_id": None,
        "text": None,
        "lang": None,
        "start_char": None,
        "end_char": None,
        "embedding": None,
        **V,
    },
    "ClaimGroup": {
        "id": None,
        "event_id": None,
        "label": None,
        "perspectives": "[]",
        "n_reports": 0,
        **V,
    },
    "Conflict": {"group_a": None, "group_b": None, "event_id": None, "nli_score": None, **V},
    "Figure": {
        "id": None,
        "report_id": None,
        "event_id": None,
        "kind": None,
        "quantity": None,
        "value": None,
        "unit": None,
        "speaker": None,
        "text": None,
        "start_char": None,
        "end_char": None,
        **V,
    },
    "ShortVersion": {"id": None, "payload": None, **V},
    "Anomaly": {
        "id": None,
        "rule": None,
        "rule_version": None,
        "status": None,
        "subject_kind": None,
        "subject_id": None,
        "story_id": None,
        "event_id": None,
        "summary": None,
        "inputs": None,
        "evidence_ids": None,
        "detail": None,
        **V,
    },
    "AnomalyFeedback": {
        "anomaly_id": None,
        "rule": None,
        "rule_version": None,
        "inputs": None,
        "label": None,
        "at": None,
    },
    "AnomalyLog": {
        "seq": None,
        "at": None,
        "anomaly_id": None,
        "change": None,
        "rule": None,
        "rule_version": None,
        "status": None,
    },
    "SourceWeight": {
        "source_id": None,
        "day": None,
        "weight": None,
        "factors": None,
        "n_reports": 0,
        "insufficient": 0,
    },
    "ReportVersion": {"report_id": None, "n": None, "fetched_at": None, "text_hash": None},
    "Document": {
        "id": None,
        "url": None,
        "issuer_id": None,
        "kind": None,
        "story_id": None,
        "event_id": None,
        "published_at": None,
        "lang": None,
        "title": None,
        "summary": None,
        "text_hash": None,
        **V,
    },
    "Actor": {"id": None, "name": None, "wikidata_id": None, "role": None},
    "Statement": {
        "id": None,
        "actor_id": None,
        "document_id": None,
        "text": None,
        "start_char": None,
        "end_char": None,
    },
    "ReaderReport": {
        "id": None,
        "kind": None,
        "ref_id": None,
        "message": None,
        "email": None,
        "created_at": None,
        "status": "open",
        "resolution": None,
    },
    "Correction": {"day": None, "kind": None, "what": None, "created_at": None},
    "Translation": {"key": None, "lang": None, "text": None, "created_at": None},
    "ReviewItem": {
        "id": None,
        "kind": None,
        "ref_id": None,
        "payload": None,
        "sampled_at": None,
        "rating": None,
        "reviewer": None,
        "rated_at": None,
    },
    "Subscription": {
        "email": None,
        "frequency": None,
        "follows": "[]",
        "token": None,
        "created_at": None,
        "last_sent": None,
    },
    "DailyDiff": {"day": None, "payload": None},
    "Prediction": {
        "id": None,
        "story_id": None,
        "text": None,
        "expected_by": None,
        "confirm_if": None,
        "refute_if": None,
        "based_on": "[]",
        "made_at": None,
        "status": "open",
        "evidence": "[]",
        "checked_at": None,
    },
    "BatchRun": {
        "run_id": None,
        "stage": None,
        "started_at": None,
        "ended_at": None,
        "rows_out": None,
        "status": None,
        "error": None,
    },
}

UNIQUE = {
    "Beat": "id",
    "Source": "id",
    "PortalCandidate": "domain",
    "Story": "id",
    "Actor": "id",
    "Statement": "id",
    "Translation": "key",
    "ReviewItem": "id",
    "Subscription": "email",
    "DailyDiff": "day",
    "EntityLink": "name",
    "ReaderReport": "id",
    "Prediction": "id",
}
INDEXED = ["id", "event_id", "story_id", "report_id", "source_id", "document_id", "actor_id"]


class Db(Protocol):
    def execute(self, query: str, args: tuple[Any, ...] = ()) -> list[dict[str, Any]]: ...


def _params(query: str, args: tuple[Any, ...]) -> tuple[str, dict[str, Any]]:
    n = iter(range(len(args)))
    return re.sub(r"\?", lambda _: f"$p{next(n)}", query), {f"p{i}": a for i, a in enumerate(args)}


class Neo4jDb:
    def __init__(self, uri: str, user: str, password: str, database: str | None = None) -> None:
        from neo4j import GraphDatabase

        # Notifications off: "property does not exist" warnings on empty labels are just noise.
        self._driver = GraphDatabase.driver(
            uri, auth=(user, password), notifications_min_severity="OFF"
        )
        self._database = database

    def execute(self, query: str, args: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        q, params = _params(query, args)
        records, _, _ = self._driver.execute_query(q, params, database_=self._database)
        return [r.data() for r in records]

    def close(self) -> None:
        self._driver.close()


def fill(label: str, props: dict[str, Any] | None) -> dict[str, Any]:
    """A node's properties with every declared property present (Neo4j drops nulls)."""
    return {**NODES[label], **(props or {})}


def nodes(db: Db, label: str, query: str, args: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    """Run a query that returns `n` (a node of `label`) and get its filled properties."""
    return [fill(label, r["n"]) for r in db.execute(query, args)]


def create(db: Db, label: str, props: dict[str, Any]) -> None:
    db.execute(f"CREATE (n:{label}) SET n = ?", (_clean(props),))


def _clean(props: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for k, v in props.items():
        out[k] = (
            json.dumps(v) if isinstance(v, list | dict) else int(v) if isinstance(v, bool) else v
        )
    return out


def _schema(db: Db, query: str, attempts: int = 5) -> None:
    """Run one IF NOT EXISTS schema statement. Services start together and race on these: losing
    the race (AlreadyExists) is fine, and a deadlock or failed result is retried, since by then
    the other writer has usually finished and IF NOT EXISTS is a no-op."""
    from neo4j.exceptions import ClientError, DriverError, TransientError

    for i in range(attempts):
        try:
            db.execute(query)
            return
        except ClientError as e:
            if "AlreadyExists" in (e.code or ""):
                return
            raise
        except (TransientError, DriverError):
            if i == attempts - 1:
                raise
            time.sleep(0.2 * (i + 1))


def init(db: Db) -> None:
    for label, key in UNIQUE.items():
        _schema(db, f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.{key} IS UNIQUE")
    for label, props in NODES.items():
        for p in INDEXED:
            if p in props and UNIQUE.get(label) != p:
                _schema(db, f"CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{p})")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def add_beat(
    db: Db,
    id: str,
    name: str,
    patterns: list[str],
    languages: list[str] | None = None,
    parties: list[str] | None = None,
    exclude: list[str] | None = None,
) -> None:
    db.execute(
        "MERGE (n:Beat {id: ?}) "
        "SET n.name=?, n.patterns=?, n.exclude=?, n.languages=?, n.parties=?",
        (
            id,
            name,
            json.dumps(patterns),
            json.dumps(exclude or []),
            json.dumps(languages or ["en"]),
            json.dumps(parties or []),
        ),
    )


def beats(db: Db) -> list[dict[str, Any]]:
    return [
        {
            **r,
            "patterns": json.loads(r["patterns"]),
            "exclude": json.loads(r["exclude"] or "[]"),
            "places": json.loads(r["places"] or "[]"),
            "groups": json.loads(r.get("groups") or "{}"),
            "parties": json.loads(r["parties"]),
        }
        for r in nodes(db, "Beat", "MATCH (n:Beat) RETURN n")
    ]


def known_domains(db: Db, retry_before: str | None = None) -> set[str]:
    """Domains already decided on, so they are not re-probed every run. With `retry_before`,
    domains rejected before that time are left out, so discovery tries them again."""
    rows = db.execute(
        "MATCH (n:Source) RETURN n.domain AS domain, n.status AS status, n.discovered_at AS at"
    )
    return {
        r["domain"]
        for r in rows
        if not (retry_before and r["status"] == "rejected" and (r["at"] or "") < retry_before)
    }


def add_candidate_hits(db: Db, domain: str, beat_id: str, n: int, now: str) -> None:
    """Add beat-matching article URLs seen for an unknown domain. Counts add up across runs."""
    db.execute(
        "MERGE (n:DomainCandidate {domain: ?, beat_id: ?}) ON CREATE SET n.hits=0, n.first_seen=? "
        "SET n.hits=n.hits+?, n.last_seen=?",
        (domain, beat_id, now, n, now),
    )


def candidates(db: Db, beat_id: str, min_hits: int, limit: int) -> list[str]:
    return [
        r["domain"]
        for r in db.execute(
            "MATCH (n:DomainCandidate {beat_id: ?}) WHERE n.hits >= ? "
            "RETURN n.domain AS domain ORDER BY n.hits DESC LIMIT ?",
            (beat_id, min_hits, limit),
        )
    ]


def prune_candidates(db: Db, before: str) -> None:
    db.execute(
        "MATCH (n:DomainCandidate) WHERE n.last_seen < ? AND n.requested IS NULL DETACH DELETE n",
        (before,),
    )


def clear_candidate(db: Db, domain: str) -> None:
    db.execute("MATCH (n:DomainCandidate {domain: ?}) DETACH DELETE n", (domain,))


def request_source(db: Db, domain: str, beat_id: str | None) -> None:
    """Admin asks discovery to probe a domain on its next run, whatever its hit count."""
    db.execute(
        "MERGE (n:DomainCandidate {domain: ?, beat_id: ?}) SET n.requested=1, n.hits=0",
        (domain, beat_id or ""),
    )


def requested_sources(db: Db) -> list[dict[str, Any]]:
    return db.execute(
        "MATCH (n:DomainCandidate) WHERE n.requested=1 "
        "RETURN n.domain AS domain, n.beat_id AS beat_id"
    )


def register_source(
    db: Db,
    *,
    domain: str,
    name: str,
    homepage: str,
    feeds: list[str],
    via: str,
    rejected: bool = False,
    rejected_reason: str | None = None,
    type: str = "news",
    crawl: dict[str, Any] | None = None,
    languages: list[str] | None = None,
) -> None:
    """Insert a discovered source, or re-probe result for a rejected one. Ownership and
    state_run stay null: nothing here cites them. An active source is never touched."""
    existing = db.execute(
        "MATCH (n:Source) WHERE n.domain=? OR n.id=? RETURN n.status AS status LIMIT 1",
        (domain, domain.replace(".", "-")),
    )
    if existing and existing[0]["status"] != "rejected":
        return
    props = {
        **{k: v for k, v in NODES["Source"].items() if v is not None},
        "id": domain.replace(".", "-"),
        "name": name,
        "homepage": homepage,
        "domain": domain,
        "feeds": feeds,
        "status": "rejected" if rejected else "active",
        "rejected_reason": rejected_reason if rejected else None,
        "discovered_via": via,
        "discovered_at": _now(),
        "verified_at": None if rejected else _now(),
        "type": type,
        "crawl": crawl or None,
        **({"languages": languages} if languages else {}),
    }
    if existing:  # keeps fields the admin set, such as country
        db.execute("MATCH (n:Source) WHERE n.domain=? SET n += ?", (domain, _clean(props)))
    else:
        create(db, "Source", props)


def set_health(db: Db, unhealthy_ids: list[str]) -> None:
    """Mark feeds unhealthy (no success within the health window) or healthy again."""
    db.execute(
        "MATCH (n:Source) SET n.healthy = CASE WHEN n.id IN ? THEN 0 ELSE 1 END", (unhealthy_ids,)
    )


def set_country(db: Db, source_id: str, country: str | None, citation: str | None) -> None:
    """Set a source's country and re-tag its reports, whose perspective is copied at ingest."""
    db.execute(
        "MATCH (n:Source {id: ?}) SET n.country=?, n.country_source=?",
        (source_id, country.upper() if country else None, citation),
    )
    retag(db, source_id)


def beat_groups(db: Db, story_id: str | None) -> dict[str, str]:
    """The owner-set outlet groups of a story's beat (D21): source id -> group. Empty for beats
    whose perspective is the outlet's country."""
    if not story_id:
        return {}
    rows = db.execute(
        "MATCH (s:Story {id: ?}) MATCH (b:Beat {id: s.beat_id}) RETURN b.groups AS g", (story_id,)
    )
    return json.loads(rows[0]["g"] or "{}") if rows else {}


def report_perspective(db: Db, src: dict[str, Any], story_id: str | None) -> str:
    """A report's perspective: its outlet's group on a grouped beat, else its outlet's country."""
    from weft_core.perspectives import perspective_of

    groups = beat_groups(db, story_id)
    if groups:
        return groups.get(src["id"], "unattributed")
    return perspective_of(src)


def retag(db: Db, source_id: str) -> None:
    """Re-derive the perspective copied onto a source's reports at ingest."""
    for src in all_sources(db, "n.id=?", (source_id,)):
        stories = db.execute(
            "MATCH (r:Report {source_id: ?}) RETURN DISTINCT r.story_id AS s", (source_id,)
        )
        for row in stories:
            db.execute(
                "MATCH (r:Report {source_id: ?}) WHERE r.story_id = ? OR (? IS NULL AND "
                "r.story_id IS NULL) SET r.perspective=?",
                (source_id, row["s"], row["s"], report_perspective(db, src, row["s"])),
            )


def set_beat_groups(db: Db, beat_id: str, groups: dict[str, str]) -> None:
    """Set a beat's outlet groups and re-tag the reports of its stories."""
    db.execute("MATCH (n:Beat {id: ?}) SET n.groups=?", (beat_id, json.dumps(groups)))
    for row in db.execute(
        "MATCH (s:Story {beat_id: ?}) MATCH (r:Report {story_id: s.id}) "
        "RETURN DISTINCT r.source_id AS id",
        (beat_id,),
    ):
        retag(db, row["id"])


def all_sources(db: Db, where: str = "true", args: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return nodes(db, "Source", f"MATCH (n:Source) WHERE {where} RETURN n", args)


def active_sources(db: Db) -> list[dict[str, Any]]:
    """Active sources in the shape of config/sources/schema.json, for the poller."""
    out = []
    for r in all_sources(db, "n.status='active'"):
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
        if r["crawl"]:
            e["crawl"] = json.loads(r["crawl"])
        for k in ("country", "state_run", "state_run_source", "owner_id", "ownership_source"):
            if r[k] is not None:
                e[k] = bool(r[k]) if k == "state_run" else r[k]
        out.append(e)
    return out


def create_story(db: Db, id: str, beat_id: str, title: str) -> None:
    create(
        db,
        "Story",
        {"id": id, "beat_id": beat_id, "title": title, "public": 0, "created_at": _now()},
    )


def get_story(db: Db, story_id: str) -> dict[str, Any] | None:
    rows = nodes(db, "Story", "MATCH (n:Story {id: ?}) RETURN n", (story_id,))
    return rows[0] if rows else None


def set_public(db: Db, story_id: str, public: bool) -> bool:
    """Admin toggle. False if the story does not exist."""
    return bool(
        db.execute("MATCH (n:Story {id: ?}) SET n.public=? RETURN 1 AS x", (story_id, int(public)))
    )


def stories(db: Db, *, public_only: bool) -> list[dict[str, Any]]:
    where = "WHERE n.public=1" if public_only else ""
    return [
        {k: r[k] for k in ("id", "beat_id", "title", "created_at")} | {"public": bool(r["public"])}
        for r in nodes(db, "Story", f"MATCH (n:Story) {where} RETURN n ORDER BY n.created_at")
    ]


def from_env() -> Neo4jDb:
    db = Neo4jDb(
        os.environ["NEO4J_URI"],
        os.environ.get("NEO4J_USER", "neo4j"),
        os.environ["NEO4J_PASSWORD"],
        os.environ.get("NEO4J_DATABASE") or None,
    )
    init(db)
    return db


class LiveSources(dict[str, dict[str, Any]]):
    """Source lookup that re-reads the store on a miss, so a long-lived service sees sources
    that discovery registered after it started."""

    def __init__(self, db: Db) -> None:
        super().__init__()
        self._db = db

    def __missing__(self, key: str) -> dict[str, Any]:
        self.clear()
        self.update({s["id"]: s for s in active_sources(self._db)})
        return self[key] if key in self else super().__getitem__(key)


def local_db() -> Neo4jDb:
    """An empty database for tests and evals: `NEO4J_URI` (default the local server), wiped."""
    db = Neo4jDb(
        os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        os.environ.get("NEO4J_USER", "neo4j"),
        os.environ.get("NEO4J_PASSWORD", "weft-test-pw"),
    )
    db.execute("MATCH (n) DETACH DELETE n")
    init(db)
    return db
