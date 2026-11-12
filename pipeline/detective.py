"""Nightly stage: detective mode (D20). Off unless DETECTIVE=on. Checks open predictions against
the day's new reports, then asks for new ones, inside each beat's token budget."""

from pipeline.ctx import Ctx
from weft_core import detective, store


def run(ctx: Ctx) -> int:
    if not detective.enabled() or ctx.model is None:
        return 0
    n = 0
    for s in store.stories(ctx.db, public_only=False):
        allow = ctx.budget(s["id"], "detective").take
        n += detective.check(ctx.db, ctx.model, s["id"], ctx.now, allow)
        n += detective.predict(ctx.db, ctx.model, s["id"], ctx.now, allow)
    return n
