"""Cloud Run service: Pub/Sub push endpoint for `items-new`.

Run with max instances 1 and concurrency 1 so there is one connection at a time.
"""

import base64
import json
import os
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from google.cloud import pubsub_v1, storage  # type: ignore[attr-defined]

from services.fetcher import refetch as refetch_mod
from services.fetcher.fetcher import Store, fetch_item, seen_keys
from services.fetcher.tasks import CloudTasksQueue
from weft_core import config, store
from weft_core import store as store_mod
from weft_core.gcp import bigquery_client
from weft_core.polite import PoliteClient


class GcpStore:
    """Raw copies in GCS, the append-only log in BigQuery. "Seen" lives in the graph store, so
    no BigQuery query job runs per message (#161); BigQuery is only written to."""

    def __init__(
        self, project: str, raw_bucket: str, db: "store_mod.Db", dataset: str = "weft"
    ) -> None:
        self._bq = bigquery_client(project)
        self._bucket = storage.Client(project=project).bucket(raw_bucket)
        self._ds = f"{project}.{dataset}"
        self._db = db

    def seen(self, canonical_url: str | None, text_hash: str) -> bool:
        keys = seen_keys(canonical_url, text_hash)
        return bool(keys) and bool(
            self._db.execute("MATCH (n:Seen) WHERE n.key IN ? RETURN n.key AS k LIMIT 1", (keys,))
        )

    def boilerplate(self, text_hash: str, url: str, limit: int) -> bool:
        """True once one text has been served under `limit` distinct URLs of the same source."""
        key = f"{text_hash}|{url}"
        self._db.execute(
            "MERGE (n:HashUrl {key: ?}) ON CREATE SET n.hash = ?, n.at = ?",
            (key, text_hash, datetime.now(UTC).isoformat()),
        )
        (r,) = self._db.execute("MATCH (n:HashUrl {hash: ?}) RETURN count(n) AS c", (text_hash,))
        return bool(r["c"] >= limit)

    def note_outcome(self, source_id: str, stub: bool, cfg: dict[str, Any]) -> None:
        """Count the day's items and stubs per source; flag a source whose last 7 days are mostly
        stubs as paywalled (an admin-set flag is never touched)."""
        today = datetime.now(UTC).date()
        self._db.execute(
            "MERGE (n:SourceDay {key: ?}) ON CREATE SET n.source_id = ?, n.day = ?, n.items = 0, "
            "n.stubs = 0 SET n.items = n.items + 1, n.stubs = n.stubs + ?",
            (f"{source_id}|{today}", source_id, str(today), int(stub)),
        )
        (r,) = self._db.execute(
            "MATCH (n:SourceDay {source_id: ?}) WHERE n.day >= ? "
            "RETURN sum(n.items) AS i, sum(n.stubs) AS s",
            (source_id, str(today - timedelta(days=7))),
        )
        if r["i"] >= cfg["paywall_min_items"] and r["s"] / r["i"] >= cfg["paywall_share"]:
            self._db.execute(
                "MATCH (n:Source {id: ?}) WHERE n.paywalled_source IS NULL OR n.paywalled_source = 'auto' "
                "SET n.paywalled = 1, n.paywalled_source = 'auto'",
                (source_id,),
            )

    def _mark_seen(self, raw_row: dict[str, Any]) -> None:
        keys = seen_keys(raw_row["url"], raw_row.get("text_hash") or "")
        keys += seen_keys(raw_row["canonical_url"], "")
        self._db.execute(
            "UNWIND ? AS k MERGE (n:Seen {key: k}) ON CREATE SET n.at = ?",
            (sorted(set(keys)), raw_row["fetched_at"]),
        )

    def save_version(self, item_id: str, n: int, content: bytes, ext: str) -> None:
        self._bucket.blob(f"{item_id}.v{n}.{ext}").upload_from_string(content)

    def save(
        self, raw_row: dict[str, Any], extracted_row: dict[str, Any], content: bytes, ext: str
    ) -> None:
        blob = self._bucket.blob(f"{raw_row['item_id']}.{ext}")
        blob.upload_from_string(content)
        raw_row["raw_gcs_uri"] = f"gs://{self._bucket.name}/{blob.name}"
        self._mark_seen(raw_row)  # first: this, not the log, decides whether a URL is fetched again
        for table, row in (("raw_items", raw_row), ("extracted_items", extracted_row)):
            self._log(table, row)

    def _log(self, table: str, row: dict[str, Any]) -> None:
        """Append to the BigQuery log. A failed insert is retried, then reported; it never fails
        the fetch (the raw copy and the seen mark are already written)."""
        errs: Any = None
        for attempt in range(3):
            try:
                errs = self._bq.insert_rows_json(f"{self._ds}.{table}", [row])
            except Exception as exc:  # noqa: BLE001 - any client error is retried, then logged
                errs = repr(exc)
            if not errs:
                return
            time.sleep(2**attempt)
        print(
            json.dumps(
                {
                    "event": "log_insert_failed",
                    "table": table,
                    "item_id": row.get("item_id"),
                    "errors": str(errs)[:500],
                }
            )
        )


def _all(sources: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return sources.all() if hasattr(sources, "all") else list(sources.values())


def create_app(
    store: Store,
    http: PoliteClient,
    sources: dict[str, dict[str, Any]],
    publish: Callable[[dict[str, Any]], None] | None = None,
    db: "store_mod.Db | None" = None,
    files: refetch_mod.VersionStore | None = None,
    queue_for: Callable[[str], refetch_mod.Enqueue] | None = None,
    qcfg: dict[str, Any] | None = None,
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
            result = fetch_item(msg, source, http, store, _all(sources), qcfg)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        # structured line; log-based metrics for the dashboards count these (infra/modules/monitoring)
        print(
            json.dumps(
                {"event": "item_processed", "source_id": msg["source_id"], "status": result.status}
            )
        )
        if result.status == "foreign" and db is not None and result.message:
            from weft_core import domains, portals

            canonical = result.message["canonical"]
            portals.record_candidates(db, {domains.host_of(canonical)}, canonical)
            result.message = None
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

    gcp = GcpStore(project, os.environ["RAW_BUCKET"], db)

    def queue_for(base_url: str) -> refetch_mod.Enqueue:
        return CloudTasksQueue(
            project,
            os.environ["REGION"],
            os.environ["REFETCH_QUEUE"],
            os.environ["TASKS_SERVICE_ACCOUNT"],
            base_url,
        )

    return create_app(gcp, http, sources, publish, db, gcp, queue_for, config.pipeline()["quality"])


def __getattr__(name: str) -> FastAPI:  # `uvicorn services.fetcher.app:app` builds it lazily
    if name == "app":
        return _default_app()
    raise AttributeError(name)
