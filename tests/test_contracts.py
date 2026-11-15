"""The system is described three times: the code, Terraform and the local compose setup. These
tests fail when the descriptions drift apart (#173). Static scans, no cloud calls."""

import json
import re
from dataclasses import fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from services.fetcher.fetcher import fetch_item
from services.poller.main import health_rows
from tests.test_fetcher import HTML, MSG, SRC, MemStore
from weft_core.models import ModelCall, as_row
from weft_core.polite import PoliteClient

ROOT = Path(__file__).resolve().parent.parent
SCHEMAS = ROOT / "infra/modules/bigquery/schemas"


def schema(table: str) -> dict[str, str]:
    return {c["name"]: c["mode"] for c in json.loads((SCHEMAS / f"{table}.json").read_text())}


def check_row(table: str, row: dict[str, object]) -> None:
    cols = schema(table)
    assert set(row) <= set(cols), f"{table}: not in the schema: {sorted(set(row) - set(cols))}"
    required = {c for c, mode in cols.items() if mode == "REQUIRED"}
    assert not required - {k for k, v in row.items() if v is not None}, (
        f"{table}: required columns missing or null: {sorted(required - set(row))}"
    )


def test_rows_the_code_writes_match_the_bigquery_schemas() -> None:
    store = MemStore()
    http = PoliteClient(
        httpx.Client(
            transport=httpx.MockTransport(
                lambda r: (
                    httpx.Response(404)
                    if r.url.path == "/robots.txt"
                    else httpx.Response(200, text=HTML)
                )
            )
        ),
        sleep=lambda s: None,
    )
    assert fetch_item(MSG, SRC, http, store).status == "stored"
    raw, extracted, _ = store.rows[0]
    check_row("raw_items", raw)
    check_row("extracted_items", extracted)
    for row in health_rows({"a": None, "b": "boom"}, datetime.now(UTC)):
        check_row("source_health", row)


def test_every_model_call_field_is_a_model_calls_column() -> None:
    cols = schema("model_calls")
    missing = {f.name for f in fields(ModelCall)} - set(cols)
    assert not missing, f"ModelCall fields without a model_calls column: {sorted(missing)}"
    values: dict[str, Any] = {f.name: _sample(f.type) for f in fields(ModelCall)}
    call = ModelCall(**values)
    check_row("model_calls", as_row(call))


def _sample(t: object) -> object:
    name = str(t)
    if "int" in name:
        return 1
    if "float" in name:
        return 0.5
    if "bool" in name:
        return True
    return "x"


def grab(pattern: str, text: str, group: int = 1) -> str:
    m = re.search(pattern, text, re.DOTALL)
    assert m, f"no match for {pattern}"
    return m.group(group)


def _tf(*parts: str) -> str:
    return "\n".join(
        p.read_text()
        for p in sorted((ROOT / "infra").rglob("*.tf"))
        if not parts or any(x in str(p) for x in parts)
    )


def test_local_pubsub_matches_terraform() -> None:
    tf_topics = set(re.findall(r'"([a-z-]+)"', grab(r"toset\(\[(.*?)\]\)", _tf("messaging"))))
    local = (ROOT / "local/init.py").read_text()
    local_topics = set(re.findall(r'"([a-z-]+)"', grab(r"for t in \((.*?)\)\n", local)))
    assert tf_topics == local_topics

    # subscriptions: name -> topic. Terraform names the service "weft-<name>".
    main = (ROOT / "infra/main.tf").read_text()
    tf_subs = {"fetcher": "items-new"}
    stream = grab(r'module "stream_worker" \{(.*?)\n\}', main)
    name = grab(r'name\s*=\s*"([^"]+)"', stream).removeprefix("weft-")
    tf_subs[name] = grab(r'push_topic\s*=\s*module\.messaging\.topic_names\["([^"]+)"\]', stream)
    extra = r'(\w+)\s*=\s*\{\s*topic\s*=\s*module\.messaging\.topic_names\["([^"]+)"\]'
    for key, topic in re.findall(extra, stream):
        tf_subs[f"{name}-{key}"] = topic
    local_subs = dict(re.findall(r'\("([a-z-]+)", "([a-z-]+)", "http', local))
    assert tf_subs == local_subs


# Variables set by the platform, or only read in tools that run by hand.
PLATFORM = {"K_SERVICE", "PORT", "HOME"}


def test_every_required_env_var_is_set_by_terraform_and_compose() -> None:
    keys: dict[str, str] = {}
    for d in ("services", "pipeline", "weft_core"):
        for f in (ROOT / d).rglob("*.py"):
            for k in re.findall(r'os\.environ\["([A-Z0-9_]+)"\]', f.read_text()):
                keys.setdefault(k, str(f.relative_to(ROOT)))
    images = "\n".join(f.read_text() for f in ROOT.rglob("Dockerfile") if ".venv" not in str(f))
    tf = _tf() + images  # an `ENV X=...` baked into an image counts for both
    compose = (ROOT / "docker-compose.yml").read_text() + images
    # The Terraform side is a text scan of the key as an environment name; secrets are set by
    # their `<NAME> = ...secret_id` entries, buckets and topics by per-module env maps.

    def present(k: str, text: str) -> bool:
        return re.search(rf"\b{k}\b", text) is not None

    bad = {
        k: f
        for k, f in keys.items()
        if k not in PLATFORM and not (present(k, tf) and present(k, compose))
    }
    assert not bad, (
        f"env vars read with os.environ[...] but not set in Terraform and compose: {bad}"
    )


def test_removing_a_schema_field_would_fail() -> None:
    with pytest.raises(AssertionError):
        check_row("raw_items", {"item_id": "x", "no_such_column": 1})
