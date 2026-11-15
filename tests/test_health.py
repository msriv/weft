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


def test_health_window_gives_the_same_unhealthy_set() -> None:
    from services.poller.main import HEALTH_WINDOW_DAYS, health_query

    assert f"INTERVAL {HEALTH_WINDOW_DAYS} DAY" in health_query("p.weft.source_health")
    rows = [  # (source, checked_at, ok)
        ("good", NOW - timedelta(minutes=5), True),
        ("old-ok-failing-now", NOW - timedelta(days=40), True),
        ("old-ok-failing-now", NOW - timedelta(minutes=5), False),
        ("never", NOW - timedelta(minutes=5), False),
    ]

    def last_ok(days: int) -> dict[str, datetime | None]:
        out: dict[str, datetime | None] = {}
        for src, at, ok in rows:
            if NOW - at <= timedelta(days=days):
                out.setdefault(src, None)
                if ok:
                    out[src] = at
        return out

    assert unhealthy(last_ok(HEALTH_WINDOW_DAYS), NOW) == unhealthy(last_ok(365), NOW)
