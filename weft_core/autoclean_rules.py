"""The autoclean rules (#146). Importing this module registers them in `autoclean.RULES`.

Product rules these keep: nothing is removed because of source weight (6); raw article text is
processing-only and expires after `raw_retention_days` (5), also in BigQuery; model calls keep
every column rule 4 needs (model, revision, seed, template, input hash, output).
"""

import json
import re
from collections import Counter
from datetime import timedelta
from typing import Any

from weft_core import schema, store
from weft_core.autoclean import Env, Match, Rule, batched, register

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

# --- schema drift (#148) ----------------------------------------------------------------------

_IDENT = re.compile(r"[A-Za-z_]\w*")


def _ident(name: str) -> str:
    if not _IDENT.fullmatch(
        name
    ):  # these come from a committed file, but they are built into Cypher
        raise ValueError(f"not an identifier: {name!r}")
    return name


def _retired_where(e: dict[str, Any]) -> str:
    return f"n.{_ident(e['property'])} IS NOT NULL" if e.get("property") else "true"


def _retired_match(env: Env) -> Match:
    total, samples = 0, []
    for e in schema.retired():
        label = _ident(e["label"])
        n = env.db.execute(f"MATCH (n:{label}) WHERE {_retired_where(e)} RETURN count(n) AS n")[0][
            "n"
        ]
        if n:
            total += n
            samples.append(f"{label}.{e['property']}" if e.get("property") else label)
    return Match(total, None, samples)


def _retired_apply(env: Env) -> int:
    changed = 0
    for e in schema.retired():
        label, where = _ident(e["label"]), _retired_where(e)
        match = f"MATCH (n:{label}) WHERE {where} WITH n LIMIT {{batch}} "
        if "property" not in e:
            q = match + "DETACH DELETE n RETURN count(*) AS n"
        elif e["action"] == "rename_to":
            old, new = _ident(e["property"]), _ident(e["to"])
            q = (
                match
                + f"SET n.{new} = coalesce(n.{new}, n.{old}) REMOVE n.{old} RETURN count(*) AS n"
            )
        else:
            q = match + f"REMOVE n.{_ident(e['property'])} RETURN count(*) AS n"
        changed += batched(env.db, q)
    return changed


# Deletes the nodes of a retired label, so it needs a good snapshot (the label is retired on
# purpose, which is why the cap in config/autoclean.yaml is off for it).
register(Rule("retired_schema", 1, _retired_match, _retired_apply, destructive=True))


def _undeclared(env: Env) -> list[str]:
    """Labels and properties in the database that NODES neither declares nor retires."""
    retired = schema.retired()
    out = []
    for r in env.db.execute(
        "CALL db.schema.nodeTypeProperties() YIELD nodeLabels, propertyName "
        "RETURN nodeLabels AS labels, propertyName AS prop"
    ):
        for label in r["labels"]:
            if any(e["label"] == label and "property" not in e for e in retired):
                continue  # the retired_schema rule owns it
            if label not in store.NODES:
                out.append(label)
            elif (
                r["prop"]
                and r["prop"] not in store.NODES[label]
                and not any(e["label"] == label and e.get("property") == r["prop"] for e in retired)
            ):
                out.append(f"{label}.{r['prop']}")
    return sorted(set(out))


def _undeclared_match(env: Env) -> Match:
    found = _undeclared(env)
    return Match(len(found), None, found)


# Report only, never deletes: these are leftovers of patches from before the drift check, and a
# person decides whether to declare, retire or migrate them.
register(Rule("undeclared_schema", 1, _undeclared_match, lambda env: 0))


def _extra_indexes(env: Env) -> list[str]:
    want = store.expected_indexes()
    return sorted(
        r["name"]
        for r in env.db.execute(
            "SHOW INDEXES YIELD name, type, labelsOrTypes, properties, owningConstraint "
            "WHERE type = 'RANGE' AND owningConstraint IS NULL "
            "RETURN name, labelsOrTypes, properties"
        )
        if not (
            len(r["labelsOrTypes"]) == 1
            and len(r["properties"]) == 1
            and (r["labelsOrTypes"][0], r["properties"][0]) in want
        )
    )


def _extra_indexes_match(env: Env) -> Match:
    found = _extra_indexes(env)
    return Match(len(found), None, found)


def _extra_indexes_apply(env: Env) -> int:
    found = _extra_indexes(env)
    for name in found:
        env.db.execute(f"DROP INDEX `{_ident(name)}` IF EXISTS")
    return len(found)


# Indexes `store.init` no longer creates. Dropping one loses no data; it only needs a rebuild.
register(Rule("stale_indexes", 1, _extra_indexes_match, _extra_indexes_apply))

# --- GCS (#154) --------------------------------------------------------------------------------


def _stale_state(env: Env) -> list[str]:
    """State blobs of a feed or portal that is gone or dead. The poller rewrites a feed's blob on
    every poll; the crawler only when a page changes, so it gets a longer window. Losing one only
    costs one unconditional fetch."""
    assert env.snapshots, "orphan_state needs the snapshots bucket"
    out = []
    for prefix, days in env.conf["prefix_days"].items():
        cutoff = env.now - timedelta(days=days)
        out += [b.name for b in env.snapshots.list(prefix) if b.updated < cutoff]
    return sorted(out)


def _state_match(env: Env) -> Match:
    found = _stale_state(env)
    return Match(len(found), None, found)


def _state_apply(env: Env) -> int:
    assert env.snapshots
    found = _stale_state(env)
    for name in found:
        env.snapshots.delete(name)
    return len(found)


register(Rule("orphan_state", 1, _state_match, _state_apply))

_DAY = re.compile(r"^(\d{4}-\d{2}-\d{2})/")


def _partial_snapshots(env: Env) -> list[str]:
    """Dated folders older than 2 days with no `_SUCCESS` (written last by the export)."""
    assert env.snapshots, "partial_snapshots needs the snapshots bucket"
    days: dict[str, bool] = {}
    for b in env.snapshots.list():
        if m := _DAY.match(b.name):
            days[m.group(1)] = days.get(m.group(1), False) or b.name.endswith("/_SUCCESS")
    cutoff = (env.now - timedelta(days=2)).date().isoformat()
    return sorted(d for d, ok in days.items() if not ok and d < cutoff)


def _partial_match(env: Env) -> Match:
    found = _partial_snapshots(env)
    return Match(len(found), None, found)


# Report only: a half-written day must be looked at, not tidied. Nothing deletes a snapshot.
register(Rule("partial_snapshots", 1, _partial_match, lambda env: 0))


def _raw_without_row(env: Env) -> list[str]:
    """Raw objects older than an hour with no `raw_items` row: the fetcher failed between the
    upload and the insert. The bucket lifecycle removes them anyway. Looks at the oldest
    `limit` objects per run."""
    assert env.raw and env.warehouse, "raw_without_row needs the raw bucket and the warehouse"
    cutoff = env.now - timedelta(hours=1)
    blobs = [b for b in env.raw.list(limit=env.conf["limit"]) if b.updated < cutoff]
    ids = sorted({b.name.split(".")[0] for b in blobs})
    have: set[str] = set()
    for i in range(0, len(ids), 5000):
        rows = env.warehouse.query(
            "SELECT DISTINCT item_id FROM `{ds}.raw_items` WHERE item_id IN UNNEST(@ids)",
            {"ids": ids[i : i + 5000]},
        )
        have |= {r["item_id"] for r in rows}
    return [i for i in ids if i not in have]


def _raw_match(env: Env) -> Match:
    found = _raw_without_row(env)
    return Match(len(found), None, found)


register(Rule("raw_without_row", 1, _raw_match, lambda env: 0))
