"""Open questions (#111): what the coverage of a story leaves open, computed from the graph by fixed
rules, no model. Each question says what would change the picture and cites claim groups; it is
computed on every read, so it disappears as soon as that input appears in the graph.

Coverage language only (rule 1): a question never says which version is right.
"""

import re
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any

from weft_core import graph, store
from weft_core.store import Db

MAX = 10
ONE_SIDE_AFTER = timedelta(hours=48)
MIN_OUTLETS_FOR_SINGLE_ORIGIN = 3  # only ask "who else?" when others covered the event
MONTHS = [
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
]
_M = "|".join(MONTHS)
DATE = re.compile(rf"\b(?:(\d{{1,2}})\s+({_M})|({_M})\s+(\d{{1,2}}))\b", re.IGNORECASE)


def future_dates(text: str, today: date) -> list[date]:
    """Day-month dates in a sentence that fall after `today` in its year (no year means this one)."""
    out = []
    for m in DATE.finditer(text):
        d, mon = (m[1], m[2]) if m[1] else (m[4], m[3])
        try:
            when = date(today.year, MONTHS.index(mon.lower()) + 1, int(d))
        except ValueError:
            continue
        if when > today:
            out.append(when)
    return out


def open_questions(db: Db, story_id: str, now: datetime | None = None) -> list[dict[str, Any]]:
    now = now or datetime.now(UTC)
    events = graph.select(db, "events", "n.story_id=?", (story_id,))
    ev_ids = [e["id"] for e in events]
    if not ev_ids:
        return []
    groups = {g["id"]: g for g in graph.select(db, "claim_groups", "n.event_id IN ?", (ev_ids,))}
    reports = {r["id"]: r for r in graph.select(db, "reports", "n.story_id=?", (story_id,))}
    claims = graph.select(db, "claims", "n.event_id IN ?", (ev_ids,))
    outlets_of: dict[str, set[str]] = defaultdict(set)
    for c in claims:
        r = reports.get(c["report_id"])
        if c["group_id"] in groups and r:
            outlets_of[c["group_id"]].add(r["source_id"])
    event_outlets: dict[str, set[str]] = defaultdict(set)
    for r in reports.values():
        if r["event_id"]:
            event_outlets[r["event_id"]].add(r["source_id"])
    sides = set(store.beat_groups(db, story_id).values()) or {
        p["party"].upper()
        for p in db.execute(
            "MATCH (n:StoryParty {story_id: ?}) RETURN n.party AS party", (story_id,)
        )
        if re.fullmatch(r"[A-Za-z]{2}", p["party"])
    }
    out: list[dict[str, Any]] = []

    for c in graph.select(db, "conflicts", "n.event_id IN ?", (ev_ids,)):
        a, b = groups.get(c["group_a"]), groups.get(c["group_b"])
        if not a or not b:
            continue
        carrying = set(a["perspectives"]) | set(b["perspectives"])
        missing = sorted(sides - carrying)
        out.append(
            {
                "kind": "conflict",
                "event_id": c["event_id"],
                "question": f"Reports conflict on: “{a['label']}” versus “{b['label']}”.",
                "would_change": (
                    f"Reports from {', '.join(missing)} carrying either version, or an official "
                    "document on it."
                    if missing
                    else "An official document on it, or later reports carrying one version."
                ),
                "groups": [a["id"], b["id"]],
            }
        )

    cutoff = (now - ONE_SIDE_AFTER).isoformat()
    for g in groups.values():
        persp = [p for p in g["perspectives"] if p != "unattributed"]
        if len(persp) == 1 and len(sides) >= 2 and (g["valid_from"] or "") <= cutoff:
            out.append(
                {
                    "kind": "one_perspective",
                    "event_id": g["event_id"],
                    "question": f"Only outlets from {persp[0]} carry: “{g['label']}”.",
                    "would_change": "Reports from another perspective carrying it.",
                    "groups": [g["id"]],
                }
            )

    for gid, srcs in outlets_of.items():
        g = groups[gid]
        if len(srcs) == 1 and len(event_outlets[g["event_id"]]) >= MIN_OUTLETS_FOR_SINGLE_ORIGIN:
            out.append(
                {
                    "kind": "single_origin",
                    "event_id": g["event_id"],
                    "question": f"One outlet alone reports: “{g['label']}”.",
                    "would_change": "A second, independent outlet reporting it.",
                    "groups": [gid],
                }
            )

    today = now.date()
    seen: set[tuple[str, date]] = set()
    for c in claims:
        for when in future_dates(c["text"], today):
            if c["group_id"] in groups and (c["group_id"], when) not in seen:
                seen.add((c["group_id"], when))
                out.append(
                    {
                        "kind": "date_ahead",
                        "event_id": c["event_id"],
                        "question": f"Reports point to {when:%d %B}: “{c['text'][:200]}”.",
                        "would_change": f"Reports published after {when:%d %B}.",
                        "groups": [c["group_id"]],
                        "due": when.isoformat(),
                    }
                )

    order = {"conflict": 0, "date_ahead": 1, "one_perspective": 2, "single_origin": 3}
    return sorted(out, key=lambda q: order[q["kind"]])[:MAX]
