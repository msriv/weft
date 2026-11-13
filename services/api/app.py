"""Weft API. Public read API under /v1 (public stories only); admin routes behind one token.

The admin toggle is the only human gate (D15): a story is invisible here until its `public` flag
is set. `GET /stories` and the /admin/stories routes predate /v1 and are kept.
"""

import asyncio
import hmac
import json
import os
import re
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from weft_core import (
    accounts,
    detective,
    digest,
    feedback,
    graph,
    questions,
    readmodel,
    relevance,
    review,
    store,
)

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
    paywalled: bool | None = None
    status: Literal["active", "rejected"] | None = None
    state_run: bool | None = None
    state_run_source: str | None = None
    owner_id: str | None = None
    ownership_source: str | None = None


class NewSource(BaseModel):
    url: str
    beat_id: str | None = None


class BeatTerms(BaseModel):
    patterns: list[str]
    exclude: list[str] = []
    groups: dict[str, str] | None = None  # source id -> outlet group (D21); None leaves as is


class BeatLabel(BaseModel):
    beat_id: str
    on_beat: bool


class Feedback(BaseModel):
    label: str


class Subscription(BaseModel):
    email: str
    frequency: str
    follows: list[str] = []


class ReaderPrefs(BaseModel):
    regions: list[str] = []
    topics: list[str] = []
    follows: list[str] = []
    frequency: str = "daily"
    email: str | None = None


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
    prefs: accounts.Prefs | None = None,
    project: str = "",
) -> FastAPI:
    app = FastAPI(title="Weft API")

    def admin(authorization: Annotated[str, Header()] = "") -> None:
        # shortcut: one shared admin token for editors, replace with Firebase custom claims
        if not admin_token or not hmac.compare_digest(authorization, f"Bearer {admin_token}"):
            raise HTTPException(401, "admin token required")

    def reader(authorization: Annotated[str, Header()] = "") -> str:
        uid = accounts.verify_token(authorization.removeprefix("Bearer "), project)
        if prefs is None or uid is None:
            raise HTTPException(401, "sign in required")
        return uid

    v1 = APIRouter(prefix="/v1")

    @v1.get("/me/prefs")
    def my_prefs(uid: Annotated[str, Depends(reader)]) -> dict[str, Any]:
        assert prefs is not None
        return prefs.get(uid)

    @v1.put("/me/prefs")
    def put_my_prefs(body: ReaderPrefs, uid: Annotated[str, Depends(reader)]) -> dict[str, Any]:
        assert prefs is not None
        prefs.put(uid, body.model_dump())
        return body.model_dump()

    @v1.get("/stories")
    def stories(
        region: str | None = None, topic: str | None = None, sort: str = "recent"
    ) -> list[dict[str, Any]]:
        return readmodel.list_stories(db, region, topic, sort)

    @v1.get("/stories/{story_id}")
    def story(
        story_id: str,
        at: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}.*$")] = None,
        until: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None,
        days: Annotated[int, Query(ge=0, le=366)] = readmodel.WINDOW_DAYS,
    ) -> Any:
        # `at=YYYY-MM-DD` replays the story as it was at the end of that day; `until` and `days`
        # pick the window of reports shown (days=0: the whole story)
        when = f"{at[:10]}T23:59:59+00:00" if at else None
        end = f"{until}T23:59:59+00:00" if until else None
        return found(readmodel.story_graph(db, story_id, when, days, end))

    @v1.get("/stories/{story_id}/questions")
    def story_questions(story_id: str) -> list[dict[str, Any]]:
        """Open questions (#111): fixed rules over the graph, no model, always on."""
        found(readmodel.public_story(db, story_id))
        return questions.open_questions(db, story_id)

    @v1.get("/stories/{story_id}/detective")
    def story_detective(story_id: str) -> dict[str, Any]:
        # D20: experimental speculation, served only when switched on and only for shown stories
        if not detective.enabled():
            raise HTTPException(404, "not found")
        found(readmodel.public_story(db, story_id))
        return detective.scorecard(db, story_id)

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
    def today(
        follow: Annotated[list[str] | None, Query()] = None, since: str | None = None
    ) -> dict[str, Any]:
        return readmodel.today(db, follow, since)

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

    @adm.get("/sources")
    def admin_sources() -> list[dict[str, Any]]:
        """Every source, rejected ones too, with when Weft last stored a report from it."""
        last = {
            r["id"]: r["last"]
            for r in db.execute(
                "MATCH (r:Report) RETURN r.source_id AS id, max(r.fetched_at) AS last"
            )
        }
        keys = (
            "id",
            "name",
            "domain",
            "country",
            "country_source",
            "paywalled",
            "status",
            "rejected_reason",
        )
        return [
            {**{k: s.get(k) for k in keys}, "last_report_at": last.get(s["id"])}
            for s in sorted(store.all_sources(db), key=lambda s: (s["status"] != "active", s["id"]))
        ]

    @adm.post("/sources", status_code=202)
    def add_source(body: NewSource) -> dict[str, Any]:
        """Queue an outlet for the next discovery run, which checks robots.txt, finds its live
        feeds and registers it. Nothing is fetched here."""
        domain = urlsplit(body.url if "//" in body.url else f"https://{body.url}").netloc.lower()
        if not re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)+", domain):
            raise HTTPException(422, "not a site address")
        store.request_source(db, domain, body.beat_id)
        return {"domain": domain, "queued": True}

    @adm.get("/beats")
    def admin_beats() -> list[dict[str, Any]]:
        return store.beats(db)

    @adm.put("/beats/{beat_id}")
    def edit_beat(beat_id: str, body: BeatTerms) -> dict[str, Any]:
        """Replace a beat's match terms. Applies to reports that arrive from now on. Marks the
        beat edited, so seed updates never overwrite it."""
        beat = next((b for b in store.beats(db) if b["id"] == beat_id), None)
        if beat is None:
            raise HTTPException(404, "no such beat")
        pats = [p.strip() for p in body.patterns if p.strip()]
        excl = [p.strip() for p in body.exclude if p.strip()]
        if not pats:
            raise HTTPException(422, "a beat needs at least one pattern")
        for p in pats + excl:
            try:
                re.compile(p)
            except re.error as exc:
                raise HTTPException(422, f"bad pattern {p!r}: {exc}") from exc
        groups = beat["groups"]
        if body.groups is not None:
            known = {s["id"] for s in store.all_sources(db)}
            groups = {
                k.strip(): v.strip() for k, v in body.groups.items() if k.strip() and v.strip()
            }
            if bad := sorted(set(groups) - known):
                raise HTTPException(422, f"unknown source ids: {', '.join(bad)}")
        store.add_beat(db, beat_id, beat["name"], pats, parties=beat["parties"], exclude=excl)
        db.execute("MATCH (n:Beat {id: ?}) SET n.edited=1", (beat_id,))
        if body.groups is not None:
            store.set_beat_groups(db, beat_id, groups)
        return {"id": beat_id, "patterns": pats, "exclude": excl, "groups": groups}

    @adm.get("/unplaced")
    def unplaced(limit: int = 50) -> list[dict[str, Any]]:
        """Newest reports that matched no beat, so the admin can see what the terms miss."""
        return db.execute(
            "MATCH (r:Report) WHERE r.story_id IS NULL "
            "RETURN r.id AS id, r.title AS title, r.url AS url, r.source_id AS source_id, "
            "r.fetched_at AS fetched_at ORDER BY r.fetched_at DESC LIMIT ?",
            (min(limit, 500),),
        )

    @adm.post("/anomalies/{anomaly_id}/feedback")
    def anomaly_feedback(anomaly_id: str, body: Feedback) -> dict[str, Any]:
        """Owner label for the anomaly eval set (#114). Tunes rules, never decides this one."""
        try:
            return feedback.label(db, anomaly_id, body.label)
        except KeyError as exc:
            raise HTTPException(404, "no such anomaly") from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @adm.get("/beat-maybes")
    def beat_maybes(limit: int = 50) -> list[dict[str, Any]]:
        """Reports whose beat relevance fell in the "maybe" band (#107), for owner labels."""
        return relevance.maybes(db, min(limit, 500))

    @adm.post("/beat-maybes/{report_id}")
    def beat_maybe_label(report_id: str, body: BeatLabel) -> dict[str, Any]:
        relevance.label_maybe(
            db, report_id, body.beat_id, body.on_beat, datetime.now(UTC).isoformat()
        )
        return {"ok": True}

    @adm.get("/anomaly-precision")
    def anomaly_precision() -> list[dict[str, Any]]:
        return feedback.precision(db)

    @adm.get("/runs")
    def runs(limit: int = 200) -> list[dict[str, Any]]:
        """Recent nightly pipeline stages, newest first. A stage still 'running' is live."""
        return store.nodes(
            db,
            "BatchRun",
            "MATCH (n:BatchRun) RETURN n ORDER BY n.started_at DESC LIMIT ?",
            (min(limit, 1000),),
        )

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
        if not store.all_sources(db, "n.id=?", (source_id,)):
            raise HTTPException(404, "no such source")
        if "country" in data:  # also re-tags the source's reports
            store.set_country(db, source_id, data.pop("country"), "admin")
        for col, val in data.items():  # col is a SourcePatch field name, never user text
            db.execute(
                f"MATCH (n:Source {{id: ?}}) SET n.{col}=?",
                (source_id, int(val) if isinstance(val, bool) else val),
            )
        return {"id": source_id, **body.model_dump(exclude_unset=True)}

    @adm.put("/stories/{story_id}/parties/{party}")
    def confirm_party(story_id: str, party: str, citation: str) -> dict[str, str]:
        db.execute(
            "MERGE (n:StoryParty {story_id: ?, party: ?}) SET n.citation=?",
            (story_id, party, citation),
        )
        return {"story_id": story_id, "party": party}

    @adm.delete("/stories/{story_id}/parties/{party}")
    def remove_party(story_id: str, party: str) -> dict[str, str]:
        db.execute("MATCH (n:StoryParty {story_id: ?, party: ?}) DELETE n", (story_id, party))
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
        return store.nodes(
            db,
            "ReaderReport",
            "MATCH (n:ReaderReport {status: ?}) RETURN n ORDER BY n.created_at",
            (status,),
        )

    @adm.post("/reader-reports/{report_id}/resolve")
    def resolve(report_id: int, body: Resolve) -> dict[str, Any]:
        db.execute(
            "MATCH (n:ReaderReport {id: ?}) SET n.status='resolved', n.resolution=?",
            (report_id, body.resolution),
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
    project = os.environ["PROJECT_ID"]
    return create_app(
        db, os.environ["ADMIN_TOKEN"], _asker(db), accounts.FirestorePrefs(project), project
    )


def _asker(db: store.Db) -> Callable[[str], dict[str, Any]] | None:
    if "MODEL_BASE_URL" not in os.environ:
        return None
    from pipeline.gcp import bq_sink
    from weft_core import ask
    from weft_core.models import ModelClient
    from weft_core.nlp import default_embedder

    model = ModelClient(
        base_url=os.environ["MODEL_BASE_URL"],
        api_key=os.environ["MODEL_API_KEY"],
        model=os.environ["MODEL_NAME"],
        revision=os.environ["MODEL_REVISION"],
        log=bq_sink(os.environ["PROJECT_ID"]),
    )
    embedder = default_embedder()
    return lambda q: ask.answer(db, embedder, model, q)
