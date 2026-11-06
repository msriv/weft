"""Eval gate. Fails when a score is below the baseline, or when a prompt template version in code
no longer matches the version the baseline was measured with. To ship a changed prompt or model:
run `python -m evals.run --live`, check the scores, then update evals/baseline.json in the same PR.
"""

import json
import re
import sys
from pathlib import Path
from typing import Any

from evals.run import HERE, run_all

ROOT = HERE.parent
PROMPT = re.compile(r'"([a-z][a-z-]+@\d+)"')


def prompt_versions() -> list[str]:
    found: set[str] = set()
    for d in ("weft_core", "pipeline", "services"):
        for f in (ROOT / d).rglob("*.py"):
            found.update(PROMPT.findall(f.read_text()))
    return sorted(found)


def check(
    baseline: dict[str, Any], scores: dict[str, dict[str, float]], prompts: list[str]
) -> list[str]:
    errors = []
    if sorted(baseline["prompts"]) != prompts:
        errors.append(f"prompt versions changed: baseline {baseline['prompts']} vs code {prompts}")
    want: dict[str, dict[str, float]] = baseline["scores"]
    for task, metrics in want.items():
        for m, floor in metrics.items():
            got = scores.get(task, {}).get(m)
            if got is None or got + 1e-9 < floor:
                errors.append(f"{task}.{m}: {got} is below baseline {floor}")
    return errors


def main(path: Path = HERE / "baseline.json") -> int:
    errors = check(json.loads(path.read_text()), run_all(), prompt_versions())
    for e in errors:
        print("EVAL GATE:", e, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
