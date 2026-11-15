"""Node and relationship counts, logged once a night (#165). AuraDB tiers have hard limits, and
writes fail at the limit, so an alert watches this line."""

import json

from weft_core.store import Db


def log(db: Db) -> dict[str, int]:
    """Print one `graph_size` JSON line and return the totals."""
    by_label = {
        r["label"] or "": r["n"]
        for r in db.execute("MATCH (n) RETURN head(labels(n)) AS label, count(n) AS n")
    }
    (rels,) = db.execute("MATCH ()-[r]->() RETURN count(r) AS n")
    out = {"nodes": sum(by_label.values()), "relationships": rels["n"]}
    print(json.dumps({"event": "graph_size", "severity": "INFO", **out, "by_label": by_label}))
    return out
