"""Weft API. Public read API under /v1 (public stories only); admin routes behind one token.

The admin toggle is the only human gate (D15): a story is invisible here until its `public` flag
is set. `GET /stories` and the /admin/stories routes predate /v1 and are kept.
"""

import asyncio
import hmac
import json
import os
import re
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from services.api.limits import Limiter, Streams, client_key
from services.api.streams import ChangeHub
from weft_core import (
    accounts,
    config,
    detective,
    digest,
    directions,
    feedback,
    graph,
    questions,
    readmodel,
    relevance,
    review,
    store,
)
from weft_core.cache import TtlCache
from weft_core.models import BudgetExceeded, ModelRefused
from weft_core.probes import add_probes

STREAM_POLL_SECONDS = 5
PUBLIC_TTL_SECONDS = 30
REPLAY_TTL_SECONDS = 600


class Visibility(BaseModel):
    public: bool


class Problem(BaseModel):
    kind: str
    ref_id: str | None = None
    message: str
    email: str | None = Field(default=None, max_length=254)


class SourcePatch(BaseModel):
    country: str | None = None
    paywalled: bool | None = None
    status: Literal["active", "rejected", "dormant"] | None = None
    state_run: bool | None = None
    state_run_source: str | None = None
    owner_id: str | None = None
    ownership_source: str | None = None
    link_domains: list[str] | None = None


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
    token: str | None = Field(default=None, max_length=100)  # from any digest mail, to change
    email: str = Field(max_length=254)
    frequency: str = Field(max_length=10)
    follows: list[str] = Field(default=[], max_length=50)


class ReaderPrefs(BaseModel):
    regions: list[str] = []
    topics: list[str] = []
    follows: list[str] = []
    frequency: str = "daily"
    email: str | None = None
    last_visit: str | None = None  # Today shows what is new since this


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
    limits: dict[str, Any] | None = None,
    proxy_secret: str = "",
    limiter: Limiter | None = None,
    admin_emails: frozenset[str] = frozenset(),
    mailer: Callable[[str, str, str], None] | None = None,
    site: str = "",
) -> FastAPI:
    app = FastAPI(title="Weft API")
    add_probes(app, db)

    lim = limits if limits is not None else config.pipeline()["limits"]
    limiter = limiter or Limiter()
    streams = Streams(lim["streams"]["per_client"], lim["streams"]["total"])

    @app.middleware("http")
    async def cap_body(request: Request, call_next: Callable[[Request], Any]) -> Any:
        size = request.headers.get("content-length", "0")
        if size.isdigit() and int(size) > lim["max_body_bytes"]:
            return JSONResponse({"detail": "request too large"}, status_code=413)
        return await call_next(request)

    def who(request: Request) -> str:
        peer = request.client.host if request.client else "unknown"
        return client_key(dict(request.headers), peer, proxy_secret)

    def throttle(name: str) -> Callable[[Request], None]:
        def dep(request: Request) -> None:
            c = lim[name]
            key = who(request)
            if name == "ask" and (
                uid := accounts.verify_token(
                    request.headers.get("authorization", "").removeprefix("Bearer "), project
                )
            ):
                key = f"user:{uid}"  # signed-in readers are limited as themselves, not by address
            if (wait := limiter.check(name, key, c["per_minute"], c["per_day"])) is not None:
                raise HTTPException(
                    429, "Too many requests. Try again later.", headers={"Retry-After": str(wait)}
                )

        return dep

    hub = ChangeHub(lambda sid, since: readmodel.changes(db, sid, since), STREAM_POLL_SECONDS)
    public = TtlCache(PUBLIC_TTL_SECONDS)

    @app.middleware("http")
    async def public_cache(request: Request, call_next: Callable[[Request], Any]) -> Any:
        """Public GET responses are reused for 30 s (a replay `at=` for 10 min: the past does not
        change). Any successful write clears the cache of this instance, so an admin publish or
        unpublish shows at once here; other instances catch up within the TTL."""
        path = request.url.path
        if request.method != "GET":
            resp = await call_next(request)
            if resp.status_code < 400:
                public.clear()
            return resp
        if (
            request.headers.get("authorization")
            or not path.startswith("/v1/")
            or path.startswith(("/v1/me", "/v1/unsubscribe"))
            or path.endswith("/stream")
        ):
            return await call_next(request)
        key = (path, request.url.query)
        if (hit := public.peek(key)) is not None:
            status, body, ctype = hit
            return Response(body, status, {"content-type": ctype, "x-cache": "hit"})
        resp = await call_next(request)
        body = b"".join([c async for c in resp.body_iterator])
        ctype = resp.headers.get("content-type", "application/json")
        if resp.status_code == 200:
            ttl = REPLAY_TTL_SECONDS if "at=" in request.url.query else PUBLIC_TTL_SECONDS
            public.put(key, (resp.status_code, body, ctype), ttl)
        headers = {"content-type": ctype, "cache-control": f"public, max-age={PUBLIC_TTL_SECONDS}"}
        return Response(body, resp.status_code, headers)

    @app.exception_handler(ModelRefused)
    def _model_refused(_: Request, exc: ModelRefused) -> JSONResponse:
        if isinstance(exc, BudgetExceeded):  # the day's ask budget is spent: no model call was made
            now = datetime.now(UTC)
            wait = int(
                (now.replace(hour=0, minute=0, second=0) + timedelta(days=1) - now).total_seconds()
            )
            return JSONResponse(
                {"detail": "Ask has reached its limit for today."},
                status_code=429,
                headers={"Retry-After": str(wait)},
            )
        return JSONResponse({"detail": "The model is not available right now."}, status_code=503)

    def deny(request: Request, status: int, detail: str) -> HTTPException:
        """Failed admin auth counts against the caller's address; past the limit it is a 429."""
        c = lim["admin_auth"]
        if (
            wait := limiter.check("admin_auth", who(request), c["per_minute"], c["per_day"])
        ) is not None:
            return HTTPException(
                429, "Too many requests. Try again later.", headers={"Retry-After": str(wait)}
            )
        return HTTPException(status, detail)

    async def admin(
        request: Request,
        authorization: Annotated[str, Header()] = "",
        x_admin_token: Annotated[str, Header()] = "",
    ) -> AsyncIterator[None]:
        """Admin = a signed-in user on the allowlist (or with an `admin` claim). The legacy token
        is for scripts and CI, in a header the browser never sends. Every mutating call that
        succeeds writes one AdminLog entry."""
        actor = None
        if admin_token and x_admin_token and hmac.compare_digest(x_admin_token, admin_token):
            actor = "token"
        elif claims := await asyncio.to_thread(
            accounts.verify_claims, authorization.removeprefix("Bearer "), project
        ):
            email = str(claims.get("email") or "").lower()
            if claims.get("admin") is True or email in admin_emails:
                actor = email or str(claims["sub"])
            else:
                raise deny(request, 403, "not an admin")
        if actor is None:
            raise deny(request, 401, "admin sign-in required")
        request.state.actor = actor
        request.state.before = None
        yield
        if request.method not in ("GET", "HEAD"):
            route = request.scope.get("route")
            entry = {
                "id": uuid.uuid4().hex,
                "at": datetime.now(UTC).isoformat(),
                "actor": actor,
                "method": request.method,
                "route": getattr(route, "path", request.url.path),
                "target": json.dumps(request.path_params),
                "after": (await request.body())[:4000].decode(errors="replace"),
                "before": json.dumps(request.state.before) if request.state.before else None,
            }
            await asyncio.to_thread(store.create, db, "AdminLog", entry)

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
        region: str | None = None,
        topic: str | None = None,
        sort: Literal["recent", "anomalies", "reports"] = "recent",
    ) -> list[dict[str, Any]]:
        return readmodel.list_stories(db, region, topic, sort)

    @v1.get("/search")
    def search(q: Annotated[str, Query(max_length=80)] = "") -> dict[str, list[dict[str, Any]]]:
        """Stories, events, sources and people whose title or name contains `q`. Public stories only."""
        return readmodel.search(db, q)

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
        return detective.scorecard(db, story_id) | {"domains": directions.for_story(db, story_id)}

    @v1.get("/directions")
    def directions_list() -> dict[str, Any]:
        # D22: model speculation on domains, served only with the detective flag on
        if not detective.enabled():
            raise HTTPException(404, "not found")
        return directions.overview(db)

    @v1.get("/directions/{domain_id}")
    def directions_one(domain_id: str) -> Any:
        if not detective.enabled():
            raise HTTPException(404, "not found")
        return found(directions.detail(db, domain_id))

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
        if since is not None:
            try:
                datetime.fromisoformat(since)
            except ValueError as exc:
                raise HTTPException(422, "since must be an ISO date or time") from exc
        return readmodel.today(db, follow, since)

    @v1.post("/reports-problem", status_code=201, dependencies=[Depends(throttle("problem"))])
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
        key = who(request)
        if not streams.acquire(key):
            raise HTTPException(429, "Too many open streams.", headers={"Retry-After": "30"})

        async def events() -> AsyncIterator[str]:
            try:
                async for m in hub.subscribe(story_id):  # one poll per story, shared by all readers
                    if await request.is_disconnected():
                        break
                    if m is None:
                        yield ": keepalive\n\n"
                    else:
                        yield f"event: {m['type']}\ndata: {json.dumps(m['data'])}\n\n"
            finally:
                streams.release(key)

        return StreamingResponse(events(), media_type="text/event-stream")

    @v1.put("/subscription", dependencies=[Depends(throttle("subscription"))])
    def subscribe(
        body: Subscription, authorization: Annotated[str, Header()] = ""
    ) -> dict[str, bool]:
        """A new address is stored pending and gets one confirmation mail. Changing an existing
        one needs its token (from a digest mail) or a signed-in account with that email."""
        claims = accounts.verify_claims(authorization.removeprefix("Bearer "), project)
        try:
            new = digest.subscribe(
                db,
                body.email,
                body.frequency,
                body.follows,
                body.token,
                str(claims.get("email")) if claims and claims.get("email") else None,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(403, "use the link in a digest mail, or sign in") from exc
        if new and mailer:
            mailer(body.email.strip().lower(), *digest.confirmation_mail(site, new[0]))
        return {"subscribed": True, "pending": bool(new)}

    def page(title: str, action: str, token: str, button: str) -> HTMLResponse:
        if not digest.exists(db, token):
            raise HTTPException(404, "not found")
        return HTMLResponse(digest.action_page(title, action, token, button))

    @v1.get("/unsubscribe", response_class=HTMLResponse)
    def unsubscribe_page(token: str) -> HTMLResponse:
        return page("Unsubscribe from the Weft digest", "unsubscribe", token, "Unsubscribe")

    @v1.post("/unsubscribe", response_class=HTMLResponse)
    def unsubscribe(token: str) -> HTMLResponse:
        found(digest.unsubscribe(db, token) or None)
        return HTMLResponse("<!doctype html><meta charset=utf-8><p>You are unsubscribed.</p>")

    @v1.get("/confirm", response_class=HTMLResponse)
    def confirm_page(token: str) -> HTMLResponse:
        return page("Confirm your Weft digest", "confirm", token, "Confirm")

    @v1.post("/confirm", response_class=HTMLResponse)
    def confirm(token: str) -> HTMLResponse:
        found(digest.confirm(db, token) or None)
        return HTMLResponse("<!doctype html><meta charset=utf-8><p>Confirmed. Thank you.</p>")

    @v1.post("/ask", dependencies=[Depends(throttle("ask"))])
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

    @adm.get("/me")
    def admin_me(request: Request) -> dict[str, str]:
        return {"actor": request.state.actor}

    @adm.get("/log")
    def admin_log() -> list[dict[str, Any]]:
        """The last 50 admin changes: who, when, which route and target, what changed."""
        return db.execute(
            "MATCH (n:AdminLog) RETURN n.at AS at, n.actor AS actor, n.method AS method, "
            "n.route AS route, n.target AS target, n.before AS before, n.after AS after "
            "ORDER BY n.at DESC LIMIT 50"
        )

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
            "yield_14d",
            "dormant_at",
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

    @adm.get("/autoclean")
    def autoclean_runs(limit: int = 100) -> list[dict[str, Any]]:
        """What each autoclean rule matched and changed on its recent runs, newest first (#147)."""
        return store.nodes(
            db,
            "AutocleanRun",
            "MATCH (n:AutocleanRun) RETURN n ORDER BY n.started_at DESC LIMIT ?",
            (min(limit, 500),),
        )

    @adm.put("/stories/{story_id}/public")
    def set_public(story_id: str, body: Visibility, request: Request) -> dict[str, Any]:
        was = [s["public"] for s in store.stories(db, public_only=False) if s["id"] == story_id]
        request.state.before = {"public": was[0]} if was else None
        if not store.set_public(db, story_id, body.public):
            raise HTTPException(404, "no such story")
        return {"id": story_id, "public": body.public}

    @adm.patch("/sources/{source_id}")
    def patch_source(source_id: str, body: SourcePatch, request: Request) -> dict[str, Any]:
        """Set country, state_run or ownership. state_run and owner_id need their citation URL
        (product rule: facts are cited or stay 'unverified')."""
        data = body.model_dump(exclude_unset=True)
        if data.get("state_run") is not None and not data.get("state_run_source"):
            raise HTTPException(422, "state_run needs state_run_source")
        if data.get("owner_id") and not data.get("ownership_source"):
            raise HTTPException(422, "owner_id needs ownership_source")
        if not (current := store.all_sources(db, "n.id=?", (source_id,))):
            raise HTTPException(404, "no such source")
        request.state.before = {k: current[0].get(k) for k in data}
        if "country" in data:  # also re-tags the source's reports
            store.set_country(db, source_id, data.pop("country"), "admin")
        if data.get("status") == "active":
            data["dormant_at"] = (
                None  # an admin reactivation; discovery will not re-dorm it for 30 days
            )
            data["discovered_at"] = datetime.now(UTC).isoformat()
        if "paywalled" in data:
            data["paywalled_source"] = "admin"  # the fetcher never overrides a hand-set flag
        for col, val in data.items():  # col is a SourcePatch field name, never user text
            if isinstance(val, list):  # stored as JSON text, like feeds and sitemaps
                val = json.dumps(val)
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
        db,
        os.environ["ADMIN_TOKEN"],
        _asker(db),
        accounts.FirestorePrefs(project),
        project,
        proxy_secret=os.environ.get("PROXY_SECRET", ""),
        admin_emails=frozenset(
            e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()
        ),
        mailer=_mailer(),
        site=os.environ.get("SITE_URL", ""),
    )


def _mailer() -> Callable[[str, str, str], None] | None:
    if not os.environ.get("SMTP_HOST"):
        return None
    from pipeline.notify import smtp_send

    return smtp_send


def _asker(db: store.Db) -> Callable[[str], dict[str, Any]] | None:
    if "MODEL_BASE_URL" not in os.environ:
        return None
    from pipeline.gcp import bq_sink
    from weft_core import ask, config
    from weft_core.ledger import GraphLedger, limits
    from weft_core.models import ModelClient
    from weft_core.nlp import default_embedder

    tokens, cost = limits(config.pipeline(), "ask")
    model = ModelClient(
        base_url=os.environ["MODEL_BASE_URL"],
        api_key=os.environ["MODEL_API_KEY"],
        model=os.environ["MODEL_NAME"],
        revision=os.environ["MODEL_REVISION"],
        log=bq_sink(os.environ["PROJECT_ID"]),
        ledger=GraphLedger(db),
        caller="ask",
        daily_tokens=tokens,
        daily_cost_usd=cost,
    )
    embedder = default_embedder()
    return lambda q: ask.answer(db, embedder, model, q)
