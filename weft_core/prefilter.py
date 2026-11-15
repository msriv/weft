"""Cheap beat check on a feed entry's title and summary, before anything is fetched (#163).

Lexical only, no model and no embedding: an entry passes when any beat's patterns match and none
of that beat's exclusions do. The stream worker stays the real gate; this only keeps clearly
off-beat articles from being downloaded, stored and embedded. Entries with no title and no
summary (sitemap entries) always pass.
"""

import random
from typing import Any

from weft_core import beats as beats_mod


def on_beat(all_beats: list[dict[str, Any]], title: str | None, summary: str | None) -> bool:
    text = f"{title or ''}. {summary or ''}".strip(". ")
    if not text:
        return True
    return bool(beats_mod.matching(all_beats, text))


def decide(
    all_beats: list[dict[str, Any]],
    title: str | None,
    summary: str | None,
    sample_rate: float,
    rng: random.Random,
) -> str:
    """'publish', 'sample' (off-beat but kept to see what the beats miss) or 'skip'."""
    if on_beat(all_beats, title, summary):
        return "publish"
    return "sample" if rng.random() < sample_rate else "skip"
