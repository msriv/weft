"""Autoclean rules that compact old node versions without changing what Replay shows (#151).
Importing this module registers them.

The graph keeps every version of a node (a change closes one and opens the next), and the owner
decided on 2026-11-14 to keep that history forever: nothing here deletes history past a horizon.
Both rules only remove what Replay cannot see:

- `strip_closed_vectors` drops the embedding and friends from closed `Report` and `Event`
  versions. `readmodel` strips those fields from every row it serves, and no reader of a closed
  version uses them.
- `collapse_intraday_versions` drops versions that were opened and closed within one UTC day.
  Replay resolves a date to the end of that day, so such a version is never the one shown.
  The version that replaced the last of them takes over its start time, so the timeline has no
  gap and `snapshot.diff` still sees one hop from the version before to the version after.

`Anomaly` is never touched: its history is the audit trail (product rule 2).
"""

from collections import defaultdict
from datetime import timedelta
from typing import Any

from weft_core.autoclean import Env, Match, Rule, register
from weft_core.autoclean_graph import VERSIONED, _count

VECTORS = {"Report": ("embedding", "minhash"), "Event": ("centroid", "entity_counts")}
CHUNK = 20000


def _cutoff(env: Env) -> tuple[str]:
    return ((env.now - timedelta(days=env.conf["days"])).isoformat(),)


def _has_vectors(label: str) -> str:
    return " OR ".join(f"n.{p} IS NOT NULL" for p in VECTORS[label])


def _strip_match(env: Env) -> Match:
    total, of, samples = 0, 0, []
    for label in VECTORS:
        where = f"n.valid_to IS NOT NULL AND n.valid_to < ? AND ({_has_vectors(label)})"
        total += _count(env, f"MATCH (n:{label}) WHERE {where} RETURN count(n) AS n", _cutoff(env))
        of += _count(env, f"MATCH (n:{label}) WHERE n.valid_to IS NOT NULL RETURN count(n) AS n")
        rows = env.db.execute(
            f"MATCH (n:{label}) WHERE {where} RETURN n.id AS id, n.valid_from AS f LIMIT 20",
            _cutoff(env),
        )
        samples += [f"{label}:{r['id']}@{r['f']}" for r in rows]
    return Match(total, of, samples)


def _strip_apply(env: Env) -> int:
    from weft_core.autoclean import batched

    return sum(
        batched(
            env.db,
            f"MATCH (n:{label}) WHERE n.valid_to IS NOT NULL AND n.valid_to < ? AND "
            f"({_has_vectors(label)}) WITH n LIMIT {{batch}} "
            f"REMOVE {', '.join(f'n.{p}' for p in props)} RETURN count(*) AS n",
            _cutoff(env),
        )
        for label, props in VECTORS.items()
    )


register(Rule("strip_closed_vectors", 1, _strip_match, _strip_apply, destructive=True))


def _groups(env: Env, label: str) -> list[list[dict[str, Any]]]:
    """Runs of consecutive same-day versions of one id that a later version follows (so the last
    version of that day is kept). Each version is {id, f, t, next_from}."""
    rows = env.db.execute(
        f"MATCH (n:{label}) WHERE n.valid_to IS NOT NULL AND n.valid_to < ? AND "
        "substring(n.valid_from, 0, 10) = substring(n.valid_to, 0, 10) "
        f"RETURN n.id AS id, n.valid_from AS f, n.valid_to AS t ORDER BY id, f LIMIT {CHUNK}",
        _cutoff(env),
    )
    if len(rows) == CHUNK:  # the last id may be cut off; the next run finishes it
        last = rows[-1]["id"]
        rows = [r for r in rows if r["id"] != last]
    by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_id[r["id"]].append(r)
    runs: list[list[dict[str, Any]]] = []
    for versions in by_id.values():
        run = [versions[0]]
        for v in versions[1:]:
            if v["f"] == run[-1]["t"]:
                run.append(v)
            else:
                runs.append(run)
                run = [v]
        runs.append(run)
    # keep only runs whose successor version exists
    ends = [{"id": r[-1]["id"], "t": r[-1]["t"]} for r in runs]
    have = {
        (b["id"], b["f"])
        for b in env.db.execute(
            f"UNWIND ? AS p MATCH (b:{label} {{id: p.id, valid_from: p.t}}) "
            "RETURN b.id AS id, b.valid_from AS f",
            (ends,),
        )
    }
    return [r for r in runs if (r[-1]["id"], r[-1]["t"]) in have]


def _collapse_labels() -> list[str]:
    return [label for label in VERSIONED if label != "Anomaly"]


def _collapse_match(env: Env) -> Match:
    total, of, samples = 0, 0, []
    for label in _collapse_labels():
        runs = _groups(env, label)
        total += sum(len(r) for r in runs)
        of += _count(env, f"MATCH (n:{label}) RETURN count(n) AS n")
        samples += [f"{label}:{r[0]['id']}@{r[0]['f']}" for r in runs[:5]]
    return Match(total, of, samples)


def _collapse_apply(env: Env) -> int:
    removed = 0
    for label in _collapse_labels():
        while runs := _groups(env, label):
            for run in runs:
                # delete first: the successor keeps its own start until it is re-dated, so a
                # list of the run's start times can never match it
                env.db.execute(
                    f"MATCH (n:{label} {{id: ?}}) WHERE n.valid_from IN ? AND n.valid_to IS NOT NULL "
                    "DELETE n",
                    (run[0]["id"], [v["f"] for v in run]),
                )
                env.db.execute(
                    f"MATCH (b:{label} {{id: ?, valid_from: ?}}) SET b.valid_from = ?",
                    (run[0]["id"], run[-1]["t"], run[0]["f"]),
                )
                removed += len(run)
    return removed


register(Rule("collapse_intraday_versions", 1, _collapse_match, _collapse_apply, destructive=True))
