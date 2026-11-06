"""What every nightly stage gets. Stages are pure functions over rows (D18): they read and write
their own tables through `weft_core.graph` and can be re-run alone."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from weft_core import graph, store
from weft_core.models import ModelClient
from weft_core.nlp import Nlp


class Budget:
    """Token budget per beat per night. Stages degrade (skip optional model calls) rather than
    overspend. Tokens are estimated as characters / 4."""

    def __init__(self, tokens: int) -> None:
        self.left = tokens

    def take(self, text: str) -> bool:
        cost = len(text) // 4 + 1
        if cost > self.left:
            return False
        self.left -= cost
        return True


@dataclass
class Ctx:
    db: store.Db
    cfg: dict[str, Any]  # config/pipeline.yaml
    nlp: Nlp
    text_of: Callable[[dict[str, Any]], str]  # report -> extracted text (from the raw copy)
    model: ModelClient | None = None
    now: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    budgets: dict[str, Budget] = field(default_factory=dict)

    def budget(self, story_id: str) -> Budget:
        return self.budgets.setdefault(
            story_id, Budget(self.cfg["nightly"]["token_budget_per_beat"])
        )

    def recent_reports(self, days: int) -> list[dict[str, Any]]:
        from datetime import timedelta

        since = (datetime.fromisoformat(self.now) - timedelta(days=days)).isoformat()
        return graph.select(
            self.db,
            "reports",
            "story_id IS NOT NULL AND COALESCE(published_at, fetched_at) >= ?",
            (since,),
        )
