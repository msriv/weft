"""Model spend ledger and stored answers (#157). Lives in the graph store: no new datastore.

`ModelSpend` rows are keyed `day|caller` (tokens, cost_usd, calls). A caller is a service
("pipeline", "stream", "ask") or a per-beat scope such as "claims:story-id". `ModelOutput` rows
hold an answer by `template|input_hash`, so an identical call (temperature 0, fixed seed) is not paid for twice.
"""

from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from weft_core.store import Db

OUTPUT_DAYS = 30  # stored answers expire; the full input stays only in model_calls


class Ledger(Protocol):
    def spent(self, day: str, caller: str) -> tuple[int, float]: ...
    def add(self, day: str, caller: str, tokens: int, cost: float) -> None: ...
    def cached(self, key: str) -> str | None: ...
    def remember(self, key: str, output: str) -> None: ...


class GraphLedger:
    def __init__(self, db: Db) -> None:
        self._db = db

    def spent(self, day: str, caller: str) -> tuple[int, float]:
        rows = self._db.execute(
            "MATCH (n:ModelSpend {key: ?}) RETURN n.tokens AS tokens, n.cost_usd AS cost",
            (f"{day}|{caller}",),
        )
        return (int(rows[0]["tokens"] or 0), float(rows[0]["cost"] or 0.0)) if rows else (0, 0.0)

    def add(self, day: str, caller: str, tokens: int, cost: float) -> None:
        # One atomic statement, so parallel services add rather than overwrite.
        self._db.execute(
            "MERGE (n:ModelSpend {key: ?}) "
            "ON CREATE SET n.day = ?, n.caller = ?, n.tokens = 0, n.cost_usd = 0.0, n.calls = 0 "
            "SET n.tokens = n.tokens + ?, n.cost_usd = n.cost_usd + ?, n.calls = n.calls + 1",
            (f"{day}|{caller}", day, caller, tokens, cost),
        )

    def cached(self, key: str) -> str | None:
        rows = self._db.execute("MATCH (n:ModelOutput {key: ?}) RETURN n.output AS out", (key,))
        return str(rows[0]["out"]) if rows else None

    def remember(self, key: str, output: str) -> None:
        self._db.execute(
            "MERGE (n:ModelOutput {key: ?}) ON CREATE SET n.output = ?, n.at = ?",
            (key, output, datetime.now(UTC).isoformat()),
        )

    def prune(self, now: datetime | None = None) -> int:
        cut = ((now or datetime.now(UTC)) - timedelta(days=OUTPUT_DAYS)).isoformat()
        rows = self._db.execute(
            "MATCH (n:ModelOutput) WHERE n.at < ? DETACH DELETE n RETURN count(n) AS n", (cut,)
        )
        return int(rows[0]["n"]) if rows else 0


class MemoryLedger:
    """In-process ledger for tests and for runs without a graph."""

    def __init__(self) -> None:
        self.rows: dict[str, tuple[int, float]] = {}
        self.outputs: dict[str, str] = {}

    def spent(self, day: str, caller: str) -> tuple[int, float]:
        return self.rows.get(f"{day}|{caller}", (0, 0.0))

    def add(self, day: str, caller: str, tokens: int, cost: float) -> None:
        t, c = self.spent(day, caller)
        self.rows[f"{day}|{caller}"] = (t + tokens, c + cost)

    def cached(self, key: str) -> str | None:
        return self.outputs.get(key)

    def remember(self, key: str, output: str) -> None:
        self.outputs[key] = output


def limits(cfg: dict[str, Any], caller: str) -> tuple[int, float]:
    """This caller's share of the day's token and cost caps (config/pipeline.yaml `model_budget`)."""
    b = cfg["model_budget"]
    share = float(b["shares"][caller])
    return int(b["daily_tokens"] * share), float(b["daily_cost_usd"]) * share
