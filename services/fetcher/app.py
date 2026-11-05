"""Cloud Run service: Pub/Sub push endpoint for `items-new`.

Run with max instances 1 and concurrency 1 so there is one connection at a time.
"""

import base64
import json
import os
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from google.cloud import bigquery, storage  # type: ignore[attr-defined]

from services.fetcher.fetcher import Store, fetch_item
from weft_core.polite import PoliteClient
from weft_core.sources import load_sources


class GcpStore:
    def __init__(self, project: str, raw_bucket: str, dataset: str = "weft") -> None:
        self._bq = bigquery.Client(project=project)
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

    def save(
        self, raw_row: dict[str, Any], extracted_row: dict[str, Any], content: bytes, ext: str
    ) -> None:
        blob = self._bucket.blob(f"{raw_row['item_id']}.{ext}")
        blob.upload_from_string(content)
        raw_row["raw_gcs_uri"] = f"gs://{self._bucket.name}/{blob.name}"
        for table, row in (("raw_items", raw_row), ("extracted_items", extracted_row)):
            if errs := self._bq.insert_rows_json(f"{self._ds}.{table}", [row]):
                raise RuntimeError(f"insert into {table} failed: {errs}")


def create_app(store: Store, http: PoliteClient, sources: dict[str, dict[str, Any]]) -> FastAPI:
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
        if result.status == "skipped":
            raise HTTPException(status_code=503, detail="deferred")  # Pub/Sub retries with backoff
        return Response(status_code=204)

    return app


def _default_app() -> FastAPI:
    project = os.environ["PROJECT_ID"]
    sources = {s["id"]: s for s in load_sources()}
    http = PoliteClient(httpx.Client(timeout=30, follow_redirects=True))
    return create_app(GcpStore(project, os.environ["RAW_BUCKET"]), http, sources)


def __getattr__(name: str) -> FastAPI:  # `uvicorn services.fetcher.app:app` builds it lazily
    if name == "app":
        return _default_app()
    raise AttributeError(name)
