"""Nightly stage: detective mode (D20). Off unless DETECTIVE=on. Resolves open predictions by a
fixed rule over later reports (no model), then asks for new ones inside the stage's budget."""

from pipeline.ctx import Ctx
from weft_core import detective, store


def run(ctx: Ctx) -> int:
    if not detective.enabled() or ctx.model is None:
        return 0
    n = 0
    for s in store.stories(ctx.db, public_only=False):
        allow = ctx.budget(s["id"], "detective").take
        n += detective.check(ctx.db, ctx.nlp.nli, s["id"], ctx.now)
        n += detective.predict(ctx.db, ctx.model, s["id"], ctx.now, allow)
    return n
