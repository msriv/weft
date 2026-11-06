"""Weft API. Public read API under /v1 (public stories only); admin routes behind one token.

The admin toggle is the only human gate (D15): a story is invisible here until its `public` flag
is set. `GET /stories` and the /admin/stories routes predate /v1 and are kept.
"""

import asyncio
import hmac
import json
import os
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from weft_core import digest, graph, readmodel, review, store

STREAM_POLL_SECONDS = 5


class Visibility(BaseModel):
    public: bool


class Problem(BaseModel):
    kind: str
    ref_id: str | None = None
    message: str
    email: str | None = None


class SourcePatch(BaseModel):
    country: str | None = None
    state_run: bool | None = None
    state_run_source: str | None = None
    owner_id: str | None = None
    ownership_source: str | None = None


class Subscription(BaseModel):
    email: str
    frequency: str
    follows: list[str] = []


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=500)


class Rating(BaseModel):
    rating: str
    reviewer: str


class Correction(BaseModel):
    kind: str
    what: str


class Resolve(BaseModel):
    resolution: str


def found(x: Any) -> Any:
    if x is None:
        raise HTTPException(404, "not found")  # also what a non-public story looks like
    return x


def create_app(
    db: store.Db,
    admin_token: str,
    asker: Callable[[str], dict[str, Any]] | None = None,
) -> FastAPI:
    app = FastAPI(title="Weft API")

    def admin(authorization: Annotated[str, Header()] = "") -> None:
        # shortcut: one shared admin token for editors, replace with Firebase custom claims
        if not admin_token or not hmac.compare_digest(authorization, f"Bearer {admin_token}"):
            raise HTTPException(401, "admin token required")

    v1 = APIRouter(prefix="/v1")

    @v1.get("/stories")
    def stories(
        region: str | None = None, topic: str | None = None, sort: str = "recent"
    ) -> list[dict[str, Any]]:
        return readmodel.list_stories(db, region, topic, sort)

    @v1.get("/stories/{story_id}")
    def story(
        story_id: str, at: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}.*$")] = None
    ) -> Any:
        # `at=YYYY-MM-DD` replays the story as it was at the end of that day
        when = f"{at[:10]}T23:59:59+00:00" if at else None
        return found(readmodel.story_graph(db, story_id, when))

    @v1.get("/events/{event_id}")
    def event(event_id: str) -> Any:
        return found(readmodel.event_page(db, event_id))

    @v1.get("/nodes/{node_id}")
    def node(node_id: str) -> Any:
        return found(readmodel.node(db, node_id))

    @v1.get("/sources")
    def sources() -> list[dict[str, Any]]:
        return readmodel.list_sources(db)

    @v1.get("/sources/{source_id}")
    def source(source_id: str) -> Any:
        return found(readmodel.source_profile(db, source_id))

    @v1.get("/documents/{doc_id}")
    def document(doc_id: str) -> Any:
        return found(readmodel.document_page(db, doc_id))

    @v1.get("/actors/{actor_id}")
    def actor(actor_id: str) -> Any:
        return found(readmodel.actor_page(db, actor_id))

    @v1.get("/world")
    def world() -> dict[str, Any]:
        return readmodel.world(db)

    @v1.get("/method")
    def method() -> dict[str, Any]:
        return readmodel.method(db)

    @v1.get("/today")
    def today(follow: Annotated[list[str] | None, Query()] = None) -> dict[str, Any]:
        return readmodel.today(db, follow)

    @v1.post("/reports-problem", status_code=201)
    def report_problem(body: Problem) -> dict[str, Any]:
        try:
            return {
                "id": readmodel.add_problem(db, body.kind, body.ref_id, body.message, body.email)
            }
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @v1.get("/stories/{story_id}/stream")
    async def stream(story_id: str, request: Request) -> StreamingResponse:
        found(readmodel.public_story(db, story_id))

        async def events() -> AsyncIterator[str]:
            cursor = datetime.now(UTC).isoformat()
            while not await request.is_disconnected():
                for m in await asyncio.to_thread(readmodel.changes, db, story_id, cursor):
                    cursor = max(cursor, m["at"])
                    yield f"event: {m['type']}\ndata: {json.dumps(m['data'])}\n\n"
                yield ": keepalive\n\n"
                await asyncio.sleep(STREAM_POLL_SECONDS)

        return StreamingResponse(events(), media_type="text/event-stream")

    @v1.put("/subscription")
    def subscribe(body: Subscription) -> dict[str, bool]:
        try:
            digest.subscribe(db, body.email, body.frequency, body.follows)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"subscribed": True}

    @v1.get("/unsubscribe")
    def unsubscribe(token: str) -> dict[str, bool]:
        return {"unsubscribed": bool(found(digest.unsubscribe(db, token) or None))}

    @v1.post("/ask")
    def ask(body: Question) -> dict[str, Any]:
        if asker is None:
            raise HTTPException(503, "ask is not configured")
        return asker(body.question)

    app.include_router(v1)

    # --- older routes, kept for the first admin tooling ---
    @app.get("/stories")
    def public_stories() -> list[dict[str, Any]]:
        return store.stories(db, public_only=True)

    # --- admin ---
    adm = APIRouter(prefix="/admin", dependencies=[Depends(admin)])

    @adm.get("/stories")
    def all_stories() -> list[dict[str, Any]]:
        return store.stories(db, public_only=False)

    @adm.put("/stories/{story_id}/public")
    def set_public(story_id: str, body: Visibility) -> dict[str, Any]:
        if not store.set_public(db, story_id, body.public):
            raise HTTPException(404, "no such story")
        return {"id": story_id, "public": body.public}

    @adm.patch("/sources/{source_id}")
    def patch_source(source_id: str, body: SourcePatch) -> dict[str, Any]:
        """Set country, state_run or ownership. state_run and owner_id need their citation URL
        (product rule: facts are cited or stay 'unverified')."""
        data = body.model_dump(exclude_unset=True)
        if data.get("state_run") is not None and not data.get("state_run_source"):
            raise HTTPException(422, "state_run needs state_run_source")
        if data.get("owner_id") and not data.get("ownership_source"):
            raise HTTPException(422, "owner_id needs ownership_source")
        if not db.execute("SELECT 1 FROM sources WHERE id=?", (source_id,)):
            raise HTTPException(404, "no such source")
        for col, val in data.items():
            db.execute(
                f"UPDATE sources SET {col}=? WHERE id=?",
                (int(val) if isinstance(val, bool) else val, source_id),
            )
        return {"id": source_id, **data}

    @adm.put("/stories/{story_id}/parties/{party}")
    def confirm_party(story_id: str, party: str, citation: str) -> dict[str, str]:
        db.execute(
            "INSERT INTO story_parties(story_id,party,citation) VALUES(?,?,?) "
            "ON CONFLICT(story_id,party) DO UPDATE SET citation=excluded.citation",
            (story_id, party, citation),
        )
        return {"story_id": story_id, "party": party}

    @adm.delete("/stories/{story_id}/parties/{party}")
    def remove_party(story_id: str, party: str) -> dict[str, str]:
        db.execute("DELETE FROM story_parties WHERE story_id=? AND party=?", (story_id, party))
        return {"story_id": story_id, "party": party}

    @adm.get("/review")
    def review_queue() -> dict[str, Any]:
        return {"open": review.open_items(db), "quality": review.quality(db)}

    @adm.post("/review/{item_id:path}")
    def rate(item_id: str, body: Rating) -> dict[str, str]:
        try:
            ok = review.rate(db, item_id, body.rating, body.reviewer)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        found(ok or None)
        return {"id": item_id, "rating": body.rating}

    @adm.get("/reader-reports")
    def reader_reports(status: str = "open") -> list[dict[str, Any]]:
        return db.execute(
            "SELECT rowid AS id, * FROM reader_reports WHERE status=? ORDER BY created_at",
            (status,),
        )

    @adm.post("/reader-reports/{report_id}/resolve")
    def resolve(report_id: int, body: Resolve) -> dict[str, Any]:
        db.execute(
            "UPDATE reader_reports SET status='resolved', resolution=? WHERE rowid=?",
            (body.resolution, report_id),
        )
        return {"id": report_id}

    @adm.post("/corrections", status_code=201)
    def add_correction(body: Correction) -> dict[str, str]:
        readmodel.add_correction(db, body.kind, body.what)
        return {"kind": body.kind}

    app.include_router(adm)
    return app


def app_from_env() -> FastAPI:
    db = store.from_env()
    graph.init(db)
    return create_app(db, os.environ["ADMIN_TOKEN"], _asker(db))


def _asker(db: store.Db) -> Callable[[str], dict[str, Any]] | None:
    if "MODEL_BASE_URL" not in os.environ:
        return None
    from pipeline.gcp import bq_sink
    from weft_core import ask
    from weft_core.models import ModelClient
    from weft_core.nlp import default_nlp

    model = ModelClient(
        base_url=os.environ["MODEL_BASE_URL"],
        api_key=os.environ["MODEL_API_KEY"],
        model=os.environ["MODEL_NAME"],
        revision=os.environ["MODEL_REVISION"],
        log=bq_sink(os.environ["PROJECT_ID"]),
    )
    embedder = default_nlp().embedder
    return lambda q: ask.answer(db, embedder, model, q)
