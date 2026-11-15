import base64
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from services.api.app import create_app
from weft_core import store

P = "p"


def token(uid: str, email: str, **extra: Any) -> dict[str, str]:
    def seg(d: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")

    jwt = f"{seg({'alg': 'none'})}.{seg({'aud': P, 'sub': uid, 'email': email, **extra})}."
    return {"Authorization": f"Bearer {jwt}"}


@pytest.fixture(autouse=True)
def emulator(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FIREBASE_AUTH_EMULATOR_HOST", "auth:9099")


def client() -> tuple[TestClient, store.Db]:
    db = store.local_db()
    store.init(db)
    db.execute("MATCH (n:AdminLog) DETACH DELETE n")
    return TestClient(
        create_app(db, "t0k", project=P, admin_emails=frozenset({"ed@example.org"}))
    ), db


def test_non_admin_is_403_allowlisted_is_200_legacy_token_still_works() -> None:
    c, _ = client()
    assert c.get("/admin/me").status_code == 401
    assert c.get("/admin/me", headers=token("u1", "reader@example.org")).status_code == 403
    r = c.get("/admin/me", headers=token("u2", "Ed@Example.org"))
    assert r.status_code == 200 and r.json() == {"actor": "ed@example.org"}
    assert c.get("/admin/me", headers=token("u3", "x@example.org", admin=True)).status_code == 200
    assert c.get("/admin/me", headers={"X-Admin-Token": "t0k"}).json() == {"actor": "token"}
    assert c.get("/admin/me", headers={"Authorization": "Bearer t0k"}).status_code == 401


def test_failed_attempts_are_rate_limited() -> None:
    c, _ = client()
    codes = [c.get("/admin/me", headers={"X-Admin-Token": "bad"}).status_code for _ in range(12)]
    assert codes[0] == 401 and codes[-1] == 429


def test_mutating_calls_are_logged_with_before_and_after() -> None:
    c, db = client()
    store.create(db, "Source", {**store.NODES["Source"], "id": "s1", "domain": "s1.example"})
    h = token("u2", "ed@example.org")
    assert c.patch("/admin/sources/s1", json={"paywalled": True}, headers=h).status_code == 200
    assert c.get("/admin/sources", headers=h).status_code == 200  # reads are not logged
    [entry] = c.get("/admin/log", headers=h).json()
    assert entry["actor"] == "ed@example.org" and entry["method"] == "PATCH"
    assert entry["route"] == "/admin/sources/{source_id}" and "s1" in entry["target"]
    assert json.loads(entry["before"]) == {"paywalled": 0}
    assert json.loads(entry["after"]) == {"paywalled": True}
    c.post("/admin/sources", json={"url": "https://nope"}, headers=h)  # 422: not logged
    assert len(c.get("/admin/log", headers=h).json()) == 1
