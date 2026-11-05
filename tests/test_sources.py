import json
from pathlib import Path

import pytest
import yaml

from weft_core.sources import SOURCES_DIR, load_sources, validate_all


def _write(tmp_path: Path, entries: list[dict[str, object]], name: str = "a.yaml") -> Path:
    (tmp_path / "schema.json").write_text((SOURCES_DIR / "schema.json").read_text())
    (tmp_path / name).write_text(yaml.safe_dump(entries))
    return tmp_path


GOOD: dict[str, object] = {
    "id": "x-news", "name": "X", "homepage": "https://x.test", "country": "AL",
    "languages": ["al"], "type": "news", "state_run": False, "feeds": ["https://x.test/rss"],
    "rate_limit": {"requests": 1, "per_seconds": 10}, "paywalled": False,
}  # fmt: skip


def test_repo_registry_is_valid() -> None:
    assert validate_all() == []


def test_schema_is_valid_json() -> None:
    json.loads((SOURCES_DIR / "schema.json").read_text())


def test_good_entry_loads(tmp_path: Path) -> None:
    assert load_sources(_write(tmp_path, [GOOD]))[0]["id"] == "x-news"


@pytest.mark.parametrize(
    "patch",
    [
        {"owner_id": "grp"},  # owner without cited source
        {"state_run": True},  # state-run without cited source
        {"type": "tabloid"},
        {"feeds": None},  # no way to ingest
    ],
)
def test_bad_entries_rejected(tmp_path: Path, patch: dict[str, object]) -> None:
    entry = {**GOOD, **patch}
    entry = {k: v for k, v in entry.items() if v is not None}
    assert validate_all(_write(tmp_path, [entry]))


def test_duplicate_id_across_files(tmp_path: Path) -> None:
    _write(tmp_path, [GOOD])
    (tmp_path / "b.yaml").write_text(yaml.safe_dump([GOOD]))
    assert any("already defined" in e for e in validate_all(tmp_path))
