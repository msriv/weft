"""Nightly: link reports to documents by citation and by quotation (#108).

CITES: a report's outbound link to a government page (stored by the stream worker as a url key)
that equals a stored document's url. An unplaced document joins the citing report's event.

QUOTES: a quote in a report whose 5-word shingles are at least QUOTE_CONTAINMENT contained in a
statement from an official document of the same story, published within 7 days. The quote_differs
rule reads these pairs; this stage only measures. No model.
"""

import difflib
from datetime import datetime, timedelta
from typing import Any

from pipeline.ctx import Ctx
from pipeline.origins import containment
from weft_core import graph, portals
from weft_core.textutil import shingles, words

QUOTE_CONTAINMENT = 0.7
WINDOW = timedelta(days=7)


def edit_ratio(quote: str, statement: str) -> float:
    """Share of words that differ between a quote and the closest same-length window of the
    statement (0 = word for word)."""
    q, s = words(quote), words(statement)
    if not q or not s:
        return 1.0
    n = len(q)
    best = 0.0
    for i in range(max(1, len(s) - n + 1)):
        best = max(best, difflib.SequenceMatcher(None, q, s[i : i + n]).ratio())
    return round(1.0 - best, 4)


def cites(ctx: Ctx) -> int:
    docs: dict[str, dict[str, Any]] = {}
    for d in graph.select(ctx.db, "documents"):
        if d.get("url"):
            docs[portals.url_key(d["url"])] = d
    made = 0
    for c in ctx.db.execute(
        "MATCH (c:Cites) WHERE c.document_id IS NULL RETURN c.report_id AS r, c.url_key AS k"
    ):
        doc = docs.get(c["k"])
        if doc is None:
            continue
        ctx.db.execute(
            "MATCH (c:Cites {report_id: ?, url_key: ?}) SET c.document_id=?",
            (c["r"], c["k"], doc["id"]),
        )
        made += 1
        rep = graph.get(ctx.db, "reports", c["r"])
        if rep and rep.get("event_id") and not doc.get("event_id"):
            row = {k: v for k, v in doc.items() if k not in ("valid_from", "valid_to")}
            graph.put(ctx.db, "documents", {**row, "event_id": rep["event_id"]})
            doc["event_id"] = rep["event_id"]
    return made


def quotes(ctx: Ctx) -> int:
    since = datetime.fromisoformat(ctx.now) - timedelta(days=3)
    made = 0
    for story_id in {r["story_id"] for r in ctx.recent_reports(3)}:
        statements = ctx.db.execute(
            "MATCH (s:Statement) MATCH (d:Document {id: s.document_id}) "
            "WHERE d.valid_to IS NULL AND d.story_id = ? "
            "OPTIONAL MATCH (a:Actor {id: s.actor_id}) "
            "RETURN s.id AS id, s.text AS text, a.name AS actor, d.issuer_id AS issuer, "
            "coalesce(d.published_at, d.valid_from) AS at",
            (story_id,),
        )
        if not statements:
            continue
        sh = {s["id"]: shingles(s["text"] or "") for s in statements}
        for f in ctx.db.execute(
            "MATCH (f:Figure {kind: 'quote'}) WHERE f.valid_to IS NULL "
            "MATCH (r:Report {id: f.report_id}) WHERE r.valid_to IS NULL AND r.story_id = ? "
            "AND coalesce(r.published_at, r.fetched_at) >= ? "
            "RETURN f.id AS id, f.text AS text, coalesce(r.published_at, r.fetched_at) AS at",
            (story_id, since.isoformat()),
        ):
            q = shingles(f["text"] or "")
            at = datetime.fromisoformat(f["at"])
            for s in statements:
                if abs(datetime.fromisoformat(s["at"]) - at) > WINDOW:
                    continue
                c = containment(q, sh[s["id"]])
                if c < QUOTE_CONTAINMENT:
                    continue
                ctx.db.execute(
                    "MERGE (n:Quotes {figure_id: ?, statement_id: ?}) SET n.containment=?, "
                    "n.edit_ratio=?",
                    (f["id"], s["id"], round(c, 4), edit_ratio(f["text"], s["text"])),
                )
                made += 1
    return made


def run(ctx: Ctx) -> int:
    return cites(ctx) + quotes(ctx)
