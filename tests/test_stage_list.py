"""config/pipeline.yaml `stages` is the one stage list (#156); guard it against the code and Terraform."""

import re
from pathlib import Path

from pipeline.run import STAGES, stage_names
from weft_core import config

ROOT = Path(__file__).resolve().parent.parent


def test_config_stages_match_runner() -> None:
    assert stage_names() == list(STAGES)


def test_needs_only_name_earlier_stages() -> None:
    seen: set[str] = set()
    for stage in config.pipeline()["stages"]:
        assert set(stage["needs"]) <= seen, stage["name"]
        seen.add(stage["name"])


def test_terraform_has_no_literal_stage_list() -> None:
    main = (ROOT / "infra/main.tf").read_text()
    assert re.search(r"stages\s*=\s*yamldecode\(file\(.*pipeline\.yaml", main)
    assert not re.search(r"stages\s*=\s*\[", main)


def test_connector_timeout_not_shorter_than_job() -> None:
    tf = (ROOT / "infra/modules/nightly/main.tf").read_text()
    assert "connector_timeout_s = local.job_timeout_s" in tf
    assert "timeout: ${local.connector_timeout_s}" in tf


def test_claims_failure_does_not_block_snapshot_or_notify() -> None:
    needs = {s["name"]: s["needs"] for s in config.pipeline()["stages"]}
    assert needs["snapshot"] == [] and needs["notify"] == []
