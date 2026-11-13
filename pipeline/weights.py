"""Nightly stage 9: one weight per source from a month of reports (fixed formula, see weights.py)."""

import json
from datetime import datetime, timedelta
from typing import Any

from pipeline.ctx import Ctx
from weft_core import graph, rules, store, weights


def run(ctx: Ctx) -> int:
    cfg = ctx.rules
    since = (
        datetime.fromisoformat(ctx.now) - timedelta(days=cfg["weights"]["window_days"])
    ).isoformat()
    copied = set()
    for a in graph.select(ctx.db, "anomalies", "n.rule='copied_text' AND n.status<>'withdrawn'"):
        copied.update(a["evidence_ids"])
    silent = {
        a["subject_id"]
        for a in graph.select(ctx.db, "anomalies", "n.rule='silent_edit' AND n.status<>'withdrawn'")
    }
    citing = {
        r["r"]
        for r in ctx.db.execute(
            "MATCH (c:Cites) WHERE c.document_id IS NOT NULL RETURN DISTINCT c.report_id AS r"
        )
    }
    n = 0
    for s in store.all_sources(ctx.db, "n.status='active'"):
        reps = graph.select(
            ctx.db,
            "reports",
            # placed reports only: unplaced ones are off every beat
            "n.source_id=? AND n.story_id IS NOT NULL "
            "AND coalesce(n.published_at, n.fetched_at) >= ?",
            (s["id"], since),
        )
        if not reps:
            continue
        ids = {r["id"] for r in reps}
        claims = graph.select(ctx.db, "claims", "n.report_id IN ?", (list(ids),))
        notes = sum(1 for r in reps if _correction_note(ctx, r))
        n_silent = len(ids & silent)
        total = len(reps)
        factors = {
            "names_sources": (
                sum(bool(rules.NAMES_SOURCE.search(c["text"])) for c in claims) / len(claims)
                if claims
                else None
            ),
            # share of reports linking a stored official document (#108)
            "links_documents": len(ids & citing) / total,
            "corrects_openly": notes / (notes + n_silent) if notes + n_silent else None,
            "silent_edits": min(1.0, n_silent / total),
            "copied_wording": len(ids & copied) / total,
            "opinion_share": sum(r["type"] != "news" for r in reps) / total,
        }
        w, insufficient = weights.compute(factors, s["type"], total, cfg)
        ctx.db.execute(
            "MERGE (n:SourceWeight {source_id: ?, day: ?}) "
            "SET n.weight=?, n.factors=?, n.n_reports=?, n.insufficient=?",
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


def _correction_note(ctx: Ctx, r: dict[str, Any]) -> bool:
    """The flag set at ingest. shortcut: reports ingested before the flag existed are read from
    the raw copy; drop the fallback once they age out (30 days)."""
    if r.get("correction_note") is not None:
        return bool(r["correction_note"])
    return bool(rules.CORRECTION.search(ctx.text_of(r)))
