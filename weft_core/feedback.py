"""Owner feedback on anomalies (#114): the anomaly eval set. A label tunes a rule's thresholds
through `rules.yaml` version bumps and decides whether a rule may notify; it never decides a
single anomaly (rule 2)."""

import json
from datetime import UTC, datetime
from typing import Any

from weft_core import graph
from weft_core.store import Db

LABELS = ("useful", "not_useful", "wrong_grouping")


def label(db: Db, anomaly_id: str, value: str) -> dict[str, Any]:
    if value not in LABELS:
        raise ValueError(f"label must be one of {', '.join(LABELS)}")
    a = graph.get(db, "anomalies", anomaly_id)
    if a is None:
        raise KeyError(anomaly_id)
    db.execute(
        "MERGE (n:AnomalyFeedback {anomaly_id: ?}) "
        "SET n.rule=?, n.rule_version=?, n.inputs=?, n.label=?, n.at=?",
        (
            anomaly_id,
            a["rule"],
            a["rule_version"],
            json.dumps(a["inputs"]),
            value,
            datetime.now(UTC).isoformat(),
        ),
    )
    return {"anomaly_id": anomaly_id, "rule": a["rule"], "label": value}


def precision(db: Db) -> list[dict[str, Any]]:
    """Per rule and rule version: labelled, useful, and the useful share."""
    rows = db.execute(
        "MATCH (n:AnomalyFeedback) RETURN n.rule AS rule, n.rule_version AS version, "
        "n.label AS label"
    )
    by: dict[tuple[str, int], list[str]] = {}
    for r in rows:
        by.setdefault((r["rule"], r["version"]), []).append(r["label"])
    return [
        {
            "rule": rule,
            "rule_version": v,
            "labelled": len(ls),
            "useful": ls.count("useful"),
            "precision": ls.count("useful") / len(ls),
        }
        for (rule, v), ls in sorted(by.items())
    ]


def promoted(db: Db, cfg: dict[str, Any]) -> set[str]:
    """Rules allowed to fire as active (and so to notify): at least `min_labels` labels (any
    rules version) and at least `min_useful_share` of them useful. With the gate off, every
    rule is promoted."""
    gate = cfg.get("promotion") or {}
    if not gate.get("enabled"):
        return set(cfg["rules"])
    tally: dict[str, list[int]] = {}
    for p in precision(db):
        t = tally.setdefault(p["rule"], [0, 0])
        t[0] += p["labelled"]
        t[1] += p["useful"]
    return {
        r
        for r, (n, useful) in tally.items()
        if n >= gate["min_labels"] and useful / n >= gate["min_useful_share"]
    }
