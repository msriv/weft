"""Nightly stage 3: numbers and quotes. Regex only, no model; every figure keeps its offsets.

shortcut: no dependency parse, a quote's speaker is the name after "said/says/told" or before it
in a quote-then-attribution pattern; add spaCy parsing when the labelled set shows misses.
"""

import hashlib
import re
from typing import Any

from pipeline.ctx import Ctx
from weft_core import graph

SCALE = {"thousand": 1e3, "million": 1e6, "billion": 1e9, "bn": 1e9, "m": 1e6, "k": 1e3}
NUM = re.compile(
    r"(?P<n>\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(?P<scale>thousand|million|billion|bn|k|m)?\b"
    r"\s*(?P<unit>%|percent|per cent|[A-Za-z][A-Za-z-]{2,})?",
    re.IGNORECASE,
)
SKIP_UNITS = {"the", "and", "was", "were", "for", "from", "that", "this", "with", "has", "had"}
MONTHS = {
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
}
QUOTE = re.compile(r"[“\"]([^”\"]{12,300})[”\"]")
SAID = re.compile(
    r"(?:(?:said|says|told|according to)\s+(?P<a>[A-Z][\w.'-]+(?:\s+[A-Z][\w.'-]+){0,3}))"
    r"|(?:(?P<b>[A-Z][\w.'-]+(?:\s+[A-Z][\w.'-]+){0,3})\s+(?:said|says|told|added|stated))"
)


def numbers(text: str) -> list[dict[str, Any]]:
    out = []
    for m in NUM.finditer(text):
        unit = (m.group("unit") or "").lower()
        if unit in MONTHS or unit in SKIP_UNITS or not unit:
            continue  # bare numbers and dates are not comparable quantities
        value = float(m.group("n").replace(",", ""))
        value *= SCALE.get((m.group("scale") or "").lower(), 1)
        unit = "percent" if unit in ("%", "per cent") else unit.rstrip("s")
        out.append(
            {"quantity": unit, "value": value, "unit": unit, "start": m.start(), "end": m.end()}
        )
    return out


def quotes(text: str) -> list[dict[str, Any]]:
    out = []
    for m in QUOTE.finditer(text):
        near = text[max(0, m.start() - 80) : m.end() + 80]
        s = SAID.search(near)
        speaker = (s.group("a") or s.group("b")) if s else None
        out.append({"text": m.group(1), "speaker": speaker, "start": m.start(), "end": m.end()})
    return out


def run(ctx: Ctx) -> int:
    made = 0
    for r in ctx.recent_reports(2):
        if ctx.db.execute(
            "SELECT 1 FROM figures WHERE report_id=? AND valid_to IS NULL LIMIT 1", (r["id"],)
        ):
            continue
        text = ctx.text_of(r)
        rows = [("number", f, text[f["start"] : f["end"]]) for f in numbers(text)] + [
            ("quote", q, q["text"]) for q in quotes(text)
        ]
        for kind, f, span in rows:
            graph.put(
                ctx.db,
                "figures",
                {
                    "id": hashlib.sha256(f"{r['id']}:{kind}:{f['start']}".encode()).hexdigest()[
                        :32
                    ],
                    "report_id": r["id"],
                    "event_id": r["event_id"],
                    "kind": kind,
                    "quantity": f.get("quantity"),
                    "value": f.get("value"),
                    "unit": f.get("unit"),
                    "speaker": f.get("speaker"),
                    "text": span[:300],
                    "start_char": f["start"],
                    "end_char": f["end"],
                },
            )
            made += 1
    return made
