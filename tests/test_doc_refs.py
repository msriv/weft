"""Every `D<n>` decision referenced in code or docs exists in docs/decisions.md (#180)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP = {"node_modules", ".venv", ".next", ".git", "__pycache__", "design"}
SUFFIXES = {".py", ".ts", ".tsx", ".tf", ".yaml", ".yml", ".md"}


def test_referenced_decisions_exist() -> None:
    known = {
        int(n)
        for n in re.findall(r"^## D(\d+)\.", (ROOT / "docs/decisions.md").read_text(), re.MULTILINE)
    }
    assert known, "no decisions found"
    missing: dict[str, set[int]] = {}
    for f in ROOT.rglob("*"):
        if f.suffix not in SUFFIXES or SKIP & set(f.parts) or f.name == "decisions.md":
            continue
        for n in re.findall(r"\bD(\d{1,3})\b", f.read_text(errors="ignore")):
            if int(n) not in known:
                missing.setdefault(str(f.relative_to(ROOT)), set()).add(int(n))
    assert not missing, f"decisions referenced but not in docs/decisions.md: {missing}"
