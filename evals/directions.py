"""World directions (D22, #130): backtest and kill criteria.

python -m evals.directions backtest --as-of 2026-10-01 [--live]
    For each active domain, picks drivers from the graph as it stood on the date, asks for
    speculations (recorded stub unless --live), and settles them against the graph now with the
    nightly rule. Nothing is written to the graph. Prints Brier against 0.5 and the base rate.

python -m evals.directions kill [--monthly-cost 1.20] [--useful-share 0.4]
    Checks the D22 kill criteria over stored domain speculations. Exits 1 when any criterion
    says turn model questions off. Only meaningful after 50 resolved or 90 days.
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from typing import Any

from weft_core import directions, graph, store
from weft_core.store import Db


def kill_criteria(
    preds: list[dict[str, Any]],
    domains: list[dict[str, Any]],
    monthly_cost: float | None = None,
    useful_share: float | None = None,
) -> dict[str, Any]:
    """Each D22 criterion with its value and whether it says stop."""
    model = [p for p in preds if p.get("origin", "model") == "model"]
    s = directions.score(model)
    resolved = s["resolved"]
    expired = s["counts"]["expired"] / resolved if resolved else 0.0
    proposed = sum(int(d.get("proposed") or 0) for d in domains)
    dropped = sum(int(d.get("dropped") or 0) for d in domains) / proposed if proposed else 0.0
    off = max(
        (abs(b["said"] - b["happened"]) for b in s["calibration"] if b["n"] >= 5), default=0.0
    )
    checks: dict[str, dict[str, Any]] = {
        "brier_beats_base_rate": {
            "value": [s["brier"], s["brier_base_rate"]],
            "stop": s["brier"] is not None
            and s["brier_base_rate"] is not None
            and s["brier"] >= s["brier_base_rate"],
        },
        "expired_share": {"value": expired, "stop": expired > 0.40},
        "dropped_share": {"value": dropped, "stop": dropped > 0.30},
        "worst_decile_gap": {"value": off, "stop": off > 0.20},
        "monthly_cost_usd": {
            "value": monthly_cost,
            "stop": monthly_cost is not None and monthly_cost > 3.0,
        },
        "useful_share": {
            "value": useful_share,
            "stop": useful_share is not None and useful_share < 0.30,
        },
    }
    return {
        "resolved": resolved,
        "review_due": resolved >= 50,
        "checks": checks,
        "stop": any(c["stop"] for c in checks.values()),
    }


def backtest(db: Db, as_of: datetime, model: Any, nli: Any, embedder: Any) -> dict[str, Any]:
    c = directions.cfg()
    now = datetime.now(as_of.tzinfo)
    out: list[dict[str, Any]] = []
    for d in directions.domains(db, active_only=True):
        since = (as_of - timedelta(days=c["domains"]["window_days"])).isoformat()
        past = [
            g
            for g in graph.select(db, "claim_groups", "true", (), as_of.isoformat())
            if (g["valid_from"] or "") >= since
        ]
        reps = directions._group_reports(db, [g["id"] for g in past])
        names: dict[str, set[str]] = {}
        if d["subject_kind"] == "country":
            for row in db.execute(
                "MATCH (e:ReportEntity) RETURN e.report_id AS r, e.name AS n, e.wikidata_id AS w"
            ):
                code = directions.country_of(row["n"], row["w"])
                if code:
                    names.setdefault(row["r"], set()).add(code)
        ds = directions.pick_drivers(d, past, reps, names, as_of, c)
        if len(ds) < c["generation"]["min_cited_groups"]:
            continue
        got = directions.propose(
            db, model, embedder, d, ds, [], as_of.isoformat(), c, c["generation"]["max_new"]
        )
        later = [{"id": g["id"], "label": g["label"]} for g in graph.select(db, "claim_groups")]
        for p in (got or ([], 0, 0))[0]:
            status, ev = directions.settle(
                db, nli, p, later, now.date().isoformat(), c["resolution"]
            )
            out.append(p | {"status": status, "evidence": ev, "domain_id": d["id"]})
    return {"as_of": as_of.isoformat(), "speculations": out, "score": directions.score(out)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backtest")
    b.add_argument("--as-of", required=True)
    b.add_argument("--live", action="store_true")
    k = sub.add_parser("kill")
    k.add_argument("--monthly-cost", type=float)
    k.add_argument("--useful-share", type=float)
    a = ap.parse_args(argv)
    db = store.from_env()
    if a.cmd == "kill":
        preds = store.nodes(
            db, "Prediction", "MATCH (n:Prediction) WHERE n.domain_id IS NOT NULL RETURN n"
        )
        res = kill_criteria(preds, directions.domains(db), a.monthly_cost, a.useful_share)
        print(json.dumps(res, indent=2))
        return 1 if res["stop"] else 0
    from evals.run import _client
    from weft_core.nlp import default_nlp

    nlp = default_nlp()
    # without --live the stub proposes nothing: the run only checks the plumbing
    model = _client(None, []) if a.live else _client({"": '{"speculations": []}'}, [""])
    as_of = datetime.fromisoformat(a.as_of + "T00:00:00+00:00")
    print(json.dumps(backtest(db, as_of, model, nlp.nli, nlp.embedder), indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
