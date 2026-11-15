"""Email digest (Phase 4): what changed in the stories a reader follows.

Coverage language only. Provisional anomalies never notify (readmodel.today leaves them out).
Subscriptions are Subscription nodes in Neo4j. A new one is `pending` until the address owner
confirms; only `confirmed` ones get digests. The token in every mail confirms, edits and
unsubscribes; unsubscribing and confirming need a POST, so a link scanner changes nothing.
"""

import html
import json
import logging
import re
import secrets
import smtplib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from weft_core import readmodel, store
from weft_core.store import Db

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
Send = Callable[[str, str, str, dict[str, str]], None]  # to, subject, body, extra headers
PENDING_TTL = timedelta(days=7)
MAX_HARD_FAILS = 3
log = logging.getLogger(__name__)


def subscribe(
    db: Db,
    email: str,
    frequency: str,
    follows: list[str],
    proof: str | None = None,
    account_email: str | None = None,
) -> tuple[str, str] | None:
    """Create a pending subscription, or change an existing one. Returns (token, "pending") for
    a new address so the caller can mail the confirmation; None for a change or a signed-in
    account's own address. An existing address needs its token or a matching account (else
    PermissionError)."""
    email = email.strip().lower()
    if not EMAIL.match(email) or frequency not in ("daily", "weekly"):
        raise ValueError("bad email or frequency")
    own = account_email is not None and account_email.lower() == email
    row = db.execute("MATCH (n:Subscription {email: ?}) RETURN n.token AS token", (email,))
    if row and not own and not (proof and secrets.compare_digest(proof, row[0]["token"] or "")):
        raise PermissionError("proof of ownership needed")
    token = row[0]["token"] if row else secrets.token_urlsafe(16)
    db.execute(
        "MERGE (n:Subscription {email: ?}) ON CREATE SET n.token=?, n.created_at=?, n.status=?, "
        "n.fails=0 SET n.frequency=?, n.follows=?",
        (
            email,
            token,
            datetime.now(UTC).isoformat(),
            "confirmed" if own else "pending",
            frequency,
            json.dumps(follows),
        ),
    )
    return (token, "pending") if not row and not own else None


def confirm(db: Db, token: str) -> bool:
    return bool(
        db.execute(
            "MATCH (n:Subscription {token: ?}) SET n.status='confirmed', n.fails=0 RETURN 1 AS x",
            (token,),
        )
    )


def unsubscribe(db: Db, token: str) -> bool:
    return bool(db.execute("MATCH (n:Subscription {token: ?}) DELETE n RETURN 1 AS x", (token,)))


def exists(db: Db, token: str) -> bool:
    return bool(db.execute("MATCH (n:Subscription {token: ?}) RETURN 1 AS x", (token,)))


def confirmation_mail(site: str, token: str) -> tuple[str, str]:
    return (
        "Confirm your Weft digest",
        (
            "Someone asked for a Weft digest to be sent to this address. Nothing is sent until you "
            f"confirm. Confirm here: {site}/api/v1/confirm?token={token}\n\n"
            "If this was not you, ignore this mail; the request expires in 7 days.\n"
        ),
    )


def action_page(title: str, action: str, token: str, button: str) -> str:
    """The page a mail link opens: a button, because a link scanner follows GET but not a click."""
    t = html.escape(token, quote=True)
    return (
        f"<!doctype html><meta charset=utf-8><title>{html.escape(title)}</title>"
        f"<h1>{html.escape(title)}</h1><form method=post action='/api/v1/{action}?token={t}'>"
        f"<button>{html.escape(button)}</button></form>"
    )


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


def _hard(exc: Exception) -> bool:
    """A refusal that will not change on retry: the address is bad, not the connection."""
    return isinstance(exc, smtplib.SMTPRecipientsRefused) or (
        isinstance(exc, smtplib.SMTPResponseException) and 500 <= exc.smtp_code < 600
    )


def send_due(db: Db, send: Send, site: str, now: datetime | None = None) -> int:
    """Mail every due, confirmed subscriber. A failing recipient is logged and skipped; three hard
    failures in a row mark it `bouncing`. `last_sent` moves only after a successful send."""
    now = now or datetime.now(UTC)
    today = now.date().isoformat()
    db.execute(
        "MATCH (n:Subscription) WHERE n.status = 'pending' AND n.created_at < ? DETACH DELETE n",
        ((now - PENDING_TTL).isoformat(),),
    )
    sent = 0
    for sub in store.nodes(db, "Subscription", "MATCH (n:Subscription) RETURN n"):
        if sub["status"] != "confirmed" or sub["last_sent"] == today:
            continue
        if sub["frequency"] == "weekly" and now.weekday() != 0:
            continue
        mail = compose(db, sub, site, now)
        if mail:
            link = f"{site}/api/v1/unsubscribe?token={sub['token']}"
            headers = {
                "List-Unsubscribe": f"<{link}>",
                "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
            }
            try:
                send(sub["email"], *mail, headers)
            except Exception as exc:  # noqa: BLE001 - one bad recipient must not stop the rest
                log.warning("digest to %s failed: %r", sub["email"], exc)
                if _hard(exc):
                    fails = int(sub["fails"] or 0) + 1
                    db.execute(
                        "MATCH (n:Subscription {email: ?}) SET n.fails=?, n.status=?",
                        (
                            sub["email"],
                            fails,
                            "bouncing" if fails >= MAX_HARD_FAILS else "confirmed",
                        ),
                    )
                continue
            sent += 1
        db.execute(
            "MATCH (n:Subscription {email: ?}) SET n.last_sent=?, n.last_sent_at=?, n.fails=0",
            (sub["email"], today, now.isoformat()),
        )
    return sent
