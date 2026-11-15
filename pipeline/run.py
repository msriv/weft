"""Nightly runner. `python -m pipeline.run` runs every stage in order; `--stage NAME` re-runs one;
`--from NAME` resumes. Stage order lives in config/pipeline.yaml `stages`. Each stage's start, end,
row count and status go to `BatchRun` nodes in the graph."""

import argparse
import sys
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from pipeline import (
    anomalies,
    autoclean,
    claims,
    detective,
    directions,
    figures,
    groups,
    links,
    notify,
    origins,
    profiles,
    regroup,
    review_sample,
    short_version,
    snapshot,
    statements,
    threads,
    weights,
)
from pipeline.ctx import Ctx
from weft_core import config, graph

STAGES: dict[str, Callable[[Ctx], int]] = {
    "regroup": regroup.run,
    "threads": threads.run,
    "origins": origins.run,
    "claims": claims.run,
    "figures": figures.run,
    "claim_groups": groups.run_groups,
    "conflicts": groups.run_conflicts,
    "short_version": short_version.run,
    "statements": statements.run,
    "links": links.run,
    "anomalies": anomalies.run,
    "weights": weights.run,
    "detective": detective.run,
    "series": directions.run_series,
    "domains": directions.run_domains,
    "directions": directions.run,
    "snapshot": lambda ctx: snapshot.run(ctx, _sink()),
    "profiles": profiles.run,
    "review_sample": review_sample.run,
    "notify": notify.run,
    # Not in the Terraform nightly list: it has its own scheduler job (#147). Last, so a local
    # `python -m pipeline.run` cleans after the nightly.
    "autoclean": autoclean.run,
}


def stage_names() -> list[str]:
    return [s["name"] for s in config.pipeline()["stages"]]


def _sink() -> snapshot.Sink | None:
    import os

    bucket = os.environ.get("SNAPSHOT_BUCKET")
    return snapshot.GcsSink(bucket) if bucket else None


def run_stages(ctx: Ctx, only: str | None = None, start: str | None = None) -> dict[str, int]:
    names = stage_names()
    if only:
        names = [only]
    elif start:
        names = names[names.index(start) :]
    run_id = uuid.uuid4().hex[:12]
    done: dict[str, int] = {}
    for name in names:
        began = datetime.now(UTC).isoformat()
        ctx.db.execute(
            "CREATE (:BatchRun {run_id: ?, stage: ?, started_at: ?, status: 'running'})",
            (run_id, name, began),
        )
        try:
            rows = STAGES[name](ctx)
        except Exception as exc:
            ctx.db.execute(
                "MATCH (n:BatchRun {run_id: ?, stage: ?}) "
                "SET n.ended_at=?, n.status='failed', n.error=?",
                (run_id, name, datetime.now(UTC).isoformat(), repr(exc)[:500]),
            )
            raise
        ctx.db.execute(
            "MATCH (n:BatchRun {run_id: ?, stage: ?}) SET n.ended_at=?, n.rows_out=?, n.status='ok'",
            (run_id, name, datetime.now(UTC).isoformat(), rows),
        )
        print(f'{{"event":"stage_done","stage":"{name}","rows":{rows}}}')
        done[name] = rows
    return done


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=list(STAGES))  # includes autoclean, which has its own job
    ap.add_argument("--from", dest="start", choices=stage_names())
    args = ap.parse_args(argv)
    ctx = production_ctx()
    run_stages(ctx, args.stage, args.start)
    return 0


def production_ctx() -> Ctx:
    import os

    from pipeline.gcp import BqWarehouse, GcsBlobs, GcsText, bq_sink, pubsub_publish, versions_of
    from weft_core import config, store
    from weft_core.ledger import GraphLedger, limits
    from weft_core.models import ModelClient
    from weft_core.nlp import default_nlp

    db = store.from_env()
    graph.init(db)
    project = os.environ["PROJECT_ID"]
    ledger = GraphLedger(db)
    tokens, cost = limits(config.pipeline(), "pipeline")
    model = ModelClient(
        base_url=os.environ["MODEL_BASE_URL"],
        api_key=os.environ["MODEL_API_KEY"],
        model=os.environ["MODEL_NAME"],
        revision=os.environ["MODEL_REVISION"],
        log=bq_sink(project),
        ledger=ledger,
        caller="pipeline",
        daily_tokens=tokens,
        daily_cost_usd=cost,
    )
    raw = os.environ["RAW_BUCKET"]
    return Ctx(
        db,
        config.pipeline(),
        default_nlp(),
        GcsText(raw).text,
        model,
        versions_of=versions_of(raw, db),
        ledger=ledger,
        warehouse=BqWarehouse(project),
        publish=pubsub_publish(project),
        snapshots=GcsBlobs(os.environ["SNAPSHOT_BUCKET"])
        if os.environ.get("SNAPSHOT_BUCKET")
        else None,
        raw_blobs=GcsBlobs(raw),
    )


if __name__ == "__main__":
    sys.exit(main())
