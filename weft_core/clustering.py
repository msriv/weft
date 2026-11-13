"""Event clustering math (#104), pure functions shared by the stream worker, the nightly
regroup and the replay eval. No database access here.

Score of a report against an event:
    w_cos  * max(cosine to centroid, mean cosine to the 3 nearest member reports)
  + w_ent  * IDF-weighted cosine between the report's entities and the event's entity counts
  + w_time * exp(-hours since the event's last report / decay)
Beat-wide entities (Israel, Iran, Kyiv) have low IDF, so they carry little weight. Hard veto:
no attach unless the report shares an entity whose IDF is above the story's median.
"""

import math
from collections import Counter
from collections.abc import Iterable
from datetime import datetime
from statistics import median
from typing import Any

from weft_core.textutil import cosine


def idf_table(df: Counter[str], n_docs: int) -> dict[str, float]:
    """Smoothed IDF from document frequencies over `n_docs` reports."""
    return {e: math.log((1 + n_docs) / (1 + d)) + 1.0 for e, d in df.items()}


def entity_counts(event: dict[str, Any]) -> dict[str, int]:
    """Per-event entity counts; events written before #104 only have the entity list."""
    counts = event.get("entity_counts")
    if counts:
        return {str(k): int(v) for k, v in counts.items()}
    return dict.fromkeys(event.get("entities") or [], 1)


def entity_cosine(ents: Iterable[str], counts: dict[str, int], idf: dict[str, float]) -> float:
    a = {e: idf.get(e, 1.0) for e in ents}
    b = {e: n * idf.get(e, 1.0) for e, n in counts.items()}
    dot = sum(w * b[e] for e, w in a.items() if e in b)
    na = math.sqrt(sum(w * w for w in a.values()))
    nb = math.sqrt(sum(w * w for w in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def vetoed(ents: set[str], counts: dict[str, int], idf: dict[str, float]) -> bool:
    """True when the report shares no informative entity with the event. Reports with no
    entities at all are not vetoed (nothing to compare)."""
    if not ents or not idf:
        return False
    cut = median(idf.values())
    return not any(idf.get(e, cut + 1) > cut for e in ents & set(counts))


def hours(a: str, b: str) -> float:
    return abs((datetime.fromisoformat(a) - datetime.fromisoformat(b)).total_seconds()) / 3600


def score(
    vec: list[float],
    ents: set[str],
    when: str,
    event: dict[str, Any],
    cfg: dict[str, Any],
    idf: dict[str, float] | None = None,
    members: list[list[float]] | None = None,
    veto: bool = False,
) -> float:
    """`veto` only once the story has enough reports for IDF to tell common from rare."""
    counts = entity_counts(event)
    if veto and idf and vetoed(ents, counts, idf):
        return 0.0
    w = cfg["weights"]
    cos = cosine(vec, event["centroid"])
    if members:
        top = sorted((cosine(vec, m) for m in members), reverse=True)[: cfg.get("member_top_k", 3)]
        cos = max(cos, sum(top) / len(top))
    last = event.get("last_seen") or event["first_seen"]
    t = math.exp(-hours(when, last) / cfg["time_decay_hours"])
    return float(
        w["cosine"] * cos + w["entities"] * entity_cosine(ents, counts, idf or {}) + w["time"] * t
    )


def mean_vec(centroid: list[float], n: int, vec: list[float]) -> list[float]:
    m = [(c * n + v) / (n + 1) for c, v in zip(centroid, vec, strict=True)]
    norm = math.sqrt(sum(x * x for x in m)) or 1.0
    return [x / norm for x in m]


def absorb(event: dict[str, Any], vec: list[float], ents: set[str], when: str) -> dict[str, Any]:
    """The event's fields after one more report."""
    counts = Counter(entity_counts(event))
    counts.update(ents)
    last = event.get("last_seen") or event["first_seen"]
    return {
        "centroid": mean_vec(event["centroid"], event["n_reports"], vec),
        "entity_counts": dict(counts),
        "entities": [e for e, _ in counts.most_common(60)],
        "n_reports": event["n_reports"] + 1,
        "last_seen": max(last, when),
    }


def bcubed(pred: dict[str, str], gold: dict[str, str]) -> dict[str, float]:
    """B-cubed precision, recall and F1 of a clustering against gold labels, over the items
    present in both."""
    items = [i for i in gold if i in pred]
    if not items:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0, "n": 0}
    by_p: dict[str, set[str]] = {}
    by_g: dict[str, set[str]] = {}
    for i in items:
        by_p.setdefault(pred[i], set()).add(i)
        by_g.setdefault(gold[i], set()).add(i)
    p = sum(len(by_p[pred[i]] & by_g[gold[i]]) / len(by_p[pred[i]]) for i in items) / len(items)
    r = sum(len(by_p[pred[i]] & by_g[gold[i]]) / len(by_g[gold[i]]) for i in items) / len(items)
    return {
        "precision": p,
        "recall": r,
        "f1": 2 * p * r / (p + r) if p + r else 0.0,
        "n": len(items),
    }
