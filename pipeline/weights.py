"""Nightly stage 9: one weight per source from a month of reports (fixed formula, see weights.py)."""

import json
from datetime import datetime, timedelta

from pipeline.ctx import Ctx
from weft_core import graph, rules, weights


def run(ctx: Ctx) -> int:
    cfg = ctx.rules
    since = (
        datetime.fromisoformat(ctx.now) - timedelta(days=cfg["weights"]["window_days"])
    ).isoformat()
    copied = set()
    for a in graph.select(ctx.db, "anomalies", "rule='copied_text' AND status!='withdrawn'"):
        copied.update(a["evidence_ids"])
    silent = {
        a["subject_id"]
        for a in graph.select(ctx.db, "anomalies", "rule='silent_edit' AND status!='withdrawn'")
    }
    n = 0
    for s in ctx.db.execute("SELECT id, type FROM sources WHERE status='active'"):
        reps = graph.select(
            ctx.db,
            "reports",
            "source_id=? AND COALESCE(published_at, fetched_at) >= ?",
            (s["id"], since),
        )
        if not reps:
            continue
        ids = {r["id"] for r in reps}
        claims = graph.select(
            ctx.db, "claims", f"report_id IN ({','.join('?' * len(ids))})", tuple(ids)
        )
        notes = sum(1 for r in reps if rules.CORRECTION.search(ctx.text_of(r)))
        n_silent = len(ids & silent)
        total = len(reps)
        factors = {
            "names_sources": (
                sum(rules.is_attributed(c["text"]) for c in claims) / len(claims)
                if claims
                else None
            ),
            "links_documents": None,  # needs outbound links from the fetcher; not collected yet
            "corrects_openly": notes / (notes + n_silent) if notes + n_silent else None,
            "silent_edits": min(1.0, n_silent / total),
            "copied_wording": len(ids & copied) / total,
            "opinion_share": sum(r["type"] != "news" for r in reps) / total,
        }
        w, insufficient = weights.compute(factors, s["type"], total, cfg)
        ctx.db.execute(
            "INSERT INTO source_weights(source_id,day,weight,factors,n_reports,insufficient) "
            "VALUES(?,?,?,?,?,?) ON CONFLICT(source_id,day) DO UPDATE SET weight=excluded.weight, "
            "factors=excluded.factors, n_reports=excluded.n_reports, insufficient=excluded.insufficient",
            (
                s["id"],
                ctx.now[:10],
                w,
                json.dumps({**factors, "silent_edit_count": n_silent}),
                total,
                int(insufficient),
            ),
        )
        n += 1
    return n
