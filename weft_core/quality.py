"""Deterministic checks on extracted text, before a page becomes a report (#170). No model.

A page can answer 200 and still not be an article: a paywall stub, a consent or bot-check wall,
a "JavaScript required" shell, a soft 404, an index page, navigation text. Those are rejected with
a reason that goes in the `item_processed` log and the dashboard.
"""

import re
from typing import Any

from weft_core.textutil import sentences, words

_STOP = {"the", "and", "for", "with", "from", "that", "this", "are", "was", "has", "have", "its"}


def _content_words(s: str) -> set[str]:
    return {w for w in words(s) if len(w) > 3 and w not in _STOP}


def check(
    text: str,
    title: str | None,
    feed_title: str | None,
    sitename: str | None,
    lang: str | None,
    cfg: dict[str, Any],
) -> str | None:
    """None when the text looks like an article; else the reason: thin, stub or title."""
    sents = [text[s:e] for s, e in sentences(text)]
    if len(text.strip()) < cfg["min_chars"] or len(sents) < cfg["min_sentences"]:
        pats = _patterns(cfg, lang)
        # a short page that is mostly a stub message is a stub, not just thin
        if sents and pats and any(pats.search(x) for x in sents):
            return "stub"
        return "thin"
    pats = _patterns(cfg, lang)
    if pats and sum(1 for x in sents if pats.search(x)) / len(sents) >= cfg["stub_share"]:
        return "stub"
    t = (title or "").strip().lower()
    if not t or (sitename and t == sitename.strip().lower()):
        return "title"
    if feed_title and not (_content_words(t) & _content_words(feed_title)):
        return "title"
    return None


def _patterns(cfg: dict[str, Any], lang: str | None) -> "re.Pattern[str] | None":
    by_lang = cfg["stub_patterns"]
    ps = by_lang.get(lang or "en") or by_lang["en"]
    return re.compile("|".join(ps), re.IGNORECASE) if ps else None
