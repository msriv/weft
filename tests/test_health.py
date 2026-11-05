from datetime import UTC, datetime, timedelta

from weft_core.health import unhealthy

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_unhealthy_sources() -> None:
    last_ok = {
        "fresh": NOW - timedelta(minutes=10),
        "stale": NOW - timedelta(hours=7),
        "never": None,
        "edge": NOW - timedelta(hours=6),  # exactly at the limit is still healthy
    }
    assert unhealthy(last_ok, NOW) == ["never", "stale"]
