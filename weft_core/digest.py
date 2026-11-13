"""Email digest (Phase 4): what changed in the stories a reader follows.

Coverage language only. Provisional anomalies never notify (readmodel.today leaves them out).
Subscriptions are Subscription nodes in Neo4j; the unsubscribe token is in every mail.
"""

import json
import re
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from weft_core import readmodel, store
from weft_core.store import Db

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
Send = Callable[[str, str, str], None]  # to, subject, body


def subscribe(db: Db, email: str, frequency: str, follows: list[str]) -> None:
    if not EMAIL.match(email) or frequency not in ("daily", "weekly"):
        raise ValueError("bad email or frequency")
    db.execute(
        "MERGE (n:Subscription {email: ?}) "
        "ON CREATE SET n.token=?, n.created_at=? SET n.frequency=?, n.follows=?",
        (
            email,
            secrets.token_urlsafe(16),
            datetime.now(UTC).isoformat(),
            frequency,
            json.dumps(follows),
        ),
    )


def unsubscribe(db: Db, token: str) -> bool:
    return bool(db.execute("MATCH (n:Subscription {token: ?}) DELETE n RETURN 1 AS x", (token,)))


def compose(
    db: Db, sub: dict[str, Any], site: str, now: datetime | None = None
) -> tuple[str, str] | None:
    """Only what is new in the followed stories since the last mail (or the last day or week)."""
    now = now or datetime.now(UTC)
    window = timedelta(days=7 if sub["frequency"] == "weekly" else 1)
    since = sub.get("last_sent_at") or (now - window).date().isoformat()
    t = readmodel.today(db, json.loads(sub["follows"]), since=since, now=now)
    mine = {c["id"] for c in t["followed"]}
    lines: list[str] = []
    for e in t["new_events"]:
        if e["story_id"] in mine:
            docs = f", {e['new_documents']} new documents" if e["new_documents"] else ""
            lines.append(
                f'{e["title"]}: "{e["label"]}" (headline from {e["label_source"]}), '
                f"{e['outlets']} outlets, {len(e['perspectives'])} perspectives{docs}. "
                f"{site}/s/{e['story_id']}/e/{e['id']}"
            )
    for a in t["new_anomalies"]:
        if a["story_id"] in mine:
            lines.append(f"Reports don't line up: {a['summary']} {site}/s/{a['story_id']}")
    if not lines:
        return None
    for b in t["blind_spots"]:
        if b["story_id"] in mine and b["no_source_published"]:
            lines.append(
                f"No source has published from {', '.join(b['no_source_published'])} on {b['title']}."
            )
    body = (
        "\n".join(lines)
        + f"\n\nWeft shows who reported what. It does not say what is true.\nUnsubscribe: {site}/api/v1/unsubscribe?token={sub['token']}\n"
    )
    return f"Weft {sub['frequency']} digest, {now.date().isoformat()}", body


def send_due(db: Db, send: Send, site: str, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    today = now.date().isoformat()
    sent = 0
    for sub in store.nodes(db, "Subscription", "MATCH (n:Subscription) RETURN n"):
        if sub["last_sent"] == today or (sub["frequency"] == "weekly" and now.weekday() != 0):
            continue
        mail = compose(db, sub, site, now)
        if mail:
            send(sub["email"], *mail)
            sent += 1
        db.execute(
            "MATCH (n:Subscription {email: ?}) SET n.last_sent=?, n.last_sent_at=?",
            (sub["email"], today, now.isoformat()),
        )
    return sent
