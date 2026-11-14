"""What every nightly stage gets. Stages are pure functions over rows (D18): they read and write
their own tables through `weft_core.graph` and can be re-run alone."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from weft_core import config, graph, models, store
from weft_core.ledger import Ledger
from weft_core.models import ModelClient
from weft_core.nlp import Nlp


class Budget:
    """Token budget per beat per night. Stages degrade (skip optional model calls) rather than
    overspend. With a ledger, tokens already spent today under `scope` (real usage from the
    provider) are subtracted at the start, so a re-run or a restart does not get a fresh budget;
    inside one process a call is reserved at characters / 4 before it is made."""

    def __init__(self, tokens: int, ledger: Ledger | None = None, scope: str | None = None) -> None:
        self.scope = scope
        if ledger and scope:
            day = datetime.now(UTC).date().isoformat()
            tokens -= ledger.spent(day, scope)[0]
        self.left = tokens

    def take(self, text: str) -> bool:
        cost = len(text) // 4 + 1
        if cost > self.left:
            return False
        self.left -= cost
        models.scope.set(self.scope)  # the client charges the real usage of the next call here
        return True


@dataclass
class Ctx:
    db: store.Db
    cfg: dict[str, Any]  # config/pipeline.yaml
    nlp: Nlp
    text_of: Callable[[dict[str, Any]], str]  # report -> extracted text (from the raw copy)
    model: ModelClient | None = None
    now: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    versions_of: Callable[[str], list[tuple[datetime, str]]] = lambda report_id: []
    rules: dict[str, Any] = field(default_factory=config.rules)  # config/rules.yaml
    budgets: dict[str, Budget] = field(default_factory=dict)
    ledger: Ledger | None = None  # spend ledger (#157); None in tests

    def budget(self, story_id: str, stage: str = "claims") -> Budget:
        """Each stage has its own share of the beat's nightly tokens, so an early stage
        (regroup) can never starve claim extraction."""
        n = self.cfg["nightly"]
        share = n.get("token_shares", {}).get(stage, 1.0)
        return self.budgets.setdefault(
            f"{stage}:{story_id}",
            Budget(int(n["token_budget_per_beat"] * share), self.ledger, f"{stage}:{story_id}"),
        )

    def recent_reports(self, days: int) -> list[dict[str, Any]]:
        from datetime import timedelta

        since = (datetime.fromisoformat(self.now) - timedelta(days=days)).isoformat()
        return graph.select(
            self.db,
            "reports",
            "n.story_id IS NOT NULL AND coalesce(n.published_at, n.fetched_at) >= ?",
            (since,),
        )
