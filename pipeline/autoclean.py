"""The `autoclean` stage (#147): `python -m pipeline.run --stage autoclean`. Runs every rule in
`weft_core.autoclean` and returns how many rows the rules changed (0 while all are in dry_run)."""

from datetime import datetime

from pipeline.ctx import Ctx
from weft_core import autoclean


def run(ctx: Ctx) -> int:
    recs = autoclean.run_all(
        ctx.db,
        datetime.fromisoformat(ctx.now),
        warehouse=ctx.warehouse,
        publish=ctx.publish,
        snapshots=ctx.snapshots,
        raw=ctx.raw_blobs,
    )
    return sum(r["changed"] for r in recs)
