"""Nightly runner. `python -m pipeline.run` runs every stage in order; `--stage NAME` re-runs one;
`--from NAME` resumes. Each stage's start, end, row count and status go to `batch_runs`."""

import argparse
import sys
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from pipeline import (
    anomalies,
    claims,
    figures,
    groups,
    notify,
    regroup,
    review_sample,
    short_version,
    snapshot,
    statements,
    weights,
)
from pipeline.ctx import Ctx
from weft_core import graph

STAGES: dict[str, Callable[[Ctx], int]] = {
    "regroup": regroup.run,
    "claims": claims.run,
    "figures": figures.run,
    "claim_groups": groups.run_groups,
    "conflicts": groups.run_conflicts,
    "short_version": short_version.run,
    "statements": statements.run,
    "anomalies": anomalies.run,
    "weights": weights.run,
    "snapshot": lambda ctx: snapshot.run(ctx, _sink()),
    "review_sample": review_sample.run,
    "notify": notify.run,
}


def _sink() -> snapshot.Sink | None:
    import os

    bucket = os.environ.get("SNAPSHOT_BUCKET")
    return snapshot.GcsSink(bucket) if bucket else None


def run_stages(ctx: Ctx, only: str | None = None, start: str | None = None) -> dict[str, int]:
    names = list(STAGES)
    if only:
        names = [only]
    elif start:
        names = names[names.index(start) :]
    run_id = uuid.uuid4().hex[:12]
    done: dict[str, int] = {}
    for name in names:
        began = datetime.now(UTC).isoformat()
        ctx.db.execute(
            "INSERT INTO batch_runs(run_id,stage,started_at,status) VALUES(?,?,?,'running')",
            (run_id, name, began),
        )
        try:
            rows = STAGES[name](ctx)
        except Exception as exc:
            ctx.db.execute(
                "UPDATE batch_runs SET ended_at=?,status='failed',error=? WHERE run_id=? AND stage=?",
                (datetime.now(UTC).isoformat(), repr(exc)[:500], run_id, name),
            )
            raise
        ctx.db.execute(
            "UPDATE batch_runs SET ended_at=?,rows_out=?,status='ok' WHERE run_id=? AND stage=?",
            (datetime.now(UTC).isoformat(), rows, run_id, name),
        )
        print(f'{{"event":"stage_done","stage":"{name}","rows":{rows}}}')
        done[name] = rows
    return done


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=list(STAGES))
    ap.add_argument("--from", dest="start", choices=list(STAGES))
    args = ap.parse_args(argv)
    ctx = production_ctx()
    run_stages(ctx, args.stage, args.start)
    return 0


def production_ctx() -> Ctx:
    import os

    from pipeline.gcp import GcsText, bq_sink, versions_of
    from weft_core import config, store
    from weft_core.models import ModelClient
    from weft_core.nlp import default_nlp

    db = store.from_env()
    graph.init(db)
    project = os.environ["PROJECT_ID"]
    model = ModelClient(
        base_url=os.environ["MODEL_BASE_URL"],
        api_key=os.environ["MODEL_API_KEY"],
        model=os.environ["MODEL_NAME"],
        revision=os.environ["MODEL_REVISION"],
        log=bq_sink(project),
    )
    raw = os.environ["RAW_BUCKET"]
    return Ctx(
        db,
        config.pipeline(),
        default_nlp(),
        GcsText(raw).text,
        model,
        versions_of=versions_of(raw, db),
    )


if __name__ == "__main__":
    sys.exit(main())
