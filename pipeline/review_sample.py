"""Nightly stage 11: queue the review sample."""

from datetime import datetime, timedelta

from pipeline.ctx import Ctx
from weft_core import review


def run(ctx: Ctx) -> int:
    since = (datetime.fromisoformat(ctx.now) - timedelta(days=1)).isoformat()
    return review.sample(ctx.db, since, ctx.cfg["nightly"]["review_sample_rate"], ctx.now)
