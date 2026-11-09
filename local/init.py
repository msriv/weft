"""One-shot setup of the local GCP stand-ins: buckets, BigQuery tables, Pub/Sub topics and push
subscriptions. Idempotent. Mirrors infra/modules/{storage,bigquery,messaging} and the push
subscriptions in infra/modules/{fetcher,run_service}."""

import json
import os
from pathlib import Path

from google.api_core.exceptions import AlreadyExists, Conflict
from google.cloud import bigquery, pubsub_v1, storage  # type: ignore[attr-defined]

from weft_core.gcp import bigquery_client

PROJECT = os.environ["PROJECT_ID"]

for name in (os.environ["RAW_BUCKET"], os.environ["STATE_BUCKET"], os.environ["SNAPSHOT_BUCKET"]):
    try:
        storage.Client(project=PROJECT).create_bucket(name)
    except Conflict:
        pass

bq = bigquery_client(PROJECT)
bq.create_dataset("weft", exists_ok=True)
for f in sorted(Path("infra/modules/bigquery/schemas").glob("*.json")):
    schema = [bigquery.SchemaField.from_api_repr(c) for c in json.loads(f.read_text())]
    bq.create_table(bigquery.Table(f"{PROJECT}.weft.{f.stem}", schema=schema), exists_ok=True)

pub, sub = pubsub_v1.PublisherClient(), pubsub_v1.SubscriberClient()
topics = {
    t: pub.topic_path(PROJECT, t)
    for t in ("items-new", "items-extracted", "documents-new", "graph-changed")
}
for path in topics.values():
    try:
        pub.create_topic(name=path)
    except AlreadyExists:
        pass
for name, topic, url in (
    ("fetcher", "items-new", "http://fetcher:8080/"),
    ("stream-worker", "items-extracted", "http://stream-worker:8080/"),
    ("stream-worker-documents", "documents-new", "http://stream-worker:8080/documents"),
):
    try:
        sub.create_subscription(
            name=sub.subscription_path(PROJECT, name),
            topic=topics[topic],
            push_config=pubsub_v1.types.PushConfig(push_endpoint=url),
            ack_deadline_seconds=120,
        )
    except AlreadyExists:
        pass
print("local stand-ins ready")
