"""Email digest (Phase 4): what changed in the stories a reader follows.

Coverage language only. Provisional anomalies never notify (readmodel.today leaves them out).
Subscriptions are Subscription nodes in Neo4j; the unsubscribe token is in every mail.
"""

import json
import re
import secrets
from collections.abc import Callable
from datetime import UTC, datetime
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


def compose(db: Db, sub: dict[str, Any], site: str) -> tuple[str, str] | None:
    t = readmodel.today(db, json.loads(sub["follows"]))
    lines: list[str] = []
    for c in t["followed"]:
        lines.append(
            f"{c['title']}: {c['reports']} reports from {len(c['perspectives'])} perspectives. {site}/s/{c['id']}"
        )
    for a in t["new_anomalies"]:
        if a["story_id"] in {c["id"] for c in t["followed"]}:
            lines.append(f"Reports don't line up: {a['summary']} {site}/s/{a['story_id']}")
    for b in t["blind_spots"]:
        if b["story_id"] in {c["id"] for c in t["followed"]}:
            lines.append(
                f"No source has published from {', '.join(b['no_source_published'])} on {b['title']}."
            )
    if not t["followed"] or not t["changes"] and not t["new_anomalies"]:
        return None
    body = (
        "\n".join(lines)
        + f"\n\nWeft shows who reported what. It does not say what is true.\nUnsubscribe: {site}/api/v1/unsubscribe?token={sub['token']}\n"
    )
    return f"Weft {sub['frequency']} digest, {t['day']}", body


def send_due(db: Db, send: Send, site: str, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    today = now.date().isoformat()
    sent = 0
    for sub in store.nodes(db, "Subscription", "MATCH (n:Subscription) RETURN n"):
        if sub["last_sent"] == today or (sub["frequency"] == "weekly" and now.weekday() != 0):
            continue
        mail = compose(db, sub, site)
        if mail:
            send(sub["email"], *mail)
            sent += 1
        db.execute("MATCH (n:Subscription {email: ?}) SET n.last_sent=?", (sub["email"], today))
    return sent
