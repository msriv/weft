"""Spend ledger over the real graph store (#157)."""

from datetime import UTC, datetime, timedelta

from pipeline.ctx import Budget
from weft_core import graph
from weft_core.ledger import GraphLedger, limits
from weft_core.store import local_db


def ledger() -> GraphLedger:
    d = local_db()
    graph.init(d)
    return GraphLedger(d)


def test_spend_adds_up_per_day_and_caller() -> None:
    led = ledger()
    led.add("2026-01-01", "t-ledger", 100, 0.01)
    led.add("2026-01-01", "t-ledger", 50, 0.02)
    assert led.spent("2026-01-01", "t-ledger") == (150, 0.03)
    assert led.spent("2026-01-02", "t-ledger") == (0, 0.0)


def test_stored_answers_expire() -> None:
    led = ledger()
    led.remember("t-key", "answer")
    assert led.cached("t-key") == "answer"
    assert led.prune(datetime.now(UTC) + timedelta(days=31)) >= 1
    assert led.cached("t-key") is None


def test_budget_starts_from_tokens_already_spent_today() -> None:
    led = ledger()
    day = datetime.now(UTC).date().isoformat()
    led.add(day, "claims:t-story", 900, 0.0)
    assert Budget(1000, led, "claims:t-story").left == 100  # a re-run is not a fresh budget
    assert Budget(1000, led, "claims:other").left == 1000


def test_limits_split_by_share() -> None:
    cfg = {"model_budget": {"daily_tokens": 1000, "daily_cost_usd": 10.0, "shares": {"ask": 0.1}}}
    assert limits(cfg, "ask") == (100, 1.0)
