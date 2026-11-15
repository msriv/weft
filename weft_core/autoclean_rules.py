"""The autoclean rules (#146). Importing this module registers them in `autoclean.RULES`.

Product rules these keep: nothing is removed because of source weight (6); raw article text is
processing-only and expires after `raw_retention_days` (5), also in BigQuery; model calls keep
every column rule 4 needs (model, revision, seed, template, input hash, output).
"""

import json
from collections import Counter
from datetime import timedelta
from typing import Any

from weft_core import store
from weft_core.autoclean import Env, Match, Rule, register

# --- stale_batch_runs (#150) ------------------------------------------------------------------


def _stale_runs(env: Env) -> list[dict[str, Any]]:
    cutoff = (env.now - timedelta(hours=env.conf["hours"])).isoformat()
    return env.db.execute(
        "MATCH (n:BatchRun {status: 'running'}) WHERE n.started_at < ? "
        "RETURN n.run_id AS run_id, n.stage AS stage",
        (cutoff,),
    )


def _stale_match(env: Env) -> Match:
    rows = _stale_runs(env)
    return Match(len(rows), None, [f"{r['run_id']}:{r['stage']}" for r in rows])


def _stale_apply(env: Env) -> int:
    rows = _stale_runs(env)
    for r in rows:
        env.db.execute(
            "MATCH (n:BatchRun {run_id: ?, stage: ?, status: 'running'}) "
            "SET n.status='abandoned', n.ended_at=?",
            (r["run_id"], r["stage"], env.now.isoformat()),
        )
        print(
            json.dumps(
                {"severity": "ERROR", "event": "stage_abandoned", "run_id": r["run_id"]}
                | {"stage": r["stage"]}
            )
        )
    return len(rows)


register(Rule("stale_batch_runs", 1, _stale_match, _stale_apply))

# --- claims_skipped (#150) --------------------------------------------------------------------

_SKIPPED = (
    "n.valid_to IS NULL AND n.story_id IS NOT NULL AND n.claims_extracted IS NULL "
    "AND coalesce(n.published_at, n.fetched_at) < ?"
)


def _skipped_cutoff(env: Env) -> tuple[str]:
    return ((env.now - timedelta(days=env.conf["days"])).isoformat(),)


def _skipped_match(env: Env) -> Match:
    rows = env.db.execute(
        f"MATCH (n:Report) WHERE {_SKIPPED} OPTIONAL MATCH (s:Story {{id: n.story_id}}) "
        "RETURN n.id AS id, s.beat_id AS beat",
        _skipped_cutoff(env),
    )
    per_beat = Counter(r["beat"] or "unknown" for r in rows)
    return Match(
        len(rows),
        None,
        [r["id"] for r in rows],
        "skipped per beat: " + json.dumps(dict(sorted(per_beat.items()))) if rows else None,
    )


def _skipped_apply(env: Env) -> int:
    # 0, not 1: claim extraction never read it. The anomaly rules treat both as "not read" (#106).
    rows = env.db.execute(
        f"MATCH (n:Report) WHERE {_SKIPPED} SET n.claims_extracted = 0 RETURN count(n) AS n",
        _skipped_cutoff(env),
    )
    return int(rows[0]["n"])


register(Rule("claims_skipped", 1, _skipped_match, _skipped_apply))

# --- unplaced_items (#150) --------------------------------------------------------------------

_UNPLACED_SQL = """
SELECT r.item_id, r.source_id, r.url, r.published_at, r.fetched_at, r.text_hash, e.title, e.summary
FROM `{ds}.raw_items` r JOIN `{ds}.extracted_items` e USING (item_id)
WHERE e.status = 'ok'
  AND r.fetched_at BETWEEN TIMESTAMP_SUB(@now, INTERVAL @max_hours HOUR)
                       AND TIMESTAMP_SUB(@now, INTERVAL @min_hours HOUR)
QUALIFY ROW_NUMBER() OVER (PARTITION BY r.item_id ORDER BY r.fetched_at DESC) = 1
"""


def _unplaced(env: Env) -> list[tuple[str, dict[str, Any]]]:
    """(topic, message) for each stored item that never reached the graph."""
    assert env.warehouse, "unplaced_items needs the warehouse"
    rows = env.warehouse.query(
        _UNPLACED_SQL,
        {
            "now": env.now,
            "min_hours": int(env.conf["min_age_hours"]),
            "max_hours": int(env.conf["max_age_days"]) * 24,
        },
    )
    sources = {s["id"]: s for s in store.active_sources(env.db)}
    placed: set[str] = set()
    ids = [r["item_id"] for r in rows]
    for i in range(0, len(ids), 1000):
        found = env.db.execute(
            "MATCH (n) WHERE (n:Report OR n:Document) AND n.id IN ? RETURN DISTINCT n.id AS id",
            (ids[i : i + 1000],),
        )
        placed |= {f["id"] for f in found}
    out = []
    for r in rows:
        src = sources.get(r["source_id"])
        if r["item_id"] in placed or src is None:  # a removed source: nothing to place it under
            continue
        # shortcut: correction_note and gov_links are not re-read from the raw copy, so a
        # re-published item loses them; add the re-read if lost items prove to carry them
        msg = {
            "item_id": r["item_id"],
            "source_id": r["source_id"],
            "url": r["url"],
            "title": r["title"],
            "summary": r["summary"],
            "published_at": (r["published_at"] or r["fetched_at"]).isoformat(),
            "text_hash": r["text_hash"],
        }
        out.append(("documents-new" if src.get("crawl") else "items-extracted", msg))
    return out


def _unplaced_match(env: Env) -> Match:
    items = _unplaced(env)
    return Match(len(items), None, [m["item_id"] for _, m in items])


def _unplaced_apply(env: Env) -> int:
    assert env.publish, "unplaced_items needs a publisher"
    items = _unplaced(env)
    for topic, msg in items:
        env.publish(topic, msg)
    return len(items)


register(Rule("unplaced_items", 1, _unplaced_match, _unplaced_apply))

# --- BigQuery retention (#153) ----------------------------------------------------------------


def _raw_cutoff(env: Env) -> dict[str, Any]:
    return {"cutoff": env.now - timedelta(days=env.raw_retention_days)}


def _bq_rule(name: str, table: str, col: str, when: str, hash_col: str) -> Rule:
    """Null `col` on rows past raw retention. Every other column stays. Rows still in the
    streaming buffer cannot be updated; the retention floor keeps them out of reach."""
    where = f"{when} < @cutoff AND {col} IS NOT NULL"

    def match(env: Env) -> Match:
        assert env.warehouse, f"{name} needs the warehouse"
        rows = env.warehouse.query(
            f"SELECT {hash_col} AS id FROM `{{ds}}.{table}` WHERE {where} LIMIT 20",
            _raw_cutoff(env),
        )
        n = env.warehouse.query(
            f"SELECT COUNT(*) AS n FROM `{{ds}}.{table}` WHERE {where}", _raw_cutoff(env)
        )[0]["n"]
        return Match(int(n), None, [str(r["id"]) for r in rows])

    def apply(env: Env) -> int:
        assert env.warehouse
        return env.warehouse.execute(
            f"UPDATE `{{ds}}.{table}` SET {col} = NULL WHERE {where}", _raw_cutoff(env)
        )

    return register(Rule(name, 1, match, apply))


# Rule 5: the article text sent to a model is raw text. Rule 4 needs the hash, not the text.
_bq_rule("model_call_inputs", "model_calls", "input", "called_at", "input_hash")
# The bucket lifecycle deleted the object; keep the row (dedupe needs URL and text hash).
_bq_rule("raw_uri_expired", "raw_items", "raw_gcs_uri", "fetched_at", "item_id")
