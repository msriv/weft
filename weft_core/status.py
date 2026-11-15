"""Admin status: "is it working", from data the system already writes (#176). Read-only, fixed
queries, thresholds from config/pipeline.yaml. States are operational (ok, slow, stopped); they
say nothing about the stories."""

from datetime import UTC, datetime, timedelta
from typing import Any

from weft_core import config
from weft_core.store import Db


def _state(age: timedelta | None, slow: timedelta, stopped: timedelta) -> str:
    if age is None or age > stopped:
        return "stopped"
    return "slow" if age > slow else "ok"


def _age(t: str | None, now: datetime) -> timedelta | None:
    if not t:
        return None
    return now - datetime.fromisoformat(t).astimezone(UTC)


def iso(d: datetime) -> str:
    return d.isoformat()


def collect(
    db: Db, now: datetime | None = None, cfg: dict[str, Any] | None = None
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    c = cfg or config.pipeline()["status"]
    stored = {
        "last_hour": iso(now - timedelta(hours=1)),
        "last_day": iso(now - timedelta(days=1)),
    }
    counts = {
        k: db.execute(
            "MATCH (r:Report) WHERE r.valid_to IS NULL AND r.fetched_at >= ? RETURN count(r) AS n",
            (since,),
        )[0]["n"]
        for k, since in stored.items()
    }
    newest = db.execute("MATCH (r:Report) RETURN max(r.fetched_at) AS t")[0]["t"]
    age = _age(newest, now)
    ingest = {
        "state": _state(
            age,
            timedelta(minutes=c["ingest_slow_minutes"]),
            timedelta(minutes=c["ingest_stopped_minutes"]),
        ),
        "stored": counts,
        "newest_report_at": newest,
    }
    placed = db.execute(
        "MATCH (r:Report) WHERE r.valid_to IS NULL AND r.fetched_at >= ? "
        "OPTIONAL MATCH (s:Story {id: r.story_id}) "
        "RETURN coalesce(s.beat_id, 'unplaced') AS beat, count(r) AS n ORDER BY beat",
        (stored["last_day"],),
    )
    stages: dict[str, str] = {}
    for r in db.execute("MATCH (b:BatchRun) RETURN b.stage AS stage, max(b.started_at) AS t"):
        stages[r["stage"]] = r["t"]
    last_stage = max(stages.values(), default=None)
    stage_age = _age(last_stage, now)
    nightly = {
        "state": _state(
            stage_age,
            timedelta(hours=c["stage_slow_hours"]),
            timedelta(hours=c["stage_stopped_hours"]),
        ),
        "stages": [{"stage": s, "last_start": t} for s, t in sorted(stages.items())],
    }
    cutoff = iso(now - timedelta(days=c["silent_source_days"]))
    last = {
        r["id"]: r["t"]
        for r in db.execute("MATCH (r:Report) RETURN r.source_id AS id, max(r.fetched_at) AS t")
    }
    active = db.execute("MATCH (s:Source) WHERE s.status = 'active' RETURN s.id AS id")
    silent = [r["id"] for r in active if (last.get(r["id"]) or "") < cutoff]
    graph = {
        "nodes": db.execute("MATCH (n) RETURN count(n) AS n")[0]["n"],
        "limit": None,
    }
    return {
        "as_of": iso(now),
        "ingest": ingest,
        "per_beat_today": [{"beat": r["beat"], "reports": r["n"]} for r in placed],
        "nightly": nightly,
        "sources": {
            "active": len(active),
            "silent": len(silent),
            "silent_days": c["silent_source_days"],
            "silent_ids": silent[:20],
        },
        "graph": graph,
        # not available until the model client (#157) and queue probes land: shown as such
        "model_spend": None,
        "queue": None,
    }
