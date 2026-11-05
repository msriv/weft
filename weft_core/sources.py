"""Source registry: loads and validates config/sources/*.yaml."""

import json
from pathlib import Path
from typing import Any

import jsonschema
import yaml

SOURCES_DIR = Path(__file__).resolve().parents[1] / "config" / "sources"


def validate_file(path: Path, schema: dict[str, Any]) -> list[str]:
    """Return human-readable errors for one registry file (a list of entries)."""
    entries = yaml.safe_load(path.read_text())
    if not isinstance(entries, list):
        return [f"{path}: top level must be a list of sources"]
    validator = jsonschema.Draft202012Validator(schema)
    errors = []
    for i, entry in enumerate(entries):
        label = entry.get("id", f"#{i}") if isinstance(entry, dict) else f"#{i}"
        errors += [f"{path}: {label}: {e.message}" for e in validator.iter_errors(entry)]
    ids = [e["id"] for e in entries if isinstance(e, dict) and "id" in e]
    errors += [f"{path}: duplicate id {i}" for i in sorted({i for i in ids if ids.count(i) > 1})]
    return errors


def load_schema(sources_dir: Path = SOURCES_DIR) -> dict[str, Any]:
    schema: dict[str, Any] = json.loads((sources_dir / "schema.json").read_text())
    return schema


def validate_all(sources_dir: Path = SOURCES_DIR) -> list[str]:
    """Validate every *.yaml (including _example.yaml) and check ids are unique across files."""
    schema = load_schema(sources_dir)
    errors: list[str] = []
    seen: dict[str, Path] = {}
    for path in sorted(sources_dir.glob("*.yaml")):
        errors += validate_file(path, schema)
        if path.name.startswith("_"):
            continue
        for e in yaml.safe_load(path.read_text()):
            if isinstance(e, dict) and e.get("id") in seen:
                errors.append(f"{path}: id {e['id']} already defined in {seen[e['id']]}")
            elif isinstance(e, dict) and "id" in e:
                seen[e["id"]] = path
    return errors


def load_sources(sources_dir: Path = SOURCES_DIR) -> list[dict[str, Any]]:
    """Load all real sources (files starting with `_` are examples). Raises on invalid config."""
    errors = validate_all(sources_dir)
    if errors:
        raise ValueError("invalid source registry:\n" + "\n".join(errors))
    out: list[dict[str, Any]] = []
    for path in sorted(sources_dir.glob("*.yaml")):
        if not path.name.startswith("_"):
            out += yaml.safe_load(path.read_text())
    return out


if __name__ == "__main__":
    problems = validate_all()
    print("\n".join(problems) or "source registry OK")
    raise SystemExit(1 if problems else 0)
