"""Nightly stage: who said what in official documents (feeds proceeding and person pages).

Transcripts are split into speaker turns ("Name: text"). Each statement stores a short quote and
its character offsets; the actor row is keyed by a slug of the name. No model. Person pages are
for public figures in their public role (spec: private individuals appear by role, not name), so
only speakers of official proceedings and releases become actors here.
"""

import hashlib
import re
from datetime import datetime, timedelta

from pipeline.ctx import Ctx
from weft_core import graph

TITLE = r"(?:Mr|Mrs|Ms|Dr|Shri|Smt|Hon|Prof|Sir|President|Minister|Speaker|Chairman|Chairperson)\.?"
NAME = r"[A-Z][\w.'’-]+(?:\s+[A-Z][\w.'’-]+){0,3}"
TURN = re.compile(
    rf"^(?:{TITLE}\s+)?(?P<name>{NAME})\s*(?:\((?P<role>[^)]{{2,60}})\))?:\s+(?P<text>\S.*)$",
    re.MULTILINE,
)
NOT_SPEAKERS = {"Note", "Source", "Date", "Subject", "Venue", "Time", "Reference", "Download"}
QUOTE_CHARS = 300


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def turns(text: str) -> list[tuple[str, str | None, int, int, str]]:
    """(name, role, start, end, quote) per speaker turn."""
    out = []
    for m in TURN.finditer(text):
        name = m.group("name").strip()
        if name.split()[0] in NOT_SPEAKERS or name.isupper():
            continue
        out.append((name, m.group("role"), m.start("text"), m.end("text"), m.group("text")))
    return out


def run(ctx: Ctx) -> int:
    since = (datetime.fromisoformat(ctx.now) - timedelta(days=3)).isoformat()
    made = 0
    for doc in graph.select(
        ctx.db, "documents", "COALESCE(published_at, valid_from) >= ?", (since,)
    ):
        if ctx.db.execute("SELECT 1 FROM statements WHERE document_id=? LIMIT 1", (doc["id"],)):
            continue
        for name, role, start, end, quote in turns(ctx.text_of(doc)):
            aid = slug(name)
            ctx.db.execute(
                "INSERT INTO actors(id,name,role) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET "
                "role=COALESCE(actors.role, excluded.role)",
                (aid, name, role),
            )
            sid = hashlib.sha256(f"{doc['id']}:{start}".encode()).hexdigest()[:32]
            ctx.db.execute(
                "INSERT OR IGNORE INTO statements(id,actor_id,document_id,text,start_char,end_char) "
                "VALUES(?,?,?,?,?,?)",
                (sid, aid, doc["id"], quote[:QUOTE_CHARS], start, end),
            )
            made += 1
    return made
