"""Cloud Run job entrypoint: poll all sources once, publish to Pub/Sub, keep ETags in GCS."""

import json
import os
import sys

import httpx
from google.cloud import pubsub_v1, storage

from services.poller.poller import FeedState, Poller
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


def main() -> int:
    publisher = pubsub_v1.PublisherClient()
    topic = publisher.topic_path(os.environ["PROJECT_ID"], "items-new")

    def publish(msg: dict[str, object]) -> None:
        publisher.publish(topic, json.dumps(msg).encode()).result()

    with httpx.Client(timeout=30, follow_redirects=True) as http:
        failures = Poller(http, GcsState(os.environ["STATE_BUCKET"]), publish).run(load_sources())
    for sid, err in failures.items():
        print(f"poll failed: {sid}: {err}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
