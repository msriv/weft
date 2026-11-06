"""Nightly stage 12: send the email digest. Skipped (0) when no SMTP host is configured."""

import os
import smtplib
from email.message import EmailMessage

from pipeline.ctx import Ctx
from weft_core import digest


def smtp_send(to: str, subject: str, body: str) -> None:
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = os.environ["MAIL_FROM"], to, subject
    m.set_content(body)
    with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "587"))) as s:
        s.starttls()
        s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
        s.send_message(m)


def run(ctx: Ctx) -> int:
    if not os.environ.get("SMTP_HOST"):
        return 0
    return digest.send_due(ctx.db, smtp_send, os.environ["SITE_URL"])
