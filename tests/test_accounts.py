"""Reader accounts: token check, prefs endpoints, Firestore REST shape."""

import base64
import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from services.api.app import create_app
from weft_core import accounts, store


def token(sub: str, aud: str = "p") -> str:
    def b64(d: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")

    return f"{b64({'alg': 'none'})}.{b64({'sub': sub, 'aud': aud})}."


class Mem:
    def __init__(self) -> None:
        self.d: dict[str, dict[str, Any]] = {}

    def get(self, uid: str) -> dict[str, Any]:
        return self.d.get(uid, {})

    def put(self, uid: str, prefs: dict[str, Any]) -> None:
        self.d[uid] = prefs


@pytest.fixture(autouse=True)
def emulator(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FIREBASE_AUTH_EMULATOR_HOST", "auth:9099")


def client() -> TestClient:
    return TestClient(create_app(store.local_db(), "t0k", prefs=Mem(), project="p"))


def test_prefs_need_a_valid_token_and_are_per_reader() -> None:
    c = client()
    assert c.get("/v1/me/prefs").status_code == 401
    wrong_project = {"Authorization": f"Bearer {token('a', 'other')}"}
    assert c.get("/v1/me/prefs", headers=wrong_project).status_code == 401
    a, b = ({"Authorization": f"Bearer {token(u)}"} for u in ("a", "b"))
    assert c.get("/v1/me/prefs", headers=a).json() == {}
    c.put("/v1/me/prefs", json={"follows": ["iran-israel-war"], "frequency": "weekly"}, headers=a)
    assert c.get("/v1/me/prefs", headers=a).json()["follows"] == ["iran-israel-war"]
    assert c.get("/v1/me/prefs", headers=b).json() == {}


def test_firestore_prefs_roundtrip_over_rest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", "fs:8080")
    docs: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/v1/projects/p/databases/(default)/documents/users/u1"
        if req.method == "PATCH":
            docs["u1"] = json.loads(req.content)
            return httpx.Response(200, json=docs["u1"])
        return httpx.Response(200, json=docs["u1"]) if "u1" in docs else httpx.Response(404)

    fs = accounts.FirestorePrefs("p", httpx.Client(transport=httpx.MockTransport(handler)))
    assert fs.get("u1") == {}
    fs.put("u1", {"follows": ["x"]})
    assert fs.get("u1") == {"follows": ["x"]}
