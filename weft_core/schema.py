"""Which node labels and properties the code's Cypher uses, checked against `store.NODES` (#148).

`NODES` is the schema of record. `tests/test_schema.py` fails when a Cypher string in the code
uses a label or a `var.prop` that `NODES` does not declare, and when a label or property leaves
`NODES` without an entry in `config/schema_retired.yaml`. Autoclean applies those entries.
"""

import ast
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from weft_core import config, store

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ("weft_core", "pipeline", "services")
LOCK = config.CONFIG / "schema.lock"

_CYPHER = re.compile(r"\b(MATCH|MERGE|CREATE)\b[^()]*\(\w*:[A-Z]")
_NODE = re.compile(r"\((\w*)((?::\w+)+)\s*(?:\{([^}]*)\})?")
_PROP = re.compile(r"\b([a-z]\w*)\.([a-z_]\w*)\b(?!\s*\()")
_KEY = re.compile(r"(\w+)\s*:")


def cypher_strings() -> Iterator[tuple[str, int, str]]:
    """(file, line, text) of every string literal in the code that looks like Cypher. An f-string
    is read with its `{...}` parts blanked out, so a dynamic label is simply not checked."""
    for d in SOURCES:
        for path in sorted((ROOT / d).rglob("*.py")):
            for node in ast.walk(ast.parse(path.read_text())):
                text = None
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    text = node.value
                elif isinstance(node, ast.JoinedStr):
                    text = "".join(
                        str(v.value) if isinstance(v, ast.Constant) else "{}" for v in node.values
                    )
                if text and _CYPHER.search(text):
                    yield str(path.relative_to(ROOT)), getattr(node, "lineno", 0), text


def uses(query: str) -> tuple[set[str], set[tuple[str, str]]]:
    """(labels, (label, property) pairs) a query touches. A variable with several labels
    (`n:Report OR n:Document`) is checked against any of them."""
    labels: set[str] = set()
    by_var: dict[str, set[str]] = {}
    props: set[tuple[str, str]] = set()
    for var, lab, body in _NODE.findall(query):
        ls = [x for x in lab.split(":") if x]
        labels |= set(ls)
        if var:
            by_var.setdefault(var, set()).update(ls)
        for key in _KEY.findall(body or ""):
            props |= {(label, key) for label in ls}
    for m in re.finditer(r"\b([a-z]\w*):([A-Z]\w*)\b", query):  # `n:Report` outside a pattern
        labels.add(m.group(2))
        by_var.setdefault(m.group(1), set()).add(m.group(2))
    for var, prop in _PROP.findall(query):
        for label in by_var.get(var, ()):
            props.add((label, prop))
    return labels, props


# Set and removed in one statement (review.py), so it never exists on a stored node.
TRANSIENT = {("ReviewItem", "new")}


def violations() -> list[str]:
    out = []
    for path, line, q in cypher_strings():
        labels, props = uses(q)
        for lab in sorted(labels - set(store.NODES)):
            out.append(f"{path}:{line} label {lab} is not in store.NODES")
        for lab in {p[0] for p in props if p[0] in store.NODES}:
            ok = {p for p in props if p[0] == lab}
            for _, prop in sorted(ok):
                if (
                    prop not in store.NODES[lab]
                    and (lab, prop) not in TRANSIENT
                    and not _bound_elsewhere(q, lab, prop)
                ):
                    out.append(f"{path}:{line} {lab}.{prop} is not in store.NODES")
    return sorted(set(out))


def _bound_elsewhere(query: str, label: str, prop: str) -> bool:
    """A property used on a variable that carries several labels is fine when any declares it."""
    for var, lab, _ in _NODE.findall(query):
        ls = {x for x in lab.split(":") if x}
        if var and label in ls and any(prop in store.NODES.get(x, {}) for x in ls):
            return True
    return False


def declared() -> dict[str, list[str]]:
    return {label: sorted(props) for label, props in sorted(store.NODES.items())}


def lock_text() -> str:
    import json

    return json.dumps(declared(), indent=1, sort_keys=True) + "\n"


def retired() -> list[dict[str, Any]]:
    return list(config.load("schema_retired.yaml").get("retired") or [])


def missing_retirements(
    old: dict[str, list[str]], new: dict[str, list[str]], entries: list[dict[str, Any]]
) -> list[str]:
    """Labels and properties in `old` (the committed lock) that `new` (NODES) no longer declares
    and that no `schema_retired.yaml` entry covers."""
    gone = []
    for label, props in old.items():
        if label not in new:
            if not any(e["label"] == label and "property" not in e for e in entries):
                gone.append(label)
            continue
        for prop in set(props) - set(new[label]):
            if not any(e["label"] == label and e.get("property") in (None, prop) for e in entries):
                gone.append(f"{label}.{prop}")
    return sorted(gone)


def write_lock() -> int:
    import json

    old = json.loads(LOCK.read_text()) if LOCK.exists() else {}
    if gone := missing_retirements(old, declared(), retired()):
        print("Removed from store.NODES without an entry in config/schema_retired.yaml:")
        print("\n".join(f"  {g}" for g in gone))
        return 1
    LOCK.write_text(lock_text())
    return 0


if __name__ == "__main__":  # `python -m weft_core.schema` regenerates config/schema.lock
    raise SystemExit(write_lock())
