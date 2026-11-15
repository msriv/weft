"""Nightly stage 12: send the email digest. Skipped (0) when no SMTP host is configured."""

import os
import smtplib
from collections.abc import Iterator
from contextlib import contextmanager
from email.message import EmailMessage

from pipeline.ctx import Ctx
from weft_core import digest


def _message(to: str, subject: str, body: str, headers: dict[str, str]) -> EmailMessage:
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = os.environ["MAIL_FROM"], to, subject
    for k, v in headers.items():
        m[k] = v
    m.set_content(body)
    return m


def _connect() -> smtplib.SMTP:
    s = smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "587")))
    s.starttls()
    s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
    return s


def smtp_send(to: str, subject: str, body: str, headers: dict[str, str] | None = None) -> None:
    """One mail on its own connection (confirmations)."""
    with _connect() as s:
        s.send_message(_message(to, subject, body, headers or {}))


@contextmanager
def smtp_session() -> Iterator[digest.Send]:
    """One connection for a whole run; reconnects once if the server drops it."""
    conn = _connect()
    try:

        def send(to: str, subject: str, body: str, headers: dict[str, str]) -> None:
            nonlocal conn
            try:
                conn.send_message(_message(to, subject, body, headers))
            except smtplib.SMTPServerDisconnected:
                conn = _connect()
                conn.send_message(_message(to, subject, body, headers))

        yield send
    finally:
        try:
            conn.quit()
        except (smtplib.SMTPException, OSError):
            pass


def run(ctx: Ctx) -> int:
    if not os.environ.get("SMTP_HOST"):
        return 0
    with smtp_session() as send:
        return digest.send_due(ctx.db, send, os.environ["SITE_URL"])
