import smtplib
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from services.api.app import create_app
from weft_core import config, digest, store

NOW = datetime(2026, 11, 6, tzinfo=UTC)


def api() -> tuple[TestClient, store.Db, list[tuple[str, str, str]]]:
    db = store.local_db()
    store.init(db)
    db.execute("MATCH (n:Subscription) DETACH DELETE n")
    mails: list[tuple[str, str, str]] = []
    lim = {**config.pipeline()["limits"], "subscription": {"per_minute": 100, "per_day": 1000}}
    app = create_app(
        db, "t0k", mailer=lambda *a: mails.append(a), site="https://w.test", limits=lim
    )
    return TestClient(app), db, mails


def token_of(db: store.Db, email: str) -> str:
    return str(
        db.execute("MATCH (n:Subscription {email: ?}) RETURN n.token AS t", (email,))[0]["t"]
    )


def body(email: str = "a@x.org", **kw: Any) -> dict[str, Any]:
    return {"email": email, "frequency": "daily", "follows": ["iran-israel-war"], **kw}


def test_new_subscription_gets_one_confirmation_and_no_digest_until_confirmed() -> None:
    c, db, mails = api()
    r = c.put("/v1/subscription", json=body())
    assert r.json() == {"subscribed": True, "pending": True} and len(mails) == 1
    assert "Nothing is sent until you confirm" in mails[0][2]
    sent: list[tuple[Any, ...]] = []
    db.execute("MERGE (n:DailyDiff {day: '2026-11-06'}) SET n.payload=?", ('{"new_events":["e"]}',))
    assert digest.send_due(db, lambda *a: sent.append(a), "https://w.test", NOW) == 0
    t = token_of(db, "a@x.org")
    assert c.get(f"/v1/confirm?token={t}").status_code == 200  # a page; nothing changes
    assert db.execute("MATCH (n:Subscription) RETURN n.status AS s")[0]["s"] == "pending"
    assert c.post(f"/v1/confirm?token={t}").status_code == 200
    assert db.execute("MATCH (n:Subscription) RETURN n.status AS s")[0]["s"] == "confirmed"


def test_changing_follows_needs_the_token_or_a_matching_account() -> None:
    c, db, _ = api()
    c.put("/v1/subscription", json=body())
    assert c.put("/v1/subscription", json=body(follows=[])).status_code == 403
    assert c.put("/v1/subscription", json=body(follows=[], token="wrong")).status_code == 403
    t = token_of(db, "a@x.org")
    assert c.put("/v1/subscription", json=body(follows=[], token=t)).status_code == 200


def test_pending_expires_after_seven_days() -> None:
    c, db, _ = api()
    c.put("/v1/subscription", json=body())
    db.execute("MATCH (n:Subscription) SET n.created_at = '2026-10-01T00:00:00+00:00'")
    digest.send_due(db, lambda *a: None, "https://w.test", NOW)
    assert db.execute("MATCH (n:Subscription) RETURN count(n) AS c")[0]["c"] == 0


def confirmed(db: store.Db, *emails: str) -> None:
    for e in emails:
        digest.subscribe(db, e, "daily", ["iran-israel-war"])
    db.execute("MATCH (n:Subscription) SET n.status = 'confirmed'")
    db.execute("MERGE (n:DailyDiff {day: '2026-11-06'}) SET n.payload=?", ('{"new_events":["e"]}',))


@pytest.fixture
def story(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(digest, "compose", lambda *a, **k: ("subject", "body"))


def test_failing_recipient_does_not_stop_the_next_and_keeps_last_sent(story: None) -> None:
    _, db, _ = api()
    confirmed(db, "a@x.org", "b@x.org")
    got: list[tuple[str, str, str, dict[str, str]]] = []

    def send(to: str, subject: str, text: str, headers: dict[str, str]) -> None:
        if to == "a@x.org":
            raise smtplib.SMTPServerDisconnected("boom")
        got.append((to, subject, text, headers))

    assert digest.send_due(db, send, "https://w.test", NOW) == 1
    assert [g[0] for g in got] == ["b@x.org"]
    rows = {
        r["e"]: r["l"]
        for r in db.execute("MATCH (n:Subscription) RETURN n.email AS e, n.last_sent AS l")
    }
    assert rows == {"a@x.org": None, "b@x.org": "2026-11-06"}
    h = got[0][3]
    assert h["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert h["List-Unsubscribe"].startswith("<https://w.test/api/v1/unsubscribe?token=")


def test_three_hard_failures_mark_bouncing(story: None) -> None:
    _, db, _ = api()
    confirmed(db, "a@x.org")

    def send(*a: Any) -> None:
        raise smtplib.SMTPRecipientsRefused({"a@x.org": (550, b"no such user")})

    for _ in range(3):
        digest.send_due(db, send, "https://w.test", NOW)
    assert db.execute("MATCH (n:Subscription) RETURN n.status AS s")[0]["s"] == "bouncing"
    sent: list[Any] = []
    assert digest.send_due(db, lambda *a: sent.append(a), "https://w.test", NOW) == 0 and not sent
