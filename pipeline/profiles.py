"""Nightly: rebuild each beat's relevance profile (#107) from its last 14 days of reports."""

from datetime import datetime

from pipeline.ctx import Ctx
from weft_core import relevance, store


def run(ctx: Ctx) -> int:
    now = datetime.fromisoformat(ctx.now)
    built = 0
    for b in store.beats(ctx.db):
        prof = relevance.build(ctx.db, b["id"], now)
        relevance.save(ctx.db, b["id"], prof, ctx.now)
        built += prof is not None
    return built
