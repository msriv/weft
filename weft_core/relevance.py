"""Beat relevance from a profile, not regex alone (#107).

A beat's profile is the embedding centroid of its last 14 days of placed reports plus their
IDF-weighted entities, rebuilt nightly. A report's relevance to a beat is

    0.5 * cosine(report, profile centroid) + 0.3 * entity overlap + 0.2 * regex hit

and an exclusion pattern sets it to 0. Before a beat has a profile (fewer than MIN_REPORTS
placed reports) relevance is the regex alone, so a new beat can start. Scores in the "maybe" band
are recorded for the owner to label; those labels are the eval set.
"""

import json
import re
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from weft_core import beats, clustering, store
from weft_core.textutil import cosine

PROFILE_DAYS = 14
MIN_REPORTS = 10
ACCEPT = 0.5
MAYBE = 0.35
W_COS, W_ENT, W_RE = 0.5, 0.3, 0.2


def regex(beat: dict[str, Any], text: str) -> float | None:
    """1 for a pattern hit, 0 for none, None when an exclusion matches (never relevant)."""
    flat = " ".join(text.split())
    if any(re.search(p, flat, re.IGNORECASE) for p in beat.get("exclude") or []):
        return None
    return 1.0 if beats.matches(beat, text) else 0.0


def score(
    beat: dict[str, Any],
    prof: dict[str, Any] | None,
    text: str,
    vec: list[float] | None,
    ents: set[str],
) -> float:
    hit = regex(beat, text)
    if hit is None:
        return 0.0
    if not prof:
        return hit
    ent = clustering.entity_cosine({e.lower() for e in ents}, prof["entities"], {})
    if vec is None:  # no embedding (discovery rows): rescale the other two parts
        return (W_ENT * ent + W_RE * hit) / (W_ENT + W_RE)
    return W_COS * max(0.0, cosine(vec, prof["centroid"])) + W_ENT * ent + W_RE * hit


def build(db: store.Db, beat_id: str, now: datetime) -> dict[str, Any] | None:
    """Profile of a beat from its story's placed reports in the last PROFILE_DAYS."""
    since = (now - timedelta(days=PROFILE_DAYS)).isoformat()
    rows = db.execute(
        "MATCH (s:Story {beat_id: ?}) MATCH (r:Report {story_id: s.id}) "
        "WHERE r.valid_to IS NULL AND r.embedding IS NOT NULL "
        "AND coalesce(r.published_at, r.fetched_at) >= ? "
        "OPTIONAL MATCH (e:ReportEntity {report_id: r.id}) "
        "RETURN r.id AS id, r.embedding AS v, collect(DISTINCT e.name) AS names",
        (beat_id, since),
    )
    if len(rows) < MIN_REPORTS:
        return None
    vecs = [json.loads(r["v"]) if isinstance(r["v"], str) else r["v"] for r in rows]
    dim = len(vecs[0])
    centroid = [sum(v[k] for v in vecs) / len(vecs) for k in range(dim)]
    df: Counter[str] = Counter()
    for r in rows:
        df.update({n.lower() for n in r["names"]})
    idf = clustering.idf_table(df, len(rows))
    weights = {e: n * idf[e] for e, n in df.most_common(100)}
    return {"centroid": centroid, "entities": weights, "n": len(rows)}


def save(db: store.Db, beat_id: str, prof: dict[str, Any] | None, now: str) -> None:
    if prof is None:
        db.execute("MATCH (n:BeatProfile {beat_id: ?}) DETACH DELETE n", (beat_id,))
        return
    db.execute(
        "MERGE (n:BeatProfile {beat_id: ?}) SET n.centroid=?, n.entities=?, n.n=?, n.updated_at=?",
        (beat_id, json.dumps(prof["centroid"]), json.dumps(prof["entities"]), prof["n"], now),
    )


def load(db: store.Db) -> dict[str, dict[str, Any]]:
    return {
        r["b"]: {"centroid": json.loads(r["c"]), "entities": json.loads(r["e"]), "n": r["n"]}
        for r in db.execute(
            "MATCH (n:BeatProfile) RETURN n.beat_id AS b, n.centroid AS c, n.entities AS e, "
            "n.n AS n"
        )
    }


def best(
    all_beats: list[dict[str, Any]],
    profiles: dict[str, dict[str, Any]],
    text: str,
    vec: list[float] | None,
    ents: set[str],
) -> tuple[dict[str, Any] | None, float]:
    """The highest-scoring beat and its score (ties keep beat order)."""
    top: tuple[dict[str, Any] | None, float] = (None, 0.0)
    for b in all_beats:
        s = score(b, profiles.get(b["id"]), text, vec, ents)
        if s > top[1]:
            top = (b, s)
    return top


def record_maybe(db: store.Db, report_id: str, beat_id: str, s: float, now: str) -> None:
    db.execute(
        "MERGE (n:BeatMaybe {report_id: ?, beat_id: ?}) ON CREATE SET n.created_at=? SET n.score=?",
        (report_id, beat_id, now, s),
    )


def label_maybe(db: store.Db, report_id: str, beat_id: str, on_beat: bool, now: str) -> None:
    """Owner thumb up or down: kept as a labelled example for tuning, never per report."""
    db.execute(
        "MATCH (n:BeatMaybe {report_id: ?, beat_id: ?}) SET n.label=?, n.labelled_at=?",
        (report_id, beat_id, int(on_beat), now),
    )


def maybes(db: store.Db, limit: int = 50) -> list[dict[str, Any]]:
    return db.execute(
        "MATCH (n:BeatMaybe) WHERE n.label IS NULL "
        "OPTIONAL MATCH (r:Report {id: n.report_id}) WHERE r.valid_to IS NULL "
        "RETURN n.report_id AS report_id, n.beat_id AS beat_id, n.score AS score, "
        "r.title AS title, r.url AS url ORDER BY n.created_at DESC LIMIT ?",
        (limit,),
    )
