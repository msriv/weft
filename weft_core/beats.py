"""Beat matching: which beats a report belongs to, from its title, lede and entities."""

import re
from typing import Any

from weft_core import store


def matching(beats: list[dict[str, Any]], text: str) -> list[dict[str, Any]]:
    flat = " ".join(text.split())
    return [b for b in beats if any(re.search(p, flat, re.IGNORECASE) for p in b["patterns"])]


def ensure_story(db: store.Db, beat: dict[str, Any]) -> str:
    """One story per beat, created on first match. Its parties are the beat's proposed parties,
    stored without a citation (shown as unverified) until an admin confirms them."""
    story_id: str = beat["id"]
    if not db.execute("SELECT 1 FROM stories WHERE id=?", (story_id,)):
        store.create_story(db, story_id, beat["id"], beat["name"])
        for party in beat.get("parties", []):
            db.execute(
                "INSERT OR IGNORE INTO story_parties(story_id,party,citation) VALUES(?,?,NULL)",
                (story_id, party),
            )
    return story_id
