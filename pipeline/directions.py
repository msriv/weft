"""Nightly stages for World directions (D22). Off unless DETECTIVE=on.

`series` (only with DIRECTIONS_SERIES=on) fetches ECB reference rates. `domains` builds domains
and their drivers. `directions` resolves open speculations first (fixed rules, no model), then
adds weekly template questions and, inside the caps and token budget, model speculations.
"""

import os
from datetime import datetime

import httpx

from pipeline.ctx import Budget, Ctx
from weft_core import detective, directions


def series_enabled() -> bool:
    return os.environ.get("DIRECTIONS_SERIES") == "on"


def run_series(ctx: Ctx, http: httpx.Client | None = None) -> int:
    if not (detective.enabled() and series_enabled()):
        return 0
    today = datetime.fromisoformat(ctx.now).date()
    own = http is None
    http = http or httpx.Client(timeout=30, headers={"User-Agent": "Weft/1.0 (news research)"})
    try:
        n = 0
        for d in directions.domains(ctx.db, active_only=True):
            cur = d.get("currency")
            if d["facet"] == "currency" and cur in directions.ECB:
                n += directions.fetch_series(ctx.db, http, cur, today)
        return n
    finally:
        if own:
            http.close()


def run_domains(ctx: Ctx) -> int:
    if not detective.enabled():
        return 0
    c = directions.cfg()
    now = datetime.fromisoformat(ctx.now)
    return sum(
        directions.build_drivers(ctx.db, d, now, c)
        for d in directions.build_domains(ctx.db, now, c)
    )


def run(ctx: Ctx) -> int:
    if not detective.enabled():
        return 0
    c = directions.cfg()
    g = c["generation"]
    n = 0
    active = directions.domains(ctx.db, active_only=True)
    for d in active:
        n += directions.resolve(ctx.db, ctx.nlp.nli, d, ctx.now, c)
    n += directions.template_questions(ctx.db, ctx.now)
    if ctx.model is None:
        return n
    budget = Budget(g["token_budget"])
    calls = 0
    for d in active:
        if calls >= g["max_calls_per_night"]:
            break
        before = d.get("last_called_at")
        n += directions.generate(ctx.db, ctx.model, ctx.nlp.embedder, d, ctx.now, c, budget.take)
        after = ctx.db.execute("MATCH (n:Domain {id: ?}) RETURN n.last_called_at AS t", (d["id"],))[
            0
        ]["t"]
        calls += after != before
    return n
