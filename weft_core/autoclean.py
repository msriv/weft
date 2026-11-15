"""Autoclean: named, versioned clean-up rules run by `pipeline.autoclean` (#146, #147).

Same shape as the anomaly rules engine: deterministic code, thresholds in `config/autoclean.yaml`,
every run logged. A rule has a `match` (count plus sample ids) and an `apply`. A rule in `dry_run`
only logs what it matched. A rule that matches more than its cap aborts and changes nothing.
A destructive rule (it deletes graph data) runs only after a good snapshot, so whatever it removes
still exists in a dated Parquet snapshot. Nothing here is decided by weight or by a model.
"""

import json
import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from weft_core import config
from weft_core.store import Db

SAMPLE_IDS = 20
BATCH = 10000
SNAPSHOT_MAX_AGE = timedelta(hours=36)


class Warehouse(Protocol):
    """BigQuery as autoclean sees it. `execute` returns the number of rows changed."""

    def query(self, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]: ...

    def execute(self, sql: str, params: dict[str, Any]) -> int: ...


Publish = Callable[[str, dict[str, Any]], None]  # (topic name, message)


@dataclass
class Env:
    db: Db
    now: datetime
    conf: dict[str, Any]  # this rule's settings: defaults overlaid with its own entry
    raw_retention_days: int = 30
    warehouse: Warehouse | None = None
    publish: Publish | None = None


@dataclass
class Match:
    matched: int
    of: int | None = None  # population the cap fraction applies to; None = row cap only
    samples: list[str] = field(default_factory=list)
    detail: str | None = None  # extra text for the run record, e.g. counts per beat


@dataclass(frozen=True)
class Rule:
    name: str
    version: int  # bump when the rule's logic changes; stored on every run
    match: Callable[[Env], Match]
    apply: Callable[[Env], int]  # returns rows changed; must be a no-op on a second run
    destructive: bool = False  # deletes graph data, so needs a good snapshot first


RULES: dict[str, Rule] = {}


def register(rule: Rule) -> Rule:
    RULES[rule.name] = rule
    return rule


def settings(cfg: dict[str, Any], name: str) -> dict[str, Any]:
    return {**cfg.get("defaults", {}), **(cfg.get("rules", {}).get(name) or {})}


def over_cap(m: Match, conf: dict[str, Any]) -> str | None:
    """Why this match is too big to act on, or None."""
    if m.matched > conf["max_rows"]:
        return f"matched {m.matched} rows, cap {conf['max_rows']}"
    if m.of and m.matched > conf["max_fraction"] * m.of:
        return f"matched {m.matched} of {m.of}, cap {conf['max_fraction']:.0%}"
    return None


def snapshot_ok(db: Db, now: datetime) -> bool:
    """The latest `snapshot` stage ended ok, less than 36 hours ago."""
    rows = db.execute(
        "MATCH (n:BatchRun {stage: 'snapshot'}) "
        "RETURN n.status AS status, n.ended_at AS ended_at ORDER BY n.started_at DESC LIMIT 1"
    )
    if not rows or rows[0]["status"] != "ok" or not rows[0]["ended_at"]:
        return False
    return now - datetime.fromisoformat(rows[0]["ended_at"]) < SNAPSHOT_MAX_AGE


def batched(db: Db, query: str, args: tuple[Any, ...] = ()) -> int:
    """Run a statement until a pass changes nothing. It must contain `LIMIT {batch}` and end with
    `RETURN count(*) AS n` of the rows that pass changed; deletes never run unbounded."""
    total = 0
    while True:
        done = int(db.execute(query.replace("{batch}", str(BATCH)), args)[0]["n"])
        total += done
        if done < BATCH:
            return total


def run_rule(
    db: Db,
    rule: Rule,
    cfg: dict[str, Any],
    *,
    run_id: str,
    now: datetime,
    snapshot_good: bool,
    warehouse: Warehouse | None = None,
    publish: Publish | None = None,
) -> dict[str, Any] | None:
    """Run one rule, write its `AutocleanRun` node, return the record (None if disabled)."""
    conf = settings(cfg, rule.name)
    if not conf.get("enabled", True):
        return None
    env = Env(db, now, conf, int(cfg.get("raw_retention_days", 30)), warehouse, publish)
    rec: dict[str, Any] = {
        "run_id": run_id,
        "rule": rule.name,
        "rule_version": rule.version,
        "mode": conf["mode"],
        "matched": 0,
        "changed": 0,
        "sample_ids": "[]",
        "started_at": datetime.now(UTC).isoformat(),
        "status": "ok",
        "note": None,
    }
    try:
        m = rule.match(env)
        rec["matched"], rec["sample_ids"] = m.matched, json.dumps(m.samples[:SAMPLE_IDS])
        rec["note"] = m.detail
        too_big = over_cap(m, conf)
        if conf["mode"] != "apply":
            rec["status"] = "dry_run"
            rec["note"] = f"would abort: {too_big}" if too_big else rec["note"]
        elif too_big:
            rec["status"], rec["note"] = "aborted", too_big
        elif rule.destructive and not snapshot_good:
            rec["status"], rec["note"] = "skipped", "no good snapshot in the last 36 hours"
        elif m.matched:
            rec["changed"] = rule.apply(env)
    except Exception as exc:  # noqa: BLE001  one failing rule must not stop the others
        rec["status"], rec["note"] = "failed", repr(exc)[:500]
    rec["ended_at"] = datetime.now(UTC).isoformat()
    from weft_core import store

    store.create(db, "AutocleanRun", rec)
    _log(rec)
    return rec


def _log(rec: dict[str, Any]) -> None:
    event = {"aborted": "autoclean_aborted", "failed": "autoclean_failed"}.get(
        rec["status"], "autoclean_rule"
    )
    line = {
        "severity": "ERROR" if rec["status"] in ("aborted", "failed") else "INFO",
        "event": event,
        "rule": rec["rule"],
        "rule_version": rec["rule_version"],
        "mode": rec["mode"],
        "status": rec["status"],
        "matched": rec["matched"],
        "changed": rec["changed"],
        "sample_ids": json.loads(rec["sample_ids"]),
        "note": rec["note"],
    }
    print(json.dumps(line))


def run_all(
    db: Db,
    now: datetime | None = None,
    *,
    warehouse: Warehouse | None = None,
    publish: Publish | None = None,
    cfg: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Every registered rule, in registration order. One rule failing does not stop the rest."""
    import weft_core.autoclean_rules  # noqa: F401  (registers the rules)

    cfg = cfg or config.load("autoclean.yaml")
    # the bucket lifecycle and this follow one Terraform variable, so they cannot drift
    cfg = {
        **cfg,
        "raw_retention_days": int(
            os.environ.get("RAW_RETENTION_DAYS") or cfg["raw_retention_days"]
        ),
    }
    now = now or datetime.now(UTC)
    run_id, good = uuid.uuid4().hex[:12], snapshot_ok(db, now)
    out = [
        run_rule(
            db,
            r,
            cfg,
            run_id=run_id,
            now=now,
            snapshot_good=good,
            warehouse=warehouse,
            publish=publish,
        )
        for r in RULES.values()
    ]
    return [r for r in out if r]
