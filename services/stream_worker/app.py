"""Cloud Run service: Pub/Sub push endpoint for `items-extracted`."""

import base64
import json
import os
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from google.cloud import pubsub_v1  # type: ignore[attr-defined]

from services.stream_worker.worker import Deps, process, process_document
from weft_core import config, graph, store
from weft_core.nlp import default_nlp
from weft_core.probes import add_probes


def _retry_if_unknown(status: str) -> None:
    """The source may have been registered seconds ago: nack so Pub/Sub retries with backoff,
    and dead-letters the message after max_delivery_attempts instead of dropping it (#150)."""
    if status == "unknown_source":
        raise HTTPException(status_code=503, detail="unknown source")


def create_app(deps: Deps) -> FastAPI:
    app = FastAPI()
    add_probes(app, deps.db)

    @app.post("/")
    async def push(request: Request) -> Response:
        envelope = await request.json()
        try:
            msg = json.loads(base64.b64decode(envelope["message"]["data"]))
            msg["item_id"], msg["source_id"], msg["url"]
        except (KeyError, ValueError):
            return Response(status_code=204)  # malformed: drop, don't retry
        status = process(msg, deps)
        print(json.dumps({"event": "stream_item", "source_id": msg["source_id"], "status": status}))
        _retry_if_unknown(status)
        return Response(status_code=204)

    @app.post("/documents")
    async def push_document(request: Request) -> Response:
        envelope = await request.json()
        try:
            msg = json.loads(base64.b64decode(envelope["message"]["data"]))
            msg["item_id"], msg["source_id"], msg["url"]
        except (KeyError, ValueError):
            return Response(status_code=204)
        status = process_document(msg, deps)
        print(
            json.dumps(
                {"event": "stream_document", "source_id": msg["source_id"], "status": status}
            )
        )
        _retry_if_unknown(status)
        return Response(status_code=204)

    return app


def _default_app() -> FastAPI:
    db = store.from_env()
    graph.init(db)
    publisher = pubsub_v1.PublisherClient()
    topic = publisher.topic_path(os.environ["PROJECT_ID"], "graph-changed")

    def publish(m: dict[str, Any]) -> None:
        publisher.publish(topic, json.dumps(m).encode()).result()

    return create_app(Deps(db, default_nlp(), config.pipeline(), publish))


def __getattr__(name: str) -> FastAPI:
    if name == "app":
        return _default_app()
    raise AttributeError(name)
