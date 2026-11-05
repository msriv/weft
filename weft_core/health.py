"""Feed health: a source is unhealthy when it has had no successful poll for too long.

Downstream rules (omission, silence) must not fire on unhealthy feeds, so this is the
single definition of "unhealthy".
"""

from datetime import datetime, timedelta

MAX_AGE = timedelta(hours=6)  # feeds poll every 5-15 min; 6 h of nothing is an outage


def unhealthy(
    last_ok: dict[str, datetime | None], now: datetime, max_age: timedelta = MAX_AGE
) -> list[str]:
    """Source ids with no success within max_age. None means polled but never succeeded."""
    return sorted(s for s, t in last_ok.items() if t is None or now - t > max_age)
