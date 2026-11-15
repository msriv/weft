"""Rate limits and input checks on the public API (#158). A stub store: nothing here needs Neo4j."""

from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from services.api.app import create_app
from services.api.limits import Limiter, Streams, client_key
from weft_core.ledger import MemoryLedger
from weft_core.models import EmptyOutput, ModelClient

LIM: dict[str, Any] = {
    "ask": {"per_minute": 2, "per_day": 100},
    "problem": {"per_minute": 2, "per_day": 100},
    "subscription": {"per_minute": 2, "per_day": 100},
    "auth": {"per_minute": 2, "per_day": 100},
    "streams": {"per_client": 1, "total": 2},
    "max_body_bytes": 500,
}


class Stub:
    def execute(self, query: str, args: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        return [{"id": 1}]


def client(asker: Any = None, secret: str = "") -> TestClient:
    return TestClient(create_app(Stub(), "t0k", asker, limits=LIM, proxy_secret=secret))


def test_limiter_window_and_retry_after() -> None:
    now = [0.0]
    lim = Limiter(lambda: now[0])
    assert lim.check("a", "ip", 2, 5) is None and lim.check("a", "ip", 2, 5) is None
    wait = lim.check("a", "ip", 2, 5)
    assert wait is not None and 1 <= wait <= 61
    now[0] = 61
    assert lim.check("a", "ip", 2, 5) is None
    assert lim.check("a", "other", 2, 5) is None  # keys are separate


def test_day_limit() -> None:
    now = [0.0]
    lim = Limiter(lambda: now[0])
    for i in range(3):
        now[0] = i * 100
        assert lim.check("a", "ip", 10, 3) is None
    now[0] = 400
    assert lim.check("a", "ip", 10, 3) is not None


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", "/v1/ask", {"question": "who reported it?"}),
        ("post", "/v1/reports-problem", {"kind": "other", "message": "something is off"}),
        ("put", "/v1/subscription", {"email": "a@b.co", "frequency": "daily"}),
    ],
)
def test_third_call_in_a_minute_is_429_with_retry_after(method: str, path: str, body: Any) -> None:
    c = client(lambda q: {"sentences": [], "cites": []})
    codes = [getattr(c, method)(path, json=body).status_code for _ in range(3)]
    assert codes[2] == 429 and codes[0] != 429
    r = getattr(c, method)(path, json=body)
    assert int(r.headers["retry-after"]) >= 1


def test_forged_client_address_does_not_dodge_the_limit() -> None:
    c = client(lambda q: {"sentences": [], "cites": []})
    body = {"question": "who reported it?"}
    for i in range(3):
        r = c.post("/v1/ask", json=body, headers={"x-weft-client-ip": f"9.9.9.{i}"})
    assert r.status_code == 429  # the header counts only with the proxy secret


def test_signed_proxy_address_separates_readers() -> None:
    c = client(lambda q: {"sentences": [], "cites": []}, secret="s3")
    body = {"question": "who reported it?"}
    seen = [
        c.post(
            "/v1/ask", json=body, headers={"x-weft-proxy": "s3", "x-weft-client-ip": f"9.9.9.{i}"}
        ).status_code
        for i in range(5)
    ]
    assert 429 not in seen


def test_client_key() -> None:
    assert client_key({"x-forwarded-for": "6.6.6.6, 1.2.3.4"}, "peer", "") == "1.2.3.4"
    assert client_key({}, "peer", "") == "peer"
    h = {"x-weft-proxy": "s", "x-weft-client-ip": "7.7.7.7"}
    assert client_key(h, "peer", "s") == "7.7.7.7"
    assert client_key(h, "peer", "other") == "peer"
    assert client_key(h, "peer", "") == "peer"


def test_daily_ask_cap_is_429_and_makes_no_model_request() -> None:
    sent: list[int] = []

    def handler(req: httpx.Request) -> httpx.Response:
        sent.append(1)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    ledger = MemoryLedger()
    from datetime import UTC, datetime

    ledger.add(datetime.now(UTC).date().isoformat(), "ask", 1000, 0.0)
    model = ModelClient(
        base_url="http://m", api_key="k", model="m", revision="r", log=lambda c: None,
        transport=httpx.MockTransport(handler), ledger=ledger, caller="ask", daily_tokens=1000,
    )  # fmt: skip

    def asker(q: str) -> dict[str, Any]:
        model.complete(prompt_template="ask@1", instructions="i", data=q, max_tokens=10)
        return {}

    r = client(asker).post("/v1/ask", json={"question": "who reported it?"})
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0 and sent == []


def test_other_model_failures_are_503() -> None:
    def empty(q: str) -> dict[str, Any]:
        raise EmptyOutput("none")

    assert client(empty).post("/v1/ask", json={"question": "who reported it?"}).status_code == 503


def test_stream_caps() -> None:
    s = Streams(per_client=1, total=2)
    assert s.acquire("a") and not s.acquire("a")
    assert s.acquire("b") and not s.acquire("c")  # total of 2
    s.release("a")
    assert s.acquire("c")


def test_since_and_sort_are_validated() -> None:
    c = client()
    assert c.get("/v1/today", params={"since": "not-a-date"}).status_code == 422
    assert c.get("/v1/stories", params={"sort": "zzz"}).status_code == 422


def test_oversized_body_is_413() -> None:
    r = client().post("/v1/reports-problem", json={"kind": "other", "message": "x" * 600})
    assert r.status_code == 413
