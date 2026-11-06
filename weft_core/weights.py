"""Source weight: a fixed formula over the six factors on How we weigh.

Weight only changes the order things appear in (rule 6). It never scores whether an outlet was
right, only how it reports. A factor with no data is left out of the mean, and a source with too
few reports gets the neutral weight and is marked "insufficient data".
"""

from typing import Any

FACTORS = (
    "names_sources",
    "links_documents",
    "corrects_openly",
    "silent_edits",
    "copied_wording",
    "opinion_share",
)


def compute(
    factors: dict[str, float | None], source_type: str, n_reports: int, cfg: dict[str, Any]
) -> tuple[float, bool]:
    """(weight in 0..1, insufficient_data). `factors` holds shares in 0..1 or None."""
    w = cfg["weights"]
    parts = [
        f if name in w["raises"] else 1 - f
        for name in FACTORS
        if (f := factors.get(name)) is not None
    ]
    if n_reports < w["min_reports"] or not parts:
        return float(w["neutral"]), True
    mult = w["type_multiplier"].get(source_type, 1.0)
    return round(mult * sum(parts) / len(parts), 4), False
