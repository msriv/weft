"""Cloud Run service: Pub/Sub push endpoint for `items-extracted`."""

import base64
import json
import os
from typing import Any

from fastapi import FastAPI, Request, Response
from google.cloud import pubsub_v1  # type: ignore[attr-defined]

from services.stream_worker.worker import Deps, process
from weft_core import config, graph, store
from weft_core.nlp import default_nlp


def create_app(deps: Deps) -> FastAPI:
    app = FastAPI()

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
