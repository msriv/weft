"""Beat matching: which beats a report belongs to, from its title, lede and entities."""

import re
from typing import Any

from weft_core import store


def matches(beat: dict[str, Any], text: str) -> bool:
    """Any pattern matches and no exclusion does."""
    flat = " ".join(text.split())

    def hit(ps: list[str]) -> bool:
        return any(re.search(p, flat, re.IGNORECASE) for p in ps)

    return hit(beat["patterns"]) and not hit(beat.get("exclude") or [])


def matching(beats: list[dict[str, Any]], text: str) -> list[dict[str, Any]]:
    return [b for b in beats if matches(b, text)]


def ensure_story(db: store.Db, beat: dict[str, Any]) -> str:
    """One story per beat, created on first match. Its parties are the beat's proposed parties,
    stored without a citation (shown as unverified) until an admin confirms them."""
    story_id: str = beat["id"]
    if not store.get_story(db, story_id):
        store.create_story(db, story_id, beat["id"], beat["name"])
        for party in beat.get("parties", []):
            db.execute("MERGE (n:StoryParty {story_id: ?, party: ?})", (story_id, party))
    return story_id
