"""Schema drift (#148): NODES is the schema of record."""

import json
from typing import Any

from tests.test_autoclean import NOW, apply_cfg
from weft_core import autoclean as ac
from weft_core import autoclean_rules, schema, store  # noqa: F401
from weft_core.store import local_db


def test_every_label_and_property_the_cypher_uses_is_declared() -> None:
    assert schema.violations() == []


def test_the_checker_fails_on_an_undeclared_label_and_property() -> None:
    labels, props = schema.uses("MATCH (n:Ghost {a: ?}) WHERE n.b = 1 RETURN n")
    assert labels == {"Ghost"} and props == {("Ghost", "a"), ("Ghost", "b")}
    _, props = schema.uses("MATCH (r:Report) WHERE r.nope = 1 RETURN r")
    assert ("Report", "nope") in props and "nope" not in store.NODES["Report"]
    labels, _ = schema.uses("MATCH (n) WHERE (n:Report OR n:Document) RETURN n")
    assert labels == {"Report", "Document"}  # a label test outside a pattern counts too


def test_lock_matches_nodes() -> None:
    assert schema.LOCK.read_text() == schema.lock_text(), "run: python -m weft_core.schema"


def test_a_removed_name_needs_a_retired_entry() -> None:
    old = {"Foo": ["a", "b"], "Bar": ["x"]}
    new = {"Foo": ["a"]}
    assert schema.missing_retirements(old, new, []) == ["Bar", "Foo.b"]
    entries = [
        {"label": "Foo", "property": "b", "action": "delete"},
        {"label": "Bar", "action": "delete"},
    ]
    assert schema.missing_retirements(old, new, entries) == []


def test_retired_entries_are_well_formed() -> None:
    for e in schema.retired():
        assert e["action"] in ("delete", "rename_to") and e["pr"]
        assert (e["action"] != "rename_to") or ("property" in e and e["to"])
        assert "property" in e or e["label"] not in store.NODES  # a label deleted is a label gone


def _db() -> Any:
    d = local_db()
    return d


def run(d: Any, *names: str, **extra: Any) -> dict[str, dict[str, Any]]:
    recs = ac.run_all(d, NOW, cfg=apply_cfg(*names, **extra))
    return {r["rule"]: r for r in recs}


def test_rename_moves_the_value_and_removes_the_old_key_and_a_second_run_is_a_noop(
    monkeypatch: Any,
) -> None:
    d = _db()
    d.execute(
        "CREATE (:Beat {id: 'b1', old_name: 'x'}), (:Beat {id: 'b2', old_name: 'y', name: 'keep'})"
    )
    d.execute("CREATE (:Beat {id: 'b3', name: 'untouched'})")
    entries = [
        {"label": "Beat", "property": "old_name", "action": "rename_to", "to": "name", "pr": 1}
    ]
    monkeypatch.setattr(schema, "retired", lambda: entries)
    d.execute(
        "CREATE (:BatchRun {run_id: 's', stage: 'snapshot', status: 'ok', started_at: ?, ended_at: ?})",
        (NOW.isoformat(), NOW.isoformat()),
    )
    first = run(d, "retired_schema")["retired_schema"]
    assert first["changed"] == 2
    rows = {
        r["id"]: r
        for r in d.execute("MATCH (n:Beat) RETURN n.id AS id, n.name AS name, n.old_name AS old")
    }
    assert rows["b1"]["name"] == "x" and rows["b2"]["name"] == "keep"  # an existing value wins
    assert all(r["old"] is None for r in rows.values()) and rows["b3"]["name"] == "untouched"
    assert run(d, "retired_schema")["retired_schema"]["changed"] == 0


def test_retired_label_is_deleted_only_after_a_good_snapshot(monkeypatch: Any) -> None:
    d = _db()
    d.execute("CREATE (:OldThing {id: 1}), (:OldThing {id: 2}), (:Beat {id: 'b'})")
    monkeypatch.setattr(
        schema, "retired", lambda: [{"label": "OldThing", "action": "delete", "pr": 1}]
    )
    assert run(d, "retired_schema")["retired_schema"]["status"] == "skipped"
    assert d.execute("MATCH (n:OldThing) RETURN count(n) AS n")[0]["n"] == 2
    d.execute(
        "CREATE (:BatchRun {run_id: 's', stage: 'snapshot', status: 'ok', started_at: ?, ended_at: ?})",
        (NOW.isoformat(), NOW.isoformat()),
    )
    assert run(d, "retired_schema")["retired_schema"]["changed"] == 2
    assert d.execute("MATCH (n:Beat) RETURN count(n) AS n")[0]["n"] == 1  # neighbour kept


def test_undeclared_schema_reports_leftovers_and_deletes_nothing(monkeypatch: Any) -> None:
    d = _db()
    d.execute("CREATE (:Leftover {a: 1}), (:Beat {id: 'b', stray: 1, name: 'n'})")
    monkeypatch.setattr(schema, "retired", list)
    r = run(d, "undeclared_schema")["undeclared_schema"]
    assert {"Leftover", "Beat.stray"} <= set(json.loads(r["sample_ids"]))
    assert "Beat.name" not in json.loads(r["sample_ids"])
    assert (
        d.execute("MATCH (n) WHERE n:Leftover OR n.stray IS NOT NULL RETURN count(n) AS n")[0]["n"]
        == 2
    )
    monkeypatch.setattr(
        schema, "retired", lambda: [{"label": "Leftover", "action": "delete", "pr": 1}]
    )
    again = run(d, "undeclared_schema")["undeclared_schema"]
    assert "Leftover" not in json.loads(again["sample_ids"])  # retired: the other rule owns it


def test_stale_index_is_reported_and_dropped_expected_ones_stay() -> None:
    d = _db()
    d.execute("CREATE INDEX stale_idx IF NOT EXISTS FOR (n:Report) ON (n.title)")
    r = run(d, "stale_indexes")["stale_indexes"]
    assert r["matched"] == 1 and r["changed"] == 1 and json.loads(r["sample_ids"]) == ["stale_idx"]
    names = {x["name"] for x in d.execute("SHOW INDEXES YIELD name RETURN name")}
    assert "stale_idx" not in names
    assert run(d, "stale_indexes")["stale_indexes"]["matched"] == 0
