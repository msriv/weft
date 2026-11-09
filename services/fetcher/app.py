"""Cloud Run service: Pub/Sub push endpoint for `items-new`.

Run with max instances 1 and concurrency 1 so there is one connection at a time.
"""

import base64
import json
import os
from collections.abc import Callable
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from google.cloud import bigquery, pubsub_v1, storage  # type: ignore[attr-defined]

from services.fetcher import refetch as refetch_mod
from services.fetcher.fetcher import Store, fetch_item
from services.fetcher.tasks import CloudTasksQueue
from weft_core import portals, store
from weft_core.gcp import bigquery_client
from weft_core import store as store_mod
from weft_core.polite import PoliteClient


class GcpStore:
    def __init__(self, project: str, raw_bucket: str, dataset: str = "weft") -> None:
        self._bq = bigquery_client(project)
        self._bucket = storage.Client(project=project).bucket(raw_bucket)
        self._ds = f"{project}.{dataset}"

    def seen(self, canonical_url: str | None, text_hash: str) -> bool:
        job = self._bq.query(
            f"SELECT 1 FROM `{self._ds}.raw_items` WHERE canonical_url = @u OR text_hash = @h LIMIT 1",
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("u", "STRING", canonical_url),
                    bigquery.ScalarQueryParameter("h", "STRING", text_hash),
                ]
            ),
        )
        return bool(job.result().total_rows)

    def save_version(self, item_id: str, n: int, content: bytes, ext: str) -> None:
        self._bucket.blob(f"{item_id}.v{n}.{ext}").upload_from_string(content)

    def save(
        self, raw_row: dict[str, Any], extracted_row: dict[str, Any], content: bytes, ext: str
    ) -> None:
        blob = self._bucket.blob(f"{raw_row['item_id']}.{ext}")
        blob.upload_from_string(content)
        raw_row["raw_gcs_uri"] = f"gs://{self._bucket.name}/{blob.name}"
        for table, row in (("raw_items", raw_row), ("extracted_items", extracted_row)):
            if errs := self._bq.insert_rows_json(f"{self._ds}.{table}", [row]):
                raise RuntimeError(f"insert into {table} failed: {errs}")


def create_app(
    store: Store,
    http: PoliteClient,
    sources: dict[str, dict[str, Any]],
    publish: Callable[[dict[str, Any]], None] | None = None,
    db: "store_mod.Db | None" = None,
    files: refetch_mod.VersionStore | None = None,
    queue_for: Callable[[str], refetch_mod.Enqueue] | None = None,
) -> FastAPI:
    app = FastAPI()

    @app.post("/")
    async def push(request: Request) -> Response:
        envelope = await request.json()
        try:
            msg = json.loads(base64.b64decode(envelope["message"]["data"]))
            source = sources[msg["source_id"]]
        except (KeyError, ValueError):
            return Response(status_code=204)  # malformed or unknown source: drop, don't retry
        try:
            result = fetch_item(msg, source, http, store)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        # structured line; log-based metrics for the dashboards count these (infra/modules/monitoring)
        print(
            json.dumps(
                {"event": "item_processed", "source_id": msg["source_id"], "status": result.status}
            )
        )
        if result.message and db is not None and result.message["gov_domains"]:
            portals.record_candidates(db, set(result.message["gov_domains"]), msg["url"])
        if result.message and publish:
            publish(result.message)  # stream worker picks it up
        if result.message and queue_for:
            refetch_mod.schedule(result.message, queue_for(str(request.base_url)))
        if result.status == "skipped":
            raise HTTPException(status_code=503, detail="deferred")  # Pub/Sub retries with backoff
        return Response(status_code=204)

    @app.post("/refetch")
    async def refetch(request: Request) -> Response:
        task = await request.json()
        try:
            source = sources[task["source_id"]]
            task["item_id"], task["url"], task["n"]
        except KeyError:
            return Response(status_code=204)
        if db is None or files is None:
            return Response(status_code=204)
        try:
            outcome = refetch_mod.refetch(task, source, http, db, files)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        print(json.dumps({"event": "refetch", "source_id": task["source_id"], "outcome": outcome}))
        if outcome == "skipped":
            raise HTTPException(status_code=503, detail="deferred")  # Cloud Tasks retries
        return Response(status_code=204)

    return app


def _default_app() -> FastAPI:
    project = os.environ["PROJECT_ID"]
    db = store.from_env()
    sources = store.LiveSources(db)
    http = PoliteClient(httpx.Client(timeout=30, follow_redirects=True))
    publisher = pubsub_v1.PublisherClient()
    topic = publisher.topic_path(project, "items-extracted")

    def publish(m: dict[str, Any]) -> None:
        publisher.publish(topic, json.dumps(m).encode()).result()

    gcp = GcpStore(project, os.environ["RAW_BUCKET"])

    def queue_for(base_url: str) -> refetch_mod.Enqueue:
        return CloudTasksQueue(
            project,
            os.environ["REGION"],
            os.environ["REFETCH_QUEUE"],
            os.environ["TASKS_SERVICE_ACCOUNT"],
            base_url,
        )

    return create_app(gcp, http, sources, publish, db, gcp, queue_for)


def __getattr__(name: str) -> FastAPI:  # `uvicorn services.fetcher.app:app` builds it lazily
    if name == "app":
        return _default_app()
    raise AttributeError(name)
