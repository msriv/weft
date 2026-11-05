"""Cloud Run job entrypoint: poll all sources once, publish to Pub/Sub, keep ETags in GCS."""

import json
import os
import sys
from datetime import UTC, datetime

import httpx
from google.cloud import bigquery, pubsub_v1, storage  # type: ignore[attr-defined]

from services.poller.poller import FeedState, Poller
from weft_core.health import unhealthy
from weft_core.polite import PoliteClient
from weft_core.sources import load_sources


class GcsState:
    def __init__(self, bucket: str, prefix: str = "poller-state/") -> None:
        self._bucket = storage.Client().bucket(bucket)
        self._prefix = prefix

    def _blob(self, url: str):  # type: ignore[no-untyped-def]
        import hashlib

        return self._bucket.blob(self._prefix + hashlib.sha256(url.encode()).hexdigest())

    def get(self, url: str) -> FeedState:
        blob = self._blob(url)
        return FeedState(**json.loads(blob.download_as_text())) if blob.exists() else FeedState()

    def put(self, url: str, state: FeedState) -> None:
        self._blob(url).upload_from_string(json.dumps(state.__dict__))


def record_and_report(project: str, results: dict[str, str | None]) -> None:
    """Append this run to `source_health`, then log one ERROR per unhealthy source."""
    bq = bigquery.Client(project=project)
    table = f"{project}.weft.source_health"
    now = datetime.now(UTC)
    rows = [
        {"source_id": sid, "checked_at": now.isoformat(), "ok": err is None, "error": err}
        for sid, err in results.items()
    ]
    if errs := bq.insert_rows_json(table, rows):
        raise RuntimeError(f"insert into source_health failed: {errs}")
    q = f"SELECT source_id, MAX(IF(ok, checked_at, NULL)) AS last_ok FROM `{table}` GROUP BY 1"
    last_ok = {r.source_id: r.last_ok for r in bq.query(q).result()}
    for sid in unhealthy(last_ok, now):
        # structured line; the Terraform log-based metric alerts on event=source_unhealthy
        print(json.dumps({"severity": "ERROR", "event": "source_unhealthy", "source_id": sid}))


def main() -> int:
    project = os.environ["PROJECT_ID"]
    publisher = pubsub_v1.PublisherClient()
    topic = publisher.topic_path(project, "items-new")

    def publish(msg: dict[str, object]) -> None:
        publisher.publish(topic, json.dumps(msg).encode()).result()

    with httpx.Client(timeout=30, follow_redirects=True) as http:
        results = Poller(PoliteClient(http), GcsState(os.environ["STATE_BUCKET"]), publish).run(
            load_sources()
        )
    for sid, err in results.items():
        if err:
            print(f"poll failed: {sid}: {err}", file=sys.stderr)
    record_and_report(project, results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
