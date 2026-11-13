"""Replay eval for event clustering (#113).

A frozen window of stored reports (id, source, title, lede, time: summaries only, rule 5) is fed
through the same attach math the stream worker uses (`weft_core.clustering`), in time order, and
scored with B-cubed against the owner's event labels. Exports and labels live outside git (a
private bucket or `evals/private/`, which is ignored): Weft never ships real news as test data.

    python -m evals.replay export --story iran-israel-war --since 2026-11-01 --until 2026-11-08 \\
        --out evals/private/week.jsonl
    # label: copy the file, set "gold" on each row to an event name of your choosing
    python -m evals.replay score --rows evals/private/week.jsonl --sweep
"""

import argparse
import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from weft_core import clustering, config
from weft_core.nlp import Nlp

THRESHOLDS = [round(0.30 + 0.05 * i, 2) for i in range(11)]


def export(db: Any, story_id: str, since: str, until: str) -> list[dict[str, Any]]:
    rows = db.execute(
        "MATCH (r:Report {story_id: ?}) WHERE r.valid_to IS NULL "
        "AND coalesce(r.published_at, r.fetched_at) >= ? "
        "AND coalesce(r.published_at, r.fetched_at) <= ? "
        "RETURN r.id AS id, r.source_id AS source_id, r.title AS title, r.summary AS summary, "
        "coalesce(r.published_at, r.fetched_at) AS at, r.event_id AS event_id ORDER BY at",
        (story_id, since, until + "T23:59:59+00:00"),
    )
    # "gold" starts as Weft's current event; the owner corrects it
    return [{**r, "gold": r["event_id"]} for r in rows]


def replay(
    rows: list[dict[str, Any]], nlp: Nlp, cfg: dict[str, Any], threshold: float | None = None
) -> dict[str, str]:
    """Report id -> predicted cluster id, attaching in time order like the stream worker."""
    cut = cfg["attach_threshold"] if threshold is None else threshold
    window = timedelta(hours=cfg["candidate_window_hours"])
    events: dict[str, dict[str, Any]] = {}
    members: dict[str, list[list[float]]] = {}
    df: Counter[str] = Counter()
    out: dict[str, str] = {}
    for n, r in enumerate(sorted(rows, key=lambda r: r["at"])):
        text = f"{r['title'] or ''}. {r['summary'] or ''}".strip()
        vec = nlp.embedder.embed(text)
        ents = {name for name, _ in nlp.entities.extract(text)}
        idf = clustering.idf_table(df, n)
        veto = n >= cfg.get("veto_min_reports", 20)
        start = (datetime.fromisoformat(r["at"]) - window).isoformat()
        cands = [e for e in events.values() if (e.get("last_seen") or e["first_seen"]) >= start]
        scored = sorted(
            (
                (clustering.score(vec, ents, r["at"], e, cfg, idf, members[e["id"]], veto), e)
                for e in cands
            ),
            key=lambda x: -x[0],
        )
        if scored and scored[0][0] >= cut:
            e = scored[0][1]
            e.update(clustering.absorb(e, vec, ents, r["at"]))
        else:
            e = {
                "id": r["id"],
                "first_seen": r["at"],
                "last_seen": r["at"],
                "centroid": vec,
                "entity_counts": dict.fromkeys(ents, 1),
                "n_reports": 1,
            }
            events[e["id"]] = e
            members[e["id"]] = []
        members[e["id"]].append(vec)
        df.update(ents)
        out[r["id"]] = e["id"]
    return out


def score(
    rows: list[dict[str, Any]], nlp: Nlp, cfg: dict[str, Any], sweep: bool
) -> list[dict[str, Any]]:
    gold = {r["id"]: str(r["gold"]) for r in rows if r.get("gold")}
    cuts = THRESHOLDS if sweep else [cfg["attach_threshold"]]
    return [{"threshold": t, **clustering.bcubed(replay(rows, nlp, cfg, t), gold)} for t in cuts]


def main() -> None:
    from weft_core import store
    from weft_core.nlp import default_nlp

    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("export")
    ex.add_argument("--story", required=True)
    ex.add_argument("--since", required=True)
    ex.add_argument("--until", required=True)
    ex.add_argument("--out", required=True)
    sc = sub.add_parser("score")
    sc.add_argument("--rows", required=True)
    sc.add_argument("--sweep", action="store_true")
    a = ap.parse_args()
    cfg = config.pipeline()["stream"]
    if a.cmd == "export":
        rows = export(store.from_env(), a.story, a.since, a.until)
        Path(a.out).write_text("".join(json.dumps(r) + "\n" for r in rows))
        print(f"{len(rows)} reports written to {a.out}")
    else:
        rows = [json.loads(x) for x in Path(a.rows).read_text().splitlines() if x.strip()]
        for line in score(rows, default_nlp(), cfg, a.sweep):
            print(json.dumps(line))


if __name__ == "__main__":
    main()
