"""Story API: public list for readers, admin toggle for what is public (D15)."""

import hmac
import os
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from weft_core import store


class Visibility(BaseModel):
    public: bool


def create_app(db: store.Db, admin_token: str) -> FastAPI:
    app = FastAPI(title="Weft API")

    def admin(authorization: Annotated[str, Header()] = "") -> None:
        # shortcut: one shared admin token, replace with Firebase auth in Phase 4
        if not admin_token or not hmac.compare_digest(authorization, f"Bearer {admin_token}"):
            raise HTTPException(401, "admin token required")

    @app.get("/stories")
    def public_stories() -> list[dict[str, Any]]:
        return store.stories(db, public_only=True)

    @app.get("/admin/stories", dependencies=[Depends(admin)])
    def all_stories() -> list[dict[str, Any]]:
        return store.stories(db, public_only=False)

    @app.put("/admin/stories/{story_id}/public", dependencies=[Depends(admin)])
    def set_public(story_id: str, body: Visibility) -> dict[str, Any]:
        if not store.set_public(db, story_id, body.public):
            raise HTTPException(404, "no such story")
        return {"id": story_id, "public": body.public}

    return app


def app_from_env() -> FastAPI:
    return create_app(store.from_env(), os.environ["ADMIN_TOKEN"])
